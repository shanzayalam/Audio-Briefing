"""
Root conftest.py for the audio_briefing test suite.

This file is loaded by pytest BEFORE any test module is imported.
It intercepts and stubs out all external dependencies (Redis, logger_config)
so that importing scheduler.main never hangs or fails in CI/CD.
"""

print("DEBUG: LOADING ROOT CONFTEST")

import sys
import os
from unittest.mock import MagicMock

# ──────────────────────────────────────────────────────────────────────────────
# 1. Ensure the project root is always on sys.path
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
print(f"DEBUG: PROJECT_ROOT = {PROJECT_ROOT}")
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"DEBUG: sys.path = {sys.path}")

# ──────────────────────────────────────────────────────────────────────────────
# 2. Stub out redis BEFORE any scheduler module is imported.
#    This prevents redis.Redis().ping() from blocking on connection.
# ──────────────────────────────────────────────────────────────────────────────
_mock_redis_instance = MagicMock()
_mock_redis_instance.ping.return_value = True      # simulate successful ping

_mock_redis_module = MagicMock()
_mock_redis_module.Redis.return_value = _mock_redis_instance

sys.modules["redis"] = _mock_redis_module

# Expose the shared mock instance for use in individual test modules
# (imported via:  from conftest import mock_redis_instance)
mock_redis_instance = _mock_redis_instance

# ──────────────────────────────────────────────────────────────────────────────
# 3. Stub out logger_config so its file-based setup never runs during tests.
# ──────────────────────────────────────────────────────────────────────────────
import logging

_mock_logger_config = MagicMock()
_mock_logger_config.setup_logger.return_value = logging.getLogger("test")
sys.modules["logger_config"] = _mock_logger_config

# ──────────────────────────────────────────────────────────────────────────────
# 4. Stub out user_service (used by cron_scheduler) to avoid DB calls.
# ──────────────────────────────────────────────────────────────────────────────
_mock_user_service = MagicMock()
sys.modules["user_service"] = _mock_user_service

# ──────────────────────────────────────────────────────────────────────────────
# 5. Stub out APScheduler to prevent real background threads from starting
# ──────────────────────────────────────────────────────────────────────────────
_mock_apscheduler_module = MagicMock()
sys.modules["apscheduler.schedulers.background"] = _mock_apscheduler_module
sys.modules["apscheduler.triggers.cron"] = MagicMock()

