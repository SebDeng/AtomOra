"""Tool definitions and executors for AtomOra's agentic loop.

Tools are defined once in Claude's format and converted to Gemini format at runtime.
Each tool has a schema (for the LLM) and an execute function (for the runtime).
"""

import base64
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

from atomora.perception.window_monitor import get_frontmost_window_id


# ── Result type ──────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Result of a tool execution, ready to be sent back to the LLM."""
    content: list[dict] = field(default_factory=list)
    is_error: bool = False


# ── Tool definitions (Claude format) ────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "take_screenshot",
        "description": (
            "Capture a screenshot of the frontmost window (usually the PDF "
            "the user is reading). Use this when the user refers to something "
            "visual — a figure, chart, equation, or anything on screen. "
            "Don't ask the user to describe what they see; just look."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "extract_pdf_figure",
        "description": (
            "Extract a specific figure from the currently loaded PDF paper. "
            "Returns a precisely cropped image of the figure plus its caption text. "
            "Use this when the user mentions a specific figure number (e.g. "
            "'Figure 3', '图2', 'Fig. 1'). Prefer this over take_screenshot "
            "when discussing a specific numbered figure in the loaded paper — "
            "it gives a cleaner, more focused image."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "figure_number": {
                    "type": "integer",
                    "description": "The figure number to extract (e.g. 3 for 'Figure 3')",
                },
            },
            "required": ["figure_number"],
        },
    },
]


# ── Format converters ───────────────────────────────────────────────

def to_claude_tools() -> list[dict]:
    """Return tool definitions in Claude API format."""
    return TOOL_DEFINITIONS


def to_gemini_tools():
    """Convert tool definitions to Gemini API format."""
    from google.genai import types as genai_types

    declarations = []
    for tool in TOOL_DEFINITIONS:
        declarations.append(genai_types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=tool["input_schema"] or None,
        ))
    return [genai_types.Tool(function_declarations=declarations)]


# ── Dispatcher ──────────────────────────────────────────────────────

_EXECUTORS = {}  # populated below


def execute_tool(name: str, arguments: dict) -> ToolResult:
    """Execute a tool by name and return its result."""
    executor = _EXECUTORS.get(name)
    if not executor:
        return ToolResult(
            content=[{"type": "text", "text": f"Unknown tool: {name}"}],
            is_error=True,
        )
    try:
        return executor(arguments)
    except Exception as e:
        return ToolResult(
            content=[{"type": "text", "text": f"Tool error: {e}"}],
            is_error=True,
        )


# ── take_screenshot ─────────────────────────────────────────────────

MAX_SCREENSHOT_WIDTH = 1920  # resize to control API cost


def _execute_take_screenshot(args: dict) -> ToolResult:
    """Capture the frontmost window and return base64 PNG."""
    window_id = get_frontmost_window_id()
    if not window_id:
        return ToolResult(
            content=[{"type": "text", "text": "No window found to capture."}],
            is_error=True,
        )

    tmp_path = tempfile.mktemp(suffix=".png", prefix="atomora_ss_")
    try:
        # Capture window (no sound, no shadow)
        subprocess.run(
            ["screencapture", "-l", str(window_id), "-x", "-o", tmp_path],
            timeout=5,
            check=True,
        )

        if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
            return ToolResult(
                content=[{"type": "text", "text": "Screenshot capture failed."}],
                is_error=True,
            )

        # Resize if too wide (saves API tokens)
        _resize_if_needed(tmp_path, MAX_SCREENSHOT_WIDTH)

        with open(tmp_path, "rb") as f:
            b64_data = base64.standard_b64encode(f.read()).decode("ascii")

        size_kb = len(b64_data) * 3 // 4 // 1024
        print(f"[Tools] Screenshot captured: window={window_id}, ~{size_kb}KB")

        return ToolResult(content=[
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64_data,
                },
            },
            {"type": "text", "text": f"Screenshot of frontmost window (id={window_id})."},
        ])

    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _resize_if_needed(path: str, max_width: int):
    """Resize image if wider than max_width using sips (macOS built-in)."""
    try:
        result = subprocess.run(
            ["sips", "-g", "pixelWidth", path],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "pixelWidth" in line:
                width = int(line.split(":")[-1].strip())
                if width > max_width:
                    subprocess.run(
                        ["sips", "--resampleWidth", str(max_width), path],
                        capture_output=True, timeout=10,
                    )
                    print(f"[Tools] Resized screenshot: {width} → {max_width}px")
                break
    except Exception as e:
        print(f"[Tools] Resize check failed (non-fatal): {e}")


_EXECUTORS["take_screenshot"] = _execute_take_screenshot


# ── extract_pdf_figure ─────────────────────────────────────────────

# Current PDF path — set by main.py when a paper is loaded.
_current_pdf_path: str | None = None


def set_current_pdf(path: str | None):
    """Set the current PDF path for figure extraction."""
    global _current_pdf_path
    _current_pdf_path = path


def _execute_extract_pdf_figure(args: dict) -> ToolResult:
    """Extract a specific figure from the loaded PDF."""
    from atomora.perception.figure_extractor import extract_figure_by_number

    if not _current_pdf_path:
        return ToolResult(
            content=[{"type": "text", "text": "No PDF is currently loaded."}],
            is_error=True,
        )

    fig_num = args.get("figure_number")
    if fig_num is None:
        return ToolResult(
            content=[{"type": "text", "text": "Missing figure_number argument."}],
            is_error=True,
        )

    fig = extract_figure_by_number(_current_pdf_path, fig_num)
    if not fig:
        return ToolResult(
            content=[{"type": "text", "text": f"Figure {fig_num} not found in the current paper."}],
            is_error=True,
        )

    b64_data = base64.standard_b64encode(fig.png_bytes).decode("ascii")
    size_kb = len(fig.png_bytes) // 1024

    print(f"[Tools] Extracted Fig. {fig_num} from page {fig.page + 1}, ~{size_kb}KB")

    return ToolResult(content=[
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": b64_data,
            },
        },
        {
            "type": "text",
            "text": f"Figure {fig_num} (page {fig.page + 1}). Caption: {fig.caption[:500]}",
        },
    ])


_EXECUTORS["extract_pdf_figure"] = _execute_extract_pdf_figure
