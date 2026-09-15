"""
LangGraph-based Audio Briefing System

"""

from typing import TypedDict, List, Dict, Any, Annotated, Optional
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI
from datetime import datetime
import json
import uuid
import os

from logger_config import setup_logger, set_correlation_id, log_with_context
from opik_config import track, get_langchain_tracer
from email_notifier import EmailNotifier
from s3_uploader import upload_briefing_package, S3_ENABLED
from research_analyst import ResearchAnalyst, ArticleAnalysis
from script_writer import ScriptWriter, NewsScript
from audio_speaker import AudioSpeaker, AudioOutput


# Define the state that flows through the graph
class BriefingState(TypedDict):
    """State object that passes through the workflow"""
    # Input
    request_id: str
    user_id: str
    articles: List[Dict[str, Any]]
    urls: Optional[List[str]]
    target_duration: int  # in seconds
    tts_provider: str
    tts_voice: Optional[str] = "marin"  # Default voice: marin
    audio_format: Optional[str]  # Audio format: mp3, aac, opus, flac, wav
    add_music: bool
    music_file: Optional[str]
    domain: str
    notification_webhook: Optional[str]
    notification_email: Optional[str]
    
    # Intermediate state
    analyzed_articles: Optional[List[ArticleAnalysis]]
    analysis_summary: Optional[Dict[str, Any]]
    news_script: Optional[NewsScript]
    
    # Output
    audio_output: Optional[AudioOutput]
    audio_filepath: Optional[str]
    audio_url: Optional[str]      # S3 URL
    analysis_url: Optional[str]   # S3 URL
    script_filepath: Optional[str]
    analysis_filepath: Optional[str]
    status: str  # "pending", "analyzing", "writing", "generating", "complete", "failed"
    error: Optional[str]
    completed_at: Optional[str]


