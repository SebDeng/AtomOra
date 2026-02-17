"""OpenAlex paper source for daily briefing.

Uses pyalex to fetch recent papers from OpenAlex API.
"""

from datetime import datetime, timedelta
from typing import Any

import pyalex
from pyalex import Works

from atomora.briefing.sources.base import Paper, PaperSource


class OpenAlexSource(PaperSource):
    """Fetch papers from OpenAlex API."""

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize OpenAlex source.

        Args:
            config: Configuration dict with:
                - openalex_concepts: list of concept names to filter by
                - email: optional email for polite pool
        """
        config = config or {}
        self.concepts = config.get("openalex_concepts", [
            "photonics",
            "materials science",
            "nanotechnology",
            "optics",
        ])
        email = config.get("email")
        if email:
            pyalex.config.email = email

    def fetch_recent(self, days: int = 1, max_results: int = 100) -> list[Paper]:
        """Fetch recent papers from OpenAlex.

        Args:
            days: Number of days to look back
            max_results: Maximum number of results to return

        Returns:
            List of Paper objects
        """
        from_date = datetime.now() - timedelta(days=days)
        date_str = from_date.strftime("%Y-%m-%d")

        try:
            # Build search query with concepts as keywords
            query_parts = []
            for concept in self.concepts:
                query_parts.append(f'"{concept}"')
            search_query = " OR ".join(query_parts) if query_parts else None

            # Fetch works
            works_query = Works().filter(from_publication_date=date_str)
            if search_query:
                works_query = works_query.search(search_query)

            results = works_query.get(per_page=max_results)

            papers = []
            for work in results:
                paper = self._parse_work(work)
                if paper:
                    papers.append(paper)

            return papers

        except Exception as e:
            print(f"Error fetching from OpenAlex: {e}")
            return []

    def _parse_work(self, work: dict) -> Paper | None:
        """Parse OpenAlex work into Paper object.

        Args:
            work: OpenAlex work dict

        Returns:
            Paper object or None if parsing fails
        """
        try:
            # Skip non-article types (conference proceedings, book chapters, etc.)
            work_type = work.get("type", "")
            if work_type in ("proceedings-article", "book-chapter", "posted-content"):
                return None

            # Extract basic fields
            title = work.get("title", "").strip()
            if not title:
                return None

            # Reconstruct abstract from inverted index
            abstract_inverted = work.get("abstract_inverted_index")
            abstract = self._reconstruct_abstract(abstract_inverted) if abstract_inverted else ""

            # Extract authors
            authors = []
            authorships = work.get("authorships", [])
            for authorship in authorships:
                author = authorship.get("author", {})
                name = author.get("display_name")
                if name:
                    authors.append(name)

            # Extract IDs
            ids = work.get("ids", {})
            doi = ids.get("doi")
            if doi and doi.startswith("https://doi.org/"):
                doi = doi.replace("https://doi.org/", "")

            # Extract arXiv ID
            arxiv_id = None
            arxiv_pdf_url = None
            arxiv_url = ids.get("pmid") or ""  # Sometimes in other fields
            if "arxiv" in str(work.get("ids", {})).lower():
                # Check in locations for arxiv
                for loc in work.get("locations", []):
                    landing_page = loc.get("landing_page_url", "")
                    if "arxiv.org" in landing_page:
                        # Extract arxiv ID from URL
                        parts = landing_page.rstrip("/").split("/")
                        if parts:
                            arxiv_id = parts[-1]
                            arxiv_pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
                        break

            # Extract journal
            journal = None
            primary_location = work.get("primary_location") or {}
            source_info = primary_location.get("source") or {}
            journal = source_info.get("display_name")

            # Extract publication date
            published = work.get("publication_date", "")

            # Extract citation count
            citation_count = work.get("cited_by_count", 0)

            # Build URL (prefer DOI, fallback to OpenAlex)
            url = f"https://doi.org/{doi}" if doi else ids.get("openalex", "")

            # Extract categories from concepts
            categories = []
            concepts = work.get("concepts", [])
            for concept in concepts[:5]:  # Top 5 concepts
                name = concept.get("display_name")
                if name:
                    categories.append(name)

            return Paper(
                title=title,
                abstract=abstract,
                authors=authors,
                url=url,
                published=published,
                source="openalex",
                doi=doi,
                arxiv_id=arxiv_id,
                arxiv_pdf_url=arxiv_pdf_url,
                journal=journal,
                citation_count=citation_count,
                categories=categories,
            )

        except Exception as e:
            print(f"Error parsing OpenAlex work: {e}")
            return None

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict) -> str:
        """Reconstruct abstract text from OpenAlex inverted index.

        OpenAlex stores abstracts as inverted index where keys are words
        and values are lists of positions.

        Args:
            inverted_index: Dict mapping words to position lists

        Returns:
            Reconstructed abstract text
        """
        if not inverted_index:
            return ""

        word_positions = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))

        word_positions.sort()
        return " ".join(w for _, w in word_positions)
