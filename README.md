# Audio Briefing System

A production-ready **audio briefing system** with zero-touch generation. Users set preferences, backend handles everything automatically.

## 🎯 User Flow
```
User 
   ↓
Sets preferences: time, duration, voice, content source
   ↓
Auto-Scheduler
   ↓
Every minute: checks scheduled users → validates subscription → fetches articles → generates briefing
   ↓
Push notification sent automatically
```

## Architecture

Four core components:

1. **Automated Scheduler** - Runs every minute, auto-generates briefings based on user preferences
2. **Scheduler Service** (Port 8001) - Manual briefing requests (testing/admin)
3. **Main API** (Port 8002) - Queue management, job submission to Redis
4. **Worker** - Consumes jobs, executes LangGraph workflow

### LangGraph Workflow (6 Nodes)
```
Extract → Analyze → Write Script → Generate Audio → Save → Notify
```

## 📦 Installation

### Prerequisites
- Python 3.10+
- **Redis** (Linux/Mac) or **Memurai** (Windows)
- **MongoDB** or **AWS DocumentDB** (for persistent briefing storage)
- OpenAI API key

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure environment (.env file)
OPENAI_API_KEY=your_key_here
PROPT_CORE_API_URL=https://your-propt-api.com
PROPT_API_KEY=your_internal_api_key

# 3. Install Redis/Memurai
# Windows: Download from https://www.memurai.com/
# Linux: sudo apt-get install redis-server

# 4. Setup MongoDB
# MONGODB_URI=mongodb://username:password@cluster.docdb.amazonaws.com:27017/audio_briefing?ssl=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false
# For local dev: MONGODB_URI=mongodb://localhost:27017/audio_briefing


---

## 🚀 Quick Start

### Automated Mode (Production)

**Terminal 1 - Redis/Memurai:**
```powershell
# Windows (Memurai as service - auto-starts)
# Or manually: cd "C:\Program Files\Memurai" ; .\memurai.exe

# Linux/Mac
redis-server
```

**Terminal 2 - Main API:**
```bash
python api/main.py
# → http://localhost:8002/briefings
```

**Terminal 3 - Worker:**
```bash
python worker.py
```

**Terminal 4 - Automated Scheduler:**
```bash
cd scheduler
python cron_scheduler.py
```

### Manual Mode (Testing/Admin)

Start services 1-3 above, then:

**Terminal 4 - Scheduler API:**
```bash
python scheduler/main.py
# → http://localhost:8001
# Swagger UI: http://localhost:8001/docs
```

---

## 🤖 Automated Scheduler

### How It Works

1. **Every minute**: Checks PROPT Core for users scheduled at current time
2. **For each user**:
   - ✅ Validates paid subscription
   - 📚 Fetches articles based on preference:
     - `saved_articles`: Yesterday's saved articles
     - `latest_news`: Top 15 unread from curated list
   - 🎯 Submits job with user's settings (duration, voice, provider)
3. **Worker generates** →  **Push notification sent**

---

## 📡 API Usage

### Option: Swagger UI (Recommended for Testing)

**Scheduler:** http://localhost:8001/docs  
**Main API:** http://localhost:8002/docs
---

## 🎯 Key Endpoints

### Scheduler Service (Port 8001)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/briefing/schedule` | Submit/schedule briefing |
| `GET` | `/briefing/schedules` | List all schedules |
| `DELETE` | `/briefing/schedule/{id}` | Cancel schedule |

**Briefing Request Body:**

You can provide content in **3 ways**:

**Option 1: Article IDs from database**
```json
{
  "username": "user_id",
  "article_ids": [1, 3, 5],
  "target_duration": 5,
  "tts_provider": "openai",
  "tts_voice": "onyx"
}
```

**Option 2: Full article objects**
```json
{
  "username": "user_id",
  "articles": [
    {
      "title": "Article Title",
      "content": "Full article text...",
      "source": "News Source"
    }
  ],
  "target_duration": 5
}
```

**Option 3: Article URLs (auto-extract)**
```json
{
  "username": "user_id",
  "urls": [
    "https://example.com/article1",
    "https://techcrunch.com/article2",
    "https://bbc.com/news/article3"
  ],
  "target_duration": 5,
  "tts_provider": "openai"
}
```

