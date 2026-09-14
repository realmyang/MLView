# MLVIEW-EXPECT-NONE: MLV707
"""PUB-07. The trap: manual optimization, where returning no loss is correct.

Lightning's own PPO example (`examples/pytorch/domain_templates/
reinforce_learn_ppo.py`) sets `self.automatic_optimization = False` and drives
both optimizers by hand. Lightning does not back-propagate a returned value in
that mode, so returning nothing is the documented shape - and MLV707 said
"Lightning has nothing to back-propagate and the batch is skipped", at medium /
0.90, above the Problems-panel floor, about Lightning's own example.
MLV706 already knew the gate; MLV707 did not use it.
"""
import pytorch_lightning as pl
import torch
import torch.nn as nn


class PPOLightning(pl.LightningModule):
    def __init__(self, obs: int = 8, actions: int = 4) -> None:
        super().__init__()
        pl.seed_everything(0)
        self.automatic_optimization = False
        self.actor = nn.Linear(obs, actions)
        self.critic = nn.Linear(obs, 1)

    def training_step(self, batch, batch_idx):
        states, advantages, returns = batch
        optimizer_actor, optimizer_critic = self.optimizers()

        loss_actor = -(self.actor(states).log_softmax(dim=-1).mean() * advantages.mean())
        optimizer_actor.zero_grad()
        self.manual_backward(loss_actor)
        optimizer_actor.step()

        loss_critic = nn.functional.mse_loss(self.critic(states).squeeze(-1), returns)
        optimizer_critic.zero_grad()
        self.manual_backward(loss_critic)
        optimizer_critic.step()

        self.log("loss_actor", loss_actor)
        self.log("loss_critic", loss_critic)

    def configure_optimizers(self):
        return (torch.optim.Adam(self.actor.parameters(), lr=3e-4),
                torch.optim.Adam(self.critic.parameters(), lr=1e-3))
