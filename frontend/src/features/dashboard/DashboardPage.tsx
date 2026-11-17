import { Refresh } from '@mui/icons-material';
import { Box, Button, Grid, Table, TableBody, TableCell, TableHead, TableRow, Typography } from '@mui/material';
import { useParams } from 'react-router-dom';
import { useComputeKpisMutation, useDashboardKpisQuery, useHealthHeatmapQuery, type DashboardView } from '@/api/kpiApi';
import { useWorkOrdersQuery } from '@/api/operationsApi';
import { useComplianceDailyQuery, useExceedancesQuery } from '@/api/reportApi';
import { HeatMap } from '@/components/charts/HeatMap';
import { StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, ErrorState, PanelSkeleton } from '@/components/common/States';
import { AlertList } from '@/components/widgets/AlertList';
import { KpiCard } from '@/components/widgets/KpiCard';
import { TelemetryTable } from '@/components/widgets/TelemetryTable';
import { usePermissions } from '@/hooks/usePermissions';
import { usePolling } from '@/hooks/usePolling';
import { useAppSelector } from '@/store';
import { formatDateTime, formatDay } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';
import { KpiTrendPanel } from './KpiTrendPanel';

const VIEWS: Record<DashboardView, { title: string; description: string }> = {
  executive: { title: 'Executive overview', description: 'Availability, quality, energy and cost across the network, with anything that needs attention first.' },
  operations: { title: 'Operations', description: 'Real-time asset status, live telemetry and active alerts for the shift.' },
  energy: { title: 'Energy', description: 'Pump energy, efficiency against best-efficiency point and time-of-use cost.' },
  quality: { title: 'Water quality', description: 'Disinfection residual, turbidity, pH and by-product risk against regulatory limits.' },
  maintenance: { title: 'Maintenance', description: 'Equipment health, reliability KPIs and open work.' },
  compliance: { title: 'Compliance', description: 'Regulatory compliance KPIs.' },
};

export default function DashboardPage() {
  const view = (useParams().view ?? 'executive') as DashboardView;
  const siteId = useAppSelector((s) => s.ui.siteId);
  const { can } = usePermissions();
  const { data, isLoading, error, refetch } = useDashboardKpisQuery({ view, site_id: siteId }, { pollingInterval: usePolling(60_000, 120_000) });
  const [compute, computeState] = useComputeKpisMutation();
  const meta = VIEWS[view] ?? VIEWS.executive;
  return (
    <>
      <PageHeader title={meta.title} description={meta.description}
        actions={can('kpis:write') && <Button size="small" startIcon={<Refresh />} disabled={computeState.isLoading} onClick={() => compute()}>Recompute KPIs</Button>} />
      {error && <ErrorState error={error} onRetry={refetch} />}
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        {isLoading && Array.from({ length: 6 }).map((_, i) => <Grid item xs={12} sm={6} md={4} lg={view === 'executive' ? 3 : 4} xl={view === 'executive' ? 3 : 2} key={i}><PanelSkeleton height={130} /></Grid>)}
        {data?.map((k) => (
          <Grid item xs={12} sm={6} md={4} lg={view === 'executive' ? 3 : 4} xl={view === 'executive' ? 3 : 2} key={k.kpi.code}><KpiCard item={k} /></Grid>
        ))}
      </Grid>
      <ViewPanels view={view} />
    </>
  );
}

