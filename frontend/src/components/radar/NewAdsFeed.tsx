import { useState, useEffect } from 'react';
import { Megaphone, Loader } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { ciApi, CIItem } from '../../services/api';
import RadarItemCard from './RadarItemCard';

interface NewAdsFeedProps {
  selectedCompetitor: string;
  onViewSimilar: (itemId: string) => void;
}

export default function NewAdsFeed({ selectedCompetitor, onViewSimilar }: NewAdsFeedProps) {
  const { t } = useLanguage();
  const [items, setItems] = useState<CIItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(20);
  const [filterType, setFilterType] = useState<string>('');

  useEffect(() => {
    fetchItems();
  }, [selectedCompetitor, limit, filterType]);

  const fetchItems = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ciApi.search({
        item_type: filterType || undefined,
        competitor: selectedCompetitor || undefined,
        limit,
      });
      setItems(res.data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setItems([]);
      } else {
        setError(err.response?.data?.detail || 'Failed to load items');
      }
    } finally {
      setLoading(false);
    }
  };

  const typeFilters = [
    { value: '', label: t('radar.all_types') || 'Todos' },
    { value: 'ad', label: 'Ads' },
    { value: 'landing_page', label: 'Landing Pages' },
    { value: 'post', label: 'Posts' },
    { value: 'offer', label: 'Ofertas' },
  ];

  if (loading) {
    return <div className="loading-state"><Loader size={20} className="spin-icon" /> {t('common.loading')}</div>;
  }

  if (error) {
    return <div className="error-state"><p>{error}</p></div>;
  }

  if (items.length === 0) {
    return (
      <div className="empty-state">
        <Megaphone size={48} />
        <h3>{t('radar.no_ads')}</h3>
        <p>{t('radar.no_competitors_hint')}</p>
      </div>
    );
  }

  return (
    <div className="radar-feed">
      <div className="radar-feed-filters">
        {typeFilters.map((f) => (
          <button
            key={f.value}
            className={`radar-type-filter ${filterType === f.value ? 'radar-type-filter--active' : ''}`}
            onClick={() => setFilterType(f.value)}
          >
            {f.label}
          </button>
        ))}
      </div>
      <div className="radar-feed-list">
        {items.map((item) => (
          <RadarItemCard key={item.id} item={item} onViewSimilar={onViewSimilar} />
        ))}
      </div>
      {items.length >= limit && (
        <button className="radar-load-more" onClick={() => setLimit(prev => prev + 20)}>
          {t('radar.load_more')}
        </button>
      )}
    </div>
  );
}
