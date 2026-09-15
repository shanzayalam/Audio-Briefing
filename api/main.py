"""
Audio Briefing API Server - Queue Management & Job Submission

Main API server that:
1. Accepts briefing job submissions
2. Pushes jobs to Redis queue
3. Provides queue monitoring endpoints
4. Manages Dead Letter Queue (DLQ)
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import redis
import json
import uuid
import os
from rq import Queue
from rq.job import Job
from logger_config import setup_logger

# Setup logger
logger = setup_logger(__name__)

# S3 Configuration for URL construction
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
S3_ENABLED = os.getenv("S3_ENABLED", "false").lower() == "true"


def ensure_s3_url(audio_path: Optional[str], user_id: Optional[str] = None, job_id: Optional[str] = None) -> Optional[str]:
    """
    Ensure audio path is a full S3 URL
    
    If it's a local path and S3 is enabled:
    1. If user_id and job_id are provided, construct the CANONICAL nested S3 URL.
    2. Otherwise, return the local path (to avoid broken URLs).
    
    Args:
        audio_path: Local path or S3 URL
        user_id: User identifier (optional, for reconstruction)
        job_id: Job/Request identifier (optional, for reconstruction)
        
    Returns:
        Full S3 URL or original path
    """
    if not audio_path:
        return None
    
    # Already a full URL
    if audio_path.startswith('http://') or audio_path.startswith('https://'):
        return audio_path
    
    # Local path - construct S3 URL if S3 is enabled
    if S3_ENABLED and S3_BUCKET_NAME:
        # If we have the IDs, we can reconstruct the CORRECT nested path
        # expected by s3_uploader.py: briefings/{user_id}/{job_id}.ext
        if user_id and job_id:
            # Extract extension from the local path
            import os
            ext = os.path.splitext(audio_path)[1]
            if not ext:
                ext = ".mp3" # Default
            
            s3_key = f"briefings/{user_id}/{job_id}{ext}"
            return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"

        # If we don't have IDs, fall back to checking if we can safely reconstruct
        # Remove 'output/' prefix if present
        s3_key = audio_path.replace('output/', '', 1) if audio_path.startswith('output/') else audio_path
        
        # Do not blindly append local flat filenames
        if "/" not in s3_key and s3_key.startswith("briefing_"):
             return audio_path

        return f"https://{S3_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{s3_key}"
    
    # Return original path
    return audio_path

app = FastAPI(
    title="Audio Briefing API",
    description="Queue management and job submission for audio briefing generation",
    version="1.0.0",
    root_path="/audioapi"  # Path-based routing prefix
)

# CORS middleware
# When allow_credentials=True, we cannot use allow_origins=["*"]
# We must specify exact origins
cors_origins = os.getenv("CORS_ORIGINS", "https://api.propt.global,http://localhost:3000,http://localhost:8000").split(",")
cors_origins = [origin.strip() for origin in cors_origins if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis connections
# RQ needs binary connection (for pickle), metadata needs decoded connection
from urllib.parse import urlparse

# Auto-detect environment: use REDIS_URL for ECS, fallback to localhost for local testing
redis_url = os.getenv('REDIS_URL')
if redis_url:
    # ECS environment - parse ElastiCache URL
    parsed = urlparse(redis_url)
    redis_host = parsed.hostname
    redis_port = parsed.port or 6379
    redis_db = int(parsed.path.lstrip('/')) if parsed.path and parsed.path != '/' else 0
else:
    # Local testing environment
    redis_host = os.getenv('REDIS_HOST', 'localhost')
    redis_port = int(os.getenv('REDIS_PORT', 6379))
    redis_db = 0

redis_conn = redis.Redis(host=redis_host, port=redis_port, db=redis_db)  # Binary for RQ
redis_metadata = redis.Redis(host=redis_host, port=redis_port, db=redis_db, decode_responses=True)  # Decoded for metadata

# RQ Queues
main_queue = Queue('newsagent_jobs', connection=redis_conn)
dlq = Queue('newsagent_dlq', connection=redis_conn)


# Pydantic Models
class Article(BaseModel):
    id: Optional[int] = None
    title: str
    content: str
    source: Optional[str] = None
    published_date: Optional[str] = None
    category: Optional[str] = None
    importance_score: Optional[float] = None


class BriefingJobRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    articles: List[Article] = Field(default_factory=list, description="List of articles to process (can be empty if fetch_articles=True)")
    target_duration: int = Field(300, description="Target duration in seconds (180/300/600/900/1200)")
    tts_provider: str = Field("openai", description="TTS provider (openai/gtts/elevenlabs/edge/silero/pyttsx3/kokoro)")
    tts_voice: Optional[str] = Field("marin", description="Voice ID for TTS. Options: OpenAI standard (alloy, echo, fable, onyx, nova, shimmer) or gpt-4o-mini-tts (marin, cedar). Default: marin")
    audio_format: str = Field("aac", description="Audio format (aac/mp3/opus/flac/wav) - aac recommended for streaming")
    add_music: bool = Field(False, description="Add background music")
    domain: str = Field("general", description="Content domain")
    notification_webhook: Optional[str] = Field(None, description="Webhook URL for completion notification")
    notification_email: Optional[str] = Field(None, description="Email for notification")
    fetch_articles: bool = Field(False, description="If True, worker will fetch fresh articles from content delivery API")
    device_info: Optional[Dict[str, Any]] = Field(default=None, description="Device information for article fetching")


class BriefingJobResponse(BaseModel):
    job_id: str
    request_id: str
    status: str
    message: str
    queued_at: str


class QueueStatusResponse(BaseModel):
    main_queue: Dict[str, int]
    dlq: Dict[str, int]
    total_jobs: int


class JobItem(BaseModel):
    job_id: str
    request_id: str
    user_id: str
    status: str
    created_at: str
    enqueued_at: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    error: Optional[str]


class BriefingResponse(BaseModel):
    briefing_id: str
    user_id: str
    title: str
    audio_url: str
    transcript: str
    duration: Optional[int] = None
    created_at: str

def _generate_title(created_at: str) -> str:
    """Generate friendly title from creation date e.g. 'Daily News Briefing Friday 16 January'"""
    try:
        # Handle formats with or without microseconds
        if "." in created_at:
             dt = datetime.fromisoformat(created_at)
        else:
             dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
             
        # Format: Friday 16 January
        date_str = dt.strftime("%A %d %B")
        return f"Daily News Briefing {date_str}"
    except Exception:
        return "Daily News Briefing"


class PushNotificationRequest(BaseModel):
    user_id: str = Field(..., description="User identifier to send notification to")
    title: str = Field(..., description="Notification title")
    body: str = Field(..., description="Notification body/message")
    data: Optional[Dict[str, Any]] = Field(None, description="Additional data payload")
    device_tokens: Optional[List[str]] = Field(None, description="Specific device tokens (FCM/APNS)")
    topic: Optional[str] = Field(None, description="Topic/channel for broadcast notifications")


class PushNotificationResponse(BaseModel):
    success: bool
    message: str
    sent_count: int
    failed_count: int
    details: Optional[Dict[str, Any]] = None


@app.get("/")
def root():
    """API root endpoint"""
    return {
        "service": "Audio Briefing API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "GET /health",
            "submit_job": "POST /briefing/submit",
            "get_briefing": "GET /briefings/{briefing_id}",
            "queue_status": "GET /queue/status",
            "main_queue_items": "GET /queue/main/items",
            "dlq_items": "GET /queue/dlq/items",
            "requeue_job": "POST /queue/dlq/requeue/{job_id}",
            "requeue_all": "POST /queue/dlq/requeue-all",
            "push_notification": "POST /notifications/push"
        }
    }


@app.get("/health")
def health_check():
    """
    Health check endpoint for ECS/load balancer
    
    Returns 200 if service is healthy, 503 if unhealthy
    Checks Redis and MongoDB connectivity
    """
    health_status = {
        "status": "healthy",
        "service": "audio-briefing-api",
        "timestamp": datetime.now().isoformat(),
        "redis": "unknown",
        "mongodb": "unknown",
        "queue_size": 0
    }
    
    issues = []
    
    try:
        # Check Redis connection
        redis_metadata.ping()
        health_status["redis"] = "connected"
        health_status["queue_size"] = len(main_queue)
    except Exception as e:
        health_status["redis"] = "disconnected"
        issues.append(f"Redis: {str(e)}")
    
    try:
        # Check MongoDB connection
        from mongodb_client import get_mongo_client
        mongo = get_mongo_client()
        if mongo.is_connected:
            health_status["mongodb"] = "connected"
        else:
            health_status["mongodb"] = "not_configured"
    except Exception as e:
        health_status["mongodb"] = "error"
        issues.append(f"MongoDB: {str(e)}")
    
    # Return unhealthy if Redis is down (critical)
    if health_status["redis"] != "connected":
        health_status["status"] = "unhealthy"
        health_status["issues"] = issues
        raise HTTPException(
            status_code=503,
            detail=health_status
        )
    
    # MongoDB is optional, log warning but don't fail
    if issues:
        health_status["warnings"] = issues
    
    return health_status


@app.get("/briefings/{briefing_id}", response_model=BriefingResponse)
async def get_briefing(briefing_id: str):
    """
    Get briefing details by ID
    
    Returns audio URL (S3), transcript, and metadata for streaming/playback.
    Checks Redis first (fast), then MongoDB (persistent) if not in Redis.
    """
    try:
        # Try Redis first (7-day cache)
        briefing_key = f"briefing:{briefing_id}:data"
        briefing_data = redis_metadata.get(briefing_key)
        
        if briefing_data:
            data = json.loads(briefing_data)
        else:
            # Not in Redis, check MongoDB for permanent record
            try:
                from mongodb_client import get_briefing
                data = get_briefing(briefing_id)
                
                if not data:
                    raise HTTPException(
                        status_code=404, 
                        detail=f"Briefing not found: {briefing_id}"
                    )
                
                # Cache back to Redis for future requests
                redis_metadata.set(
                    briefing_key,
                    json.dumps({
                        "user_id": data.get("user_id"),
                        "audio_url": data.get("audio_url"),
                        "transcript": data.get("transcript"),
                        "duration": data.get("duration"),
                        "created_at": data.get("created_at")
                    }),
                    ex=604800  # 7 days
                )
                
            except ImportError:
                # MongoDB not configured
                raise HTTPException(
                    status_code=404, 
                    detail=f"Briefing not found: {briefing_id}"
                )
        
        # Return briefing response
        return BriefingResponse(
            briefing_id=briefing_id,
            user_id=data.get("user_id"),
            title=_generate_title(data.get("created_at", "")),
            audio_url=ensure_s3_url(data.get("audio_url"), data.get("user_id"), briefing_id),
            transcript=data.get("transcript"),
            duration=data.get("duration"),
            created_at=data.get("created_at")
        )
        
    except HTTPException:
        raise
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail="Failed to parse briefing data"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve briefing: {str(e)}"
        )


@app.post("/briefing/submit", response_model=BriefingJobResponse)
async def submit_briefing_job(job_request: BriefingJobRequest):
    """
    Submit a briefing job to the queue
    
    The job will be processed by a worker and results will be sent to the notification endpoint.
    """
    try:
        # Generate IDs
        request_id = str(uuid.uuid4())
        
        logger.info(
            "Received job submission",
            extra={
                "user_id": job_request.user_id,
                "articles_count": len(job_request.articles),
                "fetch_articles": job_request.fetch_articles,
                "has_device_info": job_request.device_info is not None
            }
        )
        
        # DEBUG: Print what we're receiving
        print(f"[DEBUG] job_request.fetch_articles = {job_request.fetch_articles}")
        print(f"[DEBUG] job_request.device_info = {job_request.device_info}")
        
        # Prepare job payload
        job_payload = {
            "request_id": request_id,
            "user_id": job_request.user_id,
            "articles": [article.model_dump() for article in job_request.articles],
            "urls": [],
            "target_duration": job_request.target_duration,
            "tts_provider": job_request.tts_provider,
            "tts_voice": job_request.tts_voice,
            "audio_format": job_request.audio_format,
            "add_music": job_request.add_music,
            "music_file": None,
            "domain": job_request.domain,
            "notification_webhook": job_request.notification_webhook,
            "notification_email": job_request.notification_email,
            "fetch_articles": job_request.fetch_articles,
            "device_info": job_request.device_info,
            "status": "pending",
            "error": None,
            "completed_at": None,
            "submitted_at": datetime.now().isoformat()
        }
        
        # DEBUG: Print what we're storing
        print(f"[DEBUG] job_payload['fetch_articles'] = {job_payload['fetch_articles']}")
        print(f"[DEBUG] job_payload['device_info'] = {job_payload['device_info']}")
        
        # Enqueue job 
        job = main_queue.enqueue(
            'worker.process_briefing_job',
            job_payload,
            job_timeout=None,  # Disable timeout (SIGALRM not supported on Windows)
            result_ttl=86400,  # Keep results for 24 hours
            failure_ttl=86400
        )
        
        logger.info(f"Job enqueued successfully", extra={"job_id": job.id, "user_id": job_request.user_id})
        
        # Store job metadata in Redis
        job_metadata = {
            "job_id": job.id,
            "request_id": request_id,
            "user_id": job_request.user_id,
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "enqueued_at": datetime.now().isoformat()
        }
        redis_metadata.set(f"job:{job.id}:metadata", json.dumps(job_metadata), ex=86400)
        
        return BriefingJobResponse(
            job_id=job.id,
            request_id=request_id,
            status="queued",
            message="Job successfully queued for processing",
            queued_at=datetime.now().isoformat()
        )
        
    except Exception as e:
        logger.error(
            f"Error enqueueing job: {str(e)}",
            extra={"error_type": type(e).__name__, "user_id": job_request.user_id}
        )
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to enqueue job: {str(e)}")


@app.post("/job/{job_id}/execute")
async def execute_job_immediately(job_id: str):
    """
    Execute a job immediately (bypass queue and run synchronously)
    
    This endpoint retrieves a job from Redis queue and executes it immediately
    in the current process. Useful for manual/immediate execution without waiting
    for worker to pick it up.
    
    Args:
        job_id: The job ID to execute
        
    Returns:
        Execution result with status and output details
    """
    try:
        logger.info(f"Immediate execution requested for job: {job_id}")
        
        # Get job from Redis
        job = Job.fetch(job_id, connection=redis_conn)
        
        if not job:
            raise HTTPException(
                status_code=404,
                detail=f"Job not found: {job_id}"
            )
        
        # Check job status
        if job.is_finished:
            logger.info(f"Job {job_id} already completed")
            return {
                "job_id": job_id,
                "status": "already_completed",
                "message": "Job was already completed",
                "result": job.result
            }
        
        if job.is_failed:
            logger.warning(f"Job {job_id} previously failed")
            return {
                "job_id": job_id,
                "status": "previously_failed",
                "message": "Job previously failed",
                "error": str(job.exc_info) if job.exc_info else "Unknown error"
            }
        
        if job.is_started:
            logger.warning(f"Job {job_id} is currently running")
            return {
                "job_id": job_id,
                "status": "already_running",
                "message": "Job is currently being processed by a worker"
            }
        
        # Get job payload
        job_payload = job.args[0] if job.args else {}
        
        if not job_payload:
            raise HTTPException(
                status_code=400,
                detail="Job has no payload to execute"
            )
        
        logger.info(
            f"Executing job immediately",
            extra={
                "job_id": job_id,
                "user_id": job_payload.get("user_id"),
                "request_id": job_payload.get("request_id")
            }
        )
        
        # Import and execute the job function
        from worker import process_briefing_job
        
        # Execute the job (this will run synchronously)
        result = process_briefing_job(job_payload)
        
        # Update job status in Redis
        job.set_status('finished')
        job._result = result
        job.save()
        
        logger.info(
            f"Job executed successfully",
            extra={
                "job_id": job_id,
                "status": result.get("status")
            }
        )
        
        return {
            "job_id": job_id,
            "status": "executed",
            "message": "Job executed successfully",
            "result": result
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error executing job immediately: {str(e)}",
            extra={"job_id": job_id, "error_type": type(e).__name__}
        )
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to execute job: {str(e)}"
        )


@app.get("/queue/status", response_model=QueueStatusResponse)
async def get_queue_status():
    """
    Get current status of all queues
    
    Returns counts for queued, started, finished, and failed jobs in both main and DLQ.
    """
    try:
        main_stats = {
            "queued": len(main_queue),
            "started": main_queue.started_job_registry.count,
            "finished": main_queue.finished_job_registry.count,
            "failed": main_queue.failed_job_registry.count
        }
        
        dlq_stats = {
            "queued": len(dlq),
            "started": dlq.started_job_registry.count,
            "finished": dlq.finished_job_registry.count,
            "failed": dlq.failed_job_registry.count
        }
        
        total = sum(main_stats.values()) + sum(dlq_stats.values())
        
        return QueueStatusResponse(
            main_queue=main_stats,
            dlq=dlq_stats,
            total_jobs=total
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get queue status: {str(e)}")


@app.get("/queue/main/items", response_model=List[JobItem])
async def get_main_queue_items():
    """
    Get all items currently in the main queue
    
    Returns list of jobs with their metadata.
    """
    try:
        jobs = main_queue.jobs
        items = []
        
        for job in jobs:
            metadata_key = f"job:{job.id}:metadata"
            metadata_json = redis_metadata.get(metadata_key)
            
            if metadata_json:
                metadata = json.loads(metadata_json)
                items.append(JobItem(
                    job_id=job.id,
                    request_id=metadata.get("request_id", "unknown"),
                    user_id=metadata.get("user_id", "unknown"),
                    status=job.get_status(),
                    created_at=metadata.get("created_at", ""),
                    enqueued_at=metadata.get("enqueued_at"),
                    started_at=metadata.get("started_at"),
                    ended_at=metadata.get("ended_at"),
                    error=None
                ))
        
        return items
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get main queue items: {str(e)}")


@app.get("/queue/dlq/items", response_model=List[JobItem])
async def get_dlq_items():
    """
    Get all items in the Dead Letter Queue (failed jobs)
    
    Returns list of failed jobs with error details.
    """
    try:
        failed_jobs = main_queue.failed_job_registry.get_job_ids()
        items = []
        
        for job_id in failed_jobs:
            job = Job.fetch(job_id, connection=redis_conn)
            metadata_key = f"job:{job_id}:metadata"
            metadata_json = redis_metadata.get(metadata_key)
            
            metadata = json.loads(metadata_json) if metadata_json else {}
            
            items.append(JobItem(
                job_id=job_id,
                request_id=metadata.get("request_id", "unknown"),
                user_id=metadata.get("user_id", "unknown"),
                status="failed",
                created_at=metadata.get("created_at", ""),
                enqueued_at=metadata.get("enqueued_at"),
                started_at=metadata.get("started_at"),
                ended_at=metadata.get("ended_at"),
                error=job.exc_info if hasattr(job, 'exc_info') else None
            ))
        
        return items
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get DLQ items: {str(e)}")


@app.post("/queue/dlq/requeue/{job_id}")
async def requeue_failed_job(job_id: str):
    """
    Requeue a specific failed job from DLQ back to main queue
    
    The job will be retried with the same parameters.
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        
        if job.get_status() != 'failed':
            raise HTTPException(status_code=400, detail=f"Job {job_id} is not in failed state")
        
        # Requeue the job
        main_queue.failed_job_registry.remove(job)
        job.set_status('queued')
        main_queue.enqueue_job(job)
        
        return {
            "job_id": job_id,
            "status": "requeued",
            "message": f"Job {job_id} has been requeued successfully"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to requeue job: {str(e)}")


@app.post("/queue/dlq/requeue-all")
async def requeue_all_failed_jobs():
    """
    Requeue all failed jobs from DLQ back to main queue
    
    Useful for recovering from temporary failures or after fixes.
    """
    try:
        failed_jobs = main_queue.failed_job_registry.get_job_ids()
        requeued_count = 0
        errors = []
        
        for job_id in failed_jobs:
            try:
                job = Job.fetch(job_id, connection=redis_conn)
                main_queue.failed_job_registry.remove(job)
                job.set_status('queued')
                main_queue.enqueue_job(job)
                requeued_count += 1
            except Exception as e:
                errors.append(f"Job {job_id}: {str(e)}")
        
        return {
            "total_failed": len(failed_jobs),
            "requeued": requeued_count,
            "errors": errors,
            "message": f"Successfully requeued {requeued_count} out of {len(failed_jobs)} jobs"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to requeue all jobs: {str(e)}")


@app.get("/job/{job_id}/status")
async def get_job_status(job_id: str):
    """
    Get status of a specific job
    
    Returns detailed information about the job including current state and results.
    """
    try:
        job = Job.fetch(job_id, connection=redis_conn)
        metadata_key = f"job:{job_id}:metadata"
        metadata_json = redis_metadata.get(metadata_key)
        metadata = json.loads(metadata_json) if metadata_json else {}
        
        return {
            "job_id": job_id,
            "request_id": metadata.get("request_id", "unknown"),
            "user_id": metadata.get("user_id", "unknown"),
            "status": job.get_status(),
            "created_at": metadata.get("created_at"),
            "enqueued_at": metadata.get("enqueued_at"),
            "started_at": metadata.get("started_at"),
            "ended_at": metadata.get("ended_at"),
            "result": job.result if job.is_finished else None,
            "error": job.exc_info if job.is_failed else None
        }
        
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Job not found: {str(e)}")


@app.post("/notifications/push", response_model=PushNotificationResponse)
async def send_push_notification(notification: PushNotificationRequest):
    """
    Send push notifications to users
    
    Supports:
    - Device tokens (FCM, APNS, etc.)
    - Topic-based broadcasting
    - Custom data payloads
    
    Integration guide:
    - FCM (Firebase): Set FIREBASE_CREDENTIALS_PATH in .env
    - OneSignal: Set ONESIGNAL_API_KEY and ONESIGNAL_APP_ID
    - Custom: Implement your own notification service
    """
    try:
        logger.info(
            "Sending push notification",
            extra={
                "user_id": notification.user_id,
                "title": notification.title,
                "body": notification.body[:100]
            }
        )
        
        sent_count = 0
        failed_count = 0
        details = {}
        
        # TODO: Integrate with your push notification service
        # Example integrations:
        
        # Option 1: Firebase Cloud Messaging (FCM)
        # from firebase_admin import messaging
        # if notification.device_tokens:
        #     message = messaging.MulticastMessage(
        #         notification=messaging.Notification(
        #             title=notification.title,
        #             body=notification.body
        #         ),
        #         data=notification.data or {},
        #         tokens=notification.device_tokens
        #     )
        #     response = messaging.send_multicast(message)
        #     sent_count = response.success_count
        #     failed_count = response.failure_count
        
        # Option 2: OneSignal
        # import requests
        # response = requests.post(
        #     "https://onesignal.com/api/v1/notifications",
        #     headers={
        #         "Authorization": f"Basic {ONESIGNAL_API_KEY}",
        #         "Content-Type": "application/json"
        #     },
        #     json={
        #         "app_id": ONESIGNAL_APP_ID,
        #         "headings": {"en": notification.title},
        #         "contents": {"en": notification.body},
        #         "include_player_ids": notification.device_tokens,
        #         "data": notification.data
        #     }
        # )
        
        # For now, store notification in Redis for webhook/polling
        notification_id = str(uuid.uuid4())
        notification_data = {
            "notification_id": notification_id,
            "user_id": notification.user_id,
            "title": notification.title,
            "body": notification.body,
            "data": notification.data or {},
            "created_at": datetime.now().isoformat(),
            "status": "sent"
        }
        
        # Store in Redis with 24-hour expiry
        redis_metadata.set(
            f"notification:{notification.user_id}:{notification_id}",
            json.dumps(notification_data),
            ex=86400
        )
        
        # Add to user's notification queue
        redis_metadata.lpush(f"notifications:{notification.user_id}", notification_id)
        redis_metadata.expire(f"notifications:{notification.user_id}", 86400)
        
        sent_count = len(notification.device_tokens) if notification.device_tokens else 1
        
        logger.info(f"Push notification stored", extra={"notification_id": notification_id, "user_id": notification.user_id})
        
        details = {
            "notification_id": notification_id,
            "timestamp": datetime.now().isoformat(),
            "delivery_method": "redis_queue",
            "note": "Configure FCM/OneSignal for actual push delivery"
        }
        
        return PushNotificationResponse(
            success=True,
            message="Push notification sent successfully",
            sent_count=sent_count,
            failed_count=failed_count,
            details=details
        )
        
    except Exception as e:
        logger.error(
            f"Push notification error: {str(e)}",
            extra={"error_type": type(e).__name__}
        )
        raise HTTPException(status_code=500, detail=f"Failed to send push notification: {str(e)}")


@app.get("/notifications/{user_id}")
async def get_user_notifications(user_id: str, limit: int = 10):
    """
    Get recent notifications for a user
    
    Args:
        user_id: User identifier
        limit: Maximum number of notifications to return (default: 10)
    """
    try:
        # Get notification IDs from user's queue
        notification_ids = redis_metadata.lrange(f"notifications:{user_id}", 0, limit - 1)
        
        notifications = []
        for notif_id in notification_ids:
            notif_key = f"notification:{user_id}:{notif_id}"
            notif_data = redis_metadata.get(notif_key)
            
            if notif_data:
                notifications.append(json.loads(notif_data))
        
        return {
            "user_id": user_id,
            "count": len(notifications),
            "notifications": notifications
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get notifications: {str(e)}")


@app.get("/briefings/user/{user_id}/latest")
async def get_user_latest_briefing(user_id: str):
    """
    Get user's latest briefing (today's briefing)
    
    Args:
        user_id: User identifier
        
    Returns:
        Latest briefing with audio URL, transcript, and metadata
    """
    try:
        # Search Redis for user's briefings from today
        today = datetime.now().strftime("%Y-%m-%d")
        
        # Get all briefing keys for this user from today
        pattern = f"briefing:*:data"
        briefing_keys = []
        
        for key in redis_metadata.scan_iter(match=pattern):
            briefing_data_str = redis_metadata.get(key)
            if briefing_data_str:
                briefing_data = json.loads(briefing_data_str)
                # Check if it's this user's briefing and from today
                if (briefing_data.get("user_id") == user_id and 
                    briefing_data.get("created_at", "").startswith(today)):
                    briefing_id = key.split(":")[1]
                    briefing_keys.append({
                        "briefing_id": briefing_id,
                        "created_at": briefing_data.get("created_at"),
                        "data": briefing_data
                    })
        
        if not briefing_keys:
            # Try MongoDB if not in Redis
            try:
                from mongodb_client import get_mongo_client
                mongo = get_mongo_client()
                if mongo.is_connected:
                    briefings = mongo.db.briefings.find({
                        "user_id": user_id,
                        "created_at": {"$regex": f"^{today}"}
                    }).sort("created_at", -1).limit(1)
                    
                    briefing = next(briefings, None)
                    if briefing:
                        return {
                            "briefing_id": briefing.get("request_id"),
                            "user_id": briefing.get("user_id"),
                            "title": _generate_title(briefing.get("created_at", "")),
                            "audio_url": ensure_s3_url(briefing.get("audio_url"), briefing.get("user_id"), briefing.get("request_id")),
                            "transcript": briefing.get("transcript"),
                            "duration": briefing.get("duration"),
                            "created_at": briefing.get("created_at"),
                            "language": briefing.get("metadata", {}).get("language", "english")
                        }
            except Exception as mongo_error:
                logger.warning(f"MongoDB query failed: {mongo_error}", extra={"user_id": user_id})
            
            raise HTTPException(status_code=404, detail=f"No briefing found for user {user_id} today")
        
        # Return the most recent one
        latest = max(briefing_keys, key=lambda x: x["created_at"])
        data = latest["data"]
        
        return {
            "briefing_id": latest["briefing_id"],
            "user_id": data.get("user_id"),
            "title": _generate_title(data.get("created_at", "")),
            "audio_url": ensure_s3_url(data.get("audio_url"), data.get("user_id"), latest["briefing_id"]),
            "transcript": data.get("transcript"),
            "duration": data.get("duration"),
            "created_at": data.get("created_at"),
            "language": data.get("metadata", {}).get("language", "english")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get latest briefing: {str(e)}")


@app.get("/briefings/user/{user_id}/history")
async def get_user_briefing_history(
    user_id: str, 
    limit: int = 10, 
    skip: int = 0,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None
):
    """
    Get user's briefing history (all previous briefings)
    
    Args:
        user_id: User identifier
        limit: Number of briefings to return (default: 10)
        skip: Number of briefings to skip for pagination (default: 0)
        from_date: Filter briefings from this date (YYYY-MM-DD format, inclusive)
        to_date: Filter briefings until this date (YYYY-MM-DD format, inclusive)
        
    Returns:
        List of briefings with audio URL, transcript, and metadata
    """
    try:
        briefings = []
        
        # Build date filter for MongoDB
        date_filter = {"user_id": user_id}
        if from_date or to_date:
            date_filter["created_at"] = {}
            if from_date:
                date_filter["created_at"]["$gte"] = from_date
            if to_date:
                # Add one day to make it inclusive of the entire to_date
                date_filter["created_at"]["$lte"] = to_date + "T23:59:59"
        
        # First, try MongoDB for complete history
        try:
            from mongodb_client import get_mongo_client
            mongo = get_mongo_client()
            if mongo.is_connected:
                cursor = mongo.db.briefings.find(date_filter).sort("created_at", -1).skip(skip).limit(limit)
                
                for briefing in cursor:
                    briefings.append({
                        "briefing_id": briefing.get("request_id"),
                        "user_id": briefing.get("user_id"),
                        "title": _generate_title(briefing.get("created_at", "")),
                        "audio_url": ensure_s3_url(briefing.get("audio_url"), briefing.get("user_id"), briefing.get("request_id")),
                        "transcript": briefing.get("transcript"),
                        "duration": briefing.get("duration"),
                        "created_at": briefing.get("created_at"),
                        "language": briefing.get("metadata", {}).get("language", "english")
                    })
                
                if briefings:
                    return {
                        "user_id": user_id,
                        "count": len(briefings),
                        "briefings": briefings,
                        "skip": skip,
                        "limit": limit
                    }
        except Exception as mongo_error:
            logger.warning(f"MongoDB query failed: {mongo_error}", extra={"user_id": user_id})
        
        # Fallback to Redis (last 7 days)
        pattern = f"briefing:*:data"
        for key in redis_metadata.scan_iter(match=pattern):
            briefing_data_str = redis_metadata.get(key)
            if briefing_data_str:
                briefing_data = json.loads(briefing_data_str)
                if briefing_data.get("user_id") == user_id:
                    created_at = briefing_data.get("created_at", "")
                    
                    # Apply date filters for Redis data
                    if from_date and created_at < from_date:
                        continue
                    if to_date and created_at > to_date + "T23:59:59":
                        continue
                    
                    briefing_id = key.split(":")[1]
                    briefings.append({
                        "briefing_id": briefing_id,
                        "user_id": briefing_data.get("user_id"),
                        "title": _generate_title(briefing_data.get("created_at", "")),
                        "audio_url": ensure_s3_url(briefing_data.get("audio_url"), briefing_data.get("user_id"), briefing_id),
                        "transcript": briefing_data.get("transcript"),
                        "duration": briefing_data.get("duration"),
                        "created_at": created_at,
                        "language": briefing_data.get("metadata", {}).get("language", "english")
                    })
        
        # Sort by created_at descending
        briefings.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        # Apply pagination
        paginated = briefings[skip:skip+limit]
        
        return {
            "user_id": user_id,
            "count": len(paginated),
            "briefings": paginated,
            "skip": skip,
            "limit": limit,
            "total_available": len(briefings),
            "filters": {
                "from_date": from_date,
                "to_date": to_date
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get briefing history: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
