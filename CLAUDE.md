# AtomOra — Personal Research Intelligence System

> An ambient AI colleague that reads papers with you. Load a PDF, just talk.
> AtomOra listens continuously, responds, and talks back. Zero-friction, voice-first.

## Identity

AtomOra is NOT an assistant. It is an **ambient AI colleague** that shares your
research context. It has opinions, expresses uncertainty, proactively comments,
and tells you what you need to hear.

The persona is the **Donna Paulsen model**: someone who knows your entire context,
has her own judgment, and doesn't wait to be asked. Bilingual Chinese-English,
naturally code-switching.

## Current State (Phase 3.1 — Agentic Vision)

Phase 1 (Talking Sidebar) is complete. Phase 3.1 adds agentic tool use:

1. Load a PDF (detected from frontmost window)
2. AI pre-reads and speaks initial observations (interruptible)
3. Ambient microphone listens continuously via VAD
4. Speech → STT → **Agent Loop** (LLM + tool calls) → TTS → Speaker
5. LLM can **autonomously screenshot** the screen to analyze figures/charts
6. User can **manually capture** screenshots via **⌥S** hotkey
7. Floating chat panel shows conversation + tool execution in real-time

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  macOS Menubar (rumps)                               │
│  🔬🎤                                                │
├──────────────────────────────────────────────────────┤
│                                                      │
│  Perception                                          │
│  ├── window_monitor.py  — Detect frontmost PDF +     │
│  │                        get window ID for capture   │
│  ├── pdf_extractor.py   — Extract text (pymupdf)     │
│  └── microphone.py      — Ambient VAD (silero-vad)   │
│                                                      │
│  STT                                                 │
│  └── stt.py             — whisper.cpp transcription   │
│                                                      │
│  Agent                                               │
│  ├── agent_loop.py      — Agentic tool-use loop      │
│  └── tools.py           — Tool registry + executors   │
│                                                      │
│  Conversation                                        │
│  ├── llm_client.py      — Gemini / Claude streaming   │
│  │                        (text + tool-aware + vision) │
│  └── prompts.py         — Colleague persona + tools   │
│                                                      │
│  Voice                                               │
│  └── tts.py             — Streaming Edge TTS         │
│                                                      │
│  UI                                                  │
│  ├── chat_panel.py      — Python ↔ Swift bridge      │
│  └── AtomOraPanel.swift — Native floating panel +    │
│                           ⌥Space interrupt +         │
│                           ⌥S screenshot hotkey       │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### End-to-End Streaming Pipeline

```
Mic (always on)
  → silero-vad speech detect
    → Record until silence (1.0s)
      → whisper.cpp STT
        → Agent Loop (LLM + tool execution)
          ├── LLM streams tokens → text chunks
          └── LLM calls tool (take_screenshot)
                → screencapture → base64 PNG → back to LLM
                → LLM analyzes image → text chunks
          → Sentence accumulator (regex boundary split)
            → TTS producer-consumer (Edge TTS, queue=2)
              → Speaker (sounddevice)
                → Chat panel (real-time text via Swift stdin)
```

Key design decisions:
- **Agentic loop**: LLM can call tools (screenshot) autonomously, like Claude Code
- **Agent yields text only**: tool calls handled transparently inside the loop
- **LLM streams tokens** → accumulated into sentences → TTS processes per-sentence
- **Mic paused during TTS** (sleep, not drain) to avoid audio contention
- **Overflow detection** on mic resume to skip stale audio
- **Interrupt via ⌥Space** — Carbon RegisterEventHotKey (no Accessibility permission needed)
- **Screenshot via ⌥S** — user-initiated capture, attached to next voice message

### Interrupt Flow (⌥Space)

1. Swift panel receives Carbon hotkey event
2. Writes `{"event":"interrupt"}` to stdout
3. Python ChatPanel reads stdout, fires `_on_interrupt()` callback
4. `_on_interrupt()` sets `_interrupted = True`, calls `tts.stop()`
5. `tts.stop()` sets `_speaking = False`, calls `sd.stop()`
6. Consumer loop breaks → drains queue → joins producer thread
7. Generator checks `_interrupted` → stops pulling LLM tokens
8. Chat panel shows accumulated text + `[interrupted]` marker

## Tech Stack (Actual Implementation)

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.11+ | ML + audio + macOS ecosystem |
| Menubar | rumps | macOS menubar daemon |
| macOS APIs | pyobjc | NSWorkspace for PDF detection |
| PDF extraction | pymupdf (fitz) | Fast, reliable |
| VAD | silero-vad | Voice activity detection, 512 samples min at 16kHz |
| STT | whisper.cpp (whisper-cli) | Local, ggml-base model |
| LLM (primary) | Claude Opus 4.6 API | Streaming via anthropic SDK |
| LLM (secondary) | Gemini 2.5 Pro API | Streaming via google-genai SDK |
| TTS | Edge TTS (edge-tts) | Cloud neural TTS, sentence-level streaming |
| TTS fallback | macOS `say` | Offline |
| Chat panel | SwiftUI (NSPanel) | Dark ultra-thin material, stdin/stdout IPC |
| Global hotkey | Carbon RegisterEventHotKey | ⌥Space interrupt, no Accessibility needed |
| Audio I/O | sounddevice + soundfile | Input (mic) and output (TTS playback) |

## Project Structure

