import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileDown, TrendingUp, Pause, RefreshCw, Zap, Target, ChevronDown, ChevronUp, ArrowRight, Loader2 } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { brainApi, BrainStats, BrainSummary, BrainSuggestion, EntityTrust, RecentOutcome, FlywheelRecommendation } from '../services/api';
import './Brain.css';

function fmt$(v: number, decimals?: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  const d = decimals ?? (v < 10 ? 2 : 0);
  return `$${v.toFixed(d)}`;
}

function fmtN(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString();
}

function outcomeIcon(label: string) {
  if (label === 'win') return '\u25B2';
  if (label === 'loss') return '\u25BC';
  return '\u25CF';
}

function trendArrow(val: number | null) {
  if (val === null || val === undefined) return '';
  if (val > 0) return `+${val}%`;
  if (val < 0) return `${val}%`;
  return '0%';
}

function trendClass(val: number | null, invert?: boolean) {
  if (val === null || val === undefined) return '';
  const positive = invert ? val < 0 : val > 0;
  const negative = invert ? val > 0 : val < 0;
  if (positive) return 'trend-up';
  if (negative) return 'trend-down';
  return '';
}

function suggestion(trust: EntityTrust): string {
  const d = trust.detail || {};
  const ctr = d.ctr || 0;
  const cpc = d.cpc || 0;
  const score = trust.trust_score;

  if (score >= 80 && ctr > 1.5) return 'High performer — consider scaling budget';
  if (score >= 70 && ctr > 1.0) return 'Good results — monitor for consistency';
  if (score >= 50 && ctr < 0.8) return 'Low CTR — review creative or audience';
  if (cpc > 100) return 'High CPC — optimize targeting or bids';
  if (score < 40) return 'Underperforming — evaluate or pause';
  return 'Stable — keep monitoring';
}

function outcomeSuggestion(o: RecentOutcome): string {
  const d = o.detail || {};
  const ctr = d.ctr || 0;
  const cpc = d.cpc || 0;

  if (o.outcome_label === 'win' && ctr > 2) return 'Excellent CTR — scale this campaign';
  if (o.outcome_label === 'win') return 'Performing well — maintain current strategy';
  if (o.outcome_label === 'loss' && cpc > 100) return 'High cost per click — review audience & bids';
  if (o.outcome_label === 'loss') return 'Low engagement — test new creatives';
  return 'Average performance — A/B test to improve';
}

function renderAnalysisText(text: string) {
  if (!text) return null;
  const lines = text.split('\n');
  return lines.map((line, i) => {
    const trimmed = line.trim();
    if (!trimmed) return <br key={i} />;
    if (trimmed.startsWith('## '))
      return <h4 key={i} className="analysis-section-title">{trimmed.replace('## ', '').replace(/\*\*/g, '')}</h4>;
    if (trimmed.startsWith('- '))
      return <p key={i} className="analysis-text" style={{ paddingLeft: '1rem' }}>{trimmed.replace(/\*\*/g, '')}</p>;
    return <p key={i} className="analysis-text">{trimmed.replace(/\*\*/g, '')}</p>;
  });
}

const PRESETS = [
  { label: '7d', days: 7 },
  { label: '14d', days: 14 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '365d', days: 365 },
  { label: 'All', days: 730 },
];

