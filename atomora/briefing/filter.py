"""
Paper deduplication and AI-based filtering for daily briefing.

This module provides:
1. Deduplication across multiple sources (arXiv, S2, OpenAlex)
2. Cross-day seen paper cache (avoid re-recommending papers)
3. LLM-based relevance scoring and summarization using Claude Sonnet 4.5
"""

import os
import re
import unicodedata
import json
import logging
from typing import Optional

import anthropic

from atomora.briefing.sources.base import Paper

logger = logging.getLogger(__name__)


# ─── Cross-day seen paper cache ─────────────────────────────────────

def _paper_cache_key(paper: Paper) -> str:
    """Generate a stable cache key for a paper. Priority: DOI > arXiv ID > title."""
    if paper.doi:
        return f"doi:{paper.doi}"
    if paper.arxiv_id:
        return f"arxiv:{paper.arxiv_id}"
    # Normalize title: lowercase, strip punctuation, collapse whitespace
    t = paper.title.lower().strip()
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return f"title:{t}"


def load_seen_cache(path: str) -> dict[str, str]:
    """Load seen papers cache. Returns {cache_key: date_string}."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load seen cache: {e}")
        return {}


def save_seen_cache(path: str, cache: dict[str, str]) -> None:
    """Save seen papers cache to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def remove_seen_papers(papers: list[Paper], cache: dict[str, str]) -> list[Paper]:
    """Remove papers that are already in the seen cache."""
    if not cache:
        return papers
    result = []
    for p in papers:
        key = _paper_cache_key(p)
        if key not in cache:
            result.append(p)
    removed = len(papers) - len(result)
    if removed:
        logger.info(f"Removed {removed} previously seen papers")
    return result


def _normalize_title(title: str) -> str:
    """Normalize title for fuzzy matching."""
    t = title.lower().strip()
    # Remove punctuation
    t = re.sub(r'[^\w\s]', '', t)
    # Collapse whitespace
    t = re.sub(r'\s+', ' ', t)
    return t


def deduplicate(papers: list[Paper]) -> list[Paper]:
    """
    Deduplicate papers from multiple sources, merging metadata.

    Priority: OpenAlex > S2 > arXiv (journal version preferred over preprint)

    When merging duplicates:
    - Keep the version with journal info (published version)
    - But attach arxiv_pdf_url from the arXiv version (free full-text)
    - Keep highest citation_count
    - Merge categories

    Args:
        papers: List of Paper objects from various sources

    Returns:
        Deduplicated list of Papers with merged metadata
    """
    if not papers:
        return []

    # Index by DOI, arXiv ID, and normalized title
    by_doi: dict[str, Paper] = {}
    by_arxiv: dict[str, Paper] = {}
    by_title: dict[str, Paper] = {}

    # Source priority for keeping the "canonical" version
    SOURCE_PRIORITY = {'openalex': 3, 's2': 2, 'arxiv': 1}

    def get_priority(paper: Paper) -> int:
        return SOURCE_PRIORITY.get(paper.source, 0)

    def is_published(paper: Paper) -> bool:
        """Check if paper has journal publication info."""
        return bool(paper.journal)

    def merge_papers(canonical: Paper, duplicate: Paper) -> Paper:
        """Merge metadata from duplicate into canonical, returning merged Paper."""
        merged = canonical

        # Prefer published version, but keep arXiv PDF link from preprint
        if not is_published(canonical) and is_published(duplicate):
            # Upgrade to published version
            merged = duplicate
            # But keep arXiv PDF if original had it
            if canonical.arxiv_pdf_url and not merged.arxiv_pdf_url:
                merged.arxiv_pdf_url = canonical.arxiv_pdf_url
        elif is_published(canonical) and not is_published(duplicate):
            # Keep canonical, but grab arXiv PDF if available
            if duplicate.arxiv_pdf_url and not merged.arxiv_pdf_url:
                merged.arxiv_pdf_url = duplicate.arxiv_pdf_url

        # Keep highest citation count
        if duplicate.citation_count and (
            not merged.citation_count or duplicate.citation_count > merged.citation_count
        ):
            merged.citation_count = duplicate.citation_count

        # Merge categories (deduplicated)
        if duplicate.categories:
            existing = set(merged.categories or [])
            new_cats = set(duplicate.categories)
            merged.categories = list(existing | new_cats)

        return merged

    for paper in papers:
        # Try matching by DOI first (most reliable)
        if paper.doi:
            if paper.doi in by_doi:
                by_doi[paper.doi] = merge_papers(by_doi[paper.doi], paper)
            else:
                by_doi[paper.doi] = paper
            continue

        # Try matching by arXiv ID
        if paper.arxiv_id:
            if paper.arxiv_id in by_arxiv:
                by_arxiv[paper.arxiv_id] = merge_papers(by_arxiv[paper.arxiv_id], paper)
            else:
                by_arxiv[paper.arxiv_id] = paper
            continue

        # Fall back to fuzzy title matching
        norm_title = _normalize_title(paper.title)
        if norm_title in by_title:
            by_title[norm_title] = merge_papers(by_title[norm_title], paper)
        else:
            by_title[norm_title] = paper

    # Combine all deduplicated papers
    result = list(by_doi.values()) + list(by_arxiv.values()) + list(by_title.values())

    logger.info(f"Deduplicated {len(papers)} papers → {len(result)} unique papers")
    return result


