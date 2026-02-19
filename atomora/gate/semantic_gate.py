"""Semantic gate — classify whether speech is directed at AtomOra.

Uses a small local LLM (Qwen3-0.6B-4bit via mlx-lm) to classify
ambient speech. Uninvolved speech (phone calls, self-talk) is silently
dropped before it reaches the main LLM.
"""

import time


GATE_SYSTEM_PROMPT = (
    "You classify whether speech is directed at an AI research colleague "
    "named AtomOra, or is just ambient speech (self-talk, phone calls, "
    "talking to others).\n"
    "The user is a physicist reading papers. Speech about the paper, "
    "asking questions, or addressing the AI = \"yes\". "
    "Everything else = \"no\".\n"
    "Reply ONLY \"yes\" or \"no\"."
)


class SemanticGate:
    """Local LLM gate that decides if speech is directed at AtomOra."""

    def __init__(self, config: dict):
        self.model_name: str = config.get("model", "mlx-community/Qwen3-0.6B-4bit")
        self.max_tokens: int = config.get("max_tokens", 3)
        self.temperature: float = config.get("temperature", 0.0)
        self.enabled: bool = config.get("enabled", True)

        # Lazy-loaded
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """Load the gate model into memory. Called once on first use."""
        try:
            import mlx_lm
            print(f"[Gate] Loading {self.model_name}...")
            t0 = time.perf_counter()
            self._model, self._tokenizer = mlx_lm.load(self.model_name)
            dt = (time.perf_counter() - t0) * 1000
            print(f"[Gate] Model loaded in {dt:.0f}ms")
        except Exception as e:
            print(f"[Gate] Failed to load model: {e}")
            print("[Gate] Disabling gate — all speech will pass through")
            self.enabled = False
            self._model = None
            self._tokenizer = None

    def is_directed(self, transcription: str) -> bool:
        """Return True if the transcription is directed at AtomOra.

        On any error, returns True (fail-open — don't block speech).
        """
        if not self.enabled:
            return True

        # Lazy load
        if self._model is None:
            self._load_model()
            if self._model is None:
                return True

        try:
            import mlx_lm

            messages = [
                {"role": "system", "content": GATE_SYSTEM_PROMPT},
                {"role": "user", "content": transcription},
            ]

            prompt = self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                enable_thinking=False,
            )

            t0 = time.perf_counter()
            response = mlx_lm.generate(
                self._model,
                self._tokenizer,
                prompt=prompt,
                max_tokens=self.max_tokens,
                temp=self.temperature,
            )
            dt = (time.perf_counter() - t0) * 1000

            directed = response.strip().lower().startswith("yes")
            print(f'[Gate] "{transcription[:60]}" -> {"yes" if directed else "no"} ({dt:.0f}ms)')
            return directed

        except Exception as e:
            print(f"[Gate] Classification error: {e}")
            return True  # fail-open

    def set_enabled(self, enabled: bool):
        """Toggle the gate. Lazy-loads the model on first enable."""
        self.enabled = enabled
        if enabled and self._model is None:
            self._load_model()
        print(f"[Gate] {'Enabled' if enabled else 'Disabled'}")
