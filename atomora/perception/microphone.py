"""Voice input: ambient listening with silero-vad.

Always-on microphone. VAD detects speech start/end automatically.
When speech ends (silence after speech), returns the recorded audio
for transcription. Pauses listening during TTS playback to avoid echo.
"""

import tempfile
import threading
import time
import wave

import numpy as np
import sounddevice as sd


class Microphone:
    """Ambient microphone with VAD-based speech detection."""

    def __init__(self, config: dict):
        self.sample_rate = config.get("sample_rate", 16000)
        self.silence_duration = config.get("silence_duration", 1.5)
        self.min_speech_duration = config.get("min_speech_duration", 0.8)

        self._running = False
        self._paused = False  # Paused during TTS playback
        self._callback = None  # Called with wav_path when speech ends
        self._thread: threading.Thread | None = None

        # VAD
        self._vad = None
        self._init_vad()

    def _init_vad(self):
        """Initialize silero-vad."""
        try:
            from silero_vad import load_silero_vad
            self._vad = load_silero_vad()
            print("[Microphone] silero-vad loaded")
        except Exception as e:
            print(f"[Microphone] VAD init failed: {e}")

    def start_ambient(self, callback):
        """Start ambient listening. Calls callback(wav_path) when speech ends.

        Args:
            callback: Function called with the path to the recorded WAV file
                     whenever a speech segment is detected and completed.
        """
        if self._running:
            return

        self._callback = callback
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print("[Microphone] Ambient listening started")

    def stop(self):
        """Stop ambient listening entirely."""
        self._running = False
        print("[Microphone] Ambient listening stopped")

    def pause(self):
        """Pause listening (e.g., during TTS playback)."""
        self._paused = True

    def resume(self):
        """Resume listening after pause."""
        self._paused = False

    def _listen_loop(self):
        """Main listening loop — runs continuously in background.

        Retries on audio device errors (e.g., after TTS releases the device).
        """
        import torch

        chunk_samples = 512  # silero-vad minimum at 16kHz
        chunk_ms = chunk_samples * 1000 / self.sample_rate  # 32ms
        silence_chunks_needed = int(self.silence_duration * 1000 / chunk_ms)
        min_speech_chunks = int(self.min_speech_duration * 1000 / chunk_ms)

        max_retries = 5
        for attempt in range(max_retries):
            if not self._running:
                break

            try:
                # Brief delay to let audio system settle (especially after TTS)
                if attempt > 0:
                    wait = min(1.0 * attempt, 3.0)
                    print(f"[Microphone] Retrying in {wait:.0f}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                else:
                    time.sleep(0.3)

                with sd.InputStream(
                    samplerate=self.sample_rate,
                    channels=1,
                    dtype="float32",
                    blocksize=chunk_samples,
                ) as stream:

                    print(f"[Microphone] Audio stream opened")
                    self._vad.reset_states()
                    diag_count = 0
                    peak_level = 0.0

                    while self._running:
                        # Wait while paused (during TTS playback)
                        if self._paused:
                            time.sleep(0.1)  # Don't read — avoids audio contention with TTS
                            continue

                        # Phase 1: Wait for speech onset
                        audio_chunk, overflowed = stream.read(chunk_samples)
                        if overflowed:
                            # Stale audio (e.g., buffer filled during pause) — skip
                            self._vad.reset_states()
                            continue

                        # Periodic audio level diagnostics
                        level = float(np.abs(audio_chunk).max())
                        peak_level = max(peak_level, level)
                        diag_count += 1
                        if diag_count % 100 == 0:  # ~3.2s
                            print(f"[Microphone] peak={peak_level:.4f} (listening...)")
                            peak_level = 0.0

                        chunk_tensor = torch.from_numpy(audio_chunk[:, 0].copy())

                        confidence = self._vad(chunk_tensor, self.sample_rate).item()

                        if confidence < 0.5:
                            continue  # No speech — keep waiting

                        # Speech detected! Start recording
                        print(f"[Microphone] Speech detected (confidence={confidence:.2f})")
                        speech_buffer = [audio_chunk.copy()]
                        silence_count = 0
                        speech_count = 1

                        # Phase 2: Record until silence
                        while self._running and not self._paused:
                            audio_chunk, _ = stream.read(chunk_samples)
                            speech_buffer.append(audio_chunk.copy())

                            chunk_tensor = torch.from_numpy(audio_chunk[:, 0].copy())
                            confidence = self._vad(chunk_tensor, self.sample_rate).item()

                            if confidence >= 0.5:
                                silence_count = 0
                                speech_count += 1
                            else:
                                silence_count += 1

                            if silence_count >= silence_chunks_needed:
                                break

                        # Check minimum duration
                        if speech_count < min_speech_chunks:
                            print(f"[Microphone] Too short ({speech_count * chunk_ms:.0f}ms), skipping")
                            self._vad.reset_states()
                            continue

                        duration = len(speech_buffer) * chunk_ms / 1000
                        print(f"[Microphone] Speech ended, {duration:.1f}s recorded")

                        # Reset VAD state for next utterance
                        self._vad.reset_states()

                        # Save and deliver
                        audio_data = np.concatenate(speech_buffer)
                        wav_path = self._save_wav(audio_data)

                        if self._callback:
                            self._callback(wav_path)

                # Clean exit from while loop
                break

            except Exception as e:
                print(f"[Microphone] Audio stream error: {e}")
                if attempt >= max_retries - 1:
                    print("[Microphone] Max retries reached, giving up")

        self._running = False
        print("[Microphone] Listening loop ended")

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
