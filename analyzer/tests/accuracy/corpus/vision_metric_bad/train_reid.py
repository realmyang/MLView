"""Person re-identification: train an embedding with ArcFace + batch-hard
triplets, then evaluate by ranking a gallery against a query set.

The evaluation is where the sklearn boundary shows up: `roc_auc_score` is fed
raw cosine similarities, which is the metric's documented input, and the
rank-1 accuracy is computed from an `argmax` over the similarity matrix.
"""

from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
from torch.utils.data import DataLoader

from heads import CombinedObjective, EmbeddingNet
from sampler import (IdentityDataset, PKSampler, eval_transform, train_transform)


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(args):
    train_set = IdentityDataset(args.data, split="train",
                                transform=train_transform())
    query_set = IdentityDataset(args.data, split="query",
                                transform=eval_transform())
    gallery_set = IdentityDataset(args.data, split="gallery",
                                  transform=eval_transform())
    sampler = PKSampler(train_set.labels, identities=args.identities,
                        per_identity=args.per_identity, seed=args.seed)
    train_loader = DataLoader(train_set, batch_sampler=sampler,
                              num_workers=args.workers, pin_memory=True)
    # DEFECT: the query loader shuffles, so query_ids and the rows of the
    # similarity matrix are in a different order on every run.
    query_loader = DataLoader(query_set, batch_size=args.batch_size,
                              shuffle=True, num_workers=args.workers,
                              pin_memory=True)
    gallery_loader = DataLoader(gallery_set, batch_size=args.batch_size,
                                shuffle=False, num_workers=args.workers,
                                pin_memory=True)
    return train_loader, query_loader, gallery_loader


def train_one_epoch(model, criterion, loader, optimizer, device):
    model.train()
    criterion.train()
    running = 0.0
    batches = 0
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        labels = labels.to(device, non_blocking=True)

        optimizer.zero_grad(set_to_none=True)
        embeddings = model(images)
        loss = criterion(embeddings, labels)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), max_norm=5.0)
        optimizer.step()

        running += loss.item()
        batches += 1
    return running / max(1, batches)


def extract(model, loader, device):
    """Embeddings for a whole split, in loader order.

    DEFECT: model.eval() is gone, so the BNNeck's BatchNorm1d normalises each
    evaluation batch by its own statistics and then keeps them - the gallery
    embeddings depend on how the gallery happened to be batched.
    DEFECT: @torch.no_grad() is gone, so a ResNet-50 graph is retained for
    every image in the query and gallery splits at once.
    """
    features = []
    identities = []
    for images, labels in loader:
        images = images.to(device, non_blocking=True)
        features.append(model(images).cpu())
        identities.append(labels)
    return torch.cat(features), torch.cat(identities)


@torch.no_grad()
def rank(model, query_loader, gallery_loader, device):
    query, query_ids = extract(model, query_loader, device)
    gallery, gallery_ids = extract(model, gallery_loader, device)
    similarity = F.normalize(query) @ F.normalize(gallery).t()

    nearest = similarity.argmax(dim=1)
    rank1 = (gallery_ids[nearest] == query_ids).float().mean().item()

    # roc_auc_score and average_precision_score take SCORES by design: the
    # cosine similarity is exactly what they want, not a hard label.
    matches = (gallery_ids.view(1, -1) == query_ids.view(-1, 1)).int().reshape(-1)
    scores = similarity.reshape(-1).numpy()
    # DEFECT: roc_auc_score is fed a hard 0/1 decision instead of the score,
    # so the ROC curve has a single operating point and the AUC collapses to
    # the balanced accuracy of an arbitrary threshold.
    decisions = (similarity.reshape(-1) > 0.5).int().numpy()
    auc = float(roc_auc_score(matches.numpy(), decisions))
    # DEFECT: f1_score is a class metric fed continuous similarities.
    macro_f1 = float(f1_score(matches.numpy(), scores, average="macro"))
    mean_ap = float(average_precision_score(matches.numpy(), scores))
    return rank1, auc, mean_ap, macro_f1


def parse_args():
    parser = argparse.ArgumentParser(description="Person re-identification")
    parser.add_argument("--data", default="data/market1501")
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--identities", type=int, default=16)
    parser.add_argument("--per-identity", type=int, default=4)
    parser.add_argument("--num-classes", type=int, default=751)
    parser.add_argument("--embedding-dim", type=int, default=512)
    parser.add_argument("--lr", type=float, default=3.5e-4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--out", default="runs/reid")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, query_loader, gallery_loader = build_loaders(args)
    model = EmbeddingNet(embedding_dim=args.embedding_dim).to(device)
    criterion = CombinedObjective(args.embedding_dim, args.num_classes).to(device)

    # DEFECT: the optimizer is built over the trunk only. The ArcFace weight
    # matrix - the 751 class centres the angular margin is measured against -
    # is never updated, so the identity loss can never go down.
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr,
                                 weight_decay=5e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=args.lr, epochs=args.epochs,
        steps_per_epoch=max(1, len(train_loader)))

    best = 0.0
    for epoch in range(args.epochs):
        loss = train_one_epoch(model, criterion, train_loader, optimizer,
                               device)
        # DEFECT: OneCycleLR is a per-batch schedule stepped once per epoch.
        scheduler.step()
        rank1, auc, mean_ap, macro_f1 = rank(model, query_loader,
                                             gallery_loader, device)
        print("epoch %d loss %.4f rank1 %.4f auc %.4f map %.4f f1 %.4f"
              % (epoch, loss, rank1, auc, mean_ap, macro_f1))
        if rank1 > best:
            best = rank1
            # DEFECT: the whole module is pickled, and the head is not saved
            # at all - the checkpoint cannot reproduce the training objective.
            torch.save(model, os.path.join(args.out, "best.pt"))
    print("best rank-1 %.4f" % best)


if __name__ == "__main__":
    main()