**Common parameters (all options):**
- `scheduled_time`: "09:00" (HH:MM) or null for immediate
- `target_duration`: Minutes (3/5/10/15/20)
- `tts_provider`: "openai" (default), "gtts", "elevenlabs", "edge", "pyttsx3", "kokoro"
- `tts_voice`: Voice ID (openai: alloy/echo/fable/onyx/nova/shimmer)
- `recurrence`: "once", "daily", "weekdays", "weekends"
- `notification_email`: Optional email for completion notification

---

### Main API (Port 8002)

**Base Path:** `/briefings` (all endpoints are prefixed)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/briefings/health` | Health check (Redis + MongoDB status) |
| `GET` | `/briefings/` | API root with service info |
| `GET` | `/briefings/{id}` | Get briefing by ID (audio URL + transcript) |
| `POST` | `/briefings/submit` | Submit job to queue |
| `GET` | `/briefings/queue/status` | Queue statistics |
| `GET` | `/briefings/queue/main/items` | List queued jobs |
| `GET` | `/briefings/queue/dlq/items` | List failed jobs |
| `POST` | `/briefings/queue/dlq/requeue/{id}` | Retry failed job |
| `POST` | `/briefings/queue/dlq/requeue-all` | Retry all failed |
| `GET` | `/briefings/job/{id}/status` | Job details |
| `POST` | `/briefings/notifications/push` | Send push notification |
| `GET` | `/briefings/notifications/{user_id}` | Get user notifications |

## 📁 Project Structure

```
audio_briefing/
├── api/
│   └── main.py                 # Main API (queue management)
├── scheduler/
│   └── main.py                 # Scheduler service
├── worker.py                   # Job processor
├── briefing_graph.py           # LangGraph workflow (6 nodes)
├── research_analyst.py         # Article analysis node
├── script_writer.py            # Script generation node
├── audio_speaker.py            # TTS generation node
├── email_notifier.py           # Email notifications
├── mongodb_client.py           # MongoDB connection handler
├── s3_uploader.py              # S3 cloud storage
├── prompt_loader.py            # AI prompt management
├── logger_config.py            # Logging configuration
├── validation_models.py        # Pydantic models
├── build_database.py           # Database builder
├── articles_database.json      # Pre-processed articles
├── prompts/                    # AI prompt templates
│   ├── __init__.py
│   ├── research_analyst.py        
│   ├── script_writer_intro.py      
│   ├── script_writer_article.py    
│   └── script_writer_outro.py      
├── output/                     # Generated files
│   ├── audio_*.mp3
│   ├── script_*.txt
│   └── analysis_*.json
└── requirements.txt
```
---
## 📊 Opik Integration - LLM Workflow Tracing

The system integrates **Opik** for comprehensive LLM workflow monitoring and tracing.

### Features
- **Automatic OpenAI tracking** - All GPT-4o-mini calls traced with prompts, responses, latency, token usage
- **Workflow visualization** - Track full briefing pipeline from extraction to audio generation
- **Performance metrics** - Measure duration of each node (analysis, script writing, TTS)
- **Error tracking** - Capture failures in AI calls with full context
- **Cost tracking** - Monitor OpenAI API token usage and costs

### Setup Options

**Option 1: Opik Cloud** (Recommended)
```bash
# 1. Sign up at https://www.comet.com/site/products/opik/
# 2. Get API key from dashboard
# 3. Add to .env:
OPIK_API_KEY=your_opik_api_key_here
OPIK_WORKSPACE=your_workspace_name
```

**Option 2: Self-Hosted Opik**
```bash
# 1. Run local Opik instance
docker run -d -p 5173:5173 -p 3003:3003 --name opik comet-ml/opik:latest

# 2. Add to .env:
OPIK_URL_OVERRIDE=http://localhost:5173/api
```

## 🛠️ Configuration

### Environment Variables (.env)
```bash
# Required
OPENAI_API_KEY=your_openai_api_key

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# MongoDB (Required - for persistent storage)
# AWS DocumentDB (Production - similar to newsagent)
MONGODB_URI=mongodb://username:password@cluster.docdb.amazonaws.com:27017/audio_briefing?ssl=true&replicaSet=rs0&readPreference=secondaryPreferred&retryWrites=false
MONGODB_DATABASE=audio_briefing
# OR Local MongoDB (Development)
# MONGODB_URI=mongodb://localhost:27017/audio_briefing

# S3 Storage (Optional)
S3_ENABLED=true
AWS_ACCESS_KEY_ID=your_key
AWS_SECRET_ACCESS_KEY=your_secret
S3_BUCKET_NAME=propt-global
S3_REGION=us-east-1

# PROPT Core API (for automated scheduler)
PROPT_CORE_API_URL=https://api.propt.world
PROPT_API_KEY=your_api_key

