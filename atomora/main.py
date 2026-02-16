"""AtomOra — Personal Research Intelligence System.

macOS menubar app. Load a PDF, then just talk. AtomOra listens
continuously, responds, and talks back. Ambient, immersive, zero-friction.
"""

import os
import re
import threading
import time
import yaml
import rumps

from atomora.perception.window_monitor import get_frontmost_pdf_path
from atomora.perception.pdf_extractor import extract_text
from atomora.perception.microphone import Microphone
from atomora.conversation.llm_client import LLMClient
from atomora.agent.agent_loop import AgentLoop
from atomora.agent.tools import execute_tool as _execute_tool_fn, set_current_pdf
from atomora.voice.tts import TTSEngine, _strip_for_speech, SENTENCE_BOUNDARY
from atomora.stt import transcribe_wav
from atomora.ui.chat_panel import ChatPanel


# ─── Config ───────────────────────────────────────────────────────────

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")


def load_yaml(filename: str) -> dict:
    path = os.path.join(CONFIG_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return yaml.safe_load(f) or {}
    return {}


# ─── App ──────────────────────────────────────────────────────────────

class AtomOraApp(rumps.App):
    def __init__(self):
        super().__init__(
            name="AtomOra",
            title="🔬",  # Menubar icon
            quit_button="Quit AtomOra",
        )

        # Load config
        self.settings = load_yaml("settings.yaml")
        self.secrets = load_yaml("secrets.yaml")

        # State
        self.paper: dict | None = None
        self._processing = False
        self._interrupted = False  # Set by ⌥Space interrupt
        self._pending_images: list[dict] = []  # User-captured screenshots

        # Components
        self.mic = Microphone(self.settings.get("voice", {}).get("stt", {}))
        self.llm = LLMClient(
            config=self.settings.get("llm", {}),
            secrets=self.secrets,
        )
        self.tts = TTSEngine(self.settings.get("voice", {}).get("tts", {}))
        self.chat_panel = ChatPanel(
            on_interrupt=self._on_interrupt,
            on_screenshot=self._on_screenshot_requested,
        )

        # Agent (tool-use loop wrapping LLM)
        agent_config = self.settings.get("agent", {})
        self.agent = AgentLoop(
            llm=self.llm,
            max_tool_rounds=agent_config.get("max_tool_rounds", 5),
            on_tool_start=self._on_tool_start,
            on_tool_end=self._on_tool_end,
        )

        # Menu items
        self.menu_status = rumps.MenuItem("Status: Idle")
        self.menu_paper = rumps.MenuItem("No paper loaded")
        self.menu_load = rumps.MenuItem("Load Paper (⌘⇧A)", callback=self.on_load_paper)
        self.menu_mute = rumps.MenuItem("🎤 Listening", callback=self.on_toggle_mute)
        primary = self.settings.get('llm', {}).get('primary', 'gemini')
        self.menu_model = rumps.MenuItem(f"Model: {primary}")
        other_model = "Gemini" if primary == "claude" else "Claude"
        self.menu_switch = rumps.MenuItem(f"Switch to {other_model}", callback=self.on_switch_model)
        self.menu_chat = rumps.MenuItem("Show Chat ✦", callback=self.on_toggle_chat)

        self.menu = [
            self.menu_status,
            self.menu_paper,
            None,
            self.menu_load,
            self.menu_mute,
            self.menu_chat,
            None,
            self.menu_model,
            self.menu_switch,
        ]

        # Auto-open chat panel
        self.chat_panel.show()
        self.chat_panel.append_message("system", "AtomOra ready. Load a paper to begin.")

    def _on_interrupt(self):
        """Handle interrupt: stop TTS and resume listening."""
        if not self.tts.is_speaking:
            return

        print("[AtomOra] 🛑 Interrupted (⌥Space)")
        self._interrupted = True
        self.tts.stop()

    def _on_tool_start(self, tool_name: str, args: dict):
        """Show tool execution status in chat panel."""
        print(f"[AtomOra] 🔧 Tool: {tool_name}")
        self.chat_panel.append_message("system", f"📸 {tool_name}...")
        self._set_status(f"🔧 {tool_name}...")

    def _on_tool_end(self, tool_name: str, result):
        """Update chat panel after tool execution."""
        if result.is_error:
            self.chat_panel.append_message("system", f"⚠️ {tool_name} failed")
            print(f"[AtomOra] Tool {tool_name} failed")
        else:
            self.chat_panel.append_message("system", f"✓ {tool_name} done")
            print(f"[AtomOra] Tool {tool_name} completed")

    def _on_screenshot_requested(self):
        """Handle ⌥S: capture screen and attach to next voice message."""
        from atomora.agent.tools import _execute_take_screenshot
        result = _execute_take_screenshot({})
        if result.is_error:
            self.chat_panel.append_message("system", "⚠️ Screenshot failed")
            return

        # Store image blocks for next message
        self._pending_images = [
            block for block in result.content if block.get("type") == "image"
        ]
        self.chat_panel.append_message("system", "📸 Screenshot captured — will attach to your next message")
        print("[AtomOra] 📸 Screenshot captured, pending for next message")

    # ─── Actions ──────────────────────────────────────────────────────

    def on_toggle_chat(self, _=None):
        """Toggle the floating chat panel."""
        self.chat_panel.toggle()

    def on_toggle_mute(self, _=None):
        """Toggle ambient listening on/off."""
        if self.mic._running:
            self.mic.stop()
            if self.tts.is_speaking:
                self.tts.stop()
            self.menu_mute.title = "🔇 Muted"
            self._set_status("Muted")
            self.title = "🔬"
            print("[AtomOra] Microphone muted")
        else:
            if self.paper:
                self._start_listening()
            else:
                self._notify("No paper loaded", "Load a paper first.")

    def on_load_paper(self, _=None):
        """Detect frontmost PDF and load its text."""
        self.mic.stop()
        self._set_status("Loading paper...")

        pdf_path = get_frontmost_pdf_path()
        if not pdf_path:
            self._notify("No PDF detected", "Open a PDF in Acrobat/Preview and try again.")
            self._set_status("Idle")
            return

        try:
            pdf_config = self.settings.get("pdf", {})
            self.paper = extract_text(
                pdf_path,
                max_pages=pdf_config.get("max_pages", 50),
                max_chars=pdf_config.get("max_chars", 100_000),
            )
            self.llm.set_paper(self.paper)
            set_current_pdf(pdf_path)

            title = self.paper["title"]
            pages = self.paper["num_pages"]
            self.menu_paper.title = f"📄 {title[:40]}{'...' if len(title) > 40 else ''}"
            self._notify("Paper loaded", f"{title} ({pages} pages)")
            self._set_status("🧠 Reading paper...")
            print(f"[AtomOra] Paper loaded: {title} ({pages} pages)")
            self.chat_panel.clear()
            self.chat_panel.append_message("system", f"📄 Paper loaded: {title} ({pages} pages)")
            self.chat_panel.show()

            thread = threading.Thread(target=self._preread_then_listen, daemon=True)
            thread.start()

        except Exception as e:
            self._notify("Error loading PDF", str(e)[:100])
            self._set_status("Idle")

    def _preread_then_listen(self):
        """Pre-read the paper, speak observation, then start listening.

        Can be interrupted via double-space — will skip to listening.
        """
        print("[AtomOra] 🧠 AI is pre-reading the paper...")
        self._interrupted = False

        try:
            prompt = self.settings.get("app", {}).get(
                "preread_prompt",
                "I just opened this paper. Skim through it and give me 2-3 sentences "
                "on the core findings and anything worth noting. Be concise."
            )
            self._stream_and_speak(prompt)

            if self._interrupted:
                print("[AtomOra] Pre-read interrupted, skipping to listening")

        except Exception as e:
            print(f"[AtomOra] Pre-read error: {e}")

        self._interrupted = False
        self._start_listening()

    # ─── Ambient Listening ────────────────────────────────────────────

    def _start_listening(self):
        """Start ambient microphone listening."""
        self.mic.start_ambient(callback=self._on_speech_detected)
        self.menu_mute.title = "🎤 Listening"
        self._set_status("🎤 Listening...")
        self.title = "🔬🎤"
        print("[AtomOra] 🎤 Ambient listening active")

    def _on_speech_detected(self, wav_path: str):
        """Called by Microphone when a speech segment is detected.

        Returns immediately — processing runs in a separate thread so
        the mic loop stays free.
        """
        if self._processing:
            print("[AtomOra] Already processing, skipping")
            return

        self._processing = True
        thread = threading.Thread(
            target=self._process_speech, args=(wav_path,), daemon=True
        )
        thread.start()

    def _process_speech(self, wav_path: str):
        """Process speech: STT → LLM streaming → TTS.

        Mic is paused during the entire pipeline to prevent echo.
        Can be interrupted via double-space.
        """
        self._interrupted = False

        try:
            self.mic.pause()

            # ── STT ──
            self._set_status("💭 Transcribing...")
            transcription = transcribe_wav(wav_path)
            print(f"[AtomOra] Transcription: {transcription}")

            try:
                os.unlink(wav_path)
            except OSError:
                pass

            if not transcription or transcription.startswith("["):
                if transcription:
                    print(f"[AtomOra] STT: {transcription}")
                return

            self.chat_panel.append_message("user", transcription)

            # ── LLM streaming → TTS ──
            self._set_status("🧠 Thinking...")
            print(f"[AtomOra] Streaming LLM ({self.llm.primary})...")
            self._stream_and_speak(transcription)

            if self._interrupted:
                print("[AtomOra] Response interrupted")

        except Exception as e:
            print(f"[AtomOra] Processing error: {e}")

        finally:
            self._processing = False
            self._interrupted = False
            self.mic.resume()
            self._set_status("🎤 Listening...")

    # ─── Streaming Pipeline ───────────────────────────────────────────

    def _stream_and_speak(self, user_message: str) -> str:
        """Stream agent (LLM + tools) → sentence accumulator → TTS.

        The agent loop handles tool calls transparently — from here we
        just iterate over text chunks, same as before.

        Streams text to the chat panel in real-time.
        Stops early if interrupted (tts._speaking becomes False).
        Returns full response text accumulated so far.
        """
        full_text = ""
        sentence_buf = ""

        # Grab any pending user-captured screenshots
        images = self._pending_images if self._pending_images else None
        self._pending_images = []

        # Create assistant message placeholder for live updates
        self.chat_panel.append_message("assistant", "...")

        def sentence_stream():
            """Yield clean sentences as they're completed by the agent stream."""
            nonlocal full_text, sentence_buf

            try:
                for chunk in self.agent.stream(
                    user_message,
                    images=images,
                    interrupt_check=lambda: self._interrupted,
                ):
                    # Stop consuming tokens on interrupt
                    if self._interrupted or not self.tts._speaking:
                        break

                    full_text += chunk
                    sentence_buf += chunk

                    # Live-update chat panel
                    self.chat_panel.update_last_message(full_text)

                    # Extract complete sentences from buffer
                    parts = SENTENCE_BOUNDARY.split(sentence_buf)
                    if len(parts) > 1:
                        for part in parts[:-1]:
                            sentence = _strip_for_speech(part.strip())
                            if sentence:
                                yield sentence
                        sentence_buf = parts[-1]

            except Exception as e:
                print(f"[AtomOra] Agent stream error: {e}")

            # Flush remaining buffer (skip if interrupted)
            if sentence_buf.strip() and not self._interrupted:
                sentence = _strip_for_speech(sentence_buf.strip())
                if sentence:
                    yield sentence
                sentence_buf = ""

        self._set_status("🗣️ Speaking...")
        self.tts.speak_streamed_sync(sentence_stream())

        # Final update with whatever text we accumulated
        if full_text:
            if self._interrupted:
                self.chat_panel.update_last_message(full_text + "\n\n⏸ [interrupted]")
            else:
                self.chat_panel.update_last_message(full_text)

        return full_text

    # ─── Model Switching ──────────────────────────────────────────────

    def on_switch_model(self, _):
        """Toggle between Gemini and Claude."""
        if self.llm.primary == "gemini":
            self.llm.primary = "claude"
            self.menu_model.title = "Model: claude"
            self.menu_switch.title = "Switch to Gemini"
        else:
            self.llm.primary = "gemini"
            self.menu_model.title = "Model: gemini"
            self.menu_switch.title = "Switch to Claude"

    # ─── Helpers ──────────────────────────────────────────────────────

    def _set_status(self, status: str):
        """Update menubar status."""
        self.menu_status.title = f"Status: {status}"

    def _notify(self, title: str, message: str):
        """Show a macOS notification, fallback to print on failure."""
        try:
            rumps.notification(
                title=f"AtomOra — {title}",
                subtitle="",
                message=message,
                sound=False,
            )
        except Exception:
            print(f"[AtomOra] {title}: {message}")


# ─── Entry point ──────────────────────────────────────────────────────

def main():
    app = AtomOraApp()
    app.run()


if __name__ == "__main__":
    main()
