"""Direct preference optimisation, written by hand over a frozen reference.

Defective on purpose: the reference model is the only one ever put in eval
mode, the reference forward keeps its autograd graph, and the sampling pass
that produces the qualitative examples runs with gradients on.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F


class PreferencePair(nn.Module):
    """Holds the policy and the frozen reference side by side."""

    def __init__(self, policy, reference, beta=0.1):
        super().__init__()
        self.policy = policy
        self.reference = reference
        self.beta = beta

    def forward(self, chosen, rejected):
        policy_chosen = sequence_logprob(self.policy, chosen)
        policy_rejected = sequence_logprob(self.policy, rejected)
        reference_chosen = sequence_logprob(self.reference, chosen)
        reference_rejected = sequence_logprob(self.reference, rejected)
        return dpo_loss(policy_chosen, policy_rejected,
                        reference_chosen, reference_rejected, self.beta)


def sequence_logprob(model, batch):
    """Sum the log-probability of every answer token in the batch."""
    logits = model(input_ids=batch["input_ids"],
                   attention_mask=batch["attention_mask"]).logits
    logits = logits[:, :-1, :]
    targets = batch["input_ids"][:, 1:]
    token_logprobs = torch.log_softmax(logits, dim=-1).gather(
        -1, targets.unsqueeze(-1)).squeeze(-1)
    mask = batch["answer_mask"][:, 1:].float()
    return (token_logprobs * mask).sum(dim=-1)


def dpo_loss(policy_chosen, policy_rejected, reference_chosen,
             reference_rejected, beta=0.1):
    policy_margin = policy_chosen - policy_rejected
    reference_margin = reference_chosen - reference_rejected
    return -F.logsigmoid(beta * (policy_margin - reference_margin)).mean()


def preference_accuracy(policy_chosen, policy_rejected):
    return (policy_chosen > policy_rejected).float().mean()