# Optional Services
ELEVENLABS_API_KEY=your_key
SENDGRID_API_KEY=your_key
NOTIFICATION_EMAIL_FROM=briefings@yourdomain.com
OPIK_API_KEY=your_opik_key
```

### Storage Architecture

**Two-Tier Storage System:**
- **Redis**: Fast cache for recent briefings (7-day TTL)
- **MongoDB**: Permanent record for all briefings (required)

**GET /briefings/{id} Flow:**
1. Check Redis first (5-10ms response)
2. If not in Redis → Check MongoDB (20-50ms)
3. If found in MongoDB → Cache back to Redis
4. Return audio URL + transcript + metadata

### Duration Presets
- **3 min** - Quick headlines 
- **5 min** - Standard briefing
- **10 min** - Deep dive 
- **15 min** - Extended coverage 
- **20 min** - Comprehensive 

### TTS Providers
- **openai** (Default) - High quality (alloy/echo/fable/onyx/nova/shimmer)
- **gtts** - Free, basic quality (good for testing)
- **elevenlabs** - Premium quality (requires API key)
- **edge** - Microsoft Edge TTS
- **pyttsx3** - Offline TTS
- **kokoro** - Local ONNX model

---

## 📊 Output Files

Each briefing generates:
1. **Audio**: `output/audio_{username}_{timestamp}.mp3`
2. **Script**: `output/script_{username}_{timestamp}.txt`
3. **Analysis**: `output/analysis_{username}_{timestamp}.json`

---

## 🔧 Troubleshooting

### Redis Connection Issues
```powershell
# Check if Memurai is running (Windows)
Get-Service MemuraiService

# Test connection
cd "C:\Program Files\Memurai"
.\memurai-cli.exe ping
# Should return: PONG
```

### MongoDB Connection Issues
```bash
# Test MongoDB connection
python mongodb_client.py
# Should show: ✅ MongoDB connection successful

# Check health endpoint
curl http://localhost:8002/briefings/health
# Should show: "mongodb": "connected"
```

### Worker Not Picking Up Jobs
1. Check worker terminal for errors
2. Verify Redis connection
3. Ensure Main API is running (port 8002)

### Scheduled Jobs Not Running
1. Check scheduler logs for APScheduler errors
2. Verify scheduled_time format (HH:MM)
3. List schedules: `GET /briefing/schedules`

---

## 🎓 Usage Examples

### Example 1: Quick Test (Immediate)
```json
{
  "username": "test",
  "article_ids": [1, 2, 3],
  "target_duration": 3,
  "tts_provider": "openai"
}
```

### Example 2: Morning Briefing (Scheduled)
```json
{
  "username": "morning_news",
  "article_ids": [1, 5, 10, 15, 20, 25],
  "scheduled_time": "07:00",
  "recurrence": "weekdays",
  "target_duration": 10,
  "tts_provider": "openai",
  "tts_voice": "alloy",
  "notification_email": "user@example.com"
}
```

## Example 3: Extract from URLs
```json
{
  "username": "news_reader",
  "urls": [
    "https://techcrunch.com/2025/12/25/ai-breakthrough",
    "https://www.bbc.com/news/technology-12345678",
    "https://www.theverge.com/latest-gadget-review"
  ],
  "target_duration": 10,
  "tts_provider": "openai",
  "tts_voice": "nova"
}
```
## 📚 Article Database

The `articles_database.json` contains 70+ pre-processed articles with:
- Sequential IDs (1-70)
- Title, content, source
- Category, importance score
- Published date

---

## 🚦 Workflow Example

1. **Submit Request** → Scheduler receives briefing request
2. **Validate** → Checks articles or loads from database by IDs
3. **Queue** → Scheduler submits to Main API → Redis queue
4. **Process** → Worker picks up job
5. **Execute** → BriefingGraph workflow (6 nodes)
6. **Output** → MP3 + TXT + JSON files saved
7. **Notify** → Webhook sent back to Scheduler

---
## 📄 License
MIT License

## 🙏 Acknowledgments

- **LangGraph** - Workflow orchestration
- **FastAPI** - API framework
- **Redis/RQ** - Job queue
- **MongoDB** - Persistent storage
- **OpenAI** - GPT-4o-mini & TTS
- **APScheduler** - Job scheduling
- **Opik** - LLM tracing and monitoring
- **AWS S3** - Cloud storage
- **AWS DocumentDB** - MongoDB-compatible database
---
