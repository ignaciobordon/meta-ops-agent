import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { Lightbulb, Target, ArrowRight, Loader, RefreshCw, Sparkles, FileDown, User } from 'lucide-react';
import { opportunitiesApi, brandMapApi, BrandMapProfile, Opportunity } from '../services/api';
import { useJobPolling } from '../hooks/useJobPolling';
import './Opportunities.css';

export default function Opportunities() {
  const navigate = useNavigate();
  const [opportunities, setOpportunities] = useState<Opportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [brandProfiles, setBrandProfiles] = useState<BrandMapProfile[]>([]);
  const [selectedProfileId, setSelectedProfileId] = useState<string>('');

  const job = useJobPolling(jobId, 2000, 300000); // 5 min timeout for analysis
  const prevStatusRef = useRef<string | null>(null);

  useEffect(() => {
    fetchOpportunities();
    brandMapApi.list().then(res => {
      setBrandProfiles(res.data);
      if (res.data.length > 0) setSelectedProfileId(res.data[0].id);
    }).catch(() => {});
  }, []);

  // Auto-refetch when analysis job succeeds
  useEffect(() => {
    if (prevStatusRef.current !== job.status && job.status === 'succeeded') {
      setJobId(null);
      fetchOpportunities();
    }
    if (job.error) {
      setError(job.error);
      setJobId(null);
    }
    prevStatusRef.current = job.status;
  }, [job.status, job.error]);

  const fetchOpportunities = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await opportunitiesApi.list();
      setOpportunities(res.data);
    } catch (err: any) {
      console.error('Failed to fetch opportunities:', err);
      const detail = err.response?.data?.detail || 'Failed to load opportunities.';
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  const handleAnalyze = async () => {
    try {
      setError(null);
      const res = await opportunitiesApi.analyzeUnified(selectedProfileId || undefined);
      setJobId(res.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start analysis');
    }
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      const res = await opportunitiesApi.exportPdf();
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `opportunities_report.pdf`;
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

  const getPriorityClass = (priority: string) => {
    return `opportunity-priority priority-${priority}`;
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Lightbulb size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Market Opportunities</h1>
            <p className="page-description">
              Strategic gaps identified from competitive analysis
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {brandProfiles.length > 0 && (
            <select
              value={selectedProfileId}
              onChange={(e) => setSelectedProfileId(e.target.value)}
              style={{
                padding: '0.5rem 0.75rem',
                borderRadius: '8px',
                border: '1px solid var(--sand-300, #d4cfc4)',
                background: 'var(--sand-50, #faf8f5)',
                fontSize: '0.875rem',
                minWidth: '180px',
              }}
            >
              {brandProfiles.map((p) => (
                <option key={p.id} value={p.id}>{p.name}</option>
              ))}
            </select>
          )}
          {brandProfiles.length === 0 && (
            <button
              className="btn-secondary"
              onClick={() => navigate('/brand-profile')}
              style={{ fontSize: '0.8rem' }}
            >
              <User size={14} />
              Create Brand Profile
            </button>
          )}
          <button className="btn-primary" onClick={handleAnalyze} disabled={job.isPolling}>
            {job.isPolling ? <Loader size={18} className="spin-icon" /> : <RefreshCw size={18} />}
            {job.isPolling ? 'Analyzing...' : 'Analyze'}
          </button>
          {opportunities.length > 0 && (
            <button className="btn-secondary" onClick={handleExportPdf} disabled={exportingPdf}>
              <FileDown size={18} />
              {exportingPdf ? 'Exporting...' : 'Export PDF'}
            </button>
          )}
        </div>
      </div>

      {job.isPolling && (
        <div className="info-banner">
          <Loader size={16} className="spin-icon" />
          <span>Running market analysis… Status: <strong>{job.status}</strong></span>
        </div>
      )}

      {loading ? (
        <div className="loading-state">Analyzing opportunities...</div>
      ) : error ? (
        <div className="error-state">
          <p>{error}</p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', justifyContent: 'center' }}>
            <button onClick={handleAnalyze} className="btn-primary">Retry Analysis</button>
            <button onClick={fetchOpportunities} className="btn-secondary">Refresh List</button>
          </div>
        </div>
      ) : (
        <div className="opportunities-list">
          {opportunities.map((opp) => (
            <div key={opp.id} className="opportunity-card">
              <div className="opportunity-header">
                <div>
                  <div className={getPriorityClass(opp.priority)}>
                    <Target size={14} />
                    {opp.priority.toUpperCase()} PRIORITY
                  </div>
                  <h3 className="opportunity-title">{opp.title}</h3>
                </div>
                <div className="opportunity-impact">
                  <span className="impact-label">Est. Impact</span>
                  <span className="impact-value">
                    {(opp.estimated_impact * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              <p className="opportunity-description">{opp.description}</p>

              <div className="opportunity-strategy">
                <div className="strategy-icon">
                  <ArrowRight size={18} />
                </div>
                <div>
                  <strong>Recommended Strategy:</strong>
                  <p>{opp.strategy}</p>
                </div>
              </div>

              {opp.impact_reasoning && (
                <div className="opportunity-impact-reasoning">
                  <strong>Impact Analysis:</strong> {opp.impact_reasoning}
                </div>
              )}

              <div className="opportunity-footer">
                <span className="opportunity-id">Gap ID: {opp.gap_id}</span>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="btn-primary"
                    onClick={() => navigate(`/creatives?angle=${opp.gap_id}&brief=${encodeURIComponent(opp.title)}`)}
                  >
                    <Sparkles size={14} />
                    Generate Creative
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => navigate(`/control-panel?action_type=budget_change&entity_type=campaign&entity_name=${encodeURIComponent(opp.title)}&rationale=${encodeURIComponent(`[Opportunity: ${opp.priority}] ${opp.strategy}`)}&source=opportunities`)}
                  >
                    Create Campaign
                  </button>
                </div>
              </div>
            </div>
          ))}
          {opportunities.length === 0 && (
            <div className="empty-state" style={{ textAlign: 'center', padding: '3rem' }}>
              <Lightbulb size={48} style={{ opacity: 0.3, margin: '0 auto var(--spacing-lg)', display: 'block' }} />
              <h3>No opportunities found</h3>
              <p style={{ color: 'var(--gray-500)', marginBottom: 'var(--spacing-lg)' }}>
                Run the Flywheel or click Analyze to discover market opportunities.
              </p>
              <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
                <button className="btn-primary" onClick={() => navigate('/flywheel')}>
                  <RefreshCw size={16} /> Run Flywheel
                </button>
                <button className="btn-secondary" onClick={handleAnalyze} disabled={job.isPolling}>
                  Analyze Now
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
