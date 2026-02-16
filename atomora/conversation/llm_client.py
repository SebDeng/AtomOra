"""LLM client supporting Gemini 2.5 Pro and Claude Opus 4.6.

Provides blocking (chat), streaming (chat_stream), and tool-aware
streaming (chat_stream_with_tools) interfaces.
"""

import base64
import json
import os
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types
import anthropic

from atomora.conversation.prompts import COLLEAGUE_SYSTEM_PROMPT, build_paper_context


# ─── Stream event types ──────────────────────────────────────────────

@dataclass
class TextDelta:
    """A chunk of text from the LLM stream."""
    text: str


@dataclass
class ToolCallRequest:
    """The LLM wants to call a tool."""
    id: str
    name: str
    arguments: dict


# ─── Client ──────────────────────────────────────────────────────────

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

    def _system_prompt(self) -> str:
        return COLLEAGUE_SYSTEM_PROMPT + self.paper_context

    def _trim_history(self):
        if len(self.history) > self.max_history * 2:
            self.history = self.history[-(self.max_history * 2):]

    # ─── Blocking API (unchanged) ─────────────────────────────────────

    def chat(self, user_message: str, use_model: str | None = None) -> str:
        """Send a message and get a complete response (blocking)."""
        model = use_model or self.primary

        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

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

    # ─── Simple Streaming API (unchanged) ─────────────────────────────

    def chat_stream(self, user_message: str, use_model: str | None = None):
        """Stream LLM response, yielding text chunks.

        Conversation history is updated automatically when the stream
        completes or is interrupted.
        """
        model = use_model or self.primary

        self.history.append({"role": "user", "content": user_message})
        self._trim_history()

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

    # ─── Tool-Aware Streaming API ─────────────────────────────────────

    def chat_stream_with_tools(
        self,
        user_message: str | None = None,
        tools: list[dict] | None = None,
        images: list[dict] | None = None,
        continuation_messages: list[dict] | None = None,
    ):
        """Stream with tool support. Yields TextDelta / ToolCallRequest.

        First call: pass user_message (added to history).
        Continuation after tool execution: user_message=None,
            continuation_messages=[assistant_turn, tool_result_turn].
        """
        # Build full message list
        messages = self._build_tool_messages(
            user_message, images, continuation_messages,
        )

        model = self.primary
        if model == "claude" and self.claude:
            yield from self._stream_claude_with_tools(messages, tools or [])
        elif model == "gemini" and self.gemini:
            yield from self._stream_gemini_with_tools(messages, tools or [])
        elif self.claude:
            yield from self._stream_claude_with_tools(messages, tools or [])
        elif self.gemini:
            yield from self._stream_gemini_with_tools(messages, tools or [])
        else:
            yield TextDelta("[Error: No LLM configured]")

    def add_user_message(self, user_message: str, images: list[dict] | None = None):
        """Add a user message to history (call before chat_stream_with_tools)."""
        if images:
            content = list(images) + [{"type": "text", "text": user_message}]
        else:
            content = user_message
        self.history.append({"role": "user", "content": content})
        self._trim_history()

    def add_assistant_text(self, text: str):
        """Add final assistant text to history after tool loop completes."""
        self.history.append({"role": "assistant", "content": text})

    def _build_tool_messages(
        self,
        user_message: str | None,
        images: list[dict] | None,
        continuation_messages: list[dict] | None,
    ) -> list[dict]:
        """Build the full message list for a tool-aware API call."""
        messages = []

        # Base: copy history
        for msg in self.history:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # First call: add user message with optional images
        if user_message is not None:
            if images:
                content = list(images) + [{"type": "text", "text": user_message}]
            else:
                content = user_message
            messages.append({"role": "user", "content": content})

        # Continuation: append tool exchange turns
        if continuation_messages:
            messages.extend(continuation_messages)

        return messages

    # ─── Claude (tool-aware) ──────────────────────────────────────────

    def _stream_claude_with_tools(self, messages: list[dict], tools: list[dict]):
        """Stream Claude response with tool support.

        Iterates over raw stream events (not text_stream) to detect tool_use blocks.
        Yields TextDelta for text chunks, ToolCallRequest when a tool call completes.
        """
        args = {
            "model": self.claude_model,
            "max_tokens": self.config.get("claude", {}).get("max_output_tokens", 4096),
            "temperature": self.config.get("claude", {}).get("temperature", 0.7),
            "system": self._system_prompt(),
            "messages": messages,
        }
        if tools:
            args["tools"] = tools

        current_tool_id = None
        current_tool_name = None
        json_buf = ""

        with self.claude.messages.stream(**args) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_id = block.id
                        current_tool_name = block.name
                        json_buf = ""

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if hasattr(delta, "text"):
                        yield TextDelta(text=delta.text)
                    elif hasattr(delta, "partial_json"):
                        json_buf += delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_id:
                        arguments = json.loads(json_buf) if json_buf else {}
                        yield ToolCallRequest(
                            id=current_tool_id,
                            name=current_tool_name,
                            arguments=arguments,
                        )
                        current_tool_id = None
                        current_tool_name = None
                        json_buf = ""

    # ─── Gemini (tool-aware) ──────────────────────────────────────────

    def _stream_gemini_with_tools(self, messages: list[dict], tools: list[dict]):
        """Stream Gemini response with tool support."""
        contents = self._messages_to_gemini_contents(messages)
        gemini_config = self.config.get("gemini", {})
        config = genai_types.GenerateContentConfig(
            system_instruction=self._system_prompt(),
            max_output_tokens=gemini_config.get("max_output_tokens", 4096),
            temperature=gemini_config.get("temperature", 0.7),
        )

        # Add tools to config
        if tools:
            gemini_tools = self._claude_tools_to_gemini(tools)
            config.tools = gemini_tools

        tool_idx = 0
        for chunk in self.gemini.models.generate_content_stream(
            model=self.gemini_model,
            contents=contents,
            config=config,
        ):
            if not chunk.candidates:
                continue
            for part in chunk.candidates[0].content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    yield ToolCallRequest(
                        id=f"gemini_tool_{tool_idx}",
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    )
                    tool_idx += 1
                elif hasattr(part, "text") and part.text:
                    yield TextDelta(text=part.text)

    def _messages_to_gemini_contents(self, messages: list[dict]) -> list:
        """Convert Claude-format messages to Gemini Content objects."""
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            parts = self._content_to_gemini_parts(msg["content"])
            if parts:
                contents.append(genai_types.Content(role=role, parts=parts))
        return contents

    def _content_to_gemini_parts(self, content) -> list:
        """Convert message content (string or list of blocks) to Gemini Parts."""
        if isinstance(content, str):
            return [genai_types.Part.from_text(text=content)]

        parts = []
        for block in content:
            block_type = block.get("type", "")

            if block_type == "text":
                parts.append(genai_types.Part.from_text(text=block["text"]))

            elif block_type == "image":
                source = block.get("source", {})
                if source.get("type") == "base64":
                    image_bytes = base64.b64decode(source["data"])
                    parts.append(genai_types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=source.get("media_type", "image/png"),
                    ))

            elif block_type == "tool_use":
                # Convert to Gemini function call
                parts.append(genai_types.Part.from_function_call(
                    name=block["name"],
                    args=block.get("input", {}),
                ))

            elif block_type == "tool_result":
                # Extract text and images from tool result
                tool_content = block.get("content", [])
                text_parts = []
                for item in (tool_content if isinstance(tool_content, list) else []):
                    if item.get("type") == "text":
                        text_parts.append(item["text"])
                    elif item.get("type") == "image":
                        source = item.get("source", {})
                        if source.get("type") == "base64":
                            image_bytes = base64.b64decode(source["data"])
                            parts.append(genai_types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=source.get("media_type", "image/png"),
                            ))

                # Function response with text summary
                parts.append(genai_types.Part.from_function_response(
                    name=block.get("_tool_name", "tool"),
                    response={"result": " ".join(text_parts) if text_parts else "Done"},
                ))

        return parts

    def _claude_tools_to_gemini(self, claude_tools: list[dict]) -> list:
        """Convert Claude tool definitions to Gemini format."""
        declarations = []
        for tool in claude_tools:
            schema = tool.get("input_schema", {})
            # Gemini doesn't accept empty properties schemas well
            params = schema if schema.get("properties") else None
            declarations.append(genai_types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=params,
            ))
        return [genai_types.Tool(function_declarations=declarations)]

    # ─── Gemini (simple, unchanged) ───────────────────────────────────

    def _build_gemini_args(self, user_message: str):
        """Build Gemini API arguments."""
        system_prompt = self._system_prompt()
        contents = []
        for msg in self.history[:-1]:
            role = "user" if msg["role"] == "user" else "model"
            content = msg["content"]
            if isinstance(content, str):
                parts = [genai_types.Part.from_text(text=content)]
            else:
                parts = self._content_to_gemini_parts(content)
            contents.append(genai_types.Content(role=role, parts=parts))
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

    # ─── Claude (simple, unchanged) ───────────────────────────────────

    def _build_claude_args(self):
        """Build Claude API arguments."""
        system_prompt = self._system_prompt()
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
