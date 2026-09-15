"""Text-line recognition data: variable-width crops, variable-length labels.

The shape every CRNN/OCR repository has: a fixed image height, a variable
image width, and a target that is a sequence of character indices whose length
has nothing to do with the image width. Neither can be stacked by the default
collate, so the project ships its own.
"""

from __future__ import annotations

import os
import random
import string
from typing import List, Sequence, Tuple

import torch
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms

# index 0 is reserved for the CTC blank, so the alphabet starts at 1
ALPHABET = string.digits + string.ascii_lowercase + " -.,"
CHAR_TO_INDEX = {char: index + 1 for index, char in enumerate(ALPHABET)}
INDEX_TO_CHAR = {index + 1: char for index, char in enumerate(ALPHABET)}
BLANK_INDEX = 0
IMAGE_HEIGHT = 32


def encode(text: str) -> List[int]:
    """Characters to CTC target indices; unknown characters are dropped."""
    return [CHAR_TO_INDEX[char] for char in text.lower() if char in CHAR_TO_INDEX]


def decode(indices: Sequence[int]) -> str:
    """Collapse repeats and strip blanks - the CTC greedy decoding rule."""
    out: List[str] = []
    previous = BLANK_INDEX
    for index in indices:
        if index != previous and index != BLANK_INDEX:
            out.append(INDEX_TO_CHAR.get(int(index), ""))
        previous = int(index)
    return "".join(out)


def train_transform() -> transforms.Compose:
    """Photometric jitter only: geometry would break the CTC alignment."""
    return transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.ColorJitter(brightness=0.3, contrast=0.3),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])


def eval_transform() -> transforms.Compose:
    """The same pipeline with every stochastic stage removed."""
    return transforms.Compose([
        transforms.Grayscale(num_output_channels=1),
        transforms.ToTensor(),
        transforms.Normalize(mean=[0.5], std=[0.5]),
    ])


class TextLineDataset(Dataset):
    """One directory of `<id>_<text>.png` crops, a very common OCR layout."""

    def __init__(self, root: str, transform=None, max_width: int = 320) -> None:
        self.root = root
        self.transform = transform
        self.max_width = max_width
        self.items = self._index(root)

    @staticmethod
    def _index(root: str) -> List[Tuple[str, str]]:
        found: List[Tuple[str, str]] = []
        for name in sorted(os.listdir(root)):
            if not name.lower().endswith(".png"):
                continue
            stem = os.path.splitext(name)[0]
            _, _, text = stem.partition("_")
            found.append((os.path.join(root, name), text))
        return found

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, index: int):
        path, text = self.items[index]
        image = Image.open(path).convert("L")
        scale = IMAGE_HEIGHT / float(image.height)
        width = min(self.max_width, max(8, int(round(image.width * scale))))
        image = image.resize((width, IMAGE_HEIGHT), Image.BILINEAR)
        if self.transform is not None:
            image = self.transform(image)
        target = torch.tensor(encode(text), dtype=torch.long)
        return image, target, text


def ctc_collate(batch):
    """Right-pad the images, concatenate the targets, keep both lengths.

    `nn.CTCLoss` wants the targets as one flat 1-D tensor plus a per-sample
    length, so this is not an optional convenience.
    """
    images, targets, texts = zip(*batch)
    widths = [int(image.shape[-1]) for image in images]
    max_width = max(widths)
    padded = torch.zeros(len(images), 1, IMAGE_HEIGHT, max_width)
    for position, image in enumerate(images):
        padded[position, :, :, : image.shape[-1]] = image
    target_lengths = torch.tensor([int(t.numel()) for t in targets], dtype=torch.long)
    flat_targets = torch.cat(targets) if targets else torch.zeros(0, dtype=torch.long)
    input_widths = torch.tensor(widths, dtype=torch.long)
    return padded, flat_targets, target_lengths, input_widths, list(texts)


def character_error_rate(predicted: str, truth: str) -> float:
    """Levenshtein distance normalised by the reference length."""
    if not truth:
        return 0.0 if not predicted else 1.0
    previous = list(range(len(truth) + 1))
    for i, p_char in enumerate(predicted, start=1):
        current = [i]
        for j, t_char in enumerate(truth, start=1):
            cost = 0 if p_char == t_char else 1
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost))
        previous = current
    return previous[-1] / float(len(truth))


def shuffled_subset(items: Sequence[Tuple[str, str]], fraction: float,
                    rng: random.Random) -> List[Tuple[str, str]]:
    """Used by the smoke-test harness, never by training."""
    pool = list(items)
    rng.shuffle(pool)
    return pool[: max(1, int(len(pool) * fraction))]
