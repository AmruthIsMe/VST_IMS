"""
Reinforcement Learning Feedback Loop for VST IMS Demand Forecasting.
Uses a bandit-style algorithm (UCB1) to adaptively re-weight models
based on observed prediction errors as reward signals.
"""

import numpy as np
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent.parent / "trained_models"
RL_STATE_FILE = MODELS_DIR / "rl_state.json"


class BanditWeightOptimizer:
    """
    Multi-armed bandit (UCB1 variant) for model weight optimization.

    Each forecasting model is an "arm". The reward for each arm is the
    negative absolute error of its prediction. Over time, the bandit
    explores models that haven't been evaluated recently and exploits
    models that consistently perform well.
    """

    def __init__(self, model_names: list[str], exploration_factor: float = 1.5):
        self.model_names = model_names
        self.exploration_factor = exploration_factor

        # Per-model statistics
        self.n_pulls: dict[str, int] = {m: 0 for m in model_names}
        self.total_reward: dict[str, float] = {m: 0.0 for m in model_names}
        self.mean_reward: dict[str, float] = {m: 0.0 for m in model_names}
        self.total_rounds = 0

        # Exponential decay parameters
        self.decay_factor = 0.95  # Recent errors weighted more heavily
        self.reward_history: list[dict] = []

        self._load_state()

    def _load_state(self):
        """Load persisted bandit state."""
        if RL_STATE_FILE.exists():
            try:
                data = json.loads(RL_STATE_FILE.read_text())
                self.n_pulls = data.get("n_pulls", self.n_pulls)
                self.total_reward = data.get("total_reward", self.total_reward)
                self.mean_reward = data.get("mean_reward", self.mean_reward)
                self.total_rounds = data.get("total_rounds", 0)
                self.reward_history = data.get("reward_history", [])
            except Exception:
                pass

    def _save_state(self):
        """Persist bandit state."""
        MODELS_DIR.mkdir(exist_ok=True)
        RL_STATE_FILE.write_text(json.dumps({
            "n_pulls": self.n_pulls,
            "total_reward": self.total_reward,
            "mean_reward": self.mean_reward,
            "total_rounds": self.total_rounds,
            "reward_history": self.reward_history[-200:],
        }, indent=2, default=str))

    def update(self, model_name: str, actual: float, predicted: float):
        """
        Update the bandit with observed (actual, predicted) for a model.
        Reward = -|error| normalized to [0, 1] range.
        """
        if model_name not in self.model_names:
            return

        error = abs(actual - predicted)
        max_val = max(abs(actual), abs(predicted), 1.0)
        reward = 1.0 - min(error / max_val, 1.0)  # Normalize to [0, 1]

        self.n_pulls[model_name] += 1
        self.total_rounds += 1

        # Exponential moving average for reward
        old_mean = self.mean_reward[model_name]
        n = self.n_pulls[model_name]
        alpha = max(1.0 / n, 1 - self.decay_factor)
        self.mean_reward[model_name] = old_mean + alpha * (reward - old_mean)
        self.total_reward[model_name] += reward

    def batch_update(
        self,
        model_errors: dict[str, list[tuple[float, float]]],
    ):
        """
        Batch update from a set of (actual, predicted) pairs per model.
        model_errors: {model_name: [(actual_1, pred_1), (actual_2, pred_2), ...]}
        """
        round_rewards = {}
        for model_name, pairs in model_errors.items():
            rewards = []
            for actual, predicted in pairs:
                self.update(model_name, actual, predicted)
                error = abs(actual - predicted)
                max_val = max(abs(actual), abs(predicted), 1.0)
                rewards.append(1.0 - min(error / max_val, 1.0))
            round_rewards[model_name] = float(np.mean(rewards)) if rewards else 0.0

        self.reward_history.append({
            "date": datetime.now().isoformat(),
            "round": self.total_rounds,
            "rewards": round_rewards,
        })
        self._save_state()

    def get_weights(self) -> dict[str, float]:
        """
        Compute ensemble weights using UCB1-inspired scoring.
        Models with higher mean reward and less exploration get higher weights.
        """
        if self.total_rounds == 0:
            # Equal weights initially
            n = len(self.model_names)
            return {m: round(1.0 / n, 4) for m in self.model_names}

        scores = {}
        for model in self.model_names:
            n = max(self.n_pulls.get(model, 0), 1)
            mean_r = self.mean_reward.get(model, 0.5)

            # UCB1 exploration bonus
            exploration = self.exploration_factor * np.sqrt(
                np.log(self.total_rounds + 1) / n
            )

            # For weight computation, we use mean_reward (not exploration)
            # Exploration is for arm selection, not weighting
            scores[model] = max(mean_r, 0.01)

        # Softmax normalization for smoother weight distribution
        max_score = max(scores.values())
        exp_scores = {m: np.exp(5 * (s - max_score)) for m, s in scores.items()}
        total = sum(exp_scores.values())

        weights = {m: round(e / total, 4) for m, e in exp_scores.items()}
        return weights

    def get_ucb_scores(self) -> dict[str, float]:
        """Get UCB1 scores for each model (for diagnostics)."""
        if self.total_rounds == 0:
            return {m: 0.0 for m in self.model_names}

        scores = {}
        for model in self.model_names:
            n = max(self.n_pulls.get(model, 0), 1)
            mean_r = self.mean_reward.get(model, 0.5)
            exploration = self.exploration_factor * np.sqrt(
                np.log(self.total_rounds + 1) / n
            )
            scores[model] = round(mean_r + exploration, 4)
        return scores

    def should_retrain(self, model_name: str, threshold: float = 0.3) -> bool:
        """
        Suggest whether a model should be retrained based on recent reward.
        Returns True if the model's mean reward is below threshold.
        """
        return self.mean_reward.get(model_name, 0.5) < threshold

    def get_diagnostics(self) -> dict:
        """Return full diagnostic information about the RL state."""
        return {
            "total_rounds": self.total_rounds,
            "n_pulls": self.n_pulls,
            "mean_rewards": {m: round(r, 4) for m, r in self.mean_reward.items()},
            "ucb_scores": self.get_ucb_scores(),
            "current_weights": self.get_weights(),
            "models_needing_retrain": [
                m for m in self.model_names if self.should_retrain(m)
            ],
            "recent_history": self.reward_history[-10:],
        }


