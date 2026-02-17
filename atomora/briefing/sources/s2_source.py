"""Semantic Scholar paper source for daily briefing system."""

import time
from datetime import datetime, timedelta
from typing import Any

from semanticscholar import SemanticScholar

from atomora.briefing.sources.base import Paper, PaperSource, is_conference_proceeding


class SemanticScholarSource(PaperSource):
    """Fetches recent papers from Semantic Scholar API."""

    def __init__(self, config: dict[str, Any]):
        """Initialize S2 source.

        Args:
            config: Configuration dict with:
                - s2_queries: List of search queries
                - api_key: Optional API key for higher rate limits
        """
        self.queries = config.get("s2_queries", [
            "hexagonal boron nitride",
            "single-photon emitter",
            "cathodoluminescence STEM",
            "quantum emitter 2D materials"
        ])
        api_key = config.get("api_key")
        self.sch = SemanticScholar(api_key=api_key)

    def fetch_recent(self, days: int = 1, max_results: int = 50) -> list[Paper]:
        """Fetch recent papers from Semantic Scholar.

        Args:
            days: Number of days to look back
            max_results: Maximum results per query

        Returns:
            List of Paper objects, deduplicated across queries
        """
        cutoff_date = datetime.now() - timedelta(days=days)
        seen_ids = set()
        papers = []

        fields = [
            "title",
            "abstract",
            "authors",
            "url",
            "publicationDate",
            "citationCount",
            "externalIds",
            "journal",
            "openAccessPdf",
            "publicationTypes"
        ]

        for query in self.queries:
            try:
                # Logged at debug level — use -v to see
                results = self.sch.search_paper(
                    query=query,
                    fields=fields,
                    bulk=True,
                    sort="publicationDate:desc",
                    limit=max_results
                )

                query_count = 0
                old_count = 0
                for paper in results:
                    # Stop after enough results per query
                    if query_count >= max_results:
                        break

                    # Deduplicate by paperId
                    paper_id = getattr(paper, "paperId", None)
                    if paper_id in seen_ids:
                        continue

                    # Filter by publication date
                    pub_date_raw = getattr(paper, "publicationDate", None)
                    if not pub_date_raw:
                        continue

                    try:
                        # S2 may return datetime, date, or string
                        if isinstance(pub_date_raw, datetime):
                            pub_date = pub_date_raw
                        elif hasattr(pub_date_raw, "year"):
                            pub_date = datetime(pub_date_raw.year, pub_date_raw.month, pub_date_raw.day)
                        else:
                            pub_date = datetime.strptime(str(pub_date_raw), "%Y-%m-%d")
                        if pub_date < cutoff_date:
                            old_count += 1
                            # If sorted by date desc, stop after several old papers
                            if old_count >= 10:
                                break
                            continue
                    except (ValueError, TypeError):
                        continue

                    # Skip conference papers
                    pub_types = getattr(paper, "publicationTypes", None) or []
                    if "Conference" in pub_types:
                        continue

                    # Extract fields
                    title = getattr(paper, "title", "")
                    abstract = getattr(paper, "abstract", "")
                    url = getattr(paper, "url", "")

                    if not title:
                        continue
                    # Bulk API often omits abstracts; still include these papers
                    if not abstract:
                        abstract = ""

                    # Authors
                    authors_list = getattr(paper, "authors", [])
                    authors = [a.name for a in authors_list if hasattr(a, "name")]

                    # External IDs
                    external_ids = getattr(paper, "externalIds", {}) or {}
                    arxiv_id = external_ids.get("ArXiv")
                    doi = external_ids.get("DOI")

                    # PDF URL
                    open_access_pdf = getattr(paper, "openAccessPdf", None)
                    arxiv_pdf_url = open_access_pdf.url if open_access_pdf and hasattr(open_access_pdf, "url") else None

                    # Journal
                    journal_obj = getattr(paper, "journal", None)
                    journal = journal_obj.name if journal_obj and hasattr(journal_obj, "name") else None

                    # Skip conference proceedings by journal name heuristic
                    if is_conference_proceeding(journal):
                        continue

                    # Citation count
                    citation_count = getattr(paper, "citationCount", 0) or 0

                    papers.append(Paper(
                        title=title,
                        abstract=abstract,
                        authors=authors,
                        url=url,
                        published=pub_date.strftime("%Y-%m-%d"),
                        source="s2",
                        doi=doi,
                        arxiv_id=arxiv_id,
                        arxiv_pdf_url=arxiv_pdf_url,
                        journal=journal,
                        citation_count=citation_count
                    ))

                    seen_ids.add(paper_id)
                    query_count += 1

                # Rate limit between queries
                time.sleep(1)

            except Exception as e:
                print(f"[S2] Warning: Query '{query}' failed: {e}")
                continue

        # Summary is printed by the caller
        return papers
