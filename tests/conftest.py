"""Shared test fixtures for AtomOra.

Mocks heavy native/ML/cloud dependencies so tests can import atomora.main
without requiring rumps, sounddevice, ML frameworks, etc.
"""

import sys
import types
from unittest.mock import MagicMock

# Build a proper rumps mock with a real App base class so that
# `object.__new__(AtomOraApp)` works in tests.
_rumps = types.ModuleType("rumps")

class _FakeRumpsApp:
    """Minimal stand-in for rumps.App so subclasses can be instantiated."""
    def __init__(self, *args, **kwargs):
        pass

class _FakeMenuItem:
    """Minimal stand-in for rumps.MenuItem."""
    def __init__(self, title="", callback=None):
        self.title = title
        self.state = 0
    def __setitem__(self, key, value):
        pass
    def __getitem__(self, key):
        return _FakeMenuItem()
    def values(self):
        return []

class _FakeTimer:
    """Minimal stand-in for rumps.Timer."""
    def __init__(self, callback=None, interval=None):
        pass
    def start(self):
        pass
    def stop(self):
        pass

_rumps.App = _FakeRumpsApp
_rumps.MenuItem = _FakeMenuItem
_rumps.Timer = _FakeTimer
_rumps.notification = MagicMock()

sys.modules["rumps"] = _rumps

# Mock all other heavy dependencies
_MOCKED_MODULES = [
    "sounddevice",
    "soundfile",
    "pyobjc",
    "objc",
    "AppKit",
    "Foundation",
    "Quartz",
    "CoreGraphics",
    "Cocoa",
    "fitz",
    "pymupdf",
    "google",
    "google.genai",
    "anthropic",
    "mlx",
    "mlx_lm",
    "mlx_lm.utils",
    "mlx_lm.sample_utils",
    "edge_tts",
    "silero_vad",
]

for _mod in _MOCKED_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()