def filter_and_summarize(
    papers: list[Paper],
    api_key: str,
    config: Optional[dict] = None
) -> list[dict]:
    """
    Use Claude Sonnet 4.5 to batch-filter and summarize papers.

    Args:
        papers: List of Paper objects to filter
        api_key: Anthropic API key
        config: Optional config dict with:
            - relevance_threshold (float, default 0.6)
            - max_papers (int, default 10)
            - research_profile (str, optional additional profile text)

    Returns:
        List of dicts: [{"paper": Paper, "score": float, "summary": str}, ...]
        Sorted by score descending, capped at max_papers
    """
    if not papers:
        return []

    config = config or {}
    threshold = config.get('relevance_threshold', 0.6)
    max_papers = config.get('max_papers', 10)
    research_profile = config.get('research_profile', '')

    # System prompt
    system_prompt = f"""You are a research paper filter for a physicist. Evaluate each paper's relevance.

Research focus:
- hexagonal boron nitride (hBN) single photon emitters (SPE), color centers, quantum emitters in 2D materials
- phonon polaritons, nano-optics, nanophotonics, photonic crystal cavities
- transition metal dichalcogenides (TMDs) such as MoS2, WS2, WSe2 — especially chemical vapor deposition (CVD) growth
- cathodoluminescence (CL), aberration-corrected scanning transmission electron microscopy (AC-STEM), electron energy loss spectroscopy (EELS)
- photoluminescence (PL) spectroscopy, Raman spectroscopy of 2D materials
- 2D materials, van der Waals heterostructures, photonics
{research_profile}

Scoring (consider BOTH topic relevance AND journal prestige):
  0.9-1.0: Directly about hBN SPE/quantum emitters, phonon polaritons in hBN/2D, or TMD CVD growth — must read
  0.7-0.9: Related nano-optics, STEM/EELS characterization, PL/Raman of 2D materials, quantum photonics
  0.5-0.7: Adjacent materials science, useful methodology or instrumentation
  <0.5: Not relevant

Journal prestige bonus: bump score by +0.05~0.1 for top-tier journals (Nature, Science, Nature Photonics, Nature Materials, PRL, Nano Letters, etc.). A marginally relevant paper in Nature is worth flagging; the same paper in a low-impact journal may not be.

For papers scoring ≥{threshold}, write a one-line summary (1 sentence, conversational, like a colleague saying "this one's about..."). Bilingual OK if the paper is Chinese.

Return ONLY a JSON array: [{{"index": 0, "score": 0.85, "summary": "..."}}, ...]
Only include papers with score ≥ {threshold}. No other text."""

    # If too many papers, batch them
    if len(papers) > 150:
        logger.info(f"Batching {len(papers)} papers into chunks of 100")
        all_results = []
        for i in range(0, len(papers), 100):
            batch = papers[i:i+100]
            batch_results = _filter_batch(batch, api_key, system_prompt, threshold, offset=i)
            all_results.extend(batch_results)

        # Sort by score and cap
        all_results.sort(key=lambda x: x['score'], reverse=True)
        return all_results[:max_papers]
    else:
        results = _filter_batch(papers, api_key, system_prompt, threshold, offset=0)
        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:max_papers]


def _filter_batch(
    papers: list[Paper],
    api_key: str,
    system_prompt: str,
    threshold: float,
    offset: int = 0
) -> list[dict]:
    """Filter a single batch of papers."""
    # Build user message with numbered papers
    paper_entries = []
    for i, paper in enumerate(papers):
        idx = offset + i
        entry = f"[{idx}] {paper.title}\n"
        if paper.authors:
            entry += f"Authors: {', '.join(paper.authors[:3])}"
            if len(paper.authors) > 3:
                entry += " et al."
            entry += "\n"
        if paper.journal:
            entry += f"Journal: {paper.journal}\n"
        entry += f"Abstract: {paper.abstract}\n"
        paper_entries.append(entry)

    user_message = "\n".join(paper_entries)

    # Call Claude Sonnet 4.5
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )

        response_text = response.content[0].text.strip()

        # Try to parse JSON
        try:
            scored_papers = json.loads(response_text)
        except json.JSONDecodeError:
            # Try extracting from markdown code block
            match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', response_text, re.DOTALL)
            if match:
                scored_papers = json.loads(match.group(1))
            else:
                logger.error(f"Failed to parse LLM response as JSON: {response_text[:200]}")
                return []

        # Build result list
        results = []
        for item in scored_papers:
            idx = item.get('index')
            score = item.get('score', 0.0)
            summary = item.get('summary', '')

            # Map index back to original paper
            original_idx = idx - offset
            if 0 <= original_idx < len(papers):
                results.append({
                    'paper': papers[original_idx],
                    'score': score,
                    'summary': summary
                })

        logger.info(f"Filtered batch: {len(papers)} papers → {len(results)} above threshold {threshold}")
        return results

    except Exception as e:
        logger.error(f"Error calling Claude API: {e}")
        return []
