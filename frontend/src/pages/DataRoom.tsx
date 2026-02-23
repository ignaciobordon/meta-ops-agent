import { useState, useEffect, useRef } from 'react';
import { Database, FileDown, Loader2, Download, CheckSquare, Square } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { dataRoomApi, DataExportResponse } from '../services/api';
import { useJobPolling } from '../hooks/useJobPolling';
import { downloadBlob } from '../utils/download';
import './DataRoom.css';

interface DatasetOption {
  key: string;
  label: string;
}

const DATASET_OPTIONS: DatasetOption[] = [
  { key: 'flywheel_runs', label: 'Flywheel Runs' },
  { key: 'flywheel_steps', label: 'Flywheel Steps' },
  { key: 'decision_queue', label: 'Decision Queue' },
  { key: 'decision_outcomes', label: 'Decision Outcomes' },
  { key: 'decision_rankings', label: 'Decision Rankings' },
  { key: 'job_runs', label: 'Job Runs' },
  { key: 'alerts', label: 'Alerts' },
  { key: 'opportunities', label: 'Opportunities' },
  { key: 'creatives', label: 'Creatives' },
  { key: 'insights_daily', label: 'Meta Insights Daily' },
];

export default function DataRoom() {
  const { t } = useLanguage();

  // Filter state
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [selectedDatasets, setSelectedDatasets] = useState<Set<string>>(
    new Set(DATASET_OPTIONS.map((d) => d.key))
  );
  const [entityType, setEntityType] = useState('');
  const [status, setStatus] = useState('');
  const [severity, setSeverity] = useState('');
  const [rowLimit, setRowLimit] = useState(10000);

  // Export state
  const [exports, setExports] = useState<DataExportResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [, setActiveExportId] = useState<string | null>(null);

  const job = useJobPolling(jobId);
  const prevJobStatus = useRef<string | null>(null);

  useEffect(() => {
    fetchExports();
  }, []);

  // Auto-refetch when export job succeeds
  useEffect(() => {
    if (prevJobStatus.current !== job.status && job.status === 'succeeded') {
      setJobId(null);
      fetchExports();
    }
    if (job.error) {
      setError(job.error);
      setJobId(null);
    }
    prevJobStatus.current = job.status;
  }, [job.status, job.error]);

  const fetchExports = async () => {
    try {
      setLoading(true);
      const res = await dataRoomApi.listExports();
      setExports(res.data);
    } catch {
      // Silently fail
    } finally {
      setLoading(false);
    }
  };

  const toggleDataset = (key: string) => {
    setSelectedDatasets((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedDatasets.size === DATASET_OPTIONS.length) {
      setSelectedDatasets(new Set());
    } else {
      setSelectedDatasets(new Set(DATASET_OPTIONS.map((d) => d.key)));
    }
  };

  const handleExport = async () => {
    if (selectedDatasets.size === 0) {
      setError('Select at least one dataset');
      return;
    }

    try {
      setError(null);
      const params: Record<string, any> = {
        datasets: Array.from(selectedDatasets),
        row_limit: rowLimit,
      };
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      if (entityType) params.entity_type = entityType;
      if (status) params.status = status;
      if (severity) params.severity = severity;

      const res = await dataRoomApi.createExport(params);
      setJobId(res.data.job_id);
      setActiveExportId(res.data.export_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start export');
    }
  };

  const handleDownload = async (exportId: string) => {
    try {
      const res = await dataRoomApi.downloadExport(exportId);
      downloadBlob(res.data, `data_room_export_${exportId}.xlsx`, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    } catch (err) {
      console.error('Failed to download export:', err);
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Database size={32} className="page-icon" />
          <div>
            <h1 className="page-title">{t('dataRoom.title')}</h1>
            <p className="page-description">{t('dataRoom.subtitle')}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button
            className="btn-primary"
            onClick={handleExport}
            disabled={job.isPolling}
          >
            {job.isPolling ? (
              <Loader2 size={18} className="spin-icon" />
            ) : (
              <FileDown size={18} />
            )}
            {job.isPolling ? t('common.loading') : t('dataRoom.export_xlsx')}
          </button>
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
          <span>Exporting data... Status: <strong>{job.status}</strong></span>
        </div>
      )}

      {/* Filter/Config Card */}
      <div className="dataroom-config-card">
        {/* Date Range */}
        <div className="dataroom-section">
          <h3 className="dataroom-section-title">{t('dataRoom.date_range')}</h3>
          <div className="dataroom-date-row">
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="dataroom-input"
            />
            <span className="dataroom-date-separator">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="dataroom-input"
            />
          </div>
        </div>

        {/* Datasets */}
        <div className="dataroom-section">
          <div className="dataroom-section-header">
            <h3 className="dataroom-section-title">{t('dataRoom.datasets')}</h3>
            <button className="dataroom-toggle-all" onClick={toggleAll}>
              {selectedDatasets.size === DATASET_OPTIONS.length ? 'Deselect All' : 'Select All'}
            </button>
          </div>
          <div className="dataroom-datasets-grid">
            {DATASET_OPTIONS.map((ds) => (
              <label key={ds.key} className="dataroom-checkbox-label">
                <span
                  className="dataroom-checkbox"
                  onClick={() => toggleDataset(ds.key)}
                >
                  {selectedDatasets.has(ds.key) ? (
                    <CheckSquare size={16} className="dataroom-checkbox-checked" />
                  ) : (
                    <Square size={16} className="dataroom-checkbox-unchecked" />
                  )}
                </span>
                <span onClick={() => toggleDataset(ds.key)}>{ds.label}</span>
              </label>
            ))}
          </div>
        </div>

        {/* Filters */}
        <div className="dataroom-section">
          <h3 className="dataroom-section-title">{t('dataRoom.filters')}</h3>
          <div className="dataroom-filters-row">
            <div className="dataroom-filter-group">
              <label className="dataroom-filter-label">Entity Type</label>
              <select
                value={entityType}
                onChange={(e) => setEntityType(e.target.value)}
                className="dataroom-select"
              >
                <option value="">All</option>
                <option value="campaign">Campaign</option>
                <option value="adset">Ad Set</option>
                <option value="ad">Ad</option>
              </select>
            </div>
            <div className="dataroom-filter-group">
              <label className="dataroom-filter-label">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="dataroom-select"
              >
                <option value="">All</option>
                <option value="active">Active</option>
                <option value="paused">Paused</option>
                <option value="completed">Completed</option>
              </select>
            </div>
            <div className="dataroom-filter-group">
              <label className="dataroom-filter-label">Severity</label>
              <select
                value={severity}
                onChange={(e) => setSeverity(e.target.value)}
                className="dataroom-select"
              >
                <option value="">All</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="medium">Medium</option>
                <option value="low">Low</option>
              </select>
            </div>
            <div className="dataroom-filter-group">
              <label className="dataroom-filter-label">Row Limit</label>
              <input
                type="number"
                value={rowLimit}
                onChange={(e) => setRowLimit(Number(e.target.value) || 10000)}
                className="dataroom-input dataroom-input-narrow"
                min={1}
                max={100000}
              />
            </div>
          </div>
        </div>
      </div>

      {/* Previous Exports */}
      <section style={{ marginTop: 'var(--spacing-xl)' }}>
        <h2 style={{ fontSize: '16px', fontWeight: 600, marginBottom: 'var(--spacing-md)' }}>
          {t('dataRoom.previous_exports')}
        </h2>
        {loading ? (
          <div className="loading-state">{t('common.loading')}</div>
        ) : exports.length === 0 ? (
          <div className="empty-state">
            <Database size={48} />
            <p>{t('dataRoom.no_exports')}</p>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="dataroom-exports-table">
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Status</th>
                  <th>Rows</th>
                  <th>Download</th>
                </tr>
              </thead>
              <tbody>
                {exports.map((exp) => (
                  <tr key={exp.id}>
                    <td>{new Date(exp.created_at).toLocaleString()}</td>
                    <td>
                      <span className={`dataroom-export-status status-${exp.status}`}>
                        {exp.status}
                      </span>
                    </td>
                    <td>{exp.rows_exported.toLocaleString()}</td>
                    <td>
                      {exp.status === 'succeeded' ? (
                        <button
                          className="btn-secondary dataroom-download-btn"
                          onClick={() => handleDownload(exp.id)}
                        >
                          <Download size={14} />
                          XLSX
                        </button>
                      ) : exp.status === 'failed' ? (
                        <span className="dataroom-error-text">
                          {exp.last_error || 'Export failed'}
                        </span>
                      ) : (
                        <Loader2 size={14} className="spin-icon" />
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
