"""
CI Module — Vector Index (ChromaDB).

Provides semantic search over ci_canonical_items using ChromaDB's built-in embeddings.
Collection name: ci_items
"""
import hashlib
import threading
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logging_config import logger, get_trace_id

CI_COLLECTION = "ci_items"


class CIVectorIndex:
    """Manages the ci_items ChromaDB collection for semantic similarity search."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(CIVectorIndex, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        try:
            import chromadb
            from backend.src.config import settings

            persist_dir = settings.CHROMA_PERSIST_DIRECTORY
            self._client = chromadb.PersistentClient(path=persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=CI_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            self._initialized = True
            logger.info(f"CI_VECTOR_INDEX_INIT | collection={CI_COLLECTION} | path={persist_dir}")
        except Exception as e:
            logger.error(f"CI_VECTOR_INDEX_INIT_FAILED | error={e}")
            raise

    @classmethod
    def reset_instance(cls):
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None

    @property
    def collection(self):
        return self._collection

    def upsert_item(
        self,
        item_id: str,
        text: str,
        metadata: Dict[str, Any],
    ) -> str:
        """Upsert a single item into the vector index.

        Args:
            item_id: Unique ID for the item (typically str(ci_canonical_item.id)).
            text: The text content to embed (title + body).
            metadata: Filterable metadata (org_id, competitor_id, item_type, etc.).

        Returns:
            The document ID used in ChromaDB.
        """
        doc_id = f"ci_{item_id}"

        # ChromaDB metadata must be str/int/float/bool
        safe_meta = {}
        for k, v in metadata.items():
            if v is None:
                continue
            if isinstance(v, (str, int, float, bool)):
                safe_meta[k] = v
            else:
                safe_meta[k] = str(v)

        safe_meta["trace_id"] = get_trace_id()

        self._collection.upsert(
            ids=[doc_id],
            documents=[text],
            metadatas=[safe_meta],
        )

        logger.info(
            f"CI_VECTOR_UPSERT | doc_id={doc_id} | text_len={len(text)} | "
            f"meta_keys={list(safe_meta.keys())}"
        )
        return doc_id

    def upsert_batch(
        self,
        items: List[Tuple[str, str, Dict[str, Any]]],
    ) -> List[str]:
        """Upsert multiple items in a single batch.

        Args:
            items: List of (item_id, text, metadata) tuples.

        Returns:
            List of document IDs.
        """
        if not items:
            return []

        ids = []
        documents = []
        metadatas = []
        trace_id = get_trace_id()

        for item_id, text, metadata in items:
            doc_id = f"ci_{item_id}"
            ids.append(doc_id)
            documents.append(text)

            safe_meta = {}
            for k, v in metadata.items():
                if v is None:
                    continue
                if isinstance(v, (str, int, float, bool)):
                    safe_meta[k] = v
                else:
                    safe_meta[k] = str(v)
            safe_meta["trace_id"] = trace_id
            metadatas.append(safe_meta)

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)

        logger.info(f"CI_VECTOR_UPSERT_BATCH | count={len(ids)}")
        return ids

    def search_text(
        self,
        query_text: str,
        n_results: int = 10,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search by text query (semantic similarity).

        Args:
            query_text: Natural language query.
            n_results: Max results to return.
            where: ChromaDB where filter (e.g., {"org_id": "xxx", "item_type": "ad"}).

        Returns:
            List of {id, document, metadata, distance} dicts, sorted by relevance.
        """
        kwargs: Dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where

        results = self._collection.query(**kwargs)

        items = []
        if results and results.get("ids") and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                items.append({
                    "id": doc_id,
                    "document": results["documents"][0][i] if results.get("documents") else "",
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 0.0,
                })

        logger.info(
            f"CI_VECTOR_SEARCH | query_len={len(query_text)} | results={len(items)} | "
            f"n_results={n_results}"
        )
        return items

    def find_similar(
        self,
        item_id: str,
        n_results: int = 5,
        where: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Find items similar to a given item (by its stored document text).

        Args:
            item_id: The ci_canonical_item.id to find neighbors for.
            n_results: Max results.
            where: Optional filter.

        Returns:
            List of similar items (excludes the query item itself).
        """
        doc_id = f"ci_{item_id}"

        try:
            existing = self._collection.get(ids=[doc_id], include=["documents"])
        except Exception:
            logger.warning(f"CI_VECTOR_SIMILAR_NOT_FOUND | doc_id={doc_id}")
            return []

        if not existing or not existing.get("documents") or not existing["documents"][0]:
            return []

        text = existing["documents"][0]
        results = self.search_text(text, n_results=n_results + 1, where=where)

        # Exclude the query item itself
        return [r for r in results if r["id"] != doc_id][:n_results]

    def delete_item(self, item_id: str) -> None:
        """Remove an item from the vector index."""
        doc_id = f"ci_{item_id}"
        try:
            self._collection.delete(ids=[doc_id])
            logger.info(f"CI_VECTOR_DELETE | doc_id={doc_id}")
        except Exception as e:
            logger.warning(f"CI_VECTOR_DELETE_FAILED | doc_id={doc_id} | error={e}")

    def count(self) -> int:
        """Return total number of items in the collection."""
        return self._collection.count()
