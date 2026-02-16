# TTS Streaming Architecture

## Overview

AtomOra uses **end-to-end streaming** from LLM tokens all the way to audio playback. The LLM streams tokens, which are accumulated into sentences, then each sentence is synthesized and played back incrementally using a producer-consumer pipeline.

## Engine

- **Primary**: Microsoft Edge TTS (`edge-tts`) — cloud-based neural TTS, free, high quality
- **Fallback**: macOS `say` command — offline, lower quality
- Auto language detection on first sentence: Chinese voice when >=20% Chinese characters

| Config | EN Voice | ZH Voice |
|--------|----------|----------|
| Edge   | `en-US-AvaMultilingualNeural` | `zh-CN-XiaoxiaoNeural` |
| macOS  | `Samantha` | `Tingting` |

## End-to-End Streaming Pipeline

```
LLM (Claude/Gemini) — streaming tokens
       │
       ▼
 ┌─────────────┐
 │ Sentence Accumulator (main.py)
 │ Tokens → split on SENTENCE_BOUNDARY regex
 │ Strip markdown for TTS, keep raw for chat panel
 └─────┬───────┘
       │ yields clean sentences
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
       │
       ▼
 Chat panel (real-time text updates via Swift stdin)
```

### Sentence Accumulator (`main.py` `_stream_and_speak`)

The sentence accumulator sits between the LLM stream and the TTS pipeline:

1. **LLM tokens arrive** via `llm.chat_stream()` generator
2. Tokens accumulate in `sentence_buf` and `full_text`
3. `SENTENCE_BOUNDARY` regex splits on `.!?` + whitespace or `。！？；`
4. Complete sentences are stripped of markdown via `_strip_for_speech()`
5. Clean sentences are yielded to the TTS producer
6. Chat panel is updated in real-time with raw `full_text` (preserving formatting)

### TTS Producer-Consumer (`tts.py` `_speak_edge_sentences`)

**Producer** (background thread): Takes sentences from the accumulator, generates audio via Edge TTS, saves to temp `.mp3`, decodes to numpy array, enqueues. Uses a single `asyncio` event loop.

**Consumer** (calling thread): Dequeues audio segments and plays them back-to-back via `sounddevice`. Blocks on each segment until playback completes, then immediately starts the next.

**Queue** (`maxsize=2`): Allows the producer to stay 1-2 segments ahead. This ensures the next segment is ready before the current one finishes playing.

## Sentence Splitting

The `_split_sentences()` function (batch mode) and `SENTENCE_BOUNDARY` regex (streaming mode) balance two goals:
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
| First segment generation | 0.57s (112 chars -> 6.9s audio) |
| Avg generation per segment | ~1.4s |
| Total playback | 156.5s |
| Inter-segment gap | **~0ms** (pre-generated) |

Key observations:
- By the time `seg[0]` finishes playing (7.73s), segments 1-3 are already generated
- Producer consistently stays ahead of consumer — no playback stalls
- Generation time varies with server load (0.38s - 2.62s per segment)

## Text Preprocessing

Before TTS, `_strip_for_speech()` removes:
- Markdown: `**bold**`, `# headers`, `- bullets`, `` `code` ``, `[links](url)`
- Code blocks: ` ```...``` `
- URLs: `https://...`
- Excessive whitespace

This is critical because the LLM system prompt requests no-markdown output for voice, but models occasionally slip.

## Interrupt (⌥Space)

When the user presses **Option+Space**:

1. Swift panel sends `{"event":"interrupt"}` via stdout to Python
2. `_on_interrupt()` sets `_interrupted = True`, calls `tts.stop()`
3. `tts.stop()` sets `_speaking = False`, calls `sounddevice.stop()`
4. **Consumer** loop breaks immediately (checks `_speaking` each iteration)
5. **Producer** checks `_speaking` after each `edge_generate()` call — skips if False
6. **Queue drain**: consumer drains remaining items so producer can exit (avoids deadlock on `queue.put(None)`)
7. **Producer thread joined** with timeout before `_speak_edge_sentences` returns
8. **Generator** checks `_interrupted` flag — stops pulling LLM tokens on next chunk
9. **Chat panel** shows accumulated text + `⏸ [interrupted]` marker

This ensures clean shutdown: no orphan threads, no wasted LLM tokens, no lingering audio generation.

## Audio Device Management

The microphone (`sd.InputStream`) and TTS playback (`sd.play()`) share the audio hardware:

- **During TTS**: Microphone is paused — `time.sleep()` instead of `stream.read()` to avoid audio contention (prevents stuttering/glitchy playback)
- **After TTS**: Microphone resumes — `overflowed` flag from `stream.read()` detects stale buffered audio and skips it
- **VAD state reset** on each new listen session and after overflow

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
  stt:
    silence_duration: 1.0            # Seconds of silence to end recording
    min_speech_duration: 0.8         # Minimum speech duration to process
```

## Files

- `atomora/voice/tts.py` — TTS engine, producer-consumer pipeline
- `atomora/main.py` — Sentence accumulator (`_stream_and_speak`), interrupt handler
- `atomora/perception/microphone.py` — Ambient VAD, audio device management
- `atomora/ui/AtomOraPanel.swift` — Carbon hotkey registration
