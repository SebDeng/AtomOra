"""Tests for silence mode behavior in AtomOraApp."""

from unittest.mock import MagicMock
import pytest


class FakeChatPanel:
    """Minimal ChatPanel stand-in for testing."""
    def __init__(self):
        self.messages = []
        self.last_update = None

    def show(self): pass
    def append_message(self, role, text, icon=None):
        self.messages.append((role, text))
    def update_last_message(self, text):
        self.last_update = text
    def clear(self): self.messages.clear()


class FakeAgent:
    """Fake AgentLoop that yields predetermined chunks."""
    def __init__(self, chunks):
        self._chunks = chunks
    def stream(self, msg, images=None, interrupt_check=None):
        for c in self._chunks:
            yield c


class FakeTTS:
    """Fake TTS engine."""
    def __init__(self):
        self.is_speaking = False
        self._speaking = False
        self.spoken_sentences = []
        self.stopped = False

    def speak_streamed_sync(self, sentence_iter):
        self._speaking = True
        self.is_speaking = True
        for s in sentence_iter:
            self.spoken_sentences.append(s)
        self._speaking = False
        self.is_speaking = False

    def stop(self):
        self.stopped = True
        self._speaking = False
        self.is_speaking = False


class FakeMic:
    """Fake Microphone."""
    def __init__(self):
        self._running = False
        self.stopped = False
        self.started = False

    def stop(self):
        self._running = False
        self.stopped = True

    def start_ambient(self, callback=None):
        self._running = True
        self.started = True

    def pause(self): pass
    def resume(self): pass


class TestSilenceMode:
    """Test silence mode toggle and text-only response."""

    def _make_app(self, chunks=None):
        """Create a partially-constructed AtomOraApp for testing."""
        from atomora.main import AtomOraApp
        app = object.__new__(AtomOraApp)
        app.chat_panel = FakeChatPanel()
        app.agent = FakeAgent(chunks or ["Hello ", "world!"])
        app.tts = FakeTTS()
        app.mic = FakeMic()
        app._interrupted = False
        app._pending_images = []
        app._processing = False
        app._silence_mode = False
        app.menu_status = MagicMock()
        app._set_status = MagicMock()
        return app

    def test_stream_and_show_no_tts(self):
        """_stream_and_show streams text to panel but does NOT call TTS."""
        app = self._make_app(["Hi ", "there."])
        result = app._stream_and_show("test message")

        assert result == "Hi there."
        assert app.tts.spoken_sentences == []  # TTS not called
        assert app.chat_panel.last_update == "Hi there."

    def test_stream_and_show_updates_panel_live(self):
        """_stream_and_show updates the chat panel as chunks arrive."""
        app = self._make_app(["A", "B", "C"])
        result = app._stream_and_show("test")

        assert result == "ABC"
        assert app.chat_panel.last_update == "ABC"

    def test_stream_and_show_handles_interrupt(self):
        """_stream_and_show stops on interrupt and marks message."""
        app = self._make_app(["Hi ", "there ", "friend."])
        # Interrupt after first chunk
        chunks_seen = [0]
        original_stream = app.agent.stream
        def counting_stream(*args, **kwargs):
            for c in original_stream(*args, **kwargs):
                chunks_seen[0] += 1
                if chunks_seen[0] >= 2:
                    app._interrupted = True
                yield c
        app.agent.stream = counting_stream

        result = app._stream_and_show("test")
        assert "[interrupted]" in app.chat_panel.last_update

    def test_stream_and_speak_uses_tts(self):
        """_stream_and_speak routes through TTS (existing behavior)."""
        app = self._make_app(["Hello."])
        app._stream_and_speak("test")
        assert len(app.tts.spoken_sentences) > 0

    def test_on_text_input_silence_mode_no_tts(self):
        """In silence mode, text input uses _stream_and_show (no TTS)."""
        app = self._make_app(["Response."])
        app._silence_mode = True
        app.chat_panel.append_message("user", "user question")
        app._process_text_input("user question")
        assert app.tts.spoken_sentences == []

    def test_on_text_input_voice_mode_uses_tts(self):
        """In voice mode, text input uses _stream_and_speak (with TTS)."""
        app = self._make_app(["Answer."])
        app._silence_mode = False
        app.chat_panel.append_message("user", "user question")
        app._process_text_input("user question")
        assert len(app.tts.spoken_sentences) > 0

    def test_on_text_input_skips_when_processing(self):
        """Text input is ignored if already processing."""
        app = self._make_app()
        app._processing = True

        app._on_text_input("ignored")
        assert ("user", "ignored") not in app.chat_panel.messages
