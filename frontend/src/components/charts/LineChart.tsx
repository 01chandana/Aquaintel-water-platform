import { useTheme } from '@mui/material';
import { useMemo } from 'react';
import { Brush, CartesianGrid, Legend, Line, LineChart as RLineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { seriesColors, tokens } from '@/theme/palette';
import { formatDateTime, formatDay, formatTime } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export interface Series {
  key: string;
  label: string;
  color?: string;
  dashed?: boolean;
}

interface Props {
  data: Record<string, number | string | null>[];
  series: Series[];
  xKey?: string;
  height?: number;
  unit?: string;
  thresholds?: { value: number; label: string; level: 'warning' | 'critical' }[];
  band?: { from: number; to: number; label: string };
  brush?: boolean;
  showLegend?: boolean;
}

/** Time-series line chart with crosshair tooltip, brush zoom and threshold lines (Ch. 4.3.4). */
export function LineChart({ data, series, xKey = 'time', height = 260, unit, thresholds, band, brush, showLegend }: Props) {
  const theme = useTheme();
  const axis = { stroke: theme.palette.text.secondary, fontSize: 11 };
  const memo = useMemo(() => data, [data]); // chart memoisation (Ch. 8.10)
  // ticks show the date once the window is longer than a day and a half, otherwise the clock time
  const tick = useMemo(() => {
    const first = Date.parse(String(data[0]?.[xKey] ?? ''));
    const last = Date.parse(String(data[data.length - 1]?.[xKey] ?? ''));
    const multiDay = Math.abs(last - first) > 36 * 3600_000;
    return (v: string | number) => (multiDay ? formatDay(v) : formatTime(v));
  }, [data, xKey]);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <RLineChart data={memo} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={theme.palette.divider} vertical={false} />
        <XAxis dataKey={xKey} tickFormatter={tick} tick={axis} stroke={theme.palette.divider} minTickGap={40} />
        <YAxis tick={axis} stroke={theme.palette.divider} width={52} tickFormatter={(v) => formatNumber(v)} domain={['auto', 'auto']} />
        <Tooltip
          contentStyle={{ background: theme.palette.background.paper, border: `1px solid ${theme.palette.divider}`, fontSize: 12 }}
          labelFormatter={(v) => formatDateTime(String(v))}
          formatter={(v: number, name: string) => [formatNumber(v, unit), name]}
          cursor={{ stroke: theme.palette.text.secondary, strokeDasharray: '3 3' }}
        />
        {showLegend && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {band && <ReferenceArea y1={band.from} y2={band.to} fill={tokens.brand} fillOpacity={0.06} label={{ value: band.label, fontSize: 10, fill: theme.palette.text.secondary, position: 'insideTopLeft' }} />}
        {thresholds?.map((t) => (
          <ReferenceLine key={t.label} y={t.value} stroke={t.level === 'critical' ? tokens.alarm.critical : tokens.alarm.major} strokeDasharray="4 4"
            label={{ value: t.label, fontSize: 10, fill: theme.palette.text.secondary, position: 'insideTopRight' }} />
        ))}
        {series.map((s, i) => (
          <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color ?? seriesColors[i % seriesColors.length]}
            strokeWidth={1.6} dot={false} strokeDasharray={s.dashed ? '5 4' : undefined} isAnimationActive={false} connectNulls />
        ))}
        {brush && <Brush dataKey={xKey} height={18} stroke={theme.palette.divider} tickFormatter={tick} />}
      </RLineChart>
    </ResponsiveContainer>
  );
}
