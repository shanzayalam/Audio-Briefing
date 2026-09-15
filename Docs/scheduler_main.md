# Scheduler REST API Service (`scheduler/main.py`)

The Scheduler Service is a FastAPI application that manages schedule preferences for audio briefings. It supports creating, updating, displaying, and deleting schedules.

## Features
- **Pydantic Validation**: Strict timezone-aware and formatting checks for the `time` parameter (must be `HH:MM`).
- **Resilient Execution**: Self-healing tick loop logic that automatically purges corrupted/malformed state from Redis to prevent background loop crashes.
- **REST Endpoints**: CRUD operations for user schedules.
- **FastAPI Lifespan**: Leverages modern async context managers (`lifespan`) to manage scheduler threads gracefully.

## Ports and Endpoints
- **Running Port**: `8001` (default)
- **Path Prefix**: `/audioscheduler`
- **Key Endpoints**:
  - `POST /briefing/generate` — Schedule new briefing.
  - `GET /briefing/schedule/{user_id}` — Get briefing schedule.
  - `PUT /briefing/schedule/{user_id}` — Update schedule preferences.
  - `DELETE /briefing/schedule/{user_id}` — Cancel schedule.
  - `POST /webhook/job-completed` — Callback webhook endpoint.
  - `GET /health` — Check scheduler status.

## Configuration
- `API_BASE_URL`: Base URL of the Main API.
- `SCHEDULE_CHECK_INTERVAL_MINUTES`: Frequency of schedule checking.
- `EARLY_TRIGGER_WINDOW_MINUTES`: Allows scheduling checks up to 30 minutes early.
