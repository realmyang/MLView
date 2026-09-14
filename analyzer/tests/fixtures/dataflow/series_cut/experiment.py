"""DATAFLOW-IP probe: a research repo scaling a whole series before the cut.

The second of the two leaks the roadmap names. A `MinMaxScaler` is fitted over
the entire series inside a method, and only afterwards is the series cut
chronologically (`shuffle=False`, which is what a time-ordered holdout looks
like in scikit-learn). Every future row has already contributed its minimum and
maximum to the training features, so the reported error is optimistic and does
not survive deployment.

The series enters the object through the constructor, which is why
`--dataflow local` is silent here and `--dataflow ip` is not.
"""
from __future__ import annotations

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler


class SeriesExperiment:
    """Holds a whole series and hands back a chronological train/test cut."""

    def __init__(self, series, targets, test_size: float = 0.2) -> None:
        self.series = series
        self.targets = targets
        self.test_size = test_size
        self.scaler = MinMaxScaler()

    def prepare(self):
        scaled = self.scaler.fit_transform(self.series)
        return train_test_split(scaled, self.targets,
                                test_size=self.test_size, shuffle=False)
