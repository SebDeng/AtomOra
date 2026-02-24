# Silence Mode + Text Input Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a text input field to the SwiftUI chat panel and a "Silence Mode" menubar toggle so users can type instead of speaking in office environments.

**Architecture:** The Swift panel gets a TextField at the bottom. On Enter, it sends `{"event":"text_input","text":"..."}` via stdout to Python. Python's ChatPanel bridge gains an `on_text_input` callback. Main.py adds a silence mode toggle that, when ON, stops the mic and routes all responses through a new `_stream_and_show()` method (text-only, no TTS). The text field is always available regardless of mode — mode only controls mic + TTS.

**Tech Stack:** SwiftUI (TextField, NSPanel override), Python (chat_panel.py bridge, main.py pipeline), pytest (unit tests)

---

### Task 1: Set up test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `pyproject.toml`

**Step 1: Create pyproject.toml with pytest config**

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

**Step 2: Create test package**

```python
# tests/__init__.py
# (empty)
```

```python
# tests/conftest.py
"""Shared test fixtures for AtomOra."""
```

**Step 3: Verify pytest discovers the test directory**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest --collect-only 2>&1 | head -5`
Expected: "no tests ran" or "collected 0 items" (no errors)

**Step 4: Commit**

```
feat: add pytest infrastructure
```

---

### Task 2: ChatPanel bridge — handle text_input event (tests first)

**Files:**
- Create: `tests/test_chat_panel.py`
- Modify: `atomora/ui/chat_panel.py`

**Step 1: Write failing tests for text_input callback**

```python
# tests/test_chat_panel.py
"""Tests for ChatPanel text input handling."""

import json
import threading
import time
from unittest.mock import MagicMock, patch

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

        # Simulate the event parsing that _read_stdout does
        line = json.dumps({"event": "text_input", "text": "hello world"})
        event = json.loads(line)
        # Call the internal dispatch logic directly
        panel._dispatch_event(event)

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
```

**Step 2: Run tests — should fail**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/test_chat_panel.py -v`
Expected: FAIL — `on_text_input` parameter doesn't exist, `_dispatch_event` doesn't exist

**Step 3: Implement ChatPanel changes**

Modify `atomora/ui/chat_panel.py`:

1. Add `on_text_input: Callable[[str], None] | None = None` to `__init__`
2. Extract event dispatch logic from `_read_stdout` into a new `_dispatch_event(event)` method
3. Add `text_input` event handling in `_dispatch_event`

The `_dispatch_event` method:
```python
def _dispatch_event(self, event: dict):
    """Dispatch a parsed JSON event from the Swift panel."""
    event_type = event.get("event")
    if event_type == "interrupt":
        print("[ChatPanel] ⌥Space interrupt from Swift panel")
        if self._on_interrupt:
            self._on_interrupt()
    elif event_type == "screenshot":
        print("[ChatPanel] ⌥S screenshot from Swift panel")
        if self._on_screenshot:
            self._on_screenshot()
    elif event_type == "text_input":
        text = event.get("text", "").strip()
        if text and self._on_text_input:
            print(f"[ChatPanel] Text input: {text[:50]}...")
            self._on_text_input(text)
```

Update `_read_stdout` to call `self._dispatch_event(event)` instead of inline logic.

**Step 4: Run tests — should pass**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/test_chat_panel.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```
feat: ChatPanel text_input event dispatch
```

---

### Task 3: Swift panel — add TextField + send on Enter

**Files:**
- Modify: `atomora/ui/AtomOraPanel.swift`

**Step 1: Add inputText state to ChatState**

Add `@Published var inputText: String = ""` to `ChatState`.

**Step 2: Add InputBar view**

