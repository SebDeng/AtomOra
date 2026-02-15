"""Voice input: ambient listening with silero-vad.

Always-on microphone. VAD detects speech start/end automatically.
When speech ends (silence after speech), returns the recorded audio
for transcription. Pauses listening during TTS playback to avoid echo.
"""

import tempfile
import threading
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
        """Main listening loop — runs continuously in background."""
        import torch

        chunk_samples = 512  # silero-vad minimum at 16kHz
        chunk_ms = chunk_samples * 1000 / self.sample_rate  # 32ms
        silence_chunks_needed = int(self.silence_duration * 1000 / chunk_ms)
        min_speech_chunks = int(self.min_speech_duration * 1000 / chunk_ms)

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=chunk_samples,
            ) as stream:

                while self._running:
                    # Wait while paused (during TTS)
                    if self._paused:
                        # Drain the mic buffer to avoid stale audio
                        stream.read(chunk_samples)
                        continue

                    # Phase 1: Wait for speech onset
                    audio_chunk, _ = stream.read(chunk_samples)
                    chunk_tensor = torch.from_numpy(audio_chunk[:, 0].copy())

                    confidence = self._vad(chunk_tensor, self.sample_rate).item()

                    if confidence < 0.5:
                        continue  # No speech — keep waiting

                    # Speech detected! Start recording
                    print("[Microphone] Speech detected")
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
                        print(f"[Microphone] Too short ({speech_count * chunk_ms}ms), skipping")
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

        except Exception as e:
            print(f"[Microphone] Listening error: {e}")
        finally:
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
