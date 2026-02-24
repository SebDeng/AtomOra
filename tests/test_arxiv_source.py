"""Tests for arXiv source — combined query strategy and fallback."""

from dataclasses import dataclass
from unittest.mock import MagicMock, patch, call
import time

import pytest

from atomora.briefing.sources.arxiv_source import ArxivSource


# ── Fake arxiv objects ────────────────────────────────────────────

@dataclass
class FakeAuthor:
    name: str

@dataclass
class FakeResult:
    entry_id: str
    title: str
    summary: str
    authors: list
    published: MagicMock
    pdf_url: str
    journal_ref: str | None
    categories: list[str]


def _make_result(arxiv_id: str, title: str = "Paper", cat: str = "cond-mat.mtrl-sci"):
    pub = MagicMock()
    pub.date.return_value.isoformat.return_value = "2026-02-23"
    return FakeResult(
        entry_id=f"http://arxiv.org/abs/{arxiv_id}v1",
        title=title,
        summary="Abstract text",
        authors=[FakeAuthor("Alice"), FakeAuthor("Bob")],
        published=pub,
        pdf_url=f"http://arxiv.org/pdf/{arxiv_id}v1",
        journal_ref=None,
        categories=[cat],
    )


# ── Tests ─────────────────────────────────────────────────────────

class TestCombinedQuery:
    """Test that the combined OR query is the primary strategy."""

    def test_combined_query_builds_or_expression(self):
        source = ArxivSource({"arxiv_categories": ["cat.a", "cat.b"]})
        # _run_query should be called with a combined OR query
        with patch.object(source, '_run_query') as mock_run:
            mock_run.return_value = {}
            source.fetch_recent(days=1)

            assert mock_run.call_count == 1
            query_arg = mock_run.call_args[0][0]
            assert "cat:cat.a OR cat:cat.b" in query_arg
            assert "submittedDate:" in query_arg

    def test_combined_query_returns_papers(self):
        source = ArxivSource()
        r1 = _make_result("2602.11111", "Paper A")
        r2 = _make_result("2602.22222", "Paper B")
        with patch.object(source, '_run_query') as mock_run:
            mock_run.return_value = {
                "2602.11111": MagicMock(),
                "2602.22222": MagicMock(),
            }
            papers = source.fetch_recent(days=1)
            assert len(papers) == 2

    def test_combined_query_deduplicates_by_arxiv_id(self):
        source = ArxivSource()
        results = [
            _make_result("2602.11111", "Paper A", "cat.a"),
            _make_result("2602.11111", "Paper A dup", "cat.b"),
            _make_result("2602.22222", "Paper B", "cat.a"),
        ]
        with patch.object(source.client, 'results', return_value=iter(results)):
            papers = source._run_query("test query", 100)
            assert len(papers) == 2
            assert "2602.11111" in papers
            assert "2602.22222" in papers


class TestFallback:
    """Test per-category fallback when combined query fails."""

    def test_falls_back_to_per_category_on_failure(self):
        source = ArxivSource({"arxiv_categories": ["cat.a", "cat.b"]})

        call_count = 0

        def side_effect(query, max_results):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("429 Too Many Requests")
            return {f"id_{call_count}": MagicMock()}

        with patch.object(source, '_run_query', side_effect=side_effect):
            with patch('atomora.briefing.sources.arxiv_source.time.sleep'):
                papers = source.fetch_recent(days=1)

        # 1 combined (failed) + 2 per-category = 3 calls
        assert call_count == 3
        assert len(papers) == 2

    def test_fallback_adds_delay_between_categories(self):
        source = ArxivSource({"arxiv_categories": ["cat.a", "cat.b", "cat.c"]})

        call_count = 0

        def side_effect(query, max_results):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Combined failed")
            return {}

        with patch.object(source, '_run_query', side_effect=side_effect):
            with patch('atomora.briefing.sources.arxiv_source.time.sleep') as mock_sleep:
                source.fetch_recent(days=1)

        # 2 sleeps for 3 categories (sleep before 2nd and 3rd)
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(10)

    def test_fallback_tolerates_individual_category_failure(self):
        source = ArxivSource({"arxiv_categories": ["cat.a", "cat.b"]})

        call_count = 0

        def side_effect(query, max_results):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # combined + first category fail
                raise RuntimeError("fail")
            return {"paper_1": MagicMock()}

        with patch.object(source, '_run_query', side_effect=side_effect):
            with patch('atomora.briefing.sources.arxiv_source.time.sleep'):
                papers = source.fetch_recent(days=1)

        assert len(papers) == 1


class TestRunQuery:
    """Test the _run_query helper."""

    def test_extracts_arxiv_id_from_entry_id(self):
        source = ArxivSource()
        result = _make_result("2602.12345", "Test Paper")
        with patch.object(source.client, 'results', return_value=iter([result])):
            papers = source._run_query("q", 10)
            assert "2602.12345" in papers
            assert papers["2602.12345"].arxiv_id == "2602.12345"

    def test_paper_fields_populated(self):
        source = ArxivSource()
        result = _make_result("2602.99999", "My Paper", "physics.optics")
        with patch.object(source.client, 'results', return_value=iter([result])):
            papers = source._run_query("q", 10)
            p = papers["2602.99999"]
            assert p.title == "My Paper"
            assert p.source == "arxiv"
            assert p.abstract == "Abstract text"
            assert len(p.authors) == 2
            assert "physics.optics" in p.categories

    def test_empty_results(self):
        source = ArxivSource()
        with patch.object(source.client, 'results', return_value=iter([])):
            papers = source._run_query("q", 10)
            assert papers == {}
