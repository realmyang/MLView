"""Soft Actor-Critic - the defective twin of adv_sac_clean.

Ten defects are planted. Four of them are the ones an RL reviewer looks for
first and none of them is modelled by a rule today: the target critic that is
never Polyak-averaged, the bootstrap target that keeps its gradient, the
replay buffer that is filled from the *evaluation* environment, and the entropy
temperature that is optimised through a detached log-alpha. They are recorded
under `unsupported` in labels.json so they can be promoted the day a rule sees
them.
"""

from __future__ import annotations

import copy

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

GAMMA = 0.99
TAU = 0.005
BATCH = 256
START_STEPS = 1_000
BUFFER_SIZE = 100_000
UPDATES_PER_STEP = 2
LOG_STD_MIN = -20.0
LOG_STD_MAX = 2.0

# DEFECT: the device is hard-coded to cuda with no availability check, so the
# script cannot run at all on a machine without a GPU.
DEVICE = torch.device("cuda")


class SquashedGaussianActor(nn.Module):
    def __init__(self, obs_dim: int, act_dim: int, hidden: int = 256) -> None:
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        self.mu = nn.Linear(hidden, act_dim)
        self.log_std = nn.Linear(hidden, act_dim)

    def forward(self, obs, deterministic: bool = False):
        features = self.trunk(obs)
        mu = self.mu(features)
        log_std = torch.clamp(self.log_std(features), LOG_STD_MIN, LOG_STD_MAX)
        std = torch.exp(log_std)
        if deterministic:
            return torch.tanh(mu), None
        normal = torch.distributions.Normal(mu, std)
        raw = normal.rsample()
        action = torch.tanh(raw)
        logp = normal.log_prob(raw).sum(dim=-1)
        logp = logp - (2.0 * (np.log(2.0) - raw - F.softplus(-2.0 * raw))).sum(dim=-1)
        return action, logp


class TwinCritic(nn.Module):
    def __init__(self, obs_dim: int, act_dim: int, hidden: int = 256) -> None:
        super().__init__()
        # DEFECT: the two Q networks live in a plain Python list, so neither is
        # registered and critic.parameters() is empty.
        self.nets = [
            nn.Sequential(nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
                          nn.Linear(hidden, hidden), nn.ReLU(),
                          nn.Linear(hidden, 1))
            for _ in range(2)
        ]

    def forward(self, obs, action):
        joint = torch.cat([obs, action], dim=-1)
        return [net(joint).squeeze(-1) for net in self.nets]


class ReplayBuffer:
    def __init__(self, capacity: int, obs_dim: int, act_dim: int, device) -> None:
        self.obs = torch.zeros(capacity, obs_dim, device=device)
        self.actions = torch.zeros(capacity, act_dim, device=device)
        self.rewards = torch.zeros(capacity, device=device)
        self.next_obs = torch.zeros(capacity, obs_dim, device=device)
        self.dones = torch.zeros(capacity, device=device)
        self.capacity = capacity
        self.ptr = 0
        self.size = 0

    def push(self, obs, action, reward, next_obs, done) -> None:
        index = self.ptr
        self.obs[index] = obs
        self.actions[index] = action
        self.rewards[index] = reward
        self.next_obs[index] = next_obs
        self.dones[index] = done
        self.ptr = (index + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch: int):
        index = torch.randint(0, self.size, (batch,), device=self.obs.device)
        return (self.obs[index], self.actions[index], self.rewards[index],
                self.next_obs[index], self.dones[index])


def soft_update(target: nn.Module, online: nn.Module, tau: float) -> None:
    """Defined, exported, documented - and never called from anywhere."""
    with torch.no_grad():
        for target_param, param in zip(target.parameters(), online.parameters()):
            target_param.mul_(1.0 - tau)
            target_param.add_(tau * param)


