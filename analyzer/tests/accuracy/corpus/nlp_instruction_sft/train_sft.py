"""Supervised fine-tuning of a small instruct model with TRL and LoRA."""

import numpy as np
import torch
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    set_seed,
)
from trl import SFTConfig, SFTTrainer

from sft_data import SEED, load_instructions, prepare

BASE = "Qwen/Qwen2.5-1.5B-Instruct"


def quantization_config():
    return BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )


def lora_config(rank=16):
    return LoraConfig(
        r=rank,
        lora_alpha=rank * 2,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )


def build_model():
    model = AutoModelForCausalLM.from_pretrained(
        BASE, quantization_config=quantization_config(), device_map="auto",
        torch_dtype=torch.bfloat16,
    )
    model.config.use_cache = False
    adapted = get_peft_model(model, lora_config())
    adapted.print_trainable_parameters()
    return adapted


def compute_metrics(eval_pred):
    """Token-level accuracy over the answer positions the collator kept."""
    logits, labels = eval_pred
    predictions = np.argmax(logits[:, :-1, :], axis=-1)
    targets = labels[:, 1:]
    keep = targets != -100
    return {"token_accuracy": float((predictions[keep] == targets[keep]).mean())}


def sft_config(out_dir, epochs=2):
    return SFTConfig(
        output_dir=out_dir,
        num_train_epochs=epochs,
        per_device_train_batch_size=2,
        per_device_eval_batch_size=2,
        gradient_accumulation_steps=8,
        gradient_checkpointing=True,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        max_seq_length=1024,
        packing=True,
        dataset_text_field="text",
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        bf16=True,
        logging_steps=25,
        seed=SEED,
        data_seed=SEED,
        report_to=[],
    )


def main(out_dir="runs/sft"):
    set_seed(SEED)
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    tokenizer.pad_token = tokenizer.eos_token
    train_rows, eval_rows = load_instructions()
    train_set, eval_set = prepare(tokenizer, train_rows, eval_rows)
    model = build_model()
    trainer = SFTTrainer(
        model=model,
        args=sft_config(out_dir),
        train_dataset=train_set,
        eval_dataset=eval_set,
        processing_class=tokenizer,
        compute_metrics=compute_metrics,
    )
    trainer.train()
    metrics = trainer.evaluate()
    trainer.save_model(out_dir)
    tokenizer.save_pretrained(out_dir)
    return metrics


if __name__ == "__main__":
    print(main())
