"""
CI Module — Engine Core.

CompetitiveIntelligenceEngine: the main service class for CI operations.
Handles CRUD for competitors, canonical items, and orchestrates vector search.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from backend.src.ci.models import (
    CICanonicalItem,
    CICompetitor,
    CICompetitorDomain,
    CICompetitorStatus,
    CIDomainType,
    CIIngestRun,
    CIIngestStatus,
    CIItemType,
    CISource,
    CISourceType,
)
from backend.src.ci.normalizer import (
    normalize_ad,
    normalize_landing_page,
    normalize_offer,
    normalize_post,
)
from src.utils.logging_config import logger, get_trace_id


class CompetitiveIntelligenceEngine:
    """Main CI engine. All methods enforce org_id tenant isolation."""

    def __init__(self, db: Session):
        self.db = db

    # ── Competitors ───────────────────────────────────────────────────────────

    def register_competitor(
        self,
        org_id: UUID,
        name: str,
        website_url: Optional[str] = None,
        logo_url: Optional[str] = None,
        notes: Optional[str] = None,
        domains: Optional[List[Dict[str, str]]] = None,
        meta_json: Optional[Dict] = None,
    ) -> CICompetitor:
        """Register a new competitor for the org."""
        competitor = CICompetitor(
            org_id=org_id,
            name=name,
            website_url=website_url,
            logo_url=logo_url,
            notes=notes,
            status=CICompetitorStatus.ACTIVE,
            meta_json=meta_json or {},
        )
        self.db.add(competitor)
        self.db.flush()

        if domains:
            for d in domains:
                domain_type = d.get("domain_type", "website")
                try:
                    dt = CIDomainType(domain_type)
                except ValueError:
                    dt = CIDomainType.WEBSITE

                dom = CICompetitorDomain(
                    org_id=org_id,
                    competitor_id=competitor.id,
                    domain=d["domain"],
                    domain_type=dt,
                )
                self.db.add(dom)

        self.db.commit()
        self.db.refresh(competitor)

        logger.info(
            f"CI_COMPETITOR_REGISTERED | org={org_id} | competitor={competitor.id} | "
            f"name={name} | domains={len(domains or [])}"
        )
        return competitor

    def list_competitors(
        self,
        org_id: UUID,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CICompetitor]:
        """List competitors for an org with optional status filter."""
        q = self.db.query(CICompetitor).filter(CICompetitor.org_id == org_id)

        if status:
            try:
                q = q.filter(CICompetitor.status == CICompetitorStatus(status))
            except ValueError:
                pass

        return q.order_by(CICompetitor.created_at.desc()).offset(offset).limit(limit).all()

    def get_competitor(self, org_id: UUID, competitor_id: UUID) -> Optional[CICompetitor]:
        """Get a single competitor by ID, scoped to org."""
        return (
            self.db.query(CICompetitor)
            .filter(CICompetitor.org_id == org_id, CICompetitor.id == competitor_id)
            .first()
        )

    def update_competitor(
        self,
        org_id: UUID,
        competitor_id: UUID,
        updates: Dict[str, Any],
    ) -> Optional[CICompetitor]:
        """Update competitor fields."""
        competitor = self.get_competitor(org_id, competitor_id)
        if not competitor:
            return None

        allowed_fields = {"name", "website_url", "logo_url", "notes", "status", "meta_json"}
        for key, value in updates.items():
            if key in allowed_fields:
                if key == "status":
                    try:
                        value = CICompetitorStatus(value)
                    except ValueError:
                        continue
                setattr(competitor, key, value)

        self.db.commit()
        self.db.refresh(competitor)
        logger.info(f"CI_COMPETITOR_UPDATED | org={org_id} | competitor={competitor_id}")
        return competitor

    def delete_competitor(self, org_id: UUID, competitor_id: UUID) -> bool:
        """Delete a competitor and cascade to domains + items."""
        competitor = self.get_competitor(org_id, competitor_id)
        if not competitor:
            return False

        self.db.delete(competitor)
        self.db.commit()
        logger.info(f"CI_COMPETITOR_DELETED | org={org_id} | competitor={competitor_id}")
        return True

    # ── Sources ───────────────────────────────────────────────────────────────

    def create_source(
        self,
        org_id: UUID,
        name: str,
        source_type: str,
        config_json: Optional[Dict] = None,
    ) -> CISource:
        """Create a new CI data source."""
        try:
            st = CISourceType(source_type)
        except ValueError:
            st = CISourceType.MANUAL

        source = CISource(
            org_id=org_id,
            name=name,
            source_type=st,
            config_json=config_json or {},
        )
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)
        logger.info(f"CI_SOURCE_CREATED | org={org_id} | source={source.id} | type={source_type}")
        return source

    def list_sources(self, org_id: UUID) -> List[CISource]:
        """List all sources for an org."""
        return (
            self.db.query(CISource)
            .filter(CISource.org_id == org_id)
            .order_by(CISource.created_at.desc())
            .all()
        )

    # ── Ingest Runs ───────────────────────────────────────────────────────────

    def start_ingest_run(self, org_id: UUID, source_id: UUID) -> CIIngestRun:
        """Start a new ingest run."""
        run = CIIngestRun(
            org_id=org_id,
            source_id=source_id,
            status=CIIngestStatus.RUNNING,
            started_at=datetime.utcnow(),
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        logger.info(f"CI_INGEST_START | org={org_id} | source={source_id} | run={run.id}")
        return run

    def finish_ingest_run(
        self,
        run: CIIngestRun,
        status: str = "succeeded",
        items_fetched: int = 0,
        items_upserted: int = 0,
        items_skipped: int = 0,
        error_count: int = 0,
        error_summary: Optional[Dict] = None,
    ) -> CIIngestRun:
        """Mark an ingest run as finished."""
        try:
            run.status = CIIngestStatus(status)
        except ValueError:
            run.status = CIIngestStatus.FAILED

        run.finished_at = datetime.utcnow()
        run.items_fetched = items_fetched
        run.items_upserted = items_upserted
        run.items_skipped = items_skipped
        run.error_count = error_count
        run.error_summary_json = error_summary

        if run.started_at:
            run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)

        self.db.commit()
        self.db.refresh(run)
        logger.info(
            f"CI_INGEST_FINISH | run={run.id} | status={status} | "
            f"fetched={items_fetched} | upserted={items_upserted} | errors={error_count}"
        )
        return run

    # ── Canonical Items ───────────────────────────────────────────────────────

    def upsert_canonical_item(
        self,
        org_id: UUID,
        competitor_id: UUID,
        item_type: str,
        external_id: str,
        title: Optional[str] = None,
        body_text: Optional[str] = None,
        url: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
        canonical_json: Optional[Dict] = None,
        raw_json: Optional[Dict] = None,
        source_id: Optional[UUID] = None,
        ingest_run_id: Optional[UUID] = None,
    ) -> CICanonicalItem:
        """Upsert a canonical item (insert or update on natural key).

        Natural key: (org_id, competitor_id, item_type, external_id).
        """
        try:
            it = CIItemType(item_type)
        except ValueError:
            it = CIItemType.AD

        existing = (
            self.db.query(CICanonicalItem)
            .filter(
                CICanonicalItem.org_id == org_id,
                CICanonicalItem.competitor_id == competitor_id,
                CICanonicalItem.item_type == it,
                CICanonicalItem.external_id == external_id,
            )
            .first()
        )

        now = datetime.utcnow()

        if existing:
            existing.title = title or existing.title
            existing.body_text = body_text or existing.body_text
            existing.url = url or existing.url
            if image_urls is not None:
                existing.image_urls_json = image_urls
            if canonical_json is not None:
                existing.canonical_json = canonical_json
            if raw_json is not None:
                existing.raw_json = raw_json
            existing.source_id = source_id or existing.source_id
            existing.ingest_run_id = ingest_run_id or existing.ingest_run_id
            existing.last_seen_at = now

            self.db.commit()
            self.db.refresh(existing)
            return existing

        item = CICanonicalItem(
            org_id=org_id,
            competitor_id=competitor_id,
            source_id=source_id,
            ingest_run_id=ingest_run_id,
            item_type=it,
            external_id=external_id,
            title=title,
            body_text=body_text,
            url=url,
            image_urls_json=image_urls or [],
            canonical_json=canonical_json or {},
            raw_json=raw_json or {},
            first_seen_at=now,
            last_seen_at=now,
        )
        self.db.add(item)
        self.db.commit()
        self.db.refresh(item)

        logger.info(
            f"CI_ITEM_UPSERTED | org={org_id} | competitor={competitor_id} | "
            f"type={item_type} | ext_id={external_id}"
        )
        return item

    def list_canonical_items(
        self,
        org_id: UUID,
        competitor_id: Optional[UUID] = None,
        item_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[CICanonicalItem]:
        """List canonical items with optional filters."""
        q = self.db.query(CICanonicalItem).filter(CICanonicalItem.org_id == org_id)

        if competitor_id:
            q = q.filter(CICanonicalItem.competitor_id == competitor_id)
        if item_type:
            try:
                q = q.filter(CICanonicalItem.item_type == CIItemType(item_type))
            except ValueError:
                pass

        return q.order_by(CICanonicalItem.last_seen_at.desc()).offset(offset).limit(limit).all()

    def get_canonical_item(self, org_id: UUID, item_id: UUID) -> Optional[CICanonicalItem]:
        """Get a single canonical item by ID, scoped to org."""
        return (
            self.db.query(CICanonicalItem)
            .filter(CICanonicalItem.org_id == org_id, CICanonicalItem.id == item_id)
            .first()
        )

    # ── Vector-powered search (delegates to CIVectorIndex) ────────────────────

    def index_item(self, item: CICanonicalItem) -> str:
        """Index a canonical item in the vector store. Returns embedding_id."""
        from backend.src.ci.vector_index import CIVectorIndex

        idx = CIVectorIndex()

        text_parts = []
        if item.title:
            text_parts.append(item.title)
        if item.body_text:
            text_parts.append(item.body_text)
        text = " ".join(text_parts) if text_parts else "(empty)"

        metadata = {
            "org_id": str(item.org_id),
            "competitor_id": str(item.competitor_id),
            "item_type": item.item_type.value if hasattr(item.item_type, "value") else str(item.item_type),
        }
        if item.external_id:
            metadata["external_id"] = item.external_id
        if item.url:
            metadata["url"] = item.url

        embedding_id = idx.upsert_item(str(item.id), text, metadata)

        item.embedding_id = embedding_id
        self.db.commit()

        return embedding_id

    def search_text(
        self,
        org_id: UUID,
        query: str,
        item_types: Optional[List[str]] = None,
        competitor_ids: Optional[List[UUID]] = None,
        n_results: int = 10,
    ) -> List[Dict]:
        """Semantic search across CI items.

        Returns list of {item_id, document, metadata, distance} dicts.
        """
        from backend.src.ci.vector_index import CIVectorIndex

        idx = CIVectorIndex()

        where_filter: Dict[str, Any] = {"org_id": str(org_id)}

        # ChromaDB $and filter for multiple conditions
        conditions = [{"org_id": str(org_id)}]

        if item_types and len(item_types) == 1:
            conditions.append({"item_type": item_types[0]})
        elif item_types and len(item_types) > 1:
            conditions.append({"item_type": {"$in": item_types}})

        if competitor_ids and len(competitor_ids) == 1:
            conditions.append({"competitor_id": str(competitor_ids[0])})
        elif competitor_ids and len(competitor_ids) > 1:
            conditions.append({"competitor_id": {"$in": [str(c) for c in competitor_ids]}})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        results = idx.search_text(query, n_results=n_results, where=where_filter)

        logger.info(
            f"CI_SEARCH | org={org_id} | query_len={len(query)} | "
            f"types={item_types} | results={len(results)}"
        )
        return results

    def find_similar(
        self,
        org_id: UUID,
        item_id: UUID,
        n_results: int = 5,
    ) -> List[Dict]:
        """Find items similar to a given item."""
        from backend.src.ci.vector_index import CIVectorIndex

        idx = CIVectorIndex()
        where_filter = {"org_id": str(org_id)}

        results = idx.find_similar(str(item_id), n_results=n_results, where=where_filter)
        logger.info(f"CI_SIMILAR | org={org_id} | item={item_id} | results={len(results)}")
        return results
