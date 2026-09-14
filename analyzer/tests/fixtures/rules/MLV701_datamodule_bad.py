# MLVIEW-EXPECT: MLV701 line=21
"""vision-13. A LightningDataModule whose __init__ never chains to super().

MLV701 resolved base chains against `torch.nn.Module` and the three
`LightningModule` spellings only, so `LightningDataModule` - which the rule's
own `frameworks=["lightning"]` covers - passed silently. Skipping its base
initialiser makes `save_hyperparameters()` raise and the trainer's dataloader
wiring misbehave: the same always-a-bug, purely syntactic defect that earned
this rule its high severity and 0.97 prior.
"""
import pytorch_lightning as pl
import torch
from torch.utils.data import DataLoader, TensorDataset


class ImageDataModule(pl.LightningDataModule):
    """Defect: `self.root = root` is the first statement, not super().__init__()."""

    def __init__(self, root: str = "data/pets", batch_size: int = 32) -> None:
        self.root = root
        self.batch_size = batch_size
        self.train_ds = None

    def setup(self, stage=None) -> None:
        torch.manual_seed(0)
        self.train_ds = TensorDataset(torch.randn(64, 3), torch.randint(0, 2, (64,)))

    def train_dataloader(self) -> DataLoader:
        return DataLoader(self.train_ds, batch_size=self.batch_size, shuffle=True)