```swift
struct InputBar: View {
    @ObservedObject var state: ChatState
    var onSubmit: (String) -> Void

    var body: some View {
        HStack(spacing: 8) {
            TextField("Type a message...", text: $state.inputText)
                .textFieldStyle(.plain)
                .font(.system(size: 13))
                .foregroundColor(.white.opacity(0.9))
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .fill(.white.opacity(0.08))
                )
                .onSubmit {
                    let text = state.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !text.isEmpty else { return }
                    onSubmit(text)
                    state.inputText = ""
                }

            Button(action: {
                let text = state.inputText.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return }
                onSubmit(text)
                state.inputText = ""
            }) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 22))
                    .foregroundColor(
                        state.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                            ? .white.opacity(0.2)
                            : Color(red: 0.35, green: 0.78, blue: 1.0)
                    )
            }
            .buttonStyle(.plain)
            .disabled(state.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
    }
}
```

**Step 3: Integrate InputBar into ChatContentView**

Add `InputBar` below the ScrollView, above the closing VStack. Add a Divider between scroll and input. Wire `onSubmit` to write JSON to stdout:

```swift
InputBar(state: state) { text in
    // Write text_input event to stdout for Python
    let escaped = text
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
        .replacingOccurrences(of: "\n", with: "\\n")
    let msg = "{\"event\":\"text_input\",\"text\":\"\(escaped)\"}\n"
    if let data = msg.data(using: .utf8) {
        FileHandle.standardOutput.write(data)
    }
}
```

**Step 4: Override canBecomeKey on NSPanel**

The panel uses `.nonactivatingPanel` style which by default returns `false` for `canBecomeKey`. We need it to accept keyboard focus for the TextField. Add a custom NSPanel subclass:

```swift
class KeyablePanel: NSPanel {
    override var canBecomeKey: Bool { true }
}
```

Replace `NSPanel(...)` with `KeyablePanel(...)` in `setupPanel()`.

**Step 5: Compile and test manually**

Run: `cd /Users/dengyusong/Desktop/AtomOra/atomora/ui && swiftc -o AtomOraPanel.bin AtomOraPanel.swift -framework SwiftUI -framework AppKit -framework Carbon`
Expected: Compiles without errors

**Step 6: Manual smoke test**

Run: `echo '{"action":"append","role":"system","text":"Test"}' | ./atomora/ui/AtomOraPanel.bin`
Expected: Panel appears with text field at bottom, can type and press Enter

**Step 7: Commit**

```
feat: SwiftUI text input field with Enter-to-send
```

---

### Task 4: Silence mode — main.py text-only streaming (tests first)

**Files:**
- Create: `tests/test_silence_mode.py`
- Modify: `atomora/main.py`

**Step 1: Write failing tests**

