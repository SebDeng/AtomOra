"""LLM client supporting Gemini 2.5 Pro and Claude Opus 4.6.

Provides both blocking (chat) and streaming (chat_stream) interfaces.
"""

import os
from google import genai
from google.genai import types as genai_types
import anthropic

from atomora.conversation.prompts import COLLEAGUE_SYSTEM_PROMPT, build_paper_context


class LLMClient:
    """Unified client for Gemini and Claude APIs."""

    def __init__(self, config: dict, secrets: dict):
        self.config = config
        self.primary = config.get("primary", "gemini")

        # Init Gemini
        gemini_key = secrets.get("gemini", {}).get("api_key", "") or os.environ.get("GEMINI_API_KEY", "")
        if gemini_key:
            self.gemini = genai.Client(api_key=gemini_key)
            self.gemini_model = config.get("gemini", {}).get("model", "gemini-2.5-pro")
        else:
            self.gemini = None

        # Init Claude
        claude_key = secrets.get("anthropic", {}).get("api_key", "") or os.environ.get("ANTHROPIC_API_KEY", "")
        if claude_key:
            self.claude = anthropic.Anthropic(api_key=claude_key)
            self.claude_model = config.get("claude", {}).get("model", "claude-opus-4-6")
        else:
            self.claude = None

        # Conversation state
        self.paper_context: str = ""
        self.history: list[dict] = []
        self.max_history = 20

    def set_paper(self, paper: dict):
        """Set the current paper context."""
        self.paper_context = build_paper_context(paper)
        self.history.clear()

    # ─── Blocking API ─────────────────────────────────────────────────

    def chat(self, user_message: str, use_model: str | None = None) -> str:
        """Send a message and get a complete response (blocking)."""
        model = use_model or self.primary

        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

        if model == "gemini" and self.gemini:
            response = self._chat_gemini(user_message)
        elif model == "claude" and self.claude:
            response = self._chat_claude(user_message)
        else:
            if self.gemini:
                response = self._chat_gemini(user_message)
            elif self.claude:
                response = self._chat_claude(user_message)
            else:
                response = "[Error: No LLM API configured. Set API keys in config/secrets.yaml]"

        self.history.append({"role": "assistant", "content": response})
        return response

    # ─── Streaming API ────────────────────────────────────────────────

    def chat_stream(self, user_message: str, use_model: str | None = None):
        """Stream LLM response, yielding text chunks.

        Conversation history is updated automatically when the stream
        completes or is interrupted.
        """
        model = use_model or self.primary

        self.history.append({"role": "user", "content": user_message})
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

        accumulated = []
        try:
            if model == "gemini" and self.gemini:
                gen = self._stream_gemini(user_message)
            elif model == "claude" and self.claude:
                gen = self._stream_claude(user_message)
            elif self.gemini:
                gen = self._stream_gemini(user_message)
            elif self.claude:
                gen = self._stream_claude(user_message)
            else:
                gen = iter(["[Error: No LLM configured]"])

            for chunk in gen:
                accumulated.append(chunk)
                yield chunk
        finally:
            full_text = "".join(accumulated) or "[No response]"
            self.history.append({"role": "assistant", "content": full_text})

    # ─── Gemini ───────────────────────────────────────────────────────

    def _build_gemini_args(self, user_message: str):
        """Build Gemini API arguments."""
        system_prompt = COLLEAGUE_SYSTEM_PROMPT + self.paper_context
        contents = []
        for msg in self.history[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append(genai_types.Content(
                role=role,
                parts=[genai_types.Part.from_text(text=msg["content"])],
            ))
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=user_message)],
        ))
        gemini_config = self.config.get("gemini", {})
        config = genai_types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=gemini_config.get("max_output_tokens", 4096),
            temperature=gemini_config.get("temperature", 0.7),
        )
        return contents, config

    def _chat_gemini(self, user_message: str) -> str:
        contents, config = self._build_gemini_args(user_message)
        response = self.gemini.models.generate_content(
            model=self.gemini_model,
            contents=contents,
            config=config,
        )
        return response.text or "[No response from Gemini]"

    def _stream_gemini(self, user_message: str):
        contents, config = self._build_gemini_args(user_message)
        for chunk in self.gemini.models.generate_content_stream(
            model=self.gemini_model,
            contents=contents,
            config=config,
        ):
            if chunk.text:
                yield chunk.text

    # ─── Claude ───────────────────────────────────────────────────────

    def _build_claude_args(self):
        """Build Claude API arguments."""
        system_prompt = COLLEAGUE_SYSTEM_PROMPT + self.paper_context
        messages = [{"role": msg["role"], "content": msg["content"]} for msg in self.history]
        claude_config = self.config.get("claude", {})
        return {
            "model": self.claude_model,
            "max_tokens": claude_config.get("max_output_tokens", 4096),
            "temperature": claude_config.get("temperature", 0.7),
            "system": system_prompt,
            "messages": messages,
        }

    def _chat_claude(self, user_message: str) -> str:
        args = self._build_claude_args()
        response = self.claude.messages.create(**args)
        return response.content[0].text if response.content else "[No response from Claude]"

    def _stream_claude(self, user_message: str):
        args = self._build_claude_args()
        with self.claude.messages.stream(**args) as stream:
            for text in stream.text_stream:
                yield text
