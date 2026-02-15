"""Detect the frontmost application and active PDF file on macOS."""

import subprocess
from AppKit import NSWorkspace
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGNullWindowID,
    kCGWindowListOptionOnScreenOnly,
)


def get_frontmost_app() -> dict:
    """Return info about the frontmost application."""
    ws = NSWorkspace.sharedWorkspace()
    app = ws.frontmostApplication()
    return {
        "name": app.localizedName(),
        "bundle_id": app.bundleIdentifier(),
        "pid": app.processIdentifier(),
    }


def get_frontmost_pdf_path() -> str | None:
    """Try to detect the PDF file path open in the frontmost application.

    Supports: Adobe Acrobat, Preview, Chrome (limited), other PDF viewers.
    Returns the file path or None if no PDF detected.
    """
    app = get_frontmost_app()
    bundle_id = app.get("bundle_id", "")

    # Strategy 1: AppleScript to get the document path from known apps
    if bundle_id in (
        "com.adobe.Acrobat.Pro",
        "com.adobe.Acrobat",
        "com.adobe.Reader",
    ):
        return _get_acrobat_pdf_path()
    elif bundle_id == "com.apple.Preview":
        return _get_preview_pdf_path()

    # Strategy 2: Check window title for .pdf
    return _get_pdf_from_window_title(app["pid"])


def _get_acrobat_pdf_path() -> str | None:
    """Get PDF path from Adobe Acrobat via AppleScript."""
    script = '''
    tell application "Adobe Acrobat"
        try
            set docPath to file alias of active doc
            return POSIX path of docPath
        end try
    end tell
    '''
    return _run_applescript(script)


def _get_preview_pdf_path() -> str | None:
    """Get PDF path from Preview via AppleScript."""
    script = '''
    tell application "Preview"
        try
            set docPath to path of front document
            return docPath
        end try
    end tell
    '''
    return _run_applescript(script)


def _get_pdf_from_window_title(pid: int) -> str | None:
    """Fallback: try to extract a file path from the window title."""
    windows = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    for w in windows:
        if w.get("kCGWindowOwnerPID") == pid:
            title = w.get("kCGWindowName", "")
            if title and ".pdf" in title.lower():
                # Try common path patterns
                for prefix in ["/Users/", "/tmp/", "/var/"]:
                    if prefix in title:
                        path = title[title.index(prefix):]
                        if path.lower().endswith(".pdf"):
                            return path
                # Return just the title as a hint
                return title
    return None


def _run_applescript(script: str) -> str | None:
    """Execute an AppleScript and return the result."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = result.stdout.strip()
        return output if output else None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError):
        return None
