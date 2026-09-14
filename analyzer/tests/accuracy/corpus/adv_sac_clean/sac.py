"""Soft Actor-Critic on a continuous-control gymnasium environment.

The shape is the one every SAC implementation shares and that nothing else in
this corpus covers: an off-policy replay buffer, *twin* critics with a
Polyak-averaged target copy, a squashed-Gaussian actor with the tanh log-prob
correction, and an automatically tuned entropy temperature - three optimizers
stepping in one update, in one function body.

Everything here is correct. Its value is the interleaving: `critic_opt.step()`
(line 147) stands above `actor_loss.backward()` (line 155) in the same block,
which is exactly the statement order MLV203 looks for, and the two are not
linked - a reader who reorders them breaks the algorithm. Nothing in this file
may be reported.
"""

from __future__ import annotations

import copy
import random

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

SEED = 7
GAMMA = 0.99
TAU = 0.005
BATCH = 256
START_STEPS = 1_000
BUFFER_SIZE = 100_000
LOG_STD_MIN = -20.0
LOG_STD_MAX = 2.0

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


class SquashedGaussianActor(nn.Module):
    """Mean/log-std head over a trunk that carries dropout."""

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
    """Two Q networks, registered through a ModuleList."""

    def __init__(self, obs_dim: int, act_dim: int, hidden: int = 256) -> None:
        super().__init__()
        self.nets = nn.ModuleList([
            nn.Sequential(nn.Linear(obs_dim + act_dim, hidden), nn.ReLU(),
                          nn.Linear(hidden, hidden), nn.ReLU(),
                          nn.Linear(hidden, 1))
            for _ in range(2)
        ])

    def forward(self, obs, action):
        joint = torch.cat([obs, action], dim=-1)
        return [net(joint).squeeze(-1) for net in self.nets]


class ReplayBuffer:
    """A flat cyclic buffer of transitions, allocated once on the device."""

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

    def sample(self, batch: int, generator):
        index = torch.randint(0, self.size, (batch,), device=self.obs.device,
                              generator=generator)
        return (self.obs[index], self.actions[index], self.rewards[index],
                self.next_obs[index], self.dones[index])


def soft_update(target: nn.Module, online: nn.Module, tau: float) -> None:
    """Polyak averaging - no gradient is involved on either side."""
    with torch.no_grad():
        for target_param, param in zip(target.parameters(), online.parameters()):
            target_param.mul_(1.0 - tau)
            target_param.add_(tau * param)


def update(actor, critic, target_critic, log_alpha, optimizers, batch):
    """One SAC update: critic, then actor, then the temperature."""
    critic_opt, actor_opt, alpha_opt = optimizers
    obs, actions, rewards, next_obs, dones = batch
    alpha = log_alpha.exp().detach()

    with torch.no_grad():
        next_action, next_logp = actor(next_obs)
        target_q1, target_q2 = target_critic(next_obs, next_action)
        target_q = torch.min(target_q1, target_q2) - alpha * next_logp
        backup = rewards + GAMMA * (1.0 - dones) * target_q

    q1, q2 = critic(obs, actions)
    critic_loss = F.mse_loss(q1, backup) + F.mse_loss(q2, backup)
    critic_opt.zero_grad(set_to_none=True)
    critic_loss.backward()
    critic_opt.step()

    for param in critic.parameters():
        param.requires_grad_(False)
    fresh_action, fresh_logp = actor(obs)
    fresh_q1, fresh_q2 = critic(obs, fresh_action)
    actor_loss = (alpha * fresh_logp - torch.min(fresh_q1, fresh_q2)).mean()
    actor_opt.zero_grad(set_to_none=True)
    actor_loss.backward()
    actor_opt.step()
    for param in critic.parameters():
        param.requires_grad_(True)

    target_entropy = -float(actions.shape[-1])
    alpha_loss = -(log_alpha * (fresh_logp.detach() + target_entropy)).mean()
    alpha_opt.zero_grad(set_to_none=True)
    alpha_loss.backward()
    alpha_opt.step()

    soft_update(target_critic, critic, TAU)
    return critic_loss.item(), actor_loss.item(), alpha_loss.item()


def evaluate(env, actor, episodes: int = 5) -> float:
    """Deterministic rollouts with the policy in eval mode and no autograd."""
    actor.eval()
    scores = []
    with torch.no_grad():
        for episode in range(episodes):
            obs, _ = env.reset(seed=SEED + 1_000 + episode)
            done = False
            total = 0.0
            while not done:
                tensor = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
                action, _ = actor(tensor.unsqueeze(0), deterministic=True)
                obs, reward, terminated, truncated, _ = env.step(
                    action.squeeze(0).cpu().numpy())
                total += float(reward)
                done = bool(terminated or truncated)
            scores.append(total)
    actor.train()
    return float(np.mean(scores))


def main() -> None:
    seed_everything(SEED)
    generator = torch.Generator(device=DEVICE)
    generator.manual_seed(SEED)

    env = gym.make("Pendulum-v1")
    eval_env = gym.make("Pendulum-v1")
    obs_dim = int(env.observation_space.shape[0])
    act_dim = int(env.action_space.shape[0])

    actor = SquashedGaussianActor(obs_dim, act_dim).to(DEVICE)
    critic = TwinCritic(obs_dim, act_dim).to(DEVICE)
    target_critic = copy.deepcopy(critic)
    for param in target_critic.parameters():
        param.requires_grad_(False)

    log_alpha = torch.zeros(1, requires_grad=True, device=DEVICE)
    optimizers = (
        torch.optim.Adam(critic.parameters(), lr=1e-3),
        torch.optim.Adam(actor.parameters(), lr=1e-3),
        torch.optim.Adam([log_alpha], lr=1e-3),
    )
    buffer = ReplayBuffer(BUFFER_SIZE, obs_dim, act_dim, DEVICE)

    obs, _ = env.reset(seed=SEED)
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
            batch = buffer.sample(BATCH, generator)
            update(actor, critic, target_critic, log_alpha, optimizers, batch)

        if step % 5_000 == 0 and step > 0:
            print("step %d eval return %.1f" % (step, evaluate(eval_env, actor)))

    torch.save({"actor": actor.state_dict(), "critic": critic.state_dict()},
               "sac_pendulum.pt")


if __name__ == "__main__":
    main()
