import { useTheme } from '@mui/material';
import { Area, AreaChart, ResponsiveContainer } from 'recharts';
import { tokens } from '@/theme/palette';

/** Compact sparkline used inside KPI tiles. */
export function TrendChart({ values, status, height = 34 }: { values: number[]; status: string; height?: number }) {
  const theme = useTheme();
  if (values.length < 2) return null;
  const color = status === 'critical' ? tokens.alarm.critical : status === 'warning' ? tokens.alarm.major : theme.palette.text.secondary;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.2} fill={color} fillOpacity={0.08} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}
