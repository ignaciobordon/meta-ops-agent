/**
 * Sprint 7 — Ops Console page.
 * Queue stats, provider health, job runs table with retry/cancel.
 */
import { useState, useEffect, useCallback } from 'react';
import { useLanguage } from '../contexts/LanguageContext';
import { opsApi, JobRunItem, ProviderStatus, QueueStats } from '../services/api';
import './OpsConsole.css';

export default function OpsConsole() {
  const { t } = useLanguage();

  const [queues, setQueues] = useState<QueueStats[]>([]);
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [jobs, setJobs] = useState<JobRunItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [selectedJob, setSelectedJob] = useState<JobRunItem | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [qRes, pRes, jRes] = await Promise.all([
        opsApi.listQueues(),
        opsApi.listProviders(),
        opsApi.listJobs({
          status: statusFilter || undefined,
          job_type: typeFilter || undefined,
          limit: 100,
        }),
      ]);
      setQueues(qRes.data);
      setProviders(pRes.data);
      setJobs(jRes.data);
    } catch {
      // API errors handled silently for admin page
    } finally {
      setLoading(false);
    }
  }, [statusFilter, typeFilter]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 15000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const handleRetry = async (id: string) => {
    await opsApi.retryJob(id);
    fetchData();
  };

  const handleCancel = async (id: string) => {
    await opsApi.cancelJob(id);
    fetchData();
  };

  if (loading) {
    return <div className="ops-loading">{t('common.loading')}</div>;
  }

  return (
    <div className="ops-console">
      {/* Header */}
      <div className="ops-header">
        <h1>{t('ops.title')}</h1>
        <p>{t('ops.subtitle')}</p>
      </div>

      {/* Queue Stats */}
      <div className="ops-queues">
        {queues.map((q) => (
          <div className="queue-card" key={q.queue_name}>
            <h3>{q.queue_name}</h3>
            <div className="queue-stats">
              <div className="queue-stat">
                <span className="stat-value stat-pending">{q.pending}</span>
                <span className="stat-label">{t('ops.pending')}</span>
              </div>
              <div className="queue-stat">
                <span className="stat-value stat-running">{q.running}</span>
                <span className="stat-label">{t('ops.running')}</span>
              </div>
              <div className="queue-stat">
                <span className="stat-value stat-failed">{q.failed}</span>
                <span className="stat-label">{t('ops.failed')}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Provider Health */}
      <div className="ops-providers">
        <h2 className="ops-section-title">{t('ops.providers')}</h2>
        <div className="providers-grid">
          {providers.map((p) => {
            const pct = p.rate_limit_total > 0
              ? (p.rate_limit_remaining / p.rate_limit_total) * 100
              : 100;
            const fillClass = pct < 20 ? 'low' : pct < 50 ? 'medium' : '';

            return (
              <div className="provider-card" key={p.provider}>
                <div className="provider-card-header">
                  <span className="provider-name">{p.provider}</span>
                  <span className={`circuit-badge circuit-${p.circuit_state}`}>
                    {p.circuit_state}
                  </span>
                </div>
                <div className="rate-limit-bar">
                  <div className="rate-limit-label">
                    <span>{t('ops.rate_limit')}</span>
                    <span>{p.rate_limit_remaining} / {p.rate_limit_total}</span>
                  </div>
                  <div className="rate-limit-track">
                    <div
                      className={`rate-limit-fill ${fillClass}`}
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
                {p.failure_count > 0 && (
                  <div className="provider-failure">
                    Failures: {p.failure_count}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Job Runs Table */}
      <div className="ops-jobs">
        <div className="ops-jobs-header">
          <h2 className="ops-section-title">{t('ops.jobs')}</h2>
          <div className="ops-filters">
            <select
              className="ops-filter-select"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="">{t('ops.all')} ({t('ops.filter_status')})</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="retry_scheduled">Retry Scheduled</option>
              <option value="dead">Dead</option>
              <option value="canceled">Canceled</option>
            </select>
            <select
              className="ops-filter-select"
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
            >
              <option value="">{t('ops.all')} ({t('ops.filter_type')})</option>
              <option value="meta_sync_assets">meta_sync_assets</option>
              <option value="meta_sync_insights">meta_sync_insights</option>
              <option value="meta_live_monitor">meta_live_monitor</option>
              <option value="meta_generate_alerts">meta_generate_alerts</option>
              <option value="outcome_capture">outcome_capture</option>
              <option value="decision_execute">decision_execute</option>
              <option value="creatives_generate">creatives_generate</option>
              <option value="opportunities_analyze">opportunities_analyze</option>
            </select>
          </div>
        </div>

        <table className="jobs-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Status</th>
              <th>Queue</th>
              <th>Attempts</th>
              <th>Request ID</th>
              <th>Created</th>
              <th>Error Code</th>
              <th>Error Message</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.length === 0 ? (
              <tr>
                <td colSpan={9} style={{ textAlign: 'center', color: '#6b7280' }}>
                  {t('common.no_data')}
                </td>
              </tr>
            ) : (
              jobs.map((job) => (
                <tr key={job.id} onClick={() => setSelectedJob(job)} style={{ cursor: 'pointer' }}>
                  <td>{job.job_type}</td>
                  <td>
                    <span className={`status-badge status-${job.status}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>{job.queue || '—'}</td>
                  <td>{job.attempts}/{job.max_attempts}</td>
                  <td title={job.trace_id || '—'} style={{ maxWidth: '100px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {job.trace_id ? job.trace_id.substring(0, 8) + '…' : '—'}
                  </td>
                  <td>{job.created_at ? new Date(job.created_at).toLocaleString() : '—'}</td>
                  <td>{job.last_error_code || '—'}</td>
                  <td title={job.last_error_message || ''} style={{ maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {job.last_error_message ? job.last_error_message.substring(0, 60) : '—'}
                  </td>
                  <td>
                    <div className="ops-btn-actions" onClick={(e) => e.stopPropagation()}>
                      {(job.status === 'failed' || job.status === 'dead') && (
                        <button className="ops-btn ops-btn-retry" onClick={() => handleRetry(job.id)}>
                          {t('ops.retry')}
                        </button>
                      )}
                      {(job.status === 'queued' || job.status === 'running' || job.status === 'retry_scheduled') && (
                        <button className="ops-btn ops-btn-cancel" onClick={() => handleCancel(job.id)}>
                          {t('ops.cancel')}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Job Detail Modal */}
      {selectedJob && (
        <div className="ops-modal-overlay" onClick={() => setSelectedJob(null)}>
          <div className="ops-modal" onClick={(e) => e.stopPropagation()}>
            <h2>{t('ops.job_detail')}</h2>

            <div className="ops-modal-field">
              <label>ID</label>
              <span>{selectedJob.id}</span>
            </div>
            <div className="ops-modal-field">
              <label>Type</label>
              <span>{selectedJob.job_type}</span>
            </div>
            <div className="ops-modal-field">
              <label>Status</label>
              <span className={`status-badge status-${selectedJob.status}`}>
                {selectedJob.status}
              </span>
            </div>
            <div className="ops-modal-field">
              <label>Attempts</label>
              <span>{selectedJob.attempts} / {selectedJob.max_attempts}</span>
            </div>
            {selectedJob.trace_id && (
              <div className="ops-modal-field">
                <label>Trace ID</label>
                <span>{selectedJob.trace_id}</span>
              </div>
            )}
            {selectedJob.idempotency_key && (
              <div className="ops-modal-field">
                <label>Idempotency Key</label>
                <span>{selectedJob.idempotency_key}</span>
              </div>
            )}
            {selectedJob.started_at && (
              <div className="ops-modal-field">
                <label>Started At</label>
                <span>{new Date(selectedJob.started_at).toLocaleString()}</span>
              </div>
            )}
            {selectedJob.finished_at && (
              <div className="ops-modal-field">
                <label>Finished At</label>
                <span>{new Date(selectedJob.finished_at).toLocaleString()}</span>
              </div>
            )}
            {selectedJob.last_error_code && (
              <div className="ops-modal-field">
                <label>Error Code</label>
                <span>{selectedJob.last_error_code}</span>
              </div>
            )}
            {selectedJob.last_error_message && (
              <div className="ops-modal-field">
                <label>Error Message</label>
                <span>{selectedJob.last_error_message}</span>
              </div>
            )}
            {selectedJob.payload && (
              <div className="ops-modal-field">
                <label>Payload</label>
                <pre>{JSON.stringify(selectedJob.payload, null, 2)}</pre>
              </div>
            )}

            <button className="ops-modal-close" onClick={() => setSelectedJob(null)}>
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
