"""AtomOra — Personal Research Intelligence System.

macOS menubar app. Load a PDF, then just talk. AtomOra listens
continuously, responds, and talks back. Ambient, immersive, zero-friction.
"""

import os
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
        self._processing = False  # True while STT → LLM → TTS pipeline is active

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

    # ─── Actions ──────────────────────────────────────────────────────

    def on_toggle_chat(self, _=None):
        """Toggle the floating chat panel."""
        self.chat_panel.toggle()

    def on_toggle_mute(self, _=None):
        """Toggle ambient listening on/off."""
        if self.mic._running:
            self.mic.stop()
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
        # Stop listening while loading
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

            title = self.paper["title"]
            pages = self.paper["num_pages"]
            self.menu_paper.title = f"📄 {title[:40]}{'...' if len(title) > 40 else ''}"
            self._notify("Paper loaded", f"{title} ({pages} pages)")
            self._set_status("🧠 Reading paper...")
            print(f"[AtomOra] Paper loaded: {title} ({pages} pages)")
            self.chat_panel.clear()
            self.chat_panel.append_message("system", f"📄 Paper loaded: {title} ({pages} pages)")
            self.chat_panel.show()

            # Pre-read paper, then start ambient listening
            thread = threading.Thread(target=self._preread_then_listen, daemon=True)
            thread.start()

        except Exception as e:
            self._notify("Error loading PDF", str(e)[:100])
            self._set_status("Idle")

    def _preread_then_listen(self):
        """Pre-read the paper, speak observation, then start ambient listening."""
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

            # Speak the initial observation
            self._set_status("🗣️ Speaking...")
            self.tts.speak_sync(response)

        except Exception as e:
            print(f"[AtomOra] Pre-read error: {e}")

        # Start ambient listening
        self._start_listening()

    def _start_listening(self):
        """Start ambient microphone listening."""
        self.mic.start_ambient(callback=self._on_speech_detected)
        self.menu_mute.title = "🎤 Listening"
        self._set_status("🎤 Listening...")
        self.title = "🔬🎤"
        print("[AtomOra] 🎤 Ambient listening active")

    def _on_speech_detected(self, wav_path: str):
        """Called by Microphone when a speech segment is detected.

        This runs in the microphone's background thread.
        """
        if self._processing:
            print("[AtomOra] Already processing, skipping")
            return

        self._processing = True

        try:
            # Pause mic to avoid hearing ourselves
            self.mic.pause()

            # Transcribe
            self._set_status("💭 Transcribing...")
            transcription = transcribe_wav(wav_path)
            print(f"[AtomOra] Transcription: {transcription}")

            # Clean up wav
            try:
                os.unlink(wav_path)
            except OSError:
                pass

            if not transcription or transcription.startswith("["):
                if transcription:
                    print(f"[AtomOra] STT: {transcription}")
                self._set_status("🎤 Listening...")
                return

            # Show in chat panel
            self.chat_panel.append_message("user", transcription)

            # Get LLM response
            self._set_status("🧠 Thinking...")
            print(f"[AtomOra] Sending to LLM ({self.llm.primary})...")
            try:
                response = self.llm.chat(transcription)
            except Exception as e:
                response = f"Sorry, I encountered an error: {e}"
                print(f"[AtomOra] LLM error: {e}")

            print(f"[AtomOra] LLM response: {response[:100]}...")
            self.chat_panel.append_message("assistant", response)

            # Speak response
            self._set_status("🗣️ Speaking...")
            print("[AtomOra] Speaking response...")
            self.tts.speak_sync(response)

        finally:
            self._processing = False
            # Resume listening
            self.mic.resume()
            self._set_status("🎤 Listening...")

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
