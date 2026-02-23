/**
 * Brand Profile page — Manage multi-brand profiles with 9-layer strategic analysis.
 * CRUD + LLM analysis + PDF export.
 */
import { useState, useEffect, useCallback } from 'react';
import {
  BookOpen, Plus, Sparkles, FileDown, Trash2, Edit3, Save, X, Loader,
  Target, Users, Shield, Megaphone, Palette, Globe, Swords, Lightbulb,
  Heart, BarChart3, TrendingUp, DollarSign, MousePointerClick,
} from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { brandMapApi, BrandMapProfile } from '../services/api';
import { downloadBlob } from '../utils/download';
import './BrandProfile.css';

export default function BrandProfile() {
  const { language } = useLanguage();

  const [profiles, setProfiles] = useState<BrandMapProfile[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Create modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createName, setCreateName] = useState('');
  const [createRawText, setCreateRawText] = useState('');
  const [creating, setCreating] = useState(false);

  // Edit mode
  const [editing, setEditing] = useState(false);
  const [editRawText, setEditRawText] = useState('');
  const [editName, setEditName] = useState('');
  const [saving, setSaving] = useState(false);

  // Actions
  const [analyzing, setAnalyzing] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);

  const selectedProfile = profiles.find(p => p.id === selectedId) || null;

  const fetchProfiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await brandMapApi.list();
      const data = res.data;
      setProfiles(data);
      // Auto-select first profile if none selected
      if (data.length > 0 && !selectedId) {
        setSelectedId(data[0].id);
      }
    } catch (err: any) {
      console.error('Failed to fetch brand profiles:', err);
      setError(err.response?.data?.detail || 'Failed to load brand profiles');
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    fetchProfiles();
  }, []);

  const handleCreate = async () => {
    if (!createName.trim() || !createRawText.trim()) return;
    try {
      setCreating(true);
      const res = await brandMapApi.create({ name: createName.trim(), raw_text: createRawText });
      setProfiles(prev => [res.data, ...prev]);
      setSelectedId(res.data.id);
      setShowCreateModal(false);
      setCreateName('');
      setCreateRawText('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to create profile');
    } finally {
      setCreating(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!selectedProfile) return;
    try {
      setSaving(true);
      const res = await brandMapApi.update(selectedProfile.id, {
        name: editName.trim() || undefined,
        raw_text: editRawText || undefined,
      });
      setProfiles(prev => prev.map(p => p.id === res.data.id ? res.data : p));
      setEditing(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleAnalyze = async () => {
    if (!selectedProfile) return;
    try {
      setAnalyzing(true);
      setError(null);
      const res = await brandMapApi.analyze(selectedProfile.id);
      setProfiles(prev => prev.map(p => p.id === res.data.id ? res.data : p));
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Analysis failed');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedProfile) return;
    const confirmed = window.confirm(
      language === 'es'
        ? `¿Eliminar el perfil "${selectedProfile.name}"?`
        : `Delete profile "${selectedProfile.name}"?`
    );
    if (!confirmed) return;
    try {
      await brandMapApi.delete(selectedProfile.id);
      setProfiles(prev => prev.filter(p => p.id !== selectedProfile.id));
      setSelectedId(profiles.length > 1 ? profiles.find(p => p.id !== selectedProfile.id)?.id || null : null);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to delete');
    }
  };

  const handleExportPdf = async () => {
    if (!selectedProfile) return;
    try {
      setExportingPdf(true);
      const res = await brandMapApi.exportPdf(selectedProfile.id);
      downloadBlob(res.data, `brand_profile_${selectedProfile.name.replace(/\s+/g, '_')}.pdf`, 'application/pdf');
    } catch (err) {
      console.error('Failed to export PDF:', err);
    } finally {
      setExportingPdf(false);
    }
  };

  const startEditing = () => {
    if (!selectedProfile) return;
    setEditName(selectedProfile.name);
    setEditRawText(selectedProfile.raw_text);
    setEditing(true);
  };

  const data = selectedProfile?.structured_json || null;

  return (
    <div className="brand-profile-page">
      {/* Header */}
      <div className="brand-header">
        <div className="brand-header-content">
          <BookOpen size={32} className="page-icon" />
          <div>
            <h1 className="page-title">
              {language === 'es' ? 'Perfil de Marca' : 'Brand Profile'}
            </h1>
            <p className="page-description">
              {language === 'es'
                ? 'Análisis estratégico de marca en 9 capas con IA'
                : 'AI-powered 9-layer strategic brand analysis'}
            </p>
          </div>
        </div>
        <div className="brand-header-actions">
          <button className="btn-primary" onClick={() => setShowCreateModal(true)}>
            <Plus size={18} />
            {language === 'es' ? 'Nueva Marca' : 'New Brand'}
          </button>
          {selectedProfile && selectedProfile.structured_json && (
            <button className="btn-secondary" onClick={handleExportPdf} disabled={exportingPdf}>
              <FileDown size={18} />
              {exportingPdf ? 'Exporting...' : 'Export PDF'}
            </button>
          )}
        </div>
      </div>

      {/* Profile Selector */}
      {profiles.length > 0 && (
        <div className="brand-selector">
          <select
            value={selectedId || ''}
            onChange={e => { setSelectedId(e.target.value); setEditing(false); }}
          >
            {profiles.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          {selectedProfile && (
            <>
              <span className={`brand-status-badge brand-status-${selectedProfile.status}`}>
                {selectedProfile.status === 'ready' && (language === 'es' ? 'Analizado' : 'Analyzed')}
                {selectedProfile.status === 'pending_analysis' && (language === 'es' ? 'Pendiente' : 'Pending')}
                {selectedProfile.status === 'analyzing' && (language === 'es' ? 'Analizando...' : 'Analyzing...')}
                {selectedProfile.status === 'error' && 'Error'}
              </span>
              <button className="btn-primary" onClick={handleAnalyze} disabled={analyzing}>
                {analyzing ? <Loader size={16} className="spin-icon" /> : <Sparkles size={16} />}
                {analyzing
                  ? (language === 'es' ? 'Analizando...' : 'Analyzing...')
                  : (language === 'es' ? 'Analizar con IA' : 'Analyze with AI')}
              </button>
              {!editing && (
                <button className="btn-secondary" onClick={startEditing}>
                  <Edit3 size={16} />
                </button>
              )}
              <button
                className="btn-secondary"
                onClick={handleDelete}
                style={{ color: 'var(--terracotta-500)' }}
              >
                <Trash2 size={16} />
              </button>
            </>
          )}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="brand-error-banner">{error}</div>
      )}

      {/* Analyzing indicator */}
      {(analyzing || selectedProfile?.status === 'analyzing') && (
        <div className="brand-analyzing">
          <Loader size={16} className="spin-icon" />
          {language === 'es'
            ? 'Analizando perfil de marca con IA... esto puede tomar 10-20 segundos.'
            : 'Analyzing brand profile with AI... this may take 10-20 seconds.'}
        </div>
      )}

      {/* Loading */}
      {loading ? (
        <div className="loading-state">{language === 'es' ? 'Cargando...' : 'Loading...'}</div>
      ) : profiles.length === 0 ? (
        /* Empty State */
        <div className="brand-empty-state">
          <BookOpen size={48} />
          <h3>{language === 'es' ? 'Sin perfiles de marca' : 'No brand profiles yet'}</h3>
          <p>
            {language === 'es'
              ? 'Crea tu primer perfil de marca para que la IA construya un análisis estratégico completo.'
              : 'Create your first brand profile so AI can build a complete strategic analysis.'}
          </p>
          <button className="btn-primary" onClick={() => setShowCreateModal(true)}>
            <Plus size={18} />
            {language === 'es' ? 'Crear Perfil de Marca' : 'Create Brand Profile'}
          </button>
        </div>
      ) : selectedProfile && (
        <>
          {/* Edit Mode */}
          {editing && (
            <div className="brand-editor">
              <div className="brand-editor-header">
                <h3>{language === 'es' ? 'Editar Datos de Marca' : 'Edit Brand Data'}</h3>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button className="btn-primary" onClick={handleSaveEdit} disabled={saving}>
                    <Save size={16} />
                    {saving ? '...' : (language === 'es' ? 'Guardar' : 'Save')}
                  </button>
                  <button className="btn-secondary" onClick={() => setEditing(false)}>
                    <X size={16} />
                  </button>
                </div>
              </div>
              <div className="brand-modal-field">
                <label>{language === 'es' ? 'Nombre de Marca' : 'Brand Name'}</label>
                <input
                  value={editName}
                  onChange={e => setEditName(e.target.value)}
                  placeholder="Brand name..."
                />
              </div>
              <textarea
                className="brand-raw-textarea"
                value={editRawText}
                onChange={e => setEditRawText(e.target.value)}
                placeholder={language === 'es'
                  ? 'Pega aquí toda la información de tu marca: misión, valores, producto, audiencia, competidores...'
                  : 'Paste all your brand information here: mission, values, product, audience, competitors...'}
              />
            </div>
          )}

          {/* Campaign Performance Intelligence — if Meta data was included */}
          {data?._meta_performance && data._meta_performance.campaign_count > 0 && (
            <CampaignIntelligence metrics={data._meta_performance} language={language} />
          )}

          {/* Structured Brand Layers — only if analyzed */}
          {data ? (
            <div className="brand-layers-grid">
              {/* 1. Core Identity */}
              <LayerCard
                icon={<Heart size={18} className="layer-icon" />}
                title={language === 'es' ? '1. Identidad Central' : '1. Core Identity'}
              >
                <LayerField label={language === 'es' ? 'Misión' : 'Mission'} value={data.core_identity?.mission} />
                <LayerTagList label={language === 'es' ? 'Valores' : 'Values'} items={data.core_identity?.values} />
                <LayerField label={language === 'es' ? 'Tono y Voz' : 'Tone & Voice'} value={data.core_identity?.tone_voice} />
                <LayerTagList label={language === 'es' ? 'Rasgos de Personalidad' : 'Personality Traits'} items={data.core_identity?.personality_traits} />
              </LayerCard>

              {/* 2. Offer Layer */}
              <LayerCard
                icon={<Target size={18} className="layer-icon" />}
                title={language === 'es' ? '2. Capa de Oferta' : '2. Offer Layer'}
              >
                <LayerField label={language === 'es' ? 'Producto Principal' : 'Main Product'} value={data.offer_layer?.main_product} />
                <LayerTagList label="Upsells" items={data.offer_layer?.upsells} />
                <LayerField label={language === 'es' ? 'Psicología de Precio' : 'Pricing Psychology'} value={data.offer_layer?.pricing_psychology} />
                <LayerField label={language === 'es' ? 'Reversión de Riesgo' : 'Risk Reversal'} value={data.offer_layer?.risk_reversal} />
              </LayerCard>

              {/* 3. Audience Model — full width */}
              <div className="brand-layer-card brand-layer-full">
                <h3>
                  <Users size={18} className="layer-icon" />
                  {language === 'es' ? '3. Modelo de Audiencia' : '3. Audience Model'}
                </h3>
                {(data.audience_model || []).map((av: any, i: number) => (
                  <div key={i} className="avatar-card">
                    <h4>{av.avatar_name || `Avatar ${i + 1}`}</h4>
                    <LayerField label={language === 'es' ? 'Demografía' : 'Demographics'} value={av.demographics} />
                    <LayerField label={language === 'es' ? 'Psicografía' : 'Psychographics'} value={av.psychographics} />
                    <LayerTagList label={language === 'es' ? 'Dolores' : 'Pains'} items={av.pains} />
                    <LayerTagList label={language === 'es' ? 'Deseos' : 'Desires'} items={av.desires} />
                    <LayerTagList label={language === 'es' ? 'Disparadores' : 'Triggers'} items={av.triggers} />
                  </div>
                ))}
              </div>

              {/* 4. Differentiation */}
              <LayerCard
                icon={<Shield size={18} className="layer-icon" />}
                title={language === 'es' ? '4. Diferenciación' : '4. Differentiation'}
              >
                <LayerField label="USP" value={data.differentiation_layer?.usp} />
                <LayerField label={language === 'es' ? 'Fosa Competitiva' : 'Competitive Moat'} value={data.differentiation_layer?.competitive_moat} />
                <LayerTagList label={language === 'es' ? 'Pruebas' : 'Proof Points'} items={data.differentiation_layer?.proof_points} />
              </LayerCard>

              {/* 5. Narrative Assets */}
              <LayerCard
                icon={<Megaphone size={18} className="layer-icon" />}
                title={language === 'es' ? '5. Activos Narrativos' : '5. Narrative Assets'}
              >
                <LayerField label={language === 'es' ? 'Historia de Marca' : 'Brand Lore'} value={data.narrative_assets?.lore} />
                <LayerTagList label="Story Hooks" items={data.narrative_assets?.story_hooks} />
                <LayerTagList label={language === 'es' ? 'Mitos Centrales' : 'Core Myths'} items={data.narrative_assets?.core_myths} />
              </LayerCard>

              {/* 6. Creative DNA */}
              <LayerCard
                icon={<Palette size={18} className="layer-icon" />}
                title={language === 'es' ? '6. ADN Creativo' : '6. Creative DNA'}
              >
                <LayerTagList label={language === 'es' ? 'Paleta de Color' : 'Color Palette'} items={data.creative_dna?.color_palette} />
                <LayerField label={language === 'es' ? 'Intención Tipográfica' : 'Typography Intent'} value={data.creative_dna?.typography_intent} />
                <LayerTagList label={language === 'es' ? 'Restricciones Visuales' : 'Visual Constraints'} items={data.creative_dna?.visual_constraints} />
              </LayerCard>

              {/* 7. Market Context */}
              <LayerCard
                icon={<Globe size={18} className="layer-icon" />}
                title={language === 'es' ? '7. Contexto de Mercado' : '7. Market Context'}
              >
                <LayerTagList label={language === 'es' ? 'Factores Estacionales' : 'Seasonal Factors'} items={data.market_context?.seasonal_factors} />
                <LayerTagList label={language === 'es' ? 'Tendencias Actuales' : 'Current Trends'} items={data.market_context?.current_trends} />
              </LayerCard>

              {/* 8. Competitor Map — full width */}
              <div className="brand-layer-card brand-layer-full">
                <h3>
                  <Swords size={18} className="layer-icon" />
                  {language === 'es' ? '8. Mapa de Competidores' : '8. Competitor Map'}
                </h3>
                {(data.competitor_map || []).map((comp: any, i: number) => (
                  <div key={i} className="competitor-card">
                    <h4>{comp.name || `Competitor ${i + 1}`}</h4>
                    <LayerField label={language === 'es' ? 'Estrategia' : 'Strategy'} value={comp.strategy_type} />
                    <LayerTagList label={language === 'es' ? 'Debilidades' : 'Weak Points'} items={comp.weak_points} />
                  </div>
                ))}
              </div>

              {/* 9. Opportunity Map — full width */}
              <div className="brand-layer-card brand-layer-full">
                <h3>
                  <Lightbulb size={18} className="layer-icon" />
                  {language === 'es' ? '9. Mapa de Oportunidades' : '9. Opportunity Map'}
                </h3>
                {(data.opportunity_map || []).map((opp: any, i: number) => {
                  const impact = opp.estimated_impact || 0;
                  const impactClass = impact >= 70 ? 'impact-high' : impact >= 40 ? 'impact-medium' : 'impact-low';
                  return (
                    <div key={i} className="opportunity-sub-card">
                      <h4>
                        <span>{opp.gap_id || `OPP-${i + 1}`}</span>
                        <span className={`impact-badge ${impactClass}`}>
                          Impact: {impact}%
                        </span>
                      </h4>
                      <LayerField label={language === 'es' ? 'Estrategia' : 'Strategy'} value={opp.strategy_recommendation} />
                      <LayerField label={language === 'es' ? 'Razonamiento' : 'Reasoning'} value={opp.impact_reasoning} />
                    </div>
                  );
                })}
              </div>
            </div>
          ) : !editing && (
            <div className="brand-empty-state">
              <Sparkles size={48} />
              <h3>
                {language === 'es'
                  ? 'Perfil sin analizar'
                  : 'Profile not analyzed yet'}
              </h3>
              <p>
                {language === 'es'
                  ? 'Haz clic en "Analizar con IA" para que la inteligencia artificial construya el análisis estratégico de 9 capas.'
                  : 'Click "Analyze with AI" to have AI build the complete 9-layer strategic analysis.'}
              </p>
              <button className="btn-primary" onClick={handleAnalyze} disabled={analyzing}>
                <Sparkles size={18} />
                {language === 'es' ? 'Analizar con IA' : 'Analyze with AI'}
              </button>
            </div>
          )}
        </>
      )}

      {/* Create Modal */}
      {showCreateModal && (
        <div className="brand-modal-overlay" onClick={() => setShowCreateModal(false)}>
          <div className="brand-modal" onClick={e => e.stopPropagation()}>
            <h2>{language === 'es' ? 'Nuevo Perfil de Marca' : 'New Brand Profile'}</h2>
            <div className="brand-modal-field">
              <label>{language === 'es' ? 'Nombre de Marca' : 'Brand Name'}</label>
              <input
                value={createName}
                onChange={e => setCreateName(e.target.value)}
                placeholder={language === 'es' ? 'Ej: Mi Empresa' : 'e.g. My Company'}
              />
            </div>
            <div className="brand-modal-field">
              <label>{language === 'es' ? 'Datos de Marca (texto libre)' : 'Brand Data (free text)'}</label>
              <textarea
                value={createRawText}
                onChange={e => setCreateRawText(e.target.value)}
                placeholder={language === 'es'
                  ? 'Pega aquí toda la información de tu marca: misión, valores, producto, precio, audiencia, competidores, historia, identidad visual, oportunidades...\n\nMientras más detallado, mejor será el análisis de IA.'
                  : 'Paste all your brand information here: mission, values, product, pricing, audience, competitors, brand story, visual identity, opportunities...\n\nThe more detailed, the better the AI analysis.'}
              />
            </div>
            <div className="brand-modal-actions">
              <button className="btn-secondary" onClick={() => setShowCreateModal(false)}>
                {language === 'es' ? 'Cancelar' : 'Cancel'}
              </button>
              <button
                className="btn-primary"
                onClick={handleCreate}
                disabled={creating || !createName.trim() || !createRawText.trim()}
              >
                {creating
                  ? <Loader size={16} className="spin-icon" />
                  : <Plus size={16} />}
                {creating
                  ? (language === 'es' ? 'Creando...' : 'Creating...')
                  : (language === 'es' ? 'Crear Perfil' : 'Create Profile')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}


// ── Sub-Components ──────────────────────────────────────────────────────────


function LayerCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="brand-layer-card">
      <h3>{icon} {title}</h3>
      {children}
    </div>
  );
}

function LayerField({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="layer-field">
      <div className="layer-field-label">{label}</div>
      <div className="layer-field-value">{value}</div>
    </div>
  );
}

function LayerTagList({ label, items }: { label: string; items?: string[] }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="layer-field">
      <div className="layer-field-label">{label}</div>
      <div className="layer-tags">
        {items.map((item, i) => (
          <span key={i} className="layer-tag">{item}</span>
        ))}
      </div>
    </div>
  );
}

function CampaignIntelligence({ metrics, language }: { metrics: any; language: string }) {
  const topCampaigns = metrics.top_campaigns || [];
  return (
    <div className="campaign-intelligence">
      <div className="ci-header">
        <BarChart3 size={20} className="layer-icon" />
        <div>
          <h3>{language === 'es' ? 'Inteligencia de Campañas' : 'Campaign Intelligence'}</h3>
          <p className="ci-subtitle">
            {language === 'es'
              ? `Datos reales de ${metrics.campaign_count} campañas (${metrics.date_range || `últimos ${metrics.period_days} días`})`
              : `Real data from ${metrics.campaign_count} campaigns (${metrics.date_range || `last ${metrics.period_days} days`})`}
          </p>
        </div>
      </div>

      <div className="ci-kpi-grid">
        <div className="ci-kpi">
          <DollarSign size={16} />
          <div>
            <span className="ci-kpi-value">${metrics.total_spend?.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            <span className="ci-kpi-label">{language === 'es' ? 'Gasto Total' : 'Total Spend'}</span>
          </div>
        </div>
        <div className="ci-kpi">
          <TrendingUp size={16} />
          <div>
            <span className="ci-kpi-value">{metrics.avg_ctr?.toFixed(2)}%</span>
            <span className="ci-kpi-label">CTR</span>
          </div>
        </div>
        <div className="ci-kpi">
          <MousePointerClick size={16} />
          <div>
            <span className="ci-kpi-value">{metrics.total_clicks?.toLocaleString()}</span>
            <span className="ci-kpi-label">{language === 'es' ? 'Clics' : 'Clicks'}</span>
          </div>
        </div>
        <div className="ci-kpi">
          <Target size={16} />
          <div>
            <span className="ci-kpi-value">{metrics.total_conversions?.toLocaleString()}</span>
            <span className="ci-kpi-label">{language === 'es' ? 'Conversiones' : 'Conversions'}</span>
          </div>
        </div>
      </div>

      {topCampaigns.length > 0 && (
        <div className="ci-campaigns">
          <h4>{language === 'es' ? 'Top Campañas por Gasto' : 'Top Campaigns by Spend'}</h4>
          <div className="ci-campaigns-table">
            <div className="ci-row ci-row-header">
              <span>{language === 'es' ? 'Campaña' : 'Campaign'}</span>
              <span>{language === 'es' ? 'Objetivo' : 'Objective'}</span>
              <span>{language === 'es' ? 'Gasto' : 'Spend'}</span>
              <span>CTR</span>
              <span>{language === 'es' ? 'Conv.' : 'Conv.'}</span>
            </div>
            {topCampaigns.slice(0, 8).map((tc: any, i: number) => (
              <div key={i} className="ci-row">
                <span className="ci-campaign-name" title={tc.name}>{tc.name}</span>
                <span className="ci-objective">{tc.objective}</span>
                <span>${tc.spend?.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>
                <span>{tc.ctr?.toFixed(2)}%</span>
                <span>{tc.conversions?.toLocaleString()}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
