import { useState, useEffect } from 'react';
import { useAuth } from '../auth/AuthContext';
import { Settings as SettingsIcon, CreditCard, Users, Paintbrush } from 'lucide-react';
import api from '../services/api';
import './Settings.css';

type Tab = 'billing' | 'team' | 'branding';

interface BillingStatus {
  plan: string | null;
  status: string | null;
  limits: {
    max_ad_accounts: number;
    max_decisions_per_month: number;
    max_creatives_per_month: number;
    allow_live_execution: boolean;
  };
  usage: {
    decisions_this_month: number;
    creatives_this_month: number;
  };
  trial_ends_at: string | null;
  current_period_end: string | null;
}

interface Member {
  id: string;
  email: string;
  name: string;
  role: string;
  joined_at: string;
}

interface InviteData {
  id: string;
  email: string;
  role: string;
  token: string;
  expires_at: string;
  created_at: string;
}

interface BrandingData {
  id: string;
  logo_url: string | null;
  primary_color: string;
  accent_color: string;
  company_name: string | null;
  custom_domain: string | null;
}

export default function Settings() {
  const { user } = useAuth();
  const [tab, setTab] = useState<Tab>('billing');

  // Billing state
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  // Team state
  const [members, setMembers] = useState<Member[]>([]);
  const [invites, setInvites] = useState<InviteData[]>([]);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('viewer');
  // Branding state
  const [branding, setBranding] = useState<BrandingData | null>(null);
  const [brandingForm, setBrandingForm] = useState({ primary_color: '', accent_color: '', company_name: '' });

  const isAdmin = user?.role === 'admin';

  useEffect(() => {
    if (tab === 'billing') loadBilling();
    if (tab === 'team') { loadMembers(); loadInvites(); }
    if (tab === 'branding') loadBranding();
  }, [tab]);

  const loadBilling = async () => {
    try {
      const res = await api.get('/billing/status');
      setBilling(res.data);
    } catch { /* ignore */ }
  };

  const loadMembers = async () => {
    try {
      const res = await api.get('/orgs/members');
      setMembers(res.data);
    } catch { /* ignore */ }
  };

  const loadInvites = async () => {
    try {
      const res = await api.get('/orgs/invites');
      setInvites(res.data);
    } catch { /* ignore */ }
  };

  const loadBranding = async () => {
    try {
      const res = await api.get('/orgs/branding');
      setBranding(res.data);
      setBrandingForm({
        primary_color: res.data.primary_color || '#D4845C',
        accent_color: res.data.accent_color || '#8B9D5D',
        company_name: res.data.company_name || '',
      });
    } catch { /* ignore */ }
  };

  const handleUpgrade = async () => {
    try {
      const res = await api.post('/billing/checkout', { plan: 'pro' });
      window.location.href = res.data.checkout_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to create checkout session');
    }
  };

  const handlePortal = async () => {
    try {
      const res = await api.post('/billing/portal', {});
      window.location.href = res.data.portal_url;
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to open billing portal');
    }
  };

  const handleInvite = async () => {
    if (!inviteEmail) return;
    try {
      await api.post('/orgs/invites', { email: inviteEmail, role: inviteRole });
      setInviteEmail('');
      loadInvites();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to send invite');
    }
  };

  const handleRevokeInvite = async (id: string) => {
    try {
      await api.delete(`/orgs/invites/${id}`);
      loadInvites();
    } catch { /* ignore */ }
  };

  const handleBrandingSave = async () => {
    try {
      await api.put('/orgs/branding', brandingForm);
      loadBranding();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to update branding');
    }
  };

  const usagePercent = (current: number, limit: number) =>
    limit > 0 ? Math.min(100, Math.round((current / limit) * 100)) : 0;

  return (
    <div className="settings-page">
      <div className="settings-header">
        <SettingsIcon size={24} />
        <h1>Settings</h1>
      </div>

      <div className="settings-tabs">
        <button className={`settings-tab ${tab === 'billing' ? 'active' : ''}`} onClick={() => setTab('billing')}>
          <CreditCard size={16} /> Billing
        </button>
        <button className={`settings-tab ${tab === 'team' ? 'active' : ''}`} onClick={() => setTab('team')}>
          <Users size={16} /> Team
        </button>
        <button className={`settings-tab ${tab === 'branding' ? 'active' : ''}`} onClick={() => setTab('branding')}>
          <Paintbrush size={16} /> Branding
        </button>
      </div>

      <div className="settings-content">
        {tab === 'billing' && billing && (
          <div className="settings-section">
            <div className="plan-card">
              <div className="plan-badge">{(billing.plan || 'none').toUpperCase()}</div>
              <div className="plan-status">Status: <strong>{billing.status || 'N/A'}</strong></div>
              {billing.trial_ends_at && (
                <div className="plan-trial">Trial ends: {new Date(billing.trial_ends_at).toLocaleDateString()}</div>
              )}
            </div>

            {billing.limits && (
              <div className="usage-section">
                <h3>Usage This Month</h3>
                <div className="usage-bar-group">
                  <label>Decisions: {billing.usage.decisions_this_month} / {billing.limits.max_decisions_per_month}</label>
                  <div className="usage-bar">
                    <div className="usage-fill" style={{ width: `${usagePercent(billing.usage.decisions_this_month, billing.limits.max_decisions_per_month)}%` }} />
                  </div>
                </div>
                <div className="usage-bar-group">
                  <label>Creatives: {billing.usage.creatives_this_month} / {billing.limits.max_creatives_per_month}</label>
                  <div className="usage-bar">
                    <div className="usage-fill" style={{ width: `${usagePercent(billing.usage.creatives_this_month, billing.limits.max_creatives_per_month)}%` }} />
                  </div>
                </div>
                <div className="usage-info">
                  <span>Live execution: {billing.limits.allow_live_execution ? 'Enabled' : 'Dry-run only'}</span>
                  <span>Max ad accounts: {billing.limits.max_ad_accounts}</span>
                </div>
              </div>
            )}

            <div className="billing-actions">
              {billing.plan === 'trial' && (
                <button className="btn-primary" onClick={handleUpgrade}>Upgrade to PRO</button>
              )}
              {billing.plan && billing.plan !== 'trial' && (
                <button className="btn-secondary" onClick={handlePortal}>Manage Subscription</button>
              )}
            </div>
          </div>
        )}

        {tab === 'team' && (
          <div className="settings-section">
            <h3>Team Members</h3>
            <div className="members-list">
              {members.map(m => (
                <div key={m.id} className="member-row">
                  <div className="member-info">
                    <span className="member-name">{m.name}</span>
                    <span className="member-email">{m.email}</span>
                  </div>
                  <span className={`role-badge role-${m.role}`}>{m.role}</span>
                </div>
              ))}
            </div>

            {isAdmin && (
              <>
                <h3>Invite New Member</h3>
                <div className="invite-form">
                  <input
                    type="email"
                    placeholder="Email address"
                    value={inviteEmail}
                    onChange={e => setInviteEmail(e.target.value)}
                  />
                  <select value={inviteRole} onChange={e => setInviteRole(e.target.value)}>
                    <option value="viewer">Viewer</option>
                    <option value="operator">Operator</option>
                    <option value="admin">Admin</option>
                  </select>
                  <button className="btn-primary" onClick={handleInvite}>Send Invite</button>
                </div>

                {invites.length > 0 && (
                  <>
                    <h3>Pending Invites</h3>
                    <div className="invites-list">
                      {invites.map(inv => (
                        <div key={inv.id} className="invite-row">
                          <span>{inv.email}</span>
                          <span className={`role-badge role-${inv.role}`}>{inv.role}</span>
                          <button className="btn-danger-sm" onClick={() => handleRevokeInvite(inv.id)}>Revoke</button>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        )}

        {tab === 'branding' && (
          <div className="settings-section">
            <h3>Brand Customization</h3>
            <div className="branding-form">
              <div className="form-group">
                <label>Company Name</label>
                <input
                  type="text"
                  value={brandingForm.company_name}
                  onChange={e => setBrandingForm({ ...brandingForm, company_name: e.target.value })}
                />
              </div>
              <div className="form-group">
                <label>Primary Color</label>
                <div className="color-input">
                  <input
                    type="color"
                    value={brandingForm.primary_color}
                    onChange={e => setBrandingForm({ ...brandingForm, primary_color: e.target.value })}
                  />
                  <span>{brandingForm.primary_color}</span>
                </div>
              </div>
              <div className="form-group">
                <label>Accent Color</label>
                <div className="color-input">
                  <input
                    type="color"
                    value={brandingForm.accent_color}
                    onChange={e => setBrandingForm({ ...brandingForm, accent_color: e.target.value })}
                  />
                  <span>{brandingForm.accent_color}</span>
                </div>
              </div>
              {isAdmin && (
                <button className="btn-primary" onClick={handleBrandingSave}>Save Branding</button>
              )}
            </div>

            {branding && (
              <div className="branding-preview" style={{ borderColor: brandingForm.primary_color }}>
                <div className="preview-header" style={{ backgroundColor: brandingForm.primary_color }}>
                  <span style={{ color: '#fff' }}>{brandingForm.company_name || 'Your Brand'}</span>
                </div>
                <div className="preview-body">
                  <div className="preview-accent" style={{ backgroundColor: brandingForm.accent_color }} />
                  <span>Preview of your brand colors</span>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
