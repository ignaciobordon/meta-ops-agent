import { useEffect, useState } from 'react';
import { decisionsApi, dashboardApi, metaSyncApi, Decision, DashboardKPI, SyncStatus, MetaAlertItem, MetaCampaignItem } from '../services/api';
import { useLanguage } from '../contexts/LanguageContext';
import { TrendingUp, TrendingDown, AlertCircle, RefreshCw, AlertTriangle, Zap } from 'lucide-react';
import './Dashboard.css';

export default function Dashboard() {
  const { t } = useLanguage();
  const [recentDecisions, setRecentDecisions] = useState<Decision[]>([]);
  const [kpis, setKpis] = useState<DashboardKPI[]>([]);
  const [syncStatus, setSyncStatus] = useState<SyncStatus[]>([]);
  const [alerts, setAlerts] = useState<MetaAlertItem[]>([]);
  const [campaigns, setCampaigns] = useState<MetaCampaignItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
    try {
      setError(null);
      setLoading(true);

      const [kpiRes, decisionsRes, syncRes, alertsRes, campaignsRes] = await Promise.allSettled([
        dashboardApi.getKpis(1),
        decisionsApi.list({ limit: 10 }),
        metaSyncApi.getSyncStatus(),
        metaSyncApi.getAlerts({ limit: 5 }),
        metaSyncApi.getCampaigns(),
      ]);

      if (kpiRes.status === 'fulfilled') setKpis(kpiRes.value.data.kpis);
      if (decisionsRes.status === 'fulfilled') setRecentDecisions(decisionsRes.value.data);
      if (syncRes.status === 'fulfilled') setSyncStatus(syncRes.value.data);
      if (alertsRes.status === 'fulfilled') setAlerts(alertsRes.value.data);
      if (campaignsRes.status === 'fulfilled') setCampaigns(campaignsRes.value.data);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      setError('Failed to load dashboard data. Backend may be offline.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="dashboard">
      <div className="dashboard-header">
        <h1>{t('dashboard.title')}</h1>
        <p className="subtitle">War Room — {new Date().toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</p>
      </div>

      {loading ? (
        <p>{t('common.loading')}</p>
      ) : error ? (
        <div className="empty-state card">
          <AlertCircle size={24} />
          <p>{error}</p>
          <button className="btn-secondary" onClick={loadDashboard}>Retry</button>
        </div>
      ) : (
        <>
          <div className="kpi-grid">
            {kpis.map((kpi) => (
              <div key={kpi.label} className="kpi-card card">
                <div className="kpi-label">{kpi.label}</div>
                <div className="kpi-value">{kpi.value}</div>
                {kpi.change && (
                  <div className={`kpi-change ${kpi.trend}`}>
                    {kpi.trend === 'up' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                    <span>{kpi.change}</span>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Sprint 6: Sync Health Widget */}
          {syncStatus.length > 0 && (
            <div className="dashboard-widget">
              <div className="widget-header">
                <h2><RefreshCw size={18} /> {t('dashboard.sync_health')}</h2>
              </div>
              <div className="sync-grid">
                {syncStatus.map((s) => (
                  <div key={s.ad_account_id} className="sync-card card">
                    <div className="sync-account">{s.meta_account_id || 'Unknown'}</div>
                    <div className="sync-stats">
                      <div className="sync-stat">
                        <span className="sync-label">{t('dashboard.assets_lag')}</span>
                        <span className={`sync-value ${(s.assets_lag_minutes || 0) > 30 ? 'lag-warning' : 'lag-ok'}`}>
                          {s.assets_lag_minutes != null ? `${s.assets_lag_minutes}m` : '—'}
                        </span>
                      </div>
                      <div className="sync-stat">
                        <span className="sync-label">{t('dashboard.insights_lag')}</span>
                        <span className={`sync-value ${(s.insights_lag_minutes || 0) > 60 ? 'lag-warning' : 'lag-ok'}`}>
                          {s.insights_lag_minutes != null ? `${s.insights_lag_minutes}m` : '—'}
                        </span>
                      </div>
                      <div className="sync-stat">
                        <span className="sync-label">{t('dashboard.errors')}</span>
                        <span className={`sync-value ${s.recent_error_count > 0 ? 'lag-warning' : 'lag-ok'}`}>
                          {s.recent_error_count}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sprint 6: Active Alerts Widget */}
          {alerts.length > 0 && (
            <div className="dashboard-widget">
              <div className="widget-header">
                <h2><AlertTriangle size={18} /> {t('dashboard.active_alerts')}</h2>
              </div>
              <div className="alert-list">
                {alerts.map((a) => (
                  <div key={a.id} className={`alert-card card alert-${a.severity}`}>
                    <div className="alert-header-row">
                      <span className={`alert-severity-badge severity-${a.severity}`}>
                        {a.severity.toUpperCase()}
                      </span>
                      <span className="alert-type">{a.alert_type.replace(/_/g, ' ')}</span>
                      <span className="alert-time">
                        {new Date(a.detected_at).toLocaleString()}
                      </span>
                    </div>
                    <p className="alert-message">{a.message}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sprint 6: Campaign Performance Table */}
          {campaigns.length > 0 && (
            <div className="dashboard-widget">
              <div className="widget-header">
                <h2><Zap size={18} /> {t('dashboard.campaigns')}</h2>
              </div>
              <div className="campaign-table-wrap">
                <table className="campaign-table">
                  <thead>
                    <tr>
                      <th>{t('dashboard.campaign_name')}</th>
                      <th>{t('dashboard.campaign_status')}</th>
                      <th>{t('dashboard.campaign_objective')}</th>
                      <th>{t('dashboard.campaign_budget')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {campaigns.slice(0, 10).map((c) => (
                      <tr key={c.id}>
                        <td className="campaign-name">{c.name || '—'}</td>
                        <td>
                          <span className={`badge badge-${getStatusClass(c.effective_status)}`}>
                            {c.effective_status || c.status || '—'}
                          </span>
                        </td>
                        <td>{c.objective || '—'}</td>
                        <td>{c.daily_budget ? `$${c.daily_budget.toFixed(2)}/d` : c.lifetime_budget ? `$${c.lifetime_budget.toFixed(0)} LT` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div className="recent-section">
            <h2>Recent Decisions</h2>
            {recentDecisions.length === 0 ? (
              <div className="empty-state card">
                <p>No decisions yet. Create one from the Control Panel.</p>
              </div>
            ) : (
              <div className="decision-list">
                {recentDecisions.slice(0, 5).map((decision) => (
                  <div key={decision.id} className="decision-card card">
                    <div className="decision-header">
                      <span className={`badge badge-${getStateBadgeClass(decision.state)}`}>
                        {decision.state.replace('_', ' ')}
                      </span>
                      <span className="decision-time">
                        {new Date(decision.created_at).toLocaleString()}
                      </span>
                    </div>
                    <h3 className="decision-title">
                      {decision.action_type.replace('_', ' ')} — {decision.entity_name}
                    </h3>
                    <p className="decision-rationale">{decision.rationale || 'No rationale provided'}</p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

function getStateBadgeClass(state: string): string {
  if (['executed', 'approved'].includes(state)) return 'success';
  if (['failed', 'blocked', 'rejected'].includes(state)) return 'error';
  if (['pending_approval', 'validating'].includes(state)) return 'warning';
  return 'info';
}

function getStatusClass(status: string | null): string {
  if (!status) return 'info';
  const s = status.toUpperCase();
  if (['ACTIVE'].includes(s)) return 'success';
  if (['PAUSED', 'PENDING_REVIEW'].includes(s)) return 'warning';
  if (['DELETED', 'ARCHIVED', 'DISAPPROVED'].includes(s)) return 'error';
  return 'info';
}
