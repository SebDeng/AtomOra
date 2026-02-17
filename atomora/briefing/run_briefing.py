"""Daily Paper Briefing pipeline orchestrator.

Usage:
    python -m atomora.briefing.run_briefing
    python -m atomora.briefing.run_briefing --days 3
    python -m atomora.briefing.run_briefing --days 3 --dry-run
"""

import argparse
import logging
import os
import sys
import time

import yaml

from atomora.briefing.sources.base import Paper
from atomora.briefing.sources.arxiv_source import ArxivSource
from atomora.briefing.sources.openalex_source import OpenAlexSource
from atomora.briefing.sources.s2_source import SemanticScholarSource
from atomora.briefing.filter import deduplicate, filter_and_summarize
from atomora.briefing.delivery.local import save_local_briefing
from atomora.briefing.delivery.slack import send_slack_briefing

logger = logging.getLogger(__name__)

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")


def load_yaml(filename: str) -> dict:
    path = os.path.join(CONFIG_DIR, filename)
    if os.path.exists(path):
        with open(path) as f:
            return yaml.load(f, Loader=yaml.UnsafeLoader) or {}
    return {}


def fetch_all_papers(settings: dict, secrets: dict, days: int) -> tuple[list[Paper], dict]:
    """Fetch papers from all sources, tolerating individual failures.

    Returns (papers, stats) where stats has source counts.
    """
    briefing_cfg = settings.get("briefing", {})
    papers: list[Paper] = []
    stats: dict[str, int] = {}

    # --- arXiv ---
    try:
        print("  → arXiv ...", end=" ", flush=True)
        t0 = time.time()
        source = ArxivSource(briefing_cfg)
        arxiv_papers = source.fetch_recent(days=days)
        elapsed = time.time() - t0
        papers.extend(arxiv_papers)
        stats["arxiv"] = len(arxiv_papers)
        print(f"{len(arxiv_papers)} papers ({elapsed:.1f}s)")
    except Exception as e:
        print(f"FAILED: {e}")
        logger.error(f"arXiv fetch failed: {e}")

    # --- OpenAlex ---
    try:
        print("  → OpenAlex ...", end=" ", flush=True)
        t0 = time.time()
        oa_config = {**briefing_cfg}
        email = secrets.get("openalex", {}).get("email", "")
        if email:
            oa_config["email"] = email
        source = OpenAlexSource(oa_config)
        oa_papers = source.fetch_recent(days=days)
        elapsed = time.time() - t0
        papers.extend(oa_papers)
        stats["openalex"] = len(oa_papers)
        print(f"{len(oa_papers)} papers ({elapsed:.1f}s)")
    except Exception as e:
        print(f"FAILED: {e}")
        logger.error(f"OpenAlex fetch failed: {e}")

    # --- Semantic Scholar ---
    try:
        print("  → Semantic Scholar ...", end=" ", flush=True)
        t0 = time.time()
        s2_config = {**briefing_cfg}
        s2_key = secrets.get("semanticscholar", {}).get("api_key", "")
        if s2_key:
            s2_config["api_key"] = s2_key
        source = SemanticScholarSource(s2_config)
        s2_papers = source.fetch_recent(days=days, max_results=50)
        elapsed = time.time() - t0
        papers.extend(s2_papers)
        stats["s2"] = len(s2_papers)
        print(f"{len(s2_papers)} papers ({elapsed:.1f}s)")
    except Exception as e:
        print(f"FAILED: {e}")
        logger.error(f"Semantic Scholar fetch failed: {e}")

    return papers, stats


