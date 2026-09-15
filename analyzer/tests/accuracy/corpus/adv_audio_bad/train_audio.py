"""Keyword-spotting classifier over torchaudio mel spectrograms - defective.

The twin of adv_audio_clean, written as the flat research script it usually is:
module-level loaders with workers and no __main__ guard, an unseeded split, a
training loader that never shuffles, a cosine schedule stepped once per batch,
the epoch loss kept as a live tensor, batches that stay on the CPU while the
model is on the GPU, and a validation pass that never leaves train mode.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torchaudio
from torch.utils.data import DataLoader, random_split

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
SAMPLE_RATE = 16_000
N_MELS = 64
BATCH_SIZE = 64
EPOCHS = 20
NUM_CLASSES = 35


class LogMel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.mel = torchaudio.transforms.MelSpectrogram(
            sample_rate=SAMPLE_RATE, n_fft=400, hop_length=160, n_mels=N_MELS)
        self.to_db = torchaudio.transforms.AmplitudeToDB(top_db=80.0)

    def forward(self, waveform):
        return self.to_db(self.mel(waveform))


class AudioCNN(nn.Module):
    def __init__(self, num_classes: int) -> None:
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, kernel_size=3, padding=1),
            nn.BatchNorm2d(32),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm2d(64),
            nn.ReLU(),
            nn.MaxPool2d(2),
        )
        self.pool = nn.AdaptiveAvgPool2d(1)
        self.dropout = nn.Dropout(0.3)
        self.classifier = nn.Linear(64, num_classes)

    def forward(self, spectrogram):
        h = self.features(spectrogram)
        h = self.pool(h).flatten(1)
        return self.classifier(self.dropout(h))


def validate(model, frontend, loader, criterion):
    """DEFECT: no model.eval(), so the 0.3 dropout and both BatchNorm2d layers
    keep updating their running statistics during validation, and DEFECT: no
    torch.no_grad(), so the whole validation set builds an autograd graph."""
    total = 0.0
    for waveforms, labels in loader:
        logits = model(frontend(waveforms))
        total += criterion(logits, labels).item()
    return total / max(1, len(loader))


dataset = torchaudio.datasets.SPEECHCOMMANDS("./data", download=True)
# DEFECT: random_split with no generator=, so the three partitions are a
# different three partitions on every run.
train_set, val_set, test_set = random_split(dataset, [0.8, 0.1, 0.1])

# DEFECT: the training loader never shuffles, so every epoch sees the same
# speaker order and the batches stay correlated with the file listing.
# DEFECT: num_workers=4 on a module-level loader in a file with no
# `if __name__ == "__main__":` guard - on spawn platforms each worker
# re-imports this module and re-runs the whole script.
train_loader = DataLoader(train_set, batch_size=BATCH_SIZE, num_workers=4,
                          pin_memory=True)
val_loader = DataLoader(val_set, batch_size=BATCH_SIZE, shuffle=False,
                        num_workers=2)
test_loader = DataLoader(test_set, batch_size=BATCH_SIZE, shuffle=False,
                         num_workers=2)

frontend = LogMel()
model = AudioCNN(NUM_CLASSES).to(DEVICE)
criterion = nn.CrossEntropyLoss()
optimizer = torch.optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-2)
# DEFECT: CosineAnnealingLR is an epoch-cadence schedule, stepped below once
# per batch, so the whole cosine cycle completes inside the first epoch.
scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=EPOCHS)

# DEFECT: nothing seeds torch, numpy or python's random, so the split, the
# initialisation and the dropout masks all move between runs.
for epoch in range(EPOCHS):
    model.train()
    # DEFECT: the epoch loss is accumulated as a live tensor, so every batch's
    # autograd graph is retained for the whole epoch.
    running = 0.0
    for waveforms, labels in train_loader:
        # DEFECT: the model was moved to DEVICE but the batches never are.
        optimizer.zero_grad(set_to_none=True)
        spectrograms = frontend(waveforms)
        logits = model(spectrograms)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()
        scheduler.step()
        running += loss
    val_loss = validate(model, frontend, val_loader, criterion)
    print("epoch %d train %.4f val %.4f" % (epoch, running / len(train_loader), val_loss))

torch.save(model.state_dict(), "audio_cnn.pt")
print("test %.4f" % validate(model, frontend, test_loader, criterion))
