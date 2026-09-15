# Automated Cron Scheduler (`scheduler/cron_scheduler.py`)

The Automated Cron Scheduler runs as a background process checking for scheduled users and orchestrating the briefing generation pipeline.

## Features
- **Cron Tick Loop**: Runs every minute (using APScheduler) to process schedules.
- **Subscription Guard**: Automatically checks and verifies if a user has an active premium/pro subscription.
- **Content Ingestion**: Fetches articles based on user source preference:
  - `saved_articles`: Ingests articles saved by the user over the last 24 hours.
  - `latest_news`: Curates the latest unread articles relevant to user interests/region.
- **Backfill Strategy**: Automatically fetches extra default/popular articles if a user has fewer than 5 available articles.

## Entry Point
- Run directly: `python scheduler/cron_scheduler.py`

## Configuration
- `MAIN_API_URL`: Destination URL to send queued briefing jobs.
- `SCHEDULER_TIMEZONE`: Timezone for cron checks (default: `UTC`).
- `CHECK_INTERVAL_MINUTES`: Time interval between ticks (default: `1`).