def update(actor, critic, target_critic, log_alpha, optimizers, batch):
    critic_opt, actor_opt, alpha_opt = optimizers
    obs, actions, rewards, next_obs, dones = batch
    alpha = log_alpha.exp()

    # DEFECT: the bootstrap target is computed with gradients on and is never
    # detached, so the critic is trained through its own target.
    next_action, next_logp = actor(next_obs)
    target_q1, target_q2 = target_critic(next_obs, next_action)
    target_q = torch.min(target_q1, target_q2) - alpha * next_logp
    backup = rewards + GAMMA * (1.0 - dones) * target_q

    q1, q2 = critic(obs, actions)
    critic_loss = F.mse_loss(q1, backup) + F.mse_loss(q2, backup)
    # DEFECT: the optimizer steps before the gradients for this batch exist.
    critic_opt.zero_grad(set_to_none=True)
    critic_opt.step()
    critic_loss.backward()

    fresh_action, fresh_logp = actor(obs)
    fresh_q1, fresh_q2 = critic(obs, fresh_action)
    actor_loss = (alpha * fresh_logp - torch.min(fresh_q1, fresh_q2)).mean()
    # DEFECT: the actor update never zeroes its gradients, so every update
    # applies the sum of every actor gradient computed since the run started.
    actor_loss.backward()
    actor_opt.step()

    target_entropy = -float(actions.shape[-1])
    # DEFECT: log_alpha is detached inside its own loss, so alpha_loss has no
    # gradient path to the only parameter alpha_opt owns and the temperature
    # never moves off its initial value.
    alpha_loss = -(log_alpha.detach() * (fresh_logp.detach() + target_entropy)).mean()
    alpha_opt.zero_grad(set_to_none=True)
    alpha_loss.backward()
    alpha_opt.step()

    # DEFECT: soft_update(target_critic, critic, TAU) is never called, so the
    # target critic stays at its initialisation for the whole run.
    return critic_loss


def evaluate(env, actor, buffer, episodes: int = 5) -> float:
    """DEFECT: no actor.eval(), no torch.no_grad() - and the transitions the
    evaluation episodes produce are pushed into the *training* replay buffer."""
    scores = []
    for episode in range(episodes):
        obs, _ = env.reset(seed=1_000 + episode)
        done = False
        total = 0.0
        while not done:
            tensor = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
            action, _ = actor(tensor.unsqueeze(0), deterministic=True)
            next_obs, reward, terminated, truncated, _ = env.step(
                action.squeeze(0).detach().cpu().numpy())
            next_tensor = torch.as_tensor(next_obs, dtype=torch.float32,
                                          device=DEVICE)
            buffer.push(tensor, action.squeeze(0), float(reward), next_tensor,
                        float(terminated))
            obs = next_obs
            total += float(reward)
            done = bool(terminated or truncated)
        scores.append(total)
    return float(np.mean(scores))


def main() -> None:
    # DEFECT: nothing seeds torch, numpy or random anywhere in this project.
    env = gym.make("Pendulum-v1")
    eval_env = gym.make("Pendulum-v1")
    obs_dim = int(env.observation_space.shape[0])
    act_dim = int(env.action_space.shape[0])

    actor = SquashedGaussianActor(obs_dim, act_dim).to(DEVICE)
    critic = TwinCritic(obs_dim, act_dim).to(DEVICE)
    target_critic = copy.deepcopy(critic)

    log_alpha = torch.zeros(1, requires_grad=True, device=DEVICE)
    optimizers = (
        torch.optim.Adam(critic.parameters(), lr=1e-3),
        torch.optim.Adam(actor.parameters(), lr=1e-3),
        torch.optim.Adam([log_alpha], lr=1e-3),
    )
    buffer = ReplayBuffer(BUFFER_SIZE, obs_dim, act_dim, DEVICE)

    # DEFECT: the running critic loss keeps the live tensor, so every update of
    # every environment step is retained until main() returns.
    running_critic = 0.0
    obs, _ = env.reset()
    for step in range(20_000):
        obs_tensor = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
        if step < START_STEPS:
            action_np = env.action_space.sample()
            action = torch.as_tensor(action_np, dtype=torch.float32, device=DEVICE)
        else:
            with torch.no_grad():
                action, _ = actor(obs_tensor.unsqueeze(0))
            action = action.squeeze(0)
            action_np = action.cpu().numpy()
        next_obs, reward, terminated, truncated, _ = env.step(action_np)
        next_tensor = torch.as_tensor(next_obs, dtype=torch.float32, device=DEVICE)
        buffer.push(obs_tensor, action, float(reward), next_tensor,
                    float(terminated))
        obs = next_obs if not (terminated or truncated) else env.reset()[0]

        if step >= START_STEPS and buffer.size >= BATCH:
            for _ in range(UPDATES_PER_STEP):
                batch = buffer.sample(BATCH)
                running_critic += update(actor, critic, target_critic, log_alpha,
                                         optimizers, batch)

        if step % 5_000 == 0 and step > 0:
            print("step %d eval return %.1f"
                  % (step, evaluate(eval_env, actor, buffer)))

    # DEFECT: the whole module is pickled rather than its state_dict.
    torch.save(actor, "sac_pendulum.pt")


if __name__ == "__main__":
    main()
