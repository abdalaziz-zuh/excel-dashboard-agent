"""
groq_client.py
Single shared place for getting a Groq client, used by report_agent.py,
suggestion_agent.py, and design_agent.py. Previously each file had its own
copy-pasted version of this — which is exactly how the deprecated-model
bug (all three still pointing at a retired model id) went unnoticed for a
while. One copy now; fix it once, fixed everywhere.

DEFAULT_MODEL is likewise centralized — check
https://console.groq.com/docs/models for the current list before changing
it, and https://console.groq.com/docs/deprecations if calls start silently
failing again (see get_api_key/get_groq_client — failures are no longer
silent in the calling code, but the model id itself doesn't self-update).
"""

import os

DEFAULT_MODEL = "openai/gpt-oss-120b"


def get_api_key() -> str | None:
    """Checks Streamlit secrets first (works on Streamlit Cloud even if a
    secret isn't mirrored into os.environ), then falls back to a plain
    environment variable (works for the CLI automation_runner.py, which
    never imports streamlit)."""
    try:
        import streamlit as st
        key = st.secrets.get("GROQ_API_KEY")
        if key:
            return key
    except Exception:
        pass
    return os.environ.get("GROQ_API_KEY")


def get_groq_client():
    api_key = get_api_key()
    if not api_key:
        return None
    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception:
        return None
