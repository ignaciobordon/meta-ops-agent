"""Tests for the Web Intelligence Engine — 30+ tests across all blocks."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────────

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Acme Corp - Best Widget Store</title></head>
<body>
<header>
  <nav><a href="/">Home</a> <a href="/about">About</a> <a href="/pricing">Pricing</a></nav>
</header>
<section class="hero-banner">
  <h1>The #1 Widget Platform for Teams</h1>
  <p>Trusted by 10,000+ companies worldwide.</p>
  <button>Get Started Free</button>
</section>
<main>
  <h2>Features</h2>
  <ul>
    <li>Real-time collaboration</li>
    <li>Advanced analytics</li>
    <li>24/7 support</li>
  </ul>
  <section class="pricing" id="plans">
    <h2>Simple Pricing</h2>
    <div class="plan-card">
      <h3>Starter</h3>
      <p>$29/month</p>
      <p>Perfect for small teams</p>
      <a href="/signup" class="btn-cta">Start Free Trial</a>
    </div>
    <div class="plan-card">
      <h3>Pro</h3>
      <p>$99/month</p>
      <p>For growing businesses</p>
      <a href="/signup?plan=pro" class="btn-cta">Buy Now</a>
    </div>
  </section>
  <section id="offers">
    <h2>Limited Time Offer</h2>
    <p>Save 20% off annual plans! Use code SAVE20.</p>
    <p>30-day money-back guarantee on all plans.</p>
  </section>
</main>
<footer>
  <p>&copy; 2026 Acme Corp</p>
  <a href="/privacy">Privacy</a>
</footer>
</body>
</html>
"""

