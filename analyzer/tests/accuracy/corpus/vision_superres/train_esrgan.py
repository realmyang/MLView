"""ESRGAN training: two optimizers, three loss terms, AMP, and a PSNR pass.

The discriminator is updated first and its step legitimately precedes the
generator's backward - the two updates are separate graphs over separate
parameter sets. `d_optimizer.step()` before `g_loss.backward()` is the shape
MLV203's false-positive note exists for.
"""

from __future__ import annotations

import argparse
import os
import random

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader

from data import PairedPatchDataset, eval_pipeline, train_pipeline
from models import Discriminator, Generator, VGGFeatures, psnr


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def pick_device() -> torch.device:
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


def build_loaders(args):
    train_set = PairedPatchDataset(os.path.join(args.data, "train"),
                                   scale=args.scale, patch=args.patch,
                                   pipeline=train_pipeline(args.patch))
    val_set = PairedPatchDataset(os.path.join(args.data, "val"),
                                 scale=args.scale, patch=args.patch,
                                 pipeline=eval_pipeline())
    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True,
                              num_workers=args.workers, pin_memory=True,
                              drop_last=True)
    val_loader = DataLoader(val_set, batch_size=1, shuffle=False,
                            num_workers=args.workers, pin_memory=True)
    return train_loader, val_loader


def train_one_epoch(generator, discriminator, features, loaders, optimizers,
                    scalers, criteria, device, args):
    train_loader = loaders["train"]
    g_optimizer, d_optimizer = optimizers["g"], optimizers["d"]
    g_scaler, d_scaler = scalers["g"], scalers["d"]
    adversarial, pixel = criteria["adversarial"], criteria["pixel"]

    generator.train()
    discriminator.train()
    g_running = 0.0
    d_running = 0.0
    batches = 0

    for low_res, high_res in train_loader:
        low_res = low_res.to(device, non_blocking=True)
        high_res = high_res.to(device, non_blocking=True)

        # ---- discriminator -------------------------------------------------
        d_optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16,
                            enabled=args.amp):
            fake = generator(low_res)
            real_score = discriminator(high_res)
            fake_score = discriminator(fake.detach())
            d_loss = 0.5 * (adversarial(real_score - fake_score.mean(),
                                        torch.ones_like(real_score))
                            + adversarial(fake_score - real_score.mean(),
                                          torch.zeros_like(fake_score)))
        d_scaler.scale(d_loss).backward()
        d_scaler.step(d_optimizer)
        d_scaler.update()

        # ---- generator -----------------------------------------------------
        g_optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16,
                            enabled=args.amp):
            real_score = discriminator(high_res).detach()
            fake_score = discriminator(fake)
            adversarial_loss = 0.5 * (
                adversarial(real_score - fake_score.mean(),
                            torch.zeros_like(real_score))
                + adversarial(fake_score - real_score.mean(),
                              torch.ones_like(fake_score)))
            perceptual = F.l1_loss(features(fake), features(high_res))
            pixel_loss = pixel(fake, high_res)
            g_loss = (args.pixel_weight * pixel_loss
                      + args.perceptual_weight * perceptual
                      + args.adversarial_weight * adversarial_loss)
        g_scaler.scale(g_loss).backward()
        g_scaler.unscale_(g_optimizer)
        nn.utils.clip_grad_norm_(generator.parameters(), max_norm=1.0)
        g_scaler.step(g_optimizer)
        g_scaler.update()

        g_running += g_loss.item()
        d_running += d_loss.item()
        batches += 1
    return g_running / max(1, batches), d_running / max(1, batches)


@torch.no_grad()
def validate(generator, loader, device):
    generator.eval()
    total_psnr = 0.0
    seen = 0
    for low_res, high_res in loader:
        low_res = low_res.to(device, non_blocking=True)
        high_res = high_res.to(device, non_blocking=True)
        prediction = generator(low_res).clamp(0.0, 1.0)
        total_psnr += psnr(prediction, high_res)
        seen += 1
    generator.train()
    return total_psnr / max(1, seen)


def parse_args():
    parser = argparse.ArgumentParser(description="ESRGAN 4x super-resolution")
    parser.add_argument("--data", default="data/div2k")
    parser.add_argument("--epochs", type=int, default=200)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--patch", type=int, default=128)
    parser.add_argument("--scale", type=int, default=4)
    parser.add_argument("--g-lr", type=float, default=1e-4)
    parser.add_argument("--d-lr", type=float, default=1e-4)
    parser.add_argument("--pixel-weight", type=float, default=1e-2)
    parser.add_argument("--perceptual-weight", type=float, default=1.0)
    parser.add_argument("--adversarial-weight", type=float, default=5e-3)
    parser.add_argument("--amp", action="store_true")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--seed", type=int, default=3407)
    parser.add_argument("--out", default="runs/esrgan")
    parser.add_argument("--resume", default="")
    return parser.parse_args()


def maybe_resume(path, generator, discriminator, g_optimizer, d_optimizer):
    if not path or not os.path.isfile(path):
        return 0
    state = torch.load(path, map_location="cpu", weights_only=True)
    generator.load_state_dict(state["generator"])
    discriminator.load_state_dict(state["discriminator"])
    g_optimizer.load_state_dict(state["g_optimizer"])
    d_optimizer.load_state_dict(state["d_optimizer"])
    return int(state.get("epoch", 0)) + 1


def main() -> None:
    args = parse_args()
    seed_everything(args.seed)
    device = pick_device()
    os.makedirs(args.out, exist_ok=True)

    train_loader, val_loader = build_loaders(args)
    generator = Generator(blocks=16, scale=args.scale).to(device)
    discriminator = Discriminator().to(device)
    features = VGGFeatures().to(device)

    g_optimizer = torch.optim.Adam(generator.parameters(), lr=args.g_lr,
                                   betas=(0.9, 0.99))
    d_optimizer = torch.optim.Adam(discriminator.parameters(), lr=args.d_lr,
                                   betas=(0.9, 0.99))
    g_scheduler = torch.optim.lr_scheduler.MultiStepLR(
        g_optimizer, milestones=[50, 100, 150], gamma=0.5)
    d_scheduler = torch.optim.lr_scheduler.MultiStepLR(
        d_optimizer, milestones=[50, 100, 150], gamma=0.5)

    criteria = {"adversarial": nn.BCEWithLogitsLoss(), "pixel": nn.L1Loss()}
    scalers = {"g": torch.amp.GradScaler(enabled=args.amp),
               "d": torch.amp.GradScaler(enabled=args.amp)}

    start = maybe_resume(args.resume, generator, discriminator,
                         g_optimizer, d_optimizer)
    best_psnr = 0.0
    for epoch in range(start, args.epochs):
        g_loss, d_loss = train_one_epoch(
            generator, discriminator, features,
            {"train": train_loader}, {"g": g_optimizer, "d": d_optimizer},
            scalers, criteria, device, args)
        g_scheduler.step()
        d_scheduler.step()
        score = validate(generator, val_loader, device)
        print("epoch %d g %.4f d %.4f psnr %.3f" % (epoch, g_loss, d_loss, score))
        if score > best_psnr:
            best_psnr = score
            torch.save({"generator": generator.state_dict(),
                        "discriminator": discriminator.state_dict(),
                        "g_optimizer": g_optimizer.state_dict(),
                        "d_optimizer": d_optimizer.state_dict(),
                        "epoch": epoch, "psnr": score},
                       os.path.join(args.out, "best.pt"))
    print("best psnr %.3f" % best_psnr)


if __name__ == "__main__":
    main()
