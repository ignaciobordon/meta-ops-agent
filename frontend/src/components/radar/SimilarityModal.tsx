import { X, Loader } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { CIItem } from '../../services/api';
import RadarItemCard from './RadarItemCard';

interface SimilarityModalProps {
  isOpen: boolean;
  onClose: () => void;
  sourceItem: CIItem | null;
  similarItems: CIItem[];
  loading: boolean;
  error: string | null;
}

export default function SimilarityModal({
  isOpen, onClose, sourceItem, similarItems, loading, error,
}: SimilarityModalProps) {
  const { t } = useLanguage();

  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content radar-similar-modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('radar.similar_ads')}</h2>
          <button className="modal-close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        {sourceItem && (
          <div className="radar-similar-source">
            <h4>Source</h4>
            <RadarItemCard item={sourceItem} compact />
          </div>
        )}

        <div className="radar-similar-list">
          {loading ? (
            <div className="loading-state"><Loader size={20} className="spin-icon" /> {t('common.loading')}</div>
          ) : error ? (
            <div className="error-state"><p>{error}</p></div>
          ) : similarItems.length === 0 ? (
            <div className="empty-state">
              <p>{t('radar.no_results')}</p>
            </div>
          ) : (
            similarItems.map((item) => (
              <RadarItemCard key={item.id} item={item} compact />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