class ForecastFeedbackLoop:
    """
    Orchestrates the RL feedback loop:
    1. After actuals are observed, compare against predictions
    2. Update bandit weights
    3. Feed fluctuation features back into models
    4. Signal which models need retraining
    """

    def __init__(self, model_names: list[str]):
        self.optimizer = BanditWeightOptimizer(model_names)
        self.fluctuation_history: list[dict] = []

    def record_feedback(
        self,
        model_predictions: dict[str, float],
        actual_value: float,
        sku_id: str,
        date: str,
    ):
        """Record a single observation's feedback across all models."""
        model_errors = {}
        for model_name, predicted in model_predictions.items():
            model_errors[model_name] = [(actual_value, predicted)]

        self.optimizer.batch_update(model_errors)

        # Track fluctuation magnitude
        mean_pred = np.mean(list(model_predictions.values()))
        fluctuation = abs(actual_value - mean_pred) / max(mean_pred, 1)
        self.fluctuation_history.append({
            "date": date,
            "sku_id": sku_id,
            "actual": actual_value,
            "mean_prediction": float(mean_pred),
            "fluctuation": float(fluctuation),
        })

    def get_fluctuation_features(self, n_recent: int = 4) -> dict:
        """
        Extract recent fluctuation patterns to feed back into models.
        Returns features that capture recent prediction error patterns.
        """
        if not self.fluctuation_history:
            return {
                "mean_fluctuation": 0.0,
                "max_fluctuation": 0.0,
                "fluctuation_trend": 0.0,
                "n_high_fluctuation": 0,
            }

        recent = self.fluctuation_history[-n_recent:]
        flucts = [r["fluctuation"] for r in recent]

        return {
            "mean_fluctuation": float(np.mean(flucts)),
            "max_fluctuation": float(np.max(flucts)),
            "fluctuation_trend": float(flucts[-1] - flucts[0]) if len(flucts) > 1 else 0.0,
            "n_high_fluctuation": int(sum(1 for f in flucts if f > 0.3)),
        }

    def get_updated_weights(self) -> dict[str, float]:
        """Get current model weights from the bandit optimizer."""
        return self.optimizer.get_weights()

    def get_retrain_suggestions(self) -> list[str]:
        """Get list of models that should be retrained based on RL feedback."""
        return [
            m for m in self.optimizer.model_names
            if self.optimizer.should_retrain(m)
        ]


# Singleton
_feedback_loop: Optional[ForecastFeedbackLoop] = None


def get_feedback_loop(model_names: list[str] = None) -> ForecastFeedbackLoop:
    """Get or create the singleton feedback loop."""
    global _feedback_loop
    if _feedback_loop is None:
        names = model_names or ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]
        _feedback_loop = ForecastFeedbackLoop(names)
    return _feedback_loop
