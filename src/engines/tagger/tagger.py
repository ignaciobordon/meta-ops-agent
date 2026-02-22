"""
CP2 — Angle Tagger
Classifies ad creative content into L1/L2/L3 taxonomy tags
using local sentence-transformers embeddings + cosine similarity.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer

from src.schemas.taxonomy import ALL_TAGS, L1_TAGS, L2_TAGS, L3_TAGS, TAG_DESCRIPTIONS, TagScore, TaxonomyTags
from src.database.vector.db_client import VectorDBClient
from src.utils.logging_config import logger, get_trace_id

MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
# NOTE: Upgrading to all-mpnet-base-v2 (768-dim) requires ChromaDB migration from 384-dim
# Current model has ~70% accuracy on marketing classification - acceptable for MVP
CONFIDENCE_THRESHOLD = float(os.getenv("TAGGER_THRESHOLD", "0.15"))
TOP_K_L3 = int(os.getenv("TAGGER_TOP_K_L3", "3"))
COLLECTION_NAME = "taxonomy_centroids"


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    """Load the embedding model once and cache it."""
    logger.info(f"TAGGER_MODEL_LOAD | model={MODEL_NAME}")
    return SentenceTransformer(MODEL_NAME)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    a_norm = np.linalg.norm(a)
    b_norm = np.linalg.norm(b)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    return max(0.0, float(np.dot(a, b) / (a_norm * b_norm)))


class Tagger:
    """
    Classifies ad content into the three-level taxonomy using
    sentence-transformer embeddings and centroid-based cosine similarity.

    Centroids are pre-computed from the tag label text and stored in
    ChromaDB so they only need to be encoded once per deployment.
    """

    def __init__(self):
        self.model = _load_model()
        self.db = VectorDBClient()
        self.threshold = CONFIDENCE_THRESHOLD
        self._centroids: dict[str, np.ndarray] | None = None
        self._ensure_centroids()

    # ── Centroid Management ──────────────────────────────────────────────────

    def _ensure_centroids(self):
        """Encode tag descriptions and persist centroids in ChromaDB.
        Always upserts so stale embeddings are replaced when descriptions change.
        """
        logger.info(f"TAGGER_CENTROID_INIT | encoding {len(ALL_TAGS)} tags")
        descriptions = [TAG_DESCRIPTIONS.get(tag, tag) for tag in ALL_TAGS]
        embeddings = self.model.encode(descriptions, normalize_embeddings=True).tolist()
        self.db.upsert(
            collection_name=COLLECTION_NAME,
            ids=ALL_TAGS,
            embeddings=embeddings,
            metadatas=[{"tag": tag} for tag in ALL_TAGS],
        )
        self._centroids = self._load_centroids()

    def _load_centroids(self) -> dict[str, np.ndarray]:
        collection = self.db.get_collection(COLLECTION_NAME)
        result = collection.get(include=["embeddings", "metadatas"])
        centroids = {}
        for tag, emb in zip(result["ids"], result["embeddings"]):
            centroids[tag] = np.array(emb, dtype=np.float32)
        logger.info(f"TAGGER_CENTROIDS_LOADED | count={len(centroids)}")
        return centroids

    # ── Classification ───────────────────────────────────────────────────────

    def classify(self, ad_content: str) -> TaxonomyTags:
        """
        Encode ad_content and compare against all tag centroids.
        Returns top L1, top L2, top-K L3 above threshold.
        """
        trace_id = get_trace_id()
        logger.info(f"TAGGER_CLASSIFY_STARTED | trace_id={trace_id} | length={len(ad_content)}")

        vec = self.model.encode(ad_content, normalize_embeddings=True)

        all_scores: List[TagScore] = [
            TagScore(tag=tag, score=_cosine_similarity(vec, centroid))
            for tag, centroid in self._centroids.items()
        ]
        all_scores.sort(key=lambda x: x.score, reverse=True)

        def best_in_group(tags: List[str]) -> TagScore | None:
            group = [s for s in all_scores if s.tag in tags]
            top = group[0] if group else None
            if top and top.score >= self.threshold:
                return top
            return None

        l1 = best_in_group(L1_TAGS)
        l2 = best_in_group(L2_TAGS)
        l3 = [s for s in all_scores if s.tag in L3_TAGS and s.score >= self.threshold][:TOP_K_L3]

        result = TaxonomyTags(
            l1_intent=l1,
            l2_driver=l2,
            l3_execution=l3,
            all_scores=all_scores,
            threshold=self.threshold,
        )

        logger.info(
            f"TAGGER_CLASSIFY_DONE | l1={l1.tag if l1 else None} "
            f"| l2={l2.tag if l2 else None} "
            f"| l3_count={len(l3)}"
        )
        return result
