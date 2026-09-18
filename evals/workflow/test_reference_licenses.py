"""The third-party reference excerpts retain their exact pinned license files."""

from __future__ import annotations

import hashlib
from pathlib import Path


LICENSES = Path(__file__).parent / "reference-candidates" / "licenses"
EXPECTED = {
    "nanogpt-LICENSE": "a59ec5cdb1c1e447e5266a014b3e7ded511f8d6e5a08931e931c87490ff821fe",
    "transformers-LICENSE": "77fd4710def9ec3c0f6225800e0235f15a425abd4a8b03559127fcd782612049",
    "scikit-learn-COPYING": "50d6a9d340f19ab355609917993114daf5f47e3161067bcf34955bbd05cd9cb0",
    "flax-LICENSE": "25e8791da26f7e74c4baf19eafd7d137b64a46952ef840ed01c172b680cf4046",
    "diffusers-LICENSE": "f9e2070c247517b1ddf65f7b11b393484a18da91a958fd18a97bd0f241c3125c",
    "mmdetection-LICENSE": "874b8b2e6f12306a1ff7812c068a0dbf880418b8ac1f7190382bd6c6da9f23a1",
    "cleanrl-LICENSE": "c6c269472eecb009754856b5fe1029ee53b99b986f57bf22ad7c747b04799c69",
    "handson-ml3-LICENSE": "e1925845017bf307c7d465af432e8bb20cbb6ce17b10cd323af59da717753075",
}


def test_pinned_reference_license_files_are_complete_and_unchanged():
    files = {path.name for path in LICENSES.iterdir() if path.name != "README.md"}
    assert files == set(EXPECTED)
    for name, expected in EXPECTED.items():
        assert hashlib.sha256((LICENSES / name).read_bytes()).hexdigest() == expected
