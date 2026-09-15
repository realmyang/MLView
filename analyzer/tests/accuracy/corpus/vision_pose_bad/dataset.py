"""COCO-style keypoint data: an affine crop around the person box, a Gaussian
heatmap target per joint, and a visibility weight.

The augmentation has to know the skeleton: a horizontal flip swaps left and
right joints, so flipping the image without permuting the channels silently
trains the model to mirror its own predictions. The evaluation path builds the
same affine transform with the random scale and rotation set to zero.
"""

from __future__ import annotations

import math
import os
import random
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np
import torch
from torch.utils.data import Dataset

NUM_JOINTS = 17
FLIP_PAIRS: Tuple[Tuple[int, int], ...] = (
    (1, 2), (3, 4), (5, 6), (7, 8), (9, 10), (11, 12), (13, 14), (15, 16))
IMAGE_SIZE = (192, 256)
HEATMAP_SIZE = (48, 64)
PIXEL_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
PIXEL_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


def affine_matrix(center: np.ndarray, scale: float, rotation: float,
                  output: Sequence[int]) -> np.ndarray:
    """The 2x3 matrix that maps the person box onto the network input."""
    radians = math.pi * rotation / 180.0
    source = np.zeros((3, 2), dtype=np.float32)
    destination = np.zeros((3, 2), dtype=np.float32)
    src_dir = np.array([0.0, scale * -0.5], dtype=np.float32)
    src_dir = np.array([src_dir[0] * math.cos(radians) - src_dir[1] * math.sin(radians),
                        src_dir[0] * math.sin(radians) + src_dir[1] * math.cos(radians)],
                       dtype=np.float32)
    dst_dir = np.array([0.0, output[1] * -0.5], dtype=np.float32)
    source[0, :] = center
    source[1, :] = center + src_dir
    source[2, :] = source[1, :] + np.array([-src_dir[1], src_dir[0]])
    destination[0, :] = np.array([output[0] * 0.5, output[1] * 0.5])
    destination[1, :] = destination[0, :] + dst_dir
    destination[2, :] = destination[1, :] + np.array([-dst_dir[1], dst_dir[0]])
    return cv2.getAffineTransform(np.float32(source), np.float32(destination))


def gaussian_target(joints: np.ndarray, visibility: np.ndarray, sigma: float = 2.0):
    """One `(J, H, W)` heatmap stack plus a `(J, 1)` weight."""
    height, width = HEATMAP_SIZE[1], HEATMAP_SIZE[0]
    target = np.zeros((NUM_JOINTS, height, width), dtype=np.float32)
    weight = visibility.astype(np.float32).reshape(NUM_JOINTS, 1).copy()
    radius = int(sigma * 3)
    span = np.arange(0, 2 * radius + 1, 1, dtype=np.float32)
    offset = span[:, None]
    blob = np.exp(-((span - radius) ** 2 + (offset - radius) ** 2) / (2 * sigma ** 2))
    for joint in range(NUM_JOINTS):
        if weight[joint, 0] < 0.5:
            continue
        mu_x, mu_y = int(joints[joint, 0] + 0.5), int(joints[joint, 1] + 0.5)
        left, top = mu_x - radius, mu_y - radius
        right, bottom = mu_x + radius + 1, mu_y + radius + 1
        if left >= width or top >= height or right < 0 or bottom < 0:
            weight[joint, 0] = 0.0
            continue
        gx = (max(0, -left), min(right, width) - left)
        gy = (max(0, -top), min(bottom, height) - top)
        ix = (max(0, left), min(right, width))
        iy = (max(0, top), min(bottom, height))
        target[joint, iy[0]:iy[1], ix[0]:ix[1]] = blob[gy[0]:gy[1], gx[0]:gx[1]]
    return target, weight


def flip_joints(joints: np.ndarray, visibility: np.ndarray, width: int):
    """DEFECT: the coordinates are mirrored but the left/right joint channels
    are never swapped, so after a flip the plane that is supposed to predict
    the left wrist is trained on the right wrist and vice versa. Half the
    training signal for every paired joint is inverted."""
    mirrored = joints.copy()
    mirrored[:, 0] = width - 1 - mirrored[:, 0]
    return mirrored, visibility.copy()


class KeypointDataset(Dataset):
    def __init__(self, root: str, annotations: List[Dict], train: bool = True,
                 scale_factor: float = 0.35, rotation_factor: float = 40.0) -> None:
        self.root = root
        self.records = list(annotations)
        self.train = train
        self.scale_factor = scale_factor
        self.rotation_factor = rotation_factor

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        record = self.records[index]
        image = cv2.imread(os.path.join(self.root, record["file"]), cv2.IMREAD_COLOR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        joints = np.array(record["joints"], dtype=np.float32)
        visibility = np.array(record["visibility"], dtype=np.float32)
        center = np.array(record["center"], dtype=np.float32)
        scale = float(record["scale"])
        rotation = 0.0

        if self.train:
            scale = scale * np.clip(np.random.randn() * self.scale_factor + 1.0,
                                    1 - self.scale_factor, 1 + self.scale_factor)
            if random.random() < 0.6:
                rotation = float(np.clip(np.random.randn() * self.rotation_factor,
                                         -self.rotation_factor * 2,
                                         self.rotation_factor * 2))
            if random.random() < 0.5:
                image = image[:, ::-1, :]
                joints, visibility = flip_joints(joints, visibility, image.shape[1])
                center[0] = image.shape[1] - 1 - center[0]

        matrix = affine_matrix(center, scale, rotation, IMAGE_SIZE)
        cropped = cv2.warpAffine(image, matrix, (IMAGE_SIZE[0], IMAGE_SIZE[1]),
                                 flags=cv2.INTER_LINEAR)
        cropped = (cropped.astype(np.float32) / 255.0 - PIXEL_MEAN) / PIXEL_STD
        tensor = torch.from_numpy(cropped.transpose(2, 0, 1).copy())

        heatmap_joints = joints.copy()
        for joint in range(NUM_JOINTS):
            point = np.array([joints[joint, 0], joints[joint, 1], 1.0])
            mapped = matrix.dot(point)
            heatmap_joints[joint, 0] = mapped[0] * HEATMAP_SIZE[0] / IMAGE_SIZE[0]
            heatmap_joints[joint, 1] = mapped[1] * HEATMAP_SIZE[1] / IMAGE_SIZE[1]
        target, weight = gaussian_target(heatmap_joints, visibility)
        meta = {"center": center, "scale": scale, "index": index}
        return tensor, torch.from_numpy(target), torch.from_numpy(weight), meta


def decode_heatmaps(heatmaps: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
    """argmax over each joint plane - the standard top-down decoder."""
    batch, joints, height, width = heatmaps.shape
    flat = heatmaps.reshape(batch, joints, -1)
    scores, indices = flat.max(dim=2)
    coords = torch.zeros(batch, joints, 2, device=heatmaps.device)
    coords[:, :, 0] = (indices % width).float()
    coords[:, :, 1] = torch.div(indices, width, rounding_mode="floor").float()
    return coords, scores


def pck_at(predicted: torch.Tensor, truth: torch.Tensor, weight: torch.Tensor,
           threshold: float = 0.5, normalizer: float = 40.0) -> float:
    """Percentage of correct keypoints, computed on decoded coordinates."""
    distance = torch.norm(predicted - truth, dim=2) / normalizer
    visible = weight.squeeze(-1) > 0.5
    if visible.sum() == 0:
        return 0.0
    correct = ((distance < threshold) & visible).sum().item()
    return float(correct) / float(visible.sum().item())
