"""Local Markdown file + macOS notification."""

import os
import subprocess
from datetime import datetime
from pathlib import Path


DATA_DIR = Path(__file__).parent.parent.parent.parent / "data" / "briefing"


def save_local_briefing(papers: list[dict], stats: dict | None = None) -> str:
    """Save briefing as Markdown file and send macOS notification.

    Returns path to the saved file.
    """
    # Ensure data directory exists
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Generate filename
    today = datetime.now()
    filename = today.strftime("%Y-%m-%d.md")
    filepath = DATA_DIR / filename

    # Build Markdown content
    date_str = today.strftime("%B %d, %Y")
    lines = [f"# 📚 Daily Paper Briefing — {date_str}\n"]

    if stats:
        total = stats.get("total_fetched")
        dedup = stats.get("after_dedup")
        if total and dedup:
            lines.append(f"{len(papers)} papers selected from {total} candidates ({dedup} after dedup)\n")
        else:
            lines.append(f"{len(papers)} papers\n")
    else:
        lines.append(f"{len(papers)} papers\n")

    # Group papers by score
    high_relevance = [p for p in papers if p["score"] >= 0.8]
    relevant = [p for p in papers if 0.6 <= p["score"] < 0.8]

    # High relevance section
    if high_relevance:
        lines.append("\n## 🔥 High Relevance\n")
        for i, item in enumerate(high_relevance, 1):
            paper = item["paper"]
            score = item["score"]
            summary = item["summary"]

            lines.append(f"\n### {i}. [{paper.title}]({paper.url})")

            # Author line
            authors = paper.authors[:3] if paper.authors else []
            author_str = ", ".join(authors)
            if len(paper.authors) > 3:
                author_str += " et al."

            meta_parts = [f"**Score: {int(score * 100)}%**"]
            if author_str:
                meta_parts.append(author_str)
            if paper.journal:
                meta_parts.append(paper.journal)

            lines.append("\n" + " · ".join(meta_parts))
            lines.append(f"> {summary}\n")

            # Links
            links = []
            if paper.arxiv_pdf_url:
                links.append(f"[arXiv PDF]({paper.arxiv_pdf_url})")
            if paper.doi:
                doi_url = f"https://doi.org/{paper.doi}"
                links.append(f"[DOI]({doi_url})")
            if links:
                lines.append(" · ".join(links) + "\n")

            lines.append("\n---\n")

    # Relevant section
    if relevant:
        lines.append("\n## ⭐ Relevant\n")
        start_idx = len(high_relevance) + 1
        for i, item in enumerate(relevant, start_idx):
            paper = item["paper"]
            score = item["score"]
            summary = item["summary"]

            lines.append(f"\n### {i}. [{paper.title}]({paper.url})")

            # Author line
            authors = paper.authors[:3] if paper.authors else []
            author_str = ", ".join(authors)
            if len(paper.authors) > 3:
                author_str += " et al."

            meta_parts = [f"**Score: {int(score * 100)}%**"]
            if author_str:
                meta_parts.append(author_str)
            if paper.journal:
                meta_parts.append(paper.journal)

            lines.append("\n" + " · ".join(meta_parts))
            lines.append(f"> {summary}\n")

            # Links
            links = []
            if paper.arxiv_pdf_url:
                links.append(f"[arXiv PDF]({paper.arxiv_pdf_url})")
            if paper.doi:
                doi_url = f"https://doi.org/{paper.doi}"
                links.append(f"[DOI]({doi_url})")
            if links:
                lines.append(" · ".join(links) + "\n")

            lines.append("\n---\n")

    # Write file
    content = "".join(lines)
    filepath.write_text(content, encoding="utf-8")
    print(f"✓ Saved briefing to {filepath}")

    # macOS notification + open Slack and rendered Markdown
    high_count = len(high_relevance)
    notif_text = f"{len(papers)} papers today"
    if high_count > 0:
        notif_text += f" — {high_count} high relevance"

    _send_notification(notif_text, str(filepath))

    return str(filepath)


def _send_notification(message: str, md_path: str) -> None:
    """Send macOS notification. Click opens Slack + rendered Markdown.

    Uses terminal-notifier (supports click actions) with fallback to osascript.
    """
    import shutil

    tn = shutil.which("terminal-notifier")
    if tn:
        # terminal-notifier: -execute runs a shell command on click
        # Open both Slack and the Markdown file (rendered by default viewer)
        click_cmd = 'open -a Slack'
        try:
            subprocess.run([
                tn,
                "-title", "AtomOra 🔬",
                "-subtitle", "Daily Paper Briefing",
                "-message", message,
                "-execute", click_cmd,
                "-sound", "default",
                "-group", "atomora-briefing",
            ], check=False, timeout=10)
        except Exception as e:
            print(f"⚠ terminal-notifier failed: {e}")
        return

    # Fallback: osascript (no click action, but still shows notification)
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "AtomOra 🔬" subtitle "Daily Paper Briefing"'
        ], check=False, timeout=5)
        subprocess.run(["open", "-a", "Slack"], check=False, timeout=5)
    except Exception as e:
        print(f"⚠ Notification failed: {e}")
