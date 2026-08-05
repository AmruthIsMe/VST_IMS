"""
rl_agent.py — Tower 2: PPO agent training and evaluation.

Trains a Proximal Policy Optimisation (PPO) agent on VSTInventoryEnv,
then evaluates it against a simple heuristic baseline.

Outputs:
  - models/ppo_vst_inventory/  (saved PPO policy)
  - data/rl_eval_results.csv   (episode-level metrics)
  - output/metrics/rl_vs_heuristic.csv
"""

import os
import warnings
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.callbacks import EvalCallback, BaseCallback
from stable_baselines3.common.monitor import Monitor

from src.inventory_env import VSTInventoryEnv, build_env_from_data

warnings.filterwarnings("ignore")

MODEL_DIR   = "models"
DATA_DIR    = "data"
METRICS_DIR = "output/metrics"

# Training config
TOTAL_TIMESTEPS = 300_000   # ~5 min on CPU with 200 SKUs
N_ENVS          = 4         # parallel environments


# ── Reward tracking callback ───────────────────────────────────────────────────
class RewardLoggerCallback(BaseCallback):
    """Records mean episode reward every eval_freq steps for plotting."""
    def __init__(self, eval_freq: int = 5000, verbose: int = 0):
        super().__init__(verbose)
        self.eval_freq = eval_freq
        self.rewards: List[float] = []
        self._ep_rewards: List[float] = []

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", []):
            if "episode" in info:
                self._ep_rewards.append(info["episode"]["r"])
        if self.n_calls % self.eval_freq == 0 and self._ep_rewards:
            self.rewards.append(float(np.mean(self._ep_rewards[-50:])))
            self._ep_rewards = []
        return True


# ── Heuristic baseline ─────────────────────────────────────────────────────────
def run_heuristic_baseline(env: VSTInventoryEnv, n_episodes: int = 50) -> Dict:
    """
    Simple (s, S) reorder-point heuristic:
    - If stock < reorder_point: order 2 × weekly demand
    - Else: order nothing
    """
    total_rewards, fill_rates, stockouts = [], [], []

    for ep in range(n_episodes):
        obs, _ = env.reset()
        done, ep_reward, ep_fr, ep_so = False, 0.0, [], 0
        while not done:
            # Heuristic: action = 3 (order 2×) if stock < ~1.0 normalised, else 0
            stock_norm = float(obs[0])
            action = 3 if stock_norm < 1.0 else 0
            obs, reward, terminated, truncated, info = env.step(action)
            ep_reward += reward
            ep_fr.append(info["fill_rate"])
            if info["missed"] > 0:
                ep_so += 1
            done = terminated or truncated
        total_rewards.append(ep_reward)
        fill_rates.append(float(np.mean(ep_fr)))
        stockouts.append(ep_so)

    return {
        "mean_reward": float(np.mean(total_rewards)),
        "std_reward":  float(np.std(total_rewards)),
        "mean_fill_rate": float(np.mean(fill_rates)),
        "mean_stockouts": float(np.mean(stockouts)),
    }


# ── RL evaluation ──────────────────────────────────────────────────────────────
def evaluate_agent(
    model: PPO,
    env: VSTInventoryEnv,
    n_episodes: int = 50,
) -> Dict:
    """Evaluate trained PPO agent across n episodes."""
    total_rewards, fill_rates, stockouts = [], [], []

    for ep in range(n_episodes):
        obs, _ = env.reset()
        done, ep_reward, ep_fr, ep_so = False, 0.0, [], 0
        while not done:
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, terminated, truncated, info = env.step(int(action))
            ep_reward += reward
            ep_fr.append(info["fill_rate"])
            if info["missed"] > 0:
                ep_so += 1
            done = terminated or truncated
        total_rewards.append(ep_reward)
        fill_rates.append(float(np.mean(ep_fr)))
        stockouts.append(ep_so)

    return {
        "mean_reward":    float(np.mean(total_rewards)),
        "std_reward":     float(np.std(total_rewards)),
        "mean_fill_rate": float(np.mean(fill_rates)),
        "mean_stockouts": float(np.mean(stockouts)),
    }


