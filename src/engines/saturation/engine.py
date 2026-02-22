"""
CP4 — Saturation Engine
Detects creative fatigue from Meta Ads daily performance data.
Computes a 0-100 saturation score per creative using:
  - Frequency (35%): audience overexposure
  - CTR decay (35%): engagement decline vs peak
  - CPM inflation (30%): cost increase vs baseline
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List

import pandas as pd

from src.schemas.saturation import (
    CreativeSaturation, OpportunityGap, RecommendationType, SaturationReport,
)
from src.utils.logging_config import logger, get_trace_id

# Spanish column names from Meta Ads Manager export → internal names
_COLUMN_MAP = {
    "Nombre del anuncio": "ad_name",
    "Día": "date",
    "Nombre de la campaña": "campaign_name",
    "Importe gastado (USD)": "spend",
    "Impresiones": "impressions",
    "Alcance": "reach",
    "Frecuencia": "frequency",
    "Clics en el enlace": "link_clicks",
    "CTR (todos)": "ctr",
    "CPM (costo por mil impresiones)": "cpm",
    "Resultados": "results",
    "Costo por resultado": "cost_per_result",
}

# Weights for composite saturation score
_WEIGHTS = {"frequency": 0.35, "ctr_decay": 0.35, "cpm_inflation": 0.30}

# Thresholds for recommendation buckets
_THRESHOLDS = {"keep": 30, "monitor": 55, "refresh": 75}


class SaturationEngine:

    def load_csv(self, path: str) -> pd.DataFrame:
        """Load a Meta Ads Manager daily breakdown CSV and return a clean DataFrame."""
        raw = pd.read_csv(path)

        # Keep only columns we care about (some may be missing — that's OK)
        keep = {k: v for k, v in _COLUMN_MAP.items() if k in raw.columns}
        df = raw[list(keep.keys())].rename(columns=keep)

        # Replace "-" and empty strings with NaN, then coerce numerics
        df.replace({"-": None, "": None}, inplace=True)
        for col in ("spend", "impressions", "reach", "frequency",
                    "link_clicks", "ctr", "cpm", "results", "cost_per_result"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        # Drop rows with no ad name or no date
        df = df.dropna(subset=["ad_name", "date"])
        df = df[df["ad_name"].str.strip() != ""]

        # Aggregate over age/gender segments → one row per ad per day
        agg = {
            "spend": "sum",
            "impressions": "sum",
            "link_clicks": "sum",
        }
        # Frequency, CTR, CPM: weighted average by impressions
        # Compute them after aggregation
        df_agg = df.groupby(["ad_name", "date"], as_index=False).agg(agg)

        # Weighted metrics: merge back and compute
        df["_freq_w"] = df["frequency"] * df["impressions"]
        df["_ctr_w"] = df["ctr"] * df["impressions"]
        df["_cpm_w"] = df["cpm"] * df["impressions"]

        weighted = df.groupby(["ad_name", "date"], as_index=False).agg(
            _freq_w=("_freq_w", "sum"),
            _ctr_w=("_ctr_w", "sum"),
            _cpm_w=("_cpm_w", "sum"),
            _imp_total=("impressions", "sum"),
        )
        weighted["frequency"] = weighted["_freq_w"] / weighted["_imp_total"].replace(0, float("nan"))
        weighted["ctr"] = weighted["_ctr_w"] / weighted["_imp_total"].replace(0, float("nan"))
        weighted["cpm"] = weighted["_cpm_w"] / weighted["_imp_total"].replace(0, float("nan"))

        df_agg = df_agg.merge(
            weighted[["ad_name", "date", "frequency", "ctr", "cpm"]],
            on=["ad_name", "date"],
            how="left",
        )
        df_agg.sort_values(["ad_name", "date"], inplace=True)
        df_agg.reset_index(drop=True, inplace=True)

        logger.info(
            f"SATURATION_CSV_LOADED | rows={len(df_agg)} "
            f"| ads={df_agg['ad_name'].nunique()} "
            f"| path={os.path.basename(path)}"
        )
        return df_agg

    def analyze(self, df: pd.DataFrame) -> SaturationReport:
        trace_id = get_trace_id()
        logger.info(f"SATURATION_ANALYSIS_STARTED | trace_id={trace_id} | ads={df['ad_name'].nunique()}")

        total_spend = df["spend"].sum()
        total_impressions = int(df["impressions"].sum())
        df["date"] = pd.to_datetime(df["date"])
        date_start = df["date"].min().date()
        date_end = df["date"].max().date()

        creatives: List[CreativeSaturation] = []
        for ad_name, ad_df in df.groupby("ad_name"):
            cs = self._score_creative(str(ad_name), ad_df.copy(), total_spend)
            creatives.append(cs)

        creatives.sort(key=lambda c: c.saturation_score, reverse=True)

        most_saturated = creatives[0].ad_name if creatives else ""

        # Opportunity gaps = 3 lowest saturation with enough data (>= 7 days)
        candidates = [c for c in sorted(creatives, key=lambda c: c.saturation_score) if c.days_active >= 7]
        opportunity_gaps = [
            OpportunityGap(
                rank=i + 1,
                ad_name=c.ad_name,
                saturation_score=c.saturation_score,
                rationale=self._opportunity_rationale(c),
            )
            for i, c in enumerate(candidates[:3])
        ]

        report = SaturationReport(
            date_range_start=date_start,
            date_range_end=date_end,
            total_spend_analyzed=round(total_spend, 2),
            total_impressions_analyzed=total_impressions,
            creatives=creatives,
            opportunity_gaps=opportunity_gaps,
            most_saturated=most_saturated,
        )

        logger.info(
            f"SATURATION_ANALYSIS_DONE | most_saturated={most_saturated} "
            f"| score={creatives[0].saturation_score if creatives else 0}"
        )
        return report

    # ── Private ───────────────────────────────────────────────────────────────

    def _score_creative(
        self, ad_name: str, ad_df: pd.DataFrame, total_spend: float
    ) -> CreativeSaturation:
        ad_df = ad_df.sort_values("date").reset_index(drop=True)
        n = len(ad_df)

        # Split into baseline (first third) and recent (last third)
        window = max(1, n // 3)
        baseline_df = ad_df.head(window)
        recent_df = ad_df.tail(window)

        def wavg(sub: pd.DataFrame, col: str) -> float:
            imp = sub["impressions"].fillna(0)
            vals = sub[col].fillna(0)
            total = imp.sum()
            return float((vals * imp).sum() / total) if total > 0 else 0.0

        recent_freq = wavg(recent_df, "frequency")
        baseline_cpm = wavg(baseline_df, "cpm")
        recent_cpm = wavg(recent_df, "cpm")
        recent_ctr = wavg(recent_df, "ctr")
        peak_ctr = float(ad_df["ctr"].max()) if ad_df["ctr"].notna().any() else 0.0

        # 1. Frequency score: 1.0 → 0, 2.0 → 50, 3.0 → 100
        freq_score = min(100.0, max(0.0, (recent_freq - 1.0) / 2.0 * 100))

        # 2. CTR decay: how far has CTR fallen from peak
        if peak_ctr > 0:
            ctr_decay_score = min(100.0, max(0.0, (peak_ctr - recent_ctr) / peak_ctr * 100))
        else:
            ctr_decay_score = 0.0

        # 3. CPM inflation: how much has CPM risen from baseline
        if baseline_cpm > 0:
            cpm_inflation_score = min(100.0, max(0.0, (recent_cpm - baseline_cpm) / baseline_cpm * 100))
        else:
            cpm_inflation_score = 0.0

        saturation_score = (
            freq_score * _WEIGHTS["frequency"]
            + ctr_decay_score * _WEIGHTS["ctr_decay"]
            + cpm_inflation_score * _WEIGHTS["cpm_inflation"]
        )

        total_spend_ad = float(ad_df["spend"].sum())
        spend_share = (total_spend_ad / total_spend * 100) if total_spend > 0 else 0.0

        recommendation: RecommendationType
        if saturation_score <= _THRESHOLDS["keep"]:
            recommendation = "keep"
        elif saturation_score <= _THRESHOLDS["monitor"]:
            recommendation = "monitor"
        elif saturation_score <= _THRESHOLDS["refresh"]:
            recommendation = "refresh"
        else:
            recommendation = "kill"

        return CreativeSaturation(
            ad_name=ad_name,
            saturation_score=round(saturation_score, 1),
            frequency_score=round(freq_score, 1),
            ctr_decay_score=round(ctr_decay_score, 1),
            cpm_inflation_score=round(cpm_inflation_score, 1),
            spend_share_pct=round(spend_share, 2),
            total_spend=round(total_spend_ad, 2),
            total_impressions=int(ad_df["impressions"].sum()),
            days_active=n,
            avg_frequency_recent=round(recent_freq, 3),
            ctr_recent=round(recent_ctr, 5),
            ctr_peak=round(peak_ctr, 5),
            cpm_recent=round(recent_cpm, 3),
            cpm_baseline=round(baseline_cpm, 3),
            recommendation=recommendation,
        )

    def _opportunity_rationale(self, c: CreativeSaturation) -> str:
        parts = []
        if c.frequency_score < 20:
            parts.append(f"low audience fatigue (freq {c.avg_frequency_recent:.2f})")
        if c.ctr_decay_score < 20:
            parts.append(f"CTR holding near peak ({c.ctr_recent:.2f}%)")
        if c.cpm_inflation_score < 20:
            parts.append(f"CPM stable ({c.cpm_recent:.2f})")
        if not parts:
            parts.append(f"saturation score {c.saturation_score}/100")
        return "Fresh creative: " + ", ".join(parts) + "."
