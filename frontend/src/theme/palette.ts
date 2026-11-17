/**
 * Design tokens. ISA-101 "high-performance HMI" principle: the normal state is calm and
 * grey; colour is reserved for abnormal conditions so an alarm is never lost in decoration.
 */
export const tokens = {
  dark: {
    basin: '#0E1A22', // page background - deep water, not black
    surface: '#15252F',
    raised: '#1B2F3B',
    rule: '#23394A',
    ink: '#E3ECEF',
    inkMuted: '#8FA6B2',
  },
  light: {
    basin: '#F4F7F8', // lab paper
    surface: '#FFFFFF',
    raised: '#EEF3F5',
    rule: '#D5E0E5',
    ink: '#0F2A36',
    inkMuted: '#5A7380',
  },
  brand: '#3FC1C9', // chlorine cyan - interaction & identity only
  brandDeep: '#1D8C94',
  alarm: {
    critical: '#E5484D',
    major: '#F2994A',
    minor: '#E9C46A',
    warning: '#E9C46A',
    info: '#6FA8DC',
    normal: '#7C939F',
  },
} as const;

export type Severity = 'critical' | 'major' | 'minor' | 'warning' | 'info';

export const severityColor = (s?: string | null): string =>
  (tokens.alarm as Record<string, string>)[s ?? 'normal'] ?? tokens.alarm.normal;

export const statusColor = (s?: string | null): string =>
  s === 'critical' ? tokens.alarm.critical : s === 'warning' ? tokens.alarm.major : tokens.alarm.normal;

/** Categorical series colours for charts: desaturated so they never compete with alarm colours. */
export const seriesColors = ['#3FC1C9', '#9DB4C0', '#6FA8DC', '#B7A6D6', '#7FC8A9', '#C9B79C'];
