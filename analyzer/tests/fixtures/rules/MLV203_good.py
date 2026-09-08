# MLVIEW-EXPECT-NONE: MLV203
"""The trap: a GAN step where d_optimizer.step() legitimately runs before
g_loss.backward(). Two optimizers and two losses, so the ordering carries no
information and the rule must stay quiet."""
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset


def train(dataset: TensorDataset, epochs: int = 3) -> None:
    torch.manual_seed(0)
    generator = nn.Sequential(nn.Linear(10, 10))
    discriminator = nn.Sequential(nn.Linear(10, 1))
    criterion = nn.BCEWithLogitsLoss()
    g_optimizer = optim.Adam(generator.parameters(), lr=2e-4)
    d_optimizer = optim.Adam(discriminator.parameters(), lr=2e-4)
    train_loader = DataLoader(dataset, batch_size=32, shuffle=True)

    for epoch in range(epochs):
        for real, labels in train_loader:
            d_optimizer.zero_grad()
            d_loss = criterion(discriminator(real), labels)
            d_loss.backward()
            d_optimizer.step()

            g_optimizer.zero_grad()
            fake = generator(real)
            g_loss = criterion(discriminator(fake), labels)
            g_loss.backward()
            g_optimizer.step()
