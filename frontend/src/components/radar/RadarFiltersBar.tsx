import { Search, Filter } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { CICompetitor } from '../../services/api';

interface RadarFiltersBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  selectedType: string;
  onTypeChange: (t: string) => void;
  selectedPlatform: string;
  onPlatformChange: (p: string) => void;
  selectedFormat: string;
  onFormatChange: (f: string) => void;
  selectedCompetitor: string;
  onCompetitorChange: (c: string) => void;
  competitors: CICompetitor[];
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (d: string) => void;
  onDateToChange: (d: string) => void;
}

const ITEM_TYPES = ['ad', 'offer', 'keyword'];
const PLATFORMS = ['meta', 'google', 'tiktok'];
const FORMATS = ['image', 'video', 'carousel', 'text'];

export default function RadarFiltersBar({
  query, onQueryChange,
  selectedType, onTypeChange,
  selectedPlatform, onPlatformChange,
  selectedFormat, onFormatChange,
  selectedCompetitor, onCompetitorChange,
  competitors,
  dateFrom, dateTo,
  onDateFromChange, onDateToChange,
}: RadarFiltersBarProps) {
  const { t } = useLanguage();

  return (
    <div className="radar-filters-bar">
      <div className="radar-search-row">
        <div className="radar-search-input-wrapper">
          <Search size={18} className="radar-search-icon" />
          <input
            type="text"
            className="radar-search-input"
            placeholder={t('radar.search_placeholder')}
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
          />
        </div>
      </div>

      <div className="radar-filter-row">
        <Filter size={16} className="radar-filter-icon" />

        <select
          className="radar-filter-select"
          value={selectedCompetitor}
          onChange={(e) => onCompetitorChange(e.target.value)}
        >
          <option value="">{t('radar.all_competitors')}</option>
          {competitors.map((c) => (
            <option key={c.id} value={c.name}>{c.name}</option>
          ))}
        </select>

        <select
          className="radar-filter-select"
          value={selectedType}
          onChange={(e) => onTypeChange(e.target.value)}
        >
          <option value="">{t('radar.filter_all')}</option>
          {ITEM_TYPES.map((tp) => (
            <option key={tp} value={tp}>{tp}</option>
          ))}
        </select>

        <select
          className="radar-filter-select"
          value={selectedPlatform}
          onChange={(e) => onPlatformChange(e.target.value)}
        >
          <option value="">{t('radar.filter_all')}</option>
          {PLATFORMS.map((p) => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>

        <select
          className="radar-filter-select"
          value={selectedFormat}
          onChange={(e) => onFormatChange(e.target.value)}
        >
          <option value="">{t('radar.filter_all')}</option>
          {FORMATS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>

        <input
          type="date"
          className="radar-filter-date"
          value={dateFrom}
          onChange={(e) => onDateFromChange(e.target.value)}
          title={t('radar.filter_date_from')}
        />
        <input
          type="date"
          className="radar-filter-date"
          value={dateTo}
          onChange={(e) => onDateToChange(e.target.value)}
          title={t('radar.filter_date_to')}
        />
      </div>
    </div>
  );
}
