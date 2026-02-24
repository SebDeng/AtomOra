"""arXiv paper source for daily briefing system."""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import arxiv

from atomora.briefing.sources.base import Paper, PaperSource

logger = logging.getLogger(__name__)


class ArxivSource(PaperSource):
    """Fetch recent papers from arXiv."""

    def __init__(self, config: Optional[dict] = None):
        """Initialize arXiv source.

        Args:
            config: Dict with 'arxiv_categories' key (list of category strings)
        """
        config = config or {}
        self.categories = config.get('arxiv_categories', [
            'cond-mat.mtrl-sci',
            'cond-mat.mes-hall',
            'physics.optics',
            'physics.app-ph',
            'quant-ph',
        ])
        self.client = arxiv.Client(
            page_size=100,
            delay_seconds=5,
            num_retries=5,
        )

    def fetch_recent(self, days: int = 1, max_results: int = 200) -> list[Paper]:
        """Fetch recent papers from arXiv categories.

        Combines all categories into a single OR query to minimize API calls,
        with per-category fallback if the combined query fails.

        Args:
            days: Number of days to look back
            max_results: Maximum total papers to fetch

        Returns:
            Deduplicated list of Paper objects
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        start_str = start_date.strftime('%Y%m%d0000')
        end_str = end_date.strftime('%Y%m%d2359')

        # Strategy 1: Single combined query (1 API call instead of 5)
        cat_expr = ' OR '.join(f'cat:{cat}' for cat in self.categories)
        combined_query = f'({cat_expr}) AND submittedDate:[{start_str} TO {end_str}]'

        papers_dict = {}  # arxiv_id -> Paper

        try:
            papers_dict = self._run_query(combined_query, max_results)
            logger.info(f"arXiv combined query: {len(papers_dict)} papers")
            return list(papers_dict.values())
        except Exception as e:
            logger.warning(f"Combined arXiv query failed: {e}, falling back to per-category")

        # Strategy 2: Per-category with delay (fallback)
        per_cat_limit = max(max_results // len(self.categories), 30)
        for i, category in enumerate(self.categories):
            if i > 0:
                time.sleep(10)  # 10s between categories to avoid 429
            try:
                query = f'cat:{category} AND submittedDate:[{start_str} TO {end_str}]'
                batch = self._run_query(query, per_cat_limit)
                papers_dict.update(batch)
                logger.info(f"arXiv {category}: {len(batch)} papers")
            except Exception as e:
                logger.warning(f"arXiv {category} failed: {e}")
                continue

        return list(papers_dict.values())

    def _run_query(self, query: str, max_results: int) -> dict[str, Paper]:
        """Execute a single arXiv query and return {arxiv_id: Paper}."""
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )

        papers = {}
        for result in self.client.results(search):
            # e.g. "http://arxiv.org/abs/2402.12345v1" -> "2402.12345"
            arxiv_id = result.entry_id.split('/abs/')[-1].split('v')[0]

            if arxiv_id not in papers:
                papers[arxiv_id] = Paper(
                    title=result.title,
                    abstract=result.summary,
                    authors=[author.name for author in result.authors],
                    url=result.entry_id,
                    published=result.published.date().isoformat(),
                    source='arxiv',
                    arxiv_id=arxiv_id,
                    arxiv_pdf_url=result.pdf_url,
                    journal=result.journal_ref,
                    categories=[cat for cat in result.categories],
                )

        return papers
