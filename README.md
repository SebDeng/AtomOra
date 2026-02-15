# AtomOra

**Personal Research Intelligence System** — an ambient AI colleague that lives in your macOS menubar. Load a PDF, and AtomOra reads it, listens to you, and talks back. Zero-friction, immersive, voice-first.

## What It Does

1. **Load a paper** — AtomOra detects the frontmost PDF (Preview/Acrobat), extracts the text, and gives you an initial observation out loud.
2. **Ambient listening** — Always-on microphone with VAD (voice activity detection). Just start talking — no buttons, no triggers.
3. **Voice conversation** — Your speech is transcribed, sent to an LLM with the paper context, and the response is spoken back. A floating chat panel shows the text alongside.

AtomOra is not an assistant. It's a research colleague — it has opinions, asks probing questions, and tells you what you need to hear.

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  macOS Menubar (rumps)                               │
│  🔬🎤                                                │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Perception                                          │
│  ├── window_monitor.py  — Detect frontmost PDF       │
│  ├── pdf_extractor.py   — Extract text (pymupdf)     │
│  └── microphone.py      — Ambient VAD (silero-vad)   │
│                                                      │
│  STT                                                 │
│  └── stt.py             — whisper.cpp transcription   │
│                                                      │
│  Conversation                                        │
│  ├── llm_client.py      — Gemini / Claude APIs       │
│  └── prompts.py         — Colleague persona          │
│                                                      │
│  Voice                                               │
│  └── tts.py             — Streaming Edge TTS         │
│                                                      │
│  UI                                                  │
│  ├── chat_panel.py      — Python ↔ Swift bridge      │
│  └── AtomOraPanel.swift — Native floating panel      │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Voice Pipeline

```
Mic (always on) → VAD speech detect → Record until silence
→ whisper.cpp STT → LLM (Claude/Gemini) → Streaming Edge TTS → Speaker
```

The TTS uses sentence-level streaming to minimize latency — first word out in **~0.5s**, with segments pre-generated during playback. See [docs/tts-streaming.md](docs/tts-streaming.md) for architecture details and benchmarks.

## Setup

### Prerequisites

- macOS 14+
- Python 3.11+
- [whisper.cpp](https://github.com/ggerganov/whisper.cpp) (`brew install whisper-cpp`)

### Install

```bash
git clone https://github.com/SebDeng/AtomOra.git
cd AtomOra
pip install -r requirements.txt
```

Download the whisper model:
```bash
mkdir -p ~/.cache/whisper
curl -L -o ~/.cache/whisper/ggml-base.bin \
  https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin
```

### API Keys

Create `atomora/config/secrets.yaml`:

```yaml
gemini:
  api_key: YOUR_GEMINI_API_KEY

anthropic:
  api_key: YOUR_ANTHROPIC_API_KEY
```

### Run

```bash
python -m atomora.main
```

A 🔬 icon appears in the menubar. Open a PDF in Preview or Acrobat, then click **Load Paper** — AtomOra reads the paper, speaks its first observation, and starts listening.

## Configuration

All settings in [`atomora/config/settings.yaml`](atomora/config/settings.yaml):

| Setting | Default | Description |
|---------|---------|-------------|
| `llm.primary` | `claude` | Active LLM (`claude` or `gemini`) |
| `llm.claude.model` | `claude-opus-4-6` | Claude model ID |
| `llm.gemini.model` | `gemini-2.5-pro` | Gemini model ID |
| `voice.tts.engine` | `edge` | TTS engine (`edge` or `macos_say`) |
| `voice.stt.silence_duration` | `1.0` | Seconds of silence to end recording |
| `voice.stt.min_speech_duration` | `0.8` | Minimum speech to process (skip noise) |
| `pdf.max_pages` | `50` | Skip PDFs longer than this |

## Menubar Controls

| Menu Item | Action |
|-----------|--------|
| 🎤 Listening / 🔇 Muted | Toggle ambient microphone |
| Load Paper (⌘⇧A) | Detect and load frontmost PDF |
| Show Chat | Toggle floating conversation panel |
| Switch to Gemini/Claude | Swap active LLM |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Menubar app | [rumps](https://github.com/jaredks/rumps) |
| PDF extraction | [pymupdf](https://pymupdf.readthedocs.io/) |
| Window detection | PyObjC (NSWorkspace, Quartz) |
| VAD | [silero-vad](https://github.com/snakers4/silero-vad) |
| STT | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) |
| LLM | Claude Opus 4.6 / Gemini 2.5 Pro |
| TTS | [Edge TTS](https://github.com/rany2/edge-tts) (streaming) |
| Chat panel | SwiftUI (NSPanel, dark ultra-thin material) |

## Docs

- [TTS Streaming Architecture](docs/tts-streaming.md) — sentence-level streaming pipeline, benchmarks, configuration

## License

Private — not yet open source.
