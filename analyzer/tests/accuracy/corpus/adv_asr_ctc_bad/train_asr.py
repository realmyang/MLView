"""CTC speech recognition - the defective twin of adv_asr_ctc_clean.

Eleven defects. The two an ASR reviewer looks for first are the SpecAugment
masks left on the evaluation branch - so the dev error is measured on
deliberately corrupted audio - and the plain `softmax` where `CTCLoss` demands
a `log_softmax`, which silently trains against the wrong likelihood.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchaudio
from torch.utils.data import DataLoader

EPOCHS = 10
BLANK = 0
# DEFECT: the device is hard-coded with no torch.cuda.is_available() check.
DEVICE = torch.device("cuda:0")


class Features(nn.Module):
    """DEFECT: one front-end for both branches, and it carries SpecAugment, so
    the evaluation pass is scored on masked audio."""

    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(sample_rate=16_000,
                                                        n_mels=80)
        # DEFECT: the two augmentations live in a plain Python list, so they are
        # not registered as submodules and .to(DEVICE) never moves them.
        self.masks = [
            torchaudio.transforms.FrequencyMasking(freq_mask_param=27),
            torchaudio.transforms.TimeMasking(time_mask_param=100),
        ]

    def forward(self, waveform):
        spectrogram = torch.log(self.mel(waveform) + 1e-6)
        for mask in self.masks:
            spectrogram = mask(spectrogram)
        return spectrogram


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


def collate(batch):
    waveforms = torch.stack([item[0].squeeze(0) for item in batch])
    targets = torch.cat([item[1] for item in batch])
    target_lengths = torch.tensor([len(item[1]) for item in batch])
    return waveforms, targets, target_lengths


def build_loaders(root: str):
    train_set = torchaudio.datasets.LIBRISPEECH(root, url="train-clean-100")
    dev_set = torchaudio.datasets.LIBRISPEECH(root, url="dev-clean")
    # DEFECT: the training loader never shuffles, so every epoch sees the
    # LibriSpeech utterances in speaker order.
    train_loader = DataLoader(train_set, batch_size=16, shuffle=False,
                              num_workers=4, collate_fn=collate)
    # DEFECT: the dev loader shuffles, so decoded hypotheses no longer line up
    # with the utterances they came from.
    dev_loader = DataLoader(dev_set, batch_size=16, shuffle=True,
                            num_workers=2, collate_fn=collate)
    return train_loader, dev_loader


def train_epoch(model, features, loader, criterion, optimizer, scheduler) -> float:
    model.train()
    running_loss = 0.0
    for waveforms, targets, target_lengths in loader:
        waveforms = waveforms.to(DEVICE)
        targets = targets.to(DEVICE)
        emissions = model(features(waveforms))
        # DEFECT: CTCLoss requires LOG-probabilities; this is a plain softmax,
        # so the loss is computed against probabilities read as log-probs.
        probs = F.softmax(emissions, dim=-1).transpose(0, 1)
        input_lengths = torch.full((probs.size(1),), probs.size(0),
                                   dtype=torch.long, device=DEVICE)
        loss = criterion(probs, targets, input_lengths, target_lengths)
        # DEFECT: the gradients are never zeroed.
        loss.backward()
        optimizer.step()
        # DEFECT: the clipping runs after the step, so it never affects an
        # update; it only scales gradients that are about to be overwritten.
        nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scheduler.step()
        # DEFECT: the running loss keeps the live tensor.
        running_loss += loss
    return running_loss


def greedy_decode(model, features, loader) -> float:
    """DEFECT: no model.eval() and no torch.no_grad(), so the 0.2 LSTM dropout
    is active during decoding and a full autograd graph is built for it."""
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
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    train_loader, dev_loader = build_loaders("data/librispeech")
    features = Features().to(DEVICE)
    model = Acoustic(80, 320, vocab=29).to(DEVICE)
    criterion = nn.CTCLoss(blank=BLANK, zero_infinity=True)
    optimizer = torch.optim.AdamW(model.parameters(), lr=3e-4)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=3e-4, epochs=EPOCHS, steps_per_epoch=len(train_loader))

    for epoch in range(EPOCHS):
        loss = train_epoch(model, features, train_loader, criterion,
                           optimizer, scheduler)
        error = greedy_decode(model, features, dev_loader)
        print("epoch %d loss %.4f dev error %.4f" % (epoch, float(loss), error))
    # DEFECT: the whole module is pickled rather than its state_dict.
    torch.save(model, "asr.pt")


main()
