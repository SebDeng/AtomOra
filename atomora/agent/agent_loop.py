"""Agentic tool-use loop for AtomOra.

Sits between main.py and llm_client.py. Handles the LLM → tool call →
execute → feed result → LLM loop transparently. Callers iterate over
text chunks, same as before.
"""

from typing import Callable, Iterator

from atomora.agent.tools import ToolResult, execute_tool, to_claude_tools
from atomora.conversation.llm_client import LLMClient, TextDelta, ToolCallRequest


class AgentLoop:
    """Orchestrates LLM streaming with transparent tool execution.

    Yields only text chunks to the caller. Tool calls are handled
    internally — execute tool, feed result back to LLM, continue.
    """

    def __init__(
        self,
        llm: LLMClient,
        max_tool_rounds: int = 5,
        on_tool_start: Callable[[str, dict], None] | None = None,
        on_tool_end: Callable[[str, ToolResult], None] | None = None,
    ):
        self.llm = llm
        self.max_tool_rounds = max_tool_rounds
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end

    def stream(
        self,
        user_message: str,
        images: list[dict] | None = None,
        interrupt_check: Callable[[], bool] | None = None,
    ) -> Iterator[str]:
        """Stream a response, handling tool calls transparently.

        Args:
            user_message: The user's text message.
            images: Optional image content blocks to attach to the message.
            interrupt_check: Returns True if the user interrupted.

        Yields:
            Text chunks (same interface as LLMClient.chat_stream).
        """
        tools = to_claude_tools()
        accumulated_text = []

        # Add user message (with images) to history once.
        # All rounds read from history — no need to pass user_message again.
        self.llm.add_user_message(user_message, images)

        # Track tool exchange messages for continuation calls
        continuation_messages: list[dict] = []

        for round_num in range(self.max_tool_rounds):
            if interrupt_check and interrupt_check():
                break

            # Collect events from this streaming round
            pending_tool_calls: list[ToolCallRequest] = []
            round_text_parts: list[str] = []

            # user_message=None — it's already in history.
            # continuation_messages grows with each tool exchange round.
            event_stream = self.llm.chat_stream_with_tools(
                user_message=None,
                tools=tools,
                continuation_messages=continuation_messages if continuation_messages else None,
            )

            for event in event_stream:
                if interrupt_check and interrupt_check():
                    break

                if isinstance(event, TextDelta):
                    accumulated_text.append(event.text)
                    round_text_parts.append(event.text)
                    yield event.text

                elif isinstance(event, ToolCallRequest):
                    pending_tool_calls.append(event)

            # No tool calls — we're done
            if not pending_tool_calls:
                break

            # Execute tools and build continuation messages
            assistant_content = self._build_assistant_content(
                round_text_parts, pending_tool_calls,
            )
            tool_results_content = self._execute_and_build_results(
                pending_tool_calls, interrupt_check,
            )

            continuation_messages.append({
                "role": "assistant",
                "content": assistant_content,
            })
            continuation_messages.append({
                "role": "user",
                "content": tool_results_content,
            })

        # Commit final assistant text to history
        full_text = "".join(accumulated_text)
        self.llm.add_assistant_text(full_text or "[No response]")

    def _build_assistant_content(
        self,
        text_parts: list[str],
        tool_calls: list[ToolCallRequest],
    ) -> list[dict]:
        """Build the assistant content blocks (text + tool_use) for history."""
        content = []
        text = "".join(text_parts).strip()
        if text:
            content.append({"type": "text", "text": text})
        for tc in tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return content

    def _execute_and_build_results(
        self,
        tool_calls: list[ToolCallRequest],
        interrupt_check: Callable[[], bool] | None,
    ) -> list[dict]:
        """Execute all pending tool calls and build tool_result content blocks."""
        results = []
        for tc in tool_calls:
            if interrupt_check and interrupt_check():
                results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,

                    "content": [{"type": "text", "text": "Interrupted by user."}],
                    "is_error": True,
                })
                continue

            if self.on_tool_start:
                self.on_tool_start(tc.name, tc.arguments)

            result = execute_tool(tc.name, tc.arguments)

            if self.on_tool_end:
                self.on_tool_end(tc.name, result)

            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result.content,
                "is_error": result.is_error,
            })

        return results
