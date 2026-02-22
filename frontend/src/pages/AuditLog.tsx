import { useState, useEffect, useCallback } from 'react';
import { ScrollText, Clock, User, CheckCircle, XCircle, Play, Filter } from 'lucide-react';
import { auditApi, AuditEntry, AuditStats } from '../services/api';
import './AuditLog.css';

const STATUS_OPTIONS = [
  { value: '', label: 'All Statuses' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'dry_run', label: 'Dry Run' },
];

const ACTION_TYPE_OPTIONS = [
  { value: '', label: 'All Actions' },
  { value: 'budget_change', label: 'Budget Change' },
  { value: 'adset_pause', label: 'Adset Pause' },
  { value: 'creative_swap', label: 'Creative Swap' },
  { value: 'bid_change', label: 'Bid Change' },
  { value: 'adset_duplicate', label: 'Adset Duplicate' },
];

export default function AuditLog() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [stats, setStats] = useState<AuditStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState('');
  const [actionTypeFilter, setActionTypeFilter] = useState('');

  const fetchAuditLog = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params: Record<string, string> = {};
      if (statusFilter) params.status = statusFilter;
      if (actionTypeFilter) params.action_type = actionTypeFilter;

      const res = await auditApi.list(params);
      setEntries(res.data);
    } catch (err) {
      console.error('Failed to fetch audit log:', err);
      setError('Failed to load audit log. Please check if the backend is running.');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, actionTypeFilter]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await auditApi.stats(7);
      setStats(res.data);
    } catch {
      // Stats are non-critical
    }
  }, []);

  useEffect(() => {
    fetchAuditLog();
    fetchStats();
  }, [fetchAuditLog, fetchStats]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
        return <CheckCircle size={18} className="status-icon-success" />;
      case 'failed':
        return <XCircle size={18} className="status-icon-failed" />;
      case 'dry_run':
        return <Play size={18} className="status-icon-dryrun" />;
      default:
        return null;
    }
  };

  const getStatusClass = (status: string) => {
    return `audit-status status-${status}`;
  };

  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);

    if (diffMins < 60) {
      return `${diffMins} minutes ago`;
    } else if (diffHours < 24) {
      return `${diffHours} hours ago`;
    } else {
      return date.toLocaleString();
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <ScrollText size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Audit Log</h1>
            <p className="page-description">
              Complete history of all automated actions
            </p>
          </div>
        </div>
      </div>

      {stats && (
        <div className="audit-stats">
          <div className="audit-stat-card">
            <span className="audit-stat-value">{stats.total_executions}</span>
            <span className="audit-stat-label">Total ({stats.period_days}d)</span>
          </div>
          <div className="audit-stat-card stat-success">
            <span className="audit-stat-value">{stats.successful}</span>
            <span className="audit-stat-label">Successful</span>
          </div>
          <div className="audit-stat-card stat-failed">
            <span className="audit-stat-value">{stats.failed}</span>
            <span className="audit-stat-label">Failed</span>
          </div>
          <div className="audit-stat-card stat-dryrun">
            <span className="audit-stat-value">{stats.dry_run}</span>
            <span className="audit-stat-label">Dry Run</span>
          </div>
        </div>
      )}

      <div className="audit-filters">
        <Filter size={16} />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="audit-filter-select"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
        <select
          value={actionTypeFilter}
          onChange={(e) => setActionTypeFilter(e.target.value)}
          className="audit-filter-select"
        >
          {ACTION_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="loading-state">Loading audit log...</div>
      ) : error ? (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={fetchAuditLog} className="btn-secondary">Retry</button>
        </div>
      ) : (
        <div className="audit-list">
          {entries.map((entry) => (
            <div key={entry.id} className="audit-card">
              <div className="audit-header">
                <div className="audit-meta">
                  <Clock size={16} />
                  <span className="audit-time">{formatTimestamp(entry.timestamp)}</span>
                  <User size={16} />
                  <span className="audit-user">{entry.user_email}</span>
                </div>
                <div className={getStatusClass(entry.status)}>
                  {getStatusIcon(entry.status)}
                  <span>{entry.status.replace('_', ' ').toUpperCase()}</span>
                </div>
              </div>

              <div className="audit-action">
                <strong>{entry.action_type.replace('_', ' ')}</strong>
                <span className="audit-entity">
                  on {entry.entity_type}: <code>{entry.entity_id}</code>
                </span>
              </div>

              {expandedId === entry.id && (
                <div className="audit-changes">
                  <strong>Changes:</strong>
                  <pre>{JSON.stringify(entry.changes, null, 2)}</pre>
                  {entry.error_message && (
                    <div className="audit-error">
                      <strong>Error:</strong> {entry.error_message}
                    </div>
                  )}
                </div>
              )}

              <div className="audit-footer">
                <span className="audit-trace">Trace ID: {entry.trace_id}</span>
                <button
                  className="btn-text"
                  onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                >
                  {expandedId === entry.id ? 'Hide Details' : 'View Details'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && !error && entries.length === 0 && (
        <div className="empty-state">
          <ScrollText size={48} />
          <h3>No audit entries yet</h3>
          <p>Executed actions will appear here</p>
        </div>
      )}
    </div>
  );
}
