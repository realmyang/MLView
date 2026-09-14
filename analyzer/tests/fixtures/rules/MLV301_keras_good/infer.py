# MLVIEW-EXPECT-NONE: MLV301, MLV302
"""PUB-09. The trap: a torch-only rule judging a Keras model.

MLV301 and MLV302 both declare `frameworks=["torch"]`, and that declaration was
enforced at the workspace, never at the receiver - so `keras-io/examples/vision/
zero_dce.py:508` was told to call `zero_dce_model.eval()` before its forward
pass and to wrap it in `torch.no_grad()`. Neither method exists in Keras, so
the finding is category-wrong rather than merely uncertain.
"""
import keras
from keras import layers

keras.utils.set_random_seed(0)

_inputs = keras.Input(shape=(32, 32, 3))
_outputs = layers.Conv2D(3, 3, padding="same")(_inputs)
zero_dce_model = keras.Model(_inputs, _outputs)


def infer(original_image):
    image = keras.ops.expand_dims(original_image, axis=0)
    return zero_dce_model(image)
