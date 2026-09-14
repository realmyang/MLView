"""The `click` command group. This package's only entrypoint is a console script.

`pyproject.toml` declares `mlpkg = "mlpkg.cli:cli"`, so the process starts in
`cli()` and there is **no** `if __name__ == "__main__":` guard anywhere in the
package. On macOS and Windows a `DataLoader(num_workers=8)` therefore spawns
worker processes that re-import a module with no guard — which is the second
planted defect, and it is a property of the project layout rather than of any
one line.
"""
from __future__ import annotations

from pathlib import Path

import click

from .config import build_config
from .training import run_evaluation, run_training

CONFIG_PATH = Path("config.toml")


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=CONFIG_PATH, show_default=True,
              help="TOML file read under the dataclass defaults.")
@click.pass_context
def cli(ctx: click.Context, config_path: Path) -> None:
    """Train, evaluate and export the tabular router."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path


@cli.command()
@click.option("--epochs", type=int, default=None)
@click.option("--batch-size", "batch_size", type=int, default=None)
@click.option("--lr", type=float, default=None)
@click.option("--seed", type=int, default=None)
@click.pass_context
def train(ctx: click.Context, epochs, batch_size, lr, seed) -> None:
    """Run the training loop and write the best checkpoint."""
    cfg = build_config(ctx.obj["config_path"],
                       {"epochs": epochs, "batch_size": batch_size,
                        "lr": lr, "seed": seed})
    best = run_training(cfg)
    click.echo("best accuracy %.4f" % best)


@cli.command()
@click.option("--checkpoint", type=click.Path(path_type=Path), required=True)
@click.pass_context
def evaluate(ctx: click.Context, checkpoint: Path) -> None:
    """Score an existing checkpoint on the held-out split."""
    cfg = build_config(ctx.obj["config_path"], {})
    accuracy = run_evaluation(cfg, checkpoint)
    click.echo("accuracy %.4f" % accuracy)


@cli.command()
@click.option("--checkpoint", type=click.Path(path_type=Path), required=True)
@click.option("--out", type=click.Path(path_type=Path),
              default=Path("artifacts/router.onnx"))
@click.pass_context
def export(ctx: click.Context, checkpoint: Path, out: Path) -> None:
    """Trace the model to ONNX for the serving team."""
    import torch

    from .training import build_model

    cfg = build_config(ctx.obj["config_path"], {})
    model = build_model(cfg)
    model.load_state_dict(torch.load(checkpoint, weights_only=True))
    model.eval()
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, torch.zeros(1, cfg.features), str(out),
                      input_names=["features"], output_names=["logits"],
                      dynamic_axes={"features": {0: "batch"}})
    click.echo("wrote %s" % out)
