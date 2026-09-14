"""Train a policy against a frozen reference on a preference dataset.

Defective twin shape: there is no correct companion in the corpus because the
planted defects are the point - see labels.json.
"""

import torch
from datasets import load_dataset
from torch.utils.data import DataLoader
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    get_cosine_schedule_with_warmup,
)

from dpo import PreferencePair, preference_accuracy, sequence_logprob

BASE = "Qwen/Qwen2.5-0.5B-Instruct"
MAX_LENGTH = 512


def load_pairs(name="trl-lib/ultrafeedback_binarized"):
    raw = load_dataset(name)
    return raw["train"], raw["test"]


def collate(tokenizer):
    def _collate(rows):
        chosen = tokenizer([r["chosen"] for r in rows], padding=True,
                           truncation=True, max_length=MAX_LENGTH,
                           return_tensors="pt")
        rejected = tokenizer([r["rejected"] for r in rows], padding=True,
                             truncation=True, max_length=MAX_LENGTH,
                             return_tensors="pt")
        chosen["answer_mask"] = chosen["attention_mask"]
        rejected["answer_mask"] = rejected["attention_mask"]
        return chosen, rejected

    return _collate


def build_loaders(train_rows, eval_rows, tokenizer, batch_size=4):
    train_loader = DataLoader(train_rows, batch_size=batch_size, shuffle=True,
                              collate_fn=collate(tokenizer))
    eval_loader = DataLoader(eval_rows, batch_size=batch_size, shuffle=True,
                             collate_fn=collate(tokenizer))
    return train_loader, eval_loader


def move(batch, device):
    return {key: value.to(device) for key, value in batch.items()}


def train_epoch(pair, loader, optimizer, scheduler, device):
    pair.policy.train()
    running = 0.0
    for chosen, rejected in loader:
        loss = pair(move(chosen, device), move(rejected, device))
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        running += loss
    scheduler.step()
    return running / max(len(loader), 1)


def evaluate(pair, loader, device):
    scores = []
    for chosen, rejected in loader:
        policy_chosen = sequence_logprob(pair.policy, move(chosen, device))
        policy_rejected = sequence_logprob(pair.policy, move(rejected, device))
        scores.append(preference_accuracy(policy_chosen, policy_rejected).item())
    return sum(scores) / max(len(scores), 1)


def sample_completions(policy, tokenizer, prompts, device, max_new_tokens=128):
    """Qualitative check: decode a handful of answers after every epoch."""
    outputs = []
    for prompt in prompts:
        batch = tokenizer(prompt, return_tensors="pt").to(device)
        generated = policy.generate(**batch, max_new_tokens=max_new_tokens,
                                    do_sample=True, top_p=0.9)
        outputs.append(tokenizer.decode(generated[0], skip_special_tokens=True))
    return outputs


def main(epochs=1, lr=5e-7, beta=0.1, out_path="policy.pt"):
    device = torch.device("cuda")
    tokenizer = AutoTokenizer.from_pretrained(BASE)
    policy = AutoModelForCausalLM.from_pretrained(BASE)
    reference = AutoModelForCausalLM.from_pretrained(BASE)
    for parameter in reference.parameters():
        parameter.requires_grad_(False)
    reference.eval()
    policy.to(device)
    reference.to(device)
    pair = PreferencePair(policy, reference, beta=beta)
    train_rows, eval_rows = load_pairs()
    train_loader, eval_loader = build_loaders(train_rows, eval_rows, tokenizer)
    optimizer = torch.optim.AdamW(policy.parameters(), lr=lr)
    total = len(train_loader) * epochs
    scheduler = get_cosine_schedule_with_warmup(optimizer, int(0.1 * total), total)
    for epoch in range(epochs):
        loss = train_epoch(pair, train_loader, optimizer, scheduler, device)
        accuracy = evaluate(pair, eval_loader, device)
        print("epoch %d loss %.4f pref-acc %.4f" % (epoch, loss, accuracy))
        print(sample_completions(policy, tokenizer,
                                 ["Explain gradient clipping."], device))
    torch.save(policy, out_path)
    return out_path


if __name__ == "__main__":
    main()
