"""CTC speech recognition on torchaudio LIBRISPEECH - correct.

Round 1's audio pair was a spectrogram *classifier*. This is the sequence half:
a BiLSTM acoustic model, SpecAugment on the training branch only, a CTC loss,
a OneCycle schedule stepped per batch, gradient clipping between backward and
step, and a greedy decode under eval mode and no_grad.

The trap this file exists for is the log-softmax. `nn.CTCLoss` **requires**
log-probabilities as its first argument - unlike `CrossEntropyLoss`, which
log-softmaxes internally - so `F.log_softmax(...)` feeding `ctc_loss(...)` is
the documented, correct pairing. MLV401 firing here would be a false positive
on textbook code.
"""

from __future__ import annotations

import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from torch.utils.data import DataLoader

SEED = 21
EPOCHS = 10
BLANK = 0
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class TrainFeatures(nn.Module):
    """Mel spectrogram + SpecAugment - the training branch only."""

    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(sample_rate=16_000,
                                                        n_mels=80)
        self.masks = nn.Sequential(
            torchaudio.transforms.FrequencyMasking(freq_mask_param=27),
            torchaudio.transforms.TimeMasking(time_mask_param=100),
        )

    def forward(self, waveform):
        spectrogram = torch.log(self.mel(waveform) + 1e-6)
        return self.masks(spectrogram)


class EvalFeatures(nn.Module):
    """The same mel front-end with no augmentation at all."""

    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(sample_rate=16_000,
                                                        n_mels=80)

    def forward(self, waveform):
        return torch.log(self.mel(waveform) + 1e-6)


class Acoustic(nn.Module):
    def __init__(self, n_mels: int, hidden: int, vocab: int) -> None:
        super().__init__()
        self.rnn = nn.LSTM(n_mels, hidden, num_layers=3, bidirectional=True,
                           batch_first=True, dropout=0.2)
        self.dropout = nn.Dropout(0.2)
        self.head = nn.Linear(2 * hidden, vocab)

    def forward(self, features):
        hidden, _ = self.rnn(features.transpose(1, 2))
        return self.head(self.dropout(hidden))


def build_loaders(root: str):
    train_set = torchaudio.datasets.LIBRISPEECH(root, url="train-clean-100")
    dev_set = torchaudio.datasets.LIBRISPEECH(root, url="dev-clean")
    train_loader = DataLoader(train_set, batch_size=16, shuffle=True,
                              num_workers=4, collate_fn=collate)
    dev_loader = DataLoader(dev_set, batch_size=16, shuffle=False,
                            num_workers=2, collate_fn=collate)
    return train_loader, dev_loader


def collate(batch):
    waveforms = torch.stack([item[0].squeeze(0) for item in batch])
    targets = torch.cat([item[1] for item in batch])
    target_lengths = torch.tensor([len(item[1]) for item in batch])
    return waveforms, targets, target_lengths


def train_epoch(model, features, loader, criterion, optimizer, scheduler) -> float:
    model.train()
    features.train()
    running = 0.0
    seen = 0
    for waveforms, targets, target_lengths in loader:
        waveforms = waveforms.to(DEVICE)
        targets = targets.to(DEVICE)
        optimizer.zero_grad(set_to_none=True)
        emissions = model(features(waveforms))
        # CTCLoss takes LOG-probabilities: this log_softmax is required.
        log_probs = F.log_softmax(emissions, dim=-1).transpose(0, 1)
        input_lengths = torch.full((log_probs.size(1),), log_probs.size(0),
                                   dtype=torch.long, device=DEVICE)
        loss = criterion(log_probs, targets, input_lengths, target_lengths)
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        optimizer.step()
        scheduler.step()
        running += loss.item()
        seen += 1
    return running / max(seen, 1)


@torch.no_grad()
def greedy_decode(model, features, loader) -> float:
    model.eval()
    features.eval()
    errors = 0
    total = 0
    for waveforms, targets, target_lengths in loader:
        emissions = model(features(waveforms.to(DEVICE)))
        best = emissions.argmax(dim=-1)
        collapsed = torch.unique_consecutive(best, dim=-1)
        errors += int((collapsed != BLANK).sum())
        total += int(target_lengths.sum())
    return errors / max(total, 1)


def main() -> None:
    seed_everything(SEED)
    train_loader, dev_loader = build_loaders("data/librispeech")
    train_features = TrainFeatures().to(DEVICE)
    eval_features = EvalFeatures().to(DEVICE)
    model = Acoustic(80, 320, vocab=29).to(DEVICE)
    criterion = nn.CTCLoss(blank=BLANK, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=3e-4, epochs=EPOCHS, steps_per_epoch=len(train_loader))

    for epoch in range(EPOCHS):
        loss = train_epoch(model, train_features, train_loader, criterion,
                           optimizer, scheduler)
        error = greedy_decode(model, eval_features, dev_loader)
        print("epoch %d loss %.4f dev error %.4f" % (epoch, loss, error))
    torch.save(model.state_dict(), "asr.pt")


if __name__ == "__main__":
    main()
