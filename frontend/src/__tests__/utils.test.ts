import { describe, expect, it } from 'vitest';
import { authReducer, loggedOut, tokensReceived } from '@/store/authSlice';
import { liveAlertReceived, toggleTheme, uiReducer } from '@/store/uiSlice';
import { timeAgo } from '@/utils/formatDate';
import { formatBytes, formatNumber, formatPct } from '@/utils/formatNumber';
import { passwordSchema, ruleSchema } from '@/utils/validators';

describe('formatNumber', () => {
  it('adapts precision to magnitude', () => {
    expect(formatNumber(0.12345)).toBe('0.123');
    expect(formatNumber(98.765)).toBe('98.8');
    expect(formatNumber(48210.4, 'm3')).toBe('48,210 m3');
    expect(formatNumber(2_500_000)).toBe('2.50M');
    expect(formatNumber(null)).toBe('—');
  });
  it('formats percentages and bytes', () => {
    expect(formatPct(3.21)).toBe('+3.2%');
    expect(formatPct(-1)).toBe('-1.0%');
    expect(formatBytes(2048)).toBe('2 KB');
  });
});

describe('timeAgo', () => {
  it('renders relative times', () => {
    const now = Date.parse('2026-01-01T12:00:00Z');
    expect(timeAgo('2026-01-01T11:59:30Z', now)).toBe('30s ago');
    expect(timeAgo('2026-01-01T11:00:00Z', now)).toBe('1 h ago');
  });
});

describe('validators', () => {
  it('enforces the password policy', () => {
    expect(passwordSchema.safeParse('short').success).toBe(false);
    expect(passwordSchema.safeParse('longenoughbutnodigits').success).toBe(false);
    expect(passwordSchema.safeParse('Welcome12345').success).toBe(true);
  });
  it('requires a threshold or a range for threshold rules', () => {
    const base = { name: 'Bearing', rule_type: 'threshold', severity: 'major', tag_id: '7c9e6679-7425-40de-944b-e07fc1f90ae7' };
    expect(ruleSchema.safeParse({ ...base, operator: 'greater_than' }).success).toBe(false);
    expect(ruleSchema.safeParse({ ...base, operator: 'greater_than', value: 85 }).success).toBe(true);
    expect(ruleSchema.safeParse({ ...base, operator: 'outside_range', low: 6.5 }).success).toBe(false);
  });
});

describe('store slices', () => {
  it('stores and clears tokens', () => {
    let s = authReducer(undefined, tokensReceived({ access_token: 'a', refresh_token: 'r', token_type: 'bearer', expires_in: 3600 }));
    expect(s.accessToken).toBe('a');
    s = authReducer(s, loggedOut());
    expect(s.accessToken).toBeNull();
  });
  it('dedupes live alerts and toggles theme', () => {
    let s = uiReducer(undefined, liveAlertReceived({ alert_id: '1', title: 'x', severity: 'critical', status: 'triggered', asset_id: null }));
    s = uiReducer(s, liveAlertReceived({ alert_id: '1', title: 'x', severity: 'critical', status: 'acknowledged', asset_id: null }));
    expect(s.liveAlerts).toHaveLength(1);
    expect(uiReducer(s, toggleTheme()).themeMode).not.toBe(s.themeMode);
  });
});
