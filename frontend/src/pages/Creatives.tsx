import { useState, useEffect, useRef } from 'react';
import { Palette, Sparkles, FileText, Loader, Award, ChevronDown, ChevronUp, Layers, FileDown, Zap, Filter } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../contexts/LanguageContext';
import GenerateCreativeModal, { CreativeFormData } from '../components/GenerateCreativeModal';
import { creativesApi, Creative } from '../services/api';
import { useJobPolling } from '../hooks/useJobPolling';
import { downloadBlob } from '../utils/download';
import './Creatives.css';

const DIMENSION_LABELS: Record<string, { en: string; es: string }> = {
  hook_strength: { en: 'Hook Strength', es: 'Fuerza del Hook' },
  brand_alignment: { en: 'Brand Alignment', es: 'Alineación de Marca' },
  clarity: { en: 'Clarity', es: 'Claridad' },
  audience_fit: { en: 'Audience Fit', es: 'Ajuste de Audiencia' },
  cta_quality: { en: 'CTA Quality', es: 'Calidad del CTA' },
};

const DIMENSION_WEIGHTS: Record<string, number> = {
  hook_strength: 25,
  brand_alignment: 20,
  clarity: 20,
  audience_fit: 20,
  cta_quality: 15,
};

function getScoreColor(score: number): string {
  if (score >= 7) return 'var(--olive-500)';
  if (score >= 4) return 'var(--gold-500)';
  return 'var(--terracotta-500)';
}

