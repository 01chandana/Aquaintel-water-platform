// The API sends UTC instants with an explicit offset (ISO-8601); they are shown in the viewer's own time
// zone (QA audit AQ-013). The header shows which zone that is, so a screenshot is never ambiguous.
const dtf = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
const tf = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit' });
const df = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' });

/** Short name of the viewer's time zone, e.g. "IST" or "GMT+5:30". */
export const localZoneLabel = (): string =>
  new Intl.DateTimeFormat(undefined, { timeZoneName: 'short' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value ?? '';

export const formatDateTime = (iso?: string | null): string => (iso ? dtf.format(new Date(iso)) : '—');
export const formatTime = (iso?: string | number | null): string => (iso ? tf.format(new Date(iso)) : '—');
export const formatDay = (iso?: string | number | null): string => (iso ? df.format(new Date(iso)) : '—');

export function timeAgo(iso?: string | null, now = Date.now()): string {
  if (!iso) return '—';
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

export const hoursAgo = (h: number): string => new Date(Date.now() - h * 3600_000).toISOString();
