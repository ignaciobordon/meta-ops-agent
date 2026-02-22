"""
Tests for CI module — Vector Index (ChromaDB).
"""
import pytest
import os
import tempfile
from uuid import uuid4

# Override ChromaDB path before importing
_tmp_dir = tempfile.mkdtemp()
os.environ["CHROMA_PERSIST_DIRECTORY"] = _tmp_dir


class TestCIVectorIndex:
    """Tests using a fresh ChromaDB instance per test class."""

    @pytest.fixture(autouse=True)
    def setup_index(self, tmp_path, monkeypatch):
        """Create a fresh vector index for each test."""
        monkeypatch.setattr(
            "backend.src.config.settings",
            type("MockSettings", (), {"CHROMA_PERSIST_DIRECTORY": str(tmp_path)})(),
        )
        # Reset singleton
        from backend.src.ci.vector_index import CIVectorIndex
        CIVectorIndex.reset_instance()
        self.index = CIVectorIndex()
        yield
        CIVectorIndex.reset_instance()

    def test_upsert_single_item(self):
        doc_id = self.index.upsert_item(
            item_id="item_001",
            text="Amazing fitness product for weight loss",
            metadata={"org_id": "org_1", "item_type": "ad"},
        )
        assert doc_id == "ci_item_001"
        assert self.index.count() == 1

    def test_upsert_batch(self):
        items = [
            ("id_1", "Running shoes for marathon training", {"org_id": "org_1", "item_type": "ad"}),
            ("id_2", "Yoga mat premium quality", {"org_id": "org_1", "item_type": "post"}),
            ("id_3", "Protein powder chocolate flavor", {"org_id": "org_1", "item_type": "offer"}),
        ]
        ids = self.index.upsert_batch(items)
        assert len(ids) == 3
        assert self.index.count() == 3

    def test_upsert_batch_empty(self):
        ids = self.index.upsert_batch([])
        assert ids == []

    def test_search_text_returns_results(self):
        self.index.upsert_item("s1", "Best running shoes for athletes", {"org_id": "org_1", "item_type": "ad"})
        self.index.upsert_item("s2", "Delicious chocolate cake recipe", {"org_id": "org_1", "item_type": "post"})
        self.index.upsert_item("s3", "Athletic footwear for runners", {"org_id": "org_1", "item_type": "ad"})

        results = self.index.search_text("running shoes", n_results=5)
        assert len(results) >= 1
        assert "id" in results[0]
        assert "document" in results[0]
        assert "distance" in results[0]

    def test_search_with_where_filter(self):
        self.index.upsert_item("f1", "Fitness ad one", {"org_id": "org_1", "item_type": "ad"})
        self.index.upsert_item("f2", "Fitness post two", {"org_id": "org_1", "item_type": "post"})
        self.index.upsert_item("f3", "Fitness ad three", {"org_id": "org_2", "item_type": "ad"})

        results = self.index.search_text(
            "fitness",
            n_results=10,
            where={"org_id": "org_1"},
        )
        for r in results:
            assert r["metadata"]["org_id"] == "org_1"

    def test_find_similar(self):
        self.index.upsert_item("sim1", "Weight loss supplement for gym", {"org_id": "o1", "item_type": "ad"})
        self.index.upsert_item("sim2", "Gym protein supplement", {"org_id": "o1", "item_type": "ad"})
        self.index.upsert_item("sim3", "Cooking recipe Italian pasta", {"org_id": "o1", "item_type": "post"})

        results = self.index.find_similar("sim1", n_results=2)
        assert len(results) >= 1
        # Should not include the query item itself
        for r in results:
            assert r["id"] != "ci_sim1"

    def test_find_similar_nonexistent(self):
        results = self.index.find_similar("nonexistent_id", n_results=5)
        assert results == []

    def test_delete_item(self):
        self.index.upsert_item("del1", "Item to delete", {"org_id": "o1", "item_type": "ad"})
        assert self.index.count() == 1
        self.index.delete_item("del1")
        assert self.index.count() == 0

    def test_metadata_sanitization(self):
        """Non-primitive metadata values should be converted to strings."""
        doc_id = self.index.upsert_item(
            "meta1",
            "Test item",
            {"org_id": uuid4(), "count": 42, "active": True, "tags": ["a", "b"]},
        )
        assert doc_id == "ci_meta1"

    def test_count_empty(self):
        assert self.index.count() == 0
