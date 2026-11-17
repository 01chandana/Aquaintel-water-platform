import { Box, Grid, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import { useKpiCurrentQuery, useKpiQuery } from '@/api/kpiApi';
import { BandBar } from '@/components/charts/BandBar';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { LoadFailed, Loading } from '@/components/common/States';
import { KpiTrendPanel } from '@/features/dashboard/KpiTrendPanel';
import { useAppSelector } from '@/store';
import { formatDateTime } from '@/utils/formatDate';
import { formatNumber, formatPct } from '@/utils/formatNumber';

export default function KpiDetailPage() {
  const { id = '' } = useParams();
  const siteId = useAppSelector((s) => s.ui.siteId);
  const { data: kpi, error, refetch } = useKpiQuery(id);
  const { data: cur } = useKpiCurrentQuery({ id, asset_id: siteId ?? undefined });
  if (error && !kpi) return <LoadFailed error={error} what="KPI" backTo={{ label: 'Back to KPI explorer', href: '/analytics/kpis' }} onRetry={refetch} />;
  if (!kpi) return <Loading />;
  const row = (label: string, value: React.ReactNode) => (
    <Box sx={{ display: 'contents' }}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="body2">{value}</Typography></Box>
  );
  return (
    <>
      <PageHeader title={`${kpi.number ? `${kpi.number}. ` : ''}${kpi.name}`} description={kpi.description ?? undefined} />
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Panel title="Current value" subtitle={cur?.time ? `Computed ${formatDateTime(cur.time)}` : 'No value yet'}>
            <Typography sx={{ fontSize: 34, fontWeight: 600 }}>{formatNumber(cur?.value ?? null, kpi.unit)}</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {cur?.status ?? '—'} · {formatPct(cur?.trend_pct ?? null)} vs 24 h earlier
            </Typography>
            <BandBar value={cur?.value ?? null} warning={kpi.threshold_warning} critical={kpi.threshold_critical} higherIsBetter={kpi.higher_is_better} height={8} />
          </Panel>
          <Panel title="Definition" sx={{ mt: 2 }}>
            <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.75 }}>
              {row('Formula', kpi.formula)}
              {row('Unit', kpi.unit)}
              {row('Category', kpi.category)}
              {row('Aggregation', kpi.aggregation_type)}
              {row('Better when', kpi.higher_is_better ? 'higher' : 'lower')}
              {row('Warning', kpi.threshold_warning ?? '—')}
              {row('Critical', kpi.threshold_critical ?? '—')}
              {row('Visualization', kpi.visualization ?? '—')}
              {row('Alert condition', kpi.alert_condition ?? '—')}
            </Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={8}><KpiTrendPanel code={kpi.code} days={7} height={380} /></Grid>
      </Grid>
    </>
  );
}
