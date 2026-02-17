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

    # macOS notification
    high_count = len(high_relevance)
    notif_text = f"{len(papers)} papers today"
    if high_count > 0:
        notif_text += f" — {high_count} high relevance"

    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{notif_text}" with title "AtomOra 🔬" subtitle "Daily Paper Briefing"'
        ], check=False, timeout=5)
    except Exception as e:
        print(f"⚠ Notification failed: {e}")

    return str(filepath)
