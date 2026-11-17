import { Box, Chip, Grid, MenuItem, Tab, Tabs, TextField, Typography } from '@mui/material';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAssetAlertsQuery, useAssetKpisQuery, useAssetQuery, useAssetTelemetryQuery, useAssetWorkOrdersQuery, useUpdateAssetMutation } from '@/api/assetApi';
import { LineChart } from '@/components/charts/LineChart';
import { SeverityChip, StatusChip } from '@/components/common/Chips';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, LoadFailed, Loading } from '@/components/common/States';
import { TelemetryTable } from '@/components/widgets/TelemetryTable';
import { usePermissions } from '@/hooks/usePermissions';
import { onTelemetry } from '@/hooks/useWebSocket';
import type { Alert, Tag, WorkOrder } from '@/types/models';
import { formatDateTime, hoursAgo } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function AssetDetailPage() {
  const { id = '' } = useParams();
  const [tab, setTab] = useState(0);
  const { data: asset, isLoading, error, refetch } = useAssetQuery(id);
  const [update] = useUpdateAssetMutation();
  const [confirm, setConfirm] = useState<'maintenance' | 'active' | null>(null);
  const { can } = usePermissions();
  if (error && !asset) return <LoadFailed error={error} what="Asset" backTo={{ label: 'Back to assets', href: '/assets' }} onRetry={refetch} />;
  if (isLoading || !asset) return <Loading />;
  const meta = Object.entries(asset.metadata ?? {});
  return (
    <>
      <PageHeader title={asset.name} description={`${asset.asset_type?.name ?? ''} · ${asset.path}`}
        actions={can('assets:maintenance') && (
          <TextField select size="small" label="Status" value={asset.status} sx={{ minWidth: 170 }}
            onChange={(e) => setConfirm(e.target.value as 'maintenance' | 'active')}>
            <MenuItem value="active">Active</MenuItem>
            <MenuItem value="maintenance">In maintenance</MenuItem>
            <MenuItem value="inactive">Inactive</MenuItem>
          </TextField>
        )} />
      <ConfirmDialog open={!!confirm} title="Change asset status" confirmLabel="Change status"
        body={confirm === 'maintenance' ? 'Alerts for this asset are suppressed while it is in maintenance.' : 'Alert evaluation resumes for this asset.'}
        onClose={() => setConfirm(null)} onConfirm={() => confirm && update({ id, body: { status: confirm } })} />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Overview" /><Tab label="Telemetry" /><Tab label="KPIs" /><Tab label="Alerts" /><Tab label="Work orders" />
      </Tabs>
      {tab === 0 && (
        <Grid container spacing={2}>
          <Grid item xs={12} md={5}>
            <Panel title="Details">
              <Box sx={{ display: 'grid', gridTemplateColumns: 'auto 1fr', columnGap: 2, rowGap: 0.75, fontSize: 13 }}>
                <Typography variant="body2" color="text.secondary">Status</Typography><Box><StatusChip status={asset.status} /></Box>
                <Typography variant="body2" color="text.secondary">External id</Typography><Typography variant="body2">{asset.external_id}</Typography>
                <Typography variant="body2" color="text.secondary">Commissioned</Typography><Typography variant="body2">{asset.commissioned_at ?? '—'}</Typography>
                <Typography variant="body2" color="text.secondary">Warranty until</Typography><Typography variant="body2">{asset.warranty_until ?? '—'}</Typography>
                {meta.map(([k, v]) => (
                  <Box key={k} sx={{ display: 'contents' }}>
                    <Typography variant="body2" color="text.secondary">{k.replace(/_/g, ' ')}</Typography>
                    <Typography variant="body2">{String(v)}</Typography>
                  </Box>
                ))}
              </Box>
            </Panel>
          </Grid>
          <Grid item xs={12} md={7}><Panel title="Live values"><TelemetryTable assetId={id} height={340} /></Panel></Grid>
        </Grid>
      )}
      {tab === 1 && <TelemetryTab assetId={id} tags={asset.tags ?? []} />}
      {tab === 2 && <KpiTab assetId={id} />}
      {tab === 3 && <AlertsTab assetId={id} />}
      {tab === 4 && <WorkOrdersTab assetId={id} />}
    </>
  );
}

