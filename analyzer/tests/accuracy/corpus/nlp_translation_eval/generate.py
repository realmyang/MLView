"""Beam-search decoding for a fine-tuned marian / mbart translator."""

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

CHECKPOINT = "Helsinki-NLP/opus-mt-en-de"
MAX_SOURCE = 256
MAX_TARGET = 256


def load(checkpoint=CHECKPOINT, device=None):
    device = device or torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint)
    model.to(device)
    model.eval()
    return model, tokenizer, device


def encode(tokenizer, sources, device):
    batch = tokenizer(sources, padding=True, truncation=True,
                      max_length=MAX_SOURCE, return_tensors="pt")
    return {key: value.to(device) for key, value in batch.items()}


@torch.no_grad()
def translate(model, tokenizer, sources, device, batch_size=16, beams=4):
    """Decode a list of source sentences. Gradients are off for the whole pass."""
    outputs = []
    for start in range(0, len(sources), batch_size):
        batch = encode(tokenizer, sources[start:start + batch_size], device)
        generated = model.generate(
            input_ids=batch["input_ids"],
            attention_mask=batch["attention_mask"],
            num_beams=beams,
            max_new_tokens=MAX_TARGET,
            length_penalty=1.0,
            early_stopping=True,
        )
        outputs.extend(tokenizer.batch_decode(generated, skip_special_tokens=True))
    return outputs