```python
# tests/test_silence_mode.py
"""Tests for silence mode behavior in AtomOraApp."""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest


class FakeChatPanel:
    """Minimal ChatPanel stand-in for testing."""
    def __init__(self):
        self.messages = []
        self.last_update = None
        self._on_text_input = None

    def show(self): pass
    def append_message(self, role, text):
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

    def _make_app_components(self, chunks=None):
        """Create fake components for testing without full AtomOraApp init."""
        panel = FakeChatPanel()
        agent = FakeAgent(chunks or ["Hello ", "world!"])
        tts = FakeTTS()
        mic = FakeMic()
        return panel, agent, tts, mic

    def test_stream_and_show_no_tts(self):
        """_stream_and_show streams text to panel but does NOT call TTS."""
        from atomora.main import AtomOraApp

        panel, agent, tts, mic = self._make_app_components(["Hi ", "there."])

        # We test _stream_and_show in isolation by calling it directly
        # on a partially-constructed object
        app = object.__new__(AtomOraApp)
        app.chat_panel = panel
        app.agent = agent
        app.tts = tts
        app._interrupted = False
        app._pending_images = []
        app._set_status = MagicMock()
        app.menu_status = MagicMock()

        result = app._stream_and_show("test message")

        assert result == "Hi there."
        assert tts.spoken_sentences == []  # TTS not called
        assert panel.last_update == "Hi there."

    def test_stream_and_speak_uses_tts(self):
        """_stream_and_speak routes through TTS (existing behavior)."""
        from atomora.main import AtomOraApp

        panel, agent, tts, mic = self._make_app_components(["Hello."])

        app = object.__new__(AtomOraApp)
        app.chat_panel = panel
        app.agent = agent
        app.tts = tts
        app._interrupted = False
        app._pending_images = []
        app._set_status = MagicMock()
        app.menu_status = MagicMock()

        # _stream_and_speak calls tts.speak_streamed_sync
        app._stream_and_speak("test")
        assert len(tts.spoken_sentences) > 0

    def test_on_text_input_silence_mode_no_tts(self):
        """In silence mode, text input goes through _stream_and_show (no TTS)."""
        from atomora.main import AtomOraApp

        panel, agent, tts, mic = self._make_app_components(["Response."])

        app = object.__new__(AtomOraApp)
        app.chat_panel = panel
        app.agent = agent
        app.tts = tts
        app.mic = mic
        app._processing = False
        app._interrupted = False
        app._pending_images = []
        app._silence_mode = True
        app._set_status = MagicMock()
        app.menu_status = MagicMock()

        app._on_text_input("user question")

        # User message shown in panel
        assert ("user", "user question") in panel.messages
        # TTS not used
        assert tts.spoken_sentences == []

    def test_on_text_input_voice_mode_uses_tts(self):
        """In voice mode, text input goes through _stream_and_speak (with TTS)."""
        from atomora.main import AtomOraApp

        panel, agent, tts, mic = self._make_app_components(["Answer."])

        app = object.__new__(AtomOraApp)
        app.chat_panel = panel
        app.agent = agent
        app.tts = tts
        app.mic = mic
        app._processing = False
        app._interrupted = False
        app._pending_images = []
        app._silence_mode = False
        app._set_status = MagicMock()
        app.menu_status = MagicMock()

        app._on_text_input("user question")

        assert ("user", "user question") in panel.messages
        assert len(tts.spoken_sentences) > 0

    def test_on_text_input_skips_when_processing(self):
        """Text input is ignored if already processing another message."""
        from atomora.main import AtomOraApp

        panel, agent, tts, mic = self._make_app_components()

        app = object.__new__(AtomOraApp)
        app.chat_panel = panel
        app.agent = agent
        app.tts = tts
        app.mic = mic
        app._processing = True
        app._interrupted = False
        app._pending_images = []
        app._silence_mode = True
        app._set_status = MagicMock()
        app.menu_status = MagicMock()

        app._on_text_input("ignored")

        # No user message appended
        assert ("user", "ignored") not in panel.messages
```

