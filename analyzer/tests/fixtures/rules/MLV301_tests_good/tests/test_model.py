# MLVIEW-EXPECT-NONE: MLV301, MLV302
"""PUB-05. The trap: pytest cases that run a forward pass.

`_EVAL_NAME_RE` matches `test(_|$)`, and - unlike the loop branch of
`eval_regions` - the function branch never asked for `_evaluation_evidence`, so
the regex alone minted an eval region: `vit-pytorch/tests/test_vit.py:4` and
`stable-baselines3/tests/test_utils.py:389` were both reported at high / 0.85,
on two of the most-read repositories in the corpus. Neither function evaluates
anything: no held-out data, no metric, no reported score. The second one runs
in train mode on purpose - initialising BatchNorm statistics is the point.
"""
import torch
import torch.nn as nn

from model import Net


def test_shape():
    net = Net()
    out = net(torch.randn(4, 8))
    assert out.shape == (4, 2)


def test_batchnorm_stats_are_initialised():
    m = nn.Sequential(nn.Linear(5, 5), nn.BatchNorm1d(5))
    m(torch.ones(3, 5))
    assert m[1].running_mean is not None
