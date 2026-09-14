"""ROB-21: an unrelated project in a sibling directory of the analyzed root.

Nothing in `pkg/` imports it, it shares no package with `pkg/`, and it is not
under `workspace.root`. MLView reads it anyway and names it in the
`single_file_analysis` diagnostic as a "sibling module in the same package".
"""
import torch


def unrelated():
    return torch.zeros(1)
