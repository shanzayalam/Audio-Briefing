"""Opik configuration helpers for Audio Briefing.

This module centralizes Opik initialization and provides safe fallbacks when
Opik is unavailable or partially compatible across versions.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency fallback
    def load_dotenv(*args: Any, **kwargs: Any) -> bool:
        return False

logger = logging.getLogger(__name__)

load_dotenv()

OPIK_ENABLED = False
OPIK_INSTALLED = False


def _noop_track(name: str | None = None, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """No-op decorator used when Opik is unavailable."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        return func

    return decorator


track = _noop_track
OpikTracer = None
configure = None

try:
    from opik import configure as _opik_configure
    from opik import track as _opik_track
    from opik.integrations.langchain import OpikTracer as _opik_tracer

    configure = _opik_configure
    track = _opik_track
    OpikTracer = _opik_tracer
    OPIK_INSTALLED = True
except Exception as exc:  # pragma: no cover - defensive import guard
    logger.warning("Opik import unavailable; tracing disabled: %s", exc)


def configure_opik() -> bool:
    """Configure Opik from environment variables.

    Expected environment variables:
    - OPIK_API_KEY
    - OPIK_WORKSPACE (optional)
    - OPIK_PROJECT_NAME (optional)
    """

    global OPIK_ENABLED

    if not OPIK_INSTALLED or configure is None:
        OPIK_ENABLED = False
        return False

    api_key = os.getenv("OPIK_API_KEY")
    workspace = os.getenv("OPIK_WORKSPACE")

    if not api_key:
        logger.info("OPIK_API_KEY is not set; Opik tracing disabled")
        OPIK_ENABLED = False
        return False

    # Support multiple Opik configure signatures across versions.
    configure_kwargs = {"api_key": api_key}
    if workspace:
        configure_kwargs["workspace"] = workspace

    try:
        configure(**configure_kwargs)
        OPIK_ENABLED = True
        logger.info("Opik tracing initialized")
        return True
    except TypeError:
        try:
            configure(api_key=api_key)
            OPIK_ENABLED = True
            logger.info("Opik tracing initialized")
            return True
        except Exception as exc:
            logger.warning("Failed to initialize Opik: %s", exc)
            OPIK_ENABLED = False
            return False
    except Exception as exc:
        logger.warning("Failed to initialize Opik: %s", exc)
        OPIK_ENABLED = False
        return False


def get_langchain_tracer() -> Any:
    """Return an Opik tracer instance for LangChain/LangGraph, if enabled."""

    if not OPIK_ENABLED or OpikTracer is None:
        return None

    project_name = os.getenv("OPIK_PROJECT_NAME", "NewsBriefing")

    # Support OpikTracer constructor differences across versions.
    try:
        return OpikTracer(project_name=project_name)
    except TypeError:
        try:
            return OpikTracer()
        except Exception as exc:
            logger.warning("Failed to create Opik tracer: %s", exc)
            return None
    except Exception as exc:
        logger.warning("Failed to create Opik tracer: %s", exc)
        return None


def instrument_openai_client(client: Any) -> Any:
    """Wrap a standard OpenAI client with Opik integration when available.

    Returns the original client if Opik integration is unavailable.
    """

    if not OPIK_ENABLED:
        return client

    # Try the most common integration helper first.
    try:
        from opik.integrations.openai import track_openai  # type: ignore

        return track_openai(client)
    except Exception:
        pass

    # Fallback: some versions expose a wrapped client class.
    try:
        from opik.integrations.openai import OpenAI as OpikOpenAI  # type: ignore

        return OpikOpenAI()
    except Exception:
        logger.warning("Opik OpenAI integration unavailable; using base OpenAI client")
        return client


# Configure on import so worker and API boot paths are covered automatically.
configure_opik()


__all__ = [
    "track",
    "configure_opik",
    "get_langchain_tracer",
    "instrument_openai_client",
    "OPIK_ENABLED",
    "OPIK_INSTALLED",
]
