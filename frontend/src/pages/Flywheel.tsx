import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Repeat, RefreshCw, Brain, TrendingUp, Sparkles, Lightbulb, Palette, Layers, FileDown, Loader2, Eye, RotateCcw, StopCircle, Download, ChevronDown, ChevronUp } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { flywheelApi, FlywheelRunResponse, FlywheelStepResponse } from '../services/api';
import { useJobPolling } from '../hooks/useJobPolling';
import './Flywheel.css';

interface StepDef {
  key: string;
  labelKey: string;
  icon: any;
  route: string;
}

const STEP_DEFS: StepDef[] = [
  { key: 'meta_sync', labelKey: 'flywheel.step.meta_sync', icon: RefreshCw, route: '/dashboard' },
  { key: 'brain_analysis', labelKey: 'flywheel.step.brain', icon: Brain, route: '/brain' },
  { key: 'saturation_check', labelKey: 'flywheel.step.saturation', icon: TrendingUp, route: '/saturation' },
  { key: 'unified_intelligence', labelKey: 'flywheel.step.intelligence', icon: Sparkles, route: '/brain' },
  { key: 'opportunities', labelKey: 'flywheel.step.opportunities', icon: Lightbulb, route: '/opportunities' },
  { key: 'creatives', labelKey: 'flywheel.step.creatives', icon: Palette, route: '/creatives' },
  { key: 'content_studio', labelKey: 'flywheel.step.content', icon: Layers, route: '/content-studio' },
  { key: 'export', labelKey: 'flywheel.step.export', icon: FileDown, route: '/data-room' },
];

const TERMINAL_STATES = ['succeeded', 'failed', 'canceled'];
const LS_ACTIVE_RUN_KEY = 'flywheel_active_run';

function getStepStatus(steps: FlywheelStepResponse[], key: string): FlywheelStepResponse | undefined {
  return steps.find((s) => s.step_name === key);
}

/** Extract a brief summary from step artifacts for inline display */
function getStepBrief(step: FlywheelStepResponse | undefined): string | null {
  if (!step || step.status !== 'succeeded') return null;
  const a = step.artifacts_json || {};

  switch (step.step_name) {
    case 'meta_sync':
      if (a.reason) return a.reason;
      return a.ad_account_id ? `Synced account ${String(a.ad_account_id).slice(0, 8)}...` : null;
    case 'brain_analysis': {
      const parts = [];
      if (a.entity_memory_count != null) parts.push(`${a.entity_memory_count} entities`);
      if (a.feature_memory_count != null) parts.push(`${a.feature_memory_count} features`);
      if (a.avg_trust_score) parts.push(`avg trust: ${a.avg_trust_score}`);
      if (a.winning_features?.length) parts.push(`top: ${a.winning_features[0]?.key || ''}`);
      return parts.length > 0 ? parts.join(' | ') : null;
    }
    case 'saturation_check': {
      if (a.insights_daily_count === 0) return a.note || 'No insights data';
      const parts = [];
      if (a.ads_analyzed != null) parts.push(`${a.ads_analyzed} ads`);
      if (a.saturated_count != null) parts.push(`${a.saturated_count} saturated`);
      if (a.fresh_count != null) parts.push(`${a.fresh_count} fresh`);
      if (a.avg_frequency) parts.push(`avg freq: ${a.avg_frequency}`);
      return parts.length > 0 ? parts.join(' | ') : null;
    }
    case 'unified_intelligence':
      return a.job_run_id ? 'Intelligence analysis complete' : null;
    case 'opportunities': {
      if (a.opportunities_count != null) {
        const parts = [`${a.opportunities_count} opportunities`];
        const pb = a.priority_breakdown;
        if (pb) {
          const pParts = [];
          if (pb.high) pParts.push(`${pb.high} high`);
          if (pb.medium) pParts.push(`${pb.medium} med`);
          if (pb.low) pParts.push(`${pb.low} low`);
          if (pParts.length) parts.push(pParts.join(', '));
        }
        const top = a.top_opportunity;
        if (top?.title) parts.push(`Top: ${top.title}`);
        return parts.join(' | ');
      }
      return null;
    }
    case 'creatives': {
      const parts = [];
      if (a.angle_id) parts.push(`angle: ${a.angle_id}`);
      if (a.opportunities_used) parts.push(`${a.opportunities_used} opps used`);
      if (a.brain_features_used) parts.push(`${a.brain_features_used} brain features`);
      if (a.saturated_ads_avoided) parts.push(`${a.saturated_ads_avoided} saturated avoided`);
      return parts.length > 0 ? parts.join(' | ') : null;
    }
    case 'content_studio':
      if (a.reason) return a.reason;
      return a.content_pack_id ? `Content pack created` : null;
    case 'export':
      return 'Summary ready — Download report below';
    default:
      return null;
  }
}

