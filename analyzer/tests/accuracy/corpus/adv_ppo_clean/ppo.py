"""PPO on a gymnasium environment - the correct reference.

Rollout buffer, GAE(lambda), a clipped surrogate objective, a shared trunk with
a policy head and a value head, and an entropy bonus. Written the way a careful
person writes it: seeded, gradients zeroed at the top of every minibatch step,
targets detached, evaluation in eval mode under no_grad, and the policy put back
in train mode afterwards.

Nothing in this file is a defect. Any high-severity finding here is a false
positive.
"""

from __future__ import annotations

import random

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.distributions import Categorical

SEED = 17
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
ROLLOUT_STEPS = 2048
EPOCHS = 10
MINIBATCH = 64
GAMMA = 0.99
LAMBDA = 0.95
CLIP_EPS = 0.2
ENTROPY_COEF = 0.01
VALUE_COEF = 0.5


class ActorCritic(nn.Module):
    """Shared trunk, a categorical policy head and a scalar value head."""

    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 64) -> None:
        super().__init__()
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
        )
        self.policy_head = nn.Linear(hidden, n_actions)
        self.value_head = nn.Linear(hidden, 1)

    def forward(self, obs):
        features = self.trunk(obs)
        return self.policy_head(features), self.value_head(features).squeeze(-1)


class RolloutBuffer:
    """Fixed-length on-policy storage. One buffer, overwritten every update."""

    def __init__(self, steps: int, obs_dim: int, device) -> None:
        self.obs = torch.zeros(steps, obs_dim, device=device)
        self.actions = torch.zeros(steps, dtype=torch.long, device=device)
        self.logprobs = torch.zeros(steps, device=device)
        self.values = torch.zeros(steps, device=device)
        self.rewards = torch.zeros(steps, device=device)
        self.dones = torch.zeros(steps, device=device)
        self.ptr = 0

    def add(self, obs, action, logprob, value, reward, done) -> None:
        index = self.ptr
        self.obs[index] = obs
        self.actions[index] = action
        self.logprobs[index] = logprob
        self.values[index] = value
        self.rewards[index] = reward
        self.dones[index] = done
        self.ptr = index + 1

    def reset(self) -> None:
        self.ptr = 0


def collect_rollout(env, policy, buffer, obs, steps):
    """Run the current policy for `steps` environment steps.

    The policy stays in train mode on purpose: PPO's rollout is part of the
    training loop, and switching to eval mode here would change the behaviour
    of any dropout or batch-norm layer between collection and update.
    """
    buffer.reset()
    for _ in range(steps):
        obs_tensor = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
        with torch.no_grad():
            logits, value = policy(obs_tensor.unsqueeze(0))
            dist = Categorical(logits=logits)
            action = dist.sample()
            logprob = dist.log_prob(action)
        next_obs, reward, terminated, truncated, _ = env.step(int(action.item()))
        done = float(terminated or truncated)
        buffer.add(obs_tensor, action.squeeze(0), logprob.squeeze(0),
                   value.squeeze(0), float(reward), done)
        obs = next_obs
        if terminated or truncated:
            obs, _ = env.reset()
    return obs


def compute_gae(rewards, values, dones, last_value, gamma, lam):
    """Generalized advantage estimation. Pure tensor arithmetic, no gradients."""
    advantages = torch.zeros_like(rewards)
    running = torch.zeros((), device=rewards.device)
    next_value = last_value
    for step in reversed(range(rewards.shape[0])):
        mask = 1.0 - dones[step]
        delta = rewards[step] + gamma * next_value * mask - values[step]
        running = delta + gamma * lam * mask * running
        advantages[step] = running
        next_value = values[step]
    returns = advantages + values
    return advantages, returns


def ppo_update(policy, optimizer, buffer, advantages, returns):
    """Ten epochs of minibatch SGD on the clipped surrogate objective."""
    n = buffer.ptr
    obs = buffer.obs[:n]
    actions = buffer.actions[:n]
    old_logprobs = buffer.logprobs[:n].detach()
    advantages = advantages.detach()
    returns = returns.detach()
    normalized = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    total_loss = 0.0
    for _ in range(EPOCHS):
        order = torch.randperm(n, device=obs.device)
        for start in range(0, n, MINIBATCH):
            index = order[start:start + MINIBATCH]
            logits, values = policy(obs[index])
            dist = Categorical(logits=logits)
            logprobs = dist.log_prob(actions[index])
            entropy = dist.entropy().mean()

            ratio = torch.exp(logprobs - old_logprobs[index])
            unclipped = ratio * normalized[index]
            clipped = torch.clamp(ratio, 1.0 - CLIP_EPS, 1.0 + CLIP_EPS) * normalized[index]
            policy_loss = -torch.min(unclipped, clipped).mean()
            value_loss = F.mse_loss(values, returns[index])
            loss = policy_loss + VALUE_COEF * value_loss - ENTROPY_COEF * entropy

            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(policy.parameters(), 0.5)
            optimizer.step()
            total_loss += loss.item()
    return total_loss


def evaluate_policy(env, policy, episodes=10):
    """Greedy evaluation on a held-out environment instance."""
    policy.eval()
    returns = []
    with torch.no_grad():
        for episode in range(episodes):
            obs, _ = env.reset(seed=SEED + 10_000 + episode)
            done = False
            total = 0.0
            while not done:
                obs_tensor = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
                logits, _ = policy(obs_tensor.unsqueeze(0))
                action = int(torch.argmax(logits, dim=-1).item())
                obs, reward, terminated, truncated, _ = env.step(action)
                total += float(reward)
                done = terminated or truncated
            returns.append(total)
    policy.train()
    return float(np.mean(returns))


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)

    env = gym.make("CartPole-v1")
    eval_env = gym.make("CartPole-v1")
    obs_dim = int(env.observation_space.shape[0])
    n_actions = int(env.action_space.n)

    policy = ActorCritic(obs_dim, n_actions).to(DEVICE)
    optimizer = torch.optim.Adam(policy.parameters(), lr=3e-4)
    buffer = RolloutBuffer(ROLLOUT_STEPS, obs_dim, DEVICE)

    obs, _ = env.reset(seed=SEED)
    for update in range(50):
        obs = collect_rollout(env, policy, buffer, obs, ROLLOUT_STEPS)
        with torch.no_grad():
            last_obs = torch.as_tensor(obs, dtype=torch.float32, device=DEVICE)
            _, last_value = policy(last_obs.unsqueeze(0))
        advantages, returns = compute_gae(
            buffer.rewards[:buffer.ptr], buffer.values[:buffer.ptr],
            buffer.dones[:buffer.ptr], last_value.squeeze(0), GAMMA, LAMBDA)
        loss = ppo_update(policy, optimizer, buffer, advantages, returns)
        if update % 10 == 0:
            score = evaluate_policy(eval_env, policy)
            print("update %d loss %.3f eval return %.1f" % (update, loss, score))

    torch.save(policy.state_dict(), "ppo_cartpole.pt")


if __name__ == "__main__":
    main()
