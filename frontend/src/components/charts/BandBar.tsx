import { Box, Tooltip } from '@mui/material';
import { tokens } from '@/theme/palette';

interface Props {
  value: number | null;
  warning: number | null;
  critical: number | null;
  higherIsBetter: boolean;
  height?: number;
}

/**
 * Threshold band bar: where the current value sits relative to the KPI's normal, warning and
 * critical zones. Zones are drawn in muted tones; only the marker carries status colour.
 */
export function BandBar({ value, warning, critical, higherIsBetter, height = 6 }: Props) {
  if (value === null || warning === null || critical === null) return <Box sx={{ height }} />;
  const span = Math.abs(warning - critical) || Math.abs(warning) * 0.2 || 1;
  const lo = Math.min(value, warning, critical) - span * 0.6;
  const hi = Math.max(value, warning, critical) + span * 0.6;
  const pos = (v: number) => ((v - lo) / (hi - lo)) * 100;
  const [w, c] = [pos(warning), pos(critical)];
  const status = higherIsBetter ? (value < critical ? 'critical' : value < warning ? 'warning' : 'normal')
    : (value > critical ? 'critical' : value > warning ? 'warning' : 'normal');
  const marker = status === 'critical' ? tokens.alarm.critical : status === 'warning' ? tokens.alarm.major : tokens.brand;
  const zones = higherIsBetter
    ? [{ from: 0, to: c, o: 0.55 }, { from: c, to: w, o: 0.32 }, { from: w, to: 100, o: 0.12 }]
    : [{ from: 0, to: w, o: 0.12 }, { from: w, to: c, o: 0.32 }, { from: c, to: 100, o: 0.55 }];
  return (
    <Tooltip title={`Warning ${warning} · Critical ${critical}`} placement="top">
      <Box role="img" aria-label={`Value ${value}, status ${status}`} sx={{ position: 'relative', height, borderRadius: height, overflow: 'visible', bgcolor: 'divider' }}>
        {zones.map((z, i) => (
          <Box key={i} sx={{ position: 'absolute', left: `${z.from}%`, width: `${z.to - z.from}%`, top: 0, bottom: 0, bgcolor: 'text.secondary', opacity: z.o,
            borderRadius: i === 0 ? `${height}px 0 0 ${height}px` : i === 2 ? `0 ${height}px ${height}px 0` : 0 }} />
        ))}
        <Box sx={{ position: 'absolute', left: `calc(${pos(value)}% - 2px)`, top: -3, width: 4, height: height + 6, borderRadius: 2, bgcolor: marker }} />
      </Box>
    </Tooltip>
  );
}
