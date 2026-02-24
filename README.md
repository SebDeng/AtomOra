# AtomOra

**Personal Research Intelligence System** — an ambient AI colleague that lives in your macOS menubar. Load a PDF, and AtomOra reads it, listens to you, and talks back. Zero-friction, immersive, voice-first.

## What It Does

### Talking Sidebar (interactive)
1. **Load a paper** — AtomOra detects the frontmost PDF (Preview/Acrobat), extracts the text, and speaks an initial observation.
2. **Ambient listening** — Always-on microphone with VAD (voice activity detection). Just start talking — no buttons, no triggers.
3. **Streaming conversation** — Your speech is transcribed, streamed to an LLM with the paper context, and spoken back sentence-by-sentence. A floating chat panel shows text in real-time.
4. **Agentic vision** — The LLM can extract specific figures from the PDF or screenshot your screen autonomously. Press **⌥S** to manually capture a screenshot.
5. **Interrupt anytime** — Press **⌥Space** (Option+Space) to stop the AI mid-sentence and take the floor.

### Daily Paper Briefing (automated)
6. **Multi-source fetching** — Pulls recent papers from arXiv, OpenAlex, and Semantic Scholar in parallel.
7. **Smart dedup** — Merges duplicates across sources (DOI → arXiv ID → title), prefers journal versions over preprints while keeping arXiv PDF links.
8. **AI filtering** — Sonnet 4.5 batch-scores all papers against your research profile (topic relevance + journal prestige) and writes one-line summaries (~$0.10-0.25/day).
9. **Delivery** — Slack (Block Kit) with local file path, Markdown archive, and macOS notification (click to open Slack).
10. **Scheduled** — Runs daily at 8:00 AM via `launchd`, including weekends.

#### Manual run

```bash
python -m atomora.briefing.run_briefing           # full run (1 day)
python -m atomora.briefing.run_briefing --days 3   # look back 3 days
python -m atomora.briefing.run_briefing --dry-run  # console preview only
python -m atomora.briefing.run_briefing -v         # verbose logging
```

#### Scheduled briefing (launchd)

The briefing runs automatically every day at 8:00 AM via macOS `launchd`. The plist is at `~/Library/LaunchAgents/com.atomora.briefing.plist`.

```bash
# Check status
launchctl list | grep atomora

# Manually trigger a run
launchctl start com.atomora.briefing

# View logs
tail -f data/briefing/launchd.log

# Stop the daily schedule
launchctl unload ~/Library/LaunchAgents/com.atomora.briefing.plist

# Restart the daily schedule
launchctl load ~/Library/LaunchAgents/com.atomora.briefing.plist

# Reload after editing the plist
launchctl unload ~/Library/LaunchAgents/com.atomora.briefing.plist && \
launchctl load ~/Library/LaunchAgents/com.atomora.briefing.plist
```

Briefing results are saved to `data/briefing/YYYY-MM-DD.md`.

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
│  ├── figure_extractor.py— Smart figure cropping      │
│  └── microphone.py      — Ambient VAD (silero-vad)   │
│                                                      │
│  STT                                                 │
│  └── stt.py             — whisper.cpp transcription   │
│                                                      │
│  Agent                                               │
│  ├── agent_loop.py      — Agentic tool-use loop      │
│  └── tools.py           — screenshot, figure extract │
│                                                      │
│  Conversation                                        │
│  ├── llm_client.py      — Gemini / Claude streaming   │
│  └── prompts.py         — Colleague persona + tools  │
│                                                      │
│  Voice                                               │
│  └── tts.py             — Streaming Edge TTS         │
│                                                      │
│  UI                                                  │
│  ├── chat_panel.py      — Python ↔ Swift bridge      │
│  └── AtomOraPanel.swift — Native floating panel +    │
│                           ⌥Space / ⌥S hotkeys       │
│                                                      │
│  Briefing                                            │
│  ├── sources/            — arXiv, OpenAlex, S2       │
│  ├── filter.py           — Dedup + Sonnet 4.5 filter │
│  ├── delivery/           — Slack, Markdown, notif    │
│  └── run_briefing.py     — Pipeline orchestrator     │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### Voice Pipeline

