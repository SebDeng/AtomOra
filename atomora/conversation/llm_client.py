"""LLM client supporting Gemini 3 Pro and Claude Opus 4.6."""

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

    def chat(self, user_message: str, use_model: str | None = None) -> str:
        """Send a message and get a response.

        Args:
            user_message: The user's transcribed speech or typed message.
            use_model: Force a specific model ("gemini" or "claude").
                       Defaults to self.primary.
        """
        model = use_model or self.primary

        # Add user message to history
        self.history.append({"role": "user", "content": user_message})

        # Trim history
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

        # Route to the appropriate model
        if model == "gemini" and self.gemini:
            response = self._chat_gemini(user_message)
        elif model == "claude" and self.claude:
            response = self._chat_claude(user_message)
        else:
            # Fallback
            if self.gemini:
                response = self._chat_gemini(user_message)
            elif self.claude:
                response = self._chat_claude(user_message)
            else:
                response = "[Error: No LLM API configured. Set API keys in config/secrets.yaml]"

        # Add assistant response to history
        self.history.append({"role": "assistant", "content": response})
        return response

    def _chat_gemini(self, user_message: str) -> str:
        """Send message via Gemini API."""
        system_prompt = COLLEAGUE_SYSTEM_PROMPT + self.paper_context

        # Build Gemini conversation history
        contents = []
        for msg in self.history[:-1]:  # Exclude current message (added above)
            role = "user" if msg["role"] == "user" else "model"
            contents.append(genai_types.Content(
                role=role,
                parts=[genai_types.Part.from_text(text=msg["content"])],
            ))
        # Add current user message
        contents.append(genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=user_message)],
        ))

        gemini_config = self.config.get("gemini", {})
        response = self.gemini.models.generate_content(
            model=self.gemini_model,
            contents=contents,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=gemini_config.get("max_output_tokens", 4096),
                temperature=gemini_config.get("temperature", 0.7),
            ),
        )
        return response.text or "[No response from Gemini]"

    def _chat_claude(self, user_message: str) -> str:
        """Send message via Claude API."""
        system_prompt = COLLEAGUE_SYSTEM_PROMPT + self.paper_context

        # Build Claude messages
        messages = []
        for msg in self.history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        claude_config = self.config.get("claude", {})
        response = self.claude.messages.create(
            model=self.claude_model,
            max_tokens=claude_config.get("max_output_tokens", 4096),
            temperature=claude_config.get("temperature", 0.7),
            system=system_prompt,
            messages=messages,
        )
        return response.content[0].text if response.content else "[No response from Claude]"
