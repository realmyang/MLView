"""Grad-CAM, FGSM/PGD robustness and temperature calibration.

Every function in this file evaluates a trained classifier, and three of them
*need gradients to do it*. That is the point of the file: an evaluation pass
that calls `.backward()`, sets `requires_grad_(True)` on its input and runs
`torch.enable_grad()` inside a `no_grad` region is correct here, and a rule
family built around "evaluation must not build a graph" has to survive it.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class GradCAM:
    """Class-activation maps from the gradient of a logit w.r.t. a feature map.

    The hooks stay registered for the life of the object; `remove()` is the
    caller's job and `__exit__` does it.
    """

    def __init__(self, model: nn.Module, layer: nn.Module) -> None:
        self.model = model
        self.layer = layer
        self.activations: Optional[torch.Tensor] = None
        self.gradients: Optional[torch.Tensor] = None
        self._handles = [
            layer.register_forward_hook(self._save_activation),
            layer.register_full_backward_hook(self._save_gradient),
        ]

    def _save_activation(self, _module, _inputs, output) -> None:
        self.activations = output.detach()

    def _save_gradient(self, _module, _grad_input, grad_output) -> None:
        self.gradients = grad_output[0].detach()

    def __enter__(self) -> "GradCAM":
        return self

    def __exit__(self, *_exc) -> None:
        self.remove()

    def remove(self) -> None:
        for handle in self._handles:
            handle.remove()
        self._handles = []

    def __call__(self, images: torch.Tensor,
                 targets: Optional[torch.Tensor] = None) -> torch.Tensor:
        # eval() so dropout and batch-norm do not move the map around, but
        # gradients ARE required: the map IS a gradient.
        self.model.eval()
        self.model.zero_grad(set_to_none=True)
        with torch.enable_grad():
            logits = self.model(images)
            if targets is None:
                targets = logits.argmax(dim=1)
            selected = logits.gather(1, targets.view(-1, 1)).sum()
            selected.backward()
        weights = self.gradients.mean(dim=(2, 3), keepdim=True)
        cam = F.relu((weights * self.activations).sum(dim=1, keepdim=True))
        cam = F.interpolate(cam, size=images.shape[-2:], mode="bilinear",
                            align_corners=False)
        flat = cam.flatten(1)
        low = flat.min(dim=1, keepdim=True).values.view(-1, 1, 1, 1)
        high = flat.max(dim=1, keepdim=True).values.view(-1, 1, 1, 1)
        return (cam - low) / (high - low + 1e-8)


def fgsm(model: nn.Module, images: torch.Tensor, labels: torch.Tensor,
         epsilon: float) -> torch.Tensor:
    """One signed-gradient step away from the label. Needs a backward pass."""
    model.eval()
    perturbed = images.clone().detach().requires_grad_(True)
    with torch.enable_grad():
        loss = F.cross_entropy(model(perturbed), labels)
        gradient = torch.autograd.grad(loss, perturbed)[0]
    adversarial = images + epsilon * gradient.sign()
    return adversarial.clamp(0.0, 1.0).detach()


def pgd(model: nn.Module, images: torch.Tensor, labels: torch.Tensor,
        epsilon: float, alpha: float, steps: int) -> torch.Tensor:
    """`steps` projected FGSM steps inside an epsilon ball."""
    model.eval()
    adversarial = images.clone().detach()
    for _ in range(steps):
        adversarial.requires_grad_(True)
        with torch.enable_grad():
            loss = F.cross_entropy(model(adversarial), labels)
            gradient = torch.autograd.grad(loss, adversarial)[0]
        adversarial = adversarial.detach() + alpha * gradient.sign()
        delta = (adversarial - images).clamp(-epsilon, epsilon)
        adversarial = (images + delta).clamp(0.0, 1.0).detach()
    return adversarial


@torch.no_grad()
def tta_logits(model: nn.Module, images: torch.Tensor,
               scales: Tuple[float, ...] = (1.0, 1.25)) -> torch.Tensor:
    """Deterministic test-time augmentation: identity, flip, and two scales.

    Nothing here is random - the set of views is fixed and every one of them
    is averaged, which is what makes this a variance reduction rather than an
    augmentation left switched on by accident.
    """
    model.eval()
    accumulated = torch.zeros(images.shape[0], model.num_classes,
                              device=images.device)
    views = 0
    for scale in scales:
        if scale == 1.0:
            resized = images
        else:
            size = [int(round(dimension * scale)) for dimension in images.shape[-2:]]
            resized = F.interpolate(images, size=size, mode="bilinear",
                                    align_corners=False)
        for flipped in (False, True):
            view = resized.flip(dims=[3]) if flipped else resized
            accumulated += F.softmax(model(view), dim=1)
            views += 1
    return accumulated / max(1, views)


class TemperatureScaler(nn.Module):
    """One learned scalar, fitted on the validation split after training.

    Fitting on validation is the documented protocol for calibration - the
    parameter is one number and the test split is untouched.
    """

    def __init__(self) -> None:
        super().__init__()
        self.log_temperature = nn.Parameter(torch.zeros(1))

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        return logits / torch.exp(self.log_temperature)

    def fit(self, logits: torch.Tensor, labels: torch.Tensor,
            iterations: int = 50) -> "TemperatureScaler":
        optimizer = torch.optim.LBFGS([self.log_temperature], lr=0.05,
                                      max_iter=iterations)

        def closure():
            optimizer.zero_grad(set_to_none=True)
            loss = F.cross_entropy(self.forward(logits), labels)
            loss.backward()
            return loss

        optimizer.step(closure)
        return self


def expected_calibration_error(probabilities: torch.Tensor,
                               labels: torch.Tensor, bins: int = 15) -> float:
    """A Python float: every tensor is reduced with .item() before it is used."""
    confidence, predicted = probabilities.max(dim=1)
    correct = predicted.eq(labels).float()
    edges = torch.linspace(0.0, 1.0, bins + 1, device=probabilities.device)
    error = 0.0
    total = float(labels.numel())
    for index in range(bins):
        in_bin = (confidence > edges[index]) & (confidence <= edges[index + 1])
        count = float(in_bin.sum().item())
        if count == 0.0:
            continue
        accuracy = float(correct[in_bin].mean().item())
        average = float(confidence[in_bin].mean().item())
        error += (count / total) * abs(accuracy - average)
    return error


def layer_by_name(model: nn.Module, name: str) -> nn.Module:
    found: Dict[str, nn.Module] = dict(model.named_modules())
    if name not in found:
        raise KeyError("no module named %r; have %s"
                       % (name, ", ".join(sorted(found)[:8])))
    return found[name]


def top_k_confusions(matrix: List[List[int]], k: int = 5):
    """Off-diagonal cells, largest first - a pure-Python report helper."""
    cells = []
    for true_index, row in enumerate(matrix):
        for predicted_index, count in enumerate(row):
            if true_index != predicted_index and count:
                cells.append((count, true_index, predicted_index))
    cells.sort(reverse=True)
    return cells[:k]
