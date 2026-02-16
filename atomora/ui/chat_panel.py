"""Floating chat panel — native Swift/SwiftUI overlay with liquid glass effect.

Launches a compiled Swift binary (AtomOraPanel.bin) and communicates
via JSON lines on stdin. The Swift panel sends events back on stdout
(e.g. double-space interrupt).
"""

import json
import os
import subprocess
import threading
from typing import Callable


PANEL_BIN = os.path.join(os.path.dirname(__file__), "AtomOraPanel.bin")


class ChatPanel:
    """Bridge to the native Swift chat panel process."""

    def __init__(
        self,
        on_interrupt: Callable | None = None,
        on_screenshot: Callable | None = None,
    ):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._on_interrupt = on_interrupt
        self._on_screenshot = on_screenshot

    def _ensure_running(self):
        """Launch the Swift panel if not already running."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already running

            if not os.path.isfile(PANEL_BIN):
                print(f"[ChatPanel] Binary not found: {PANEL_BIN}")
                return

            self._proc = subprocess.Popen(
                [PANEL_BIN],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,  # inherit parent stderr — shows in terminal
            )
            print("[ChatPanel] Swift panel launched")

            # Start stdout reader thread for events from Swift
            reader = threading.Thread(target=self._read_stdout, daemon=True)
            reader.start()

    def _read_stdout(self):
        """Read JSON events from the Swift panel's stdout."""
        proc = self._proc
        if not proc or not proc.stdout:
            return

        for raw in proc.stdout:
            try:
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                event = json.loads(line)
                if event.get("event") == "interrupt":
                    print("[ChatPanel] ⌥Space interrupt from Swift panel")
                    if self._on_interrupt:
                        self._on_interrupt()
                elif event.get("event") == "screenshot":
                    print("[ChatPanel] ⌥S screenshot from Swift panel")
                    if self._on_screenshot:
                        self._on_screenshot()
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

    def _send(self, action: dict):
        """Send a JSON action to the Swift panel."""
        self._ensure_running()
        if self._proc and self._proc.stdin:
            try:
                line = json.dumps(action, ensure_ascii=False) + "\n"
                self._proc.stdin.write(line.encode("utf-8"))
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError):
                self._proc = None

    def show(self):
        """Show the panel."""
        self._send({"action": "show"})

    def hide(self):
        """Hide the panel."""
        self._send({"action": "hide"})

    def toggle(self):
        """Toggle the panel visibility."""
        self._send({"action": "show"})

    def append_message(self, role: str, text: str):
        """Add a message to the chat panel.

        Args:
            role: 'user', 'assistant', or 'system'
            text: The message text
        """
        self._send({"action": "append", "role": role, "text": text})

    def update_last_message(self, text: str):
        """Update the text of the last message (for streaming display)."""
        self._send({"action": "update_last", "text": text})

    def clear(self):
        """Clear all messages."""
        self._send({"action": "clear"})

    def close(self):
        """Terminate the panel process."""
        if self._proc:
            self._proc.terminate()
            self._proc = None
