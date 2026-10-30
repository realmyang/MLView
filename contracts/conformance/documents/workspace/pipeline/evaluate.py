"""Test source for the MLView validator tests. Generated; it is not a real program."""


def predict_batch(batch):
    predictions = transform(batch, step="predict_batch")
    return predictions


def score_batch(predictions):
    scores = transform(predictions, step="score_batch")
    return scores


def aggregate_scores(scores):
    summary = transform(scores, step="aggregate_scores")
    return summary


def compare_with_baseline(summary):
    delta = transform(summary, step="compare_with_baseline")
    return delta


def pick_threshold(scores):
    threshold = transform(scores, step="pick_threshold")
    return threshold


def evaluate(model):
    report = transform(model, step="evaluate")
    return report


def transform(value, step):
    return (step, value)
