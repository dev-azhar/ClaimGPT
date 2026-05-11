"""HTTP endpoint tests for the coding service's RAG search routes.

Covers:
  POST /search/icd10
  POST /search/cpt
  GET  /search/cache-stats
  POST /search/cache-clear

Underlying ``services.coding.app.icd10_rag`` is mocked so the tests don't
need the FAISS indices on disk and run in <1s.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

# Make services/coding/app importable as `app.*` so we don't collide with
# sibling test modules (e.g. tests/predictor) when the full suite runs.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "coding"))
for _k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
    del sys.modules[_k]

from fastapi.testclient import TestClient

from app.main import app  # noqa: E402

client = TestClient(app)


class TestSearchIcd10:
    def test_returns_hits(self):
        with patch("app.icd10_rag.is_rag_available", return_value=True), \
             patch(
                 "app.icd10_rag.search_icd10_rag",
                 return_value=[
                     ("E11.9", "Type 2 diabetes mellitus without complications", "Endocrine", 0.91),
                     ("E11.65", "Type 2 diabetes with hyperglycemia", "Endocrine", 0.83),
                 ],
             ):
            resp = client.post(
                "/search/icd10",
                json={"query": "type 2 diabetes", "max_results": 2},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "type 2 diabetes"
        assert data["code_system"] == "ICD-10"
        assert data["total"] == 2
        assert data["results"][0]["code"] == "E11.9"
        assert data["results"][0]["score"] == 0.91
        assert data["results"][0]["category"] == "Endocrine"

    def test_returns_503_when_index_unavailable(self):
        with patch("app.icd10_rag.is_rag_available", return_value=False):
            resp = client.post(
                "/search/icd10",
                json={"query": "fever", "max_results": 5},
            )
        assert resp.status_code == 503
        assert "FAISS" in resp.json()["detail"]

    def test_validates_empty_query(self):
        resp = client.post("/search/icd10", json={"query": "", "max_results": 5})
        assert resp.status_code == 422

    def test_validates_max_results_upper_bound(self):
        resp = client.post(
            "/search/icd10",
            json={"query": "fever", "max_results": 999},
        )
        assert resp.status_code == 422

    def test_validates_min_score_range(self):
        resp = client.post(
            "/search/icd10",
            json={"query": "fever", "min_score": 1.5},
        )
        assert resp.status_code == 422

    def test_validates_mode_pattern(self):
        resp = client.post(
            "/search/icd10",
            json={"query": "fever", "mode": "quantum"},
        )
        assert resp.status_code == 422

    def test_mode_passed_through_to_search(self):
        captured = {}

        def _spy(query, max_results, min_score, mode):
            captured["mode"] = mode
            return [("J18.9", "Pneumonia", "Respiratory", 0.81)]

        with patch("app.icd10_rag.is_rag_available", return_value=True), \
             patch("app.icd10_rag.search_icd10_rag", side_effect=_spy):
            resp = client.post(
                "/search/icd10",
                json={"query": "fever", "max_results": 1, "mode": "bm25"},
            )
        assert resp.status_code == 200
        assert captured["mode"] == "bm25"


class TestSearchCpt:
    def test_returns_hits(self):
        with patch("app.icd10_rag.is_rag_available", return_value=True), \
             patch(
                 "app.icd10_rag.search_cpt_rag",
                 return_value=[
                     ("29881", "Arthroscopy, knee", "Surgery", 0.76),
                 ],
             ):
            resp = client.post(
                "/search/cpt",
                json={"query": "knee arthroscopy", "max_results": 1},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code_system"] == "CPT"
        assert data["results"][0]["code"] == "29881"

    def test_returns_503_when_index_unavailable(self):
        with patch("app.icd10_rag.is_rag_available", return_value=False):
            resp = client.post(
                "/search/cpt",
                json={"query": "appendectomy", "max_results": 5},
            )
        assert resp.status_code == 503


class TestCacheEndpoints:
    def test_cache_stats_shape(self):
        with patch(
            "app.icd10_rag.get_cache_stats",
            return_value={
                "icd10": {"hits": 5, "misses": 3, "current_size": 8, "max_size": 512},
                "cpt": {"hits": 1, "misses": 1, "current_size": 2, "max_size": 512},
            },
        ):
            resp = client.get("/search/cache-stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["icd10"]["hits"] == 5
        assert data["cpt"]["misses"] == 1

    def test_cache_clear(self):
        called = {"v": False}

        def _clear():
            called["v"] = True

        with patch("app.icd10_rag.clear_search_cache", side_effect=_clear):
            resp = client.post("/search/cache-clear")
        assert resp.status_code == 200
        assert resp.json() == {"cleared": True}
        assert called["v"] is True
