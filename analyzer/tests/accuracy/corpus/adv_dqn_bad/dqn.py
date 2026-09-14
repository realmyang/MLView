"""DQN with a replay buffer and a target network - the defective version.

The shape is the standard one: an online network, a target network, a cyclic
replay buffer, epsilon-greedy action selection and a Huber TD loss. Seven
defects are planted; the three that matter most to an RL reviewer (the target
network that is never synchronised, the TD target that keeps its gradient, and
the replay buffer that is filled from the evaluation episodes) have no rule in
the catalog today and are recorded under `unsupported` in labels.json.
"""

from __future__ import annotations

import collections

import gymnasium as gym
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

GAMMA = 0.99
BATCH = 64
BUFFER_SIZE = 50_000
LEARN_EVERY = 4
SYNC_EVERY = 1_000
EPS_START = 1.0
EPS_END = 0.05


class QNetwork(nn.Module):
    """DEFECT: __init__ never calls super().__init__()."""

    def __init__(self, obs_dim: int, n_actions: int, hidden: int = 128) -> None:
        self.body = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(hidden, hidden),
            nn.ReLU(),
        )
        # DEFECT: the two output branches live in a plain dict, so duelling
        # heads are invisible to .parameters() and never train.
        self.branches = {"value": nn.Linear(hidden, 1),
                         "advantage": nn.Linear(hidden, n_actions)}

    def forward(self, obs):
        features = self.body(obs)
        value = self.branches["value"](features)
        advantage = self.branches["advantage"](features)
        return value + advantage - advantage.mean(dim=-1, keepdim=True)


class ReplayBuffer:
    """A cyclic buffer of (s, a, r, s', done) transitions."""

    def __init__(self, capacity: int) -> None:
        self.storage = collections.deque(maxlen=capacity)

    def push(self, state, action, reward, next_state, done) -> None:
        self.storage.append((state, action, reward, next_state, done))

    def sample(self, batch_size: int):
        index = np.random.randint(0, len(self.storage), size=batch_size)
        batch = [self.storage[int(i)] for i in index]
        states, actions, rewards, next_states, dones = zip(*batch)
        return (torch.as_tensor(np.array(states), dtype=torch.float32),
                torch.as_tensor(np.array(actions), dtype=torch.long),
                torch.as_tensor(np.array(rewards), dtype=torch.float32),
                torch.as_tensor(np.array(next_states), dtype=torch.float32),
                torch.as_tensor(np.array(dones), dtype=torch.float32))

    def __len__(self) -> int:
        return len(self.storage)


def select_action(online, obs, epsilon, n_actions):
    if np.random.rand() < epsilon:
        return int(np.random.randint(n_actions))
    with torch.no_grad():
        values = online(torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0))
    return int(values.argmax(dim=-1).item())


def learn(online, target, optimizer, buffer):
    """One gradient step on a sampled minibatch."""
    states, actions, rewards, next_states, dones = buffer.sample(BATCH)
    q_values = online(states).gather(1, actions.unsqueeze(1)).squeeze(1)
    # DEFECT: the bootstrap target is not detached, so gradients flow into the
    # target network through the TD target and the regression chases itself.
    next_q = target(next_states).max(dim=1)[0]
    td_target = rewards + GAMMA * next_q * (1.0 - dones)
    loss = F.smooth_l1_loss(q_values, td_target)
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return loss.item()


def evaluate(env, online, episodes=5):
    """DEFECT: the network keeps dropout active and no_grad is never entered,
    so the reported greedy return is noisy and the evaluation allocates a full
    autograd graph per step."""
    scores = []
    for _ in range(episodes):
        obs, _ = env.reset()
        done = False
        total = 0.0
        while not done:
            values = online(torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0))
            action = int(values.argmax(dim=-1).item())
            obs, reward, terminated, truncated, _ = env.step(action)
            total += float(reward)
            done = terminated or truncated
        scores.append(total)
    return float(np.mean(scores))


def evaluation_episodes_into_buffer(env, online, buffer, episodes=5):
    """DEFECT: the evaluation episodes are pushed into the same replay buffer
    the agent learns from, so the held-out interaction is trained on."""
    for _ in range(episodes):
        obs, _ = env.reset()
        done = False
        while not done:
            action = select_action(online, obs, 0.0, env.action_space.n)
            next_obs, reward, terminated, truncated, _ = env.step(action)
            buffer.push(obs, action, reward, next_obs, float(terminated or truncated))
            obs = next_obs
            done = terminated or truncated


def main() -> None:
    # DEFECT: nothing seeds numpy, torch or the environment.
    env = gym.make("CartPole-v1")
    eval_env = gym.make("CartPole-v1")
    obs_dim = int(env.observation_space.shape[0])
    n_actions = int(env.action_space.n)

    # DEFECT: .cuda() is unconditional - this file never asks whether a GPU
    # exists, so it raises on any CPU-only machine.
    online = QNetwork(obs_dim, n_actions).cuda()
    target = QNetwork(obs_dim, n_actions).cuda()
    target.load_state_dict(online.state_dict())
    optimizer = torch.optim.Adam(online.parameters(), lr=1e-3)
    buffer = ReplayBuffer(BUFFER_SIZE)

    obs, _ = env.reset()
    epsilon = EPS_START
    for step in range(100_000):
        action = select_action(online, obs, epsilon, n_actions)
        next_obs, reward, terminated, truncated, _ = env.step(action)
        buffer.push(obs, action, reward, next_obs, float(terminated or truncated))
        obs = next_obs
        if terminated or truncated:
            obs, _ = env.reset()
        epsilon = max(EPS_END, epsilon - 1.0 / 20_000)

        if len(buffer) > BATCH and step % LEARN_EVERY == 0:
            learn(online, target, optimizer, buffer)
        # DEFECT: SYNC_EVERY is computed but the target network is never
        # reloaded from the online one, so the TD target is frozen at the
        # random initialisation for the whole run.
        if step % SYNC_EVERY == 0:
            print("step %d epsilon %.2f" % (step, epsilon))

        if step % 20_000 == 0:
            evaluation_episodes_into_buffer(eval_env, online, buffer)
            print("eval return %.1f" % evaluate(eval_env, online))

    torch.save(online.state_dict(), "dqn_cartpole.pt")
    # DEFECT: torch.load with neither weights_only= nor map_location=.
    restored = torch.load("dqn_cartpole.pt")
    online.load_state_dict(restored)


if __name__ == "__main__":
    main()
