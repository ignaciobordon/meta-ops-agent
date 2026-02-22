/**
 * Sprint 8 — Alert Center page.
 * Unified alert list with acknowledge/resolve/snooze actions.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileDown, Zap } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { alertsApi } from '../services/api';
import './AlertCenter.css';

interface Alert {
  id: string;
  alert_type: string;
  severity: string;
  message: string;
  entity_type: string | null;
  entity_meta_id: string | null;
  detected_at: string;
  resolved_at: string | null;
  status: string;
  acknowledged_at: string | null;
  payload: Record<string, any> | null;
}

interface AlertStats {
  total: number;
  by_severity: Record<string, number>;
  by_status: Record<string, number>;
}

export default function AlertCenter() {
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [stats, setStats] = useState<AlertStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [exportingPdf, setExportingPdf] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [aRes, sRes] = await Promise.all([
        alertsApi.list({
          status: statusFilter || undefined,
          severity: severityFilter || undefined,
          limit: 100,
        }),
        alertsApi.getStats(),
      ]);
      setAlerts(aRes.data.data || []);
      setStats(sRes.data);
    } catch {
      // Silent failure
    } finally {
      setLoading(false);
    }
  }, [statusFilter, severityFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleAcknowledge = async (id: string) => {
    await alertsApi.acknowledge(id);
    fetchData();
  };

  const handleResolve = async (id: string) => {
    await alertsApi.resolve(id);
    fetchData();
  };

  const handleSnooze = async (id: string) => {
    await alertsApi.snooze(id);
    fetchData();
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      const res = await alertsApi.exportPdf({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
      });
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = 'alerts_report.pdf';
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

  if (loading) {
    return <div className="alerts-loading">{t('common.loading')}</div>;
  }

  return (
    <div className="alert-center">
      <div className="alerts-header">
        <div>
          <h1>{t('alerts.title')}</h1>
          <p>{t('alerts.subtitle')}</p>
        </div>
        <button
          onClick={handleExportPdf}
          disabled={exportingPdf}
          style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 16px', border: '1px solid var(--border)', borderRadius: '8px', background: 'var(--bg-card)', cursor: 'pointer', fontSize: '13px' }}
        >
          <FileDown size={16} />
          {exportingPdf ? 'Exporting...' : 'Export PDF'}
        </button>
      </div>

      {/* Stats Bar */}
      {stats && (
        <div className="alerts-stats">
          <div className="stat-pill stat-critical">
            {t('alerts.critical')}: {stats.by_severity.critical || 0}
          </div>
          <div className="stat-pill stat-high">
            {t('alerts.high')}: {stats.by_severity.high || 0}
          </div>
          <div className="stat-pill stat-medium">
            {t('alerts.medium')}: {stats.by_severity.medium || 0}
          </div>
          <div className="stat-pill stat-low">
            {t('alerts.low')}: {stats.by_severity.low || 0}
          </div>
          <div className="stat-pill stat-total">
            {t('alerts.total')}: {stats.total}
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="alerts-filters">
        <select
          className="alert-filter-select"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
        >
          <option value="">{t('alerts.all_status')}</option>
          <option value="active">{t('alerts.status_active')}</option>
          <option value="acknowledged">{t('alerts.status_ack')}</option>
          <option value="resolved">{t('alerts.status_resolved')}</option>
          <option value="snoozed">{t('alerts.status_snoozed')}</option>
        </select>
        <select
          className="alert-filter-select"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
        >
          <option value="">{t('alerts.all_severity')}</option>
          <option value="critical">{t('alerts.critical')}</option>
          <option value="high">{t('alerts.high')}</option>
          <option value="medium">{t('alerts.medium')}</option>
          <option value="low">{t('alerts.low')}</option>
        </select>
      </div>

      {/* Alert List */}
      <div className="alerts-list">
        {alerts.length === 0 ? (
          <div className="alerts-empty">{t('common.no_data')}</div>
        ) : (
          alerts.map((alert) => (
            <div key={alert.id} className="alert-item">
              <div
                className="alert-item-header"
                onClick={() => setExpandedId(expandedId === alert.id ? null : alert.id)}
              >
                <div className="alert-item-left">
                  <span className={`alert-severity-badge severity-${alert.severity}`}>
                    {alert.severity}
                  </span>
                  <span className="alert-type-badge">{alert.alert_type}</span>
                  <span className="alert-message">{alert.message}</span>
                </div>
                <div className="alert-item-right">
                  <span className={`alert-status-badge alert-status-${alert.status}`}>
                    {alert.status}
                  </span>
                  <span className="alert-time">
                    {alert.detected_at ? new Date(alert.detected_at).toLocaleString() : ''}
                  </span>
                </div>
              </div>

              {expandedId === alert.id && (
                <div className="alert-item-detail">
                  {alert.entity_type && (
                    <div className="alert-detail-field">
                      <label>{t('alerts.entity')}</label>
                      <span>{alert.entity_type}: {alert.entity_meta_id || '-'}</span>
                    </div>
                  )}
                  {alert.payload && Object.keys(alert.payload).length > 0 && (
                    <div className="alert-detail-field">
                      <label>{t('alerts.payload')}</label>
                      <pre>{JSON.stringify(alert.payload, null, 2)}</pre>
                    </div>
                  )}
                  {/* Suggested Actions */}
                  {alert.payload?.suggested_actions && alert.payload.suggested_actions.length > 0 && (
                    <div className="alert-detail-field" style={{ marginBottom: '0.75rem' }}>
                      <label>Suggested Actions</label>
                      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.25rem' }}>
                        {alert.payload.suggested_actions.map((action: string, i: number) => (
                          <span key={i} style={{
                            padding: '4px 10px', borderRadius: '12px', fontSize: '12px',
                            background: 'var(--olive-50, #f4f6ef)', color: 'var(--olive-700, #5c6b3a)',
                            border: '1px solid var(--olive-200, #c8d4a8)',
                          }}>
                            {action}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="alert-actions">
                    {/* Create Decision from Alert */}
                    <button
                      className="alert-btn"
                      style={{ background: 'var(--olive-500, #8b9857)', color: 'white', border: 'none' }}
                      onClick={() => {
                        const actionType = alert.alert_type.includes('budget') || alert.alert_type.includes('spend')
                          ? 'budget_change'
                          : alert.alert_type.includes('ctr') || alert.alert_type.includes('creative')
                          ? 'creative_swap'
                          : 'adset_pause';
                        const entityType = alert.entity_type || 'adset';
                        navigate(`/control-panel?action_type=${actionType}&entity_type=${entityType}&entity_id=${alert.entity_meta_id || ''}&entity_name=${encodeURIComponent(alert.message.substring(0, 60))}&rationale=${encodeURIComponent(`[Alert: ${alert.severity}/${alert.alert_type}] ${alert.message}`)}&source=alerts`);
                      }}
                    >
                      <Zap size={14} />
                      Crear Decisión
                    </button>

                    {alert.status === 'active' && (
                      <button className="alert-btn alert-btn-ack" onClick={() => handleAcknowledge(alert.id)}>
                        {t('alerts.acknowledge')}
                      </button>
                    )}
                    {(alert.status === 'active' || alert.status === 'acknowledged') && (
                      <>
                        <button className="alert-btn alert-btn-resolve" onClick={() => handleResolve(alert.id)}>
                          {t('alerts.resolve')}
                        </button>
                        <button className="alert-btn alert-btn-snooze" onClick={() => handleSnooze(alert.id)}>
                          {t('alerts.snooze')}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
