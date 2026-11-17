import { ToggleButton, ToggleButtonGroup } from '@mui/material';
import { useMemo, useState } from 'react';
import { useKpisQuery, useKpiValuesQuery } from '@/api/kpiApi';
import { LineChart } from '@/components/charts/LineChart';
import { Panel } from '@/components/common/Panel';
import { EmptyState, PanelSkeleton } from '@/components/common/States';
import { useAppSelector } from '@/store';
import { hoursAgo } from '@/utils/formatDate';

/** KPI trend with its warning/critical threshold lines (Ch. 8.5.4 "threshold visualization"). */
export function KpiTrendPanel({ code, title, days = 7, height = 240 }: { code: string; title?: string; days?: number; height?: number }) {
  const [range, setRange] = useState(days);
  const siteId = useAppSelector((s) => s.ui.siteId);
  const { data: defs } = useKpisQuery();
  const kpi = defs?.find((d) => d.code === code);
  // the window is fixed per range selection; recomputing it on every render would change the cache key and refetch
  const window = useMemo(() => ({ start: hoursAgo(range * 24), end: new Date().toISOString() }), [range]);
  const { data, isLoading } = useKpiValuesQuery(
    { id: kpi?.id ?? '', ...window, asset_id: siteId ?? undefined, bucket: range > 14 ? 'day' : undefined },
    { skip: !kpi, pollingInterval: 300_000 },
  );
  const rows = useMemo(() => (data ?? []).map((v) => ({ time: v.time, value: v.value })), [data]);
  const thresholds = kpi
    ? [
        ...(kpi.threshold_warning !== null ? [{ value: kpi.threshold_warning, label: 'Warning', level: 'warning' as const }] : []),
        ...(kpi.threshold_critical !== null ? [{ value: kpi.threshold_critical, label: 'Critical', level: 'critical' as const }] : []),
      ]
    : [];
  return (
    <Panel title={title ?? kpi?.name ?? code} subtitle={kpi ? `${kpi.formula} · ${kpi.unit}` : undefined}
      actions={
        <ToggleButtonGroup size="small" exclusive value={range} onChange={(_, v) => v && setRange(v)} aria-label="Time range">
          <ToggleButton value={1}>24 h</ToggleButton>
          <ToggleButton value={7}>7 d</ToggleButton>
          <ToggleButton value={14}>14 d</ToggleButton>
        </ToggleButtonGroup>
      }>
      {isLoading || !kpi ? <PanelSkeleton height={height} /> : rows.length ? (
        <LineChart data={rows} series={[{ key: 'value', label: kpi.name }]} unit={kpi.unit} height={height} thresholds={thresholds} />
      ) : <EmptyState title="No values in this range" hint="KPIs are computed hourly by the KPI engine." />}
    </Panel>
  );
}
