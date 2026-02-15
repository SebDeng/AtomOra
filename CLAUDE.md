# AtomOra — Personal Research Intelligence System

> An ambient AI colleague that reads papers with you, monitors the literature for you,
> remembers your research trajectory, and grows smarter over time.

## Identity

AtomOra is NOT an app, NOT an assistant, NOT a search engine. It is an **ambient AI colleague**
that shares your research context. It has opinions, expresses uncertainty, proactively comments,
references past discussions, and does not wait to be asked.

The persona is the **Donna Paulsen model**: someone who knows your entire context, has her
own judgment, and tells you what you need to hear. Bilingual Chinese-English, naturally
code-switching.

## Architecture Overview

macOS menubar daemon (Python). Three-module pipeline:

```
Perception (always running, zero API cost)
    → Gate (decides relevance)
        → Response (generates conversation)
```

All local models served via a unified inference backend (vllm-mlx or direct MLX).
Target hardware: M1 Max 64GB unified memory.

## Model Stack (February 2026)

### Local Models (~9.2 GB total, 14% of 64GB)

| Role | Model | Quant | Memory | Framework |
|------|-------|-------|--------|-----------|
| STT (Speech-to-Text) | Qwen3-ASR-0.6B | bf16 | ~1.2 GB | mlx-audio / mlx-qwen3-asr |
| TTS (English) | Kokoro 82M | bf16 | ~0.2 GB | mlx-audio |
| TTS (Chinese) | Qwen3-TTS 0.6B | bf16 | ~1.2 GB | mlx-audio |
| VLM (Vision) | Qwen3-VL-8B-Thinking | 4-bit | ~6 GB | mlx-vlm |
| Embedding | GTE-multilingual-base | fp16 | ~0.6 GB | sentence-transformers |

### Cloud LLM APIs

| Role | Model | Pricing ($/M in/out) | Context | Use Case |
|------|-------|---------------------|---------|----------|
| Primary LLM | Gemini 3 Pro | $2.00 / $12.00 | 1M tokens | Daily paper discussion, briefing, figure analysis |
| Deep Reasoning | Claude Opus 4.6 | $5.00 / $25.00 | 200K (1M beta) | Complex derivations, agent tasks, knowledge extraction |

**Routing logic**: Default to Gemini 3 Pro for cost efficiency and native multimodal.
Escalate to Claude Opus 4.6 for deep physics reasoning, long-chain derivations,
and knowledge graph extraction.

### Model Selection Rationale

- **Qwen3-ASR-0.6B** over Whisper V3 Turbo: Native streaming (not chunked hack), better
  Chinese accuracy (AISHELL-2: 3.15% vs 5.06%), 22 Chinese dialect support for robust
  code-switching.
- **Qwen3-VL-8B-Thinking** over Qwen2.5-VL-7B: +13 MMMU, +12 MathVista, +7 ChartQA
  at same memory. Chain-of-thought reasoning for complex scientific figures.
- **GTE-multilingual-base** over MiniLM-L6-v2: MiniLM has no real Chinese support and
  256-token limit. GTE is Alibaba-built (Chinese first-class), 8192 tokens, 768-dim.
- **Gemini 3 Pro**: GPQA Diamond 91.9%, native multimodal (no separate vision pipeline),
  1M context, context caching saves 75% on repeated paper discussions.
- **Claude Opus 4.6**: Adaptive Thinking for extended reasoning chains, 128K output,
  best-in-class coding/agent performance (SWE-Bench 80.8%).

## Phase 1: Talking Sidebar (MVP)

Build time target: one weekend (~12 hours).

**Deliverable**: A menubar icon. Open a PDF in any reader, press Cmd+Shift+A to load paper
context. Then talk. AtomOra talks back. Phase 1 uses hotkey trigger (ambient listening = Phase 2).

### Milestone Breakdown

1. **Menubar app skeleton** (~2h): rumps menubar daemon, status icon, global hotkey (Cmd+Shift+A).
2. **PDF loader** (~2h): Detect frontmost PDF via pyobjc NSWorkspace, extract text with pymupdf.
3. **Voice input** (~3h): Qwen3-ASR-0.6B via mlx-audio, silero-vad for voice activity detection.
   Hotkey triggers recording, silence ends recording, transcription returned.
4. **LLM integration** (~2h): Gemini 3 Pro (primary) + Claude Opus 4.6 (fallback) with
   colleague-persona system prompt. Paper text as context, transcription as user message.
5. **Voice output** (~1h): Day 1: macOS `say` (zero-setup). Day 2-3: Kokoro via mlx-audio.
6. **Conversation loop** (~2h): Wire all components. Maintain conversation history.

### Success Metric

Use AtomOra for a full paper-reading session without annoyance. Instant startup,
zero-friction interaction, silence as default.

## Project Structure

