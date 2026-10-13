"""Switch on LangSmith tracing from settings.

The langsmith library reads real environment variables, but pydantic-settings
only reads the .env file into the Settings object. This bridges the two.
"""
import os

from freight_intel.config import get_settings


def configure_tracing() -> bool:
    """Returns True if tracing was enabled (an API key is configured)."""
    settings = get_settings()
    if not settings.langsmith_api_key:
        return False
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    os.environ["LANGSMITH_TRACING"] = "true"
    return True
