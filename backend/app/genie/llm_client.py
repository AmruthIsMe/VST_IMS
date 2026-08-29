"""
Shared lazy Gemini client used by all Genie agents.

Why a separate module:
- Avoids every agent re-implementing the lazy `import google.generativeai`
  boilerplate.
- Centralises the model-name and API-key handling.
- Lets us swap model names in one place.

Key resolution order:
  1. GEMINI_API_KEY environment variable (production / shell export)
  2. backend/.env file via pydantic Settings (local dev)

If no key or SDK is available the caller falls back to deterministic
rule-based mode — Genie never hard-fails because of a missing key.
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

MODEL_CANDIDATES = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

_model: Optional[object] = None


def _resolve_api_key() -> str:
    """Find the Gemini API key: env var first, then backend/.env."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        return api_key
    try:
        from app.config import get_settings

        api_key = (getattr(get_settings(), "GEMINI_API_KEY", "") or "").strip()
    except Exception:
        pass
    return api_key


def get_gemini_model():
    """Return a configured Gemini GenerativeModel, or None if unavailable."""
    global _model
    if _model is not None:
        return _model

    try:
        import google.generativeai as genai
    except ImportError:
        logger.warning("google-generativeai not installed - Genie will use offline mode")
        return None

    api_key = _resolve_api_key()
    if not api_key:
        logger.warning("GEMINI_API_KEY not set - Genie will use offline mode")
        return None

    try:
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(MODEL_CANDIDATES[0])
        logger.info("Gemini initialised: %s", MODEL_CANDIDATES[0])
        return _model
    except Exception as e:
        logger.warning("Gemini init failed: %s", e)
        return None


def reset_gemini_model():
    """Test hook - drop the cached model (e.g. after key rotation)."""
    global _model
    _model = None
