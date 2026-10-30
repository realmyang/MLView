"""Test source for the MLView validator tests. Generated; it is not a real program."""


def make_optimizer(model):
    optimizer = transform(model, step="make_optimizer")
    return optimizer


def make_schedule(optimizer):
    schedule = transform(optimizer, step="make_schedule")
    return schedule


def forward_pass(batch):
    outputs = transform(batch, step="forward_pass")
    return outputs


def compute_loss(outputs):
    loss = transform(outputs, step="compute_loss")
    return loss


def backward_pass(loss):
    gradients = transform(loss, step="backward_pass")
    return gradients


def update_weights(gradients):
    step = transform(gradients, step="update_weights")
    return step


def train_epoch(batches):
    epoch_loss = transform(batches, step="train_epoch")
    return epoch_loss


def fit(config):
    history = transform(config, step="fit")
    return history


def transform(value, step):
    return (step, value)