export default function Flywheel() {
  const { t } = useLanguage();
  const navigate = useNavigate();

  const [activeRun, setActiveRun] = useState<FlywheelRunResponse | null>(null);
  const [runs, setRuns] = useState<FlywheelRunResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [pollingRunId, setPollingRunId] = useState<string | null>(null);
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set());
  const [downloadingPdf, setDownloadingPdf] = useState(false);
  const [strategicSummary, setStrategicSummary] = useState<string | null>(null);
  const [loadingSummary, setLoadingSummary] = useState(false);

  const job = useJobPolling(jobId, 2000, 1800000); // 30 min timeout for flywheel
  const prevJobStatus = useRef<string | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Fetch runs list — check localStorage for active run first
  const fetchRuns = useCallback(async () => {
    try {
      // Check localStorage for a previously active run
      const savedRunId = localStorage.getItem(LS_ACTIVE_RUN_KEY);

      const res = await flywheelApi.listRuns(20);
      setRuns(res.data);

      // If there's an active (non-terminal) run, set it
      const active = res.data.find((r) => !TERMINAL_STATES.includes(r.status));
      if (active) {
        setActiveRun(active);
        setPollingRunId(active.id);
        localStorage.setItem(LS_ACTIVE_RUN_KEY, active.id);
      } else if (savedRunId) {
        // Reconnect to saved run — it may have completed while we were away
        const saved = res.data.find((r) => r.id === savedRunId);
        if (saved) {
          setActiveRun(saved);
          if (!TERMINAL_STATES.includes(saved.status)) {
            setPollingRunId(saved.id);
          } else {
            localStorage.removeItem(LS_ACTIVE_RUN_KEY);
          }
        } else {
          localStorage.removeItem(LS_ACTIVE_RUN_KEY);
          if (res.data.length > 0) setActiveRun(res.data[0]);
        }
      } else if (res.data.length > 0) {
        setActiveRun(res.data[0]);
      }
    } catch {
      // Silently fail on list
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await fetchRuns();
      setLoading(false);
    };
    init();
  }, [fetchRuns]);

  // Poll active run status
  useEffect(() => {
    if (!pollingRunId) return;

    const poll = async () => {
      try {
        const res = await flywheelApi.getRun(pollingRunId);
        setActiveRun(res.data);
        // Update runs list
        setRuns((prev) =>
          prev.map((r) => (r.id === res.data.id ? res.data : r))
        );
        if (TERMINAL_STATES.includes(res.data.status)) {
          setPollingRunId(null);
          localStorage.removeItem(LS_ACTIVE_RUN_KEY);
        }
      } catch {
        setPollingRunId(null);
      }
    };

    poll();
    pollIntervalRef.current = setInterval(poll, 3000);

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, [pollingRunId]);

  // Fetch strategic summary when a succeeded run is selected
  useEffect(() => {
    if (!activeRun || activeRun.status !== 'succeeded') {
      setStrategicSummary(null);
      return;
    }
    // Check if summary is already cached in outputs_json
    const cached = (activeRun as any).outputs_json?.strategic_summary;
    if (cached) {
      setStrategicSummary(cached);
      return;
    }
    // Fetch from backend (will call LLM if not cached)
    setLoadingSummary(true);
    flywheelApi.getSummary(activeRun.id)
      .then((res) => setStrategicSummary(res.data.summary))
      .catch(() => setStrategicSummary(null))
      .finally(() => setLoadingSummary(false));
  }, [activeRun?.id, activeRun?.status]);

  // When job polling completes (from initial run trigger)
  useEffect(() => {
    if (prevJobStatus.current !== job.status && job.status === 'succeeded') {
      setJobId(null);
      fetchRuns();
    }
    if (job.error) {
      setError(job.error);
      setJobId(null);
    }
    prevJobStatus.current = job.status;
  }, [job.status, job.error, fetchRuns]);

  const handleRunFull = async () => {
    try {
      setError(null);
      const res = await flywheelApi.run();
      setJobId(res.data.job_id);
      setPollingRunId(res.data.run_id);
      // Persist active run ID so it survives page navigation
      if (res.data.run_id) {
        localStorage.setItem(LS_ACTIVE_RUN_KEY, res.data.run_id);
      }
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start flywheel run');
    }
  };

  const handleRetryStep = async (stepId: string) => {
    if (!activeRun) return;
    try {
      setError(null);
      await flywheelApi.retryStep(activeRun.id, stepId);
      setPollingRunId(activeRun.id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to retry step');
    }
  };

  const handleCancelRun = async () => {
    if (!activeRun) return;
    try {
      setError(null);
      await flywheelApi.cancelRun(activeRun.id);
      setJobId(null);
      setPollingRunId(null);
      localStorage.removeItem(LS_ACTIVE_RUN_KEY);
      await fetchRuns();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to cancel run');
    }
  };

  const handleDownloadPdf = async () => {
    if (!activeRun) return;
    try {
      setDownloadingPdf(true);
      const res = await flywheelApi.exportPdf(activeRun.id);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `flywheel-report-${activeRun.id.slice(0, 8)}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Failed to download PDF:', err);
      setError('Failed to download report PDF');
    } finally {
      setDownloadingPdf(false);
    }
  };

  const toggleStepExpanded = (key: string) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const isRunning = activeRun && !TERMINAL_STATES.includes(activeRun.status);
  const isSucceeded = activeRun?.status === 'succeeded';
  const steps = activeRun?.steps || [];

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Repeat size={32} className="page-icon" />
          <div>
            <h1 className="page-title">{t('flywheel.title')}</h1>
            <p className="page-description">{t('flywheel.subtitle')}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn-primary"
            onClick={handleRunFull}
            disabled={!!isRunning || job.isPolling}
          >
            {isRunning || job.isPolling ? (
              <Loader2 size={18} className="spin-icon" />
            ) : (
              <Repeat size={18} />
            )}
            {isRunning || job.isPolling ? t('common.loading') : t('flywheel.run_full')}
          </button>
          {isSucceeded && (
            <button
              className="btn-secondary"
              onClick={handleDownloadPdf}
              disabled={downloadingPdf}
            >
              {downloadingPdf ? <Loader2 size={18} className="spin-icon" /> : <Download size={18} />}
              {downloadingPdf ? 'Generating...' : 'Download Report'}
            </button>
          )}
          {isRunning && (
            <button
              className="btn-danger"
              onClick={handleCancelRun}
            >
              <StopCircle size={18} />
              {t('flywheel.stop')}
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="error-state">
          <p>{error}</p>
        </div>
      )}

      {job.isPolling && (
        <div className="info-banner">
          <Loader2 size={16} className="spin-icon" />
          <span>Starting flywheel... Status: <strong>{job.status}</strong></span>
        </div>
      )}

      {loading ? (
        <div className="loading-state">{t('common.loading')}</div>
      ) : (
        <>
          {/* Pipeline Steps */}
          <div className="flywheel-pipeline">
            {STEP_DEFS.map((def) => {
              const step = getStepStatus(steps, def.key);
              const status = step?.status || 'idle';
              const Icon = def.icon;
              const brief = getStepBrief(step);
              const isExpanded = expandedSteps.has(def.key);
              const hasArtifacts = step && step.artifacts_json && Object.keys(step.artifacts_json).length > 0;
              return (
                <div
                  key={def.key}
                  className={`flywheel-step-card status-${status}`}
                >
                  <div className={`flywheel-step-icon`}>
                    <Icon
                      size={20}
                      className={status === 'running' ? 'spin-icon' : ''}
                    />
                  </div>
                  <span className="flywheel-step-name">{t(def.labelKey)}</span>
                  <span className={`flywheel-step-status status-${status}`}>
                    {status}
                  </span>
                  {/* Brief result summary */}
                  {brief && (
                    <span className="flywheel-step-brief">{brief}</span>
                  )}
                  {/* Error message */}
                  {step?.error_message && (
                    <span className="flywheel-step-error">{step.error_message.slice(0, 120)}</span>
                  )}
                  {/* Action buttons */}
                  <div className="flywheel-step-actions">
                    {status === 'succeeded' && (
                      <button
                        className="btn-secondary flywheel-step-btn"
                        onClick={() => navigate(def.route)}
                      >
                        <Eye size={14} />
                        View
                      </button>
                    )}
                    {status === 'failed' && step && (
                      <button
                        className="btn-secondary flywheel-step-btn"
                        onClick={() => handleRetryStep(step.id)}
                      >
                        <RotateCcw size={14} />
                        Retry
                      </button>
                    )}
                    {hasArtifacts && status === 'succeeded' && (
                      <button
                        className="btn-ghost flywheel-step-btn"
                        onClick={(e) => { e.stopPropagation(); toggleStepExpanded(def.key); }}
                        title="Show details"
                      >
                        {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                      </button>
                    )}
                  </div>
                  {/* Expanded artifacts detail */}
                  {isExpanded && hasArtifacts && (
                    <div className="flywheel-step-details">
                      {Object.entries(step!.artifacts_json).map(([k, v]) => {
                        if (k === 'summary') return null; // skip nested summary
                        const val = typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);
                        return (
                          <div key={k} className="flywheel-detail-row">
                            <span className="flywheel-detail-key">{k.replace(/_/g, ' ')}</span>
                            <span className="flywheel-detail-val">{val.length > 200 ? val.slice(0, 200) + '...' : val}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Run Summary for succeeded runs */}
          {isSucceeded && activeRun && (
            <div className="flywheel-run-summary">
              <h3>Cycle Complete</h3>
              <p>
                All {steps.filter(s => s.status === 'succeeded').length} of {steps.length} steps succeeded.
                {activeRun.started_at && activeRun.finished_at && (
                  <> Duration: {Math.round((new Date(activeRun.finished_at).getTime() - new Date(activeRun.started_at).getTime()) / 1000)}s</>
                )}
              </p>
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                <button className="btn-primary" onClick={() => navigate('/opportunities')}>
                  <Lightbulb size={16} /> View Opportunities
                </button>
                <button className="btn-secondary" onClick={() => navigate('/creatives')}>
                  <Palette size={16} /> View Creatives
                </button>
                <button className="btn-secondary" onClick={handleDownloadPdf} disabled={downloadingPdf}>
                  {downloadingPdf ? <Loader2 size={16} className="spin-icon" /> : <Download size={16} />}
                  {downloadingPdf ? 'Generating PDF...' : 'Download Full Report'}
                </button>
              </div>
            </div>
          )}

          {/* Strategic Summary — LLM-powered next best action */}
          {isSucceeded && (
            <div className="flywheel-next-action">
              <h3>{t('flywheel.next_action')}</h3>
              {loadingSummary ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--color-text-muted)' }}>
                  <Loader2 size={16} className="spin-icon" />
                  <span style={{ fontSize: '13px' }}>Analyzing results...</span>
                </div>
              ) : strategicSummary ? (
                <p className="flywheel-summary-text">{strategicSummary}</p>
              ) : (
                <p style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                  Run a new flywheel cycle to generate strategic recommendations.
                </p>
              )}
              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.75rem', flexWrap: 'wrap' }}>
                <button className="btn-primary" onClick={() => navigate('/opportunities')}>
                  <Lightbulb size={14} /> View Opportunities
                </button>
                <button className="btn-secondary" onClick={() => navigate('/creatives')}>
                  <Palette size={14} /> View Creatives
                </button>
              </div>
            </div>
          )}

          {/* Recent Runs */}
          <section style={{ marginTop: 'var(--spacing-xl)' }}>
            <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: 'var(--spacing-md)' }}>
              {t('flywheel.recent_runs')}
            </h2>
            {runs.length === 0 ? (
              <div className="empty-state">
                <Repeat size={48} />
                <p>{t('flywheel.no_runs')}</p>
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="flywheel-runs-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Status</th>
                      <th>Trigger</th>
                      <th>Steps</th>
                      <th>Started</th>
                      <th>Finished</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr
                        key={run.id}
                        style={{ cursor: 'pointer', background: run.id === activeRun?.id ? 'var(--sand-100, #f5f0e8)' : undefined }}
                        onClick={() => {
                          setActiveRun(run);
                          if (!TERMINAL_STATES.includes(run.status)) {
                            setPollingRunId(run.id);
                          }
                        }}
                      >
                        <td style={{ fontFamily: 'monospace', fontSize: '12px' }}>
                          {run.id.slice(0, 8)}...
                        </td>
                        <td>
                          <span className={`flywheel-step-status status-${run.status}`}>
                            {run.status}
                          </span>
                        </td>
                        <td>{run.trigger}</td>
                        <td>{run.steps?.length || 0}</td>
                        <td>
                          {run.started_at
                            ? new Date(run.started_at).toLocaleString()
                            : '-'}
                        </td>
                        <td>
                          {run.finished_at
                            ? new Date(run.finished_at).toLocaleString()
                            : '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
