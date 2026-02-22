import { useState } from 'react';
import { Eye, Calendar, Tag, Globe, Sparkles, Download, RefreshCw, Loader, ChevronDown, ChevronUp, Shield } from 'lucide-react';
import { useLanguage } from '../../contexts/LanguageContext';
import { CIItem, CIAnalysis, ciApi } from '../../services/api';

interface RadarItemCardProps {
  item: CIItem;
  onViewSimilar?: (itemId: string) => void;
  compact?: boolean;
}

/** Strip residual markdown code fences from LLM text fields. */
function cleanText(val: unknown): string {
  if (typeof val !== 'string') return String(val ?? '');
  return val.replace(/^```(?:json)?\s*/g, '').replace(/\s*```$/g, '').trim();
}

export default function RadarItemCard({ item, onViewSimilar, compact }: RadarItemCardProps) {
  const { t } = useLanguage();
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<CIAnalysis | null>(item.analysis || null);
  const [showAnalysis, setShowAnalysis] = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);

  const formatDate = (dateStr: string) => {
    try {
      return new Date(dateStr).toLocaleDateString(undefined, {
        month: 'short', day: 'numeric', year: 'numeric',
      });
    } catch {
      return dateStr;
    }
  };

  const handleAnalyze = async (forceRefresh = false) => {
    try {
      setAnalyzing(true);
      const res = await ciApi.analyzeItem(item.id, forceRefresh);
      setAnalysis(res.data.analysis);
      setShowAnalysis(true);
    } catch (err) {
      console.error('Analysis failed:', err);
    } finally {
      setAnalyzing(false);
    }
  };

  const handleExportPdf = async () => {
    try {
      setExportingPdf(true);
      setPdfError(null);
      const res = await ciApi.exportAnalysisPdf(item.id);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `analysis_${item.competitor}_${item.id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      let msg = 'Error al exportar PDF';
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
      console.error('PDF export failed:', msg, err);
      setPdfError(msg);
      setTimeout(() => setPdfError(null), 5000);
    } finally {
      setExportingPdf(false);
    }
  };

  const threatColor = (level: string) => {
    switch (level) {
      case 'high': return '#f44336';
      case 'medium': return '#ff9800';
      case 'low': return '#4caf50';
      default: return '#ff9800';
    }
  };

  return (
    <div className={`radar-item-card ${compact ? 'radar-item-card--compact' : ''}`}>
      <div className="radar-item-header">
        <div className="radar-item-meta">
          <span className={`radar-item-type radar-item-type--${item.item_type}`}>
            {item.item_type}
          </span>
          {item.platform && (
            <span className="radar-item-platform">
              <Globe size={12} />
              {item.platform}
            </span>
          )}
          {item.format && (
            <span className="radar-item-format">
              <Tag size={12} />
              {item.format}
            </span>
          )}
        </div>
        <span className="radar-item-competitor">{item.competitor}</span>
      </div>

      {item.headline && (
        <h4 className="radar-item-headline">{item.headline}</h4>
      )}

      {item.body && !compact && (
        <p className="radar-item-body">
          {item.body.length > 200 ? item.body.slice(0, 200) + '...' : item.body}
        </p>
      )}

      {item.cta && (
        <span className="radar-item-cta">{item.cta}</span>
      )}

      {/* Analysis Actions */}
      <div className="radar-item-analysis-actions">
        {!analysis ? (
          <button
            className="radar-item-analyze-btn"
            onClick={() => handleAnalyze(false)}
            disabled={analyzing}
          >
            {analyzing ? <Loader size={14} className="spinning" /> : <Sparkles size={14} />}
            {analyzing ? 'Analizando...' : 'Analizar'}
          </button>
        ) : (
          <>
            <button
              className="radar-item-toggle-btn"
              onClick={() => setShowAnalysis(!showAnalysis)}
            >
              {showAnalysis ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              {showAnalysis ? 'Ocultar Analisis' : 'Ver Analisis'}
            </button>
            <button
              className="radar-item-refresh-btn"
              onClick={() => handleAnalyze(true)}
              disabled={analyzing}
              title="Re-analizar"
            >
              {analyzing ? <Loader size={14} className="spinning" /> : <RefreshCw size={14} />}
            </button>
            <button
              className="radar-item-pdf-btn"
              onClick={handleExportPdf}
              disabled={exportingPdf}
              title="Descargar PDF"
            >
              {exportingPdf ? <Loader size={14} className="spinning" /> : <Download size={14} />}
            </button>
          </>
        )}
        {pdfError && <span className="radar-pdf-error">{pdfError}</span>}
      </div>

      {/* Analysis Panel */}
      {analysis && showAnalysis && (
        <div className="radar-item-analysis">
          <div className="analysis-header">
            <Sparkles size={16} />
            <span>Strategic Analysis</span>
            <span
              className="threat-badge"
              style={{ backgroundColor: threatColor(analysis.threat_level), color: '#fff' }}
            >
              <Shield size={10} />
              {analysis.threat_level?.toUpperCase()}
            </span>
          </div>

          {analysis.competitor_strategy && (
            <div className="analysis-section">
              <h5>Competitor Strategy</h5>
              <p>{cleanText(analysis.competitor_strategy)}</p>
            </div>
          )}

          {analysis.brand_comparison && (
            <div className="analysis-section">
              <h5>Brand Comparison</h5>
              <p>{cleanText(analysis.brand_comparison)}</p>
            </div>
          )}

          {Array.isArray(analysis.messaging_angles) && analysis.messaging_angles.length > 0 && (
            <div className="analysis-section">
              <h5>Messaging Angles</h5>
              <div className="analysis-tags">
                {analysis.messaging_angles.map((angle, i) => (
                  <span key={i} className="analysis-tag">{cleanText(angle)}</span>
                ))}
              </div>
            </div>
          )}

          {Array.isArray(analysis.recommendations) && analysis.recommendations.length > 0 && (
            <div className="analysis-section">
              <h5>Recommendations</h5>
              <ul>
                {analysis.recommendations.map((rec, i) => (
                  <li key={i}>{cleanText(rec)}</li>
                ))}
              </ul>
            </div>
          )}

          {Array.isArray(analysis.ad_copy_suggestions) && analysis.ad_copy_suggestions.length > 0 && (
            <div className="analysis-section">
              <h5>Suggested Ad Copy</h5>
              <ol>
                {analysis.ad_copy_suggestions.map((copy, i) => (
                  <li key={i}>{cleanText(copy)}</li>
                ))}
              </ol>
            </div>
          )}

          {Array.isArray(analysis.opportunities) && analysis.opportunities.length > 0 && (
            <div className="analysis-section">
              <h5>Opportunities</h5>
              <ul>
                {analysis.opportunities.map((opp, i) => (
                  <li key={i}>{cleanText(opp)}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      <div className="radar-item-footer">
        <div className="radar-item-dates">
          <span title={t('radar.first_seen')}>
            <Calendar size={12} />
            {formatDate(item.first_seen)}
          </span>
          {item.price !== null && item.price > 0 && (
            <span className="radar-item-price">${item.price.toFixed(2)}</span>
          )}
          {item.discount && (
            <span className="radar-item-discount">{item.discount}</span>
          )}
        </div>
        {onViewSimilar && (
          <button
            className="radar-item-similar-btn"
            onClick={() => onViewSimilar(item.id)}
          >
            <Eye size={14} />
            {t('radar.view_similar')}
          </button>
        )}
      </div>
    </div>
  );
}
