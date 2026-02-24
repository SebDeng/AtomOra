"""Integration tests for the full text input flow."""

import json
from unittest.mock import MagicMock

from atomora.ui.chat_panel import ChatPanel


class TestTextInputIntegration:
    """Test the full flow: event parsing → callback → response."""

    def test_json_roundtrip(self):
        """JSON from Swift → Python parses correctly."""
        swift_output = '{"event":"text_input","text":"What is the main finding?"}'
        event = json.loads(swift_output)
        assert event["event"] == "text_input"
        assert event["text"] == "What is the main finding?"

    def test_json_with_special_chars(self):
        """Text with quotes and newlines survives JSON roundtrip."""
        text = 'He said "hello"\nNew line here'
        swift_output = json.dumps({"event": "text_input", "text": text})
        event = json.loads(swift_output)
        assert event["text"] == text

    def test_json_with_chinese(self):
        """Chinese text survives JSON roundtrip."""
        text = "这篇paper的main finding是什么？"
        swift_output = json.dumps({"event": "text_input", "text": text}, ensure_ascii=False)
        event = json.loads(swift_output)
        assert event["text"] == text

    def test_dispatch_fires_callback(self):
        """Full dispatch: JSON parse → _dispatch_event → callback."""
        received = []
        panel = ChatPanel(on_text_input=lambda t: received.append(t))

        line = json.dumps({"event": "text_input", "text": "test input"})
        event = json.loads(line)
        panel._dispatch_event(event)

        assert received == ["test input"]

    def test_append_message_with_icon(self):
        """append_message includes icon field when provided."""
        panel = ChatPanel()
        panel._proc = MagicMock()
        panel._proc.poll.return_value = None
        panel._proc.stdin = MagicMock()

        panel.append_message("user", "hello", icon="keyboard")

        # Verify the JSON sent includes icon
        written = panel._proc.stdin.write.call_args[0][0]
        data = json.loads(written.decode("utf-8"))
        assert data["icon"] == "keyboard"
        assert data["role"] == "user"

    def test_append_message_without_icon(self):
        """append_message omits icon field when not provided."""
        panel = ChatPanel()
        panel._proc = MagicMock()
        panel._proc.poll.return_value = None
        panel._proc.stdin = MagicMock()

        panel.append_message("user", "hello")

        written = panel._proc.stdin.write.call_args[0][0]
        data = json.loads(written.decode("utf-8"))
        assert "icon" not in data
