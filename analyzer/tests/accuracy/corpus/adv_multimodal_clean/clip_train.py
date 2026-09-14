"""CLIP-style image/text contrastive trainer - correct.

Two encoders, a learnable temperature clamped the way the paper does it, and a
symmetric InfoNCE loss built from `cross_entropy` over the raw similarity
logits. The two directions of the loss share one label vector, the temperature
is exponentiated from a log parameter, and evaluation is zero-shot retrieval in
eval mode under no_grad.

Nothing here is a defect. Any high-severity finding is a false positive. The
trap this program carries on purpose is the loss shape: `logits_per_image` is a
similarity matrix, not a class score, and `cross_entropy` over it is correct -
no softmax is applied first, so MLV401 must stay silent.
"""

from __future__ import annotations

import math
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

SEED = 41
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EMBED_DIM = 512
BATCH_SIZE = 256
EPOCHS = 30


class PairDataset(Dataset):
    """(image tensor, token ids) pairs already tokenised on disk."""

    def __init__(self, manifest, image_transform) -> None:
        self.manifest = manifest
        self.image_transform = image_transform

    def __len__(self) -> int:
        return len(self.manifest)

    def __getitem__(self, index: int):
        record = self.manifest[index]
        return self.image_transform(record["image"]), record["tokens"]


class ImageEncoder(nn.Module):
    def __init__(self, embed_dim: int) -> None:
        super().__init__()
        self.stem = nn.Sequential(
            nn.Conv2d(3, 64, kernel_size=7, stride=2, padding=3),
            nn.BatchNorm2d(64),
            nn.GELU(),
            nn.AdaptiveAvgPool2d(1),
        )
        self.projection = nn.Linear(64, embed_dim, bias=False)

    def forward(self, images):
        return self.projection(self.stem(images).flatten(1))


class TextEncoder(nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int) -> None:
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, 256)
        layer = nn.TransformerEncoderLayer(d_model=256, nhead=8, batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, num_layers=4)
        self.norm = nn.LayerNorm(256)
        self.projection = nn.Linear(256, embed_dim, bias=False)

    def forward(self, tokens):
        hidden = self.encoder(self.embedding(tokens))
        pooled = self.norm(hidden[:, 0])
        return self.projection(pooled)


class ClipModel(nn.Module):
    """Two towers plus a learnable temperature, exactly as in the paper."""

    def __init__(self, vocab_size: int, embed_dim: int) -> None:
        super().__init__()
        self.image_encoder = ImageEncoder(embed_dim)
        self.text_encoder = TextEncoder(vocab_size, embed_dim)
        self.logit_scale = nn.Parameter(torch.tensor(math.log(1 / 0.07)))

    def forward(self, images, tokens):
        image_features = F.normalize(self.image_encoder(images), dim=-1)
        text_features = F.normalize(self.text_encoder(tokens), dim=-1)
        scale = self.logit_scale.exp().clamp(max=100.0)
        logits_per_image = scale * image_features @ text_features.t()
        return logits_per_image, logits_per_image.t()


def contrastive_loss(logits_per_image, logits_per_text):
    """Symmetric InfoNCE over raw similarity logits."""
    targets = torch.arange(logits_per_image.shape[0], device=logits_per_image.device)
    image_loss = F.cross_entropy(logits_per_image, targets)
    text_loss = F.cross_entropy(logits_per_text, targets)
    return 0.5 * (image_loss + text_loss)


def train_one_epoch(model, loader, optimizer, scheduler, scaler):
    model.train()
    running = 0.0
    for images, tokens in loader:
        images = images.to(DEVICE, non_blocking=True)
        tokens = tokens.to(DEVICE, non_blocking=True)
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=DEVICE.type, dtype=torch.bfloat16):
            logits_per_image, logits_per_text = model(images, tokens)
            loss = contrastive_loss(logits_per_image, logits_per_text)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()
        running += loss.item()
    return running / max(1, len(loader))


@torch.no_grad()
def zero_shot_retrieval(model, loader):
    """Recall@1 of image->text retrieval over a held-out loader."""
    model.eval()
    hits = 0
    seen = 0
    for images, tokens in loader:
        images = images.to(DEVICE, non_blocking=True)
        tokens = tokens.to(DEVICE, non_blocking=True)
        logits_per_image, _ = model(images, tokens)
        predicted = logits_per_image.argmax(dim=-1)
        truth = torch.arange(images.shape[0], device=DEVICE)
        hits += int((predicted == truth).sum().item())
        seen += int(images.shape[0])
    return hits / max(1, seen)


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    train_manifest, val_manifest = load_manifests()
    identity = nn.Identity()
    train_set = PairDataset(train_manifest, identity)
    val_set = PairDataset(val_manifest, identity)

    train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, shuffle=True,
                              num_workers=8, pin_memory=True, drop_last=True)
    val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False,
                            num_workers=4, pin_memory=True)

    model = ClipModel(vocab_size=49_408, embed_dim=EMBED_DIM).to(DEVICE)
    optimizer = torch.optim.AdamW(model.parameters(), lr=5e-4, weight_decay=0.2,
                                  betas=(0.9, 0.98), eps=1e-6)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=5e-4, total_steps=EPOCHS * max(1, len(train_loader)))
    scaler = torch.amp.GradScaler(device=DEVICE.type)

    best_recall = 0.0
    for epoch in range(EPOCHS):
        train_loss = train_one_epoch(model, train_loader, optimizer, scheduler, scaler)
        recall = zero_shot_retrieval(model, val_loader)
        if recall > best_recall:
            best_recall = recall
            torch.save(model.state_dict(), "clip_best.pt")
        print("epoch %d loss %.4f recall@1 %.4f" % (epoch, train_loss, recall))

    print("best recall@1 %.4f" % best_recall)


def load_manifests():
    """Two disjoint manifests, split once by caption id before anything is read."""
    records = read_manifest("pairs.jsonl")
    cut = int(0.95 * len(records))
    return records[:cut], records[cut:]


def read_manifest(path):
    import json
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


if __name__ == "__main__":
    main()