function TelemetryTab({ assetId, tags }: { assetId: string; tags: Tag[] }) {
  const params = tags.map((t) => t.parameter);
  const [param, setParam] = useState(params[0] ?? '');
  const [hours, setHours] = useState(24);
  const tag = tags.find((t) => t.parameter === param);
  const start = useMemo(() => hoursAgo(hours), [hours]);
  const { data, isFetching } = useAssetTelemetryQuery({ id: assetId, parameter: param, start, interval: hours > 48 ? '1h' : undefined }, { skip: !param });
  const [live, setLive] = useState<{ time: string; value: number }[]>([]);
  useEffect(() => { setLive([]); }, [param, hours]);
  useEffect(() => onTelemetry((pts) => {
    const mine = pts.filter((p) => p.tag_id === tag?.id);
    if (mine.length) setLive((prev) => [...prev, ...mine.map((p) => ({ time: p.time, value: p.value }))].slice(-500));
  }), [tag?.id]);
  const rows = useMemo(() => [
    ...(data?.points ?? []).map((p: { bucket?: string; time: string; avg_value?: number; value: number }) => ({ time: p.bucket ?? p.time, value: p.avg_value ?? p.value })),
    ...live,
  ], [data, live]);
  return (
    <Panel title={tag?.name ?? 'Telemetry'} subtitle={hours > 48 ? 'Hourly averages from the continuous aggregate' : 'Raw samples, extended live as new data arrives'}
      actions={<Box sx={{ display: 'flex', gap: 1 }}>
        <TextField select size="small" label="Signal" value={param} onChange={(e) => setParam(e.target.value)} sx={{ minWidth: 200 }}>
          {params.map((p) => <MenuItem key={p} value={p}>{p.replace(/_/g, ' ')}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Range" value={hours} onChange={(e) => setHours(Number(e.target.value))}>
          {[6, 24, 72, 168, 720].map((h) => <MenuItem key={h} value={h}>{h < 72 ? `${h} h` : `${h / 24} d`}</MenuItem>)}
        </TextField>
      </Box>}>
      {isFetching && !rows.length ? <Loading /> : rows.length ? (
        <LineChart data={rows} series={[{ key: 'value', label: tag?.name ?? param }]} unit={tag?.unit} height={340} brush />
      ) : <EmptyState title="No samples in this range" />}
    </Panel>
  );
}

function KpiTab({ assetId }: { assetId: string }) {
  const { data } = useAssetKpisQuery(assetId);
  if (!data?.length) return <Panel><EmptyState title="No asset-level KPIs" hint="Asset KPIs (pump efficiency, health score) are computed for pumps; site KPIs are on the dashboards." /></Panel>;
  return (
    <Grid container spacing={1.5}>
      {data.map((k) => (
        <Grid item xs={12} sm={6} md={4} key={k.code}>
          <Panel title={k.name} subtitle={formatDateTime(k.time)}>
            <Typography sx={{ fontSize: 26, fontWeight: 600 }}>{formatNumber(k.value, k.unit)}</Typography>
            <Chip size="small" label={k.status} color={k.status === 'critical' ? 'error' : k.status === 'warning' ? 'warning' : 'default'} sx={{ mt: 1 }} />
          </Panel>
        </Grid>
      ))}
    </Grid>
  );
}

function AlertsTab({ assetId }: { assetId: string }) {
  const nav = useNavigate();
  const { data, error, refetch } = useAssetAlertsQuery(assetId);
  return (
    <Panel>
      <DataTable<Alert> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(a) => a.id} onRowClick={(a) => nav(`/alerts/${a.id}`)} dense columns={[
        { key: 'sev', label: 'Severity', render: (a) => <SeverityChip severity={a.severity} /> },
        { key: 'title', label: 'Alert', render: (a) => a.title },
        { key: 'status', label: 'Status', render: (a) => <StatusChip status={a.status} /> },
        { key: 'time', label: 'Raised', render: (a) => formatDateTime(a.created_at) },
      ]} />
    </Panel>
  );
}

function WorkOrdersTab({ assetId }: { assetId: string }) {
  const { data, error, refetch } = useAssetWorkOrdersQuery(assetId);
  return (
    <Panel>
      <DataTable<WorkOrder> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(w) => w.id} dense columns={[
        { key: 'n', label: 'Number', render: (w) => w.number },
        { key: 't', label: 'Title', render: (w) => w.title },
        { key: 'type', label: 'Type', render: (w) => w.wo_type },
        { key: 's', label: 'Status', render: (w) => <StatusChip status={w.status} /> },
        { key: 'f', label: 'Failure code', render: (w) => w.failure_code ?? '—' },
        { key: 'd', label: 'Created', render: (w) => formatDateTime(w.created_at) },
      ]} />
    </Panel>
  );
}
