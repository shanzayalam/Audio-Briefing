# Main API Server (`api/main.py`)

The Main API Server handles job submissions, maintains the Redis task queues, provides queue health monitoring, and manages the Dead Letter Queue (DLQ).

## Features
- **Job Submission**: Receives raw briefing requests, validates the requests, and queues them for processing.
- **Queue Management**: Integrates with `rq` (Redis Queue) to enqueue and monitor jobs.
- **Health Checks**: Monitors connection statuses for Redis and MongoDB.
- **Dead Letter Queue (DLQ)**: Implements automated routing and isolation for persistently failing tasks.

## Ports and Endpoints
- **Running Port**: `8002` (default)
- **Path Prefix**: `/briefings`
- **Key Endpoints**:
  - `GET /` — API root information.
  - `GET /health` — Check Redis and DB health.
  - `POST /submit` — Submit a new briefing request.
  - `GET /jobs/{job_id}` — Check specific job status and download link.

## Configuration
- `REDIS_HOST`: Redis host name (default: `localhost`).
- `REDIS_PORT`: Redis port (default: `6379`).
- `S3_BUCKET_NAME`: AWS S3 bucket name for uploads.
- `S3_ENABLED`: Set to `true` to construct and return canonical S3 URLs.
