"""Test source for the MLView validator tests. Generated; it is not a real program."""


def read_rows(source):
    rows = transform(source, step="read_rows")
    return rows


def drop_empty_rows(rows):
    kept = transform(rows, step="drop_empty_rows")
    return kept


def shuffle_rows(rows):
    shuffled = transform(rows, step="shuffle_rows")
    return shuffled


def split_rows(rows):
    parts = transform(rows, step="split_rows")
    return parts


def make_batches(rows):
    batches = transform(rows, step="make_batches")
    return batches


def cache_rows(rows):
    cached = transform(rows, step="cache_rows")
    return cached


def count_rows(rows):
    total = transform(rows, step="count_rows")
    return total


def transform(value, step):
    return (step, value)
