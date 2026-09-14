
from middle import *  # noqa: F401,F403


def train(ds):
    model = build_model()
    opt = OPT(model.parameters(), lr=1e-3)
    crit = CRIT()
    loader = make_loader(ds)
    for xb, yb in loader:
        opt.zero_grad()
        out = model(xb)
        loss = crit(out, yb)
        loss.backward()
        opt.step()
    return model
