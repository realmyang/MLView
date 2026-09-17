# Configured teacher/student training

A small source-reading fixture for MLView. Do not run it: the dataset and
checkpoint are deliberately external. The selected scenario is
`configs/distill.json`, passed to `train.py` with `--config`.

It exercises configuration-selected construction, a frozen teacher, two loss
terms, student-only updates, and a separate inference entrypoint. The actual
dataset contents, checkpoint quality, and runtime metrics are unknown from
these files. The teacher and student architectures differ; both emit three
class logits.
