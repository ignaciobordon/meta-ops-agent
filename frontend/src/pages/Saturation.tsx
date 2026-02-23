import { useState, useEffect, useRef } from 'react';
import { TrendingUp, AlertTriangle, CheckCircle, TrendingDown, Upload, ChevronDown, ChevronUp, FileDown, Loader, Database } from 'lucide-react';
import { saturationApi, SaturationMetric } from '../services/api';
import { downloadBlob } from '../utils/download';
import './Saturation.css';

export default function Saturation() {
  const [metrics, setMetrics] = useState<SaturationMetric[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [loadingMeta, setLoadingMeta] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set());
  const [downloadingReport, setDownloadingReport] = useState<string | null>(null);
  const [reportError, setReportError] = useState<string | null>(null);
  const [_dataSource, setDataSource] = useState<'demo' | 'meta' | 'csv'>('demo');
  const fileInputRef = useRef<HTMLInputElement>(null);

  const toggleExpanded = (id: string) => {
    setExpandedCards(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const getComponentColor = (score: number) => {
    if (score < 30) return 'var(--olive-500)';
    if (score < 60) return 'var(--gold-500)';
    return 'var(--terracotta-500)';
  };

  const formatMoney = (n: number) => `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const formatNum = (n: number) => n.toLocaleString('en-US');

  useEffect(() => {
    fetchSaturation();
  }, []);

  const fetchSaturation = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await saturationApi.analyze();
      setMetrics(res.data);
    } catch (err) {
      console.error('Failed to fetch saturation data:', err);
      setError('Failed to load saturation analysis. Please check if the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      setUploading(true);
      setError(null);
      const res = await saturationApi.uploadCsv(file);
      setMetrics(res.data);
    } catch (err: any) {
      const detail = err.response?.data?.detail || 'Failed to upload and analyze CSV.';
      setError(detail);
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleLoadFromMeta = async (days: number = 30) => {
    try {
      setLoadingMeta(true);
      setError(null);
      const res = await saturationApi.analyzeMeta(days);
      setMetrics(res.data);
      setDataSource('meta');
    } catch (err: any) {
      const detail = err.response?.data?.detail || 'Failed to load Meta data. Make sure Meta sync has run.';
      setError(detail);
    } finally {
      setLoadingMeta(false);
    }
  };

  const handleDownloadReport = async (metric: SaturationMetric) => {
    try {
      setDownloadingReport(metric.angle_id);
      setReportError(null);
      const res = await saturationApi.downloadReport(metric);
      const safeName = metric.angle_name.replace(/\s+/g, '_').substring(0, 40);
      downloadBlob(res.data, `saturation_report_${safeName}.pdf`, 'application/pdf');
    } catch (err: any) {
      console.error('Failed to download report:', err);
      setReportError(`Failed to generate report for "${metric.angle_name}". Please try again.`);
    } finally {
      setDownloadingReport(null);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'fresh':
        return <CheckCircle size={20} className="status-icon-fresh" />;
      case 'moderate':
        return <TrendingDown size={20} className="status-icon-moderate" />;
      case 'saturated':
        return <AlertTriangle size={20} className="status-icon-saturated" />;
      default:
        return null;
    }
  };

  const getStatusClass = (status: string) => {
    return `saturation-status status-${status}`;
  };

  const isLoading = loading || uploading || loadingMeta;

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <TrendingUp size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Saturation Analysis</h1>
            <p className="page-description">
              Monitor angle performance and audience fatigue
            </p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn-primary"
            onClick={() => handleLoadFromMeta(30)}
            disabled={loadingMeta}
          >
            <Database size={18} />
            {loadingMeta ? 'Loading Meta...' : 'Load from Meta Data'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            onChange={handleFileChange}
            style={{ display: 'none' }}
          />
          <button
            className="btn-secondary"
            onClick={handleUploadClick}
            disabled={uploading}
          >
            <Upload size={18} />
            {uploading ? 'Uploading...' : 'Upload CSV'}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="loading-state">
          {loadingMeta ? 'Loading from Meta insights...' : uploading ? 'Analyzing uploaded CSV...' : 'Analyzing saturation...'}
        </div>
      ) : error ? (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={fetchSaturation} className="btn-secondary">Retry</button>
        </div>
      ) : (
        <div className="saturation-list">
          {reportError && (
            <div className="report-error-banner">
              <AlertTriangle size={16} />
              <span>{reportError}</span>
              <button onClick={() => setReportError(null)} className="dismiss-btn">&times;</button>
            </div>
          )}
          {metrics.map((metric) => (
            <div key={metric.angle_id} className="saturation-card">
              <div className="saturation-header">
                <div>
                  <h3 className="saturation-angle">{metric.angle_name}</h3>
                  <span className="saturation-id">#{metric.angle_id}</span>
                </div>
                <div className={getStatusClass(metric.status)}>
                  {getStatusIcon(metric.status)}
                  <span>{metric.status.toUpperCase()}</span>
                </div>
              </div>

              <div className="saturation-metrics">
                <div className="metric">
                  <span className="metric-label">Saturation Score</span>
                  <div className="metric-bar">
                    <div
                      className="metric-bar-fill"
                      style={{
                        width: `${metric.saturation_score * 100}%`,
                        backgroundColor:
                          metric.saturation_score < 0.4
                            ? 'var(--olive-500)'
                            : metric.saturation_score < 0.7
                            ? 'var(--gold-500)'
                            : 'var(--terracotta-500)',
                      }}
                    />
                  </div>
                  <span className="metric-value">
                    {(metric.saturation_score * 100).toFixed(0)}%
                  </span>
                </div>

                <div className="metric-row">
                  <div className="metric-item">
                    <span className="metric-label">CTR Trend</span>
                    <span
                      className={`metric-value ${
                        metric.ctr_trend > 0 ? 'positive' : 'negative'
                      }`}
                    >
                      {metric.ctr_trend > 0 ? '+' : ''}
                      {(metric.ctr_trend * 100).toFixed(1)}%
                    </span>
                  </div>
                  <div className="metric-item">
                    <span className="metric-label">Frequency</span>
                    <span className="metric-value">{metric.frequency.toFixed(1)}x</span>
                  </div>
                </div>
              </div>

              <div className="saturation-recommendation">
                <strong>Recommendation:</strong> {metric.recommendation}
              </div>

              <div className="saturation-actions">
                <button
                  className="saturation-detail-toggle"
                  onClick={() => toggleExpanded(metric.angle_id)}
                >
                  {expandedCards.has(metric.angle_id) ? (
                    <><ChevronUp size={16} /> Hide detailed analysis</>
                  ) : (
                    <><ChevronDown size={16} /> View detailed analysis</>
                  )}
                </button>

                <button
                  className="btn-download-report"
                  onClick={() => handleDownloadReport(metric)}
                  disabled={downloadingReport === metric.angle_id}
                >
                  {downloadingReport === metric.angle_id ? (
                    <><Loader size={14} className="spin-icon" /> Generating PDF...</>
                  ) : (
                    <><FileDown size={14} /> Download Analysis PDF</>
                  )}
                </button>
              </div>

              {expandedCards.has(metric.angle_id) && (
                <div className="saturation-detail">
                  <div className="detail-grid">
                    <div className="detail-item">
                      <span className="detail-label">CTR Current</span>
                      <span className="detail-value">{metric.ctr_recent?.toFixed(2)}%</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">CTR Peak</span>
                      <span className="detail-value">{metric.ctr_peak?.toFixed(2)}%</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">CPM Current</span>
                      <span className="detail-value">{formatMoney(metric.cpm_recent || 0)}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">CPM Baseline</span>
                      <span className="detail-value">{formatMoney(metric.cpm_baseline || 0)}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">Total Spend</span>
                      <span className="detail-value">{formatMoney(metric.total_spend || 0)}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">Impressions</span>
                      <span className="detail-value">{formatNum(metric.total_impressions || 0)}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">Days Active</span>
                      <span className="detail-value">{metric.days_active || 0}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">Spend Share</span>
                      <span className="detail-value">{(metric.spend_share_pct || 0).toFixed(1)}%</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-label">Frequency</span>
                      <span className="detail-value">{metric.frequency?.toFixed(2)}x</span>
                    </div>
                  </div>

                  <div className="component-scores">
                    <h4>Score Breakdown (weight → score)</h4>
                    <div className="component-bar">
                      <span className="component-label">Frequency (35%)</span>
                      <div className="component-track">
                        <div className="component-fill" style={{ width: `${metric.frequency_score || 0}%`, backgroundColor: getComponentColor(metric.frequency_score || 0) }} />
                      </div>
                      <span className="component-val">{(metric.frequency_score || 0).toFixed(0)}</span>
                    </div>
                    <div className="component-bar">
                      <span className="component-label">CTR Decay (35%)</span>
                      <div className="component-track">
                        <div className="component-fill" style={{ width: `${metric.ctr_decay_score || 0}%`, backgroundColor: getComponentColor(metric.ctr_decay_score || 0) }} />
                      </div>
                      <span className="component-val">{(metric.ctr_decay_score || 0).toFixed(0)}</span>
                    </div>
                    <div className="component-bar">
                      <span className="component-label">CPM Inflation (30%)</span>
                      <div className="component-track">
                        <div className="component-fill" style={{ width: `${metric.cpm_inflation_score || 0}%`, backgroundColor: getComponentColor(metric.cpm_inflation_score || 0) }} />
                      </div>
                      <span className="component-val">{(metric.cpm_inflation_score || 0).toFixed(0)}</span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
