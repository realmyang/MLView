import torch
from models import build


@torch.no_grad()
def predict(checkpoint, features):
    student = build("small")
    student.load_state_dict(torch.load(checkpoint, map_location="cpu", weights_only=True))
    student.eval()
    return student(features).argmax(dim=-1)
