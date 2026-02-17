"""Text-to-speech output with sentence-level streaming.

Engines:
  - edge: Microsoft Edge neural TTS (cloud, free, high quality)
         Streams sentence-by-sentence for fast time-to-first-word.
  - macos_say: macOS built-in say command (fallback, offline)
"""

import asyncio
import os
import queue as queue_mod
import re
import subprocess
import tempfile
import threading
import time


def _resolve_device(name: str | None, kind: str) -> int | None:
    """Resolve a device name to a sounddevice index."""
    if not name:
        return None
    import sounddevice as sd
    devices = sd.query_devices()
    channel_key = "max_input_channels" if kind == "input" else "max_output_channels"
    for i, d in enumerate(devices):
        if d[channel_key] > 0 and name.lower() in d["name"].lower():
            return i
    print(f"[Audio] Device '{name}' ({kind}) not found, using default")
    return None


class TTSEngine:
    """TTS engine supporting Edge TTS and macOS say fallback."""

    def __init__(self, config: dict):
        self.config = config
        self.engine = config.get("engine", "edge")
        self._speaking = False
        self._process: subprocess.Popen | None = None
        self._device_name: str | None = config.get("device_name")
        self._device_id: int | None = _resolve_device(self._device_name, "output")

    # ─── Public API ───────────────────────────────────────────────────

    def speak(self, text: str):
        """Speak text asynchronously (non-blocking)."""
        if self._speaking:
            self.stop()
        thread = threading.Thread(target=self._speak_sync, args=(text,), daemon=True)
        thread.start()

    def speak_sync(self, text: str):
        """Speak full text synchronously (blocking). Splits into sentences."""
        if self._speaking:
            self.stop()
        self._speak_sync(text)

    def speak_streamed_sync(self, sentence_iter):
        """Speak sentences from a streaming source (blocking).

        sentence_iter: iterator yielding clean, ready-to-speak text segments.
        Sentences are played as they arrive — first sentence starts immediately.
        """
        if self._speaking:
            self.stop()
        self._speaking = True
        try:
            if self.engine == "edge":
                self._speak_edge_sentences(sentence_iter)
            else:
                text = " ".join(sentence_iter)
                if text:
                    self._speak_macos(text)
        except Exception as e:
            print(f"[TTS] Error: {e}")
        finally:
            self._speaking = False

    def stop(self):
        """Stop current speech immediately."""
        self._speaking = False
        try:
            import sounddevice as sd
            sd.stop()
        except Exception:
            pass
        if self._process:
            self._process.terminate()
            self._process = None

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def set_device(self, name: str | None):
        """Change the output device. Takes effect on next playback."""
        self._device_name = name
        self._device_id = _resolve_device(name, "output")
        print(f"[TTS] Device set: {name or 'system default'} (id={self._device_id})")

    # ─── Internal ─────────────────────────────────────────────────────

    def _speak_sync(self, text: str):
        """Speak full text synchronously (batch mode)."""
        self._speaking = True
        try:
            text = _strip_for_speech(text)
            if not text:
                return
            if self.engine == "edge":
                sentences = _split_sentences(text)
                if sentences:
                    print(f"[TTS] Edge batch: {len(sentences)} segment(s)")
                    self._speak_edge_sentences(iter(sentences))
            else:
                self._speak_macos(text)
        except Exception as e:
            print(f"[TTS] Error: {e}")
        finally:
            self._speaking = False

    def _speak_edge_sentences(self, sentence_iter):
        """Core Edge TTS producer-consumer pipeline.

        Works with both batch (pre-split sentences) and streaming
        (sentences arriving from LLM stream) inputs.
        """
        import sounddevice as sd
        import soundfile as sf

        edge_config = self.config.get("edge", {})
        en_voice = edge_config.get("voice", "en-US-AvaMultilingualNeural")
        zh_voice = edge_config.get("voice_zh", "zh-CN-XiaoxiaoNeural")
        rate = edge_config.get("rate", "+0%")

        audio_q: queue_mod.Queue = queue_mod.Queue(maxsize=2)
        t_start = time.perf_counter()

        def _ts():
            return time.perf_counter() - t_start

        def producer():
            voice = None
            loop = asyncio.new_event_loop()
            seg_idx = 0
            try:
                for sentence in sentence_iter:
                    if not self._speaking:
                        break
                    sentence = sentence.strip()
                    if not sentence:
                        continue

                    # Detect voice on first sentence
                    if voice is None:
                        voice = zh_voice if _is_predominantly_chinese(sentence) else en_voice
                        print(f"[TTS] Edge: voice={voice}")

                    t_gen_start = _ts()
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
                    tmp_path = tmp.name
                    tmp.close()
                    try:
                        loop.run_until_complete(
                            self._edge_generate(sentence, voice, rate, tmp_path)
                        )
                        if not self._speaking:
                            break
                        data, sr = sf.read(tmp_path)
                        duration = len(data) / sr
                        print(f"[TTS] seg[{seg_idx}] generated: {_ts():.2f}s (took {_ts()-t_gen_start:.2f}s, audio {duration:.1f}s, {len(sentence)} chars)")
                        audio_q.put((data, sr, seg_idx))
                        seg_idx += 1
                    except Exception as e:
                        print(f"[TTS] seg[{seg_idx}] error: {e}")
                    finally:
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
            finally:
                loop.close()
                audio_q.put(None)

        gen_thread = threading.Thread(target=producer, daemon=True)
        gen_thread.start()

        # Play segments as they arrive
        while self._speaking:
            try:
                item = audio_q.get(timeout=30)
            except queue_mod.Empty:
                print("[TTS] Timed out waiting for audio")
                break
            if item is None:
                break
            data, sr, idx = item
            duration = len(data) / sr
            print(f"[TTS] seg[{idx}] playing:   {_ts():.2f}s (audio {duration:.1f}s)")
            sd.play(data, samplerate=sr, device=self._device_id)
            sd.wait()

        # Drain queue so producer thread can finish
        # (producer might be blocked on audio_q.put)
        while gen_thread.is_alive():
            try:
                audio_q.get(timeout=0.5)
            except queue_mod.Empty:
                continue
        gen_thread.join(timeout=1)

        print(f"[TTS] total: {_ts():.2f}s")

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


# ── Text preprocessing ──────────────────────────────────────────────

# Sentence boundary: English punctuation + whitespace, or Chinese punctuation
SENTENCE_BOUNDARY = re.compile(r'(?<=[.!?])\s+|(?<=[。！？；])')


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences for streaming TTS."""
    raw = re.split(r'(?<=[.!?。！？；])\s+', text)

    # Further split long segments on em-dash or semicolon
    split2 = []
    for part in raw:
        if len(part) > 150:
            subs = re.split(r'\s*[—–]\s+|\s*;\s+', part)
            split2.extend(subs)
        else:
            split2.append(part)

    merged = []
    for part in split2:
        part = part.strip()
        if not part:
            continue
        if merged and len(merged[-1]) < 60:
            merged[-1] += " " + part
        else:
            merged.append(part)

    return merged if merged else [text.strip()]


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