class BriefingGraph:
    """LangGraph workflow for audio briefing generation"""
    
    def __init__(
        self,
        use_ai: bool = True,
        words_per_minute: int = 130,  # Adjusted for TTS speech rate (gTTS ~130 WPM)
        output_dir: str = "output"
    ):
        self.logger = setup_logger(__name__)
        self.use_ai = use_ai
        self.words_per_minute = words_per_minute
        self.output_dir = output_dir
        
        # Initialize LLM
        self.llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.7)
        
        # Initialize Opik if available and configured
        self.opik_tracer = get_langchain_tracer()
        self.opik_enabled = self.opik_tracer is not None
        
        if self.opik_enabled:
            self.logger.info(f"Opik tracing enabled via global configuration")
        else:
            self.logger.info("Opik tracing disabled or not configured")
        
        # Build the graph
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build the LangGraph workflow"""
        
        # Create graph
        workflow = StateGraph(BriefingState)
        
        # Add nodes
        workflow.add_node("extract_articles", self.extract_articles_node)
        workflow.add_node("analyze_articles", self.analyze_articles_node)
        workflow.add_node("write_script", self.write_script_node)
        workflow.add_node("generate_audio", self.generate_audio_node)
        workflow.add_node("save_outputs", self.save_outputs_node)
        workflow.add_node("send_notification", self.send_notification_node)
        
        # Define edges (workflow)
        workflow.set_entry_point("extract_articles")
        workflow.add_edge("extract_articles", "analyze_articles")
        workflow.add_edge("analyze_articles", "write_script")
        workflow.add_edge("write_script", "generate_audio")
        workflow.add_edge("generate_audio", "save_outputs")
        workflow.add_edge("save_outputs", "send_notification")
        workflow.add_edge("send_notification", END)
        
        return workflow.compile()
    

    @track(name="extract_articles")
    def extract_articles_node(self, state: BriefingState) -> BriefingState:
        """Node 1: Extract articles from URLs if provided"""
        print("[STAGE 1] Extracting articles...")
        
        state["status"] = "extracting"
        
        try:
            # If URLs provided, extract articles
            if state.get("urls") and len(state["urls"]) > 0:
                try:
                    from newspaper import Article as NewspaperArticle
                except ImportError as e:
                    raise ImportError("newspaper4k is required for article extraction. Install with: pip install newspaper4k") from e
                
                extracted_articles = []
                failed_urls = []
                
                for url in state["urls"]:
                    try:
                        if not url or not url.startswith(('http://', 'https://')):
                            raise ValueError(f"Invalid URL format: {url}")
                        
                        article = NewspaperArticle(url)
                        article.download()
                        article.parse()
                        
                        if not article.text:
                            raise ValueError(f"No content extracted from {url}")
                        
                        extracted_articles.append({
                            'title': article.title or 'Untitled',
                            'text': article.text,
                            'url': url,
                            'authors': article.authors,
                            'publish_date': article.publish_date.isoformat() if article.publish_date else None,
                            'top_image': article.top_image,
                            'extracted_at': datetime.now().isoformat()
                        })
                    except Exception as e:
                        failed_urls.append((url, str(e)))
                        self.logger.warning(f"Failed to extract article from {url}: {e}")
                
                # Merge with existing articles if any
                existing_articles = state.get("articles", [])
                state["articles"] = existing_articles + extracted_articles
                
                print(f"   ✓ Extracted {len(extracted_articles)} articles from URLs")
                if failed_urls:
                    print(f"   ⚠️  Failed to extract {len(failed_urls)} URLs")
            
            # Validate we have at least one article
            if not state.get("articles") or len(state["articles"]) == 0:
                raise ValueError("No articles available for processing")
            
            return state
            
        except ImportError as e:
            state["status"] = "failed"
            state["error"] = f"Missing dependency: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
        except ValueError as e:
            state["status"] = "failed"
            state["error"] = str(e)
            print(f"   ❌ Error: {state['error']}")
            return state
        except Exception as e:
            state["status"] = "failed"
            state["error"] = f"Article extraction failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            self.logger.exception("Unexpected error in article extraction")
            return state
    

    @track(name="analyze_articles")
    def analyze_articles_node(self, state: BriefingState) -> BriefingState:
        """Node 2: Analyze articles using Research Analyst"""
        print("[STAGE 2] Research Analyst - Analyzing articles...")
        
        start_time = datetime.now()
        log_with_context(
            self.logger, "info",
            f"Starting article analysis for {len(state.get('articles', []))} articles",
            request_id=state['request_id'],
            user_id=state['user_id'],
            article_count=len(state.get('articles', []))
        )
        
        state["status"] = "analyzing"
        
        try:
            # Validate input
            if not state.get("articles") or len(state["articles"]) == 0:
                raise ValueError("No articles to analyze")
            
            if not state.get("target_duration") or state["target_duration"] <= 0:
                raise ValueError(f"Invalid target duration: {state.get('target_duration')}")
            
            analyst = ResearchAnalyst(
                use_ai=self.use_ai,
                domain=state.get("domain", "general")
            )
            
            analyzed = analyst.analyze_articles(
                articles=state["articles"],
                target_duration=state["target_duration"],
                words_per_minute=self.words_per_minute
            )
            
            if not analyzed or len(analyzed) == 0:
                raise ValueError("Analysis produced no results")
            
            summary = analyst.get_analysis_summary(analyzed)
            
            state["analyzed_articles"] = analyzed
            state["analysis_summary"] = summary
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            log_with_context(
                self.logger, "info",
                "Article analysis completed",
                request_id=state['request_id'],
                duration_ms=duration_ms,
                analyzed_count=len(analyzed)
            )
            
            print(f"   ✓ Analyzed {len(analyzed)} articles")
            print(f"   ✓ Tier breakdown: {summary['tier_breakdown']}")
            
            return state
            
        except ValueError as e:
            log_with_context(
                self.logger, "error",
                f"Analysis validation error: {e}",
                request_id=state['request_id']
            )
            state["status"] = "failed"
            state["error"] = f"Analysis validation failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"Analysis failed: {e}",
                request_id=state['request_id'],
                error_type=type(e).__name__
            )
            state["status"] = "failed"
            state["error"] = f"Analysis failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
    

    @track(name="write_script")
    def write_script_node(self, state: BriefingState) -> BriefingState:
        """Node 3: Write script using Script Writer"""
        print("✍️  STAGE 3: Script Writer - Crafting news script...")
        
        state["status"] = "writing"
        
        try:
            # Validate input
            if not state.get("analyzed_articles") or len(state["analyzed_articles"]) == 0:
                raise ValueError("No analyzed articles available for script writing")
            
            writer = ScriptWriter(use_ai=self.use_ai, news_style="professional")
            
            script = writer.write_script(
                analyzed_articles=state["analyzed_articles"],
                briefing_title=f"News Briefing for {state['user_id']}",
                words_per_minute=self.words_per_minute
            )
            
            # Validate output
            if not script or not hasattr(script, 'total_word_count'):
                raise ValueError("Script generation produced invalid output")
            
            if script.total_word_count == 0:
                raise ValueError("Generated script is empty")
            
            state["news_script"] = script
            
            print(f"   ✓ Script written: {script.total_word_count} words")
            print(f"   ✓ Estimated duration: {script.estimated_duration}s")
            
            return state
            
        except ValueError as e:
            state["status"] = "failed"
            state["error"] = f"Script validation failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
        except Exception as e:
            state["status"] = "failed"
            state["error"] = f"Script writing failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            self.logger.exception("Unexpected error in script writing")
            return state
    
    
    @track(name="generate_audio")
    def generate_audio_node(self, state: BriefingState) -> BriefingState:
        """Node 4: Generate audio using Audio Speaker"""
        print("[STAGE 4] Audio Speaker - Generating audio...")
        
        state["status"] = "generating"
        
        try:
            # Validate input
            if not state.get("news_script"):
                raise ValueError("No script available for audio generation")
            
            # Validate output directory
            from pathlib import Path
            output_dir = Path(self.output_dir)
            if not output_dir.exists():
                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                except OSError as e:
                    raise OSError(f"Failed to create output directory {output_dir}: {e}") from e
            
            try:
                speaker = AudioSpeaker(
                    provider=state.get("tts_provider", "openai"),
                    voice_id=state.get("tts_voice") or "marin",  # Default to marin
                    output_dir=self.output_dir,
                    audio_format=state.get("audio_format", "mp3")
                )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize AudioSpeaker: {e}") from e
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"briefing_{state['user_id']}_{timestamp}"
            
            try:
                audio = speaker.generate_audio(
                    script=state["news_script"],
                    filename=filename,
                    add_music=state.get("add_music", False),
                    music_file=state.get("music_file")
                )
            except Exception as e:
                raise RuntimeError(f"TTS generation failed: {e}") from e
            
            # Validate output
            print(f"DEBUG: Audio object type: {type(audio)}")
            if audio:
                 print(f"DEBUG: Audio object attrs: {dir(audio)}")

            if not audio or not hasattr(audio, 'audio_filepath'):
                raise ValueError(f"Audio generation produced invalid output: {audio}")
            
            if not Path(audio.audio_filepath).exists():
                raise FileNotFoundError(f"Generated audio file not found: {audio.audio_filepath}")
            
            state["audio_output"] = audio
            state["audio_filepath"] = audio.audio_filepath
            
            print(f"   ✓ Audio generated: {audio.audio_filepath}")
            print(f"   ✓ Duration: {audio.duration}s")
            
            return state
            
        except (ValueError, FileNotFoundError) as e:
            state["status"] = "failed"
            state["error"] = f"Audio validation failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
        except (OSError, RuntimeError) as e:
            state["status"] = "failed"
            state["error"] = str(e)
            print(f"   ❌ Error: {state['error']}")
            return state
        except Exception as e:
            state["status"] = "failed"
            state["error"] = f"Audio generation failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            self.logger.exception("Unexpected error in audio generation")
            return state
    
    
    @track(name="save_outputs")
    def save_outputs_node(self, state: BriefingState) -> BriefingState:
        """Node 5: Save script and analysis files"""
        #print(" STAGE 5: Saving outputs...")
        
        try:
            from pathlib import Path
            
            # Validate input
            if not state.get("news_script"):
                raise ValueError("No script available to save")
            
            if not state.get("analysis_summary"):
                raise ValueError("No analysis summary available to save")
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_dir = Path(self.output_dir)
            
            # Ensure output directory exists
            try:
                output_dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise OSError(f"Failed to create output directory {output_dir}: {e}") from e
            
            # Save script
            script_path = output_dir / f"script_{state['user_id']}_{timestamp}.txt"
            try:
                writer = ScriptWriter()
                writer.export_script(state["news_script"], str(script_path))
                state["script_filepath"] = str(script_path)
            except OSError as e:
                raise OSError(f"Failed to save script to {script_path}: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Script export failed: {e}") from e
            
            # Save analysis
            analysis_path = output_dir / f"analysis_{state['user_id']}_{timestamp}.json"
            try:
                with open(analysis_path, 'w', encoding='utf-8') as f:
                    json.dump(state["analysis_summary"], f, indent=2, ensure_ascii=False)
                state["analysis_filepath"] = str(analysis_path)
            except OSError as e:
                raise OSError(f"Failed to save analysis to {analysis_path}: {e}") from e
            except (TypeError, ValueError) as e:
                raise ValueError(f"Failed to serialize analysis data: {e}") from e
            
            # Verify files were created
            if not script_path.exists():
                raise FileNotFoundError(f"Script file was not created: {script_path}")
            
            if not analysis_path.exists():
                raise FileNotFoundError(f"Analysis file was not created: {analysis_path}")
            
            print(f"   ✓ Script saved: {script_path}")
            print(f"   ✓ Analysis saved: {analysis_path}")
            
            # Upload to S3 if enabled
            if S3_ENABLED:
                print(f"   📤 Uploading to S3...")
                s3_urls = upload_briefing_package(
                    user_id=state['user_id'],
                    job_id=state['request_id'],
                    audio_file=state.get("audio_filepath"),
                    script_file=str(script_path),
                    analysis_file=str(analysis_path)
                )
                
                # Store S3 URLs in state (override local paths)
                if s3_urls.get("audio_url"):
                    state["audio_url"] = s3_urls["audio_url"]
                    print(f"   ✓ Audio uploaded to S3")
                
                if s3_urls.get("script_url"):
                    state["script_url"] = s3_urls["script_url"]
                    print(f"   ✓ Script uploaded to S3")
                
                if s3_urls.get("analysis_url"):
                    state["analysis_url"] = s3_urls["analysis_url"]
                    print(f"   ✓ Analysis uploaded to S3")
                
                # Verify we have the audio URL
                if not state.get("audio_url"):
                    print(f"   ⚠️  WARNING: Audio uploaded checking failed - audio_url not set in state")
                    # Fallback construct if upload succeeded but key missing (shouldn't happen)
                    if s3_urls.get("audio_url"):
                         state["audio_url"] = s3_urls["audio_url"]
                else:
                    print(f"   ✓ CONFIRMED: State audio_url set to: {state['audio_url']}")
            else:
                print(f"   ℹ️  S3 upload disabled - files saved locally only")
            
            state["status"] = "complete"
            state["completed_at"] = datetime.now().isoformat()
            
            return state
            
        except (ValueError, FileNotFoundError) as e:
            state["status"] = "failed"
            state["error"] = f"Output validation failed: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            return state
        except OSError as e:
            state["status"] = "failed"
            state["error"] = str(e)
            print(f"   ❌ Error: {state['error']}")
            return state
        except Exception as e:
            state["status"] = "failed"
            state["error"] = f"Failed to save outputs: {str(e)}"
            print(f"   ❌ Error: {state['error']}")
            self.logger.exception("Unexpected error saving outputs")
            return state
    
    
    @track(name="send_notification")
    def send_notification_node(self, state: BriefingState) -> BriefingState:
        """Node 6: Send notification to user"""
        #print("📬 STAGE 6: Sending notification...")
        
        try:
            # Send webhook notification if configured
            if state.get("notification_webhook"):
                try:
                    import requests
                except ImportError:
                    print("   ⚠️  'requests' library not installed, skipping webhook notification")
                    return state
                
                webhook_url = state["notification_webhook"]
                
                # Validate webhook URL
                if not webhook_url.startswith(('http://', 'https://')):
                    print(f"   ⚠️  Invalid webhook URL: {webhook_url}")
                    return state
                
                payload = {
                    "request_id": state["request_id"],
                    "user_id": state["user_id"],
                    "status": state["status"],
                    "audio_file": state.get("audio_filepath"),
                    "duration": state["audio_output"].duration if state.get("audio_output") else None,
                    "completed_at": state.get("completed_at")
                }
                
                try:
                    response = requests.post(
                        webhook_url,
                        json=payload,
                        timeout=10
                    )
                    response.raise_for_status()
                    print(f"   ✓ Webhook notification sent (status: {response.status_code})")
                except requests.exceptions.Timeout:
                    print(f"   ⚠️  Webhook timeout: {webhook_url}")
                except requests.exceptions.ConnectionError:
                    print(f"   ⚠️  Webhook connection failed: {webhook_url}")
                except requests.exceptions.HTTPError as e:
                    print(f"   ⚠️  Webhook HTTP error: {e}")
                except Exception as e:
                    print(f"   ⚠️  Webhook failed: {e}")
            
            # Email notification
            if state.get("notification_email"):
                email = state["notification_email"]
                
                # Basic email validation
                if not email or '@' not in email:
                    print(f"   ⚠️  Invalid email address: {email}")
                    return state
                
                try:
                    self._send_email_notification(state)
                    print(f"   ✓ Email notification sent to {email}")
                except ImportError:
                    print("   ⚠️  Email dependencies not installed, skipping email notification")
                except Exception as e:
                    log_with_context(
                        self.logger, "error",
                        f"Email notification failed: {e}",
                        request_id=state['request_id'],
                        error_type=type(e).__name__
                    )
                    print(f"   ⚠️  Email notification failed: {e}")
            
            #print(f"   ✓ Notification process complete")
            
            return state
            
        except Exception as e:
            # Notifications are non-critical, log but don't fail the workflow
            print(f"   ⚠️  Notification failed (non-critical): {e}")
            log_with_context(
                self.logger, "warning",
                f"Notification node encountered error: {e}",
                request_id=state.get('request_id', 'unknown'),
                error_type=type(e).__name__
            )
            return state
    
    def _send_email_notification(self, state: BriefingState):
        """Send email notification using EmailNotifier"""
        notifier = EmailNotifier()
        notifier.send_notification(
            to_email=state["notification_email"],
            request_id=state["request_id"],
            user_id=state["user_id"],
            status=state["status"],
            audio_filepath=state.get("audio_filepath"),
            script_filepath=state.get("script_filepath"),
            duration=state["audio_output"].duration if state.get("audio_output") else None,
            error=state.get("error")
        )
    

    @track(name="briefing_workflow")
    def run(self, initial_state: Dict[str, Any]) -> BriefingState:
        """Execute the workflow"""
        # Set correlation ID for logging
        request_id = initial_state.get('request_id', str(uuid.uuid4()))
        set_correlation_id(request_id)
        
        log_with_context(
            self.logger, "info",
            "Starting briefing workflow",
            request_id=request_id,
            user_id=initial_state.get('user_id', 'default')
        )
        
        print(f"\n{'='*60}")
        print(f" AUDIO BRIEFING SYSTEM ")
        print(f"   Request ID: {request_id}")
        print(f"   User ID: {initial_state.get('user_id', 'default')}")
        print(f"{'='*60}\n")
        
        start_time = datetime.now()
        
        # Run the graph
        result = self.graph.invoke(initial_state)
        
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        
        print(f"\n{'='*60}")
        if result["status"] == "complete":
            log_with_context(
                self.logger, "info",
                "Briefing workflow completed successfully",
                request_id=request_id,
                duration_ms=duration_ms,
                audio_duration=result.get('audio_output').duration if result.get('audio_output') else None
            )
            print(f"✅ BRIEFING COMPLETE")
            print(f"{'='*60}")
            print(f" Audio: {result.get('audio_filepath')}")
            print(f" Script: {result.get('script_filepath')}")
            print(f" Analysis: {result.get('analysis_filepath')}")
            print(f"Completed at: {result.get('completed_at')}")
        else:
            log_with_context(
                self.logger, "error",
                f"Briefing workflow failed",
                request_id=request_id,
                duration_ms=duration_ms,
                error=result.get('error', 'Unknown error')
            )
            print(f"❌ BRIEFING FAILED")
            print(f"{'='*60}")
            print(f"Error: {result.get('error', 'Unknown error')}")
        print(f"{'='*60}\n")
        
        return result