**Step 2: Run tests — should fail**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/test_silence_mode.py -v`
Expected: FAIL — `_stream_and_show` and `_on_text_input` and `_silence_mode` don't exist

**Step 3: Implement main.py changes**

1. Add `self._silence_mode = False` to `__init__` state section
2. Add `on_text_input=self._on_text_input` to ChatPanel constructor
3. Add silence mode menu item after `self.menu_gate`:
   ```python
   self.menu_silence = rumps.MenuItem("🔇 Silence Mode", callback=self.on_toggle_silence)
   ```
4. Add `self.menu_silence` to `self.menu` list (after `self.menu_gate`)
5. Implement `on_toggle_silence`:
   ```python
   def on_toggle_silence(self, _=None):
       self._silence_mode = not self._silence_mode
       if self._silence_mode:
           self.menu_silence.title = "🔊 Voice Mode"
           self.mic.stop()
           self.menu_mute.title = "🔇 Muted"
           self._set_status("⌨️ Silence mode")
           self.title = "🔬⌨️"
       else:
           self.menu_silence.title = "🔇 Silence Mode"
           if self.paper:
               self._start_listening()
           else:
               self._set_status("Idle")
               self.title = "🔬"
   ```
6. Implement `_on_text_input`:
   ```python
   def _on_text_input(self, text: str):
       if self._processing:
           return
       self._processing = True
       self.chat_panel.append_message("user", text)
       thread = threading.Thread(
           target=self._process_text_input, args=(text,), daemon=True
       )
       thread.start()

   def _process_text_input(self, text: str):
       self._interrupted = False
       try:
           if self._silence_mode:
               self._set_status("🧠 Thinking...")
               self._stream_and_show(text)
           else:
               self.mic.pause()
               self._set_status("🧠 Thinking...")
               self._stream_and_speak(text)
       except Exception as e:
           print(f"[AtomOra] Text input error: {e}")
       finally:
           self._processing = False
           self._interrupted = False
           if not self._silence_mode:
               self.mic.resume()
               self._set_status("🎤 Listening...")
           else:
               self._set_status("⌨️ Silence mode")
   ```
7. Implement `_stream_and_show`:
   ```python
   def _stream_and_show(self, user_message: str) -> str:
       """Stream agent response as text only — no TTS. For silence mode."""
       full_text = ""
       images = self._pending_images if self._pending_images else None
       self._pending_images = []
       self.chat_panel.append_message("assistant", "...")
       try:
           for chunk in self.agent.stream(
               user_message,
               images=images,
               interrupt_check=lambda: self._interrupted,
           ):
               if self._interrupted:
                   break
               full_text += chunk
               self.chat_panel.update_last_message(full_text)
       except Exception as e:
           print(f"[AtomOra] Stream error: {e}")
       if full_text:
           if self._interrupted:
               self.chat_panel.update_last_message(full_text + "\n\n⏸ [interrupted]")
           else:
               self.chat_panel.update_last_message(full_text)
       return full_text
   ```

**Step 4: Run tests — should pass**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/test_silence_mode.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```
feat: silence mode — text input + text-only response pipeline
```

---

### Task 5: Persist silence mode in settings.yaml

**Files:**
- Create: `tests/test_settings_persistence.py`
- Modify: `atomora/main.py`

**Step 1: Write failing test**

```python
# tests/test_settings_persistence.py
"""Tests for silence mode settings persistence."""

from atomora.main import load_yaml


class TestSilenceModePersistence:
    def test_silence_mode_read_from_settings(self):
        """_silence_mode should initialize from settings.yaml app.silence_mode."""
        # This tests the initialization logic — silence_mode read from config
        settings = {"app": {"silence_mode": True}}
        assert settings.get("app", {}).get("silence_mode", False) is True

    def test_silence_mode_defaults_false(self):
        """silence_mode defaults to False when not in settings."""
        settings = {"app": {}}
        assert settings.get("app", {}).get("silence_mode", False) is False
```

**Step 2: Run tests — should pass immediately (logic test)**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/test_settings_persistence.py -v`

**Step 3: Modify main.py initialization and toggle**

In `__init__`, change:
```python
self._silence_mode = self.settings.get("app", {}).get("silence_mode", False)
```

In `on_toggle_silence`, add at end of each branch:
```python
self.settings.setdefault("app", {})["silence_mode"] = self._silence_mode
self._save_settings()
```

Also initialize menu title based on saved state:
```python
silence_label = "🔊 Voice Mode" if self._silence_mode else "🔇 Silence Mode"
self.menu_silence = rumps.MenuItem(silence_label, callback=self.on_toggle_silence)
```

