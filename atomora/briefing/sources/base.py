"""Base types for paper sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Paper:
    """Unified paper representation across all sources."""

    title: str
    abstract: str
    authors: list[str]
    url: str
    published: str  # ISO date string (YYYY-MM-DD)
    source: str  # "arxiv" | "openalex" | "s2"
    doi: str | None = None
    arxiv_id: str | None = None
    arxiv_pdf_url: str | None = None
    journal: str | None = None
    citation_count: int = 0
    categories: list[str] = field(default_factory=list)


def is_conference_proceeding(journal: str | None) -> bool:
    """Heuristic to detect conference proceedings from journal name."""
    if not journal:
        return False
    j = journal.lower()
    # Common conference proceeding patterns
    indicators = [
        "proceedings", "conference", "symposium", "workshop",
        "meeting", "congress", " ieee ", "lecture notes",
        # SPIE pattern: title + roman numeral suffix (e.g. "... IX", "... XIV")
    ]
    if any(ind in j for ind in indicators):
        return True
    # SPIE-style: ends with roman numerals
    import re
    if re.search(r'\b[IVXLC]+$', journal.strip()):
        return True
    return False


class PaperSource(ABC):
    """Abstract base class for paper sources."""

    @abstractmethod
    def fetch_recent(self, days: int = 1, max_results: int = 100) -> list[Paper]:
        """Fetch recent papers from this source.

        Args:
            days: How many days back to look.
            max_results: Maximum number of papers to return.

        Returns:
            List of Paper objects.
        """
        ...
