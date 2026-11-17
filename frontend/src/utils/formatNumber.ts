/** Number formatting that adapts precision to magnitude so tiles stay readable. */
export function formatNumber(v: number | null | undefined, unit?: string): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  const abs = Math.abs(v);
  const digits = abs >= 1000 ? 0 : abs >= 100 ? 1 : abs >= 10 ? 1 : abs >= 1 ? 2 : 3;
  const s = abs >= 1_000_000 ? `${(v / 1_000_000).toFixed(2)}M` : v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: 0 });
  return unit ? `${s} ${unit}` : s;
}

export const formatPct = (v: number | null | undefined, digits = 1): string =>
  v === null || v === undefined ? '—' : `${v > 0 ? '+' : ''}${v.toFixed(digits)}%`;

export const formatBytes = (n?: number | null): string =>
  !n ? '—' : n > 1_048_576 ? `${(n / 1_048_576).toFixed(1)} MB` : `${Math.ceil(n / 1024)} KB`;
