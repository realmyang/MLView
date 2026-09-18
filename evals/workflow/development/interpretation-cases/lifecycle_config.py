"""Source-reading case: layered config and scoped lifecycle absence."""

DEFAULTS = {"epochs": 3, "save": None, "evaluate": True}


def resolve(file_config, cli):
    selected = {**DEFAULTS, **file_config}
    if cli.epochs is not None:
        selected["epochs"] = cli.epochs
    if cli.no_evaluate:
        selected["evaluate"] = False
    return selected


def run(model, train_loader, validation_loader, optimizer, config, callbacks):
    for callback in callbacks:
        callback.on_start(model)
    try:
        for _ in range(config["epochs"]):
            for batch in train_loader:
                optimizer.step(model.loss(batch))
            if config["evaluate"]:
                model.evaluate(validation_loader)
    finally:
        for callback in callbacks:
            callback.on_end(model)
    if config["save"]:
        model.save(config["save"])
