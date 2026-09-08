"""A windowed time-series dataset, published through `src.data`."""
import torch
from torch.utils.data import Dataset


class WindowDataset(Dataset):
    def __init__(self, series: torch.Tensor, width: int = 16) -> None:
        self.series = series
        self.width = width

    def __len__(self) -> int:
        return len(self.series) - self.width

    def __getitem__(self, index: int):
        return self.series[index:index + self.width], self.series[index + self.width]
