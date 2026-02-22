import { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { X, ChevronLeft, ChevronRight, CheckCircle } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import './TutorialOverlay.css';

interface TutorialStep {
  id: string;
  route: string;
  targetSelector?: string;
  title: { en: string; es: string };
  description: { en: string; es: string };
  position: 'top' | 'bottom' | 'left' | 'right' | 'center';
}

const tutorialSteps: TutorialStep[] = [
  {
    id: 'welcome',
    route: '/dashboard',
    title: {
      en: 'Welcome to Meta Ops Agent!',
      es: '¡Bienvenido a Meta Ops Agent!',
    },
    description: {
      en: 'This is your AI-powered Meta Ads optimization platform. Let me show you how it works in just a few simple steps.',
      es: 'Esta es tu plataforma de optimización de Meta Ads potenciada por IA. Déjame mostrarte cómo funciona en solo unos pocos pasos simples.',
    },
    position: 'center',
  },
  {
    id: 'dashboard',
    route: '/dashboard',
    title: {
      en: 'Dashboard Overview',
      es: 'Vista General del Panel',
    },
    description: {
      en: 'Here you see a summary of your campaign performance, pending decisions, and recent activity.',
      es: 'Aquí ves un resumen del rendimiento de tus campañas, decisiones pendientes y actividad reciente.',
    },
    position: 'center',
  },
  {
    id: 'control-panel',
    route: '/control-panel',
    title: {
      en: 'Control Panel - Create Decisions',
      es: 'Panel de Control - Crear Decisiones',
    },
    description: {
      en: 'Use this form to manually create budget changes, pause adsets, or swap creatives. Fill in the details and click "Create Draft".',
      es: 'Usa este formulario para crear cambios de presupuesto, pausar conjuntos de anuncios o cambiar creativos manualmente. Completa los detalles y haz clic en "Crear Borrador".',
    },
    position: 'center',
  },
  {
    id: 'operator-armed',
    route: '/control-panel',
    title: {
      en: 'Safety Control - Operator Armed',
      es: 'Control de Seguridad - Operador Armado',
    },
    description: {
      en: 'IMPORTANT: Toggle "Operator Armed" ON only when you want to make REAL changes. When OFF, all executions are safe dry-runs (test mode).',
      es: 'IMPORTANTE: Activa "Operador Armado" solo cuando quieras hacer cambios REALES. Cuando está DESACTIVADO, todas las ejecuciones son pruebas seguras (modo de prueba).',
    },
    position: 'top',
  },
  {
    id: 'decisions',
    route: '/decisions',
    title: {
      en: 'Decision Queue - Review & Approve',
      es: 'Cola de Decisiones - Revisar y Aprobar',
    },
    description: {
      en: 'All decisions (manual or AI-generated) appear here. Review them and use the buttons: Validate → Request Approval → Approve → Execute.',
      es: 'Todas las decisiones (manuales o generadas por IA) aparecen aquí. Revísalas y usa los botones: Validar → Solicitar Aprobación → Aprobar → Ejecutar.',
    },
    position: 'center',
  },
  {
    id: 'dry-run',
    route: '/decisions',
    title: {
      en: 'Always Test First!',
      es: '¡Siempre Prueba Primero!',
    },
    description: {
      en: 'Use "Dry Run First" to test changes without touching your Meta account. Only use "Execute Live" when you\'re ready for real changes.',
      es: 'Usa "Prueba Seca Primero" para probar cambios sin tocar tu cuenta de Meta. Solo usa "Ejecutar en Vivo" cuando estés listo para cambios reales.',
    },
    position: 'center',
  },
  {
    id: 'creatives',
    route: '/creatives',
    title: {
      en: 'Creative Library',
      es: 'Biblioteca de Creativos',
    },
    description: {
      en: 'View your ad creatives with AI-analyzed performance scores. Generate new creatives or use existing ones in campaigns.',
      es: 'Ve tus creativos publicitarios con puntuaciones de rendimiento analizadas por IA. Genera nuevos creativos o usa los existentes en campañas.',
    },
    position: 'center',
  },
  {
    id: 'opportunities',
    route: '/opportunities',
    title: {
      en: 'AI-Detected Opportunities',
      es: 'Oportunidades Detectadas por IA',
    },
    description: {
      en: 'The AI finds scaling opportunities automatically. Click "Create Campaign" to act on high-priority opportunities.',
      es: 'La IA encuentra oportunidades de escalamiento automáticamente. Haz clic en "Crear Campaña" para actuar sobre oportunidades de alta prioridad.',
    },
    position: 'center',
  },
  {
    id: 'audit',
    route: '/audit',
    title: {
      en: 'Audit Log - Full History',
      es: 'Registro de Auditoría - Historial Completo',
    },
    description: {
      en: 'Every action is logged here. Review what was executed, when, and whether it was a dry-run or live execution.',
      es: 'Cada acción se registra aquí. Revisa qué se ejecutó, cuándo y si fue una prueba seca o ejecución en vivo.',
    },
    position: 'center',
  },
  {
    id: 'complete',
    route: '/dashboard',
    title: {
      en: 'You\'re All Set!',
      es: '¡Todo Listo!',
    },
    description: {
      en: 'You now know the basics! Start by creating a decision in the Control Panel, or explore the AI features. Need help? Check the Help page anytime.',
      es: '¡Ya conoces lo básico! Comienza creando una decisión en el Panel de Control, o explora las funciones de IA. ¿Necesitas ayuda? Consulta la página de Ayuda en cualquier momento.',
    },
    position: 'center',
  },
];

export default function TutorialOverlay() {
  const navigate = useNavigate();
  const location = useLocation();
  const { language, t } = useLanguage();
  const [isActive, setIsActive] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);

  useEffect(() => {
    const hasSeenTutorial = localStorage.getItem('hasSeenTutorial');
    if (!hasSeenTutorial) {
      setIsActive(true);
    }
  }, []);

  useEffect(() => {
    if (isActive && tutorialSteps[currentStep]) {
      const targetRoute = tutorialSteps[currentStep].route;
      if (location.pathname !== targetRoute) {
        navigate(targetRoute);
      }
    }
  }, [currentStep, isActive, location.pathname, navigate]);

  const handleNext = () => {
    if (currentStep < tutorialSteps.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleFinish();
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleSkip = () => {
    localStorage.setItem('hasSeenTutorial', 'true');
    setIsActive(false);
  };

  const handleFinish = () => {
    localStorage.setItem('hasSeenTutorial', 'true');
    setIsActive(false);
  };

  const handleRestart = () => {
    setCurrentStep(0);
    setIsActive(true);
    navigate(tutorialSteps[0].route);
  };

  if (!isActive) {
    return (
      <button className="tutorial-restart-btn" onClick={handleRestart} title={t('tutorial.start')}>
        ?
      </button>
    );
  }

  const step = tutorialSteps[currentStep];
  const isLastStep = currentStep === tutorialSteps.length - 1;

  return (
    <>
      <div className="tutorial-overlay" />
      <div className={`tutorial-card tutorial-position-${step.position}`}>
        <button className="tutorial-close" onClick={handleSkip} aria-label="Close tutorial">
          <X size={20} />
        </button>

        <div className="tutorial-header">
          <div className="tutorial-progress">
            {t('tutorial.step')} {currentStep + 1} {t('tutorial.of')} {tutorialSteps.length}
          </div>
          <div className="tutorial-progress-bar">
            <div
              className="tutorial-progress-fill"
              style={{ width: `${((currentStep + 1) / tutorialSteps.length) * 100}%` }}
            />
          </div>
        </div>

        <div className="tutorial-content">
          <h2>{step.title[language]}</h2>
          <p>{step.description[language]}</p>
        </div>

        <div className="tutorial-actions">
          {currentStep > 0 && (
            <button className="tutorial-btn tutorial-btn-secondary" onClick={handlePrev}>
              <ChevronLeft size={18} />
              {t('tutorial.prev')}
            </button>
          )}

          <button className="tutorial-btn tutorial-btn-skip" onClick={handleSkip}>
            {t('tutorial.skip')}
          </button>

          <button className="tutorial-btn tutorial-btn-primary" onClick={handleNext}>
            {isLastStep ? (
              <>
                <CheckCircle size={18} />
                {t('tutorial.finish')}
              </>
            ) : (
              <>
                {t('tutorial.next')}
                <ChevronRight size={18} />
              </>
            )}
          </button>
        </div>
      </div>
    </>
  );
}

// Export function to restart tutorial
export function restartTutorial() {
  localStorage.removeItem('hasSeenTutorial');
  window.location.reload();
}
