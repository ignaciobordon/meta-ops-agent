import { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { decisionsApi, organizationsApi, metaApi, metaSyncApi } from '../services/api';
import { useStore } from '../store';
import { useAuth } from '../auth/AuthContext';
import { Shield, AlertTriangle, Link2, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import './ControlPanel.css';

export default function ControlPanel() {
  const {
    activeAdAccount, setActiveAdAccount,
    adAccounts, setAdAccounts, metaConnected,
  } = useStore();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [operatorArmed, setOperatorArmed] = useState(false);
  const [orgId, setOrgId] = useState<string>('');
  const [connectLoading, setConnectLoading] = useState(false);
  const [selectLoading, setSelectLoading] = useState(false);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [metaSuccess, setMetaSuccess] = useState<string | null>(null);
  const [syncLoading, setSyncLoading] = useState(false);

  const [formData, setFormData] = useState({
    ad_account_id: '',
    action_type: 'budget_change',
    entity_type: 'adset',
    entity_id: '',
    entity_name: '',
    current_budget: '',
    new_budget: '',
    rationale: '',
  });

  // Pre-fill form from query params (from Alerts, Opportunities, Brain, Creatives)
  useEffect(() => {
    const action = searchParams.get('action_type');
    const entity = searchParams.get('entity_type');
    const eid = searchParams.get('entity_id');
    const ename = searchParams.get('entity_name');
    const rationale = searchParams.get('rationale');
    if (action || entity || eid || ename || rationale) {
      setFormData(prev => ({
        ...prev,
        ...(action && { action_type: action }),
        ...(entity && { entity_type: entity }),
        ...(eid && { entity_id: eid }),
        ...(ename && { entity_name: ename }),
        ...(rationale && { rationale: rationale }),
      }));
      // Clean up query params after reading
      setSearchParams({});
    }
  }, []);

  useEffect(() => {
    loadOrganization();
    loadMetaState();
    handleOAuthCallback();
  }, []);

  const handleOAuthCallback = () => {
    if (searchParams.get('meta_connected') === 'true') {
      const accounts = searchParams.get('accounts') || '0';
      setMetaSuccess(`Meta connected successfully! ${accounts} ad account(s) found.`);
      loadMetaState();
      setSearchParams({});
    }
    const error = searchParams.get('meta_error');
    if (error) {
      setMetaError(`Meta connection failed: ${error}`);
      setSearchParams({});
    }
  };

  const loadOrganization = async () => {
    try {
      const res = await organizationsApi.list();
      if (res.data.length > 0) {
        const org = res.data[0];
        setOrgId(org.id);
        setOperatorArmed(org.operator_armed);
      }
    } catch (error) {
      console.error('Failed to load organization:', error);
    }
  };

  const loadMetaState = async () => {
    try {
      const activeRes = await metaApi.getActiveAccount();
      setActiveAdAccount(activeRes.data);

      const accountsRes = await metaApi.listAdAccounts();
      setAdAccounts(accountsRes.data);

      if (activeRes.data.has_active_account && activeRes.data.ad_account_id) {
        setFormData(prev => ({ ...prev, ad_account_id: activeRes.data.ad_account_id! }));
      }
    } catch (error) {
      // No accounts yet — that's ok
    }
  };

  const handleToggleOperatorArmed = async () => {
    if (!orgId) return;
    try {
      await organizationsApi.toggleOperatorArmed(orgId, !operatorArmed);
      setOperatorArmed(!operatorArmed);
    } catch (error) {
      console.error('Failed to toggle Operator Armed:', error);
      alert('Failed to toggle Operator Armed');
    }
  };

  const handleConnectMetaAccount = async () => {
    setConnectLoading(true);
    setMetaError(null);
    try {
      const res = await metaApi.oauthStart();
      window.location.href = res.data.authorization_url;
    } catch (error: any) {
      const detail = error.response?.data?.detail || 'Failed to start OAuth';
      setMetaError(detail);
      setConnectLoading(false);
    }
  };

  const handleSelectAccount = async (adAccountId: string) => {
    if (!adAccountId) return;
    setSelectLoading(true);
    setMetaError(null);
    try {
      await metaApi.selectAdAccount(adAccountId);
      await loadMetaState();
      setFormData(prev => ({ ...prev, ad_account_id: adAccountId }));
    } catch (error: any) {
      setMetaError(error.response?.data?.detail || 'Failed to select account');
    } finally {
      setSelectLoading(false);
    }
  };

  const handleSyncActiveAccount = async () => {
    setSyncLoading(true);
    setMetaError(null);
    setMetaSuccess(null);
    try {
      const res = await metaSyncApi.syncActiveAccount();
      const data = res.data as any;
      const assetsCount = data.assets?.items_upserted || 0;
      const insightsCount = data.insights?.items_upserted || 0;
      setMetaSuccess(
        `Sync complete for ${data.account}: ${assetsCount} assets + ${insightsCount} insights synced`
      );
    } catch (error: any) {
      setMetaError(error.response?.data?.detail || 'Sync failed');
    } finally {
      setSyncLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (!user) {
      navigate('/login');
      return;
    }

    if (!formData.ad_account_id) {
      alert('Please select an Ad Account before creating a decision.');
      return;
    }

    try {
      const payload = {
        before: { daily_budget: parseFloat(formData.current_budget) },
        after: { daily_budget: parseFloat(formData.new_budget) },
        current_budget: parseFloat(formData.current_budget),
        new_budget: parseFloat(formData.new_budget),
      };

      await decisionsApi.create({
        ad_account_id: formData.ad_account_id,
        user_id: user.id,
        action_type: formData.action_type,
        entity_type: formData.entity_type,
        entity_id: formData.entity_id,
        entity_name: formData.entity_name,
        payload,
        rationale: formData.rationale,
        source: 'Manual',
      });

      alert('Decision created successfully!');
      navigate('/decisions');
    } catch (error) {
      console.error('Failed to create decision:', error);
      alert('Failed to create decision: ' + ((error as any).response?.data?.detail || 'Unknown error'));
    }
  };

  return (
    <div className="control-panel">
      <div className="panel-header">
        <h1>Control Panel</h1>
        <p className="subtitle">Create manual decision drafts and manage settings</p>
      </div>

      {/* Operator Armed & Account Connection */}
      <div className="control-settings card">
        <div className="setting-row">
          <div className="setting-info">
            <Shield size={24} className={operatorArmed ? 'text-olive' : 'text-gray'} />
            <div>
              <h3>Operator Armed</h3>
              <p>
                {operatorArmed ? (
                  <span className="text-olive">ON - Live executions enabled</span>
                ) : (
                  <span className="text-gray">OFF - Dry-run mode only (safe)</span>
                )}
              </p>
            </div>
          </div>
          <label className="toggle-switch">
            <input
              type="checkbox"
              checked={operatorArmed}
              onChange={handleToggleOperatorArmed}
            />
            <span className="toggle-slider"></span>
          </label>
        </div>

        {operatorArmed && (
          <div className="warning-box">
            <AlertTriangle size={18} />
            <span>
              <strong>Warning:</strong> Operator Armed is ON. Approved decisions can make REAL changes to your Meta Ads account.
            </span>
          </div>
        )}

        {/* Meta Connection */}
        <div className="setting-row">
          <div className="setting-info">
            <Link2 size={24} className={metaConnected ? 'text-olive' : 'text-terracotta'} />
            <div>
              <h3>Meta Ads Connection</h3>
              {metaConnected && activeAdAccount ? (
                <p className="text-olive">
                  Connected: {activeAdAccount.name} ({activeAdAccount.meta_ad_account_id})
                </p>
              ) : adAccounts.length > 0 ? (
                <p className="text-terracotta">Connected but no active account selected</p>
              ) : (
                <p className="text-gray">Connect your Facebook/Instagram advertising accounts</p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={handleConnectMetaAccount}
            className="btn btn-primary"
            disabled={connectLoading}
          >
            {connectLoading ? 'Connecting...' : adAccounts.length > 0 ? 'Reconnect' : 'Connect Account'}
          </button>
        </div>

        {/* Ad Account Selector */}
        {adAccounts.length > 0 && (
          <div className="setting-row">
            <div className="setting-info" style={{ width: '100%' }}>
              <div style={{ width: '100%' }}>
                <h3>Active Ad Account</h3>
                <select
                  value={activeAdAccount?.ad_account_id || ''}
                  onChange={(e) => handleSelectAccount(e.target.value)}
                  disabled={selectLoading}
                  className="ad-account-select"
                >
                  <option value="">Select an account...</option>
                  {adAccounts.map(acct => (
                    <option key={acct.id} value={acct.id}>
                      {acct.name} ({acct.meta_ad_account_id}) - {acct.currency}
                    </option>
                  ))}
                </select>
                {activeAdAccount?.has_active_account && (
                  <button
                    type="button"
                    onClick={handleSyncActiveAccount}
                    className="btn btn-primary"
                    disabled={syncLoading}
                    style={{ marginTop: 'var(--spacing-sm)' }}
                  >
                    <RefreshCw size={16} className={syncLoading ? 'spin' : ''} style={{ marginRight: 6 }} />
                    {syncLoading ? 'Syncing...' : 'Sync Active Account'}
                  </button>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Status messages */}
        {metaError && (
          <div className="warning-box" style={{ borderColor: 'var(--terracotta-500)', background: 'var(--terracotta-50, #fdf2ec)' }}>
            <XCircle size={18} style={{ color: 'var(--terracotta-500)' }} />
            <span style={{ color: 'var(--terracotta-700, #a0533a)' }}>{metaError}</span>
          </div>
        )}
        {metaSuccess && (
          <div className="warning-box" style={{ borderColor: 'var(--olive-500)', background: 'var(--olive-50, #f4f6ef)' }}>
            <CheckCircle size={18} style={{ color: 'var(--olive-500)' }} />
            <span style={{ color: 'var(--olive-700, #5c6b3a)' }}>{metaSuccess}</span>
          </div>
        )}
      </div>

      {/* Gate: require active account for decision form */}
      {!metaConnected ? (
        <div className="card" style={{ padding: 'var(--spacing-2xl)', textAlign: 'center' }}>
          <Link2 size={48} style={{ margin: '0 auto var(--spacing-lg)', opacity: 0.3, display: 'block' }} />
          <h2 style={{ color: 'var(--gray-600)' }}>Connect a Meta Account</h2>
          <p style={{ color: 'var(--gray-500)' }}>
            You need to connect and select an active Meta ad account before creating decisions.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="control-form card">
          <div className="form-section">
            <h2>Action Configuration</h2>

            <div className="form-group">
              <label>Action Type</label>
              <select
                value={formData.action_type}
                onChange={(e) => setFormData({ ...formData, action_type: e.target.value })}
              >
                <option value="budget_change">Budget Change</option>
                <option value="adset_pause">Adset Pause</option>
                <option value="creative_swap">Creative Swap</option>
              </select>
            </div>

            <div className="form-group">
              <label>Entity Type</label>
              <select
                value={formData.entity_type}
                onChange={(e) => setFormData({ ...formData, entity_type: e.target.value })}
              >
                <option value="adset">Adset</option>
                <option value="ad">Ad</option>
                <option value="campaign">Campaign</option>
              </select>
            </div>

            <div className="form-group">
              <label>Entity ID</label>
              <input
                type="text"
                value={formData.entity_id}
                onChange={(e) => setFormData({ ...formData, entity_id: e.target.value })}
                placeholder="e.g., 23851234567890"
                required
              />
            </div>

            <div className="form-group">
              <label>Entity Name</label>
              <input
                type="text"
                value={formData.entity_name}
                onChange={(e) => setFormData({ ...formData, entity_name: e.target.value })}
                placeholder="e.g., High Intent Adset"
                required
              />
            </div>
          </div>

          {formData.action_type === 'budget_change' && (
            <div className="form-section">
              <h2>Budget Configuration</h2>

              <div className="form-group">
                <label>Current Budget (USD/day)</label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.current_budget}
                  onChange={(e) => setFormData({ ...formData, current_budget: e.target.value })}
                  placeholder="100.00"
                  required
                />
              </div>

              <div className="form-group">
                <label>New Budget (USD/day)</label>
                <input
                  type="number"
                  step="0.01"
                  value={formData.new_budget}
                  onChange={(e) => setFormData({ ...formData, new_budget: e.target.value })}
                  placeholder="120.00"
                  required
                />
              </div>

              {formData.current_budget && formData.new_budget && (
                <div className="budget-preview">
                  <div className="preview-label">Change:</div>
                  <div className="preview-value">
                    ${parseFloat(formData.current_budget).toFixed(2)} → ${parseFloat(formData.new_budget).toFixed(2)}
                    <span className="change-pct">
                      ({((parseFloat(formData.new_budget) - parseFloat(formData.current_budget)) / parseFloat(formData.current_budget) * 100).toFixed(1)}%)
                    </span>
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="form-section">
            <h2>Rationale</h2>
            <div className="form-group">
              <textarea
                value={formData.rationale}
                onChange={(e) => setFormData({ ...formData, rationale: e.target.value })}
                placeholder="Explain why this change is needed..."
                rows={4}
                required
              />
            </div>
          </div>

          <div className="form-actions">
            <button type="button" onClick={() => navigate('/decisions')} className="btn btn-outline">
              Cancel
            </button>
            <button type="submit" className="btn btn-primary">
              Create Draft
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
