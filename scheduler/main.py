"""
Scheduler Service - Accepts briefing requests and submits to API

This service:
1. Receives briefing requests (articles, username, scheduled time)
2. Submits jobs to the Main API
3. Acts as webhook receiver for job completion notifications
4. Can schedule recurring briefings
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, time, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from contextlib import asynccontextmanager
import requests
import json
import uuid
import os
import redis
from dotenv import load_dotenv
from logger_config import setup_logger

# Load environment variables
load_dotenv()

# Setup logger
logger = setup_logger(__name__)

# Redis connection for storing user schedules
try:
    redis_client = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=int(os.getenv("REDIS_DB", 0)),
        decode_responses=True
    )
    redis_client.ping()
    logger.info("Redis connection established for scheduler")
except Exception as e:
    logger.warning(f"Redis connection failed: {e}")
    redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize/cleanup scheduler on startup/shutdown"""
    logger.info("Scheduler Service Started", extra={"api_base_url": API_BASE_URL})
    
    # Start the background scheduler
    scheduler.start()
    
    # Add periodic job to check user schedules and trigger briefings
    scheduler.add_job(
        func=check_and_trigger_schedules,
        trigger='interval',
        minutes=SCHEDULE_CHECK_INTERVAL_MINUTES,
        id='schedule_checker',
        replace_existing=True,
        max_instances=1  # Prevent overlapping executions
    )
    
    logger.info(
        "Schedule checker started",
        extra={
            "check_interval_minutes": SCHEDULE_CHECK_INTERVAL_MINUTES,
            "early_trigger_window_minutes": EARLY_TRIGGER_WINDOW_MINUTES
        }
    )
    yield
    # Cleanup on shutdown
    scheduler.shutdown()


