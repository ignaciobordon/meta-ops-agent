/* ── Shared formatting utilities ─────────────────────────────────────────── */

export function fmt$(v: number, decimals?: number) {
  if (v >= 1_000_000) return `$${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `$${(v / 1_000).toFixed(1)}K`;
  const d = decimals ?? (v < 10 ? 2 : 0);
  return `$${v.toFixed(d)}`;
}

export function fmtN(v: number) {
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toLocaleString();
}

export function trendArrow(val: number | null) {
  if (val === null || val === undefined) return '';
  if (val > 0) return `+${val}%`;
  if (val < 0) return `${val}%`;
  return '0%';
}

export function trendClass(val: number | null, invert?: boolean) {
  if (val === null || val === undefined) return '';
  const positive = invert ? val < 0 : val > 0;
  const negative = invert ? val > 0 : val < 0;
  if (positive) return 'trend-up';
  if (negative) return 'trend-down';
  return '';
}

export const DATE_PRESETS = [
  { label: '7d', days: 7 },
  { label: '14d', days: 14 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '365d', days: 365 },
  { label: 'All', days: 730 },
];
