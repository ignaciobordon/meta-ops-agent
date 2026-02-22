import { useState, useEffect } from 'react';
import { X, Wand2 } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { brandMapApi, BrandMapProfile } from '../services/api';
import './GenerateCreativeModal.css';

interface GenerateCreativeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGenerate: (data: CreativeFormData) => Promise<void>;
}

export interface CreativeFormData {
  audience: string;
  objective: string;
  tone: string;
  format: string;
  description: string;
  framework: string;
  hook_style: string;
  brand_profile_id: string;
}

const AUDIENCE_PRESETS = [
  { value: '', label: 'Custom...', labelEs: 'Personalizado...' },
  { value: 'young_professionals_25_34', label: 'Young professionals 25-34', labelEs: 'Profesionales jóvenes 25-34' },
  { value: 'parents_30_45', label: 'Parents 30-45', labelEs: 'Padres 30-45' },
  { value: 'tech_enthusiasts', label: 'Tech enthusiasts', labelEs: 'Entusiastas de tecnología' },
  { value: 'small_business_owners', label: 'Small business owners', labelEs: 'Dueños de pequeños negocios' },
  { value: 'fitness_health', label: 'Fitness & health conscious', labelEs: 'Fitness y salud' },
];

const OBJECTIVE_PRESETS = [
  { value: '', label: 'Custom...', labelEs: 'Personalizado...' },
  { value: 'brand_awareness', label: 'Brand awareness', labelEs: 'Conocimiento de marca' },
  { value: 'lead_generation', label: 'Lead generation', labelEs: 'Generación de leads' },
  { value: 'conversions', label: 'Conversions', labelEs: 'Conversiones' },
  { value: 'app_installs', label: 'App installs', labelEs: 'Instalaciones de app' },
  { value: 'engagement', label: 'Engagement', labelEs: 'Engagement' },
];

const FRAMEWORK_PRESETS = [
  { value: 'aida', label: 'AIDA (Attention, Interest, Desire, Action)', labelEs: 'AIDA (Atención, Interés, Deseo, Acción)' },
  { value: 'pas', label: 'PAS (Problem, Agitate, Solve)', labelEs: 'PAS (Problema, Agitar, Resolver)' },
  { value: 'bab', label: 'BAB (Before, After, Bridge)', labelEs: 'BAB (Antes, Después, Puente)' },
  { value: '4ps', label: '4Ps (Promise, Picture, Proof, Push)', labelEs: '4Ps (Promesa, Imagen, Prueba, Empuje)' },
];

const HOOK_STYLE_PRESETS = [
  { value: 'question', label: 'Question', labelEs: 'Pregunta' },
  { value: 'statistic', label: 'Statistic', labelEs: 'Estadística' },
  { value: 'story', label: 'Story', labelEs: 'Historia' },
  { value: 'bold_claim', label: 'Bold claim', labelEs: 'Afirmación audaz' },
];

