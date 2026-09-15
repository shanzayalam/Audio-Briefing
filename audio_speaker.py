"""
Audio Speaker Module
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass
from script_writer import NewsScript
import os
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from logger_config import setup_logger, log_with_context

load_dotenv()


@dataclass
class AudioOutput:
    """Audio generation result"""
    audio_filepath: str
    duration: int  # actual duration in seconds
    file_size: int  # bytes
    script_word_count: int
    metadata: Dict[str, Any]


class AudioSpeaker:
    """
    Audio Speaker - Final role in the newsroom pipeline
    Converts script to professional audio
    """
    
    def __init__(
        self, 
        provider: str = "elevenlabs",
        voice_id: Optional[str] = None,
        output_dir: str = "output",
        audio_format: str = "mp3"
    ):
        """
        Initialize the audio speaker
        
        Args:
            provider: TTS provider ('elevenlabs', 'openai', 'gtts', 'azure')
            voice_id: Specific voice to use (provider-dependent)
            output_dir: Directory to save audio files
            audio_format: Audio format ('mp3', 'aac', 'opus') - default 'mp3'
        """
        self.logger = setup_logger(__name__)
        self.provider = provider.lower()
        self.voice_id = voice_id
        self.audio_format = audio_format.lower()
        
        # Validate format
        valid_formats = ['mp3', 'aac', 'opus', 'flac', 'wav']
        if self.audio_format not in valid_formats:
            print(f"Warning: Unknown format '{audio_format}', defaulting to 'mp3'")
            self.audio_format = 'mp3'
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Initialize the selected TTS provider
        self._initialize_provider()
    
    def _initialize_provider(self):
        """Initialize the selected TTS provider"""
        
        if self.provider == "elevenlabs":
            try:
                from elevenlabs import ElevenLabs
                self.client = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))
                # Default professional news voice
                self.voice_id = self.voice_id or "21m00Tcm4TlvDq8ikWAM"  # Rachel
            except ImportError:
                print("ElevenLabs not installed. Install with: pip install elevenlabs")
                self._fallback_to_gtts()
        
        elif self.provider == "openai":
            try:
                import openai
                openai.api_key = os.getenv("OPENAI_API_KEY")
                self.client = openai
                # Default OpenAI voice
                self.voice_id = self.voice_id or "marin"  # Professional voice
            except ImportError:
                print("OpenAI not properly configured.")
                self._fallback_to_gtts()
        
        elif self.provider == "gtts":
            try:
                from gtts import gTTS
                self.client = gTTS
                self.voice_id = "en"  # Language code
            except ImportError:
                print("gTTS not installed. Install with: pip install gTTS")
                raise
        
        elif self.provider == "edge":
            try:
                import edge_tts
                self.client = edge_tts
                # Default Microsoft Edge voice (excellent quality)
                self.voice_id = self.voice_id or "en-US-AriaNeural"  # Female, professional
            except ImportError:
                print("Edge TTS not installed. Install with: pip install edge-tts")
                self._fallback_to_gtts()
        
        elif self.provider == "silero":
            # Silero disabled because PyTorch is removed to reduce image size
            print("Silero TTS is disabled (PyTorch removed). Please select another provider.")
            self._fallback_to_gtts()
        
        elif self.provider == "pyttsx3":
            try:
                import pyttsx3
                self.client = pyttsx3.init()
                # Use system default voice (Windows SAPI on Windows, eSpeak on Linux)
                if self.voice_id:
                    self.client.setProperty('voice', self.voice_id)
            except ImportError:
                print("Pyttsx3 not installed. Install with: pip install pyttsx3")
                self._fallback_to_gtts()
        
        elif self.provider == "kokoro":
            try:
                import kokoro_onnx
                from kokoro_setup import get_kokoro_paths
                
                # Auto-download models if needed
                model_path, voices_path = get_kokoro_paths()
                
                # Initialize Kokoro with model paths
                self.client = kokoro_onnx.Kokoro(model_path, voices_path)
                self.voice_id = self.voice_id or "af_sky"  # American female
            except ImportError:
                print("Kokoro TTS not installed. Install with: pip install kokoro-onnx")
                self._fallback_to_gtts()
            except Exception as e:
                print(f"Kokoro initialization failed: {e}")
                self._fallback_to_gtts()
        
        elif self.provider == "azure":
            try:
                import azure.cognitiveservices.speech as speechsdk
                speech_key = os.getenv("AZURE_SPEECH_KEY")
                speech_region = os.getenv("AZURE_SPEECH_REGION")
                
                self.speech_config = speechsdk.SpeechConfig(
                    subscription=speech_key, 
                    region=speech_region
                )
                self.voice_id = self.voice_id or "en-US-JennyNeural"
                self.speech_config.speech_synthesis_voice_name = self.voice_id
                self.client = speechsdk
            except ImportError:
                print("Azure SDK not installed. Install with: pip install azure-cognitiveservices-speech")
                self._fallback_to_gtts()
    
    def _fallback_to_gtts(self):
        """Fallback to gTTS if primary provider fails"""
        print("Falling back to gTTS (free, basic quality)")
        self.provider = "gtts"
        from gtts import gTTS
        self.client = gTTS
        self.voice_id = "en"
    
    def _preprocess_text(self, text: str) -> str:
        """
        Preprocess text to normalize currencies and formatting for TTS.
        
        Converts:
        - "Dh15 million" -> "15 million Dirhams"
        - "Dh 15" -> "15 Dirhams"
        - "$15" -> "15 Dollars" (Explicitly ensuring this)
        """
        import re
        
        # 1. Handle UAE Dirhams (Dh/AED) at start
        # Matches: Dh15, Dh 15, Dh15.5, Dh 15 million, Dh 15.5 billion
        # Group 1: The number and optional magnitude (million/billion)
        pattern_dh_start = r'(?:Dh|AED)\s*([\d\.,]+(?:\s+(?:million|billion|trillion))?)'
        text = re.sub(pattern_dh_start, r'\1 Dirhams', text, flags=re.IGNORECASE)
        
        # 2. Handle UAE Dirhams (Dh/AED) at end
        # Matches: 15 Dh, 15Dh, 15 million Dh
        pattern_dh_end = r'([\d\.,]+(?:\s+(?:million|billion|trillion))?)\s*(?:Dh|AED)\b'
        text = re.sub(pattern_dh_end, r'\1 Dirhams', text, flags=re.IGNORECASE)
        
        # 3. Handle Dollar sign (Explicit expansion if needed, though most TTS handle it)
        # Matches: $15, $ 15 million
        pattern_dollar = r'\$\s*([\d\.,]+(?:\s+(?:million|billion|trillion))?)'
        text = re.sub(pattern_dollar, r'\1 Dollars', text)
        
        return text
    def generate_audio(
        self, 
        script: NewsScript,
        filename: Optional[str] = None,
        speed: float = 1.0,
        add_music: bool = False,
        music_file: Optional[str] = None
    ) -> AudioOutput:
        """
        Generate audio from script
        
        Args:
            script: NewsScript object
            filename: Custom filename (without extension)
            speed: Speaking speed multiplier (0.5 to 2.0)
            add_music: Whether to add background music
            music_file: Path to background music file (optional)
            
        Returns:
            AudioOutput object with file info
            
        Raises:
            ValueError: If inputs are invalid
            RuntimeError: If audio generation fails
        """
        
        if not script or not hasattr(script, 'full_script'):
            print("DEBUG: Invalid script provided to generate_audio")
            raise ValueError("Invalid script object provided")
        
        if not script.full_script or not script.full_script.strip():
            raise ValueError("Script text is empty")
            
        # Preprocess text for better TTS pronunciation
        # processed_text = self._preprocess_text(script.full_script)
        processed_text = script.full_script
        

        if speed <= 0 or speed > 3.0:
            raise ValueError(f"Invalid speed: {speed}. Must be between 0 and 3.0")
        
        # Validate output directory
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise RuntimeError(f"Failed to create output directory {self.output_dir}: {e}") from e
        
        # Generate filename if not provided
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"briefing_{timestamp}"
        
        # Add appropriate extension based on format
        file_extension = self.audio_format if self.audio_format != 'aac' else 'm4a'
        filepath = self.output_dir / f"{filename}.{file_extension}"
        
        # Generate audio based on provider
        try:
            if self.provider == "elevenlabs":
                audio_path = self._generate_elevenlabs(processed_text, filepath)
            elif self.provider == "openai":
                audio_path = self._generate_openai(processed_text, filepath, speed)
            elif self.provider == "edge":
                audio_path = self._generate_edge(processed_text, filepath)
            elif self.provider == "silero":
                raise ValueError("Silero TTS is disabled because PyTorch is not installed.")
            elif self.provider == "pyttsx3":
                audio_path = self._generate_pyttsx3(processed_text, filepath)
            elif self.provider == "kokoro":
                audio_path = self._generate_kokoro(processed_text, filepath)
            elif self.provider == "gtts":
                audio_path = self._generate_gtts(processed_text, filepath)
            elif self.provider == "azure":
                audio_path = self._generate_azure(processed_text, filepath)
            else:
                raise ValueError(f"Unknown provider: {self.provider}")
            
            # Verify audio file was created
            if not audio_path or not os.path.exists(audio_path):
                raise FileNotFoundError(f"Audio file was not created: {audio_path}")
            
        except Exception as e:
            # If primary provider fails, try falling back to gtts
            if self.provider != "gtts":
                print(f"Warning: {self.provider} failed: {e}. Falling back to gtts...")
                try:
                    self.provider = "gtts"
                    audio_path = self._generate_gtts(processed_text, filepath)
                    if not audio_path or not os.path.exists(audio_path):
                        raise FileNotFoundError(f"Fallback gtts also failed to create audio file")
                except Exception as fallback_error:
                    raise RuntimeError(f"Both primary ({self.provider}) and fallback (gtts) TTS failed: {e}, {fallback_error}") from e
            else:
                raise RuntimeError(f"Audio generation failed: {e}") from e
        
        # Add background music if requested
        if add_music:
            try:
                if music_file and not os.path.exists(music_file):
                    print(f"Warning: Music file not found: {music_file}. Skipping background music.")
                else:
                    audio_path = self._add_background_music(audio_path, music_file)
            except Exception as e:
                print(f"Warning: Failed to add background music: {e}. Continuing without music.")
        
        # Get file info
        try:
            file_size = os.path.getsize(audio_path)
        except OSError as e:
            raise RuntimeError(f"Failed to get file size: {e}") from e
        
        # Get actual duration using pydub if available
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            duration = int(len(audio) / 1000)  # Convert ms to seconds
        except ImportError:
            # Fallback to estimated duration
            duration = script.estimated_duration
        except Exception as e:
            print(f"Warning: Failed to get audio duration: {e}. Using estimated duration.")
            duration = script.estimated_duration
        
        output = AudioOutput(
            audio_filepath=str(audio_path),
            duration=duration,
            file_size=file_size,
            script_word_count=script.total_word_count,
            metadata={
                "provider": self.provider,
                "voice_id": self.voice_id,
                "article_count": script.metadata.get("article_count", 0),
                "categories": script.metadata.get("categories", [])
            }
        )
        print(f"DEBUG: Returning AudioOutput: {output}")
        return output
    
    def _generate_elevenlabs(self, text: str, filepath: Path) -> Path:
        """Generate audio using ElevenLabs"""
        
        try:
            audio = self.client.generate(
                text=text,
                voice=self.voice_id,
                model="eleven_monolingual_v1"
            )
            
            # Save audio
            with open(filepath, 'wb') as f:
                for chunk in audio:
                    f.write(chunk)
            
            return filepath
            
        except Exception as e:
            print(f"ElevenLabs generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True
    )
    def _generate_openai(self, text: str, filepath: Path, speed: float = 1.0) -> Path:
        """Generate audio using OpenAI TTS with retry logic"""
        
        start_time = datetime.now()
        self.logger.info(f"Starting OpenAI TTS generation, text length: {len(text)} chars")
        
        try:
            # OpenAI TTS has 4096 character limit, split if needed
            max_chars = 4000  # Leave buffer
            
            if len(text) <= max_chars:
                # Single request
                response = self.client.audio.speech.create(
                    model="gpt-4o-mini-tts",
                    voice=self.voice_id or "marin",
                    input=text,
                    speed=0.95
                )
                response.stream_to_file(str(filepath))
            else:
                # Split into chunks and merge using binary concatenation
                # Split on sentence boundaries
                sentences = text.replace('? ', '?|').replace('! ', '!|').replace('. ', '.|').split('|')
                chunks = []
                current_chunk = ""
                
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < max_chars:
                        current_chunk += sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = sentence
                
                if current_chunk:
                    chunks.append(current_chunk)
                
                # Generate audio for each chunk and concatenate
                import tempfile
                import shutil
                
                temp_dir = filepath.parent / "temp"
                temp_dir.mkdir(exist_ok=True)
                
                chunk_files = []
                try:
                    for i, chunk in enumerate(chunks):
                        chunk_ext = self.audio_format if self.audio_format != 'aac' else 'm4a'
                        temp_file = temp_dir / f"chunk_{i}.{chunk_ext}"
                        response = self.client.audio.speech.create(
                            model="gpt-4o-mini-tts",
                            voice=self.voice_id or "marin",
                            input=chunk,
                            speed=0.95,
                            response_format=self.audio_format
                        )
                        response.stream_to_file(str(temp_file))
                        chunk_files.append(temp_file)
                    
                    # Simple binary concatenation of MP3 files
                    with open(filepath, 'wb') as outfile:
                        for chunk_file in chunk_files:
                            with open(chunk_file, 'rb') as infile:
                                outfile.write(infile.read())
                finally:
                    # Clean up temp files and directory
                    for chunk_file in chunk_files:
                        try:
                            chunk_file.unlink()
                        except:
                            pass
                    try:
                        shutil.rmtree(temp_dir)
                    except:
                        pass
            
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            log_with_context(
                self.logger, "info",
                "OpenAI TTS generation completed",
                duration_ms=duration_ms,
                text_length=len(text),
                chunks=len(chunks) if len(text) > max_chars else 1
            )
            return filepath
            
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"OpenAI TTS generation failed: {e}",
                error_type=type(e).__name__,
                text_length=len(text)
            )
            print(f"OpenAI TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def _generate_edge(self, text: str, filepath: Path) -> Path:
        """Generate audio using Microsoft Edge TTS (Free, High Quality)"""
        
        try:
            import asyncio
            import edge_tts
            
            self.logger.info(f"Starting Edge TTS generation, text length: {len(text)} chars")
            
            async def generate():
                communicate = edge_tts.Communicate(
                    text=text,
                    voice=self.voice_id or "en-US-AriaNeural"
                )
                await communicate.save(str(filepath))
            
            # Run async function
            asyncio.run(generate())
            
            log_with_context(
                self.logger, "info",
                "Edge TTS generation completed",
                text_length=len(text),
                voice=self.voice_id
            )
            
            return filepath
            
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"Edge TTS generation failed: {e}",
                error_type=type(e).__name__
            )
            print(f"Edge TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def _generate_silero(self, text: str, filepath: Path) -> Path:
        """Generate audio using Silero TTS (Local, CPU-friendly)"""
        
        try:
            import torch
            
            self.logger.info(f"Starting Silero TTS generation, text length: {len(text)} chars")
            
            # Silero has 1000 character limit, need to chunk
            max_chars = 900  # Leave buffer
            
            # Load Silero model (cached after first load)
            device = torch.device('cpu')
            model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-models',
                model='silero_tts',
                language='en',
                speaker='v3_en'
            )
            model.to(device)
            
            # Get speaker
            speaker = self.voice_id or 'en_0'
            sample_rate = 48000
            
            if len(text) <= max_chars:
                # Single generation
                audio = model.apply_tts(
                    text=text,
                    speaker=speaker,
                    sample_rate=sample_rate
                )
                # Save as WAV - convert tensor to numpy
                import scipy.io.wavfile as wavfile
                import numpy as np
                audio_np = audio.cpu().numpy()
                wavfile.write(str(filepath), sample_rate, audio_np)
            else:
                # Split text into chunks and merge
                sentences = text.replace('? ', '?|').replace('! ', '!|').replace('. ', '.|').split('|')
                chunks = []
                current_chunk = ""
                
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < max_chars:
                        current_chunk += sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk)
                        current_chunk = sentence
                
                if current_chunk:
                    chunks.append(current_chunk)
                
                # Generate audio for each chunk
                audio_segments = []
                for chunk in chunks:
                    audio_chunk = model.apply_tts(
                        text=chunk,
                        speaker=speaker,
                        sample_rate=sample_rate
                    )
                    audio_segments.append(audio_chunk)
                
                # Concatenate all audio tensors
                combined_audio = torch.cat(audio_segments)
                
                # Save as WAV - convert tensor to numpy
                import scipy.io.wavfile as wavfile
                import numpy as np
                audio_np = combined_audio.cpu().numpy()
                wavfile.write(str(filepath), sample_rate, audio_np)
            
            log_with_context(
                self.logger, "info",
                "Silero TTS generation completed",
                text_length=len(text),
                speaker=speaker,
                chunks=len(chunks) if len(text) > max_chars else 1
            )
            
            return filepath
            
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"Silero TTS generation failed: {e}",
                error_type=type(e).__name__
            )
            print(f"Silero TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def _generate_pyttsx3(self, text: str, filepath: Path) -> Path:
        """Generate audio using Pyttsx3 (System TTS, fully local, instant)"""
        
        try:
            import pyttsx3
            
            self.logger.info(f"Starting Pyttsx3 TTS generation, text length: {len(text)} chars")
            
            # Use existing engine or create new one
            engine = self.client if hasattr(self, 'client') and self.client else pyttsx3.init()
            
            # Save to file
            engine.save_to_file(text, str(filepath))
            engine.runAndWait()
            
            log_with_context(
                self.logger, "info",
                "Pyttsx3 TTS generation completed",
                text_length=len(text)
            )
            
            return filepath
            
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"Pyttsx3 TTS generation failed: {e}",
                error_type=type(e).__name__
            )
            print(f"Pyttsx3 TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def _generate_kokoro(self, text: str, filepath: Path) -> Path:
        """Generate audio using Kokoro TTS (Local, CPU-optimized, 8/10 quality)"""
        
        try:
            import scipy.io.wavfile as wavfile
            
            self.logger.info(f"Starting Kokoro TTS generation, text length: {len(text)} chars")
            
            # Generate audio with Kokoro
            audio_array, sample_rate = self.client.create(
                text=text,
                voice=self.voice_id,
                speed=1.0,
                lang="en-us"
            )
            
            # Save as WAV
            wavfile.write(str(filepath), sample_rate, audio_array)
            
            log_with_context(
                self.logger, "info",
                "Kokoro TTS generation completed",
                text_length=len(text),
                voice=self.voice_id,
                sample_rate=sample_rate
            )
            
            return filepath
            
        except Exception as e:
            log_with_context(
                self.logger, "error",
                f"Kokoro TTS generation failed: {e}",
                error_type=type(e).__name__
            )
            print(f"Kokoro TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def _generate_gtts(self, text: str, filepath: Path) -> Path:
        """Generate audio using gTTS (free, basic quality)"""
        
        try:
            from gtts import gTTS
            
            # Use slightly slower speech for better clarity
            tts = gTTS(text=text, lang='en', slow=False, tld='com')
            tts.save(str(filepath))
            return filepath
            
        except Exception as e:
            raise Exception(f"gTTS generation failed: {e}")
    
    def _add_background_music(
        self, 
        voice_path: Path, 
        music_path: Optional[str] = None
    ) -> Path:
        """
        Add background music to voice audio
        
        Args:
            voice_path: Path to voice audio file
            music_path: Path to background music (optional, uses default if None)
            
        Returns:
            Path to mixed audio file
        """
        try:
            from pydub import AudioSegment
            from pydub.effects import normalize
            
            # Load voice audio
            voice = AudioSegment.from_file(voice_path)
            
            # Use provided music or create simple tone if none available
            if music_path and os.path.exists(music_path):
                music = AudioSegment.from_file(music_path)
            else:
                # Generate simple ambient background (low frequency hum)
                # This creates a subtle background presence
                from pydub.generators import Sine
                # Create a very subtle low frequency tone
                music = Sine(220).to_audio_segment(duration=len(voice))
                music = music - 30  # Make it very quiet
            
            # Loop/trim music to match voice duration
            if len(music) < len(voice):
                # Loop music
                loops_needed = (len(voice) // len(music)) + 1
                music = music * loops_needed
            music = music[:len(voice)]
            
            # Reduce music volume to 15% (background level)
            music = music - 18  # Reduce by 18 dB (approximately 15% volume)
            
            # Apply fade in/out to music for professional sound
            music = music.fade_in(2000).fade_out(3000)
            
            # Mix voice and music
            combined = voice.overlay(music)
            
            # Normalize to prevent clipping
            combined = normalize(combined)
            
            # Save mixed version
            output_path = voice_path.parent / f"{voice_path.stem}_mixed{voice_path.suffix}"
            combined.export(output_path, format="mp3", bitrate="192k")
            
            # Replace original file
            os.remove(voice_path)
            os.rename(output_path, voice_path)
            
            return voice_path
            
        except ImportError:
            print("pydub not installed. Skipping background music. Install with: pip install pydub")
            return voice_path
        except Exception as e:
            print(f"Background music mixing failed: {e}. Using voice-only audio.")
            return voice_path
    
    def _generate_azure(self, text: str, filepath: Path) -> Path:
        """Generate audio using Azure Cognitive Services"""
        
        try:
            audio_config = self.client.audio.AudioOutputConfig(filename=str(filepath))
            synthesizer = self.client.SpeechSynthesizer(
                speech_config=self.speech_config,
                audio_config=audio_config
            )
            
            result = synthesizer.speak_text_async(text).get()
            
            if result.reason == self.client.ResultReason.SynthesizingAudioCompleted:
                return filepath
            else:
                raise Exception(f"Azure TTS failed: {result.reason}")
                
        except Exception as e:
            print(f"Azure TTS generation failed: {e}")
            print("Falling back to gTTS...")
            self._fallback_to_gtts()
            return self._generate_gtts(text, filepath)
    
    def adjust_audio_speed(self, audio_path: str, speed_factor: float = 1.0) -> str:
        """
        Adjust audio speed without changing pitch
        
        Args:
            audio_path: Path to audio file
            speed_factor: Speed multiplier (0.5 = half speed, 2.0 = double speed)
            
        Returns:
            Path to adjusted audio file
        """
        try:
            from pydub import AudioSegment
            from pydub.playback import play
            
            audio = AudioSegment.from_file(audio_path)
            
            # Change speed
            if speed_factor != 1.0:
                # This changes both speed and pitch
                # For professional quality, use external tools like ffmpeg
                sound_with_altered_frame_rate = audio._spawn(
                    audio.raw_data,
                    overrides={"frame_rate": int(audio.frame_rate * speed_factor)}
                )
                adjusted = sound_with_altered_frame_rate.set_frame_rate(audio.frame_rate)
                
                # Save adjusted audio
                output_path = audio_path.replace(".mp3", "_adjusted.mp3")
                adjusted.export(output_path, format="mp3")
                return output_path
            
            return audio_path
            
        except ImportError:
            print("pydub not installed. Cannot adjust speed.")
            return audio_path
    
    def add_intro_music(
        self, 
        audio_path: str, 
        intro_music_path: str,
        fade_duration: int = 2000
    ) -> str:
        """
        Add intro music to the briefing
        
        Args:
            audio_path: Path to main audio
            intro_music_path: Path to intro music
            fade_duration: Fade duration in milliseconds
            
        Returns:
            Path to combined audio
        """
        try:
            from pydub import AudioSegment
            
            main_audio = AudioSegment.from_file(audio_path)
            intro_music = AudioSegment.from_file(intro_music_path)
            
            # Fade out intro music
            intro_music = intro_music.fade_out(fade_duration)
            
            # Reduce intro music volume
            intro_music = intro_music - 10  # Reduce by 10dB
            
            # Overlay or concatenate
            combined = intro_music + main_audio
            
            # Save
            output_path = audio_path.replace(".mp3", "_with_intro.mp3")
            combined.export(output_path, format="mp3")
            return output_path
            
        except ImportError:
            print("pydub not installed. Cannot add intro music.")
            return audio_path


# Voice recommendations by provider
VOICE_RECOMMENDATIONS = {
    "elevenlabs": {
        "professional_male": "21m00Tcm4TlvDq8ikWAM",  # Josh
        "professional_female": "EXAVITQu4vr4xnSDxMaL",  # Bella
        "authoritative": "pNInz6obpgDQGcFmaJgB",  # Adam
    },
    "openai": {
        "professional_female": "nova",
        "authoritative_male": "onyx",
        "warm_female": "shimmer",
    },
    "azure": {
        "professional_female": "en-US-JennyNeural",
        "authoritative_male": "en-US-GuyNeural",
        "news_anchor": "en-US-AriaNeural",
    }
}
