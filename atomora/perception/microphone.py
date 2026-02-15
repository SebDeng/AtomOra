"""Voice input: audio recording with VAD-based silence detection.

Day 1: Records audio, saves to temp WAV, returns path for STT.
Future: Qwen3-ASR-0.6B via mlx-audio for streaming transcription.
"""

import io
import tempfile
import threading
import wave

import numpy as np
import sounddevice as sd


class Microphone:
    """Record audio with voice activity detection."""

    def __init__(self, config: dict):
        self.sample_rate = config.get("sample_rate", 16000)
        self.silence_duration = config.get("silence_duration", 1.5)
        self.vad_threshold = config.get("vad_threshold", 0.01)  # RMS energy threshold
        self._recording = False
        self._audio_buffer: list[np.ndarray] = []

    def record_until_stopped(self) -> str | None:
        """Record audio until stop() is called (push-to-talk).

        Returns path to the recorded WAV file, or None if no audio captured.
        """
        self._recording = True
        self._audio_buffer = []
        frames_per_chunk = int(self.sample_rate * 0.1)  # 100ms chunks

        print("[Microphone] Recording... press Talk again to stop")

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=frames_per_chunk,
            ) as stream:
                while self._recording:
                    audio_chunk, _ = stream.read(frames_per_chunk)
                    self._audio_buffer.append(audio_chunk.copy())

        except Exception as e:
            print(f"[Microphone] Recording error: {e}")
            return None
        finally:
            self._recording = False

        if not self._audio_buffer:
            return None

        duration = len(self._audio_buffer) * 0.1
        print(f"[Microphone] Recorded {duration:.1f}s of audio")

        # Discard too-short recordings (< 1s is likely just button noise)
        if duration < 1.0:
            print("[Microphone] Recording too short, discarding")
            return None

        # Trim the first 0.2s to avoid click/pop noise from mic activation
        trim_chunks = 2  # 2 * 100ms = 0.2s
        audio_buffer = self._audio_buffer[trim_chunks:] if len(self._audio_buffer) > trim_chunks else self._audio_buffer

        # Save to temp WAV
        audio_data = np.concatenate(audio_buffer)
        return self._save_wav(audio_data)

    def stop(self):
        """Stop recording."""
        self._recording = False

    def _save_wav(self, audio: np.ndarray) -> str:
        """Save audio array to a temporary WAV file."""
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        audio_int16 = (audio * 32767).astype(np.int16)

        with wave.open(tmp.name, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.sample_rate)
            wf.writeframes(audio_int16.tobytes())

        return tmp.name
