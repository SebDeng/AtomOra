"""Floating chat panel — native Swift/SwiftUI overlay with liquid glass effect.

Launches a compiled Swift binary (AtomOraPanel.bin) and communicates
via JSON lines on stdin. The Swift panel renders with .ultraThinMaterial
for a true Apple liquid glass appearance.
"""

import json
import os
import subprocess
import threading


PANEL_BIN = os.path.join(os.path.dirname(__file__), "AtomOraPanel.bin")


class ChatPanel:
    """Bridge to the native Swift chat panel process."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

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
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print("[ChatPanel] Swift panel launched")

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
        # For simplicity, just show — the Swift panel handles close via title bar
        self._send({"action": "show"})

    def append_message(self, role: str, text: str):
        """Add a message to the chat panel.

        Args:
            role: 'user', 'assistant', or 'system'
            text: The message text
        """
        self._send({"action": "append", "role": role, "text": text})

    def clear(self):
        """Clear all messages."""
        self._send({"action": "clear"})

    def close(self):
        """Terminate the panel process."""
        if self._proc:
            self._proc.terminate()
            self._proc = None
