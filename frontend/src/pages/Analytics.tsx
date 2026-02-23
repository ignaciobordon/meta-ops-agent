/**
 * Analytics Panel — smart bucketed chart, KPIs with trends, sortable table, insights.
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import { FileDown, AlertTriangle } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import {
  analyticsApi,
  metaApi,
  PerformanceSummary,
  MetricsBucket,
  MetaAdAccount,
  TopCampaign,
  InsightItem,
} from '../services/api';
import { fmt$, fmtN, trendArrow, trendClass, DATE_PRESETS } from '../utils/formatting';
import { downloadBlob } from '../utils/download';
import './Analytics.css';

/* ── Metric selector for chart ─────────────────────────────────────────────── */

type ChartMetric = 'spend' | 'clicks' | 'ctr' | 'cpc' | 'impressions';

const CHART_METRICS: { key: ChartMetric; label: string; format: (v: number) => string }[] = [
  { key: 'spend', label: 'Spend', format: (v) => fmt$(v) },
  { key: 'clicks', label: 'Clicks', format: (v) => fmtN(v) },
  { key: 'ctr', label: 'CTR', format: (v) => `${v.toFixed(2)}%` },
  { key: 'cpc', label: 'CPC', format: (v) => `$${v.toFixed(2)}` },
  { key: 'impressions', label: 'Impressions', format: (v) => fmtN(v) },
];

/* ── Sort helpers ──────────────────────────────────────────────────────────── */

type SortField = keyof TopCampaign;
type SortDir = 'asc' | 'desc';

/* ── Y-axis tick helper ──────────────────────────────────────────────────── */

function yTicks(max: number): number[] {
  if (max <= 0) return [0];
  const step = max / 3;
  return [max, step * 2, step, 0];
}

/* ── Main component ──────────────────────────────────────────────────────── */

