/**
 * API client for Renaissance backend
 */
import axios, { InternalAxiosRequestConfig, AxiosError } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// ── Auth Interceptors ─────────────────────────────────────────────────────────

// Attach access token to every request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('meta_ops_access_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401: attempt refresh, then retry once
let isRefreshing = false;
let refreshQueue: Array<{ resolve: (token: string) => void; reject: (err: any) => void }> = [];

function processQueue(error: any, token: string | null) {
  refreshQueue.forEach(({ resolve, reject }) => {
    if (error) reject(error);
    else resolve(token!);
  });
  refreshQueue = [];
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean };

    // Skip refresh for auth endpoints
    if (!originalRequest || originalRequest.url?.includes('/auth/')) {
      return Promise.reject(error);
    }

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshQueue.push({
            resolve: (token: string) => {
              originalRequest.headers.Authorization = `Bearer ${token}`;
              resolve(api(originalRequest));
            },
            reject,
          });
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      const refreshToken = localStorage.getItem('meta_ops_refresh_token');
      if (!refreshToken) {
        isRefreshing = false;
        localStorage.removeItem('meta_ops_access_token');
        localStorage.removeItem('meta_ops_refresh_token');
        window.location.href = '/login';
        return Promise.reject(error);
      }

      try {
        const res = await axios.post(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        });
        const { access_token, refresh_token: newRefresh } = res.data;
        localStorage.setItem('meta_ops_access_token', access_token);
        localStorage.setItem('meta_ops_refresh_token', newRefresh);
        processQueue(null, access_token);
        originalRequest.headers.Authorization = `Bearer ${access_token}`;
        return api(originalRequest);
      } catch (refreshError: any) {
        processQueue(refreshError, null);
        localStorage.removeItem('meta_ops_access_token');
        localStorage.removeItem('meta_ops_refresh_token');
        // Detect theft/reuse message from backend
        const detail = refreshError.response?.data?.detail || '';
        if (detail.includes('reuse detected') || detail.includes('revoked')) {
          alert('Security alert: Your session was invalidated because a token reuse was detected. Please log in again.');
        }
        window.location.href = '/login';
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

// ── Organizations ─────────────────────────────────────────────────────────────

export interface Organization {
  id: string;
  name: string;
  slug: string;
  operator_armed: boolean;
  created_at: string;
}

export const organizationsApi = {
  list: () => api.get<Organization[]>('/orgs'),
  get: (id: string) => api.get<Organization>(`/orgs/${id}`),
  create: (data: { name: string; slug: string }) => api.post<Organization>('/orgs', data),
  toggleOperatorArmed: (id: string, enabled: boolean) =>
    api.post<Organization>(`/orgs/${id}/operator-armed`, { enabled }),
  listAdAccounts: (id: string) => api.get(`/orgs/${id}/ad-accounts`),
};

// ── Meta OAuth + Multi-Account (FASE 5.4) ───────────────────────────────────

export interface MetaAdAccount {
  id: string;
  meta_ad_account_id: string;
  name: string;
  currency: string;
  spend_cap: number | null;
  meta_metadata: Record<string, any> | null;
  synced_at: string | null;
  is_active: boolean;
}

export interface MetaActiveAccount {
  ad_account_id: string | null;
  meta_ad_account_id: string | null;
  name: string | null;
  currency: string | null;
  connection_status: string | null;
  has_active_account: boolean;
}

export interface MetaOAuthStartResponse {
  authorization_url: string;
  message: string;
}

export interface MetaSelectResponse {
  org_id: string;
  active_ad_account_id: string;
  active_ad_account_name: string;
  message: string;
}

export const metaApi = {
  oauthStart: () => api.get<MetaOAuthStartResponse>('/meta/oauth/start'),
  listAdAccounts: () => api.get<MetaAdAccount[]>('/meta/adaccounts'),
  selectAdAccount: (adAccountId: string) =>
    api.post<MetaSelectResponse>('/meta/adaccounts/select', { ad_account_id: adAccountId }),
  getActiveAccount: () => api.get<MetaActiveAccount>('/meta/adaccounts/active'),
};

// ── Decisions ─────────────────────────────────────────────────────────────────

export interface Decision {
  id: string;
  trace_id: string;
  state: string;
  action_type: string;
  entity_type: string;
  entity_id: string;
  entity_name: string;
  rationale: string | null;
  source: string;
  before_snapshot: Record<string, any>;
  after_proposal: Record<string, any>;
  policy_checks: any[];
  risk_score: number;
  created_at: string;
  validated_at: string | null;
  approved_at: string | null;
  executed_at: string | null;
}

export interface CreateDecisionData {
  ad_account_id: string;
  user_id: string;
  action_type: string;
  entity_type: string;
  entity_id: string;
  entity_name: string;
  payload: Record<string, any>;
  rationale: string;
  source?: string;
}

export const decisionsApi = {
  list: (params?: { ad_account_id?: string; state?: string; limit?: number }) =>
    api.get<Decision[]>('/decisions', { params }),
  get: (id: string) => api.get<Decision>(`/decisions/${id}`),
  create: (data: CreateDecisionData) => api.post<Decision>('/decisions', data),
  validate: (id: string) => api.post<Decision>(`/decisions/${id}/validate`),
  requestApproval: (id: string) => api.post<Decision>(`/decisions/${id}/request-approval`),
  approve: (id: string, approverUserId: string) =>
    api.post<Decision>(`/decisions/${id}/approve`, { approver_user_id: approverUserId }),
  reject: (id: string, reason: string) =>
    api.post<Decision>(`/decisions/${id}/reject`, { reason }),
  execute: (id: string, dryRun: boolean = false) =>
    api.post<Decision>(`/decisions/${id}/execute`, { dry_run: dryRun }),
};

// ── Opportunities ────────────────────────────────────────────────────────────

export interface Opportunity {
  id: string;
  gap_id: string;
  title: string;
  description: string;
  strategy: string;
  priority: 'high' | 'medium' | 'low';
  estimated_impact: number;
  impact_reasoning: string;
  identified_at: string;
}

export const opportunitiesApi = {
  list: (config?: Record<string, any>) => api.get<Opportunity[]>('/opportunities/', config),
  get: (id: string) => api.get<Opportunity>(`/opportunities/${id}`),
  analyze: (brandProfileId?: string) =>
    api.post<AsyncJobResponse>('/opportunities/analyze', null, {
      params: brandProfileId ? { brand_profile_id: brandProfileId } : {},
    }),
  analyzeUnified: (brandProfileId?: string) =>
    api.post<AsyncJobResponse>('/opportunities/analyze-unified', null, {
      params: brandProfileId ? { brand_profile_id: brandProfileId } : {},
    }),
  exportPdf: () => api.get('/opportunities/export/pdf', { responseType: 'blob' }),
};

// ── Policies ─────────────────────────────────────────────────────────────────

export interface PolicyRule {
  rule_id: string;
  name: string;
  description: string;
  severity: 'critical' | 'high' | 'medium';
  enabled: boolean;
  violations_count: number;
}

export const policiesApi = {
  listRules: () => api.get<PolicyRule[]>('/policies/rules'),
};

// ── Creatives ────────────────────────────────────────────────────────────────

export interface DimensionScore {
  score: number;
  reasoning: string;
}

export interface Creative {
  id: string;
  angle_id: string;
  angle_name: string;
  script: string;
  score: number;
  overall_reasoning: string;
  dimensions: Record<string, DimensionScore> | null;
  is_best: boolean;
  generated_at: string;
  source: 'manual' | 'flywheel';
  flywheel_metadata: Record<string, any> | null;
}

export interface GenerateCreativeData {
  angle_id: string;
  brand_map_id: string;
  n_variants?: number;
  brand_profile_id?: string;
  framework?: string;
  hook_style?: string;
  audience?: string;
  objective?: string;
  tone?: string;
  format?: string;
}

export interface AsyncJobResponse {
  job_id: string;
  status: string;
}

export const creativesApi = {
  list: (source?: string) => api.get<Creative[]>('/creatives/', { params: source ? { source } : {} }),
  generate: (data: GenerateCreativeData) => api.post<AsyncJobResponse>('/creatives/generate', data),
  exportPdf: () => api.get('/creatives/export/pdf', { responseType: 'blob' }),
};

// ── Content Studio ──────────────────────────────────────────────────────────

export interface ContentPackResponse {
  pack_id: string;
  job_id: string;
  status: string;
}

export interface ContentVariant {
  id: string;
  channel: string;
  format: string;
  variant_index: number;
  output_json: Record<string, any>;
  score: number;
  score_breakdown_json: Record<string, number>;
  rationale_text: string;
}

export interface ContentPackSummary {
  id: string;
  creative_id: string;
  status: string;
  goal: string;
  language: string;
  channels_json: Array<{ channel: string; format?: string }>;
  input_json: Record<string, any>;
  last_error_code: string;
  last_error_message: string;
  created_at: string;
  variants_count: number;
}

export const contentStudioApi = {
  listChannels: () => api.get('/content-studio/channels'),
  listPacks: (limit?: number) =>
    api.get<ContentPackSummary[]>('/content-studio/packs', { params: { limit: limit || 20 } }),
  createPack: (data: any) => api.post<ContentPackResponse>('/content-studio/packs', data),
  getPack: (packId: string) => api.get(`/content-studio/packs/${packId}`),
  getVariants: (packId: string, channel?: string) =>
    api.get<ContentVariant[]>(`/content-studio/packs/${packId}/variants`, { params: channel ? { channel } : {} }),
  lockVariant: (packId: string, data: { channel: string; variant_id: string }) =>
    api.post(`/content-studio/packs/${packId}/lock`, data),
  getLocks: (packId: string) =>
    api.get<Record<string, string>>(`/content-studio/packs/${packId}/locks`),
  regenerate: (packId: string, channels?: string[]) =>
    api.post<ContentPackResponse>(`/content-studio/packs/${packId}/regenerate`, { channels: channels || [] }),
  exportPdf: (packId: string) =>
    api.get(`/content-studio/packs/${packId}/export/pdf`, { responseType: 'blob' }),
  exportXlsx: (packId: string) =>
    api.get(`/content-studio/packs/${packId}/export/xlsx`, { responseType: 'blob' }),
};

// ── Saturation ───────────────────────────────────────────────────────────────

export interface SaturationMetric {
  angle_id: string;
  angle_name: string;
  saturation_score: number;
  status: 'fresh' | 'moderate' | 'saturated';
  ctr_trend: number;
  frequency: number;
  cpm_inflation: number;
  recommendation: string;
  // Detailed analysis
  frequency_score: number;
  ctr_decay_score: number;
  cpm_inflation_score: number;
  ctr_recent: number;
  ctr_peak: number;
  cpm_recent: number;
  cpm_baseline: number;
  total_spend: number;
  total_impressions: number;
  days_active: number;
  spend_share_pct: number;
}

export const saturationApi = {
  analyze: () => api.get<SaturationMetric[]>('/saturation/analyze'),
  analyzeMeta: (days?: number) => api.get<SaturationMetric[]>('/saturation/analyze-meta', { params: { days } }),
  uploadCsv: (file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post<SaturationMetric[]>('/saturation/upload-csv', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  downloadReport: (metric: SaturationMetric) =>
    api.post('/saturation/report', metric, { responseType: 'blob' }),
};

// ── Audit ────────────────────────────────────────────────────────────────────

export interface AuditEntry {
  id: string;
  timestamp: string;
  user_email: string;
  action_type: string;
  entity_type: string;
  entity_id: string;
  status: 'success' | 'failed' | 'dry_run';
  changes: Record<string, unknown>;
  trace_id: string;
  error_message: string | null;
}

export interface AuditStats {
  total_executions: number;
  successful: number;
  failed: number;
  dry_run: number;
  period_days: number;
}

export const auditApi = {
  list: (params?: { status?: string; action_type?: string; limit?: number }) =>
    api.get<AuditEntry[]>('/audit/', { params }),
  stats: (days: number = 7) =>
    api.get<AuditStats>('/audit/stats/summary', { params: { days } }),
};

// ── Dashboard ───────────────────────────────────────────────────────────────

export interface DashboardKPI {
  label: string;
  value: string;
  change: string | null;
  trend: 'up' | 'down' | null;
}

export interface DashboardData {
  kpis: DashboardKPI[];
  summary: {
    total_decisions: number;
    success_rate: number;
    executed_period: number;
    successful: number;
    dry_runs: number;
    period_days: number;
  };
}

export const dashboardApi = {
  getKpis: (days: number = 1) => api.get<DashboardData>('/dashboard/kpis', { params: { days } }),
};

// ── Health ────────────────────────────────────────────────────────────────────

export const healthApi = {
  check: () => api.get('/health'),
};

// ── Billing (Sprint 4) ──────────────────────────────────────────────────────

export const billingApi = {
  getStatus: () => api.get('/billing/status'),
  createCheckout: (plan: string) => api.post('/billing/checkout', { plan }),
  createPortal: () => api.post('/billing/portal', {}),
};

// ── Team / Invites (Sprint 4) ───────────────────────────────────────────────

export const teamApi = {
  listMembers: () => api.get('/orgs/members'),
  sendInvite: (data: { email: string; role: string }) => api.post('/orgs/invites', data),
  listInvites: () => api.get('/orgs/invites'),
  revokeInvite: (id: string) => api.delete(`/orgs/invites/${id}`),
};

// ── Branding (Sprint 4) ─────────────────────────────────────────────────────

export const brandingApi = {
  get: () => api.get('/orgs/branding'),
  update: (data: { primary_color?: string; accent_color?: string; company_name?: string }) =>
    api.put('/orgs/branding', data),
};

// ── API Keys (Sprint 4) ─────────────────────────────────────────────────────

export const apiKeysApi = {
  create: (data: { name: string; scopes?: string[]; expires_in_days?: number }) =>
    api.post('/keys', data),
  list: () => api.get('/keys'),
  revoke: (id: string) => api.delete(`/keys/${id}`),
};

// ── Rankings + Outcomes + Brain (Sprint 5) ──────────────────────────────────

export interface RankedDecision extends Decision {
  score_total: number;
  score_impact: number;
  score_risk: number;
  score_confidence: number;
  score_freshness: number;
  explanation: Record<string, string>;
}

export interface RankExplanation {
  decision_id: string;
  score_total: number;
  score_impact: number;
  score_risk: number;
  score_confidence: number;
  score_freshness: number;
  rank_version: number;
  explanation: Record<string, string>;
}

export interface OutcomeEntry {
  id: string;
  decision_id: string;
  entity_type: string;
  entity_id: string;
  action_type: string;
  horizon_minutes: number;
  dry_run: boolean;
  outcome_label: string | null;
  confidence: number;
  before_metrics_json: Record<string, any> | null;
  after_metrics_json: Record<string, any> | null;
  delta_metrics_json: Record<string, any> | null;
  executed_at: string;
  created_at: string;
}

export interface FeatureStats {
  feature_type: string;
  feature_key: string;
  win_rate: number;
  samples: number;
  avg_delta: Record<string, any>;
}

export interface RecentOutcome {
  entity_type: string;
  entity_id: string;
  action_type: string;
  outcome_label: string;
  confidence: number;
  horizon_minutes: number;
  executed_at: string;
  detail: Record<string, any>;
}

export interface EntityTrust {
  entity_type: string;
  entity_id: string;
  trust_score: number;
  last_outcome: string | null;
  last_seen_at: string | null;
  detail: Record<string, any> & {
    trust_ctr_score?: number;
    trust_efficiency_score?: number;
    trust_stability_score?: number;
    trust_formula?: string;
    entity_meta_id?: string;
  };
}

export interface BrainSummary {
  total_campaigns: number;
  avg_trust: number;
  win_count: number;
  loss_count: number;
  total_spend: number;
  total_clicks: number;
  total_impressions: number;
  avg_ctr: number;
  avg_cpc: number;
  avg_cpm: number;
  period_days: number;
  spend_trend: number | null;
  ctr_trend: number | null;
  cpc_trend: number | null;
}

export interface BrainStats {
  summary: BrainSummary;
  top_features: FeatureStats[];
  recent_outcomes: RecentOutcome[];
  entity_trust: EntityTrust[];
}

export const rankingsApi = {
  listRanked: (params?: { state?: string; limit?: number }) =>
    api.get<RankedDecision[]>('/decisions/ranked', { params }),
  getExplanation: (id: string) =>
    api.get<RankExplanation>(`/decisions/${id}/rank-explanation`),
};

export const outcomesApi = {
  getForDecision: (id: string) =>
    api.get<OutcomeEntry[]>(`/decisions/${id}/outcomes`),
  runPending: (limit: number = 50) =>
    api.post('/internal/run-outcomes', null, { params: { limit } }),
};

export interface BrainSuggestion {
  type: string;
  entity_id: string;
  title: string;
  description: string;
  metrics: Record<string, any>;
}

export interface FlywheelRecommendation {
  module: string;
  reason: string;
  priority: number;
  action_label: string;
  route_path: string;
}

export interface EntityAnalysis {
  entity: EntityTrust & Record<string, any>;
  analysis_text: string;
  flywheel_next: FlywheelRecommendation;
}

export interface FeatureAnalysis {
  feature: FeatureStats;
  analysis_text: string;
}

export interface OutcomeAnalysis {
  outcome: RecentOutcome;
  analysis_text: string;
}

export const brainApi = {
  getStats: (days?: number, since?: string, until?: string) =>
    api.get<BrainStats>('/brain/stats', { params: { days, since, until } }),
  getSuggestions: (days?: number, since?: string, until?: string) =>
    api.get<{ suggestions: BrainSuggestion[] }>('/brain/suggestions', { params: { days, since, until } }),
  exportPdf: (days?: number, since?: string, until?: string) =>
    api.get('/brain/export/pdf', { params: { days, since, until }, responseType: 'blob' }),
  exportXlsx: (days?: number, since?: string, until?: string) =>
    api.get('/brain/export/xlsx', { params: { days, since, until }, responseType: 'blob' }),
  getEntityAnalysis: (entityId: string, days?: number, since?: string, until?: string) =>
    api.get<EntityAnalysis>(`/brain/entity/${encodeURIComponent(entityId)}/analysis`, { params: { days, since, until } }),
  getFeatureAnalysis: (featureName: string, days?: number, since?: string, until?: string) =>
    api.get<FeatureAnalysis>(`/brain/feature/${encodeURIComponent(featureName)}/analysis`, { params: { days, since, until } }),
  getOutcomeAnalysis: (outcomeIdx: number, days?: number, since?: string, until?: string) =>
    api.get<OutcomeAnalysis>(`/brain/outcome/${outcomeIdx}/analysis`, { params: { days, since, until } }),
  getFlywheelRecommendations: (days?: number, since?: string, until?: string) =>
    api.get<{ recommendations: FlywheelRecommendation[] }>('/brain/flywheel', { params: { days, since, until } }),
  exportEntityPdf: (entityId: string, days?: number, since?: string, until?: string) =>
    api.get(`/brain/entity/${encodeURIComponent(entityId)}/pdf`, { params: { days, since, until }, responseType: 'blob' }),
};

// ── Meta Sync (Sprint 6) ───────────────────────────────────────────────────

export interface SyncStatus {
  ad_account_id: string | null;
  meta_account_id: string | null;
  last_assets_sync: string | null;
  last_insights_sync: string | null;
  last_monitor_sync: string | null;
  assets_lag_minutes: number | null;
  insights_lag_minutes: number | null;
  recent_error_count: number;
  pending_jobs: number;
}

export interface MetaCampaignItem {
  id: string;
  meta_campaign_id: string;
  name: string | null;
  objective: string | null;
  status: string | null;
  effective_status: string | null;
  daily_budget: number | null;
  lifetime_budget: number | null;
  bid_strategy: string | null;
}

export interface MetaInsight {
  entity_meta_id: string;
  level: string;
  date_start: string;
  spend: number | null;
  impressions: number | null;
  clicks: number | null;
  ctr: number | null;
  cpm: number | null;
  cpc: number | null;
  frequency: number | null;
  conversions: number | null;
  purchase_roas: number | null;
}

export interface MetaAlertItem {
  id: string;
  alert_type: string;
  severity: string;
  message: string;
  entity_type: string | null;
  entity_meta_id: string | null;
  detected_at: string;
  resolved_at: string | null;
  payload: Record<string, any> | null;
}

export const metaSyncApi = {
  getSyncStatus: () => api.get<SyncStatus[]>('/meta/sync/status'),
  triggerSync: () => api.post('/meta/sync/now'),
  syncActiveAccount: () => api.post('/meta/sync/active'),
  getCampaigns: (params?: { status?: string; search?: string }) =>
    api.get<MetaCampaignItem[]>('/meta/campaigns', { params }),
  getInsights: (params?: { level?: string; entity_id?: string; since?: string; until?: string }) =>
    api.get<MetaInsight[]>('/meta/insights', { params }),
  getAlerts: (params?: { severity?: string; limit?: number }) =>
    api.get<MetaAlertItem[]>('/meta/alerts', { params }),
  getSignals: (limit?: number) =>
    api.get<MetaAlertItem[]>('/meta/insights/signals', { params: { limit: limit || 20 } }),
  getAnomalies: (limit?: number) =>
    api.get<MetaAlertItem[]>('/meta/anomalies', { params: { limit: limit || 20 } }),
};

// ── Ops Console (Sprint 7) ──────────────────────────────────────────────────

export interface JobRunItem {
  id: string;
  org_id: string;
  job_type: string;
  status: string;
  queue: string | null;
  attempts: number;
  max_attempts: number;
  payload: Record<string, any> | null;
  scheduled_for: string | null;
  started_at: string | null;
  finished_at: string | null;
  last_error_code: string | null;
  last_error_message: string | null;
  trace_id: string | null;
  idempotency_key: string | null;
  created_at: string | null;
}

export interface ProviderStatus {
  provider: string;
  circuit_state: string;
  failure_count: number;
  rate_limit_remaining: number;
  rate_limit_total: number;
}

export interface QueueStats {
  queue_name: string;
  pending: number;
  running: number;
  failed: number;
}

export const opsApi = {
  listJobs: (params?: { status?: string; job_type?: string; limit?: number }) =>
    api.get<JobRunItem[]>('/ops/jobs', { params }),
  getJob: (id: string) => api.get<JobRunItem>(`/ops/jobs/${id}`),
  retryJob: (id: string) => api.post(`/ops/jobs/${id}/retry`),
  cancelJob: (id: string) => api.post(`/ops/jobs/${id}/cancel`),
  listProviders: () => api.get<ProviderStatus[]>('/ops/providers'),
  listQueues: () => api.get<QueueStats[]>('/ops/queues'),
};

// ── Onboarding (Sprint 8) ──────────────────────────────────────────────────

export const onboardingApi = {
  getStatus: () => api.get('/onboarding/status'),
  advanceStep: (step: string, data?: Record<string, any>) =>
    api.post(`/onboarding/step/${step}`, data || {}),
  complete: () => api.post('/onboarding/complete'),
};

// ── Templates (Sprint 8) ───────────────────────────────────────────────────

export interface Template {
  id: string;
  slug: string;
  name: string;
  description: string;
  vertical: string;
  default_config: Record<string, any>;
}

export const templatesApi = {
  list: () => api.get<Template[]>('/templates/'),
  get: (id: string) => api.get<Template>(`/templates/${id}`),
  install: (id: string, overrides?: Record<string, any>) =>
    api.post(`/templates/${id}/install`, { overrides }),
};

// ── Org Config (Sprint 8) ──────────────────────────────────────────────────

export const orgConfigApi = {
  get: () => api.get('/org-config/'),
  update: (overrides: Record<string, any>) =>
    api.put('/org-config/', { overrides }),
  getFeatureFlags: () => api.get('/org-config/feature-flags'),
};

// ── Reports (Sprint 11) ──────────────────────────────────────────────────

export const reportsApi = {
  downloadDecisionDocx: (decisionId: string) =>
    api.get(`/reports/decisions/${decisionId}/docx`, { responseType: 'blob' }),
  downloadDecisionXlsx: (decisionId: string) =>
    api.get(`/reports/decisions/${decisionId}/xlsx`, { responseType: 'blob' }),
};

// ── Alert Center (Sprint 8) ────────────────────────────────────────────────

export const alertsApi = {
  list: (params?: { status?: string; severity?: string; alert_type?: string; limit?: number; offset?: number }) =>
    api.get('/alerts/', { params }),
  getStats: () => api.get('/alerts/stats'),
  get: (id: string) => api.get(`/alerts/${id}`),
  acknowledge: (id: string) => api.post(`/alerts/${id}/acknowledge`),
  resolve: (id: string) => api.post(`/alerts/${id}/resolve`),
  snooze: (id: string, snoozeUntil?: string) =>
    api.post(`/alerts/${id}/snooze`, { snooze_until: snoozeUntil }),
  exportPdf: (params?: { status?: string; severity?: string }) =>
    api.get('/alerts/export/pdf', { params, responseType: 'blob' }),
};

// ── Analytics (Sprint 8+) ──────────────────────────────────────────────────

export interface MetricsBucket {
  label: string;
  spend: number;
  clicks: number;
  impressions: number;
  ctr: number;
  cpc: number;
  cpm: number;
  conversions: number;
}

export interface MetricsOverTimeResponse {
  buckets: MetricsBucket[];
  bucket_type: 'daily' | 'weekly' | 'monthly';
}

export interface PerformanceSummary {
  total_spend: number;
  total_impressions: number;
  total_clicks: number;
  total_conversions: number;
  avg_ctr: number;
  avg_cpc: number;
  avg_cpm: number;
  avg_roas: number;
  active_campaigns: number;
  period_days: number;
  currency: string;
  spend_trend: number | null;
  impressions_trend: number | null;
  clicks_trend: number | null;
  conversions_trend: number | null;
  ctr_trend: number | null;
  cpc_trend: number | null;
  roas_trend: number | null;
}

export interface TopCampaign {
  campaign_id: string;
  name: string;
  objective: string;
  status: string;
  spend: number;
  clicks: number;
  impressions: number;
  conversions: number;
  ctr: number;
  cpc: number;
  cpm: number;
  roas: number;
  frequency: number;
}

export interface InsightItem {
  type: 'positive' | 'warning' | 'info';
  title: string;
  description: string;
  metric_value: string;
}

export interface InsightsResponse {
  insights: InsightItem[];
}

export const analyticsApi = {
  getSummary: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get<PerformanceSummary>('/analytics/summary', { params: { days, since, until, ad_account_id } }),
  getMetricsOverTime: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get<MetricsOverTimeResponse>('/analytics/metrics-over-time', { params: { days, since, until, ad_account_id } }),
  getInsights: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get<InsightsResponse>('/analytics/insights', { params: { days, since, until, ad_account_id } }),
  getTopCampaigns: (days?: number, limit?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get<TopCampaign[]>('/analytics/top-campaigns', { params: { days, limit, since, until, ad_account_id } }),
  getSpendOverTime: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get('/analytics/spend-over-time', { params: { days, since, until, ad_account_id } }),
  getDaily: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get('/analytics/daily', { params: { days, since, until, ad_account_id } }),
  getBenchmarks: () => api.get('/analytics/benchmarks'),
  exportPdf: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get('/analytics/export/pdf', { params: { days, since, until, ad_account_id }, responseType: 'blob' }),
  exportXlsx: (days?: number, since?: string, until?: string, ad_account_id?: string) =>
    api.get('/analytics/export/xlsx', { params: { days, since, until, ad_account_id }, responseType: 'blob' }),
};

// ── BrandMap Profiles ───────────────────────────────────────────────────────

export interface BrandMapProfile {
  id: string;
  org_id: string;
  name: string;
  raw_text: string;
  structured_json: Record<string, any> | null;
  status: 'pending_analysis' | 'analyzing' | 'ready' | 'error';
  last_analyzed_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string | null;
}

export const brandMapApi = {
  list: () => api.get<BrandMapProfile[]>('/brandmap/'),
  get: (id: string) => api.get<BrandMapProfile>(`/brandmap/${id}`),
  create: (data: { name: string; raw_text: string }) =>
    api.post<BrandMapProfile>('/brandmap/', data),
  update: (id: string, data: { name?: string; raw_text?: string }) =>
    api.put<BrandMapProfile>(`/brandmap/${id}`, data),
  delete: (id: string) => api.delete(`/brandmap/${id}`),
  analyze: (id: string) => api.post<BrandMapProfile>(`/brandmap/${id}/analyze`),
  exportPdf: (profileId?: string) =>
    api.get('/brandmap/export/pdf', { params: { profile_id: profileId }, responseType: 'blob' }),
};

// ── Competitive Intelligence / Radar ────────────────────────────────────────

export interface CICompetitor {
  id: string;
  name: string;
  website_url?: string;
  logo_url?: string;
  notes?: string;
  status?: string;
  platform: string;
  total_ads: number;
  active_ads: number;
  last_seen: string | null;
  domains?: { id: string; domain: string; domain_type: string }[];
  created_at?: string;
}

export interface CIAnalysis {
  competitor_strategy: string;
  messaging_angles: string[];
  brand_comparison: string;
  recommendations: string[];
  ad_copy_suggestions: string[];
  opportunities: string[];
  threat_level: 'low' | 'medium' | 'high';
}

export interface CIItem {
  id: string;
  competitor: string;
  platform: string;
  item_type: 'ad' | 'offer' | 'keyword';
  headline: string;
  body: string;
  cta: string;
  format: string;
  country: string;
  price: number | null;
  discount: string;
  first_seen: string;
  last_seen: string;
  fingerprint: string;
  metadata: Record<string, any>;
  has_analysis?: boolean;
  analysis?: CIAnalysis;
}

export interface CIOpportunity {
  id: string;
  type: string;
  title: string;
  description: string;
  confidence_score: number;
  impact_score: number;
  priority_score: number;
  evidence_ids: string[];
  detected_at: string;
  expires_at: string | null;
  suggested_actions: string[];
  rationale: string;
}

export interface CISearchParams {
  q?: string;
  competitor?: string;
  item_type?: string;
  platform?: string;
  format?: string;
  min_date?: string;
  max_date?: string;
  limit?: number;
  offset?: number;
}

export const ciApi = {
  competitors: () => api.get<CICompetitor[]>('/ci/competitors'),
  createCompetitor: (data: { name: string; website_url?: string; notes?: string; domains?: { domain: string; domain_type: string }[] }) =>
    api.post<CICompetitor>('/ci/competitors', data),
  deleteCompetitor: (id: string) => api.delete(`/ci/competitors/${id}`),
  search: (params: CISearchParams) =>
    api.get<CIItem[]>('/ci/feed', { params }),
  similar: (itemId: string, limit?: number) =>
    api.post<{ results: CIItem[]; count: number }>('/ci/similar', { item_id: itemId, n_results: limit || 10 }),
  opportunities: (params?: { type?: string; min_priority?: number; min_confidence?: number; limit?: number }) =>
    api.get<CIOpportunity[]>('/ci/opportunities', { params }),
  runDetection: () =>
    api.post<{ status: string; summary: Record<string, any> }>('/ci/autoloop/run-now'),
  exportPdf: () => api.get('/ci/export/pdf', { responseType: 'blob' }),
  exportXlsx: () => api.get('/ci/export/xlsx', { responseType: 'blob' }),
  analyzeItem: (itemId: string, forceRefresh = false) =>
    api.post<{ item_id: string; has_brand_context: boolean; analysis: CIAnalysis; generated_at: string; model: string; cached: boolean; tokens_used: number }>(
      `/ci/items/${itemId}/analyze`, null, { params: { force_refresh: forceRefresh } }
    ),
  getItemAnalysis: (itemId: string) =>
    api.get<{ has_analysis: boolean; analysis?: CIAnalysis; generated_at?: string; model?: string }>(`/ci/items/${itemId}/analysis`),
  exportAnalysisPdf: (itemId?: string) =>
    api.get('/ci/export/analysis-pdf', { params: itemId ? { item_id: itemId } : {}, responseType: 'blob' }),
  discoverCompetitors: (query: string, country = '', limit = 5) =>
    api.post<{ competitors: { name: string; website_url: string; reason: string }[]; model: string; tokens_used: number }>(
      '/ci/competitors/discover', null, { params: { query, ...(country ? { country } : {}), limit } }
    ),
};

// ── Product Events (Sprint 8) ──────────────────────────────────────────────

export const eventsApi = {
  track: (eventName: string, properties?: Record<string, any>) =>
    api.post('/events/track', { event_name: eventName, properties }),
  getFunnel: () => api.get('/events/funnel'),
};

// ── Flywheel ───────────────────────────────────────────────────────────────
export interface FlywheelStepResponse {
  id: string;
  step_name: string;
  step_order: number;
  status: string;
  job_run_id: string | null;
  artifacts_json: Record<string, any>;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
}

export interface FlywheelRunResponse {
  id: string;
  status: string;
  trigger: string;
  config_json: Record<string, any>;
  outputs_json: Record<string, any>;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  steps: FlywheelStepResponse[];
  created_at: string;
}

export const flywheelApi = {
  run: (config?: Record<string, any>) =>
    api.post<{ run_id: string; job_id: string; status: string }>('/flywheel/run', config || {}),
  listRuns: (limit?: number) =>
    api.get<FlywheelRunResponse[]>('/flywheel/runs', { params: { limit } }),
  getRun: (id: string) =>
    api.get<FlywheelRunResponse>(`/flywheel/runs/${id}`),
  retryStep: (runId: string, stepId: string) =>
    api.post(`/flywheel/runs/${runId}/retry/${stepId}`),
  cancelRun: (runId: string) =>
    api.post(`/flywheel/runs/${runId}/cancel`),
  exportPdf: (runId: string) =>
    api.get(`/flywheel/runs/${runId}/export`, { responseType: 'blob' }),
  getSummary: (runId: string) =>
    api.get<{ summary: string }>(`/flywheel/runs/${runId}/summary`),
};

// ── Data Room ──────────────────────────────────────────────────────────────
export interface DataRoomDataset {
  key: string;
  label: string;
  description: string;
}

export interface DataRoomSchemaResponse {
  datasets: DataRoomDataset[];
  filters: string[];
}

export interface DataExportResponse {
  id: string;
  status: string;
  rows_exported: number;
  created_at: string;
  finished_at: string | null;
  last_error: string | null;
  params_json: Record<string, any>;
}

export const dataRoomApi = {
  getSchema: () =>
    api.get<DataRoomSchemaResponse>('/data-room/schema'),
  createExport: (params: Record<string, any>) =>
    api.post<{ export_id: string; job_id: string; status: string }>('/data-room/export', params),
  listExports: () =>
    api.get<DataExportResponse[]>('/data-room/exports'),
  getExport: (id: string) =>
    api.get<DataExportResponse>(`/data-room/exports/${id}`),
  downloadExport: (id: string) =>
    api.get(`/data-room/exports/${id}/download`, { responseType: 'blob' }),
};

export default api;
