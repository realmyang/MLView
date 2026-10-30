# Samples

This folder holds small machine-learning projects to read. They are not meant
to be run. They need not be installed or executed to produce a diagram. Beside
each project is its diagram.

| Project | What it is | Diagram | Producer, as the diagram records it |
|---|---|---|---|
| `configured_training/` | PyTorch distillation: a student trained against a teacher, both chosen by a JSON config, and a separate inference entry point | [configured_training.mlview.json](configured_training.mlview.json) | `"host": "claude-code"`, `"model": "claude-opus-5-5"` |
| `image_classification/` | A small convolutional network trained with PyTorch, and a scikit-learn baseline | [image_classification.mlview.json](image_classification.mlview.json) | `"host": "claude-code"`, `"model": "claude-opus-5-5"` |
| `notebook_classifier/` | A notebook that trains a linear classifier with PyTorch | [notebook_classifier.mlview.json](notebook_classifier.mlview.json) | `"host": "claude-code"`, `"model": "claude-opus-5-5"` |
| `keras_tfdata/` | A tabular classifier with Keras and a `tf.data` input pipeline | [keras_tfdata.mlview.json](keras_tfdata.mlview.json) | `"host": "claude-code"`, `"model": "claude-opus-5-5"` |

To open a diagram, open this repository's folder in VS Code with the MLView
extension installed and click the diagram's file in the Explorer, or run
**MLView: Open Generated Diagram**.

Each diagram is one assistant session's reading of the code, not a fixed
answer: another session can write a different diagram of the same project.

## From the maintainer, 29 October 2026

The maintainer wrote `image_classification`, `notebook_classifier` and
`keras_tfdata` with mistakes on purpose. This page does not list them. Read
these projects; do not copy them.

For each project, its diagram is the output of the earliest session that
passed the mechanical checks listed under
[The sample diagrams](../docs/validation.md#the-sample-diagrams), and no
diagram was edited. One session was run for each of the four projects, and
each diagram here is that session's output.
For `image_classification`, one of these checks could not decide at first,
because some file edits in the session's log differ slightly in form from the
ones the assistant sent. At the maintainer's word the check now accepts that
one difference, and the same session passed.

The diagrams of `configured_training` and `image_classification`:

> I checked the two diagrams. They both look pretty good. I followed the
> diagrams step by step as well as the linked code snippets.

The diagrams of `notebook_classifier` and `keras_tfdata` are unreviewed
assistant output.