app = FastAPI(
    title="Audio Briefing Scheduler",
    description="Schedule and manage audio briefing generation",
    version="1.0.0",
    root_path="/audioscheduler",  # Path-based routing prefix
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# APScheduler for recurring jobs
scheduler = BackgroundScheduler()

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8002/audioapi")  # Main API URL
DATABASE_PATH = "articles_database.json"  # Article database
SCHEDULE_CHECK_INTERVAL_MINUTES = 1  # Check schedules every minute
EARLY_TRIGGER_WINDOW_MINUTES = 30  # Allow triggering up to 30 minutes before scheduled time


def check_and_trigger_schedules():
    """
    Periodic task to check user schedules and trigger briefings at scheduled time
    
    Runs every minute to check if any user schedules are ready to trigger.
    Triggers briefings up to 30 minutes BEFORE scheduled time (early trigger window).
    Does NOT trigger late schedules - only early or exact time.
    """
    if not redis_client:
        logger.warning("Redis not available, skipping schedule check")
        return
    
    try:
        current_time = datetime.now(timezone.utc)
        current_time_str = current_time.strftime("%H:%M")
        
        logger.info(f"Checking schedules for time: {current_time_str}")
        
        # Get all user schedule keys
        schedule_keys = redis_client.keys("user_schedule:*")
        
        if not schedule_keys:
            logger.info("No user schedules found")
            return
        
        logger.info(f"Found {len(schedule_keys)} schedules to check")
        
        triggered_count = 0
        skipped_count = 0
        
        for schedule_key in schedule_keys:
            try:
                schedule_data = redis_client.get(schedule_key)
                if not schedule_data:
                    continue
                
                schedule = json.loads(schedule_data)
                
                # Check if daily briefing is enabled
                if not schedule.get("enable_daily_briefing", False):
                    logger.debug(f"Skipping - daily briefing disabled", extra={"user_id": schedule.get("user_id")})
                    continue
                
                scheduled_time = schedule.get("time")
                if not scheduled_time:
                    logger.debug(f"Skipping - no time set", extra={"user_id": schedule.get("user_id")})
                    continue
                
                user_id = schedule.get("user_id")

                # Guard: validate HH:MM format before int() conversion
                if not isinstance(scheduled_time, str) or not re.match(
                    r"^(?:[01]\d|2[0-3]):[0-5]\d$", scheduled_time
                ):
                    logger.warning(
                        f"Deleting schedule key '{schedule_key}' - invalid time format: '{scheduled_time}'",
                        extra={"user_id": user_id}
                    )
                    redis_client.delete(schedule_key)
                    continue

                logger.info(f"Evaluating schedule", extra={"user_id": user_id, "scheduled_time": scheduled_time, "current_time": current_time_str})

                # Parse scheduled time
                scheduled_hour, scheduled_minute = map(int, scheduled_time.split(':'))
                scheduled_datetime = current_time.replace(
                    hour=scheduled_hour,
                    minute=scheduled_minute,
                    second=0,
                    microsecond=0
                )
                
                # Calculate time difference (positive = scheduled time is in future)
                time_diff_minutes = (scheduled_datetime - current_time).total_seconds() / 60
                
                logger.info(f"Time difference: {time_diff_minutes:.2f} minutes", extra={"user_id": user_id})
                
                # Only trigger at exact scheduled time (allow 1-minute window for timing)
                if abs(time_diff_minutes) > 1:
                    # Not at scheduled time yet (or too late)
                    if time_diff_minutes > 0:
                        # Too early - scheduled time hasn't arrived
                        logger.debug(
                            f"Skipping early schedule - waiting for scheduled time",
                            extra={
                                "user_id": user_id,
                                "scheduled_time": scheduled_time,
                                "minutes_until": int(time_diff_minutes)
                            }
                        )
                    else:
                        # Too late - scheduled time has passed
                        logger.debug(
                            f"Skipping late schedule",
                            extra={
                                "user_id": user_id,
                                "scheduled_time": scheduled_time,
                                "minutes_late": abs(int(time_diff_minutes))
                            }
                        )
                    skipped_count += 1
                    continue
                
                # Check if already generated today
                last_generated = schedule.get("last_generated")
                if last_generated:
                    last_gen_time = datetime.fromisoformat(last_generated)
                    # If generated within last 23 hours, skip (avoid duplicate daily runs)
                    if (current_time - last_gen_time).total_seconds() < 23 * 3600:
                        logger.debug(
                            f"Skipping - already generated today",
                            extra={"user_id": user_id, "last_generated": last_generated}
                        )
                        skipped_count += 1
                        continue
                
                # Trigger briefing generation
                logger.info(
                    f"Triggering scheduled briefing",
                    extra={
                        "user_id": user_id,
                        "scheduled_time": scheduled_time,
                        "current_time": current_time_str,
                        "minutes_before_scheduled": int(time_diff_minutes) if time_diff_minutes > 0 else 0
                    }
                )
                
                # Prepare job payload
                target_duration_seconds = schedule.get("duration", 5) * 60
                job_payload = {
                    "user_id": user_id,
                    "articles": [],  # Worker will fetch fresh articles
                    "fetch_articles": True,
                    "device_info": {
                        "platform": schedule.get("deviceplatform"),
                        "name": schedule.get("devicename"),
                        "type": schedule.get("devicetype"),
                        "identifier": schedule.get("deviceidentifier")
                    },
                    "target_duration": target_duration_seconds,
                    "tts_provider": "openai",
                    "tts_voice": schedule.get("voice", "marin"),
                    "audio_format": "mp3",
                    "add_music": False,
                    "domain": "general",
                    "notification_webhook": None,
                    "notification_email": None
                }
                
                # Submit job
                result = submit_job_to_api(job_payload)
                
                # Update last_generated timestamp
                schedule["last_generated"] = current_time.isoformat()
                redis_client.set(schedule_key, json.dumps(schedule))
                
                logger.info(
                    f"Scheduled briefing triggered successfully",
                    extra={
                        "user_id": user_id,
                        "job_id": result.get("job_id"),
                        "scheduled_time": scheduled_time
                    }
                )
                
                triggered_count += 1
                
            except Exception as schedule_error:
                logger.error(
                    f"Error processing schedule: {schedule_error}",
                    extra={"schedule_key": schedule_key}
                )
                continue
        
        if triggered_count > 0 or skipped_count > 0:
            logger.info(
                f"Schedule check completed",
                extra={
                    "triggered": triggered_count,
                    "skipped": skipped_count,
                    "current_time": current_time_str
                }
            )
        
    except Exception as e:
        logger.error(f"Error in schedule checker: {e}")


def load_articles_by_ids(article_ids: List[int]) -> List[Dict[str, Any]]:
    """
    Load articles from database by their IDs
    
    Args:
        article_ids: List of article IDs to load
        
    Returns:
        List of article dictionaries formatted for the Main API
    """
    try:
        with open(DATABASE_PATH, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        articles = db.get('articles', [])
        selected = [a for a in articles if a.get('id') in article_ids]
        
        if len(selected) != len(article_ids):
            found_ids = [a['id'] for a in selected]
            missing = set(article_ids) - set(found_ids)
            logger.warning(f"Could not find articles with IDs: {missing}")
        
        # Transform database articles to match Main API Article model
        # Database has 'text' field, API expects 'content'
        formatted_articles = []
        for article in selected:
            # Validate required fields (title and content must not be None/empty)
            title = article.get("title")
            text = article.get("text")
            
            if not title or not text:
                logger.warning(f"Skipping article - missing title or text", extra={"article_id": article.get('id')})
                continue
            
            formatted_articles.append({
                "id": article.get("id"),
                "title": title,
                "content": text,  # Map 'text' to 'content'
                "source": article.get("url"),  # Use url as source
                "published_date": article.get("publish_date"),
                "category": article.get("category"),
                "importance_score": article.get("importance_score")
            })
        
        if not formatted_articles:
            raise ValueError(f"No valid articles found with IDs: {article_ids}")
        
        return formatted_articles
        
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Database not found: {DATABASE_PATH}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load articles: {str(e)}")


# Pydantic Models
class Article(BaseModel):
    id: Optional[int] = None
    title: str
    content: str
    source: Optional[str] = None
    published_date: Optional[str] = None
    category: Optional[str] = None
    importance_score: Optional[float] = None


class ScheduleBriefingRequest(BaseModel):
    username: str = Field(..., description="User identifier")
    articles: Optional[List[Article]] = Field(None, description="List of articles to process (provide articles, article_ids, or urls)")
    article_ids: Optional[List[int]] = Field(None, description="List of article IDs to load from database (provide articles, article_ids, or urls)")
    urls: Optional[List[str]] = Field(None, description="List of article URLs to extract and process (provide articles, article_ids, or urls)")
    scheduled_time: Optional[str] = Field(None, description="Time to generate briefing (HH:MM format)")
    target_duration: int = Field(5, description="Target duration in minutes")
    tts_provider: str = Field("openai", description="TTS provider (openai/gtts/elevenlabs/edge/etc)")
    tts_voice: Optional[str] = Field("marin", description="Voice ID for TTS (default: marin)")
    audio_format: str = Field("aac", description="Audio format (aac/mp3/opus) - aac recommended for streaming")
    recurrence: Optional[str] = Field("once", description="Recurrence: once, daily, weekdays, weekends")
    notification_webhook: Optional[str] = Field(None, description="Webhook for completion")
    notification_email: Optional[str] = Field(None, description="Email for notification")


class ScheduleBriefingResponse(BaseModel):
    schedule_id: str
    username: str
    status: str
    message: str
    scheduled_for: Optional[str]
    recurrence: str
    created_at: str


class WebhookNotification(BaseModel):
    event: str
    timestamp: str
    data: Dict[str, Any]


class GenerateBriefingRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    duration: int = Field(..., description="Target duration in minutes")
    enable_daily_briefing: bool = Field(..., description="Enable or disable daily briefing generation")
    voice: str = Field("marin", description="TTS voice (marin, cedar, alloy, echo, fable, onyx, nova, shimmer)")
    time: str = Field(..., description="Scheduled time in UTC (HH:MM format, e.g., '07:00')")
    deviceplatform: Optional[str] = Field(None, description="Device platform (e.g., 'web', 'ios', 'android')")
    devicename: Optional[str] = Field(None, description="Device name (e.g., 'Chrome', 'Safari')")
    devicetype: Optional[str] = Field(None, description="Device type (e.g., 'desktop', 'mobile', 'tablet')")
    deviceidentifier: Optional[str] = Field(None, description="Unique device identifier")

    @field_validator("time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        """Enforce HH:MM 24-hour format to prevent scheduler parse errors."""
        if not re.match(r"^(?:[01]\d|2[0-3]):[0-5]\d$", v):
            raise ValueError(
                "time must be in 24-hour HH:MM format, e.g. '07:00' or '23:59'"
            )
        return v


class GenerateBriefingResponse(BaseModel):
    success: bool
    message: str
    job_id: Optional[str] = None
    user_id: str
    enable_daily_briefing: bool
    scheduled_time: Optional[str] = None


@app.get("/health")
def health_check():
    """
    Health check endpoint for ECS/load balancer
    
    Returns 200 if service is healthy, 503 if unhealthy
    Checks scheduler status and Main API connectivity
    """
    health_status = {
        "status": "healthy",
        "service": "audio-briefing-scheduler",
        "timestamp": datetime.now().isoformat(),
        "scheduler": "unknown",
        "main_api": "unknown",
        "scheduled_jobs": 0
    }
    
    issues = []
    
    try:
        # Check scheduler status
        if scheduler.running:
            health_status["scheduler"] = "running"
            health_status["scheduled_jobs"] = len(scheduler.get_jobs())
        else:
            health_status["scheduler"] = "stopped"
            issues.append("Scheduler is not running")
    except Exception as e:
        health_status["scheduler"] = "error"
        issues.append(f"Scheduler: {str(e)}")
    
    try:
        # Check Main API connectivity
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        if response.status_code == 200:
            health_status["main_api"] = "connected"
        else:
            health_status["main_api"] = "unhealthy"
            issues.append(f"Main API returned {response.status_code}")
    except requests.exceptions.Timeout:
        health_status["main_api"] = "timeout"
        issues.append("Main API timeout")
    except Exception as e:
        health_status["main_api"] = "disconnected"
        issues.append(f"Main API: {str(e)}")
    
    # Return unhealthy if scheduler is not running (critical)
    if health_status["scheduler"] != "running":
        health_status["status"] = "unhealthy"
        health_status["issues"] = issues
        raise HTTPException(
            status_code=503,
            detail=health_status
        )
    
    # Main API connection is important but not critical for scheduler health
    if issues:
        health_status["warnings"] = issues
    
    return health_status


# Lifespan events handled by the modern lifespan context manager


@app.get("/")
def root():
    """Scheduler root endpoint"""
    return {
        "service": "Audio Briefing Scheduler",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "schedule_briefing": "POST /briefing/schedule",
            "generate_briefing": "POST /briefing/generate",
            "get_user_schedule": "GET /briefing/schedule/{user_id}",
            "update_user_schedule": "PUT /briefing/schedule/{user_id}",
            "delete_user_schedule": "DELETE /briefing/schedule/{user_id}",
            "list_schedules": "GET /briefing/schedules",
            "cancel_schedule": "DELETE /briefing/schedule/{schedule_id}",
            "webhook_receiver": "POST /webhook/job-completed"
        }
    }


# Old APScheduler-based endpoints removed - replaced by Redis-based user preference system
# New endpoints: POST /briefing/generate, GET/PUT/DELETE /briefing/schedule/{user_id}


@app.post("/briefing/generate", response_model=GenerateBriefingResponse)
async def generate_briefing(request: GenerateBriefingRequest):
    """
    Generate audio briefing based on user preferences
    
    Takes user_id, duration, enable_daily_briefing, voice, and time (UTC) as inputs.
    If enable_daily_briefing is true, fetches articles and generates briefing.
    If false, returns without generating.
    
    Args:
        request: GenerateBriefingRequest with user_id, duration, enable_daily_briefing, voice, time
        
    Returns:
        GenerateBriefingResponse with success status and job_id if generated
    """
    try:
        logger.info(
            "Generate briefing request received",
            extra={
                "user_id": request.user_id,
                "enable_daily_briefing": request.enable_daily_briefing,
                "voice": request.voice,
                "duration": request.duration,
                "scheduled_time": request.time
            }
        )
        
        # Check if user already has a daily briefing schedule
        if redis_client:
            schedule_key = f"user_schedule:{request.user_id}"
            existing_schedule = redis_client.get(schedule_key)
            
            if existing_schedule:
                existing_data = json.loads(existing_schedule)
                logger.info(
                    f"User has existing schedule, will update it",
                    extra={
                        "user_id": request.user_id,
                        "old_time": existing_data.get("time"),
                        "new_time": request.time
                    }
                )
        
        # Check if daily briefing is enabled
        if not request.enable_daily_briefing:
            logger.info(f"Daily briefing disabled, skipping generation", extra={"user_id": request.user_id})
            
            # Explicitly delete the schedule from Redis so it stops triggering
            if redis_client:
                schedule_key = f"user_schedule:{request.user_id}"
                redis_client.delete(schedule_key)
                logger.info(f"Deleted schedule for user {request.user_id} from Redis")
                
            return GenerateBriefingResponse(
                success=True,
                message=f"Briefing generation skipped - daily briefing is disabled for user {request.user_id}",
                job_id=None,
                user_id=request.user_id,
                enable_daily_briefing=False,
                scheduled_time=request.time
            )
        
        # Daily briefing is enabled - store schedule for periodic checker to trigger
        logger.info(f"Daily briefing enabled, storing schedule", extra={"user_id": request.user_id, "scheduled_time": request.time})
        
        # Store or update user schedule in Redis (for periodic checker)
        if redis_client:
            schedule_key = f"user_schedule:{request.user_id}"
            existing_schedule = redis_client.get(schedule_key)
            
            # Preserve created_at if updating, otherwise create new timestamp
            created_at = datetime.now().isoformat()
            if existing_schedule:
                existing_data = json.loads(existing_schedule)
                created_at = existing_data.get("created_at", created_at)
            
            schedule_data = {
                "user_id": request.user_id,
                "duration": request.duration,
                "voice": request.voice,
                "time": request.time,
                "enable_daily_briefing": request.enable_daily_briefing,
                "deviceplatform": request.deviceplatform,
                "devicename": request.devicename,
                "devicetype": request.devicetype,
                "deviceidentifier": request.deviceidentifier,
                "created_at": created_at,
                "updated_at": datetime.now().isoformat()
                # Note: last_generated will be set when periodic checker triggers
            }
            redis_client.set(schedule_key, json.dumps(schedule_data))
            
            action = "updated" if existing_schedule else "created"
            logger.info(f"User schedule {action}", extra={"user_id": request.user_id})
        
        return GenerateBriefingResponse(
            success=True,
            message=f"Briefing scheduled successfully for user {request.user_id} at {request.time} UTC",
            job_id=None,  # No job_id yet - will be created at scheduled time
            user_id=request.user_id,
            enable_daily_briefing=True,
            scheduled_time=request.time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating briefing", extra={"error": str(e), "user_id": request.user_id})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate briefing: {str(e)}"
        )


@app.get("/briefing/schedule/{user_id}")
async def get_user_schedule(user_id: str):
    """
    Get user's daily briefing schedule configuration
    
    Args:
        user_id: User identifier
        
    Returns:
        User's schedule configuration or 404 if not found
    """
    try:
        if not redis_client:
            raise HTTPException(
                status_code=503,
                detail="Schedule storage not available"
            )
        
        schedule_key = f"user_schedule:{user_id}"
        schedule_data = redis_client.get(schedule_key)
        
        if not schedule_data:
            raise HTTPException(
                status_code=404,
                detail=f"No daily briefing schedule found for user {user_id}"
            )
        
        return json.loads(schedule_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving user schedule", extra={"error": str(e), "user_id": user_id})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve schedule: {str(e)}"
        )


@app.put("/briefing/schedule/{user_id}", response_model=GenerateBriefingResponse)
async def update_user_schedule(user_id: str, request: GenerateBriefingRequest):
    """
    Update user's daily briefing schedule configuration
    
    Args:
        user_id: User identifier (must match request body user_id)
        request: Updated schedule configuration
        
    Returns:
        Updated schedule confirmation
    """
    try:
        if user_id != request.user_id:
            raise HTTPException(
                status_code=400,
                detail="URL user_id must match request body user_id"
            )
        
        if not redis_client:
            raise HTTPException(
                status_code=503,
                detail="Schedule storage not available"
            )
        
        schedule_key = f"user_schedule:{user_id}"
        existing_schedule = redis_client.get(schedule_key)
        
        if not existing_schedule:
            raise HTTPException(
                status_code=404,
                detail=f"No daily briefing schedule found for user {user_id}. Use POST /briefing/generate to create one."
            )
        
        # Update schedule
        existing_data = json.loads(existing_schedule)
        updated_data = {
            "user_id": request.user_id,
            "duration": request.duration,
            "voice": request.voice,
            "time": request.time,
            "enable_daily_briefing": request.enable_daily_briefing,
            "deviceplatform": request.deviceplatform,
            "devicename": request.devicename,
            "devicetype": request.devicetype,
            "deviceidentifier": request.deviceidentifier,
            "created_at": existing_data.get("created_at"),
            "updated_at": datetime.now().isoformat()
        }
        
        redis_client.set(schedule_key, json.dumps(updated_data))
        logger.info(f"User schedule updated", extra={"user_id": user_id})
        
        return GenerateBriefingResponse(
            success=True,
            message=f"Daily briefing schedule updated for user {user_id}",
            job_id=None,
            user_id=user_id,
            enable_daily_briefing=request.enable_daily_briefing,
            scheduled_time=request.time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user schedule", extra={"error": str(e), "user_id": user_id})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update schedule: {str(e)}"
        )


@app.delete("/briefing/schedule/{user_id}")
async def delete_user_schedule(user_id: str):
    """
    Delete user's daily briefing schedule configuration
    
    Args:
        user_id: User identifier
        
    Returns:
        Deletion confirmation
    """
    try:
        if not redis_client:
            raise HTTPException(
                status_code=503,
                detail="Schedule storage not available"
            )
        
        schedule_key = f"user_schedule:{user_id}"
        deleted = redis_client.delete(schedule_key)
        
        if not deleted:
            raise HTTPException(
                status_code=404,
                detail=f"No daily briefing schedule found for user {user_id}"
            )
        
        logger.info(f"User schedule deleted", extra={"user_id": user_id})
        
        return {
            "success": True,
            "message": f"Daily briefing schedule deleted for user {user_id}",
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user schedule", extra={"error": str(e), "user_id": user_id})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete schedule: {str(e)}"
        )


@app.post("/webhook/job-completed")
async def receive_job_completion(notification: WebhookNotification):
    """
    Receive job completion notifications from worker
    
    Acts as the Archive - receives and logs final results.
    """
    try:
        logger.info(
            "Received job completion notification",
            extra={
                "event": notification.event,
                "request_id": notification.data.get('request_id'),
                "user_id": notification.data.get('user_id'),
                "status": notification.data.get('status'),
                "audio_filepath": notification.data.get('audio_filepath'),
                "completed_at": notification.data.get('completed_at')
            }
        )
        
        # Here you could:
        # 1. Store results in database
        # 2. Send email to user
        # 3. Trigger downstream processes
        # 4. Update UI/dashboard
        
        return {
            "status": "received",
            "message": "Notification processed successfully",
            "request_id": notification.data.get('request_id')
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process notification: {str(e)}")


def submit_job_to_api(job_payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Submit a job to the Main API
    
    Args:
        job_payload: Job data to submit
        
    Returns:
        dict: API response with job_id and status
    """
    try:
        logger.info(
            f"Submitting job to API with payload",
            extra={
                "user_id": job_payload.get("user_id"),
                "fetch_articles": job_payload.get("fetch_articles"),
                "has_device_info": job_payload.get("device_info") is not None,
                "articles_count": len(job_payload.get("articles", []))
            }
        )
        
        response = requests.post(
            f"{API_BASE_URL}/briefing/submit",
            json=job_payload,
            timeout=10
        )
        response.raise_for_status()
        
        result = response.json()
        logger.info(f"Job submitted to API successfully", extra={"job_id": result.get('job_id')})
        
        return result
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to submit job to API", extra={"error": str(e)})
        raise


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
