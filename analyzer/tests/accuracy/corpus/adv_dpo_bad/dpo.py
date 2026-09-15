"""Direct Preference Optimisation on a HuggingFace causal LM - defective.

Preference training is the advanced pattern round 1 did not reach: two copies
of the same model, one trained and one frozen, and an objective that is a
function of the *difference* between their log-probabilities. Eight defects.

The three that break the method are reference-model specific and no rule sees
them: the reference model is never put in eval mode, its forward is not wrapped
in `torch.no_grad()`, and its parameters are handed to the optimizer along with
the policy's - so the "frozen" reference drifts and the implicit KL term the
method rests on stops existing.
"""

from __future__ import annotations

import copy

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader
from transformers import AutoModelForCausalLM, AutoTokenizer

BETA = 0.1
EPOCHS = 3
MODEL_ID = "gpt2"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def sequence_logprobs(model, input_ids, attention_mask, labels):
    """Sum of the per-token log-probabilities of `labels` under `model`."""
    outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    logits = outputs.logits[:, :-1, :]
    targets = labels[:, 1:]
    token_logprobs = torch.gather(
        F.log_softmax(logits, dim=-1), 2, targets.unsqueeze(-1)).squeeze(-1)
    mask = (targets != -100).float()
    return (token_logprobs * mask).sum(dim=-1)


def dpo_loss(policy_chosen, policy_rejected, reference_chosen,
             reference_rejected, beta):
    """The pairwise logistic objective over the two log-ratio differences."""
    policy_margin = policy_chosen - policy_rejected
    reference_margin = reference_chosen - reference_rejected
    return -F.logsigmoid(beta * (policy_margin - reference_margin)).mean()


def train_epoch(policy, reference, loader, optimizer) -> float:
    policy.train()
    running_loss = 0.0
    for batch in loader:
        chosen_ids = batch["chosen_input_ids"].to(DEVICE)
        chosen_mask = batch["chosen_attention_mask"].to(DEVICE)
        rejected_ids = batch["rejected_input_ids"].to(DEVICE)
        rejected_mask = batch["rejected_attention_mask"].to(DEVICE)

        policy_chosen = sequence_logprobs(policy, chosen_ids, chosen_mask,
                                          chosen_ids)
        policy_rejected = sequence_logprobs(policy, rejected_ids, rejected_mask,
                                            rejected_ids)
        # DEFECT: the reference forward is not wrapped in torch.no_grad(), so
        # the frozen model builds a graph and - because its parameters are in
        # the optimizer below - is actually trained.
        reference_chosen = sequence_logprobs(reference, chosen_ids, chosen_mask,
                                             chosen_ids)
        reference_rejected = sequence_logprobs(reference, rejected_ids,
                                               rejected_mask, rejected_ids)

        loss = dpo_loss(policy_chosen, policy_rejected, reference_chosen,
                        reference_rejected, BETA)
        # DEFECT: the gradients are never zeroed.
        loss.backward()
        optimizer.step()
        # DEFECT: the running loss keeps the live tensor.
        running_loss += loss
    return running_loss


def evaluate_preferences(policy, reference, loader) -> float:
    """DEFECT: neither model is put in eval mode and nothing here is wrapped in
    torch.no_grad(), so GPT-2's attention and residual dropout stay active and
    the reported preference accuracy is noise."""
    correct = 0
    seen = 0
    for batch in loader:
        chosen_ids = batch["chosen_input_ids"].to(DEVICE)
        rejected_ids = batch["rejected_input_ids"].to(DEVICE)
        chosen = sequence_logprobs(policy, chosen_ids,
                                   batch["chosen_attention_mask"].to(DEVICE),
                                   chosen_ids)
        rejected = sequence_logprobs(policy, rejected_ids,
                                     batch["rejected_attention_mask"].to(DEVICE),
                                     rejected_ids)
        correct += int((chosen > rejected).sum())
        seen += chosen.numel()
    return correct / max(seen, 1)


def main(train_pairs, eval_pairs) -> None:
    # DEFECT: nothing calls transformers.set_seed or torch.manual_seed.
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    policy = AutoModelForCausalLM.from_pretrained(MODEL_ID).to(DEVICE)
    # DEFECT: the reference is never switched to eval mode and its parameters
    # are never frozen with requires_grad_(False).
    reference = copy.deepcopy(policy)

    # DEFECT: the training loader does not shuffle, so the preference pairs are
    # replayed in dataset order every epoch.
    train_loader = DataLoader(train_pairs, batch_size=4, shuffle=False)
    # DEFECT: the evaluation loader shuffles.
    eval_loader = DataLoader(eval_pairs, batch_size=4, shuffle=True)

    # DEFECT: the optimizer owns the reference model's parameters too.
    optimizer = torch.optim.AdamW(
        list(policy.parameters()) + list(reference.parameters()), lr=5e-7)

    for epoch in range(EPOCHS):
        loss = train_epoch(policy, reference, train_loader, optimizer)
        accuracy = evaluate_preferences(policy, reference, eval_loader)
        print("epoch %d loss %.4f preference accuracy %.4f"
              % (epoch, float(loss), accuracy))

    policy.save_pretrained("dpo-gpt2")
    tokenizer.save_pretrained("dpo-gpt2")
