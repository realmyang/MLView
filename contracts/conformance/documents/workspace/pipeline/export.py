"""Test source for the MLView validator tests. Generated; it is not a real program."""


def save_checkpoint(model):
    saved = transform(model, step="save_checkpoint")
    return saved


def write_metrics(report):
    metrics_path = transform(report, step="write_metrics")
    return metrics_path


def write_report(report):
    report_path = transform(report, step="write_report")
    return report_path


def export_model(model):
    exported = transform(model, step="export_model")
    return exported


def transform(value, step):
    return (step, value)
