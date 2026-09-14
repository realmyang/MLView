"""The DDPM schedule, noising and sampler (defective twin).

Defect 1 (no rule covers it yet): the schedule tensors are plain attributes
instead of registered buffers, so `.to(device)` leaves them on the CPU and the
first `self.sqrt_alphas_cumprod[t]` with a CUDA `t` raises - and nothing about
them is saved in the checkpoint.
Defect 2: `p_sample_loop` runs the model without `eval()` and without
`no_grad()`, so dropout is active in every one of the 1000 reverse steps and
the sampler keeps a 1000-step autograd graph alive.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn


def cosine_beta_schedule(timesteps: int, s: float = 0.008) -> torch.Tensor:
    """Nichol & Dhariwal's cosine schedule, clipped away from 1.0."""
    steps = torch.arange(timesteps + 1, dtype=torch.float64) / timesteps
    alphas_cumprod = torch.cos((steps + s) / (1 + s) * math.pi * 0.5) ** 2
    alphas_cumprod = alphas_cumprod / alphas_cumprod[0]
    betas = 1.0 - (alphas_cumprod[1:] / alphas_cumprod[:-1])
    return betas.clamp(1e-8, 0.999).float()


class GaussianDiffusion(nn.Module):
    """Forward noising and reverse sampling for a fixed beta schedule."""

    def __init__(self, timesteps: int = 1000) -> None:
        super().__init__()
        self.timesteps = timesteps
        betas = cosine_beta_schedule(timesteps)
        alphas = 1.0 - betas
        alphas_cumprod = torch.cumprod(alphas, dim=0)
        self.betas = betas
        self.alphas_cumprod = alphas_cumprod
        self.sqrt_alphas_cumprod = alphas_cumprod.sqrt()
        self.sqrt_one_minus = (1.0 - alphas_cumprod).sqrt()
        self.posterior_variance = (betas * (1.0 - alphas_cumprod / alphas)
                                   / (1.0 - alphas_cumprod))

    def sample_timesteps(self, batch: int, device: torch.device) -> torch.Tensor:
        return torch.randint(0, self.timesteps, (batch,), device=device)

    def q_sample(self, x_start: torch.Tensor, t: torch.Tensor,
                 noise: torch.Tensor) -> torch.Tensor:
        """x_t = sqrt(a_bar) x_0 + sqrt(1 - a_bar) eps."""
        shape = (-1, 1, 1, 1)
        sqrt_alpha = self.sqrt_alphas_cumprod[t].reshape(shape)
        sqrt_one_minus = self.sqrt_one_minus[t].reshape(shape)
        return sqrt_alpha * x_start + sqrt_one_minus * noise

    def p_sample_loop(self, model: nn.Module, shape: tuple,
                      device: torch.device) -> torch.Tensor:
        """Defect 2: train mode, gradients on, for a thousand steps."""
        image = torch.randn(shape, device=device)
        for step in reversed(range(self.timesteps)):
            t = torch.full((shape[0],), step, device=device, dtype=torch.long)
            predicted_noise = model(image, t)
            alpha = 1.0 - self.betas[step]
            alpha_bar = self.alphas_cumprod[step]
            mean = (image - (1.0 - alpha) / (1.0 - alpha_bar).sqrt()
                    * predicted_noise) / alpha.sqrt()
            if step > 0:
                noise = torch.randn_like(image)
                image = mean + self.posterior_variance[step].sqrt() * noise
            else:
                image = mean
        return image.clamp(-1.0, 1.0)
