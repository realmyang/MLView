
"""A local module named `torch` that is NOT the framework."""


def device(name):
    return name


class nn:
    Linear = staticmethod(lambda a, b: (a, b))
