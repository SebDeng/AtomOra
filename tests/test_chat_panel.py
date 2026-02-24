"""Tests for ChatPanel text input handling."""

import json
from unittest.mock import MagicMock

from atomora.ui.chat_panel import ChatPanel


class TestChatPanelTextInput:
    """Test that ChatPanel correctly dispatches text_input events."""

    def test_on_text_input_callback_stored(self):
        """ChatPanel accepts on_text_input callback."""
        cb = MagicMock()
        panel = ChatPanel(on_text_input=cb)
        assert panel._on_text_input is cb

    def test_on_text_input_defaults_to_none(self):
        """on_text_input is None when not provided."""
        panel = ChatPanel()
        assert panel._on_text_input is None

    def test_text_input_event_dispatched(self):
        """A text_input JSON event triggers on_text_input callback."""
        cb = MagicMock()
        panel = ChatPanel(on_text_input=cb)

        panel._dispatch_event({"event": "text_input", "text": "hello world"})
        cb.assert_called_once_with("hello world")

    def test_text_input_event_empty_text_ignored(self):
        """Empty text_input events are ignored."""
        cb = MagicMock()
        panel = ChatPanel(on_text_input=cb)

        panel._dispatch_event({"event": "text_input", "text": ""})
        panel._dispatch_event({"event": "text_input", "text": "   "})
        cb.assert_not_called()

    def test_interrupt_event_still_works(self):
        """Existing interrupt events still dispatch correctly."""
        interrupt_cb = MagicMock()
        panel = ChatPanel(on_interrupt=interrupt_cb)

        panel._dispatch_event({"event": "interrupt"})
        interrupt_cb.assert_called_once()

    def test_screenshot_event_still_works(self):
        """Existing screenshot events still dispatch correctly."""
        screenshot_cb = MagicMock()
        panel = ChatPanel(on_screenshot=screenshot_cb)

        panel._dispatch_event({"event": "screenshot"})
        screenshot_cb.assert_called_once()
