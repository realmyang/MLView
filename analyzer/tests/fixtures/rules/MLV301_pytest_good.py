# MLVIEW-EXPECT-NONE: MLV301, MLV302
"""REC-09: a pytest module is not an evaluation region.

`_EVAL_NAME_RE` reads any `test*` function as an evaluation entrypoint, so an
ordinary test suite drew a **high** MLV301 ("runs a forward pass and never
calls backward()") on every assertion about a tensor shape. A test that asserts
a shape has no reason to call `.eval()`, and a high finding is the one marker
this project must never misplace. The shape is
`LLMs-from-scratch/ch04/09_dsa/test_dsa.py`."""
import pytest
import torch
import torch.nn as nn


def build():
    torch.manual_seed(0)
    return nn.Sequential(nn.Linear(16, 8), nn.Dropout(0.1), nn.Linear(8, 4))


def test_output_shape():
    model = build()
    inputs = torch.randn(2, 16)
    out = model(inputs)
    assert out.shape == (2, 4), "wrong shape: %s" % (out.shape,)


def test_is_deterministic_under_a_fixed_seed():
    model = build()
    inputs = torch.randn(3, 16)
    torch.testing.assert_close(model(inputs), model(inputs), rtol=0, atol=1e-6)
    with pytest.raises(RuntimeError):
        model(torch.randn(3, 17))
