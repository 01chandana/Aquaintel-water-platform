import { Add, Delete, DragIndicator } from '@mui/icons-material';
import { Box, Button, Card, CardActionArea, CardContent, Dialog, DialogActions, DialogContent, DialogTitle, Grid, IconButton, MenuItem, TextField, Typography } from '@mui/material';
import { useState, type DragEvent } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  useAddWidgetMutation, useCreateDashboardMutation, useDashboardQuery, useDashboardsQuery, useDeleteDashboardMutation,
  useDeleteWidgetMutation, useTemplatesQuery, useUpdateDashboardMutation,
} from '@/api/dashboardApi';
import { useKpisQuery } from '@/api/kpiApi';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, LoadFailed, Loading } from '@/components/common/States';
import { AlertList } from '@/components/widgets/AlertList';
import { TelemetryTable } from '@/components/widgets/TelemetryTable';
import type { Widget } from '@/types/models';
import { formatDateTime } from '@/utils/formatDate';
import { KpiTrendPanel } from './KpiTrendPanel';
import { KpiWidget } from './KpiWidget';

export function DashboardListPage() {
  const nav = useNavigate();
  const { data: mine } = useDashboardsQuery();
  const { data: templates } = useTemplatesQuery();
  const [create] = useCreateDashboardMutation();
  const [name, setName] = useState('');
  const [tpl, setTpl] = useState('');
  return (
    <>
      <PageHeader title="My dashboards" description="Build your own view from KPI cards, gauges, trends, alert lists and live telemetry." />
      <Panel title="New dashboard" sx={{ mb: 2 }}>
        <Box component="form" sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}
          onSubmit={async (e) => { e.preventDefault(); const d = await create({ name, template_id: tpl || undefined }).unwrap(); nav(`/dashboards/${d.id}`); }}>
          <TextField size="small" label="Name" value={name} onChange={(e) => setName(e.target.value)} required />
          <TextField size="small" select label="Start from" value={tpl} onChange={(e) => setTpl(e.target.value)} sx={{ minWidth: 220 }}>
            <MenuItem value="">Blank dashboard</MenuItem>
            {templates?.map((t) => <MenuItem key={t.id} value={t.id}>{t.name}</MenuItem>)}
          </TextField>
          <Button type="submit" variant="contained" startIcon={<Add />}>Create dashboard</Button>
        </Box>
      </Panel>
      {!mine?.length ? <EmptyState title="You have no dashboards yet" hint="Create one above, starting from a template or a blank canvas." /> : (
        <Grid container spacing={1.5}>
          {mine.map((d) => (
            <Grid item xs={12} sm={6} md={4} key={d.id}>
              <Card variant="outlined"><CardActionArea onClick={() => nav(`/dashboards/${d.id}`)}><CardContent>
                <Typography variant="subtitle1">{d.name}</Typography>
                <Typography variant="body2" color="text.secondary">{d.widgets.length} widgets · updated {formatDateTime(d.updated_at)}</Typography>
              </CardContent></CardActionArea></Card>
            </Grid>
          ))}
        </Grid>
      )}
    </>
  );
}

const WIDGET_TYPES = [
  { value: 'kpi_card', label: 'KPI card' }, { value: 'gauge', label: 'Gauge' }, { value: 'trend_chart', label: 'KPI trend' },
  { value: 'alert_list', label: 'Alert list' }, { value: 'telemetry_table', label: 'Live telemetry' },
];

