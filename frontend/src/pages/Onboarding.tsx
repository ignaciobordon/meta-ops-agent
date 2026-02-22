/**
 * Sprint 8 — Onboarding Wizard page.
 * 6-step flow: Welcome → Connect Meta → Select Account → Choose Template → Configure → Syncing/Complete.
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useLanguage } from '../contexts/LanguageContext';
import { onboardingApi, templatesApi, metaApi, eventsApi } from '../services/api';
import './Onboarding.css';

interface Template {
  id: string;
  slug: string;
  name: string;
  description: string;
  vertical: string;
  default_config: Record<string, any>;
}

interface AdAccount {
  id: string;
  meta_ad_account_id: string;
  name: string;
  currency: string;
}

const STEP_KEYS = ['pending', 'connect_meta', 'select_account', 'choose_template', 'configure', 'syncing', 'completed'] as const;

const STEP_LABELS_EN = ['Welcome', 'Connect Meta', 'Select Account', 'Choose Template', 'Configure', 'Syncing'];
const STEP_LABELS_ES = ['Bienvenida', 'Conectar Meta', 'Seleccionar Cuenta', 'Elegir Plantilla', 'Configurar', 'Sincronizando'];

export default function Onboarding() {
  const { t, language } = useLanguage();
  const navigate = useNavigate();

  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [accounts, setAccounts] = useState<AdAccount[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);
  const [selectedAccount, setSelectedAccount] = useState<string | null>(null);
  const [error, setError] = useState('');

  const stepLabels = language === 'es' ? STEP_LABELS_ES : STEP_LABELS_EN;

  // Load current onboarding state on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await onboardingApi.getStatus();
        const progress = res.data;
        if (progress.completed) {
          navigate('/dashboard', { replace: true });
          return;
        }
        const idx = STEP_KEYS.indexOf(progress.current_step as any);
        setCurrentStep(idx >= 0 ? idx : 0);
        if (progress.selected_template_id) {
          setSelectedTemplate(progress.selected_template_id);
        }
      } catch {
        // New user — start at step 0
      } finally {
        setLoading(false);
      }
    })();
  }, [navigate]);

  const advanceToStep = useCallback(async (stepKey: string, data?: Record<string, any>) => {
    try {
      setError('');
      // Advance through intermediate steps sequentially to satisfy backend prerequisites
      const targetIdx = STEP_KEYS.indexOf(stepKey as any);
      for (let i = currentStep + 1; i <= targetIdx; i++) {
        await onboardingApi.advanceStep(STEP_KEYS[i], i === targetIdx ? data : undefined);
      }
      setCurrentStep(targetIdx >= 0 ? targetIdx : currentStep + 1);
      eventsApi.track(stepKey, { step: stepKey }).catch(() => {});
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to advance step');
    }
  }, [currentStep]);

  const handleConnectMeta = async () => {
    try {
      const res = await metaApi.oauthStart();
      window.location.href = res.data.authorization_url;
    } catch {
      // If OAuth is not configured, simulate success for dev
      await advanceToStep('select_account');
    }
  };

  const handleSelectAccount = async (accountId: string) => {
    try {
      await metaApi.selectAdAccount(accountId);
      setSelectedAccount(accountId);
      await advanceToStep('choose_template');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to select account');
    }
  };

  const handleChooseTemplate = async (templateId: string) => {
    setSelectedTemplate(templateId);
    try {
      await templatesApi.install(templateId);
      await advanceToStep('configure', { template_id: templateId });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to install template');
    }
  };

  const handleConfigure = async () => {
    await advanceToStep('syncing');
  };

  const handleComplete = async () => {
    try {
      await onboardingApi.complete();
      eventsApi.track('onboarding_completed', {}).catch(() => {});
      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to complete onboarding');
    }
  };

  // Load templates when reaching step 3
  useEffect(() => {
    if (currentStep === 3) {
      templatesApi.list().then(res => setTemplates(res.data)).catch(() => {});
    }
  }, [currentStep]);

  // Load accounts when reaching step 2
  useEffect(() => {
    if (currentStep === 2) {
      metaApi.listAdAccounts().then(res => setAccounts(res.data)).catch(() => {});
    }
  }, [currentStep]);

  if (loading) {
    return <div className="onboarding-loading">{t('common.loading')}</div>;
  }

  return (
    <div className="onboarding">
      <div className="onboarding-container">
        {/* Stepper */}
        <div className="onboarding-stepper">
          {stepLabels.map((label, i) => (
            <div
              key={i}
              className={`stepper-step ${i < currentStep ? 'completed' : ''} ${i === currentStep ? 'active' : ''}`}
            >
              <div className="stepper-circle">{i < currentStep ? '\u2713' : i + 1}</div>
              <span className="stepper-label">{label}</span>
            </div>
          ))}
        </div>

        {/* Error */}
        {error && <div className="onboarding-error">{error}</div>}

        {/* Step Content */}
        <div className="onboarding-content">
          {/* Step 0: Welcome */}
          {currentStep === 0 && (
            <div className="step-card">
              <h2>{t('onboarding.welcome_title')}</h2>
              <p>{t('onboarding.welcome_desc')}</p>
              <button className="onboarding-btn primary" onClick={() => advanceToStep('connect_meta')}>
                {t('onboarding.get_started')}
              </button>
            </div>
          )}

          {/* Step 1: Connect Meta */}
          {currentStep === 1 && (
            <div className="step-card">
              <h2>{t('onboarding.connect_title')}</h2>
              <p>{t('onboarding.connect_desc')}</p>
              <button className="onboarding-btn primary" onClick={handleConnectMeta}>
                {t('onboarding.connect_meta_btn')}
              </button>
              <button className="onboarding-btn secondary" onClick={() => advanceToStep('select_account')}>
                {t('onboarding.skip_for_now')}
              </button>
            </div>
          )}

          {/* Step 2: Select Account */}
          {currentStep === 2 && (
            <div className="step-card">
              <h2>{t('onboarding.select_title')}</h2>
              <p>{t('onboarding.select_desc')}</p>
              {accounts.length > 0 ? (
                <div className="account-grid">
                  {accounts.map(acc => (
                    <div
                      key={acc.id}
                      className={`account-card ${selectedAccount === acc.id ? 'selected' : ''}`}
                      onClick={() => handleSelectAccount(acc.id)}
                    >
                      <strong>{acc.name}</strong>
                      <span>{acc.meta_ad_account_id}</span>
                      <span>{acc.currency}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="onboarding-empty">
                  <p>{t('onboarding.no_accounts')}</p>
                  <button className="onboarding-btn secondary" onClick={() => advanceToStep('choose_template')}>
                    {t('onboarding.skip_for_now')}
                  </button>
                </div>
              )}
            </div>
          )}

          {/* Step 3: Choose Template */}
          {currentStep === 3 && (
            <div className="step-card">
              <h2>{t('onboarding.template_title')}</h2>
              <p>{t('onboarding.template_desc')}</p>
              {templates.length > 0 ? (
                <div className="template-grid">
                  {templates.map(tmpl => (
                    <div
                      key={tmpl.id}
                      className={`template-card ${selectedTemplate === tmpl.id ? 'selected' : ''}`}
                      onClick={() => handleChooseTemplate(tmpl.id)}
                    >
                      <h3>{tmpl.name}</h3>
                      <span className="template-vertical">{tmpl.vertical}</span>
                      <p>{tmpl.description}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="onboarding-empty">
                  <p>{t('onboarding.no_templates')}</p>
                </div>
              )}
              <button className="onboarding-btn secondary" onClick={() => advanceToStep('configure')}>
                {t('onboarding.skip_for_now')}
              </button>
            </div>
          )}

          {/* Step 4: Configure */}
          {currentStep === 4 && (
            <div className="step-card">
              <h2>{t('onboarding.configure_title')}</h2>
              <p>{t('onboarding.configure_desc')}</p>
              <div className="config-summary">
                <p>{t('onboarding.config_ready')}</p>
              </div>
              <button className="onboarding-btn primary" onClick={handleConfigure}>
                {t('onboarding.continue')}
              </button>
            </div>
          )}

          {/* Step 5: Syncing / Complete */}
          {currentStep >= 5 && (
            <div className="step-card">
              <h2>{t('onboarding.complete_title')}</h2>
              <p>{t('onboarding.complete_desc')}</p>
              <div className="sync-progress">
                <div className="sync-spinner" />
                <span>{t('onboarding.syncing_data')}</span>
              </div>
              <button className="onboarding-btn primary" onClick={handleComplete}>
                {t('onboarding.go_to_dashboard')}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