export default function Creatives() {
  const { t, language } = useLanguage();
  const navigate = useNavigate();
  const [creatives, setCreatives] = useState<Creative[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [lastFormData, setLastFormData] = useState<CreativeFormData | null>(null);
  const [expandedCards, setExpandedCards] = useState<Set<string>>(new Set());
  const [exportingPdf, setExportingPdf] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<string>('');
  const [expandedIntel, setExpandedIntel] = useState<Set<string>>(new Set());

  const job = useJobPolling(jobId);
  const prevStatusRef = useRef<string | null>(null);

  useEffect(() => {
    fetchCreatives();
  }, [sourceFilter]);

  // Auto-refetch when job succeeds
  useEffect(() => {
    if (prevStatusRef.current !== job.status && job.status === 'succeeded') {
      setJobId(null);
      fetchCreatives();
    }
    if (job.error) {
      setError(job.error);
      setJobId(null);
    }
    prevStatusRef.current = job.status;
  }, [job.status, job.error]);

  const fetchCreatives = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await creativesApi.list(sourceFilter || undefined);
      setCreatives(res.data);
    } catch (err) {
      console.error('Failed to fetch creatives:', err);
      setError(t('common.error'));
    } finally {
      setLoading(false);
    }
  };

  const toggleIntel = (id: string) => {
    setExpandedIntel(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleGenerate = async (formData: CreativeFormData) => {
    setError(null);
    setLastFormData(formData);
    const angleId = formData.objective.toLowerCase().replace(/\s+/g, '_') || 'general';
    try {
      const res = await creativesApi.generate({
        angle_id: angleId,
        brand_map_id: formData.brand_profile_id || 'demo',
        n_variants: 3,
        brand_profile_id: formData.brand_profile_id || undefined,
        framework: formData.framework,
        hook_style: formData.hook_style,
        audience: formData.audience,
        objective: formData.objective,
        tone: formData.tone,
        format: formData.format,
      });
      setJobId(res.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start generation');
    }
  };

  const handleRetryGeneration = () => {
    if (lastFormData) {
      handleGenerate(lastFormData);
    }
  };

  const handleUseInCampaign = (creative: Creative) => {
    const rationale = `[Creative: ${creative.angle_name}] Score: ${(creative.score * 100).toFixed(0)}/100. ${creative.script.substring(0, 150)}...`;
    navigate(`/control-panel?action_type=creative_swap&entity_type=ad&entity_name=${encodeURIComponent(creative.angle_name)}&rationale=${encodeURIComponent(rationale)}&source=creatives`);
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      const res = await creativesApi.exportPdf();
      downloadBlob(res.data, 'creatives_report.pdf', 'application/pdf');
    } catch (err) {
      console.error('Failed to export PDF:', err);
    } finally {
      setExportingPdf(false);
    }
  };

  const toggleExpanded = (id: string) => {
    setExpandedCards(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Palette size={32} className="page-icon" />
          <div>
            <h1 className="page-title">{t('creatives.title')}</h1>
            <p className="page-description">{t('creatives.subtitle')}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <button className="btn-primary" onClick={() => setShowGenerateModal(true)}>
            <Sparkles size={18} />
            {t('creatives.generate_new')}
          </button>
          {creatives.length > 0 && (
            <button className="btn-secondary" onClick={handleExportPdf} disabled={exportingPdf}>
              <FileDown size={18} />
              {exportingPdf ? 'Exporting...' : 'Export PDF'}
            </button>
          )}
        </div>
      </div>

      <div className="source-filter-bar">
        <Filter size={16} />
        <span>{language === 'es' ? 'Fuente:' : 'Source:'}</span>
        <button
          className={`source-filter-btn ${sourceFilter === '' ? 'active' : ''}`}
          onClick={() => setSourceFilter('')}
        >
          {language === 'es' ? 'Todos' : 'All'}
        </button>
        <button
          className={`source-filter-btn ${sourceFilter === 'manual' ? 'active' : ''}`}
          onClick={() => setSourceFilter('manual')}
        >
          Manual
        </button>
        <button
          className={`source-filter-btn source-filter-flywheel ${sourceFilter === 'flywheel' ? 'active' : ''}`}
          onClick={() => setSourceFilter('flywheel')}
        >
          <Zap size={14} />
          Flywheel
        </button>
      </div>

      {job.isPolling && (
        <div className="info-banner">
          <Loader size={16} className="spin-icon" />
          <span>
            {language === 'es'
              ? <>Generando 3 variantes creativas… Estado: <strong>{job.status}</strong></>
              : <>Generating 3 creative variants… Status: <strong>{job.status}</strong></>
            }
          </span>
        </div>
      )}

      {error && (
        <div className="error-state">
          <p>{error}</p>
          <div style={{ display: 'flex', gap: '0.5rem', marginTop: '0.5rem', justifyContent: 'center' }}>
            {lastFormData && (
              <button onClick={handleRetryGeneration} className="btn-primary">
                {language === 'es' ? 'Reintentar' : 'Retry Generation'}
              </button>
            )}
            <button onClick={fetchCreatives} className="btn-secondary">
              {language === 'es' ? 'Actualizar Lista' : 'Refresh List'}
            </button>
          </div>
        </div>
      )}

      {loading ? (
        <div className="loading-state">{t('common.loading')}</div>
      ) : !error && (
        <div className="creatives-grid">
          {creatives.map((creative) => (
            <div key={creative.id} className={`creative-card ${creative.is_best ? 'creative-card-best' : ''}`}>
              <div className="creative-badges">
                {creative.is_best && (
                  <div className="creative-best-badge">
                    <Award size={14} />
                    {language === 'es' ? 'Mejor Opción' : 'Best Pick'}
                  </div>
                )}
                {creative.source === 'flywheel' && (
                  <div className="creative-flywheel-badge">
                    <Zap size={14} />
                    Flywheel
                  </div>
                )}
              </div>
              <div className="creative-header">
                <div>
                  <h3 className="creative-angle">{creative.angle_name}</h3>
                  <span className="creative-id">#{creative.angle_id}</span>
                </div>
                <div className="creative-score">
                  {(creative.score * 100).toFixed(0)}/100
                </div>
              </div>
              <div className="creative-script">
                <FileText size={16} />
                <p>{creative.script}</p>
              </div>

              {creative.overall_reasoning && (
                <div className="creative-reasoning">
                  {creative.overall_reasoning}
                </div>
              )}

              {creative.dimensions && (
                <button
                  className="creative-detail-toggle"
                  onClick={() => toggleExpanded(creative.id)}
                >
                  {expandedCards.has(creative.id) ? (
                    <><ChevronUp size={16} /> {language === 'es' ? 'Ocultar desglose' : 'Hide breakdown'}</>
                  ) : (
                    <><ChevronDown size={16} /> {language === 'es' ? 'Ver desglose de puntaje' : 'View score breakdown'}</>
                  )}
                </button>
              )}

              {expandedCards.has(creative.id) && creative.dimensions && (
                <div className="creative-dimensions">
                  {Object.entries(creative.dimensions).map(([key, dim]) => (
                    <div key={key} className="dimension-row">
                      <span className="dimension-label">
                        {DIMENSION_LABELS[key]?.[language] || key} ({DIMENSION_WEIGHTS[key] || 0}%)
                      </span>
                      <div className="dimension-track">
                        <div
                          className="dimension-fill"
                          style={{
                            width: `${(dim.score / 10) * 100}%`,
                            backgroundColor: getScoreColor(dim.score),
                          }}
                        />
                      </div>
                      <span className="dimension-val">{dim.score.toFixed(1)}</span>
                    </div>
                  ))}
                  {Object.entries(creative.dimensions).map(([key, dim]) => (
                    dim.reasoning && (
                      <div key={`${key}-reason`} className="dimension-reasoning">
                        <strong>{DIMENSION_LABELS[key]?.[language] || key}:</strong> {dim.reasoning}
                      </div>
                    )
                  ))}
                </div>
              )}

              {creative.source === 'flywheel' && creative.flywheel_metadata && (
                <>
                  <button
                    className="creative-detail-toggle flywheel-intel-toggle"
                    onClick={() => toggleIntel(creative.id)}
                  >
                    {expandedIntel.has(creative.id) ? (
                      <><ChevronUp size={16} /> {language === 'es' ? 'Ocultar inteligencia' : 'Hide intelligence'}</>
                    ) : (
                      <><Zap size={16} /> {language === 'es' ? 'Ver inteligencia del Flywheel' : 'View Flywheel intelligence'}</>
                    )}
                  </button>
                  {expandedIntel.has(creative.id) && (
                    <div className="flywheel-intel-panel">
                      <div className="flywheel-intel-grid">
                        {creative.flywheel_metadata.opportunities_used > 0 && (
                          <div className="flywheel-intel-item">
                            <span className="flywheel-intel-value">{creative.flywheel_metadata.opportunities_used}</span>
                            <span className="flywheel-intel-label">{language === 'es' ? 'Oportunidades usadas' : 'Opportunities used'}</span>
                          </div>
                        )}
                        {creative.flywheel_metadata.winning_features_used > 0 && (
                          <div className="flywheel-intel-item">
                            <span className="flywheel-intel-value">{creative.flywheel_metadata.winning_features_used}</span>
                            <span className="flywheel-intel-label">{language === 'es' ? 'Features ganadoras' : 'Winning features'}</span>
                          </div>
                        )}
                        {creative.flywheel_metadata.saturated_ads_avoided > 0 && (
                          <div className="flywheel-intel-item">
                            <span className="flywheel-intel-value">{creative.flywheel_metadata.saturated_ads_avoided}</span>
                            <span className="flywheel-intel-label">{language === 'es' ? 'Ads saturados evitados' : 'Saturated ads avoided'}</span>
                          </div>
                        )}
                      </div>
                      {creative.flywheel_metadata.priority_breakdown && (
                        <div className="flywheel-intel-priorities">
                          <span className="flywheel-intel-label">{language === 'es' ? 'Prioridades:' : 'Priorities:'}</span>
                          {Object.entries(creative.flywheel_metadata.priority_breakdown as Record<string, number>).map(([key, val]) => (
                            val > 0 && <span key={key} className={`priority-chip priority-${key}`}>{key}: {val}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}

              <div className="creative-footer">
                <span className="creative-date">
                  Generated {new Date(creative.generated_at).toLocaleDateString()}
                </span>
                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button
                    className="btn-secondary"
                    onClick={() => navigate(`/content-studio?creative_id=${creative.id}`)}
                    title="Send to Content Studio"
                  >
                    <Layers size={14} />
                    Content Studio
                  </button>
                  <button
                    className="btn-secondary"
                    onClick={() => handleUseInCampaign(creative)}
                  >
                    {t('creatives.use_in_campaign')}
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {!loading && creatives.length === 0 && (
        <div className="empty-state">
          <Palette size={48} />
          <h3>{t('common.no_data')}</h3>
          <p>{language === 'es' ? 'Genera tu primer script publicitario con IA o elige una oportunidad' : 'Generate your first AI-powered ad script or pick an opportunity'}</p>
          <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'center' }}>
            <button className="btn-primary" onClick={() => setShowGenerateModal(true)}>
              <Sparkles size={18} />
              {t('creatives.generate_new')}
            </button>
            <button className="btn-secondary" onClick={() => navigate('/opportunities')}>
              {language === 'es' ? 'Ver Oportunidades' : 'Browse Opportunities'}
            </button>
          </div>
        </div>
      )}

      <GenerateCreativeModal
        isOpen={showGenerateModal}
        onClose={() => setShowGenerateModal(false)}
        onGenerate={handleGenerate}
      />
    </div>
  );
}