```
Mic (always on) → VAD speech detect → Record until silence
  → whisper.cpp STT
    → LLM streaming (Claude/Gemini tokens)
      → Sentence accumulator
        → Edge TTS (producer-consumer, queue=2)
          → Speaker
```

The entire pipeline is streaming end-to-end:
- **LLM tokens** arrive and accumulate into sentences
- **TTS generates audio** per-sentence in a background thread while the current sentence plays
- **Chat panel** updates in real-time as tokens arrive
- First word out in **~0.5s** after TTS starts, with zero inter-sentence gaps

See [docs/tts-streaming.md](docs/tts-streaming.md) for architecture details and benchmarks.

### Interrupt (⌥Space)

Press **Option+Space** anywhere to interrupt the AI mid-speech:
- TTS stops immediately
- LLM stops generating tokens
- Producer thread cleans up (drains queue, joins)
- Chat panel shows accumulated text with `[interrupted]` marker
- Microphone resumes listening

The hotkey uses Carbon `RegisterEventHotKey` — works system-wide without Accessibility permission.

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

### Compile the Chat Panel (if needed)

The Swift panel binary is pre-compiled, but if you need to rebuild:
```bash
swiftc -o atomora/ui/AtomOraPanel.bin atomora/ui/AtomOraPanel.swift \
  -framework SwiftUI -framework AppKit -framework Carbon
```

### API Keys

Create `atomora/config/secrets.yaml`:

```yaml
gemini:
  api_key: YOUR_GEMINI_API_KEY

anthropic:
  api_key: YOUR_ANTHROPIC_API_KEY

# Optional — for daily briefing
openalex:
  email: "your@email.com"         # For polite pool (faster rate limits)
slack:
  webhook_url: ""                  # Slack incoming webhook URL
semanticscholar:
  api_key: ""                      # Optional, increases rate limits
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
| `briefing.relevance_threshold` | `0.6` | Minimum score for paper inclusion |
| `briefing.max_papers` | `20` | Max papers per briefing |
| `briefing.arxiv_categories` | `[cond-mat.mtrl-sci, ...]` | arXiv categories to monitor |
| `briefing.s2_queries` | `["hexagonal boron nitride", ...]` | Semantic Scholar search terms |

## Controls

| Control | Action |
|---------|--------|
| **⌥Space** | Interrupt AI speech (global, works from any app) |
| **⌥S** | Capture screenshot and attach to next message |
| 🎤 Listening / 🔇 Muted | Toggle ambient microphone |
| 🎤 Microphone ▸ | Select input device |
| 🔊 Speaker ▸ | Select output device |
| Load Paper (⌘⇧A) | Detect and load frontmost PDF |
| Show Chat | Toggle floating conversation panel |
| Switch to Gemini/Claude | Swap active LLM |

## Tech Stack

| Component | Technology |
|-----------|------------|
| Menubar app | [rumps](https://github.com/jaredks/rumps) |
| PDF extraction | [pymupdf](https://pymupdf.readthedocs.io/) |
| Window detection | PyObjC (NSWorkspace) |
| VAD | [silero-vad](https://github.com/snakers4/silero-vad) |
| STT | [whisper.cpp](https://github.com/ggerganov/whisper.cpp) |
| LLM (interactive) | Claude Opus 4.6 / Gemini 2.5 Pro (streaming) |
| LLM (briefing filter) | Claude Sonnet 4.5 (batch scoring) |
| TTS | [Edge TTS](https://github.com/rany2/edge-tts) (sentence-level streaming) |
| Paper sources | [arxiv](https://pypi.org/project/arxiv/), [pyalex](https://pypi.org/project/pyalex/), [semanticscholar](https://pypi.org/project/semanticscholar/) |
| Slack delivery | requests (incoming webhook, Block Kit) |
| Chat panel | SwiftUI (NSPanel, dark ultra-thin material) |
| Global hotkey | Carbon RegisterEventHotKey |
| Audio I/O | [sounddevice](https://python-sounddevice.readthedocs.io/) |

## Docs

- [TTS Streaming Architecture](docs/tts-streaming.md) — sentence-level streaming pipeline, benchmarks, configuration

## License

Private — not yet open source.