```
atomora/
├── main.py                    # Entry point, menubar app, streaming pipeline
├── perception/
│   ├── microphone.py          # Ambient VAD listening (silero-vad + sounddevice)
│   ├── window_monitor.py      # Active window/PDF detection + screenshot (pyobjc)
│   └── pdf_extractor.py       # Text extraction (pymupdf)
├── stt.py                     # whisper.cpp STT wrapper
├── agent/
│   ├── agent_loop.py          # Agentic tool-use loop (LLM → tool → LLM)
│   └── tools.py               # Tool definitions + executors (screenshot, etc.)
├── conversation/
│   ├── llm_client.py          # Gemini + Claude streaming (text + tools + vision)
│   └── prompts.py             # System prompts (colleague persona + tools)
├── voice/
│   └── tts.py                 # Streaming Edge TTS (producer-consumer pipeline)
├── ui/
│   ├── chat_panel.py          # Python ↔ Swift bridge (stdin/stdout JSON)
│   ├── AtomOraPanel.swift     # Native SwiftUI panel + ⌥Space/⌥S hotkeys
│   └── AtomOraPanel.bin       # Compiled Swift binary
├── config/
│   ├── settings.yaml          # General settings
│   └── secrets.yaml           # API keys (gitignored)
├── docs/
│   └── tts-streaming.md       # TTS architecture and benchmarks
├── CLAUDE.md                  # This file
├── README.md
└── requirements.txt
```

## Key Implementation Details

### Microphone (microphone.py)
- silero-vad requires **512 samples minimum** at 16kHz (not 480)
- Retry logic with backoff on audio device errors (PaMacCore)
- During TTS pause: **sleep** (not read) to avoid audio hardware contention
- After resume: **overflow detection** skips stale buffered audio
- VAD state reset on each new listen session

### LLM Streaming (llm_client.py)
- `chat_stream()` generator with `try/finally` for history management
- Claude: `client.messages.stream()` → `stream.text_stream`
- Gemini: `client.models.generate_content_stream()`
- Partial responses saved to history on interrupt

### TTS Streaming (tts.py)
- Producer-consumer with `Queue(maxsize=2)`
- Producer generates audio per-sentence in background thread
- Consumer plays audio via sounddevice on calling thread
- On interrupt: producer checks `_speaking` after each edge_generate, drains queue, joins thread
- Language detection on first sentence (Chinese ≥20% → Chinese voice)
- See [docs/tts-streaming.md](docs/tts-streaming.md) for benchmarks

### Chat Panel (AtomOraPanel.swift)
- Native SwiftUI NSPanel with `.ultraThinMaterial` dark glass effect
- Floating, always-on-top, joins all spaces
- Python→Swift: JSON lines on stdin (append, update_last, clear, show, hide)
- Swift→Python: JSON lines on stdout (interrupt events)
- Carbon `RegisterEventHotKey` for ⌥Space global hotkey

### Agent Loop (agent/agent_loop.py)
- **Agentic tool-use pattern** modeled after Claude Code
- Wraps LLMClient, yields only text chunks — tool calls handled transparently
- Loop: LLM streams → detect ToolCallRequest → execute tool → feed result → LLM streams again
- Max tool rounds configurable (default 5) to prevent infinite loops
- Interrupt check between each tool call and stream event
- Tools defined in `agent/tools.py` with Claude-format schemas, converted to Gemini at runtime

### Vision / Screenshot (agent/tools.py)
- `take_screenshot`: captures frontmost window via `screencapture -l <windowid>`
- Window ID from `get_frontmost_window_id()` in window_monitor.py (CGWindowListCopyWindowInfo)
- Resizes images >1920px wide via `sips` to control API cost
- Returns base64 PNG as image content block in Claude API format
- LLM decides autonomously when to screenshot (proactive tool use)
- User can also trigger via **⌥S** hotkey → image attached to next voice message

### Tool-Aware LLM Streaming (llm_client.py)
- `chat_stream_with_tools()`: iterates over raw stream events (not text_stream)
- Claude: detects `content_block_start` with `type="tool_use"`, accumulates JSON from `input_json_delta`
- Gemini: checks `part.function_call` in stream chunks
- History supports both string content and structured content blocks (tool_use, tool_result, images)
- `_messages_to_gemini_contents()`: converts Claude-format messages to Gemini Content objects

### Sentence Accumulator (main.py `_stream_and_speak`)
- LLM tokens accumulated into `sentence_buf`
- Split on `SENTENCE_BOUNDARY` regex: `(?<=[.!?])\s+|(?<=[。！？；])`
- Markdown stripped before TTS via `_strip_for_speech()`
- Chat panel updated in real-time with raw LLM text

## Conventions

- Python 3.11+, type hints where helpful
- Config via YAML files in `config/`
- Secrets in `config/secrets.yaml` (gitignored)
- Prefer composition over inheritance
- Modules are loosely coupled — perception, conversation, voice, ui are independent
- Thread safety: flags (`_speaking`, `_interrupted`, `_processing`) checked across threads via Python GIL
- Daemon threads for background work (producer, mic loop, hotkey reader)

## Colleague Persona

- Has opinions. Expresses uncertainty. Proactively comments.
- Does NOT say "How can I help you?" — comments like a colleague would
- Bilingual: matches the user's language mix naturally
- Domain: atomic-scale physics, photonics, materials science
- Voice output: concise, conversational, no markdown formatting

## Future Phases

- **Phase 2**: Ambient context awareness (attention state, address detection)
- **Phase 3.2**: Daily paper briefing (arXiv RSS → LLM filter → voice summary)
- **Phase 4**: Knowledge graph, long-term memory across sessions
