import { useState, useEffect } from 'react';
import { TrendingUp, Loader } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { ciApi, CIOpportunity } from '../../services/api';

interface AngleTrendsChartProps {
  selectedCompetitor: string;
}

export default function AngleTrendsChart({ selectedCompetitor }: AngleTrendsChartProps) {
  const { t } = useLanguage();
  const [trends, setTrends] = useState<CIOpportunity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchTrends();
  }, [selectedCompetitor]);

  const fetchTrends = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ciApi.opportunities({
        type: 'angle_trend_rise',
        limit: 50,
      });
      let data = res.data;
      if (selectedCompetitor) {
        data = data.filter(o =>
          o.description.toLowerCase().includes(selectedCompetitor.toLowerCase())
        );
      }
      setTrends(data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setTrends([]);
      } else {
        setError(err.response?.data?.detail || 'Failed to load trends');
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

  if (trends.length === 0) {
    return (
      <div className="empty-state">
        <TrendingUp size={48} />
        <h3>{t('radar.no_trends')}</h3>
        <p>{t('radar.no_competitors_hint')}</p>
      </div>
    );
  }

  return (
    <div className="radar-trends">
      {trends.map((trend) => {
        const priorityPct = Math.round(trend.priority_score * 100);
        const impactPct = Math.round(trend.impact_score * 100);
        const confidencePct = Math.round(trend.confidence_score * 100);

        return (
          <div key={trend.id} className="radar-trend-card">
            <div className="radar-trend-header">
              <h4 className="radar-trend-title">{trend.title}</h4>
              <span className={`radar-priority-badge ${priorityPct >= 70 ? 'radar-priority--high' : priorityPct >= 40 ? 'radar-priority--medium' : 'radar-priority--low'}`}>
                {priorityPct}%
              </span>
            </div>
            <p className="radar-trend-desc">{trend.description}</p>

            <div className="radar-trend-bars">
              <div className="radar-bar-group">
                <span className="radar-bar-label">{t('radar.confidence')}</span>
                <div className="radar-bar-track">
                  <div
                    className="radar-bar-fill radar-bar--confidence"
                    style={{ width: `${confidencePct}%` }}
                  />
                </div>
                <span className="radar-bar-value">{confidencePct}%</span>
              </div>
              <div className="radar-bar-group">
                <span className="radar-bar-label">{t('radar.impact')}</span>
                <div className="radar-bar-track">
                  <div
                    className="radar-bar-fill radar-bar--impact"
                    style={{ width: `${impactPct}%` }}
                  />
                </div>
                <span className="radar-bar-value">{impactPct}%</span>
              </div>
            </div>

            {trend.suggested_actions.length > 0 && (
              <div className="radar-trend-actions">
                <strong>{t('radar.actions')}:</strong>
                <ul>
                  {trend.suggested_actions.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
