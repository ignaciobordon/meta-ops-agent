import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Layers, Send, Lock, RefreshCw,
  FileDown, FileSpreadsheet, Loader, CheckCircle, AlertTriangle, Shield,
  Clock, Package, Eye,
} from 'lucide-react';
import { creativesApi, contentStudioApi, Creative, ContentPackSummary } from '../services/api';
import { useJobPolling } from '../hooks/useJobPolling';
import './ContentStudio.css';

// Presets
const AUDIENCE_PRESETS = [
  'Principiantes 18-30', 'Adultos 30-45', 'Adultos 45+',
  'Mujeres tonificacion', 'Hombres recomposicion', 'Ex gym frustrados',
  'Crossfitters lesionados', 'Sedentarios con dolor espalda', 'Busy professionals',
];
const GOAL_PRESETS = ['awareness', 'leads', 'sales', 'reactivation', 'retention'];
const TONE_PRESETS = [
  'profesional', 'directo', 'premium', 'minimalista', 'estoico', 'educativo',
  'motivacional', 'humor seco', 'corporativo', 'luxury wellness', 'agresivo', 'friendly',
];
const FRAMEWORK_PRESETS = ['', 'AIDA', 'PAS', 'BAB', 'Story-Lesson', 'List', 'Contrast'];
const HOOK_STYLE_PRESETS = ['', 'Anti-belief', 'Shock truth', 'Problem callout', 'Authority claim', 'Before/After', 'Data-stat'];

// Score metric max values for display
const SCORE_MAXES: Record<string, number> = {
  hook_strength: 25,
  clarity: 15,
  cta_fit: 10,
  channel_fit: 15,
  brand_voice_match: 15,
  goal_alignment: 10,
  novelty: 10,
};

// All available channels grouped by platform
const CHANNEL_GROUPS = [
  {
    platform: 'Instagram',
    channels: [
      { key: 'ig_reel', label: 'Reel' },
      { key: 'ig_post', label: 'Post' },
      { key: 'ig_carousel', label: 'Carousel' },
      { key: 'ig_story', label: 'Story' },
    ],
  },
  {
    platform: 'TikTok',
    channels: [{ key: 'tiktok_short', label: 'Short' }],
  },
  {
    platform: 'YouTube',
    channels: [
      { key: 'yt_short', label: 'Short' },
      { key: 'yt_long', label: 'Long Form' },
    ],
  },
  {
    platform: 'Facebook',
    channels: [
      { key: 'fb_feed', label: 'Feed Post' },
      { key: 'fb_ad_copy', label: 'Ad Copy' },
    ],
  },
  {
    platform: 'X (Twitter)',
    channels: [
      { key: 'x_post', label: 'Post' },
      { key: 'x_thread', label: 'Thread' },
    ],
  },
  {
    platform: 'LinkedIn',
    channels: [{ key: 'linkedin_post', label: 'Post' }],
  },
  {
    platform: 'Email',
    channels: [{ key: 'email_newsletter', label: 'Newsletter' }],
  },
];

interface Variant {
  id: string;
  channel: string;
  format: string;
  variant_index: number;
  output_json: Record<string, any>;
  score: number;
  score_breakdown_json: Record<string, number>;
  rationale_text: string;
}