export default function Analytics() {
  const { t } = useLanguage();

  // Data state
  const [summary, setSummary] = useState<PerformanceSummary | null>(null);
  const [buckets, setBuckets] = useState<MetricsBucket[]>([]);
  const [bucketType, setBucketType] = useState<string>('daily');
  const [campaigns, setCampaigns] = useState<TopCampaign[]>([]);
  const [insights, setInsights] = useState<InsightItem[]>([]);
  const [loading, setLoading] = useState(true);

  // UI state
  const [activePreset, setActivePreset] = useState('30d');
  const [days, setDays] = useState(30);
  const [customSince, setCustomSince] = useState('');
  const [customUntil, setCustomUntil] = useState('');
  const [showCustom, setShowCustom] = useState(false);
  const [chartMetric, setChartMetric] = useState<ChartMetric>('spend');
  const [sortField, setSortField] = useState<SortField>('spend');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingXlsx, setExportingXlsx] = useState(false);

  // Account selector for currency filtering
  const [adAccounts, setAdAccounts] = useState<MetaAdAccount[]>([]);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');

  // Chart width measurement
  const chartRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(0);

  useEffect(() => {
    const el = chartRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setChartWidth(entry.contentRect.width);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  /* ── Fetch ad accounts on mount ─────────────────────────────────────────── */

  useEffect(() => {
    metaApi.listAdAccounts().then(res => {
      setAdAccounts(res.data || []);
    }).catch(() => {});
  }, []);

  /* ── Data fetching ───────────────────────────────────────────────────────── */

  const fetchData = useCallback(async (daysVal: number, since?: string, until?: string, accId?: string) => {
    setLoading(true);
    try {
      const p = since
        ? { days: undefined as number | undefined, since, until }
        : { days: daysVal, since: undefined as string | undefined, until: undefined as string | undefined };

      const aid = accId || undefined;

      const [sRes, mRes, tcRes, iRes] = await Promise.allSettled([
        analyticsApi.getSummary(p.days, p.since, p.until, aid),
        analyticsApi.getMetricsOverTime(p.days, p.since, p.until, aid),
        analyticsApi.getTopCampaigns(p.days, 20, p.since, p.until, aid),
        analyticsApi.getInsights(p.days, p.since, p.until, aid),
      ]);

      if (sRes.status === 'fulfilled') setSummary(sRes.value.data);
      if (mRes.status === 'fulfilled') {
        setBuckets(mRes.value.data.buckets);
        setBucketType(mRes.value.data.bucket_type);
      }
      if (tcRes.status === 'fulfilled') setCampaigns(tcRes.value.data);
      if (iRes.status === 'fulfilled') setInsights(iRes.value.data.insights);
    } catch {
      // Fallback for unexpected errors
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData(days);
  }, []);

  const handlePreset = (preset: { label: string; days: number }) => {
    setShowCustom(false);
    setActivePreset(preset.label);
    setDays(preset.days);
    fetchData(preset.days, undefined, undefined, selectedAccountId);
  };

  const handleCustomApply = () => {
    if (!customSince) return;
    setActivePreset('custom');
    fetchData(0, customSince, customUntil || undefined, selectedAccountId);
  };

  const handleAccountChange = (accId: string) => {
    setSelectedAccountId(accId);
    if (activePreset === 'custom' && customSince) {
      fetchData(0, customSince, customUntil || undefined, accId);
    } else {
      fetchData(days, undefined, undefined, accId);
    }
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      const p = customSince ? { days: undefined, since: customSince, until: customUntil || undefined } : { days, since: undefined, until: undefined };
      const res = await analyticsApi.exportPdf(p.days, p.since, p.until, selectedAccountId || undefined);
      downloadBlob(res.data, 'analytics_report.pdf', 'application/pdf');
    } catch (err) {
      console.error('Failed to export PDF:', err);
    } finally {
      setExportingPdf(false);
    }
  };

  const handleExportXlsx = async () => {
    try {
      setExportingXlsx(true);
      const p = customSince ? { days: undefined, since: customSince, until: customUntil || undefined } : { days, since: undefined, until: undefined };
      const res = await analyticsApi.exportXlsx(p.days, p.since, p.until, selectedAccountId || undefined);
      downloadBlob(res.data, 'analytics_report.xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    } catch (err) {
      console.error('Failed to export XLSX:', err);
    } finally {
      setExportingXlsx(false);
    }
  };

  /* ── Table sorting ──────────────────────────────────────────────────────── */

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('desc');
    }
  };

  const sortedCampaigns = [...campaigns].sort((a, b) => {
    const av = a[sortField];
    const bv = b[sortField];
    if (typeof av === 'number' && typeof bv === 'number') {
      return sortDir === 'asc' ? av - bv : bv - av;
    }
    const as = String(av).toLowerCase();
    const bs = String(bv).toLowerCase();
    return sortDir === 'asc' ? as.localeCompare(bs) : bs.localeCompare(as);
  });

  const sortIcon = (field: SortField) => {
    if (sortField !== field) return ' \u2195';
    return sortDir === 'asc' ? ' \u2191' : ' \u2193';
  };

  /* ── Chart computations ─────────────────────────────────────────────────── */

  const metricConf = CHART_METRICS.find(m => m.key === chartMetric)!;
  const chartValues = buckets.map(b => b[chartMetric] as number);
  const maxVal = Math.max(...chartValues, 0.01);
  const barGap = 3;
  const yAxisWidth = 50;
  const availableWidth = chartWidth - yAxisWidth;
  const barWidth = buckets.length > 0
    ? Math.max(4, Math.min(40, (availableWidth - barGap * buckets.length) / buckets.length))
    : 20;
  const labelSkip = buckets.length > 0 ? Math.max(1, Math.ceil(50 / barWidth)) : 1;
  const ticks = yTicks(maxVal);

  // Currency helpers
  const currency = summary?.currency || 'USD';

  /* ── Loading state ──────────────────────────────────────────────────────── */

  if (loading && !summary) {
    return <div className="analytics-loading">{t('common.loading')}</div>;
  }

  /* ── Render ─────────────────────────────────────────────────────────────── */

  return (
    <div className="analytics">
      {/* Header + Date Controls */}
      <div className="analytics-header">
        <div>
          <h1>{t('analytics.title')}</h1>
          <p>{t('analytics.subtitle')}</p>
        </div>
        <div className="analytics-date-controls">
          {/* Account selector */}
          {adAccounts.length > 1 && (
            <div className="analytics-account-selector">
              <select
                value={selectedAccountId}
                onChange={e => handleAccountChange(e.target.value)}
                className="account-select"
              >
                <option value="">All accounts (mixed currencies)</option>
                {adAccounts.map(acc => (
                  <option key={acc.id} value={acc.id}>
                    {acc.name} ({acc.currency})
                  </option>
                ))}
              </select>
              {currency === 'MIXED' && (
                <span className="currency-warning" title="Data includes multiple currencies (ARS + USD). Select a specific account for accurate metrics.">
                  <AlertTriangle size={14} /> Mixed currencies
                </span>
              )}
            </div>
          )}
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <button className="btn btn-sm" onClick={handleExportPdf} disabled={exportingPdf} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-card)', cursor: 'pointer' }}>
              <FileDown size={14} />
              {exportingPdf ? 'Exporting...' : 'Export PDF'}
            </button>
            <button className="btn btn-sm" onClick={handleExportXlsx} disabled={exportingXlsx} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-card)', cursor: 'pointer' }}>
              <FileDown size={14} />
              {exportingXlsx ? 'Exporting...' : 'Export XLSX'}
            </button>
          </div>
          <div className="analytics-period">
            {DATE_PRESETS.map(p => (
              <button
                key={p.label}
                className={`period-btn ${activePreset === p.label ? 'active' : ''}`}
                onClick={() => handlePreset(p)}
              >
                {p.label}
              </button>
            ))}
            <button
              className={`period-btn ${showCustom ? 'active' : ''}`}
              onClick={() => setShowCustom(!showCustom)}
            >
              Custom
            </button>
          </div>
          {showCustom && (
            <div className="custom-date-row">
              <input
                type="date"
                value={customSince}
                onChange={e => setCustomSince(e.target.value)}
                className="date-input"
              />
              <span className="date-separator">to</span>
              <input
                type="date"
                value={customUntil}
                onChange={e => setCustomUntil(e.target.value)}
                className="date-input"
              />
              <button className="btn btn-primary btn-sm" onClick={handleCustomApply}>
                Apply
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── KPI Cards ──────────────────────────────────────────────────────── */}
      {summary && (
        <div className="analytics-kpis">
          <div className="kpi-card">
            <span className="kpi-label">{t('analytics.total_spend')} {currency !== 'USD' && currency !== 'MIXED' ? `(${currency})` : ''}</span>
            <span className="kpi-value">{currency === 'ARS' ? `ARS ${summary.total_spend.toLocaleString('es-AR', { maximumFractionDigits: 0 })}` : fmt$(summary.total_spend)}</span>
            {summary.spend_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.spend_trend)}`}>
                {trendArrow(summary.spend_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">{t('analytics.avg_ctr')}</span>
            <span className="kpi-value">{summary.avg_ctr}%</span>
            {summary.ctr_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.ctr_trend)}`}>
                {trendArrow(summary.ctr_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">{t('analytics.avg_cpc')}</span>
            <span className="kpi-value">${summary.avg_cpc.toFixed(2)}</span>
            {summary.cpc_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.cpc_trend, true)}`}>
                {trendArrow(summary.cpc_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">{t('analytics.avg_roas')}</span>
            <span className="kpi-value">{summary.avg_roas}x</span>
            {summary.roas_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.roas_trend)}`}>
                {trendArrow(summary.roas_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Clicks</span>
            <span className="kpi-value">{fmtN(summary.total_clicks)}</span>
            {summary.clicks_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.clicks_trend)}`}>
                {trendArrow(summary.clicks_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Impressions</span>
            <span className="kpi-value">{fmtN(summary.total_impressions)}</span>
            {summary.impressions_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.impressions_trend)}`}>
                {trendArrow(summary.impressions_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">{t('analytics.conversions')}</span>
            <span className="kpi-value">{fmtN(summary.total_conversions)}</span>
            {summary.conversions_trend !== null && (
              <span className={`kpi-trend ${trendClass(summary.conversions_trend)}`}>
                {trendArrow(summary.conversions_trend)}
              </span>
            )}
          </div>
          <div className="kpi-card">
            <span className="kpi-label">Active Campaigns</span>
            <span className="kpi-value">{summary.active_campaigns}</span>
          </div>
        </div>
      )}

      {/* ── Metrics Chart ──────────────────────────────────────────────────── */}
      <div className="analytics-section">
        <div className="chart-header">
          <h2 className="analytics-section-title">Metrics Over Time</h2>
          <div className="chart-metric-tabs">
            {CHART_METRICS.map(m => (
              <button
                key={m.key}
                className={`chart-tab ${chartMetric === m.key ? 'active' : ''}`}
                onClick={() => setChartMetric(m.key)}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
        <div className="analytics-chart" ref={chartRef}>
          {buckets.length === 0 ? (
            <div className="analytics-empty">{t('common.no_data')}</div>
          ) : (
            <div className="chart-inner">
              {/* Y-axis */}
              <div className="chart-y-axis">
                {ticks.map((tick, i) => (
                  <span key={i} className="y-tick">{metricConf.format(tick)}</span>
                ))}
              </div>
              {/* Bars */}
              <div className="chart-bars-area">
                <div className="chart-grid-lines">
                  {ticks.map((_, i) => (
                    <div key={i} className="grid-line" style={{ top: `${(i / (ticks.length - 1)) * 100}%` }} />
                  ))}
                </div>
                <div className="chart-bars">
                  {buckets.map((b, i) => {
                    const val = b[chartMetric] as number;
                    const pct = maxVal > 0 ? (val / maxVal) * 100 : 0;
                    return (
                      <div
                        key={i}
                        className="chart-bar-col"
                      >
                        <div className="chart-bar-wrap">
                          <div
                            className="chart-bar"
                            style={{ height: `${Math.max(pct, 1)}%` }}
                          >
                            <div className="chart-tooltip">
                              <div className="tooltip-label">{b.label}</div>
                              <div>Spend: {fmt$(b.spend)}</div>
                              <div>Clicks: {fmtN(b.clicks)}</div>
                              <div>Impr: {fmtN(b.impressions)}</div>
                              <div>CTR: {b.ctr}%</div>
                              <div>CPC: ${b.cpc.toFixed(2)}</div>
                              <div>Conv: {b.conversions}</div>
                            </div>
                          </div>
                        </div>
                        <span className="chart-bar-label">{i % labelSkip === 0 ? b.label : ''}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="chart-bucket-type">
          {bucketType === 'daily' ? 'Daily' : bucketType === 'weekly' ? 'Weekly' : 'Monthly'} buckets
        </div>
      </div>

      {/* ── Campaign Table ─────────────────────────────────────────────────── */}
      <div className="analytics-section">
        <h2 className="analytics-section-title">{t('analytics.top_campaigns')}</h2>
        <div className="analytics-table-wrap">
          <table className="analytics-table">
            <thead>
              <tr>
                <th className="sortable" onClick={() => handleSort('name')}>
                  {t('analytics.campaign')}{sortIcon('name')}
                </th>
                <th className="sortable" onClick={() => handleSort('objective')}>
                  Objective{sortIcon('objective')}
                </th>
                <th className="sortable" onClick={() => handleSort('status')}>
                  Status{sortIcon('status')}
                </th>
                <th className="sortable num" onClick={() => handleSort('spend')}>
                  {t('analytics.spend_col')}{sortIcon('spend')}
                </th>
                <th className="sortable num" onClick={() => handleSort('ctr')}>
                  CTR{sortIcon('ctr')}
                </th>
                <th className="sortable num" onClick={() => handleSort('cpc')}>
                  CPC{sortIcon('cpc')}
                </th>
                <th className="sortable num" onClick={() => handleSort('roas')}>
                  ROAS{sortIcon('roas')}
                </th>
                <th className="sortable num" onClick={() => handleSort('clicks')}>
                  {t('analytics.clicks')}{sortIcon('clicks')}
                </th>
                <th className="sortable num" onClick={() => handleSort('impressions')}>
                  Impr{sortIcon('impressions')}
                </th>
              </tr>
            </thead>
            <tbody>
              {sortedCampaigns.length === 0 ? (
                <tr>
                  <td colSpan={9} style={{ textAlign: 'center', color: '#6b7280' }}>
                    {t('common.no_data')}
                  </td>
                </tr>
              ) : (
                sortedCampaigns.map((c) => (
                  <tr key={c.campaign_id}>
                    <td className="campaign-name-cell" title={c.name}>{c.name}</td>
                    <td>{c.objective}</td>
                    <td>
                      <span className={`status-pill ${c.status === 'ACTIVE' ? 'status-active' : 'status-paused'}`}>
                        {c.status}
                      </span>
                    </td>
                    <td className="num">{fmt$(c.spend)}</td>
                    <td className="num">{c.ctr}%</td>
                    <td className="num">${c.cpc.toFixed(2)}</td>
                    <td className="num">{c.roas}x</td>
                    <td className="num">{fmtN(c.clicks)}</td>
                    <td className="num">{fmtN(c.impressions)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Insights Grid ──────────────────────────────────────────────────── */}
      {insights.length > 0 && (
        <div className="analytics-section">
          <h2 className="analytics-section-title">Insights</h2>
          <div className="insights-grid">
            {insights.map((ins, i) => (
              <div key={i} className={`insight-card insight-${ins.type}`}>
                <div className="insight-header">
                  <span className="insight-title">{ins.title}</span>
                  <span className="insight-metric">{ins.metric_value}</span>
                </div>
                <p className="insight-desc">{ins.description}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
