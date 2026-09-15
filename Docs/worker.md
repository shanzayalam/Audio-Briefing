# Worker Process (`worker.py`)

The Worker is a long-running queue consumer. It polls the Redis queue for scheduled briefing jobs, compiles the LangGraph state machine, and executes the briefing generation workflow.

## Features
- **Queue Consumer**: Leverages `rq.Worker` to poll for enqueued jobs.
- **Robust Execution**: Processes jobs asynchronously to avoid blocking the API or scheduler.
- **Workflow Compilation**: Dynamically instantiates the LangGraph pipeline with appropriate settings (e.g., words-per-minute speed and OpenAI LLM parameters).
- **Concurrency Control**: Prevents overlapping executions and maintains high throughput.

## Entry Point
- Run directly: `python worker.py`

## Configuration
- `REDIS_HOST`: Redis host name (default: `localhost`).
- `REDIS_PORT`: Redis port (default: `6379`).
- `REDIS_DB`: Redis database index (default: `0`).
