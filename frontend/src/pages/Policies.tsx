import { useState, useEffect } from 'react';
import { Shield, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { policiesApi, PolicyRule } from '../services/api';
import './Policies.css';

export default function Policies() {
  const [rules, setRules] = useState<PolicyRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPolicies();
  }, []);

  const fetchPolicies = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await policiesApi.listRules();
      setRules(res.data);
    } catch (err) {
      console.error('Failed to fetch policies:', err);
      setError('Failed to load policy rules. Please check if the backend is running.');
    } finally {
      setLoading(false);
    }
  };

  const getSeverityClass = (severity: string) => {
    return `policy-severity severity-${severity}`;
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'critical':
        return <XCircle size={16} />;
      case 'high':
        return <AlertCircle size={16} />;
      case 'medium':
        return <CheckCircle size={16} />;
      default:
        return null;
    }
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Shield size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Policy Rules</h1>
            <p className="page-description">
              Safety guardrails that protect your Meta Ads accounts
            </p>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="loading-state">Loading policies...</div>
      ) : error ? (
        <div className="error-state">
          <p>{error}</p>
          <button onClick={fetchPolicies} className="btn-secondary">Retry</button>
        </div>
      ) : (
        <>
          <div className="policies-summary">
            <div className="summary-stat">
              <span className="stat-value">{rules.length}</span>
              <span className="stat-label">Active Rules</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">
                {rules.filter((r) => r.severity === 'critical').length}
              </span>
              <span className="stat-label">Critical</span>
            </div>
            <div className="summary-stat">
              <span className="stat-value">
                {rules.reduce((sum, r) => sum + r.violations_count, 0)}
              </span>
              <span className="stat-label">Total Violations</span>
            </div>
          </div>

          <div className="policies-list">
            {rules.map((rule) => (
              <div key={rule.rule_id} className="policy-card">
                <div className="policy-header">
                  <div className="policy-title-group">
                    <h3 className="policy-name">{rule.name}</h3>
                    <div className={getSeverityClass(rule.severity)}>
                      {getSeverityIcon(rule.severity)}
                      {rule.severity.toUpperCase()}
                    </div>
                  </div>
                  <div className="policy-status">
                    {rule.enabled ? (
                      <span className="status-enabled">
                        <CheckCircle size={16} />
                        Enabled
                      </span>
                    ) : (
                      <span className="status-disabled">
                        <XCircle size={16} />
                        Disabled
                      </span>
                    )}
                  </div>
                </div>

                <p className="policy-description">{rule.description}</p>

                <div className="policy-footer">
                  <span className="policy-id">Rule ID: {rule.rule_id}</span>
                  <span className="policy-violations">
                    {rule.violations_count === 0 ? (
                      <span className="no-violations">No violations</span>
                    ) : (
                      <span className="has-violations">
                        {rule.violations_count} violation{rule.violations_count !== 1 ? 's' : ''}
                      </span>
                    )}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
