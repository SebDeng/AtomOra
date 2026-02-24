"""Tests for cross-day seen paper cache."""

import json
import os
import tempfile

import pytest

from atomora.briefing.sources.base import Paper
from atomora.briefing.filter import (
    load_seen_cache,
    save_seen_cache,
    remove_seen_papers,
    _paper_cache_key,
)


def _make_paper(title="Test Paper", doi=None, arxiv_id=None, **kw):
    defaults = dict(
        abstract="Abstract", authors=["A"], url="http://example.com",
        published="2026-02-23", source="arxiv",
    )
    defaults.update(kw)
    return Paper(title=title, doi=doi, arxiv_id=arxiv_id, **defaults)


class TestPaperCacheKey:
    def test_doi_preferred(self):
        p = _make_paper(doi="10.1234/foo", arxiv_id="2602.12345")
        assert _paper_cache_key(p) == "doi:10.1234/foo"

    def test_arxiv_id_fallback(self):
        p = _make_paper(arxiv_id="2602.12345")
        assert _paper_cache_key(p) == "arxiv:2602.12345"

    def test_title_fallback(self):
        p = _make_paper(title="  Hello World!  ")
        key = _paper_cache_key(p)
        assert key == "title:hello world"

    def test_title_normalized(self):
        """Same title with different casing/whitespace produces same key."""
        p1 = _make_paper(title="  Foo Bar: A Study!  ")
        p2 = _make_paper(title="foo bar a study")
        assert _paper_cache_key(p1) == _paper_cache_key(p2)


class TestLoadSaveCache:
    def test_load_missing_file(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        cache = load_seen_cache(path)
        assert cache == {}

    def test_save_and_load_roundtrip(self, tmp_path):
        path = str(tmp_path / "cache.json")
        data = {"doi:10.1234/foo": "2026-02-23", "arxiv:2602.111": "2026-02-22"}
        save_seen_cache(path, data)
        loaded = load_seen_cache(path)
        assert loaded == data

    def test_save_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "sub" / "dir" / "cache.json")
        save_seen_cache(path, {"key": "2026-02-23"})
        assert os.path.isfile(path)

    def test_load_corrupted_file(self, tmp_path):
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not json{{{")
        cache = load_seen_cache(path)
        assert cache == {}


class TestRemoveSeenPapers:
    def test_removes_seen_by_doi(self):
        papers = [
            _make_paper(title="New", doi="10.1234/new"),
            _make_paper(title="Old", doi="10.1234/old"),
        ]
        cache = {"doi:10.1234/old": "2026-02-22"}
        result = remove_seen_papers(papers, cache)
        assert len(result) == 1
        assert result[0].title == "New"

    def test_removes_seen_by_arxiv_id(self):
        papers = [
            _make_paper(title="New", arxiv_id="2602.999"),
            _make_paper(title="Old", arxiv_id="2602.111"),
        ]
        cache = {"arxiv:2602.111": "2026-02-22"}
        result = remove_seen_papers(papers, cache)
        assert len(result) == 1
        assert result[0].title == "New"

    def test_removes_seen_by_title(self):
        papers = [
            _make_paper(title="Brand New Paper"),
            _make_paper(title="Already Seen Paper"),
        ]
        cache = {"title:already seen paper": "2026-02-21"}
        result = remove_seen_papers(papers, cache)
        assert len(result) == 1
        assert result[0].title == "Brand New Paper"

    def test_empty_cache_keeps_all(self):
        papers = [_make_paper(title="A"), _make_paper(title="B")]
        result = remove_seen_papers(papers, {})
        assert len(result) == 2

    def test_all_seen_returns_empty(self):
        papers = [_make_paper(title="Seen", doi="10.1/a")]
        cache = {"doi:10.1/a": "2026-02-23"}
        result = remove_seen_papers(papers, cache)
        assert len(result) == 0
