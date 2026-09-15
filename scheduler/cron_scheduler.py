"""
Automated Cron Scheduler - Generates briefings based on user preferences

Runs every minute checking for users scheduled at current time.
Fetches articles and submits jobs automatically.
"""

import os
import sys
import time
import requests
from datetime import datetime, timedelta
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from typing import List, Dict, Any
from dotenv import load_dotenv

# Add parent directory to path to import user_service
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from user_service import (
    get_users_scheduled_for_time,
    get_user_preferences,
    check_subscription,
    get_saved_articles,
    get_latest_unread_articles
)

load_dotenv()

# Main API endpoint
MAIN_API_URL = os.getenv("MAIN_API_URL", "http://localhost:8002/briefings")

# Scheduler configuration
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "UTC")
CHECK_INTERVAL_MINUTES = int(os.getenv("CHECK_INTERVAL_MINUTES", "1"))


def submit_briefing_job(user_id: str, articles: List[Dict[str, Any]], 
                       duration_minutes: int, tts_voice: str, 
                       tts_provider: str) -> bool:
    """
    Submit briefing job to main API queue
    
    Args:
        user_id: User identifier
        articles: List of article objects
        duration_minutes: Target duration in minutes
        tts_voice: Voice to use for TTS
        tts_provider: TTS provider (openai, gtts, etc)
    
    Returns:
        True if submission successful, False otherwise
    """
    try:
        payload = {
            "user_id": user_id,
            "articles": articles,
            "target_duration": duration_minutes,
            "tts_voice": tts_voice,
            "tts_provider": tts_provider
        }
        
        response = requests.post(
            f"{MAIN_API_URL}/briefing/submit",
            json=payload,
            timeout=10.0
        )
        response.raise_for_status()
        
        result = response.json()
        job_id = result.get("job_id")
        
        print(f"✓ Submitted job {job_id} for user {user_id}")
        return True
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Failed to submit job for user {user_id}: {e}")
        return False


def process_user_briefing(user_data: Dict[str, Any]) -> bool:
    """
    Process briefing generation for a single user
    
    Args:
        user_data: User preferences object from get_users_scheduled_for_time
    
    Returns:
        True if successful, False otherwise
    """
    user_id = user_data.get("user_id")
    preferences = user_data.get("preferences", {})
    
    print(f"\n⏰ Processing briefing for user: {user_id}")
    
    # 1. Check subscription
    if not check_subscription(user_id):
        print(f"   ✗ User {user_id} does not have paid subscription - skipping")
        return False
    
    print(f"   ✓ Subscription validated")
    
    # 2. Fetch articles based on content source preference
    content_source = preferences.get("content_source", "latest_news")
    interests = preferences.get("interests", [])
    region = preferences.get("region")
    articles = []
    
    if content_source == "saved_articles":
        print(f"   📚 Fetching saved articles from yesterday...")
        articles = get_saved_articles(user_id)
    else:  # latest_news
        print(f"   📰 Fetching last 10 curated articles (interests: {interests}, region: {region})...")
        articles = get_latest_unread_articles(user_id, limit=10, interests=interests, region=region)
        
        # Backfill if less than 5 articles
        if len(articles) < 5:
            print(f"   ⚠️  Only {len(articles)} articles found, backfilling with interest-only filter...")
            remaining = 10 - len(articles)
            backfill_articles = get_latest_unread_articles(user_id, limit=remaining, interests=interests, region=None)
            articles.extend(backfill_articles)
            print(f"   ✓ Added {len(backfill_articles)} backfill articles, total: {len(articles)}")
    
    if not articles:
        print(f"   ✗ No articles found for user {user_id} - skipping")
        return False
    
    print(f"   ✓ Found {len(articles)} articles")
    
    # 3. Submit to queue with user's preferences
    duration = preferences.get("duration_minutes", 5)
    voice = preferences.get("tts_voice", "marin")
    provider = preferences.get("tts_provider", "openai")
    
    print(f"   ⚙️  Settings: {duration}min, {voice}, {provider}")
    
    success = submit_briefing_job(
        user_id=user_id,
        articles=articles,
        duration_minutes=duration,
        tts_voice=voice,
        tts_provider=provider
    )
    
    return success


def check_and_process_briefings():
    """
    Main scheduler function - runs every minute
    
    Checks current time and processes users scheduled for now
    Fetches latest articles at scheduled time to ensure fresh content
    """
    # Use current time (not 30 minutes ahead)
    current_time = datetime.now().strftime("%H:%M")
    
    print(f"\n{'='*60}")
    print(f"🕐 Scheduler check at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Processing briefings scheduled for: {current_time}")
    print(f"{'='*60}")
    
    # Get users scheduled for current time
    users = get_users_scheduled_for_time(current_time)
    
    if not users:
        print(f"No users scheduled for {current_time}")
        return
    
    print(f"Found {len(users)} user(s) scheduled for {current_time}")
    
    # Process each user
    success_count = 0
    failed_count = 0
    
    for user_data in users:
        try:
            if process_user_briefing(user_data):
                success_count += 1
            else:
                failed_count += 1
        except Exception as e:
            print(f"   ✗ Error processing user {user_data.get('user_id')}: {e}")
            failed_count += 1
    
    print(f"\n📊 Summary: {success_count} successful, {failed_count} failed")
    print(f"{'='*60}\n")


def start_scheduler():
    """
    Start the automated briefing scheduler
    
    Runs check_and_process_briefings every minute
    """
    scheduler = BlockingScheduler(timezone=SCHEDULER_TIMEZONE)
    
    # Run every minute
    scheduler.add_job(
        check_and_process_briefings,
        CronTrigger.from_crontab(f'*/{CHECK_INTERVAL_MINUTES} * * * *'),
        id='briefing_scheduler',
        name='Check and process scheduled briefings',
        replace_existing=True
    )
    
    print(" Audio Briefing Automated Scheduler  ")

    print(f"\n Configuration:")
    print(f"   • Check interval: Every {CHECK_INTERVAL_MINUTES} minute(s)")
    print(f"   • Timezone: {SCHEDULER_TIMEZONE}")
    print(f"   • Main API: {MAIN_API_URL}")
    print(f"\n Scheduler started. Waiting for scheduled briefings...\n")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("\n\n👋 Scheduler stopped by user")
        scheduler.shutdown()


if __name__ == "__main__":
    start_scheduler()