export default function Brain() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [stats, setStats] = useState<BrainStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [activePreset, setActivePreset] = useState('90d');
  const [days, setDays] = useState(90);
  const [customSince, setCustomSince] = useState('');
  const [customUntil, setCustomUntil] = useState('');
  const [showCustom, setShowCustom] = useState(false);
  const [suggestions, setSuggestions] = useState<BrainSuggestion[]>([]);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingXlsx, setExportingXlsx] = useState(false);

  // Flywheel
  const [flywheelRecs, setFlywheelRecs] = useState<FlywheelRecommendation[]>([]);

  // Expandable analysis panels
  const [expandedEntity, setExpandedEntity] = useState<number | null>(null);
  const [entityAnalysis, setEntityAnalysis] = useState<Record<number, { text: string; loading: boolean }>>({});
  const [expandedFeature, setExpandedFeature] = useState<number | null>(null);
  const [featureAnalysis, setFeatureAnalysis] = useState<Record<number, { text: string; loading: boolean }>>({});
  const [expandedOutcome, setExpandedOutcome] = useState<number | null>(null);
  const [outcomeAnalysis, setOutcomeAnalysis] = useState<Record<number, { text: string; loading: boolean }>>({});
  const [exportingEntityPdf, setExportingEntityPdf] = useState<number | null>(null);

  const getDateParams = () => customSince
    ? { days: undefined as number | undefined, since: customSince, until: customUntil || undefined }
    : { days, since: undefined as string | undefined, until: undefined as string | undefined };

  const fetchSuggestions = async (daysVal: number, since?: string, until?: string) => {
    try {
      const res = since
        ? await brainApi.getSuggestions(undefined, since, until || undefined)
        : await brainApi.getSuggestions(daysVal);
      setSuggestions(res.data.suggestions || []);
    } catch {
      setSuggestions([]);
    }
  };

  const fetchFlywheel = async (daysVal: number, since?: string, until?: string) => {
    try {
      const res = since
        ? await brainApi.getFlywheelRecommendations(undefined, since, until || undefined)
        : await brainApi.getFlywheelRecommendations(daysVal);
      setFlywheelRecs(res.data.recommendations || []);
    } catch {
      setFlywheelRecs([]);
    }
  };

  const fetchData = async (daysVal: number, since?: string, until?: string) => {
    setLoading(true);
    try {
      const res = since
        ? await brainApi.getStats(undefined, since, until || undefined)
        : await brainApi.getStats(daysVal);
      setStats(res.data);
    } catch {
      setStats(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(days);
    fetchSuggestions(days);
    fetchFlywheel(days);
  }, []);

  const handlePreset = (p: typeof PRESETS[0]) => {
    setShowCustom(false);
    setActivePreset(p.label);
    setDays(p.days);
    setExpandedEntity(null);
    setExpandedFeature(null);
    setExpandedOutcome(null);
    fetchData(p.days);
    fetchSuggestions(p.days);
    fetchFlywheel(p.days);
  };

  const handleCustomApply = () => {
    if (!customSince) return;
    setActivePreset('custom');
    fetchData(0, customSince, customUntil || undefined);
    fetchSuggestions(0, customSince, customUntil || undefined);
    fetchFlywheel(0, customSince, customUntil || undefined);
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      const p = getDateParams();
      const res = await brainApi.exportPdf(p.days, p.since, p.until);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'brain_report.pdf';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export PDF:', err);
    } finally {
      setExportingPdf(false);
    }
  };

  const handleExportXlsx = async () => {
    try {
      setExportingXlsx(true);
      const p = getDateParams();
      const res = await brainApi.exportXlsx(p.days, p.since, p.until);
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'brain_report.xlsx';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export XLSX:', err);
    } finally {
      setExportingXlsx(false);
    }
  };

  const handleEntityAnalysis = async (idx: number, entity: EntityTrust) => {
    if (expandedEntity === idx) { setExpandedEntity(null); return; }
    setExpandedEntity(idx);
    if (entityAnalysis[idx]?.text) return;
    setEntityAnalysis(prev => ({ ...prev, [idx]: { text: '', loading: true } }));
    try {
      const p = getDateParams();
      const res = await brainApi.getEntityAnalysis(entity.entity_id, p.days, p.since, p.until);
      setEntityAnalysis(prev => ({ ...prev, [idx]: { text: res.data.analysis_text || '', loading: false } }));
    } catch {
      setEntityAnalysis(prev => ({ ...prev, [idx]: { text: 'Analysis unavailable', loading: false } }));
    }
  };

  const handleEntityPdfExport = async (idx: number, entity: EntityTrust) => {
    try {
      setExportingEntityPdf(idx);
      const p = getDateParams();
      const res = await brainApi.exportEntityPdf(entity.entity_id, p.days, p.since, p.until);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `brain_${entity.entity_id.replace(/\s+/g, '_').substring(0, 20)}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to export entity PDF:', err);
    } finally {
      setExportingEntityPdf(null);
    }
  };

  const handleFeatureAnalysis = async (idx: number, featureKey: string) => {
    if (expandedFeature === idx) { setExpandedFeature(null); return; }
    setExpandedFeature(idx);
    if (featureAnalysis[idx]?.text) return;
    setFeatureAnalysis(prev => ({ ...prev, [idx]: { text: '', loading: true } }));
    try {
      const p = getDateParams();
      const res = await brainApi.getFeatureAnalysis(featureKey, p.days, p.since, p.until);
      setFeatureAnalysis(prev => ({ ...prev, [idx]: { text: res.data.analysis_text || '', loading: false } }));
    } catch {
      setFeatureAnalysis(prev => ({ ...prev, [idx]: { text: 'Analysis unavailable', loading: false } }));
    }
  };

  const handleOutcomeAnalysis = async (idx: number) => {
    if (expandedOutcome === idx) { setExpandedOutcome(null); return; }
    setExpandedOutcome(idx);
    if (outcomeAnalysis[idx]?.text) return;
    setOutcomeAnalysis(prev => ({ ...prev, [idx]: { text: '', loading: true } }));
    try {
      const p = getDateParams();
      const res = await brainApi.getOutcomeAnalysis(idx, p.days, p.since, p.until);
      setOutcomeAnalysis(prev => ({ ...prev, [idx]: { text: res.data.analysis_text || '', loading: false } }));
    } catch {
      setOutcomeAnalysis(prev => ({ ...prev, [idx]: { text: 'Analysis unavailable', loading: false } }));
    }
  };

  const suggestionIcon = (type: string) => {
    switch (type) {
      case 'scale': return <TrendingUp size={16} />;
      case 'pause': return <Pause size={16} />;
      case 'refresh': return <RefreshCw size={16} />;
      case 'test': return <Zap size={16} />;
      case 'optimize': return <Target size={16} />;
      default: return <Zap size={16} />;
    }
  };

  const suggestionColor = (type: string) => {
    switch (type) {
      case 'scale': return 'var(--olive-500, #8b9857)';
      case 'pause': return 'var(--terracotta-500, #ba6044)';
      case 'refresh': return 'var(--gold-500, #c4a434)';
      case 'test': return '#5b8cd4';
      case 'optimize': return '#c49a34';
      default: return '#888';
    }
  };

  const suggestionRoute = (type: string) => {
    switch (type) {
      case 'scale': return '/opportunities';
      case 'pause': return '/analytics';
      case 'refresh': return '/creatives';
      case 'test': return '/creatives';
      case 'optimize': return '/opportunities';
      default: return '/analytics';
    }
  };

  if (loading && !stats) {
    return <div className="brain-page"><p>{t('common.loading')}</p></div>;
  }

  const s: BrainSummary = stats?.summary || {} as BrainSummary;

  return (
    <div className="brain-page">
      {/* Header + Date Controls */}
      <div className="brain-header">
        <div>
          <h1>{t('brain.title')}</h1>
          <p>{t('brain.subtitle')}</p>
        </div>
        <div className="brain-date-controls">
          <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
            <button onClick={handleExportPdf} disabled={exportingPdf} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-card)', cursor: 'pointer' }}>
              <FileDown size={14} />
              {exportingPdf ? 'Exporting...' : 'Export PDF'}
            </button>
            <button onClick={handleExportXlsx} disabled={exportingXlsx} style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px', padding: '4px 10px', border: '1px solid var(--border)', borderRadius: '6px', background: 'var(--bg-card)', cursor: 'pointer' }}>
              <FileDown size={14} />
              {exportingXlsx ? 'Exporting...' : 'Export XLSX'}
            </button>
          </div>
          <div className="brain-period">
            {PRESETS.map(p => (
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
            <div className="brain-custom-row">
              <input type="date" value={customSince} onChange={e => setCustomSince(e.target.value)} className="date-input" />
              <span className="date-separator">to</span>
              <input type="date" value={customUntil} onChange={e => setCustomUntil(e.target.value)} className="date-input" />
              <button className="btn btn-primary btn-sm" onClick={handleCustomApply}>Apply</button>
            </div>
          )}
        </div>
      </div>

      {/* KPI Summary with Trends */}
      <div className="brain-kpis">
        <div className="brain-kpi">
          <span className="brain-kpi-value">{s.total_campaigns || 0}</span>
          <span className="brain-kpi-label">Campaigns</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{s.avg_trust || 0}</span>
          <span className="brain-kpi-label">Avg Trust</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{s.win_count || 0}/{s.total_campaigns || 0}</span>
          <span className="brain-kpi-label">Winning</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{fmt$(s.total_spend || 0)}</span>
          <span className={`brain-kpi-trend ${trendClass(s.spend_trend)}`}>{trendArrow(s.spend_trend)}</span>
          <span className="brain-kpi-label">Spend</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{s.avg_ctr || 0}%</span>
          <span className={`brain-kpi-trend ${trendClass(s.ctr_trend)}`}>{trendArrow(s.ctr_trend)}</span>
          <span className="brain-kpi-label">CTR</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{fmt$(s.avg_cpc || 0)}</span>
          <span className={`brain-kpi-trend ${trendClass(s.cpc_trend, true)}`}>{trendArrow(s.cpc_trend)}</span>
          <span className="brain-kpi-label">CPC</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{fmtN(s.total_clicks || 0)}</span>
          <span className="brain-kpi-label">Clicks</span>
        </div>
        <div className="brain-kpi">
          <span className="brain-kpi-value">{fmtN(s.total_impressions || 0)}</span>
          <span className="brain-kpi-label">Impressions</span>
        </div>
      </div>

      {/* Suggested Actions */}
      {suggestions.length > 0 && (
        <section className="brain-section" style={{ marginBottom: '1.5rem' }}>
          <div className="brain-section-header">
            <h2>Suggested Actions</h2>
            <span className="brain-section-count">{suggestions.length}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '0.75rem' }}>
            {suggestions.map((sg, i) => (
              <div
                key={i}
                className="suggestion-card"
                style={{
                  padding: '1rem',
                  borderRadius: '10px',
                  border: `1px solid ${suggestionColor(sg.type)}30`,
                  background: `${suggestionColor(sg.type)}08`,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
                  <span style={{ color: suggestionColor(sg.type), display: 'flex' }}>{suggestionIcon(sg.type)}</span>
                  <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text-primary)', flex: 1 }}>{sg.title}</span>
                  <span className={`recommendation-priority priority-${sg.type === 'scale' ? 'high' : sg.type === 'pause' ? 'high' : 'medium'}`}>
                    {sg.type === 'scale' || sg.type === 'pause' ? 'P1' : 'P2'}
                  </span>
                </div>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', margin: '0 0 0.5rem 0', lineHeight: 1.5 }}>{sg.description}</p>
                <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap' }}>
                  <button
                    className="flywheel-action-btn"
                    onClick={() => navigate(suggestionRoute(sg.type))}
                  >
                    Take Action <ArrowRight size={12} />
                  </button>
                  <button
                    className="flywheel-action-btn"
                    style={{ background: 'var(--olive-50, #f4f6ef)', color: 'var(--olive-600, #6b7a3d)', border: '1px solid var(--olive-200, #c8d4a8)' }}
                    onClick={() => navigate(`/control-panel?action_type=${sg.type === 'pause' ? 'adset_pause' : sg.type === 'refresh' ? 'creative_swap' : 'budget_change'}&entity_type=${sg.type === 'pause' ? 'adset' : 'campaign'}&entity_name=${encodeURIComponent(sg.title)}&rationale=${encodeURIComponent(`[Brain: ${sg.type}] ${sg.description}`)}&source=brain`)}
                  >
                    Crear Decisión <Zap size={12} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      <div className="brain-grid-layout">
        {/* Left Column */}
        <div className="brain-col-main">
          {/* Top Features — Expandable */}
          <section className="brain-section">
            <div className="brain-section-header">
              <h2>{t('brain.top_features')}</h2>
              <span className="brain-section-count">{stats?.top_features.length || 0}</span>
            </div>
            <div className="brain-scroll-area" style={{ maxHeight: '520px' }}>
              {stats && stats.top_features.length > 0 ? (
                <div className="feature-list">
                  {stats.top_features.map((f, i) => {
                    const pct = Math.round(f.win_rate * 100);
                    const level = pct >= 60 ? 'high' : pct >= 40 ? 'medium' : 'low';
                    const d = f.avg_delta || {};
                    const isExpanded = expandedFeature === i;
                    const analysis = featureAnalysis[i];
                    return (
                      <div key={i} className={`feature-row ${isExpanded ? 'expanded' : ''}`}>
                        <div
                          className="feature-row-clickable"
                          onClick={() => handleFeatureAnalysis(i, f.feature_key)}
                          style={{ cursor: 'pointer' }}
                        >
                          <div className="feature-row-left">
                            <div className={`feature-pct-badge ${level}`}>{pct}%</div>
                            <div className="feature-row-info">
                              <span className="feature-name">{f.feature_key}</span>
                              <span className="feature-type-label">{f.feature_type}</span>
                            </div>
                            <span className="expand-icon">
                              {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                            </span>
                          </div>
                        </div>
                        <div className="feature-row-metrics">
                          {d.spend != null && <span className="metric-pill">{fmt$(d.spend)}</span>}
                          {d.clicks != null && <span className="metric-pill">{fmtN(d.clicks)} clicks</span>}
                          {d.avg_ctr != null && <span className="metric-pill">{d.avg_ctr}% CTR</span>}
                          {d.avg_cpc != null && <span className="metric-pill">{fmt$(d.avg_cpc)} CPC</span>}
                          {d.conversions != null && d.conversions > 0 && <span className="metric-pill">{d.conversions} conv</span>}
                        </div>
                        <div className="feature-row-bar">
                          <div className={`feature-bar-fill ${level}`} style={{ width: `${pct}%` }} />
                        </div>
                        <span className="feature-samples">{f.samples} campaigns</span>

                        {isExpanded && (
                          <div className="analysis-panel">
                            {analysis?.loading ? (
                              <div className="analysis-loading"><Loader2 size={16} className="spin" /> Analyzing...</div>
                            ) : (
                              <>
                                {renderAnalysisText(analysis?.text || '')}
                                <button className="flywheel-action-btn" onClick={() => navigate('/creatives')} style={{ marginTop: '0.75rem' }}>
                                  Create Creative for this objective <ArrowRight size={12} />
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="brain-empty">{t('common.no_data')}</p>
              )}
            </div>
          </section>

          {/* Recent Outcomes — Expandable */}
          <section className="brain-section">
            <div className="brain-section-header">
              <h2>{t('brain.recent_outcomes')}</h2>
              <span className="brain-section-count">{stats?.recent_outcomes.length || 0}</span>
            </div>
            <div className="brain-scroll-area" style={{ maxHeight: '620px' }}>
              {stats && stats.recent_outcomes.length > 0 ? (
                <div className="outcome-cards">
                  {stats.recent_outcomes.map((o, i) => {
                    const d = o.detail || {};
                    const isExpanded = expandedOutcome === i;
                    const analysis = outcomeAnalysis[i];
                    return (
                      <div key={i} className={`outcome-card ${o.outcome_label}`}>
                        <div
                          className="outcome-card-header"
                          onClick={() => handleOutcomeAnalysis(i)}
                          style={{ cursor: 'pointer' }}
                        >
                          <span className={`outcome-icon ${o.outcome_label}`}>
                            {outcomeIcon(o.outcome_label)}
                          </span>
                          <span className="outcome-name">{o.entity_id}</span>
                          <span className="outcome-date">
                            {new Date(o.executed_at).toLocaleDateString()}
                          </span>
                          <span className="expand-icon">
                            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                          </span>
                        </div>
                        <div className="outcome-card-metrics">
                          {d.spend != null && (
                            <div className="outcome-metric">
                              <span className="outcome-metric-val">{fmt$(d.spend)}</span>
                              <span className="outcome-metric-lbl">Spend</span>
                            </div>
                          )}
                          {d.clicks != null && (
                            <div className="outcome-metric">
                              <span className="outcome-metric-val">{fmtN(d.clicks)}</span>
                              <span className="outcome-metric-lbl">Clicks</span>
                            </div>
                          )}
                          {d.ctr != null && (
                            <div className="outcome-metric">
                              <span className="outcome-metric-val">{d.ctr}%</span>
                              <span className="outcome-metric-lbl">CTR</span>
                            </div>
                          )}
                          {d.cpc != null && (
                            <div className="outcome-metric">
                              <span className="outcome-metric-val">{fmt$(d.cpc)}</span>
                              <span className="outcome-metric-lbl">CPC</span>
                            </div>
                          )}
                          {d.impressions != null && (
                            <div className="outcome-metric">
                              <span className="outcome-metric-val">{fmtN(d.impressions)}</span>
                              <span className="outcome-metric-lbl">Imp.</span>
                            </div>
                          )}
                          <div className="outcome-metric">
                            <span className="outcome-metric-val">{Math.round(o.confidence * 100)}%</span>
                            <span className="outcome-metric-lbl">Conf.</span>
                          </div>
                        </div>
                        <div className="outcome-suggestion">
                          {outcomeSuggestion(o)}
                        </div>

                        {isExpanded && (
                          <div className="analysis-panel">
                            {analysis?.loading ? (
                              <div className="analysis-loading"><Loader2 size={16} className="spin" /> Analyzing...</div>
                            ) : (
                              <>
                                {renderAnalysisText(analysis?.text || '')}
                                <button
                                  className="flywheel-action-btn"
                                  onClick={() => navigate(o.outcome_label === 'win' ? '/opportunities' : '/creatives')}
                                  style={{ marginTop: '0.75rem' }}
                                >
                                  {o.outcome_label === 'win' ? 'Scale via Opportunities' : 'Refresh Creatives'} <ArrowRight size={12} />
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="brain-empty">{t('common.no_data')}</p>
              )}
            </div>
          </section>
        </div>

        {/* Right Column: Entity Trust — with breakdown + analysis */}
        <div className="brain-col-side">
          <section className="brain-section">
            <div className="brain-section-header">
              <h2>{t('brain.entity_trust')}</h2>
              <span className="brain-section-count">{stats?.entity_trust.length || 0}</span>
            </div>
            <div className="brain-scroll-area" style={{ maxHeight: '960px' }}>
              {stats && stats.entity_trust.length > 0 ? (
                <div className="trust-list">
                  {stats.entity_trust.map((e, i) => {
                    const level = e.trust_score >= 70 ? 'high' : e.trust_score >= 40 ? 'medium' : 'low';
                    const d = e.detail || {};
                    const isExpanded = expandedEntity === i;
                    const analysis = entityAnalysis[i];
                    return (
                      <div key={i} className={`trust-item ${level}`}>
                        <div className="trust-item-top">
                          <div className={`trust-ring ${level}`}>
                            <svg viewBox="0 0 36 36" className="trust-ring-svg">
                              <path
                                className="trust-ring-bg"
                                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                              />
                              <path
                                className={`trust-ring-fill ${level}`}
                                strokeDasharray={`${e.trust_score}, 100`}
                                d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                              />
                            </svg>
                            <span className="trust-ring-text">{Math.round(e.trust_score)}</span>
                          </div>
                          <div className="trust-item-info">
                            <span className="trust-item-name">{e.entity_id}</span>
                            {d.objective && <span className="trust-item-obj">{d.objective}</span>}
                            {d.status && (
                              <span className={`trust-status-pill ${d.status === 'ACTIVE' ? 'active' : 'paused'}`}>
                                {d.status}
                              </span>
                            )}
                          </div>
                        </div>

                        {/* Trust Breakdown Bars */}
                        <div className="trust-breakdown">
                          <div className="trust-bar-row">
                            <span className="trust-bar-label">CTR</span>
                            <div className="trust-bar-track">
                              <div className="trust-bar-fill ctr" style={{ width: `${(d.trust_ctr_score || 0) / 40 * 100}%` }} />
                            </div>
                            <span className="trust-bar-value">{d.trust_ctr_score || 0}/40</span>
                          </div>
                          <div className="trust-bar-row">
                            <span className="trust-bar-label">Efficiency</span>
                            <div className="trust-bar-track">
                              <div className="trust-bar-fill efficiency" style={{ width: `${(d.trust_efficiency_score || 0) / 30 * 100}%` }} />
                            </div>
                            <span className="trust-bar-value">{d.trust_efficiency_score || 0}/30</span>
                          </div>
                          <div className="trust-bar-row">
                            <span className="trust-bar-label">Stability</span>
                            <div className="trust-bar-track">
                              <div className="trust-bar-fill stability" style={{ width: `${(d.trust_stability_score || 0) / 30 * 100}%` }} />
                            </div>
                            <span className="trust-bar-value">{d.trust_stability_score || 0}/30</span>
                          </div>
                        </div>

                        <div className="trust-item-metrics">
                          {d.spend != null && <span>{fmt$(d.spend)}</span>}
                          {d.ctr != null && <span>{d.ctr}% CTR</span>}
                          {d.cpc != null && <span>{fmt$(d.cpc)} CPC</span>}
                          {d.days_active != null && <span>{d.days_active}d</span>}
                        </div>
                        <div className="trust-suggestion">{suggestion(e)}</div>

                        {/* Action buttons */}
                        <div className="trust-actions">
                          <button className="trust-action-btn" onClick={() => handleEntityAnalysis(i, e)}>
                            {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                            {isExpanded ? 'Hide' : 'Analyze'}
                          </button>
                          <button
                            className="trust-action-btn"
                            onClick={() => handleEntityPdfExport(i, e)}
                            disabled={exportingEntityPdf === i}
                          >
                            <FileDown size={13} />
                            {exportingEntityPdf === i ? '...' : 'PDF'}
                          </button>
                        </div>

                        {isExpanded && (
                          <div className="analysis-panel">
                            {analysis?.loading ? (
                              <div className="analysis-loading"><Loader2 size={16} className="spin" /> Analyzing...</div>
                            ) : (
                              renderAnalysisText(analysis?.text || '')
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <p className="brain-empty">{t('common.no_data')}</p>
              )}
            </div>
          </section>
        </div>
      </div>

      {/* Flywheel Navigation */}
      {flywheelRecs.length > 0 && (
        <section className="flywheel-section">
          <div className="brain-section-header">
            <h2>Flywheel — Next Steps</h2>
            <span className="brain-section-count">{flywheelRecs.length}</span>
          </div>
          <div className="flywheel-grid">
            {flywheelRecs.map((rec, i) => (
              <div
                key={i}
                className={`flywheel-card priority-${rec.priority}`}
                onClick={() => navigate(rec.route_path)}
              >
                <div className="flywheel-card-header">
                  <span className="flywheel-module">{rec.module}</span>
                  <span className={`recommendation-priority priority-${rec.priority <= 1 ? 'high' : rec.priority <= 2 ? 'medium' : 'low'}`}>
                    P{rec.priority}
                  </span>
                </div>
                <p className="flywheel-reason">{rec.reason}</p>
                <span className="flywheel-action">
                  {rec.action_label} <ArrowRight size={14} />
                </span>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