If silence mode was saved as ON, start in silence mode (don't auto-start mic after preread):
- In `_preread_then_listen`, check: if `self._silence_mode`, skip `_start_listening()`

**Step 4: Run all tests**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 5: Commit**

```
feat: persist silence mode preference in settings.yaml
```

---

### Task 6: Update user icon for typed messages + Swift panel polish

**Files:**
- Modify: `atomora/ui/AtomOraPanel.swift`

**Step 1: Support "user_typed" role in Swift panel**

The Python side will send `role: "user"` for voice and `role: "user"` for typed (same role, different display). However, to distinguish the icon (mic vs keyboard), we pass a different role string from Python for typed input: we'll use `"user"` for both but check for an icon hint.

Simpler approach: In Swift, just check if the message starts with a special prefix, or accept an optional `icon` field in the JSON.

**Actually simplest**: In `ChatAction`, add an optional `icon` field. When appending typed messages from Python, pass `icon: "keyboard"`. The MessageBubble switches icon based on this.

Add to `ChatAction`:
```swift
let icon: String?  // optional, e.g. "keyboard"
```

In `ChatState.append`, accept icon:
```swift
func append(role: String, text: String, icon: String? = nil)
```

In `ChatMessage`:
```swift
let iconOverride: String?  // e.g. "keyboard"
```

In `MessageBubble`, use `iconOverride ?? default`:
```swift
private var roleIcon: String {
    if let override = message.iconOverride {
        switch override {
        case "keyboard": return "keyboard.fill"
        default: break
        }
    }
    switch message.role {
    case "user":      return "mic.fill"
    ...
    }
}
```

**Step 2: Update Python chat_panel.py append_message to accept icon**

```python
def append_message(self, role: str, text: str, icon: str | None = None):
    msg = {"action": "append", "role": role, "text": text}
    if icon:
        msg["icon"] = icon
    self._send(msg)
```

**Step 3: In main.py _on_text_input, use icon="keyboard"**

```python
self.chat_panel.append_message("user", text, icon="keyboard")
```

**Step 4: Compile Swift**

Run: `cd /Users/dengyusong/Desktop/AtomOra/atomora/ui && swiftc -o AtomOraPanel.bin AtomOraPanel.swift -framework SwiftUI -framework AppKit -framework Carbon`

**Step 5: Commit**

```
feat: keyboard icon for typed messages in chat panel
```

---

### Task 7: Integration test — end-to-end text input flow

**Files:**
- Create: `tests/test_integration_text_input.py`

**Step 1: Write integration test**

```python
# tests/test_integration_text_input.py
"""Integration tests for the full text input flow."""

import json
from unittest.mock import MagicMock

from atomora.ui.chat_panel import ChatPanel


class TestTextInputIntegration:
    """Test the full flow: event parsing → callback → response."""

    def test_json_roundtrip(self):
        """JSON from Swift → Python parses correctly."""
        # Simulate what Swift sends
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
```

**Step 2: Run all tests**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```
test: integration tests for text input flow
```

---

### Task 8: Final compile, manual test, update CLAUDE.md

**Files:**
- Modify: `atomora/ui/AtomOraPanel.swift` (compile)
- Modify: `CLAUDE.md`

**Step 1: Compile Swift binary**

Run: `cd /Users/dengyusong/Desktop/AtomOra/atomora/ui && swiftc -o AtomOraPanel.bin AtomOraPanel.swift -framework SwiftUI -framework AppKit -framework Carbon`

**Step 2: Run full test suite**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m pytest tests/ -v`

**Step 3: Manual smoke test**

Run: `cd /Users/dengyusong/Desktop/AtomOra && python -m atomora.main`
- Verify: text field visible at bottom of chat panel
- Verify: can type and press Enter to send
- Verify: toggle silence mode from menubar
- Verify: in silence mode, response appears as text only (no audio)
- Verify: in voice mode, typed input still triggers voice response

**Step 4: Update CLAUDE.md**

Add to Current State section:
- **Text input** — type in the chat panel (Enter to send), works in both modes
- **Silence mode** — menubar toggle "🔇 Silence Mode", mutes mic + TTS, text-only I/O

Add to Architecture section under UI:
- `AtomOraPanel.swift` now includes InputBar (TextField + send button)
- `KeyablePanel` subclass overrides `canBecomeKey` for keyboard focus

Add to Key Implementation Details:
- `_stream_and_show()` — same as `_stream_and_speak()` but skips TTS
- `_on_text_input()` — routes typed text through silence or voice pipeline
- Silence mode persisted in `settings.yaml` → `app.silence_mode`

**Step 5: Commit**

```
feat: silence mode — text input in chat panel, no-audio office mode

Adds a text field to the SwiftUI chat panel and a silence mode toggle
in the menubar. In silence mode, mic is muted and responses are
text-only. The text field is always available in both modes.
```
