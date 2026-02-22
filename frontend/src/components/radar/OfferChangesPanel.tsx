import { useState, useEffect } from 'react';
import { DollarSign, Loader } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { ciApi, CIOpportunity } from '../../services/api';

interface OfferChangesPanelProps {
  selectedCompetitor: string;
}

export default function OfferChangesPanel({ selectedCompetitor }: OfferChangesPanelProps) {
  const { t } = useLanguage();
  const [opportunities, setOpportunities] = useState<CIOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchOfferChanges();
  }, [selectedCompetitor]);

  const fetchOfferChanges = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ciApi.opportunities({ type: 'competitor_offer_change', limit: 50 });
      let data = res.data;
      if (selectedCompetitor) {
        data = data.filter(o =>
          o.description.toLowerCase().includes(selectedCompetitor.toLowerCase())
        );
      }
      setOpportunities(data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setOpportunities([]);
      } else {
        setError(err.response?.data?.detail || 'Failed to load offer changes');
      }
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return <div className="loading-state"><Loader size={20} className="spin-icon" /> {t('common.loading')}</div>;
  }

  if (error) {
    return <div className="error-state"><p>{error}</p></div>;
  }

  if (opportunities.length === 0) {
    return (
      <div className="empty-state">
        <DollarSign size={48} />
        <h3>{t('radar.no_offers')}</h3>
        <p>{t('radar.no_competitors_hint')}</p>
      </div>
    );
  }

  return (
    <div className="radar-offers">
      {opportunities.map((opp) => (
        <div key={opp.id} className="radar-offer-card">
          <div className="radar-offer-header">
            <h4 className="radar-offer-title">{opp.title}</h4>
            <div className="radar-offer-scores">
              <span className="radar-score" title={t('radar.confidence')}>
                {(opp.confidence_score * 100).toFixed(0)}%
              </span>
              <span className="radar-score radar-score--impact" title={t('radar.impact')}>
                {(opp.impact_score * 100).toFixed(0)}%
              </span>
            </div>
          </div>
          <p className="radar-offer-desc">{opp.description}</p>
          {opp.suggested_actions.length > 0 && (
            <div className="radar-offer-actions">
              <strong>{t('radar.actions')}:</strong>
              <ul>
                {opp.suggested_actions.map((a, i) => (
                  <li key={i}>{a}</li>
                ))}
              </ul>
            </div>
          )}
          {opp.rationale && (
            <div className="radar-offer-rationale">
              <strong>{t('radar.rationale')}:</strong> {opp.rationale}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
