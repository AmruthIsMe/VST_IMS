"""
Training Progress Tracker
Provides real-time per-model training status for the frontend polling endpoint.
"""
import time
import threading
from datetime import datetime
from typing import Optional

_lock = threading.Lock()

_state = {
    "status": "idle",
    "started_at": None,
    "completed_at": None,
    "current_model": None,
    "models_completed": 0,
    "total_models": 6,
    "elapsed_seconds": 0,
    "models": {},
    "error": None,
}

ALL_MODELS = ["xgboost", "lightgbm", "arima", "sarima", "prophet", "holt_winters"]


def reset():
    with _lock:
        _state.update({
            "status": "idle",
            "started_at": None,
            "completed_at": None,
            "current_model": None,
            "models_completed": 0,
            "total_models": 6,
            "elapsed_seconds": 0,
            "models": {},
            "error": None,
        })


def start_training():
    with _lock:
        _state.update({
            "status": "training",
            "started_at": datetime.now().isoformat(),
            "completed_at": None,
            "current_model": None,
            "models_completed": 0,
            "total_models": 6,
            "elapsed_seconds": 0,
            "models": {},
            "error": None,
        })


def begin_model(model_name: str):
    with _lock:
        _state["current_model"] = model_name
        _state["models"][model_name] = {
            "status": "training",
            "started_at": time.time(),
            "completed_at": None,
            "elapsed_seconds": 0,
            "metrics": {},
            "error": None,
        }


def complete_model(model_name: str, metrics: dict = None, error: str = None):
    with _lock:
        now = time.time()
        m = _state["models"].get(model_name, {})
        m["completed_at"] = now
        m["elapsed_seconds"] = round(now - m.get("started_at", now), 2)
        if error:
            m["status"] = "failed"
            m["error"] = error
        else:
            m["status"] = "completed"
            m["metrics"] = metrics or {}
        _state["models"][model_name] = m
        _state["models_completed"] = sum(
            1 for v in _state["models"].values() if v["status"] in ("completed", "failed")
        )
        if _state["started_at"]:
            started = datetime.fromisoformat(_state["started_at"])
            _state["elapsed_seconds"] = round((datetime.now() - started).total_seconds(), 1)


def complete_training(error: str = None):
    with _lock:
        _state["completed_at"] = datetime.now().isoformat()
        _state["current_model"] = None
        _state["status"] = "completed" if not error else "failed"
        _state["error"] = error
        if _state["started_at"]:
            started = datetime.fromisoformat(_state["started_at"])
            _state["elapsed_seconds"] = round((datetime.now() - started).total_seconds(), 1)


def get_status() -> dict:
    with _lock:
        return {
            "status": _state["status"],
            "started_at": _state["started_at"],
            "completed_at": _state["completed_at"],
            "current_model": _state["current_model"],
            "models_completed": _state["models_completed"],
            "total_models": _state["total_models"],
            "elapsed_seconds": _state["elapsed_seconds"],
            "models": {
                name: {
                    "status": info["status"],
                    "elapsed_seconds": info["elapsed_seconds"],
                    "metrics": info["metrics"],
                    "error": info["error"],
                }
                for name, info in _state["models"].items()
            },
            "error": _state["error"],
        }
