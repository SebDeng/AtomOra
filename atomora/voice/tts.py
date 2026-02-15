"""Text-to-speech output.

Engines:
  - edge: Microsoft Edge neural TTS (cloud, free, high quality)
  - macos_say: macOS built-in say command (fallback, offline)
"""

import asyncio
import re
import subprocess
import tempfile
import threading


class TTSEngine:
    """TTS engine supporting Edge TTS and macOS say fallback."""

    def __init__(self, config: dict):
        self.config = config
        self.engine = config.get("engine", "edge")
        self._speaking = False
        self._process: subprocess.Popen | None = None

    def speak(self, text: str):
        """Speak text asynchronously (non-blocking)."""
        if self._speaking:
            self.stop()
        thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
        thread.start()

    def speak_sync(self, text: str):
        """Speak text synchronously (blocking)."""
        if self._speaking:
            self.stop()
        self._speak_sync(text)

    def _speak_sync(self, text: str):
        """Speak text synchronously."""
        self._speaking = True
        try:
            text = _strip_for_speech(text)
            if not text:
                return
            if self.engine == "edge":
                self._speak_edge(text)
            else:
                self._speak_macos(text)
        except Exception as e:
            print(f"[TTS] Error: {e}")
        finally:
            self._speaking = False

    def _speak_edge(self, text: str):
        """Speak using Microsoft Edge neural TTS."""
        import sounddevice as sd
        import soundfile as sf

        edge_config = self.config.get("edge", {})
        en_voice = edge_config.get("voice", "en-US-AvaMultilingualNeural")
        zh_voice = edge_config.get("voice_zh", "zh-CN-XiaoxiaoNeural")
        rate = edge_config.get("rate", "+0%")

        is_zh = _is_predominantly_chinese(text)
        voice = zh_voice if is_zh else en_voice
        print(f"[TTS] Edge: voice={voice}")

        # Edge TTS is async — run in a new event loop
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        try:
            asyncio.run(self._edge_generate(text, voice, rate, tmp_path))

            if not self._speaking:
                return

            # Play the audio
            data, sr = sf.read(tmp_path)
            sd.play(data, samplerate=sr)
            sd.wait()
        finally:
            import os
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    async def _edge_generate(self, text: str, voice: str, rate: str, output_path: str):
        """Generate audio file with edge-tts."""
        import edge_tts
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)

    def _speak_macos(self, text: str):
        """Use macOS say with auto language detection (fallback)."""
        say_config = self.config.get("macos_say", {})
        en_voice = say_config.get("voice", "Samantha")
        zh_voice = say_config.get("voice_zh", "Tingting")
        rate = say_config.get("rate", 200)

        voice = zh_voice if _is_predominantly_chinese(text) else en_voice
        print(f"[TTS] macOS say: voice={voice}")

        cmd = ["say", "-v", voice, "-r", str(rate), text]
        self._process = subprocess.Popen(cmd)
        self._process.wait()
        self._process = None

    def stop(self):
        """Stop current speech."""
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self._process:
            self._process.terminate()
            self._process = None
        self._speaking = False

    @property
    def is_speaking(self) -> bool:
        return self._speaking


# ── Text preprocessing ──────────────────────────────────────────────

def _strip_for_speech(text: str) -> str:
    """Strip markdown and formatting artifacts before TTS."""
    text = re.sub(r'\*{1,3}', '', text)
    text = re.sub(r'_{1,3}', ' ', text)
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*[-•*]\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[\s]*\d+\.\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'`([^`]*)`', r'\1', text)
    text = re.sub(r'```[\s\S]*?```', '', text)
    text = re.sub(r'\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    return text.strip()


def _is_predominantly_chinese(text: str) -> bool:
    """Check if text is predominantly Chinese by character ratio."""
    if not text:
        return False
    zh_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_chars = len(re.findall(r'[a-zA-Z]', text))
    total = zh_chars + en_chars
    if total == 0:
        return False
    return zh_chars / total >= 0.2
