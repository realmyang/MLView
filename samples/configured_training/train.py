import argparse
import json
import torch
from torch.utils.data import DataLoader, TensorDataset
from engine import evaluate, train_epoch
from models import build


def batches(filename, shuffle):
    tensors = torch.load(filename, map_location="cpu", weights_only=True)
    return DataLoader(TensorDataset(tensors["features"], tensors["labels"]),
                      batch_size=32, shuffle=shuffle)


def run(config):
    student = build(config["student"])
    teacher = build(config["teacher"])
    teacher.load_state_dict(torch.load(config["teacher_checkpoint"],
                                      map_location="cpu", weights_only=True))
    teacher.requires_grad_(False)
    optimizer = torch.optim.Adam(student.parameters(), lr=config["learning_rate"])
    train_batches = batches(config["train_data"], shuffle=True)
    validation_batches = batches(config["validation_data"], shuffle=False)
    for _ in range(config["epochs"]):
        train_epoch(student, teacher, train_batches, optimizer,
                    config["alpha"], config["temperature"])
        print({"validation_accuracy": evaluate(student, validation_batches)})
    torch.save(student.state_dict(), config["output"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as stream:
        run(json.load(stream))
