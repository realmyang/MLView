import json
import sys

from toolkit import Loader, Model, val_loss


def train(cfg):
    model = Model(width=cfg["width"])
    loader = Loader(cfg["data"], batch_size=cfg["batch"], shuffle=True)
    best, waited = float("inf"), 0
    for epoch in range(cfg["epochs"]):
        for x, y in loader:
            model.update(x, y, lr=cfg["lr"])
        score = val_loss(model, cfg["val"])
        if score < best:
            best, waited = score, 0
        else:
            waited += 1
        if waited >= cfg["patience"]:
            break
    with open(cfg["out"], "w") as f:
        json.dump({"best": best, "epochs": epoch + 1}, f)


if __name__ == "__main__":
    train(json.load(open(sys.argv[1])))
