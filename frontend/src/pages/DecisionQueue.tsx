import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { decisionsApi, rankingsApi, reportsApi, Decision, RankedDecision } from '../services/api';
import { useStore } from '../store';
import { useAuth } from '../auth/AuthContext';
import { useLanguage } from '../contexts/LanguageContext';
import { CheckCircle, XCircle, Play, FileText, Table } from 'lucide-react';
import './DecisionQueue.css';

export default function DecisionQueue() {
  const { currentOrg } = useStore();
  const { user } = useAuth();
  const { t } = useLanguage();
  const navigate = useNavigate();
  const [decisions, setDecisions] = useState<(Decision | RankedDecision)[]>([]);
  const [filterState, setFilterState] = useState<string>('all');
  const [smartOrder, setSmartOrder] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadDecisions();
  }, [filterState, smartOrder]);

  const loadDecisions = async () => {
    setLoading(true);
    try {
      if (smartOrder) {
        const params = filterState !== 'all' ? { state: filterState } : {};
        const res = await rankingsApi.listRanked(params);
        setDecisions(res.data);
      } else {
        const params = filterState !== 'all' ? { state: filterState } : {};
        const res = await decisionsApi.list(params);
        setDecisions(res.data);
      }
    } catch (error) {
      console.error('Failed to load decisions:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleValidate = async (id: string) => {
    try {
      await decisionsApi.validate(id);
      await loadDecisions();
    } catch (error) {
      console.error('Failed to validate:', error);
      alert('Failed to validate decision');
    }
  };

  const handleRequestApproval = async (id: string) => {
    try {
      await decisionsApi.requestApproval(id);
      await loadDecisions();
    } catch (error) {
      console.error('Failed to request approval:', error);
      alert('Failed to request approval');
    }
  };

  const handleApprove = async (id: string) => {
    if (!user) { navigate('/login'); return; }
    try {
      await decisionsApi.approve(id, user.id);
      await loadDecisions();
    } catch (error) {
      console.error('Failed to approve:', error);
      alert('Failed to approve decision');
    }
  };

  const handleReject = async (id: string) => {
    const reason = prompt('Rejection reason:');
    if (!reason) return;
    try {
      await decisionsApi.reject(id, reason);
      await loadDecisions();
    } catch (error) {
      console.error('Failed to reject:', error);
      alert('Failed to reject decision');
    }
  };

  const handleExecute = async (id: string, dryRun: boolean = false) => {
    if (!dryRun && !currentOrg?.operator_armed) {
      alert('Operator Armed must be ON to execute live changes');
      return;
    }

    const confirmMessage = dryRun
      ? 'Run dry-run test?'
      : 'EXECUTE LIVE CHANGE? This will modify your Meta Ads account.';

    if (!confirm(confirmMessage)) return;

    try {
      await decisionsApi.execute(id, dryRun);
      await loadDecisions();
      alert(dryRun ? 'Dry run completed' : 'Executed successfully');
    } catch (error) {
      console.error('Failed to execute:', error);
      alert('Execution failed: ' + (error as any).response?.data?.detail || 'Unknown error');
    }
  };

  const states = ['all', 'draft', 'ready', 'pending_approval', 'approved', 'executed', 'blocked'];

  return (
    <div className="decision-queue">
      <div className="queue-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
          <h1>Decision Queue</h1>
          <button
            onClick={() => setSmartOrder(!smartOrder)}
            className={`btn ${smartOrder ? 'btn-primary' : 'btn-outline'}`}
            style={{ fontSize: '0.8rem', padding: '0.3rem 0.75rem' }}
          >
            {t('brain.smart_order')} {smartOrder ? 'ON' : 'OFF'}
          </button>
        </div>
        <div className="state-filters">
          {states.map((state) => (
            <button
              key={state}
              onClick={() => setFilterState(state)}
              className={`filter-btn ${filterState === state ? 'active' : ''}`}
            >
              {state.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <p>Loading...</p>
      ) : decisions.length === 0 ? (
        <div className="empty-state card">
          <p>No decisions found for filter: {filterState}</p>
        </div>
      ) : (
        <div className="decision-list">
          {decisions.map((decision) => (
            <DecisionCard
              key={decision.id}
              decision={decision}
              onValidate={handleValidate}
              onRequestApproval={handleRequestApproval}
              onApprove={handleApprove}
              onReject={handleReject}
              onExecute={handleExecute}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface DecisionCardProps {
  decision: Decision | RankedDecision;
  onValidate: (id: string) => void;
  onRequestApproval: (id: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onExecute: (id: string, dryRun: boolean) => void;
}

function isRanked(d: Decision | RankedDecision): d is RankedDecision {
  return 'score_total' in d;
}

function DecisionCard({
  decision,
  onValidate,
  onRequestApproval,
  onApprove,
  onReject,
  onExecute,
}: DecisionCardProps) {
  return (
    <div className="decision-card card">
      <div className="decision-header">
        <span className={`badge badge-${getStateBadgeClass(decision.state)}`}>
          {decision.state.replace('_', ' ')}
        </span>
        {isRanked(decision) && (
          <span style={{ display: 'flex', gap: '0.4rem', fontSize: '0.7rem' }}>
            <span style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', background: '#e8f0db', color: '#5a6b3a' }}>
              Impact {(decision.score_impact * 100).toFixed(0)}
            </span>
            <span style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', background: '#f5e0db', color: '#8b3a2a' }}>
              Risk {(decision.score_risk * 100).toFixed(0)}
            </span>
            <span style={{ padding: '0.15rem 0.4rem', borderRadius: '8px', background: '#f5ecd8', color: '#7a6730' }}>
              Trust {(decision.score_confidence * 100).toFixed(0)}
            </span>
          </span>
        )}
        <span className="decision-id">ID: {decision.trace_id}</span>
      </div>

      <h3 className="decision-title">
        {decision.action_type.replace('_', ' ')} — {decision.entity_name}
      </h3>

      <div className="decision-details">
        <div className="detail-row">
          <span className="label">Entity:</span>
          <span>{decision.entity_type} ({decision.entity_id})</span>
        </div>
        <div className="detail-row">
          <span className="label">Source:</span>
          <span>{decision.source}</span>
        </div>
        <div className="detail-row">
          <span className="label">Rationale:</span>
          <span>{decision.rationale || 'None'}</span>
        </div>
      </div>

      {decision.policy_checks.length > 0 && (
        <div className="policy-checks">
          <h4>Policy Checks:</h4>
          {decision.policy_checks.map((check, i) => (
            <div key={i} className={`policy-check ${check.passed ? 'pass' : 'fail'}`}>
              {check.passed ? <CheckCircle size={14} /> : <XCircle size={14} />}
              <span>{check.rule_name}: {check.message}</span>
            </div>
          ))}
        </div>
      )}

      <div className="decision-exports" style={{ display: 'flex', gap: '0.5rem', marginBottom: '0.5rem' }}>
        <button
          className="btn btn-outline"
          style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
          onClick={async () => {
            try {
              const res = await reportsApi.downloadDecisionDocx(decision.id);
              const url = URL.createObjectURL(res.data);
              const a = document.createElement('a');
              a.href = url;
              a.download = `decision_${decision.id}.docx`;
              a.click();
              URL.revokeObjectURL(url);
            } catch { alert('Failed to download DOCX'); }
          }}
        >
          <FileText size={14} /> DOCX
        </button>
        <button
          className="btn btn-outline"
          style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
          onClick={async () => {
            try {
              const res = await reportsApi.downloadDecisionXlsx(decision.id);
              const url = URL.createObjectURL(res.data);
              const a = document.createElement('a');
              a.href = url;
              a.download = `decision_${decision.id}.xlsx`;
              a.click();
              URL.revokeObjectURL(url);
            } catch { alert('Failed to download XLSX'); }
          }}
        >
          <Table size={14} /> XLSX
        </button>
      </div>

      <div className="decision-actions">
        {decision.state === 'draft' && (
          <button onClick={() => onValidate(decision.id)} className="btn btn-primary">
            Validate
          </button>
        )}
        {decision.state === 'ready' && (
          <button onClick={() => onRequestApproval(decision.id)} className="btn btn-primary">
            Request Approval
          </button>
        )}
        {decision.state === 'pending_approval' && (
          <>
            <button onClick={() => onApprove(decision.id)} className="btn btn-secondary">
              <CheckCircle size={16} /> Approve
            </button>
            <button onClick={() => onReject(decision.id)} className="btn btn-outline">
              <XCircle size={16} /> Reject
            </button>
          </>
        )}
        {decision.state === 'approved' && (
          <>
            <button onClick={() => onExecute(decision.id, true)} className="btn btn-outline">
              Dry Run First
            </button>
            <button onClick={() => onExecute(decision.id, false)} className="btn btn-primary">
              <Play size={16} /> Execute Live
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function getStateBadgeClass(state: string): string {
  if (['executed', 'approved'].includes(state)) return 'success';
  if (['failed', 'blocked', 'rejected'].includes(state)) return 'error';
  if (['pending_approval', 'validating'].includes(state)) return 'warning';
  return 'info';
}