export default function GenerateCreativeModal({ isOpen, onClose, onGenerate }: GenerateCreativeModalProps) {
  const { language } = useLanguage();
  const [formData, setFormData] = useState<CreativeFormData>({
    audience: '',
    objective: '',
    tone: 'professional',
    format: 'image',
    description: '',
    framework: 'aida',
    hook_style: 'question',
    brand_profile_id: '',
  });
  const [customAudience, setCustomAudience] = useState('');
  const [customObjective, setCustomObjective] = useState('');
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);
  const [brandProfiles, setBrandProfiles] = useState<BrandMapProfile[]>([]);

  useEffect(() => {
    if (isOpen) {
      brandMapApi.list().then(res => setBrandProfiles(res.data)).catch(() => {});
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setGenerating(true);
    setGenError(null);
    try {
      await onGenerate(formData);
      setFormData({
        audience: '',
        objective: '',
        tone: 'professional',
        format: 'image',
        description: '',
        framework: 'aida',
        hook_style: 'question',
        brand_profile_id: '',
      });
      setCustomAudience('');
      setCustomObjective('');
      onClose();
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Generation failed. Check ANTHROPIC_API_KEY.';
      setGenError(detail);
    } finally {
      setGenerating(false);
    }
  };

  const labels = {
    en: {
      title: 'Generate New Creative',
      audience: 'Target Audience',
      audiencePlaceholder: 'e.g., Millennial dog owners in NYC',
      objective: 'Campaign Objective',
      objectivePlaceholder: 'e.g., Increase brand awareness',
      tone: 'Creative Tone',
      format: 'Format',
      description: 'Additional Details',
      descriptionPlaceholder: 'Describe what you want the creative to convey...',
      framework: 'Copywriting Framework',
      hookStyle: 'Hook Style',
      cancel: 'Cancel',
      generate: 'Generate Creative',
      tones: {
        professional: 'Professional',
        casual: 'Casual',
        playful: 'Playful',
        urgent: 'Urgent',
        luxurious: 'Luxurious',
      },
      formats: {
        image: 'Image (1200x628)',
        square: 'Square (1080x1080)',
        story: 'Story (1080x1920)',
        video: 'Video Concept',
      },
    },
    es: {
      title: 'Generar Nuevo Creativo',
      audience: 'Audiencia Objetivo',
      audiencePlaceholder: 'ej., Dueños de perros mileniales en NYC',
      objective: 'Objetivo de Campaña',
      objectivePlaceholder: 'ej., Aumentar conocimiento de marca',
      tone: 'Tono del Creativo',
      format: 'Formato',
      description: 'Detalles Adicionales',
      descriptionPlaceholder: 'Describe qué quieres que transmita el creativo...',
      framework: 'Framework de Copywriting',
      hookStyle: 'Estilo de Hook',
      cancel: 'Cancelar',
      generate: 'Generar Creativo',
      tones: {
        professional: 'Profesional',
        casual: 'Casual',
        playful: 'Juguetón',
        urgent: 'Urgente',
        luxurious: 'Lujoso',
      },
      formats: {
        image: 'Imagen (1200x628)',
        square: 'Cuadrado (1080x1080)',
        story: 'Historia (1080x1920)',
        video: 'Concepto de Video',
      },
    },
  };

  const t = labels[language];

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose}>
          <X size={20} />
        </button>

        <div className="modal-header">
          <Wand2 size={24} className="modal-icon" />
          <h2>{t.title}</h2>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {brandProfiles.length > 0 && (
            <div className="form-group">
              <label>{language === 'es' ? 'Perfil de Marca' : 'Brand Profile'}</label>
              <select
                value={formData.brand_profile_id}
                onChange={(e) => setFormData({ ...formData, brand_profile_id: e.target.value })}
              >
                <option value="">{language === 'es' ? 'Demo Brand (por defecto)' : 'Demo Brand (default)'}</option>
                {brandProfiles.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
          )}

          <div className="form-group">
            <label>{t.audience}</label>
            <select
              value={formData.audience}
              onChange={(e) => {
                setFormData({ ...formData, audience: e.target.value });
                if (e.target.value !== '') setCustomAudience('');
              }}
            >
              {AUDIENCE_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {language === 'es' ? p.labelEs : p.label}
                </option>
              ))}
            </select>
            {formData.audience === '' && (
              <input
                type="text"
                value={customAudience}
                onChange={(e) => setCustomAudience(e.target.value)}
                placeholder={t.audiencePlaceholder}
                style={{ marginTop: '0.5rem' }}
                required
              />
            )}
          </div>

          <div className="form-group">
            <label>{t.objective}</label>
            <select
              value={formData.objective}
              onChange={(e) => {
                setFormData({ ...formData, objective: e.target.value });
                if (e.target.value !== '') setCustomObjective('');
              }}
            >
              {OBJECTIVE_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {language === 'es' ? p.labelEs : p.label}
                </option>
              ))}
            </select>
            {formData.objective === '' && (
              <input
                type="text"
                value={customObjective}
                onChange={(e) => setCustomObjective(e.target.value)}
                placeholder={t.objectivePlaceholder}
                style={{ marginTop: '0.5rem' }}
                required
              />
            )}
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>{t.tone}</label>
              <select
                value={formData.tone}
                onChange={(e) => setFormData({ ...formData, tone: e.target.value })}
              >
                <option value="professional">{t.tones.professional}</option>
                <option value="casual">{t.tones.casual}</option>
                <option value="playful">{t.tones.playful}</option>
                <option value="urgent">{t.tones.urgent}</option>
                <option value="luxurious">{t.tones.luxurious}</option>
              </select>
            </div>

            <div className="form-group">
              <label>{t.format}</label>
              <select
                value={formData.format}
                onChange={(e) => setFormData({ ...formData, format: e.target.value })}
              >
                <option value="image">{t.formats.image}</option>
                <option value="square">{t.formats.square}</option>
                <option value="story">{t.formats.story}</option>
                <option value="video">{t.formats.video}</option>
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>{t.framework}</label>
              <select
                value={formData.framework}
                onChange={(e) => setFormData({ ...formData, framework: e.target.value })}
              >
                {FRAMEWORK_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {language === 'es' ? p.labelEs : p.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="form-group">
              <label>{t.hookStyle}</label>
              <select
                value={formData.hook_style}
                onChange={(e) => setFormData({ ...formData, hook_style: e.target.value })}
              >
                {HOOK_STYLE_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {language === 'es' ? p.labelEs : p.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="form-group">
            <label>{t.description}</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              placeholder={t.descriptionPlaceholder}
              rows={4}
              required
            />
          </div>

          {genError && (
            <div style={{ background: '#fde8e3', color: '#9b3722', padding: '0.75rem 1rem', borderRadius: '8px', fontSize: '0.9rem' }}>
              {genError}
            </div>
          )}

          <div className="modal-actions">
            <button type="button" onClick={onClose} className="btn btn-outline" disabled={generating}>
              {t.cancel}
            </button>
            <button type="submit" className="btn btn-primary" disabled={generating}>
              <Wand2 size={18} />
              {generating ? (language === 'es' ? 'Generando...' : 'Generating...') : t.generate}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