SAMPLE_HTML_V2 = """
<!DOCTYPE html>
<html>
<head><title>Acme Corp - Best Widget Store</title></head>
<body>
<header>
  <nav><a href="/">Home</a> <a href="/about">About</a> <a href="/pricing">Pricing</a> <a href="/blog">Blog</a></nav>
</header>
<section class="hero-banner">
  <h1>The #1 Widget Platform for Modern Teams</h1>
  <p>Trusted by 15,000+ companies worldwide.</p>
  <button>Try It Free</button>
</section>
<main>
  <h2>Features</h2>
  <ul>
    <li>Real-time collaboration</li>
    <li>Advanced analytics</li>
    <li>24/7 support</li>
    <li>AI-powered insights</li>
  </ul>
  <section class="pricing" id="plans">
    <h2>Simple Pricing</h2>
    <div class="plan-card">
      <h3>Starter</h3>
      <p>$39/month</p>
      <p>Perfect for small teams</p>
      <a href="/signup" class="btn-cta">Start Free Trial</a>
    </div>
    <div class="plan-card">
      <h3>Pro</h3>
      <p>$119/month</p>
      <p>For growing businesses</p>
      <a href="/signup?plan=pro" class="btn-cta">Subscribe Now</a>
    </div>
  </section>
  <section id="offers">
    <h2>Black Friday Special</h2>
    <p>50% off first 3 months! Limited time.</p>
    <p>60-day money-back guarantee on all plans.</p>
  </section>
</main>
<footer>
  <p>&copy; 2026 Acme Corp</p>
  <a href="/privacy">Privacy</a>
</footer>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 1: URL NORMALIZATION + LINK EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestURLNormalization:

    def test_strips_utm_params(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        url = "https://example.com/page?utm_source=google&utm_medium=cpc&id=123"
        result = normalize_url(url)
        assert "utm_source" not in result
        assert "utm_medium" not in result
        assert "id=123" in result

    def test_strips_fbclid(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        url = "https://example.com/page?fbclid=abc123&valid=1"
        result = normalize_url(url)
        assert "fbclid" not in result
        assert "valid=1" in result

    def test_lowercase_host(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        result = normalize_url("https://EXAMPLE.COM/Page")
        assert "example.com" in result

    def test_strips_fragment(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        result = normalize_url("https://example.com/page#section")
        assert "#" not in result

    def test_trailing_slash_normalized(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        a = normalize_url("https://example.com/page/")
        b = normalize_url("https://example.com/page")
        assert a == b

    def test_root_path(self):
        from src.engines.web_intelligence.crawler_service import normalize_url
        result = normalize_url("https://example.com")
        assert result.endswith("/")


class TestLinkExtraction:

    def test_extracts_links(self):
        from src.engines.web_intelligence.crawler_service import extract_links
        links = extract_links(SAMPLE_HTML, "https://acme.com")
        assert len(links) >= 4  # /, /about, /pricing, /signup, etc.

    def test_resolves_relative_links(self):
        from src.engines.web_intelligence.crawler_service import extract_links
        links = extract_links('<a href="/about">About</a>', "https://acme.com/page")
        assert any("acme.com/about" in l for l in links)

    def test_ignores_javascript_links(self):
        from src.engines.web_intelligence.crawler_service import extract_links
        links = extract_links(
            '<a href="javascript:void(0)">Click</a><a href="/real">Real</a>',
            "https://acme.com",
        )
        assert len(links) == 1
        assert "real" in links[0]

    def test_ignores_mailto(self):
        from src.engines.web_intelligence.crawler_service import extract_links
        links = extract_links(
            '<a href="mailto:x@y.com">Email</a><a href="/ok">OK</a>',
            "https://acme.com",
        )
        assert len(links) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 2: EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractors:

    def test_extract_headlines(self):
        from src.engines.web_intelligence.extractors import extract_headlines
        headlines = extract_headlines(SAMPLE_HTML)
        assert any("Widget Platform" in h for h in headlines)
        assert any("Features" in h for h in headlines)

    def test_extract_offers(self):
        from src.engines.web_intelligence.extractors import extract_offers
        offers = extract_offers(SAMPLE_HTML)
        assert any("20%" in o for o in offers)

    def test_extract_pricing_blocks(self):
        from src.engines.web_intelligence.extractors import extract_pricing_blocks
        prices = extract_pricing_blocks(SAMPLE_HTML)
        assert any("$29" in p for p in prices)
        assert any("$99" in p for p in prices)

    def test_extract_cta_phrases(self):
        from src.engines.web_intelligence.extractors import extract_cta_phrases
        ctas = extract_cta_phrases(SAMPLE_HTML)
        assert any("free" in c.lower() for c in ctas)

    def test_extract_guarantees(self):
        from src.engines.web_intelligence.extractors import extract_guarantees
        guarantees = extract_guarantees(SAMPLE_HTML)
        assert any("money-back" in g.lower() for g in guarantees)

    def test_extract_product_names(self):
        from src.engines.web_intelligence.extractors import extract_product_names
        names = extract_product_names(SAMPLE_HTML)
        assert any("Acme" in n for n in names)

    def test_extract_hero_sections(self):
        from src.engines.web_intelligence.extractors import extract_hero_sections
        heroes = extract_hero_sections(SAMPLE_HTML)
        assert len(heroes) >= 1
        assert any("Widget" in h for h in heroes)

    def test_extract_structured_lists(self):
        from src.engines.web_intelligence.extractors import extract_structured_lists
        lists = extract_structured_lists(SAMPLE_HTML)
        assert len(lists) >= 1
        assert any("Real-time collaboration" in item for lst in lists for item in lst)

    def test_extract_semantic_keywords(self):
        from src.engines.web_intelligence.extractors import extract_semantic_keywords
        kws = extract_semantic_keywords(SAMPLE_HTML)
        assert len(kws) > 0
        # Common words from the page should appear

    def test_extract_all_aggregate(self):
        from src.engines.web_intelligence.extractors import extract_all
        result = extract_all(SAMPLE_HTML, "https://acme.com")
        assert result["url"] == "https://acme.com"
        assert len(result["headlines"]) > 0
        assert len(result["content_hash"]) > 0

    def test_tolerates_broken_html(self):
        from src.engines.web_intelligence.extractors import extract_headlines
        broken = "<h1>Title<h2>Subtitle<p>paragraph"
        headlines = extract_headlines(broken)
        assert "Title" in headlines[0]


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 3: SIGNALS ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestSignalsEngine:

    def _make_page(self, url, **kwargs):
        from src.engines.web_intelligence.models import ExtractedPageData
        from src.engines.web_intelligence.fingerprint import content_hash
        defaults = {
            "url": url,
            "content_hash": content_hash(str(kwargs)),
            "title": url,
            "headlines": [],
            "offers": [],
            "pricing_blocks": [],
            "cta_phrases": [],
        }
        defaults.update(kwargs)
        return ExtractedPageData(**defaults)

    def test_detects_new_pages(self):
        from src.engines.web_intelligence.signals_engine import detect_signals
        from src.engines.web_intelligence.models import SignalType

        current = {"/new": self._make_page("/new")}
        previous: dict = {}
        signals = detect_signals(current, previous)
        assert any(s.type == SignalType.NEW_PAGES for s in signals)

    def test_detects_removed_pages(self):
        from src.engines.web_intelligence.signals_engine import detect_signals
        from src.engines.web_intelligence.models import SignalType

        current: dict = {}
        previous = {"/old": self._make_page("/old")}
        signals = detect_signals(current, previous)
        assert any(s.type == SignalType.REMOVED_PAGES for s in signals)

    def test_detects_headline_changes(self):
        from src.engines.web_intelligence.signals_engine import detect_signals
        from src.engines.web_intelligence.models import SignalType

        prev = self._make_page("/page", headlines=["Old Title"], content_hash="aaa")
        curr = self._make_page("/page", headlines=["New Title"], content_hash="bbb")
        signals = detect_signals({"/page": curr}, {"/page": prev})
        assert any(s.type == SignalType.HEADLINE_CHANGES for s in signals)

    def test_no_signals_when_identical(self):
        from src.engines.web_intelligence.signals_engine import detect_signals

        page = self._make_page("/page", headlines=["Same"])
        signals = detect_signals({"/page": page}, {"/page": page})
        assert len(signals) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 4: DIFF ENGINE
# ═══════════════════════════════════════════════════════════════════════════════


class TestDiffEngine:

    def test_text_diff_detects_changes(self):
        from src.engines.web_intelligence.diff_engine import text_diff
        diffs = text_diff(SAMPLE_HTML, SAMPLE_HTML_V2)
        assert len(diffs) > 0  # There are text differences

    def test_text_diff_identical(self):
        from src.engines.web_intelligence.diff_engine import text_diff
        diffs = text_diff(SAMPLE_HTML, SAMPLE_HTML)
        assert len(diffs) == 0

    def test_pricing_diff_detects_price_change(self):
        from src.engines.web_intelligence.diff_engine import pricing_diff
        result = pricing_diff(SAMPLE_HTML, SAMPLE_HTML_V2)
        assert result["changed"] is True
        # $29 → $39 and $99 → $119

    def test_cta_diff_detects_change(self):
        from src.engines.web_intelligence.diff_engine import cta_diff
        result = cta_diff(SAMPLE_HTML, SAMPLE_HTML_V2)
        # "Buy Now" changed to "Subscribe Now", "Get Started Free" → "Try It Free"
        assert result["changed"] is True

    def test_section_diff(self):
        from src.engines.web_intelligence.diff_engine import section_diff
        result = section_diff(SAMPLE_HTML, SAMPLE_HTML_V2)
        # At least header or main should be different
        assert len(result) > 0

    def test_full_diff_returns_all_sections(self):
        from src.engines.web_intelligence.diff_engine import full_diff
        result = full_diff(SAMPLE_HTML, SAMPLE_HTML_V2)
        assert "text_diff" in result
        assert "section_diff" in result
        assert "pricing_diff" in result
        assert "cta_diff" in result


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 5: FINGERPRINTING
# ═══════════════════════════════════════════════════════════════════════════════


class TestFingerprint:

    def test_identical_html_same_fingerprint(self):
        from src.engines.web_intelligence.fingerprint import page_fingerprint
        f1 = page_fingerprint(SAMPLE_HTML)
        f2 = page_fingerprint(SAMPLE_HTML)
        assert f1 == f2

    def test_different_html_different_fingerprint(self):
        from src.engines.web_intelligence.fingerprint import page_fingerprint
        f1 = page_fingerprint(SAMPLE_HTML)
        f2 = page_fingerprint(SAMPLE_HTML_V2)
        assert f1 != f2

    def test_content_hash_deterministic(self):
        from src.engines.web_intelligence.fingerprint import content_hash
        h1 = content_hash("test content")
        h2 = content_hash("test content")
        assert h1 == h2
        assert len(h1) == 32

    def test_ignores_tracking_params_in_text(self):
        from src.engines.web_intelligence.fingerprint import text_fingerprint
        html1 = "<p>Hello world utm_source=google</p>"
        html2 = "<p>Hello world utm_source=facebook</p>"
        f1 = text_fingerprint(html1)
        f2 = text_fingerprint(html2)
        assert f1 == f2


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 6: SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════════


class TestScheduler:

    def test_never_crawled_is_due(self):
        from src.engines.web_intelligence.scheduler import get_due_targets
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        t = CrawlTarget(domain="example.com", tier=CrawlTier.A, last_crawl_at=None)
        due = get_due_targets([t])
        assert len(due) == 1

    def test_recently_crawled_not_due(self):
        from src.engines.web_intelligence.scheduler import get_due_targets
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        now = datetime.utcnow()
        t = CrawlTarget(
            domain="example.com",
            tier=CrawlTier.A,
            last_crawl_at=now - timedelta(hours=1),
        )
        due = get_due_targets([t], now)
        assert len(due) == 0

    def test_stale_crawl_is_due(self):
        from src.engines.web_intelligence.scheduler import get_due_targets
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        now = datetime.utcnow()
        t = CrawlTarget(
            domain="example.com",
            tier=CrawlTier.A,
            last_crawl_at=now - timedelta(days=2),
        )
        due = get_due_targets([t], now)
        assert len(due) == 1

    def test_scheduler_tick(self):
        from src.engines.web_intelligence.scheduler import Scheduler
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        s = Scheduler()
        s.add_target(CrawlTarget(domain="a.com", tier=CrawlTier.A))
        due = s.tick()
        assert len(due) == 1

    def test_scheduler_mark_completed(self):
        from src.engines.web_intelligence.scheduler import Scheduler
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        s = Scheduler()
        s.add_target(CrawlTarget(domain="a.com", tier=CrawlTier.A))
        s.mark_completed("a.com")
        # Should not be due immediately after
        due = s.tick()
        assert len(due) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 7: POLITENESS
# ═══════════════════════════════════════════════════════════════════════════════


class TestPoliteness:

    def test_random_headers_has_user_agent(self):
        from src.engines.web_intelligence.politeness import random_headers
        headers = random_headers()
        assert "User-Agent" in headers
        assert len(headers["User-Agent"]) > 10

    def test_random_headers_vary(self):
        from src.engines.web_intelligence.politeness import random_headers
        samples = [random_headers()["User-Agent"] for _ in range(20)]
        assert len(set(samples)) > 1  # At least 2 different UAs


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 9: STORAGE
# ═══════════════════════════════════════════════════════════════════════════════


class TestStorage:

    def test_store_and_load(self):
        from src.engines.web_intelligence.storage import InMemoryStore
        from src.engines.web_intelligence.models import ExtractedPageData

        store = InMemoryStore()
        data = ExtractedPageData(url="/test", content_hash="abc123")
        store.store_page("/test", "<html>content</html>", data)

        html, loaded = store.load_last_page("/test")
        assert html == "<html>content</html>"
        assert loaded is not None
        assert loaded.content_hash == "abc123"

    def test_load_nonexistent_returns_none(self):
        from src.engines.web_intelligence.storage import InMemoryStore
        store = InMemoryStore()
        html, data = store.load_last_page("/nope")
        assert html is None
        assert data is None

    def test_version_tracking(self):
        from src.engines.web_intelligence.storage import InMemoryStore
        from src.engines.web_intelligence.models import ExtractedPageData

        store = InMemoryStore()
        d1 = ExtractedPageData(url="/p", content_hash="v1")
        d2 = ExtractedPageData(url="/p", content_hash="v2")
        store.store_page("/p", "<v1>", d1)
        store.store_page("/p", "<v2>", d2)

        assert store.version_count("/p") == 2
        html, latest = store.load_last_page("/p")
        assert latest.content_hash == "v2"

        html_prev, prev = store.load_previous_page("/p")
        assert prev.content_hash == "v1"

    def test_store_signals(self):
        from src.engines.web_intelligence.storage import InMemoryStore
        from src.engines.web_intelligence.models import SignalEvent, SignalType

        store = InMemoryStore()
        sig = SignalEvent(type=SignalType.NEW_PAGES, url="/new")
        store.store_signals("example.com", [sig])
        loaded = store.get_signals("example.com")
        assert len(loaded) == 1
        assert loaded[0].type == SignalType.NEW_PAGES


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCK 10: MODELS SERIALIZATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestModels:

    def test_crawl_report_json_serializable(self):
        from src.engines.web_intelligence.models import CrawlReport
        r = CrawlReport(domain="test.com", pages_crawled=5, errors=1, duration_seconds=3.14)
        data = r.model_dump(mode="json")
        assert data["domain"] == "test.com"
        assert data["pages_crawled"] == 5

    def test_signal_event_json_serializable(self):
        from src.engines.web_intelligence.models import SignalEvent, SignalType
        s = SignalEvent(type=SignalType.PRICING_CHANGES, url="/pricing", old_value="$29", new_value="$39")
        data = s.model_dump(mode="json")
        assert data["type"] == "pricing_changes"
        assert data["old_value"] == "$29"

    def test_extracted_page_data_json(self):
        from src.engines.web_intelligence.models import ExtractedPageData
        p = ExtractedPageData(url="/test", content_hash="abc", headlines=["Test"])
        data = p.model_dump(mode="json")
        assert data["headlines"] == ["Test"]

    def test_crawl_target_json(self):
        from src.engines.web_intelligence.models import CrawlTarget, CrawlTier
        t = CrawlTarget(domain="example.com", tier=CrawlTier.A)
        data = t.model_dump(mode="json")
        assert data["tier"] == "A"
