# Configured teacher/student training

A small distillation project. `train.py` reads a JSON config
(`configs/distill.json`, passed with `--config`) and trains a student model
against a teacher; `infer.py` is a separate entry point. The dataset and the
teacher checkpoint are not in this folder, so the project is not meant to be
run here.
