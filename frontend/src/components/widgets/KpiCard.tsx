import { Box, Paper, Typography } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { BandBar } from '@/components/charts/BandBar';
import { TrendChart } from '@/components/charts/TrendChart';
import { tokens } from '@/theme/palette';
import type { KpiCurrent } from '@/types/models';
import { formatNumber, formatPct } from '@/utils/formatNumber';

/**
 * KPI tile. Normal values render in neutral ink; only warning/critical states gain colour,
 * through the left status edge, the band-bar marker and the sparkline.
 */
export function KpiCard({ item }: { item: KpiCurrent }) {
  const { kpi, value, status, trend_pct, sparkline } = item;
  const edge = status === 'critical' ? tokens.alarm.critical : status === 'warning' ? tokens.alarm.major : 'transparent';
  const good = trend_pct === null ? null : kpi.higher_is_better ? trend_pct >= 0 : trend_pct <= 0;
  return (
    <Paper component={RouterLink} to={`/analytics/kpis/${kpi.id}`}
      sx={{ p: 1.75, display: 'block', textDecoration: 'none', color: 'inherit', borderLeft: `3px solid ${edge}`, height: '100%',
        '&:hover': { borderColor: 'text.secondary' } }}
      aria-label={`${kpi.name}: ${formatNumber(value, kpi.unit)}, ${status}`}>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 1 }}>
        <Typography variant="body2" color="text.secondary" title={kpi.name}
          sx={{ flex: 1, minHeight: '2.6em', lineHeight: 1.3, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {kpi.name}
        </Typography>
        {status !== 'normal' && status !== 'no_data' && (
          <Typography variant="caption" sx={{ color: edge, fontWeight: 600, textTransform: 'capitalize' }}>{status}</Typography>
        )}
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'baseline', gap: 0.75, mt: 0.5 }}>
        <Typography sx={{ fontSize: '1.625rem', fontWeight: 600, lineHeight: 1.15 }}>{formatNumber(value)}</Typography>
        <Typography variant="body2" color="text.secondary">{kpi.unit}</Typography>
        {trend_pct !== null && (
          <Typography variant="caption" sx={{ ml: 'auto', color: good ? 'text.secondary' : tokens.alarm.major }} title="Change vs 24 h earlier">
            {formatPct(trend_pct)}
          </Typography>
        )}
      </Box>
      <Box sx={{ mt: 1.25 }}>
        <BandBar value={value} warning={kpi.threshold_warning} critical={kpi.threshold_critical} higherIsBetter={kpi.higher_is_better} />
      </Box>
      {sparkline && <Box sx={{ mt: 1 }}><TrendChart values={sparkline} status={status} /></Box>}
    </Paper>
  );
}
