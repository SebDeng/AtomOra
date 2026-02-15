"""AtomOra — Personal Research Intelligence System.

macOS menubar app. Press Cmd+Shift+A to load the frontmost PDF,
then Cmd+Shift+R to talk. AtomOra talks back.
"""

import os
import sys
import threading
import yaml
import rumps

from atomora.perception.window_monitor import get_frontmost_pdf_path
from atomora.perception.pdf_extractor import extract_text
from atomora.perception.microphone import Microphone
from atomora.conversation.llm_client import LLMClient
from atomora.voice.tts import TTSEngine
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
        self.is_listening = False

        # Components
        self.mic = Microphone(self.settings.get("voice", {}).get("stt", {}))
        self.llm = LLMClient(
            config=self.settings.get("llm", {}),
            secrets=self.secrets,
        )
        self.tts = TTSEngine(self.settings.get("voice", {}).get("tts", {}))
        self.chat_panel = ChatPanel()

        # Menu items
        self.menu_status = rumps.MenuItem("Status: Idle")
        self.menu_paper = rumps.MenuItem("No paper loaded")
        self.menu_load = rumps.MenuItem("Load Paper (⌘⇧A)", callback=self.on_load_paper)
        self.menu_talk = rumps.MenuItem("Talk (⌘⇧R)", callback=self.on_talk)
        primary = self.settings.get('llm', {}).get('primary', 'gemini')
        self.menu_model = rumps.MenuItem(f"Model: {primary}")
        other_model = "Gemini" if primary == "claude" else "Claude"
        self.menu_switch = rumps.MenuItem(f"Switch to {other_model}", callback=self.on_switch_model)
        self.menu_chat = rumps.MenuItem("Show Chat ✦", callback=self.on_toggle_chat)

        self.menu = [
            self.menu_status,
            self.menu_paper,
            None,  # separator
            self.menu_load,
            self.menu_talk,
            self.menu_chat,
            None,
            self.menu_model,
            self.menu_switch,
        ]

        # Register global hotkeys
        self._register_hotkeys()

        # Auto-open chat panel on launch
        self.chat_panel.show()
        self.chat_panel.append_message("system", "AtomOra ready. Load a paper to begin.")

    def _register_hotkeys(self):
        """Register global hotkeys using pyobjc."""
        try:
            from Cocoa import NSEvent, NSKeyDownMask
            from Quartz import (
                CGEventMaskBit,
                kCGEventKeyDown,
            )

            # We use a simpler approach: check key combos in a Carbon hotkey
            # For MVP, menu items + hotkey hints are sufficient.
            # Full global hotkey registration will be added in iteration.
            pass
        except ImportError:
            pass

    # ─── Actions ──────────────────────────────────────────────────────

    def on_toggle_chat(self, _=None):
        """Toggle the floating chat panel."""
        self.chat_panel.toggle()

    def on_load_paper(self, _=None):
        """Detect frontmost PDF and load its text."""
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

            title = self.paper["title"]
            pages = self.paper["num_pages"]
            self.menu_paper.title = f"📄 {title[:40]}{'...' if len(title) > 40 else ''}"
            self._notify("Paper loaded", f"{title} ({pages} pages)")
            self._set_status("🧠 Reading paper...")
            print(f"[AtomOra] Paper loaded: {title} ({pages} pages)")
            self.chat_panel.clear()
            self.chat_panel.append_message("system", f"📄 Paper loaded: {title} ({pages} pages)")
            self.chat_panel.show()

            # Background: let AI pre-read the paper
            thread = threading.Thread(target=self._preread_paper, daemon=True)
            thread.start()

        except Exception as e:
            self._notify("Error loading PDF", str(e)[:100])
            self._set_status("Idle")

    def _preread_paper(self):
        """Background: ask the LLM to read and understand the paper."""
        print("[AtomOra] 🧠 AI is pre-reading the paper...")
        try:
            prompt = self.settings.get("app", {}).get(
                "preread_prompt",
                "I just opened this paper. Skim through it and give me 2-3 sentences "
                "on the core findings and anything worth noting. Be concise."
            )
            response = self.llm.chat(prompt)
            print(f"[AtomOra] AI pre-read done: {response[:100]}...")
            self.chat_panel.append_message("assistant", response)
            self._set_status("Ready — press ⌘⇧R to talk")
            # Speak the initial observation
            self.tts.speak_sync(response)
        except Exception as e:
            print(f"[AtomOra] Pre-read error: {e}")
            self._set_status("Ready — press ⌘⇧R to talk")

    def on_talk(self, _=None):
        """Toggle voice recording (push-to-talk)."""
        if self.is_listening:
            # Second click: stop recording → process
            print("[AtomOra] ⏹ Stopping recording...")
            self.mic.stop()
            return

        if not self.paper:
            self._notify("No paper loaded", "Press ⌘⇧A first to load a paper.")
            return

        # First click: start recording
        self.is_listening = True
        self._set_status("🎤 Recording... click Talk again to stop")
        self.menu_talk.title = "⏹ Stop (⌘⇧R)"
        print("[AtomOra] 🎤 Recording started — click Talk again to stop")

        # Record in background thread, process when stopped
        thread = threading.Thread(target=self._record_and_respond, daemon=True)
        thread.start()

    def _record_and_respond(self):
        """Record audio, transcribe, get LLM response, speak."""
        # Record until user clicks Talk again
        wav_path = self.mic.record_until_stopped()
        self.is_listening = False
        self.menu_talk.title = "Talk (⌘⇧R)"

        if not wav_path:
            print("[AtomOra] No audio recorded")
            self._set_status("Ready")
            return

        print(f"[AtomOra] Audio saved: {wav_path}")

        # Transcribe
        self._set_status("💭 Transcribing...")
        transcription = transcribe_wav(wav_path)
        print(f"[AtomOra] Transcription: {transcription}")

        if not transcription or transcription.startswith("["):
            self._set_status("Ready")
            if transcription:
                self._notify("STT", transcription)
            return

        # Show user's speech in chat panel
        self.chat_panel.append_message("user", transcription)

        # Clean up temp file
        try:
            os.unlink(wav_path)
        except OSError:
            pass

        # Get LLM response
        self._set_status("🧠 Thinking...")
        print(f"[AtomOra] Sending to LLM ({self.llm.primary})...")
        try:
            response = self.llm.chat(transcription)
        except Exception as e:
            response = f"[LLM error: {e}]"
            self._notify("Error", str(e)[:100])

        print(f"[AtomOra] LLM response: {response[:100]}...")

        # Show AI response in chat panel
        self.chat_panel.append_message("assistant", response)

        # Speak response (blocking — wait for speech to finish)
        self._set_status("🗣️ Speaking...")
        print("[AtomOra] Speaking response...")
        self.tts.speak_sync(response)

        self._set_status("Ready — press ⌘⇧R to talk")

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
