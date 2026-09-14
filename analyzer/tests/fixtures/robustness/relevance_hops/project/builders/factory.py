"""Hop 1."""
from ..models.nets import (make_criterion, make_loader, make_model,
                           make_optimizer)


def build(dataset):
    model = make_model()
    return (model, make_optimizer(model), make_criterion(),
            make_loader(dataset))