```
atomora/
├── main.py                    # Entry point, menubar app (rumps)
├── perception/
│   ├── microphone.py          # STT via Qwen3-ASR (mlx-audio)
│   ├── window_monitor.py      # Active window/PDF detection (pyobjc)
│   ├── pdf_extractor.py       # Text extraction (pymupdf)
│   └── screenshot.py          # Event-driven screen capture (Phase 3)
├── gate/
│   ├── relevance.py           # Semantic similarity (GTE embedding)
│   ├── address_detect.py      # Is user talking to me? (Phase 2)
│   └── attention.py           # Focus state estimation (Phase 2)
├── conversation/
│   ├── llm_client.py          # Gemini + Claude API clients
│   ├── prompts.py             # System prompts (colleague persona)
│   └── context.py             # Context window management
├── voice/
│   ├── tts.py                 # TTS output (Kokoro + Qwen3-TTS)
│   └── notification.py        # macOS notification bubbles
├── briefing/                  # Phase 1.5
│   ├── harvester.py
│   ├── sources/
│   │   ├── arxiv.py
│   │   ├── springer.py
│   │   ├── crossref.py
│   │   └── openalex.py
│   ├── filter.py
│   ├── contextualizer.py
│   ├── delivery/
│   │   ├── slack.py
│   │   └── pushover.py
│   ├── profile.py
│   └── scheduler.py
├── memory/                    # Phase 4
│   ├── extractor.py
│   ├── graph.py
│   └── vectorstore.py
├── config/
│   ├── settings.yaml          # General settings
│   ├── profile.yaml           # Research profile (anchor papers)
│   └── secrets.yaml           # API keys (gitignored)
├── data/
│   ├── embeddings/
│   ├── history.json
│   └── graph/
├── tests/
├── CLAUDE.md                  # This file
└── requirements.txt
```

## Tech Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Language | Python 3.11+ | ML + audio + macOS ecosystem |
| Menubar | rumps | macOS menubar daemon |
| macOS APIs | pyobjc | NSWorkspace, global hotkeys |
| PDF extraction | pymupdf (fitz) | Fast, reliable |
| STT | Qwen3-ASR-0.6B (mlx-audio) | Local, streaming |
| VAD | silero-vad | Lightweight voice activity detection |
| TTS (EN) | Kokoro 82M (mlx-audio) | Local, ultra-fast |
| TTS (CN) | Qwen3-TTS 0.6B (mlx-audio) | Local, emotion control |
| VLM | Qwen3-VL-8B-Thinking (mlx-vlm) | Local, 4-bit quantized |
| Embeddings | GTE-multilingual-base | Local, Chinese+English |
| LLM (primary) | Gemini 3 Pro API | Daily conversation |
| LLM (deep) | Claude Opus 4.6 API | Complex reasoning |
| Knowledge graph | NetworkX + ChromaDB | Phase 4 |

## Three-Tier Cost Model

- **Tier 0 (free, continuous)**: All local inference — STT, TTS, VLM, embeddings,
  PDF extraction, window monitoring.
- **Tier 1 (cheap, on user action)**: Text to Gemini 3 Pro — paper context,
  conversation turns. Fractions of a cent per event.
- **Tier 2 (expensive, explicit)**: Claude Opus 4.6 for deep reasoning,
  or Gemini 3 Pro vision for complex figures.

Estimated: ~$0.02-0.08 per 1-hour reading session (Gemini 3 Pro).

## Chinese-English Bilingual Handling

The user naturally code-switches. Read English papers, discuss in Chinese,
mix English terminology into Chinese commentary.

- **STT**: Qwen3-ASR handles code-switching natively. 22 Chinese dialect support.
- **TTS**: Language detection on LLM response determines routing —
  Chinese → Qwen3-TTS, English → Kokoro. Both loaded simultaneously.
- **LLM prompt**: System prompt instructs bilingual responses matching user's language mix.
- **Embeddings**: GTE-multilingual-base handles both languages natively.

## Colleague Persona Guidelines

AtomOra is NOT a helpful assistant. It is a research colleague.

- Has opinions. Expresses uncertainty. Proactively comments.
- References past discussions (when knowledge graph is available).
- Does NOT say "How can I help you?" — instead says things like
  "这个proof的第三步seems rushed—你能看出来他们怎么从equation 7到8的吗?"
- Bilingual: matches the user's language mix naturally.
- Knows when to be silent (Phase 2+ attention state model).
- Domain: deep understanding of atomic-scale physics, photonics,
  materials science (hBN, SPE, cathodoluminescence, STEM, etc.).

## Development Notes

- Build skeleton manually (env config, aesthetic decisions, core interaction loop).
- Hand off mechanical implementation to automated loops overnight.
- Review PRs in the morning.
- Use interactive Claude Code during the day for persona tuning and interaction refinement.

## Conventions

- Python 3.11+, type hints, async where beneficial.
- Config via YAML files in `config/`.
- Secrets in `config/secrets.yaml` (gitignored).
- Tests in `tests/` with pytest.
- Prefer composition over inheritance.
- Keep modules loosely coupled — perception, gate, conversation, voice are independent.
