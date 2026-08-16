"""
Shared lazy Gemini client used by all Genie agents.

Why a separate module:
- Avoids every agent re-implementing the lazy `import google.generativeai`
  boilerplate.
- Centralises the model-name and API-key handling.
- Lets us swap model names in one place (e.g. `gemini-2.0-flash` -> `gemini-1.5-pro`).
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"

_model: Optional[object] = None


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

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        logger.warning("GEMINI_API_KEY not set - Genie will use offline mode")
        return None

    try:
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(DEFAULT_MODEL)
        logger.info("Gemini initialised: %s", DEFAULT_MODEL)
        return _model
    except Exception as e:
        logger.warning("Gemini init failed: %s", e)
        return None


def reset_gemini_model():
    """Test hook - drop the cached model (e.g. after key rotation)."""
    global _model
    _model = None
