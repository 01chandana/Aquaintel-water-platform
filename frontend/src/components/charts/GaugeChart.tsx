import { Box, Typography, useTheme } from '@mui/material';
import { tokens } from '@/theme/palette';
import { formatNumber } from '@/utils/formatNumber';

interface Props {
  value: number | null;
  min?: number;
  max: number;
  warning: number | null;
  critical: number | null;
  higherIsBetter: boolean;
  unit?: string;
  label: string;
}

/** Semi-circular gauge with green/yellow/red zones (KPI 1 / 21 visualization guidance). */
export function GaugeChart({ value, min = 0, max, warning, critical, higherIsBetter, unit, label }: Props) {
  const theme = useTheme();
  const r = 70;
  const angle = (v: number) => Math.PI * (1 - (Math.min(max, Math.max(min, v)) - min) / (max - min));
  const pt = (a: number, rad = r) => [80 + rad * Math.cos(a), 84 - rad * Math.sin(a)];
  const arc = (from: number, to: number) => {
    const [x1, y1] = pt(angle(from));
    const [x2, y2] = pt(angle(to));
    return `M ${x1} ${y1} A ${r} ${r} 0 0 1 ${x2} ${y2}`;
  };
  const zones = warning !== null && critical !== null
    ? higherIsBetter
      ? [{ a: min, b: critical, c: tokens.alarm.critical }, { a: critical, b: warning, c: tokens.alarm.major }, { a: warning, b: max, c: theme.palette.text.secondary }]
      : [{ a: min, b: warning, c: theme.palette.text.secondary }, { a: warning, b: critical, c: tokens.alarm.major }, { a: critical, b: max, c: tokens.alarm.critical }]
    : [{ a: min, b: max, c: theme.palette.text.secondary }];
  const [nx, ny] = value !== null ? pt(angle(value), r - 14) : [80, 84];
  return (
    <Box sx={{ textAlign: 'center' }}>
      <svg viewBox="0 0 160 96" width="100%" style={{ maxWidth: 220 }} role="img" aria-label={`${label}: ${formatNumber(value, unit)}`}>
        {zones.map((z, i) => <path key={i} d={arc(z.a, z.b)} stroke={z.c} strokeOpacity={z.c === theme.palette.text.secondary ? 0.35 : 0.8} strokeWidth={10} fill="none" />)}
        {value !== null && <line x1={80} y1={84} x2={nx} y2={ny} stroke={theme.palette.text.primary} strokeWidth={2.5} strokeLinecap="round" />}
        <circle cx={80} cy={84} r={4} fill={theme.palette.text.primary} />
      </svg>
      <Typography variant="h3" component="p" sx={{ mt: -1 }}>{formatNumber(value, unit)}</Typography>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Box>
  );
}