export default function ContentStudio() {
  const [searchParams] = useSearchParams();

  // Creatives
  const [creatives, setCreatives] = useState<Creative[]>([]);
  const [selectedCreativeId, setSelectedCreativeId] = useState(searchParams.get('creative_id') || '');

  // Channel selection
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set());

  // Settings
  const [goal, setGoal] = useState('awareness');
  const [audience, setAudience] = useState('');
  const [toneTags, setToneTags] = useState<string[]>([]);
  const [framework, setFramework] = useState('');
  const [hookStyle, setHookStyle] = useState('');
  const [curatorPrompt, setCuratorPrompt] = useState('');

  // Job state
  const [packId, setPackId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const { status: jobStatus, error: jobError } = useJobPolling(jobId, 2500, 300000);

  // Results
  const [variants, setVariants] = useState<Variant[]>([]);
  const [activeTab, setActiveTab] = useState('');
  const [lockedVariants, setLockedVariants] = useState<Record<string, string>>({});
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exportingPdf, setExportingPdf] = useState(false);
  const [exportingXlsx, setExportingXlsx] = useState(false);

  // Pack history
  const [packHistory, setPackHistory] = useState<ContentPackSummary[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [selectedHistoryPackId, setSelectedHistoryPackId] = useState<string | null>(null);

  // Load creatives and pack history
  useEffect(() => {
    creativesApi.list().then(res => setCreatives(res.data)).catch(() => {});
    setLoadingHistory(true);
    contentStudioApi.listPacks(20).then(res => {
      setPackHistory(res.data);
    }).catch(() => {}).finally(() => setLoadingHistory(false));
  }, []);

  // When job succeeds, load variants + locks
  useEffect(() => {
    if (jobStatus === 'succeeded' && packId) {
      Promise.all([
        contentStudioApi.getVariants(packId),
        contentStudioApi.getLocks(packId),
      ]).then(([varRes, lockRes]) => {
        setVariants(varRes.data);
        setLockedVariants(lockRes.data || {});
        setGenerating(false);
        setJobId(null);
        // Refresh pack history
        contentStudioApi.listPacks(20).then(res => setPackHistory(res.data)).catch(() => {});
        if (varRes.data.length > 0) {
          setActiveTab(varRes.data[0].channel);
        } else {
          setError('Generation completed but no variants were produced. The LLM response may have been malformed. Try again.');
        }
      }).catch(() => {
        setError('Failed to load variants');
        setGenerating(false);
      });
    }
    if (jobStatus === 'failed' || jobStatus === 'dead') {
      setError(jobError || 'Generation failed');
      setGenerating(false);
      setJobId(null);
    }
  }, [jobStatus, packId, jobError]);

  const toggleChannel = (key: string) => {
    setSelectedChannels(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleTone = (tone: string) => {
    setToneTags(prev =>
      prev.includes(tone) ? prev.filter(t => t !== tone) : [...prev, tone]
    );
  };

  const handleLoadPack = async (historyPackId: string) => {
    setError(null);
    setSelectedHistoryPackId(historyPackId);
    try {
      const [varRes, lockRes] = await Promise.all([
        contentStudioApi.getVariants(historyPackId),
        contentStudioApi.getLocks(historyPackId),
      ]);
      setPackId(historyPackId);
      setVariants(varRes.data);
      setLockedVariants(lockRes.data || {});
      if (varRes.data.length > 0) {
        setActiveTab(varRes.data[0].channel);
      }
    } catch {
      setError('Failed to load pack variants');
    }
  };

  const handleGenerate = async () => {
    if (!selectedCreativeId) {
      setError('Select a creative first');
      return;
    }
    if (selectedChannels.size === 0) {
      setError('Select at least one channel');
      return;
    }

    setError(null);
    setGenerating(true);
    setVariants([]);

    try {
      const res = await contentStudioApi.createPack({
        creative_id: selectedCreativeId,
        channels: Array.from(selectedChannels).map(ch => ({ channel: ch, format: '' })),
        goal,
        target_audience: audience,
        tone_tags: toneTags,
        curator_prompt: curatorPrompt,
        framework_preference: framework,
        hook_style_preference: hookStyle,
      });
      setPackId(res.data.pack_id);
      setJobId(res.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start generation');
      setGenerating(false);
    }
  };

  const handleLock = async (channel: string, variantId: string) => {
    if (!packId) return;
    try {
      await contentStudioApi.lockVariant(packId, { channel, variant_id: variantId });
      setLockedVariants(prev => ({ ...prev, [channel]: variantId }));
    } catch (err: any) {
      setError('Failed to lock variant');
    }
  };

  const hasLockedVariants = Object.keys(lockedVariants).length > 0;

  const handleRegenerate = async () => {
    if (!packId) return;
    setError(null);
    setGenerating(true);

    try {
      const res = await contentStudioApi.regenerate(packId);
      setJobId(res.data.job_id);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start regeneration');
      setGenerating(false);
    }
  };

  const handleExportPdf = async () => {
    if (!packId) return;
    setExportingPdf(true);
    try {
      const res = await contentStudioApi.exportPdf(packId);
      const blob = new Blob([res.data], { type: 'application/pdf' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `content_pack_${packId.substring(0, 8)}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Failed to export PDF');
    } finally {
      setExportingPdf(false);
    }
  };

  const handleExportXlsx = async () => {
    if (!packId) return;
    setExportingXlsx(true);
    try {
      const res = await contentStudioApi.exportXlsx(packId);
      const blob = new Blob([res.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `content_pack_${packId.substring(0, 8)}.xlsx`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch {
      setError('Failed to export XLSX');
    } finally {
      setExportingXlsx(false);
    }
  };

  // Get unique channels from variants for tabs
  const channelTabs = [...new Set(variants.map(v => v.channel))];
  const filteredVariants = variants.filter(v => v.channel === activeTab);

  return (
    <div className="page-container">
      <div className="page-header">
        <div className="page-header-content">
          <Layers size={32} className="page-icon" />
          <div>
            <h1 className="page-title">Content Studio</h1>
            <p className="page-description">Generate multi-platform production packs from your creatives</p>
          </div>
        </div>
      </div>

      {/* Configuration Panel */}
      <div className="cs-config-panel">
        {/* Creative Selector */}
        <div className="cs-section">
          <label className="cs-label">Base Creative</label>
          <select
            className="cs-select"
            value={selectedCreativeId}
            onChange={e => setSelectedCreativeId(e.target.value)}
          >
            <option value="">-- Select a creative --</option>
            {creatives.map(c => (
              <option key={c.id} value={c.id}>
                {c.angle_name || c.id.substring(0, 8)} (Score: {(c.score * 100).toFixed(0)}/100)
              </option>
            ))}
          </select>
        </div>

        {/* Channel Selector */}
        <div className="cs-section">
          <label className="cs-label">Channels</label>
          <div className="cs-channel-groups">
            {CHANNEL_GROUPS.map(group => (
              <div key={group.platform} className="cs-channel-group">
                <span className="cs-platform-label">{group.platform}</span>
                <div className="cs-channel-options">
                  {group.channels.map(ch => (
                    <label key={ch.key} className={`cs-channel-chip ${selectedChannels.has(ch.key) ? 'active' : ''}`}>
                      <input
                        type="checkbox"
                        checked={selectedChannels.has(ch.key)}
                        onChange={() => toggleChannel(ch.key)}
                      />
                      {ch.label}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Settings Row */}
        <div className="cs-settings-row">
          <div className="cs-field">
            <label className="cs-label">Goal</label>
            <select className="cs-select" value={goal} onChange={e => setGoal(e.target.value)}>
              {GOAL_PRESETS.map(g => (
                <option key={g} value={g}>{g.charAt(0).toUpperCase() + g.slice(1)}</option>
              ))}
            </select>
          </div>

          <div className="cs-field">
            <label className="cs-label">Audience</label>
            <select
              className="cs-select"
              value={audience}
              onChange={e => setAudience(e.target.value)}
            >
              <option value="">Custom...</option>
              {AUDIENCE_PRESETS.map(a => (
                <option key={a} value={a}>{a}</option>
              ))}
            </select>
            {audience === '' && (
              <input
                className="cs-input"
                placeholder="Describe your target audience..."
                onChange={e => setAudience(e.target.value)}
              />
            )}
          </div>

          <div className="cs-field">
            <label className="cs-label">Framework</label>
            <select className="cs-select" value={framework} onChange={e => setFramework(e.target.value)}>
              <option value="">Auto</option>
              {FRAMEWORK_PRESETS.filter(f => f).map(f => (
                <option key={f} value={f}>{f}</option>
              ))}
            </select>
          </div>

          <div className="cs-field">
            <label className="cs-label">Hook Style</label>
            <select className="cs-select" value={hookStyle} onChange={e => setHookStyle(e.target.value)}>
              <option value="">Auto</option>
              {HOOK_STYLE_PRESETS.filter(h => h).map(h => (
                <option key={h} value={h}>{h}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Tone Tags */}
        <div className="cs-section">
          <label className="cs-label">Tone</label>
          <div className="cs-tone-chips">
            {TONE_PRESETS.map(tone => (
              <button
                key={tone}
                className={`cs-tone-chip ${toneTags.includes(tone) ? 'active' : ''}`}
                onClick={() => toggleTone(tone)}
              >
                {tone}
              </button>
            ))}
          </div>
        </div>

        {/* Curator Prompt */}
        <div className="cs-section">
          <label className="cs-label">Curator Notes (optional)</label>
          <textarea
            className="cs-textarea"
            value={curatorPrompt}
            onChange={e => setCuratorPrompt(e.target.value)}
            placeholder="Any specific instructions for the content generation..."
            rows={3}
          />
        </div>

        {/* Generate Button */}
        <div className="cs-actions">
          <button
            className="btn-primary cs-generate-btn"
            onClick={handleGenerate}
            disabled={generating || !selectedCreativeId || selectedChannels.size === 0}
          >
            {generating ? (
              <><Loader size={18} className="spin-icon" /> Generating Pack...</>
            ) : (
              <><Send size={18} /> Generate Production Pack</>
            )}
          </button>
        </div>
      </div>

      {/* Pack History */}
      {packHistory.length > 0 && (
        <div className="cs-history-panel">
          <div className="cs-history-header">
            <Package size={18} />
            <h3>Pack History</h3>
            {loadingHistory && <Loader size={14} className="spin-icon" />}
          </div>
          <div className="cs-history-list">
            {packHistory.map(p => (
              <div
                key={p.id}
                className={`cs-history-item ${selectedHistoryPackId === p.id ? 'active' : ''} ${p.variants_count === 0 ? 'empty' : ''}`}
                onClick={() => p.variants_count > 0 && handleLoadPack(p.id)}
                role="button"
                tabIndex={0}
              >
                <div className="cs-history-item-main">
                  <span className={`cs-history-status cs-status-${p.status}`}>
                    {p.status === 'succeeded' ? <CheckCircle size={12} /> : p.status === 'failed' ? <AlertTriangle size={12} /> : <Clock size={12} />}
                  </span>
                  <span className="cs-history-goal">{p.goal || 'general'}</span>
                  <span className="cs-history-channels">
                    {(p.channels_json || []).map(ch => ch.channel).join(', ') || 'N/A'}
                  </span>
                  <span className="cs-history-variants">
                    {p.variants_count} variant{p.variants_count !== 1 ? 's' : ''}
                  </span>
                  <span className="cs-history-date">
                    {p.created_at ? new Date(p.created_at).toLocaleDateString() : ''}
                  </span>
                  {p.variants_count > 0 && (
                    <button className="cs-history-view-btn" onClick={(e) => { e.stopPropagation(); handleLoadPack(p.id); }}>
                      <Eye size={14} /> View
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="cs-error-banner">
          <AlertTriangle size={16} />
          <span>{error}</span>
          <button onClick={() => setError(null)} className="cs-dismiss">&times;</button>
        </div>
      )}

      {/* Generating State */}
      {generating && (
        <div className="loading-state">
          Generating content pack... This may take 30-60 seconds per channel.
        </div>
      )}

      {/* Results */}
      {variants.length > 0 && (
        <div className="cs-results">
          <div className="cs-results-header">
            <h2>Production Pack Results</h2>
            <div className="cs-export-buttons">
              {hasLockedVariants && (
                <button
                  className="btn-primary cs-regen-btn"
                  onClick={handleRegenerate}
                  disabled={generating}
                >
                  {generating ? (
                    <><Loader size={14} className="spin-icon" /> Regenerating...</>
                  ) : (
                    <><RefreshCw size={14} /> Regenerate Others</>
                  )}
                </button>
              )}
              <button className="btn-download-report" onClick={handleExportPdf} disabled={exportingPdf}>
                {exportingPdf ? <Loader size={14} className="spin-icon" /> : <FileDown size={14} />}
                Export PDF
              </button>
              <button className="btn-download-report" onClick={handleExportXlsx} disabled={exportingXlsx}>
                {exportingXlsx ? <Loader size={14} className="spin-icon" /> : <FileSpreadsheet size={14} />}
                Export XLSX
              </button>
            </div>
          </div>

          {/* Channel Tabs */}
          <div className="cs-tabs">
            {channelTabs.map(ch => (
              <button
                key={ch}
                className={`cs-tab ${activeTab === ch ? 'active' : ''}`}
                onClick={() => setActiveTab(ch)}
              >
                {ch.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase())}
                <span className="cs-tab-count">{variants.filter(v => v.channel === ch).length}</span>
              </button>
            ))}
          </div>

          {/* Variant Cards */}
          <div className="cs-variants-grid">
            {filteredVariants.map(v => {
              const isLocked = lockedVariants[v.channel] === v.id;
              return (
                <div key={v.id} className={`cs-variant-card ${isLocked ? 'locked' : ''}`}>
                  <div className="cs-variant-header">
                    <span className="cs-variant-number">
                      {isLocked && <Shield size={14} className="cs-locked-icon" />}
                      Variant {v.variant_index}
                      {isLocked && <span className="cs-locked-badge">LOCKED</span>}
                    </span>
                    <span className="cs-variant-score">{v.score.toFixed(0)}/100</span>
                  </div>

                  <div className="cs-variant-content">
                    {Object.entries(v.output_json).map(([key, val]) => (
                      <div key={key} className="cs-variant-field">
                        <span className="cs-field-label">{key.replace(/_/g, ' ').toUpperCase()}</span>
                        <span className="cs-field-value">
                          {Array.isArray(val) ? (
                            typeof val[0] === 'object' ? (
                              // Nested objects like carousel slides
                              <div className="cs-nested-list">
                                {val.map((item: any, i: number) => (
                                  <div key={i} className="cs-nested-item">
                                    {typeof item === 'object'
                                      ? Object.entries(item).map(([sk, sv]) => (
                                          <div key={sk} className="cs-nested-field">
                                            <strong>{sk.replace(/_/g, ' ')}:</strong> {String(sv)}
                                          </div>
                                        ))
                                      : String(item)
                                    }
                                  </div>
                                ))}
                              </div>
                            ) : (
                              val.join(', ')
                            )
                          ) : (
                            String(val)
                          )}
                        </span>
                      </div>
                    ))}
                  </div>

                  {v.rationale_text && (
                    <div className="cs-variant-rationale">
                      {v.rationale_text}
                    </div>
                  )}

                  {/* Score Breakdown */}
                  {v.score_breakdown_json && Object.keys(v.score_breakdown_json).length > 0 && (
                    <div className="cs-score-breakdown">
                      {Object.entries(v.score_breakdown_json)
                        .filter(([k]) => k !== 'total')
                        .map(([k, val]) => {
                          const maxVal = SCORE_MAXES[k] || 10;
                          const numVal = typeof val === 'number' ? val : 0;
                          const pct = Math.min((numVal / maxVal) * 100, 100);
                          return (
                            <div key={k} className="cs-score-item">
                              <div className="cs-score-label-row">
                                <span className="cs-score-name">{k.replace(/_/g, ' ')}</span>
                                <span className="cs-score-value">{numVal.toFixed(0)}/{maxVal}</span>
                              </div>
                              <div className="cs-score-bar">
                                <div className="cs-score-bar-fill" style={{ width: `${pct}%` }} />
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  )}

                  <button
                    className={`cs-lock-btn ${isLocked ? 'locked' : ''}`}
                    onClick={() => handleLock(v.channel, v.id)}
                  >
                    {isLocked ? (
                      <><CheckCircle size={14} /> Locked</>
                    ) : (
                      <><Lock size={14} /> Lock as Final</>
                    )}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
