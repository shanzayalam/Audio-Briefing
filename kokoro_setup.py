"""
Kokoro TTS Setup Helper
Auto-downloads and configures Kokoro models
"""

import os
import sys
from pathlib import Path
import urllib.request
import zipfile

KOKORO_MODELS_DIR = Path("models/kokoro")
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/kokoro-v0_19.onnx"
VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files/voices.bin"

def download_file(url: str, dest: Path):
    """Download a file with progress"""
    print(f"Downloading {url.split('/')[-1]}...")
    
    def progress_hook(count, block_size, total_size):
        percent = int(count * block_size * 100 / total_size)
        sys.stdout.write(f"\r  Progress: {percent}%")
        sys.stdout.flush()
    
    urllib.request.urlretrieve(url, dest, progress_hook)
    print("\n  ✓ Downloaded")

def setup_kokoro():
    """Download and setup Kokoro models"""
    
    # Create models directory
    KOKORO_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    
    model_path = KOKORO_MODELS_DIR / "kokoro-v0_19.onnx"
    voices_path = KOKORO_MODELS_DIR / "voices.bin"
    
    # Download model if not exists
    if not model_path.exists():
        print("Kokoro model not found. Downloading (~60MB)...")
        download_file(MODEL_URL, model_path)
    else:
        print(f"✓ Model found: {model_path}")
    
    # Download voices if not exists
    if not voices_path.exists():
        print("Kokoro voices not found. Downloading (~2MB)...")
        download_file(VOICES_URL, voices_path)
    else:
        print(f"✓ Voices found: {voices_path}")
    
    print("\n✓ Kokoro setup complete!")
    return str(model_path), str(voices_path)

def get_kokoro_paths():
    """Get paths to Kokoro model and voices"""
    model_path = KOKORO_MODELS_DIR / "kokoro-v0_19.onnx"
    voices_path = KOKORO_MODELS_DIR / "voices.bin"
    
    if not model_path.exists() or not voices_path.exists():
        return setup_kokoro()
    
    return str(model_path), str(voices_path)

if __name__ == "__main__":
    setup_kokoro()