export function DashboardBuilderPage() {
  const { id = '' } = useParams();
  const nav = useNavigate();
  const { data, isLoading, error, refetch } = useDashboardQuery(id);
  const [update] = useUpdateDashboardMutation();
  const [remove] = useDeleteDashboardMutation();
  const [removeWidget] = useDeleteWidgetMutation();
  const [dragId, setDragId] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  if (error && !data) return <LoadFailed error={error} what="Dashboard" backTo={{ label: 'Back to my dashboards', href: '/dashboards' }} onRetry={refetch} />;
  if (isLoading || !data) return <Loading />;
  const widgets = [...data.widgets].sort((a, b) => a.position_index - b.position_index);

  // native HTML5 drag-and-drop reorder; order persisted through PUT /dashboards/{id}
  const onDrop = (e: DragEvent, targetId: string) => {
    e.preventDefault();
    if (!dragId || dragId === targetId) return;
    const ids = widgets.map((w) => w.id).filter((x) => x !== dragId);
    ids.splice(ids.indexOf(targetId), 0, dragId);
    update({ id, body: { widget_order: ids } });
    setDragId(null);
  };

  return (
    <>
      <PageHeader title={data.name} description="Drag widgets by their handle to reorder. Changes save automatically."
        actions={<>
          <Button startIcon={<Add />} variant="contained" onClick={() => setAdding(true)}>Add widget</Button>
          <Button color="error" startIcon={<Delete />} onClick={async () => { await remove(id); nav('/dashboards'); }}>Delete dashboard</Button>
        </>} />
      {!widgets.length && <EmptyState title="This dashboard is empty" hint="Add a widget to get started." />}
      <Grid container spacing={1.5}>
        {widgets.map((w) => (
          <Grid item xs={12} md={Math.max(3, w.width)} key={w.id} onDragOver={(e) => e.preventDefault()} onDrop={(e) => onDrop(e, w.id)}>
            <Box sx={{ position: 'relative', opacity: dragId === w.id ? 0.4 : 1 }}>
              <Box sx={{ position: 'absolute', top: 6, right: 6, zIndex: 2, display: 'flex' }}>
                <IconButton size="small" draggable onDragStart={() => setDragId(w.id)} aria-label={`Move ${w.title}`} sx={{ cursor: 'grab' }}><DragIndicator fontSize="small" /></IconButton>
                <IconButton size="small" aria-label={`Remove ${w.title}`} onClick={() => removeWidget({ id, wid: w.id })}><Delete fontSize="small" /></IconButton>
              </Box>
              <WidgetView widget={w} />
            </Box>
          </Grid>
        ))}
      </Grid>
      <AddWidgetDialog open={adding} dashboardId={id} onClose={() => setAdding(false)} />
    </>
  );
}

function WidgetView({ widget }: { widget: Widget }) {
  const kpi = widget.config.kpi as string | undefined;
  switch (widget.widget_type) {
    case 'kpi_card':
    case 'gauge':
      return kpi ? <KpiWidget code={kpi} gauge={widget.widget_type === 'gauge'} /> : <Panel title={widget.title}><EmptyState title="Choose a KPI" /></Panel>;
    case 'trend_chart':
      return kpi ? <KpiTrendPanel code={kpi} title={widget.title} days={Number(widget.config.days ?? 7)} height={200} /> : null;
    case 'alert_list':
      return <Panel title={widget.title}><AlertList severity={widget.config.severity as string | undefined} limit={Number(widget.config.limit ?? 6)} /></Panel>;
    case 'telemetry_table':
      return <Panel title={widget.title}><TelemetryTable parameter={widget.config.parameter as string | undefined} height={260} /></Panel>;
    case 'heatmap':
      return <Panel title={widget.title}><Typography variant="body2" color="text.secondary">Open the maintenance dashboard for the full heat map.</Typography></Panel>;
    default:
      return <Panel title={widget.title}><Typography variant="body2">Unsupported widget</Typography></Panel>;
  }
}

function AddWidgetDialog({ open, dashboardId, onClose }: { open: boolean; dashboardId: string; onClose: () => void }) {
  const { data: kpis } = useKpisQuery();
  const [add] = useAddWidgetMutation();
  const [type, setType] = useState('kpi_card');
  const [kpi, setKpi] = useState('');
  const [title, setTitle] = useState('');
  const [width, setWidth] = useState(4);
  const needsKpi = ['kpi_card', 'gauge', 'trend_chart'].includes(type);
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Add widget</DialogTitle>
      <DialogContent sx={{ display: 'grid', gap: 2, pt: '8px !important' }}>
        <TextField select label="Widget" value={type} onChange={(e) => setType(e.target.value)}>
          {WIDGET_TYPES.map((t) => <MenuItem key={t.value} value={t.value}>{t.label}</MenuItem>)}
        </TextField>
        {needsKpi && (
          <TextField select label="KPI" value={kpi} onChange={(e) => { setKpi(e.target.value); setTitle(kpis?.find((k) => k.code === e.target.value)?.name ?? ''); }}>
            {kpis?.map((k) => <MenuItem key={k.code} value={k.code}>{k.number ? `${k.number}. ` : ''}{k.name}</MenuItem>)}
          </TextField>
        )}
        <TextField label="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
        <TextField select label="Width" value={width} onChange={(e) => setWidth(Number(e.target.value))}>
          {[3, 4, 6, 8, 12].map((w) => <MenuItem key={w} value={w}>{w} of 12 columns</MenuItem>)}
        </TextField>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!title || (needsKpi && !kpi)}
          onClick={async () => { await add({ id: dashboardId, body: { widget_type: type, title, width, config: needsKpi ? { kpi } : {} } }); onClose(); }}>
          Add widget
        </Button>
      </DialogActions>
    </Dialog>
  );
}
