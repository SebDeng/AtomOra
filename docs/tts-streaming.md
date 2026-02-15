# TTS Streaming Architecture

## Overview

AtomOra uses **sentence-level streaming TTS** to minimize time-to-first-word. Instead of generating audio for the entire LLM response at once, the text is split into sentences and each sentence is synthesized and played back incrementally using a producer-consumer pipeline.

## Engine

- **Primary**: Microsoft Edge TTS (`edge-tts`) — cloud-based neural TTS, free, high quality
- **Fallback**: macOS `say` command — offline, lower quality
- Auto language detection: Chinese voice when ≥20% Chinese characters, English otherwise

| Config | EN Voice | ZH Voice |
|--------|----------|----------|
| Edge   | `en-US-AvaMultilingualNeural` | `zh-CN-XiaoxiaoNeural` |
| macOS  | `Samantha` | `Tingting` |

## Streaming Pipeline

```
LLM Response (full text)
       │
       ▼
 ┌─────────────┐
 │ Strip markdown, URLs, formatting
 └─────┬───────┘
       ▼
 ┌─────────────┐
 │ Split into sentences (by .!?。！？ and —)
 └─────┬───────┘
       ▼
 ┌──────────────────────────────────────────┐
 │  Producer Thread          Consumer Thread │
 │  ┌──────────┐   Queue    ┌────────────┐  │
 │  │ Generate │──(max 2)──▶│ Play audio │  │
 │  │ seg[0]   │            │ seg[0]     │  │
 │  │ seg[1]   │            │ seg[1]     │  │
 │  │ ...      │            │ ...        │  │
 │  └──────────┘            └────────────┘  │
 └──────────────────────────────────────────┘
```

**Producer** (background thread): Generates audio for each sentence via Edge TTS, saves to temp `.mp3`, decodes to numpy array, enqueues. Uses a single `asyncio` event loop for all sentences.

**Consumer** (calling thread): Dequeues audio segments and plays them back-to-back via `sounddevice`. Blocks on each segment until playback completes, then immediately starts the next.

**Queue** (`maxsize=2`): Allows the producer to stay 1-2 segments ahead of the consumer. This ensures the next segment is ready before the current one finishes playing.

## Sentence Splitting

The `_split_sentences()` function balances two goals:
- **Fast first-word**: Keep the first segment short enough to generate quickly
- **Natural speech flow**: Don't split so aggressively that TTS sounds choppy

Split rules:
1. Primary split on sentence-ending punctuation: `.` `!` `?` `。` `！` `？` `；`
2. Secondary split on em-dash `—` or semicolon `;` for segments > 150 chars
3. Merge fragments < 60 chars with the previous segment

## Performance (Benchmark)

Tested with 2677 chars of natural academic discussion (18 segments):

| Metric | Value |
|--------|-------|
| Time to first word | **0.57s** |
| First segment generation | 0.57s (112 chars → 6.9s audio) |
| Avg generation per segment | ~1.4s |
| Total playback | 156.5s |
| Inter-segment gap | **~0ms** (pre-generated) |

Key observations:
- By the time `seg[0]` finishes playing (7.73s), segments 1-3 are already generated
- Producer consistently stays ahead of consumer — no playback stalls
- Generation time varies with server load (0.38s – 2.62s per segment)

## Text Preprocessing

Before TTS, `_strip_for_speech()` removes:
- Markdown: `**bold**`, `# headers`, `- bullets`, `` `code` ``, `[links](url)`
- Code blocks: ` ```...``` `
- URLs: `https://...`
- Excessive whitespace

This is critical because the LLM system prompt requests no-markdown output for voice, but models occasionally slip.

## Configuration

In `atomora/config/settings.yaml`:

```yaml
voice:
  tts:
    engine: edge                     # edge | macos_say
    edge:
      voice: en-US-AvaMultilingualNeural
      voice_zh: zh-CN-XiaoxiaoNeural
      rate: "+0%"                    # Speed: -50% to +100%
    macos_say:
      voice: Samantha
      voice_zh: Tingting
      rate: 200                      # words per minute
```

## Stop / Interrupt

Calling `tts.stop()` sets `_speaking = False`, which:
1. Stops the producer from generating further segments
2. Calls `sounddevice.stop()` to halt current playback immediately
3. Consumer loop exits on next iteration

## File

`atomora/voice/tts.py`