# ── Training ───────────────────────────────────────────────────────────────────
def train_ppo(train_env: VSTInventoryEnv) -> Tuple[PPO, RewardLoggerCallback]:
    """Train PPO on VSTInventoryEnv. Returns (model, callback)."""

    def make_env_fn():
        env = build_env_from_data(train_mode=True)
        return Monitor(env)

    vec_env = make_vec_env(make_env_fn, n_envs=N_ENVS)

    model = PPO(
        "MlpPolicy",
        vec_env,
        learning_rate    = 3e-4,
        n_steps          = 512,
        batch_size       = 64,
        n_epochs         = 10,
        gamma            = 0.99,
        gae_lambda       = 0.95,
        clip_range       = 0.2,
        ent_coef         = 0.01,
        vf_coef          = 0.5,
        max_grad_norm    = 0.5,
        policy_kwargs    = dict(net_arch=[128, 128]),
        verbose          = 0,
        seed             = 42,
    )

    callback = RewardLoggerCallback(eval_freq=5000)
    model.learn(total_timesteps=TOTAL_TIMESTEPS, callback=callback, progress_bar=False)

    return model, callback


# ── Master runner ──────────────────────────────────────────────────────────────
def run_rl_agent(
    run_training: bool = True,
) -> Tuple[PPO, Dict, Dict, RewardLoggerCallback]:
    """
    Full RL pipeline: train PPO -> evaluate -> compare vs heuristic.
    Returns (model, rl_metrics, heuristic_metrics, training_callback).
    """
    print("  Building training environment...")
    train_env = build_env_from_data(train_mode=True)
    eval_env  = build_env_from_data(train_mode=False)

    model_path = os.path.join(MODEL_DIR, "ppo_vst_inventory")
    callback   = RewardLoggerCallback()

    if run_training:
        print(f"  Training PPO ({TOTAL_TIMESTEPS:,} timesteps, {N_ENVS} parallel envs)...")
        model, callback = train_ppo(train_env)

        os.makedirs(MODEL_DIR, exist_ok=True)
        model.save(model_path)
        print(f"  [OK] PPO model saved -> {model_path}")

        # Save training curve
        if callback.rewards:
            tc_df = pd.DataFrame({
                "checkpoint": range(len(callback.rewards)),
                "mean_reward": callback.rewards,
            })
            os.makedirs(METRICS_DIR, exist_ok=True)
            tc_df.to_csv(os.path.join(METRICS_DIR, "training_curve.csv"), index=False)

    else:
        print(f"  Loading saved model from {model_path}...")
        model = PPO.load(model_path)

    print("  Evaluating RL agent (50 episodes)...")
    rl_metrics = evaluate_agent(model, eval_env, n_episodes=50)

    print("  Running heuristic baseline (50 episodes)...")
    heuristic_metrics = run_heuristic_baseline(eval_env, n_episodes=50)

    # Comparison table
    comparison = pd.DataFrame([
        {"Method": "RL Agent (PPO)",    **rl_metrics},
        {"Method": "Heuristic (s,S)",   **heuristic_metrics},
    ])
    os.makedirs(METRICS_DIR, exist_ok=True)
    comparison.to_csv(os.path.join(METRICS_DIR, "rl_vs_heuristic.csv"), index=False)
    print(f"  [OK] Comparison -> output/metrics/rl_vs_heuristic.csv")

    return model, rl_metrics, heuristic_metrics, callback


if __name__ == "__main__":
    print("=" * 50)
    print("  Tower 2: PPO RL Inventory Agent")
    print("=" * 50)
    model, rl, heuristic, cb = run_rl_agent(run_training=True)
    print("\n  RL Agent Results:")
    for k, v in rl.items():
        print(f"    {k}: {v:.4f}")
    print("\n  Heuristic Baseline:")
    for k, v in heuristic.items():
        print(f"    {k}: {v:.4f}")
    improvement = (rl["mean_fill_rate"] - heuristic["mean_fill_rate"]) * 100
    print(f"\n  Fill Rate Improvement vs Heuristic: {improvement:+.2f}%")
