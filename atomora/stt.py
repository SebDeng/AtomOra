"""Speech-to-text abstraction layer.

Day 1: Uses macOS built-in speech recognition via subprocess (whisper-cpp or say).
Future: Qwen3-ASR-0.6B via mlx-audio.
"""

import re
import subprocess
import os


def transcribe_wav(wav_path: str) -> str:
    print(f"[STT] Transcribing: {wav_path}")
    """Transcribe a WAV file to text.

    Day 1 strategy: Use whisper.cpp if available, else fall back to
    a basic approach.
    """
    # Try whisper.cpp first
    whisper_path = _find_whisper_cpp()
    if whisper_path:
        print(f"[STT] Using whisper binary: {whisper_path}")
        return _transcribe_whisper_cpp(whisper_path, wav_path)

    # Fallback: return a placeholder prompting user to install whisper.cpp
    print("[STT] whisper-cpp not found!")
    return "[STT unavailable — install whisper.cpp: brew install whisper-cpp]"


def _find_whisper_cpp() -> str | None:
    """Find the whisper.cpp binary."""
    # Check common locations (brew installs as whisper-cli)
    candidates = [
        "/opt/homebrew/bin/whisper-cli",
        "/usr/local/bin/whisper-cli",
        "/opt/homebrew/bin/whisper-cpp",
        "/usr/local/bin/whisper-cpp",
        os.path.expanduser("~/whisper.cpp/main"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    # Try which (check both names)
    for name in ["whisper-cli", "whisper-cpp"]:
        try:
            result = subprocess.run(
                ["which", name],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    return None


def _transcribe_whisper_cpp(binary: str, wav_path: str) -> str:
    """Transcribe using whisper.cpp CLI."""
    # Find model file
    model_path = _find_whisper_model()

    cmd = [binary]
    if model_path:
        print(f"[STT] Using model: {model_path}")
        cmd.extend(["-m", model_path])
    else:
        print("[STT] WARNING: No model file found, whisper may fail")
    cmd.extend([
        "-f", wav_path,
        "--no-timestamps",
        "-l", "auto",          # Auto language detection
        "--print-special", "false",
    ])
    print(f"[STT] Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            text = result.stdout.strip()
            # Clean up whisper output artifacts
            text = _clean_whisper_output(text)
            return text if text else "[No speech detected]"
        else:
            return f"[STT error: {result.stderr.strip()[:200]}]"
    except subprocess.TimeoutExpired:
        return "[STT timeout]"
    except Exception as e:
        return f"[STT error: {e}]"


def _clean_whisper_output(text: str) -> str:
    """Remove whisper-cpp artifacts from transcription."""
    # Remove common special tokens
    artifacts = [
        "[BLANK_AUDIO]", "[_EOT_]", "[_BEG_]", "[_SOT_]",
        "[_PREV_]", "[_SOLM_]", "[_NOT_]", "[_TT_",
        "(music)", "(Music)", "(applause)", "(Applause)",
        "(silence)", "(Silence)",
    ]
    for art in artifacts:
        text = text.replace(art, "")

    # Remove any remaining [bracketed] tokens like [_TT_123]
    text = re.sub(r'\[_[A-Z]+_\d*\]', '', text)
    # Remove (descriptive) annotations
    text = re.sub(r'\([^)]*\)', '', text)

    text = text.strip()

    # If what's left is just a very short word (likely noise), discard
    if len(text) <= 3 and not any('\u4e00' <= c <= '\u9fff' for c in text):
        return ""

    return text


def _find_whisper_model() -> str | None:
    """Find a whisper model file."""
    # Common model locations for homebrew whisper-cpp
    candidates = [
        os.path.expanduser("~/.cache/whisper/ggml-large-v3-turbo.bin"),
        os.path.expanduser("~/.cache/whisper/ggml-base.bin"),
        "/opt/homebrew/share/whisper-cpp/models/ggml-large-v3-turbo.bin",
        "/opt/homebrew/share/whisper-cpp/models/ggml-base.bin",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None
