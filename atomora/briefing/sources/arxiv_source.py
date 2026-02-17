"""arXiv paper source for daily briefing system."""

from datetime import datetime, timedelta
from typing import Optional

import arxiv

from atomora.briefing.sources.base import Paper, PaperSource


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
            delay_seconds=3,
            num_retries=3,
        )

    def fetch_recent(self, days: int = 1, max_results: int = 100) -> list[Paper]:
        """Fetch recent papers from arXiv categories.

        Args:
            days: Number of days to look back
            max_results: Maximum papers per category

        Returns:
            Deduplicated list of Paper objects
        """
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        start_str = start_date.strftime('%Y%m%d0000')
        end_str = end_date.strftime('%Y%m%d2359')

        papers_dict = {}  # arxiv_id -> Paper (for deduplication)

        for category in self.categories:
            try:
                query = f'cat:{category} AND submittedDate:[{start_str} TO {end_str}]'
                search = arxiv.Search(
                    query=query,
                    max_results=max_results,
                    sort_by=arxiv.SortCriterion.SubmittedDate,
                    sort_order=arxiv.SortOrder.Descending,
                )

                for result in self.client.results(search):
                    # Extract arxiv_id from entry_id
                    # e.g. "http://arxiv.org/abs/2402.12345v1" -> "2402.12345"
                    arxiv_id = result.entry_id.split('/abs/')[-1].split('v')[0]

                    if arxiv_id not in papers_dict:
                        paper = Paper(
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
                        papers_dict[arxiv_id] = paper

            except Exception as e:
                print(f'Warning: Failed to fetch from {category}: {e}')
                continue

        return list(papers_dict.values())