function ViewPanels({ view }: { view: DashboardView }) {
  switch (view) {
    case 'operations':
      return (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={7}><Panel title="Live flow and pressure" subtitle="Pushed over WebSocket as samples arrive"><TelemetryTable parameter="flow" height={300} /></Panel></Grid>
          <Grid item xs={12} lg={5}><Panel title="Active alerts"><AlertList limit={9} /></Panel></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="PRESSURE_STABILITY_INDEX" days={1} /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="FLOW_RATE_EFFICIENCY" days={1} /></Grid>
        </Grid>
      );
    case 'energy':
      return (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="SPECIFIC_ENERGY_CONSUMPTION" /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="PUMP_EFFICIENCY_INDEX" /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="MAXIMUM_DEMAND_UTILIZATION" /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="ENERGY_COST_INTENSITY" /></Grid>
        </Grid>
      );
    case 'quality':
      return (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="WATER_QUALITY_INDEX" /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="CHLORINE_RESIDUAL_COMPLIANCE" /></Grid>
          <Grid item xs={12} lg={6}><Panel title="Live chlorine residual"><TelemetryTable parameter="chlorine" height={260} /></Panel></Grid>
          <Grid item xs={12} lg={6}><ExceedancePanel /></Grid>
        </Grid>
      );
    case 'maintenance':
      return (
        <Grid container spacing={2}>
          <Grid item xs={12}><HealthHeatmapPanel /></Grid>
          <Grid item xs={12} lg={7}><OpenWorkPanel /></Grid>
          <Grid item xs={12} lg={5}><Panel title="Predictive maintenance alerts" subtitle="Raised by the pump failure and anomaly models"><AlertList limit={6} /></Panel></Grid>
        </Grid>
      );
    default:
      return (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={8}><KpiTrendPanel code="PRODUCTION_VOLUME" title="Production volume (rolling 24 h)" /></Grid>
          <Grid item xs={12} lg={4}><Panel title="Critical and major alerts"><AlertList severity="critical,major" limit={7} /></Panel></Grid>
          <Grid item xs={12} lg={6}><CompliancePanel /></Grid>
          <Grid item xs={12} lg={6}><KpiTrendPanel code="OM_COST_PER_UNIT" /></Grid>
        </Grid>
      );
  }
}

function CompliancePanel() {
  const { data, isLoading } = useComplianceDailyQuery();
  return (
    <Panel title="Today's compliance" subtitle={data?.overall_compliance_pct !== undefined ? `${formatNumber(data?.overall_compliance_pct)}% of samples within limits` : undefined}>
      {isLoading ? <PanelSkeleton /> : (
        <Table size="small">
          <TableHead><TableRow><TableCell>Parameter</TableCell><TableCell align="right">Samples</TableCell><TableCell align="right">Exceedances</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
          <TableBody>
            {data?.parameters.map((p) => (
              <TableRow key={p.parameter}>
                <TableCell>{p.display_name}</TableCell>
                <TableCell align="right">{p.samples}</TableCell>
                <TableCell align="right">{p.exceedances}</TableCell>
                <TableCell><StatusChip status={p.status === 'compliant' ? 'resolved' : 'triggered'} /></TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </Panel>
  );
}

function ExceedancePanel() {
  const { data } = useExceedancesQuery();
  return (
    <Panel title="Recent exceedances" subtitle="Samples outside regulatory limits (30 days)">
      {!data?.length ? <EmptyState title="No exceedances in the last 30 days" /> : (
        <Box sx={{ maxHeight: 280, overflow: 'auto' }}>
          <Table size="small">
            <TableBody>
              {data.slice(0, 40).map((e, i) => (
                <TableRow key={i}>
                  <TableCell>{formatDateTime(e.time)}</TableCell>
                  <TableCell>{e.asset_name}</TableCell>
                  <TableCell>{e.parameter}</TableCell>
                  <TableCell align="right" sx={{ color: 'error.main', fontWeight: 600 }}>{formatNumber(e.value, e.unit)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Box>
      )}
    </Panel>
  );
}

function HealthHeatmapPanel() {
  const { data, isLoading } = useHealthHeatmapQuery();
  const cells = (data ?? []).map((d) => ({ row: d.asset, col: d.time.slice(0, 13), value: d.value }));
  return (
    <Panel title="Equipment health score" subtitle="Hourly composite of vibration, bearing temperature, efficiency, service age and open alerts (KPI 22)">
      {isLoading ? <PanelSkeleton height={260} /> : cells.length ? (
        <HeatMap cells={cells} height={Math.max(180, new Set(cells.map((c) => c.row)).size * 28 + 40)} formatCol={(c) => formatDay(`${c}:00:00Z`)} label="Equipment health heat map" />
      ) : <EmptyState title="No health scores yet" />}
    </Panel>
  );
}

function OpenWorkPanel() {
  const { data } = useWorkOrdersQuery({ status: 'open,assigned,in_progress', per_page: 8 });
  return (
    <Panel title="Open work orders" subtitle={data ? `${data.meta.total} open` : undefined}>
      <Table size="small">
        <TableBody>
          {data?.items.map((w) => (
            <TableRow key={w.id}>
              <TableCell sx={{ whiteSpace: 'nowrap' }}>{w.number}</TableCell>
              <TableCell><Typography variant="body2" noWrap sx={{ maxWidth: 280 }}>{w.title}</Typography></TableCell>
              <TableCell>{w.asset_name}</TableCell>
              <TableCell><StatusChip status={w.status} /></TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Panel>
  );
}
