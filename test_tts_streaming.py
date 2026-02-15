"""Test streaming TTS latency with TestSpeech.txt."""
import time
import yaml
import os

config_path = os.path.join(os.path.dirname(__file__), "atomora", "config", "settings.yaml")
with open(config_path) as f:
    settings = yaml.safe_load(f)

from atomora.voice.tts import TTSEngine, _split_sentences, _strip_for_speech

tts = TTSEngine(settings.get("voice", {}).get("tts", {}))

# Read test text
with open(os.path.join(os.path.dirname(__file__), "TestSpeech.txt")) as f:
    text = f.read().strip()

if not text:
    print("TestSpeech.txt is empty!")
    exit(1)

text = _strip_for_speech(text)
sentences = _split_sentences(text)
print(f"Total: {len(text)} chars → {len(sentences)} segments")
for i, s in enumerate(sentences):
    preview = s[:80] + "..." if len(s) > 80 else s
    print(f"  [{i}] ({len(s)} chars) {preview}")

print(f"\nSpeaking (streaming)...")
t0 = time.time()
tts.speak_sync(text)
print(f"\nTotal playback: {time.time() - t0:.1f}s")