def print_dry_run(filtered: list[dict]) -> None:
    """Print filtered papers to console (dry-run mode)."""
    if not filtered:
        print("\nNo papers passed the relevance filter.")
        return

    print(f"\n{'='*60}")
    print(f"  TOP {len(filtered)} PAPERS")
    print(f"{'='*60}\n")

    for i, item in enumerate(filtered, 1):
        paper = item["paper"]
        score = item["score"]
        summary = item["summary"]

        emoji = "🔥" if score >= 0.8 else "⭐"
        print(f"{emoji} [{i}] {paper.title}")
        print(f"   Score: {int(score * 100)}%  |  {paper.source}", end="")
        if paper.journal:
            print(f"  |  {paper.journal}", end="")
        print()

        authors = paper.authors[:3] if paper.authors else []
        if authors:
            author_str = ", ".join(authors)
            if len(paper.authors) > 3:
                author_str += " et al."
            print(f"   Authors: {author_str}")

        print(f"   → {summary}")

        if paper.url:
            print(f"   {paper.url}")
        print()


def run(days: int = 1, dry_run: bool = False) -> None:
    """Run the full briefing pipeline."""
    print(f"\n🔬 AtomOra Daily Paper Briefing")
    print(f"   Looking back {days} day(s)\n")

    # 1. Load config
    settings = load_yaml("settings.yaml")
    secrets = load_yaml("secrets.yaml")
    briefing_cfg = settings.get("briefing", {})

    # Check for Anthropic API key (required for filtering)
    anthropic_key = secrets.get("anthropic", {}).get("api_key", "")
    if not anthropic_key:
        print("✗ No Anthropic API key found in secrets.yaml — cannot filter papers.")
        sys.exit(1)

    # 2. Fetch papers from all sources
    print("📡 Fetching papers...")
    all_papers, source_stats = fetch_all_papers(settings, secrets, days)
    total_fetched = len(all_papers)

    if total_fetched == 0:
        print("\n✗ No papers fetched from any source. Check your network and config.")
        return

    print(f"\n  Total fetched: {total_fetched}")

    # 3. Deduplicate
    print("\n🔄 Deduplicating...")
    unique_papers = deduplicate(all_papers)
    after_dedup = len(unique_papers)
    print(f"  {total_fetched} → {after_dedup} unique papers")

    # 4. Filter with LLM (Sonnet 4.5)
    print(f"\n🧠 Filtering with Sonnet 4.5 ({after_dedup} papers)...")
    t0 = time.time()
    filtered = filter_and_summarize(unique_papers, anthropic_key, briefing_cfg)
    elapsed = time.time() - t0
    print(f"  {len(filtered)} papers passed filter ({elapsed:.1f}s)")

    # Build stats dict for delivery
    delivery_stats = {
        "total_fetched": total_fetched,
        "after_dedup": after_dedup,
        **{f"source_{k}": v for k, v in source_stats.items()},
    }

    # 5. Dry-run: print to console and exit
    if dry_run:
        print_dry_run(filtered)
        print("(dry-run mode — no delivery)")
        return

    # 6. Local delivery (always)
    print("\n📝 Saving local briefing...")
    filepath = save_local_briefing(filtered, delivery_stats)
    print(f"  → {filepath}")

    # 7. Slack delivery (if configured)
    slack_url = secrets.get("slack", {}).get("webhook_url", "")
    if slack_url:
        print("\n📨 Sending to Slack...")
        ok = send_slack_briefing(slack_url, filtered, delivery_stats)
        if ok:
            print("  ✓ Slack delivered")
        else:
            print("  ✗ Slack delivery failed")
    else:
        print("\n  (Slack not configured — skipping)")

    # 8. Summary
    high = sum(1 for p in filtered if p["score"] >= 0.8)
    print(f"\n✅ Done! {len(filtered)} papers ({high} high-relevance)")


def main():
    parser = argparse.ArgumentParser(
        description="AtomOra Daily Paper Briefing",
        prog="python -m atomora.briefing.run_briefing",
    )
    parser.add_argument(
        "--days", type=int, default=1,
        help="How many days back to look (default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print results to console only, skip delivery",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # In verbose mode, show our module at INFO; otherwise quiet
    if args.verbose:
        logging.getLogger("atomora.briefing").setLevel(logging.DEBUG)

    run(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
