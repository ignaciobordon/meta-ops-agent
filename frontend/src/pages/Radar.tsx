import { useState, useCallback } from 'react';
import { Radar as RadarIcon, RefreshCw, Loader, Users, Search, Plus, X, Trash2, Globe, Download, Sparkles } from 'lucide-react';
import { useLanguage } from '../contexts/LanguageContext';
import { ciApi, CIItem } from '../services/api';
import { useRadarCompetitors, useRadarSearch, useRadarSimilar } from '../hooks/useRadarSearch';
import RadarFiltersBar from '../components/radar/RadarFiltersBar';
import RadarItemCard from '../components/radar/RadarItemCard';
import NewAdsFeed from '../components/radar/NewAdsFeed';
import OfferChangesPanel from '../components/radar/OfferChangesPanel';
import AngleTrendsChart from '../components/radar/AngleTrendsChart';
import SimilarityModal from '../components/radar/SimilarityModal';
import './Radar.css';

type TabKey = 'ads' | 'offers' | 'trends' | 'search';

export default function Radar() {
  const { t } = useLanguage();

  // Competitors panel
  const { competitors, loading: competitorsLoading, refetch: refetchCompetitors } = useRadarCompetitors();
  const [selectedCompetitor, setSelectedCompetitor] = useState('');

  // Tabs
  const [activeTab, setActiveTab] = useState<TabKey>('ads');

  // Search state
  const {
    results: searchResults, loading: searchLoading, error: searchError,
    hasMore, debouncedSearch, loadMore, reset: resetSearch,
  } = useRadarSearch();
  const [query, setQuery] = useState('');
  const [filterType, setFilterType] = useState('');
  const [filterPlatform, setFilterPlatform] = useState('');
  const [filterFormat, setFilterFormat] = useState('');
  const [filterCompetitor, setFilterCompetitor] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  // Similar modal
  const { similar, loading: similarLoading, error: similarError, fetch: fetchSimilar, reset: resetSimilar } = useRadarSimilar();
  const [similarModalOpen, setSimilarModalOpen] = useState(false);
  const [sourceItem, setSourceItem] = useState<CIItem | null>(null);

  // Scan
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<string | null>(null);

  // Export all analyses
  const [exportingAll, setExportingAll] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  // Add Competitor form
  const [showAddForm, setShowAddForm] = useState(false);
  const [newName, setNewName] = useState('');
  const [newWebsite, setNewWebsite] = useState('');
  const [addingCompetitor, setAddingCompetitor] = useState(false);
  const [addError, setAddError] = useState('');

  // Discovery
  const [showDiscovery, setShowDiscovery] = useState(false);
  const [discoveryQuery, setDiscoveryQuery] = useState('');
  const [discovering, setDiscovering] = useState(false);
  const [suggestions, setSuggestions] = useState<{ name: string; website_url: string; reason: string }[]>([]);
  const [addingSuggestion, setAddingSuggestion] = useState<string | null>(null);

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleSearch = useCallback((newQuery: string) => {
    setQuery(newQuery);
    if (!newQuery.trim() && !filterType && !filterPlatform && !filterFormat && !filterCompetitor) {
      resetSearch();
      return;
    }
    debouncedSearch({
      q: newQuery || undefined,
      item_type: filterType || undefined,
      platform: filterPlatform || undefined,
      format: filterFormat || undefined,
      competitor: filterCompetitor || undefined,
      min_date: dateFrom || undefined,
      max_date: dateTo || undefined,
      limit: 20,
      offset: 0,
    });
  }, [filterType, filterPlatform, filterFormat, filterCompetitor, dateFrom, dateTo, debouncedSearch, resetSearch]);

  const triggerSearch = useCallback(() => {
    debouncedSearch({
      q: query || undefined,
      item_type: filterType || undefined,
      platform: filterPlatform || undefined,
      format: filterFormat || undefined,
      competitor: filterCompetitor || undefined,
      min_date: dateFrom || undefined,
      max_date: dateTo || undefined,
      limit: 20,
      offset: 0,
    });
  }, [query, filterType, filterPlatform, filterFormat, filterCompetitor, dateFrom, dateTo, debouncedSearch]);

  const handleViewSimilar = useCallback(async (itemId: string) => {
    const found = searchResults.find(r => r.id === itemId);
    setSourceItem(found || null);
    setSimilarModalOpen(true);
    await fetchSimilar(itemId);
  }, [searchResults, fetchSimilar]);

  const handleCloseSimilar = useCallback(() => {
    setSimilarModalOpen(false);
    setSourceItem(null);
    resetSimilar();
  }, [resetSimilar]);

  const handleRunScan = async () => {
    try {
      setScanning(true);
      setScanResult(null);
      const res = await ciApi.runDetection();
      const summary = res.data?.summary;
      if (summary) {
        const msg = `Ingest: ${summary.ingest_enqueued || 0} | Detect: ${summary.detect_enqueued || 0}`;
        setScanResult(msg);
      }
      refetchCompetitors();
    } catch {
      setScanResult('Error al ejecutar escaneo');
    } finally {
      setScanning(false);
      setTimeout(() => setScanResult(null), 5000);
    }
  };

  const handleCompetitorSelect = (name: string) => {
    setSelectedCompetitor(name === selectedCompetitor ? '' : name);
  };

  const handleAddCompetitor = async () => {
    if (!newName.trim()) return;
    setAddingCompetitor(true);
    setAddError('');
    try {
      await ciApi.createCompetitor({
        name: newName.trim(),
        website_url: newWebsite.trim() || undefined,
        domains: newWebsite.trim() ? [{ domain: newWebsite.trim(), domain_type: 'website' }] : [],
      });
      setNewName('');
      setNewWebsite('');
      setShowAddForm(false);
      refetchCompetitors();
    } catch (err: any) {
      setAddError(err?.response?.data?.detail || 'Error al agregar competidor');
    } finally {
      setAddingCompetitor(false);
    }
  };

  const handleDeleteCompetitor = async (id: string, name: string) => {
    if (!confirm(`Eliminar competidor "${name}"?`)) return;
    try {
      await ciApi.deleteCompetitor(id);
      refetchCompetitors();
      if (selectedCompetitor === name) setSelectedCompetitor('');
    } catch {
      // silent
    }
  };

  const handleDiscover = async () => {
    if (!discoveryQuery.trim()) return;
    try {
      setDiscovering(true);
      const res = await ciApi.discoverCompetitors(discoveryQuery.trim());
      setSuggestions(res.data.competitors || []);
    } catch {
      setSuggestions([]);
    } finally {
      setDiscovering(false);
    }
  };

  const handleAddSuggestion = async (s: { name: string; website_url: string }) => {
    try {
      setAddingSuggestion(s.name);
      await ciApi.createCompetitor({
        name: s.name,
        website_url: s.website_url || undefined,
        domains: s.website_url ? [{ domain: s.website_url, domain_type: 'website' }] : [],
      });
      setSuggestions(prev => prev.filter(x => x.name !== s.name));
      refetchCompetitors();
    } catch {
      // silent
    } finally {
      setAddingSuggestion(null);
    }
  };

  const handleExportAllAnalyses = async () => {
    try {
      setExportingAll(true);
      const res = await ciApi.exportAnalysisPdf();
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `ci_strategy_report_${new Date().toISOString().slice(0, 10)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      let msg = 'No hay items analizados aún';
      try {
        const blob = err?.response?.data;
        if (blob instanceof Blob) {
          const text = await blob.text();
          const json = JSON.parse(text);
          if (json?.detail) msg = json.detail;
        } else if (err?.response?.data?.detail) {
          msg = err.response.data.detail;
        }
      } catch { /* keep default msg */ }
      console.error('Export analysis PDF failed:', msg, err);
      setExportError(msg);
      setTimeout(() => setExportError(null), 5000);
    } finally {
      setExportingAll(false);
    }
  };

  // ── Tabs ─────────────────────────────────────────────────────────────────

  const tabs: { key: TabKey; labelKey: string }[] = [
    { key: 'ads', labelKey: 'radar.tab_ads' },
    { key: 'offers', labelKey: 'radar.tab_offers' },
    { key: 'trends', labelKey: 'radar.tab_trends' },
    { key: 'search', labelKey: 'radar.tab_search' },
  ];

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <RadarIcon size={32} className="page-icon" />
          <div>
            <h1 className="page-title">{t('radar.title')}</h1>
            <p className="page-description">{t('radar.subtitle')}</p>
          </div>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
          {scanResult && (
            <span className="radar-scan-result">{scanResult}</span>
          )}
          {exportError && (
            <span className="radar-pdf-error">{exportError}</span>
          )}
          <button
            className="radar-export-all-btn"
            onClick={handleExportAllAnalyses}
            disabled={exportingAll}
            title="Export all analyses as PDF"
          >
            {exportingAll ? <Loader size={14} className="spinning" /> : <Download size={14} />}
            Export Analyses
          </button>
          <button
            className="btn-primary"
            onClick={handleRunScan}
            disabled={scanning || competitors.length === 0}
            title={competitors.length === 0 ? 'Agrega competidores primero' : ''}
          >
            {scanning ? <Loader size={18} className="spin-icon" /> : <RefreshCw size={18} />}
            {scanning ? t('radar.scanning') : t('radar.run_scan')}
          </button>
        </div>
      </div>

      <div className="radar-layout">
        {/* Left: Competitors Panel */}
        <aside className="radar-competitors-panel">
          <div className="radar-panel-header">
            <Users size={18} />
            <h3>{t('radar.competitors')}</h3>
            <button
              className="radar-add-btn"
              onClick={() => { setShowAddForm(!showAddForm); setShowDiscovery(false); }}
              title="Agregar competidor"
            >
              {showAddForm ? <X size={16} /> : <Plus size={16} />}
            </button>
            <button
              className="radar-discover-btn"
              onClick={() => { setShowDiscovery(!showDiscovery); setShowAddForm(false); }}
              title="Descubrir competidores con IA"
            >
              {showDiscovery ? <X size={16} /> : <Sparkles size={16} />}
            </button>
          </div>

          {showAddForm && (
            <div className="radar-add-form">
              <input
                type="text"
                className="radar-input"
                placeholder="Nombre del competidor *"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddCompetitor()}
                autoFocus
              />
              <input
                type="text"
                className="radar-input"
                placeholder="Website URL (opcional)"
                value={newWebsite}
                onChange={(e) => setNewWebsite(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleAddCompetitor()}
              />
              {addError && <p className="radar-add-error">{addError}</p>}
              <button
                className="btn-primary radar-add-submit"
                onClick={handleAddCompetitor}
                disabled={addingCompetitor || !newName.trim()}
              >
                {addingCompetitor ? <Loader size={14} className="spin-icon" /> : <Plus size={14} />}
                Agregar
              </button>
            </div>
          )}

          {showDiscovery && (
            <div className="radar-discovery-panel">
              <div className="radar-discovery-input-row">
                <input
                  type="text"
                  className="radar-input"
                  placeholder="Industria o nicho (ej: fitness, ecommerce moda)"
                  value={discoveryQuery}
                  onChange={(e) => setDiscoveryQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleDiscover()}
                  autoFocus
                />
                <button
                  className="btn-primary radar-discover-submit"
                  onClick={handleDiscover}
                  disabled={discovering || !discoveryQuery.trim()}
                >
                  {discovering ? <Loader size={14} className="spin-icon" /> : <Sparkles size={14} />}
                  Descubrir
                </button>
              </div>
              {suggestions.length > 0 && (
                <ul className="radar-suggestions-list">
                  {suggestions.map((s) => (
                    <li key={s.name} className="radar-suggestion-item">
                      <div className="radar-suggestion-info">
                        <span className="radar-suggestion-name">{s.name}</span>
                        {s.website_url && (
                          <span className="radar-suggestion-url">
                            <Globe size={10} /> {s.website_url.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                          </span>
                        )}
                        <span className="radar-suggestion-reason">{s.reason}</span>
                      </div>
                      <button
                        className="btn-primary radar-suggestion-add"
                        onClick={() => handleAddSuggestion(s)}
                        disabled={addingSuggestion === s.name}
                      >
                        {addingSuggestion === s.name ? <Loader size={12} className="spin-icon" /> : <Plus size={12} />}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {competitorsLoading ? (
            <div className="loading-state" style={{ padding: 'var(--space-4)' }}>
              <Loader size={16} className="spin-icon" /> {t('common.loading')}
            </div>
          ) : competitors.length === 0 && !showAddForm ? (
            <div className="radar-empty-panel">
              <p>{t('radar.no_competitors')}</p>
              <p className="radar-hint">{t('radar.no_competitors_hint')}</p>
              <button
                className="btn-secondary radar-add-first"
                onClick={() => setShowAddForm(true)}
              >
                <Plus size={14} /> Agregar competidor
              </button>
            </div>
          ) : (
            <ul className="radar-competitor-list">
              {competitors.map((c) => (
                <li
                  key={c.id}
                  className={`radar-competitor-item ${selectedCompetitor === c.name ? 'radar-competitor-item--active' : ''}`}
                  onClick={() => handleCompetitorSelect(c.name)}
                >
                  <div className="radar-competitor-info">
                    <span className="radar-competitor-name">{c.name}</span>
                    {c.website_url && (
                      <span className="radar-competitor-platform">
                        <Globe size={10} /> {c.website_url.replace(/^https?:\/\//, '').replace(/\/$/, '')}
                      </span>
                    )}
                    {!c.website_url && c.platform && (
                      <span className="radar-competitor-platform">{c.platform}</span>
                    )}
                  </div>
                  <div className="radar-competitor-actions">
                    <div className="radar-competitor-stats">
                      <span className="radar-competitor-count">{c.active_ads || 0}</span>
                      <span className="radar-competitor-label">ads</span>
                    </div>
                    <button
                      className="radar-delete-btn"
                      onClick={(e) => { e.stopPropagation(); handleDeleteCompetitor(c.id, c.name); }}
                      title="Eliminar"
                    >
                      <Trash2 size={12} />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </aside>

        {/* Right: Main Content */}
        <main className="radar-main">
          {/* Tabs */}
          <div className="radar-tabs">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                className={`radar-tab ${activeTab === tab.key ? 'radar-tab--active' : ''}`}
                onClick={() => setActiveTab(tab.key)}
              >
                {t(tab.labelKey)}
              </button>
            ))}
          </div>

          {/* Tab Content */}
          <div className="radar-tab-content">
            {activeTab === 'ads' && (
              <NewAdsFeed
                selectedCompetitor={selectedCompetitor}
                onViewSimilar={handleViewSimilar}
              />
            )}

            {activeTab === 'offers' && (
              <OfferChangesPanel selectedCompetitor={selectedCompetitor} />
            )}

            {activeTab === 'trends' && (
              <AngleTrendsChart selectedCompetitor={selectedCompetitor} />
            )}

            {activeTab === 'search' && (
              <div className="radar-search-panel">
                <RadarFiltersBar
                  query={query}
                  onQueryChange={handleSearch}
                  selectedType={filterType}
                  onTypeChange={(v) => { setFilterType(v); triggerSearch(); }}
                  selectedPlatform={filterPlatform}
                  onPlatformChange={(v) => { setFilterPlatform(v); triggerSearch(); }}
                  selectedFormat={filterFormat}
                  onFormatChange={(v) => { setFilterFormat(v); triggerSearch(); }}
                  selectedCompetitor={filterCompetitor}
                  onCompetitorChange={(v) => { setFilterCompetitor(v); triggerSearch(); }}
                  competitors={competitors}
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  onDateFromChange={(v) => { setDateFrom(v); triggerSearch(); }}
                  onDateToChange={(v) => { setDateTo(v); triggerSearch(); }}
                />

                {searchLoading ? (
                  <div className="loading-state">
                    <Loader size={20} className="spin-icon" /> {t('common.loading')}
                  </div>
                ) : searchError ? (
                  <div className="error-state"><p>{searchError}</p></div>
                ) : searchResults.length === 0 && (query || filterType || filterPlatform || filterFormat || filterCompetitor) ? (
                  <div className="empty-state">
                    <Search size={48} />
                    <h3>{t('radar.no_results')}</h3>
                    <p>{t('radar.no_results_hint')}</p>
                  </div>
                ) : searchResults.length === 0 ? (
                  <div className="empty-state">
                    <Search size={48} />
                    <h3>{t('radar.tab_search')}</h3>
                    <p>{t('radar.search_placeholder')}</p>
                  </div>
                ) : (
                  <>
                    <div className="radar-feed-list">
                      {searchResults.map((item) => (
                        <RadarItemCard key={item.id} item={item} onViewSimilar={handleViewSimilar} />
                      ))}
                    </div>
                    {hasMore && (
                      <button className="radar-load-more" onClick={loadMore}>
                        {t('radar.load_more')}
                      </button>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        </main>
      </div>

      <SimilarityModal
        isOpen={similarModalOpen}
        onClose={handleCloseSimilar}
        sourceItem={sourceItem}
        similarItems={similar}
        loading={similarLoading}
        error={similarError}
      />
    </div>
  );
}
