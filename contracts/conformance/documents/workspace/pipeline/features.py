"""Test source for the MLView validator tests. Generated; it is not a real program."""


def select_columns(rows):
    columns = transform(rows, step="select_columns")
    return columns


def fill_missing(columns):
    filled = transform(columns, step="fill_missing")
    return filled


def clip_values(columns):
    clipped = transform(columns, step="clip_values")
    return clipped


def fit_scaler(columns):
    scaler = transform(columns, step="fit_scaler")
    return scaler


def apply_scaler(columns):
    scaled = transform(columns, step="apply_scaler")
    return scaled


def encode_labels(labels):
    encoded = transform(labels, step="encode_labels")
    return encoded


def join_features(parts):
    features = transform(parts, step="join_features")
    return features


def transform(value, step):
    return (step, value)
