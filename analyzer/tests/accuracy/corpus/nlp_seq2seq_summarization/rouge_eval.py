"""Generate summaries for the holdout and score them with ROUGE.

The generation loop is hand-written because `predict_with_generate` does not
give you the decoded strings in the shape the report wants. It is wrong in four
ways, and every one of them still prints a number.
"""
from __future__ import annotations

import evaluate
import torch
from torch.utils.data import DataLoader
from transformers import DataCollatorForSeq2Seq

from summarize import TARGET_LENGTH, build_trainer

BEAMS = 4


def evaluate_holdout(model, tokenizer, holdout, collator):
    """Decode the holdout and score it. Nothing here is under no_grad."""
    val_loader = DataLoader(holdout["test"], batch_size=8, shuffle=True,
                            collate_fn=collator)
    model.cuda()
    rouge = evaluate.load("rouge")
    predictions = []
    references = []
    for batch in val_loader:
        generated = model.generate(input_ids=batch["input_ids"],
                                   attention_mask=batch["attention_mask"],
                                   num_beams=BEAMS,
                                   max_length=TARGET_LENGTH)
        predictions.extend(tokenizer.batch_decode(generated,
                                                  skip_special_tokens=True))
        references.extend(tokenizer.batch_decode(batch["labels"],
                                                 skip_special_tokens=True))
    return rouge.compute(predictions=predictions, references=references)


def main():
    tokenizer, model, holdout, trainer = build_trainer()
    trainer.train()
    collator = DataCollatorForSeq2Seq(tokenizer, model=model)
    scores = evaluate_holdout(model, tokenizer, holdout, collator)
    print({name: round(float(value), 4) for name, value in scores.items()})
    torch.save(model, "runs/sum/summariser.pt")


main()
