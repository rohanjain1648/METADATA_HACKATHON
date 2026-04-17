"""
LLM client — Gemini via OpenAI-compatible endpoint.
All tools import get_client() from here instead of instantiating openai directly.
"""

import os
import openai

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def get_client() -> openai.AsyncOpenAI:
    """Return an async OpenAI client pointed at the Gemini API."""
    return openai.AsyncOpenAI(
        api_key=os.environ["GEMINI_API_KEY"],
        base_url=_GEMINI_BASE_URL,
    )


def get_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
