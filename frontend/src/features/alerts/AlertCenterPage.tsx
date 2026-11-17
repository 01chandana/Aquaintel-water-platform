import { Box, Button, Chip, Grid, InputAdornment, MenuItem, Tab, Tabs, TextField, Typography } from '@mui/material';
import { Search } from '@mui/icons-material';
import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useAlertsQuery, useAnalyticsQuery, useBulkAlertsMutation, useIncidentsQuery } from '@/api/alertApi';
import { SeverityChip, StatusChip } from '@/components/common/Chips';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, ErrorState, Loading } from '@/components/common/States';
import { useDebounce } from '@/hooks/useDebounce';
import { usePermissions } from '@/hooks/usePermissions';
import { usePolling } from '@/hooks/usePolling';
import { severityColor } from '@/theme/palette';
import type { Alert } from '@/types/models';
import { SEVERITIES } from '@/utils/constants';
import { formatDateTime, formatDay, timeAgo } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function AlertCenterPage() {
  const [tab, setTab] = useState(0);
  return (
    <>
      <PageHeader title="Alert center" description="Every alarm raised by rules, KPIs and models. Suppressed alerts are kept for the record but never page anyone." />
      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Alerts" /><Tab label="Incidents" /><Tab label="Analytics" />
      </Tabs>
      {tab === 0 && <AlertTable />}
      {tab === 1 && <Incidents />}
      {tab === 2 && <Analytics />}
    </>
  );
}

function AlertTable() {
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const [page, setPage] = useState({ page: 1, per_page: 25 });
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('-created_at');
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const search = useDebounce(q);
  const status = params.get('status') ?? '';
  const severity = params.get('severity') ?? '';
  const openOnly = params.get('open_only') === 'true';
  const { data, isLoading, error, refetch } = useAlertsQuery({ ...page, q: search, status, severity, open_only: openOnly || undefined, sort }, { pollingInterval: usePolling() });
  const [bulk, bulkState] = useBulkAlertsMutation();
  const { can } = usePermissions();
  const set = (k: string, v: string) => { const p = new URLSearchParams(params); if (v) p.set(k, v); else p.delete(k); setParams(p); setPage({ ...page, page: 1 }); };

  return (
    <Panel>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 1.5, alignItems: 'center' }}>
        <TextField size="small" placeholder="Search alerts" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ 'aria-label': 'Search alerts' }}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
        <TextField select size="small" label="Severity" value={severity} onChange={(e) => set('severity', e.target.value)} sx={{ minWidth: 140 }}>
          <MenuItem value="">Any</MenuItem>{SEVERITIES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Status" value={openOnly ? 'open' : status} sx={{ minWidth: 160 }}
          onChange={(e) => { const p = new URLSearchParams(params); p.delete('status'); p.delete('open_only'); if (e.target.value === 'open') p.set('open_only', 'true'); else if (e.target.value) p.set('status', e.target.value); setParams(p); }}>
          <MenuItem value="">Any</MenuItem><MenuItem value="open">Open (any open state)</MenuItem>
          {['triggered', 'acknowledged', 'escalated', 'resolved', 'closed'].map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}
        </TextField>
        <Box sx={{ flex: 1 }} />
        {selected.size > 0 && can('alerts:acknowledge') && <>
          <Typography variant="body2" color="text.secondary">{selected.size} selected</Typography>
          <Button size="small" variant="outlined" disabled={bulkState.isLoading} onClick={async () => { await bulk({ alert_ids: [...selected], action: 'acknowledge' }); setSelected(new Set()); }}>Acknowledge</Button>
          <Button size="small" variant="outlined" disabled={bulkState.isLoading} onClick={async () => { await bulk({ alert_ids: [...selected], action: 'resolve' }); setSelected(new Set()); }}>Resolve</Button>
        </>}
      </Box>
      {isLoading ? <Loading /> : (
        <DataTable<Alert> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(a) => a.id} total={data?.meta.total} page={page.page} perPage={page.per_page}
          onPage={(p, pp) => setPage({ page: p, per_page: pp })} sort={sort} onSort={setSort} onRowClick={(a) => nav(`/alerts/${a.id}`)}
          selected={can('alerts:acknowledge') ? selected : undefined} onSelect={can('alerts:acknowledge') ? setSelected : undefined} dense empty="No alerts match these filters"
          columns={[
            { key: 'sev', label: 'Severity', sortKey: 'severity', render: (a) => <SeverityChip severity={a.severity} /> },
            { key: 'title', label: 'Alert', render: (a) => (
              <Box sx={{ opacity: a.suppressed ? 0.6 : 1 }}>
                <Typography variant="body2" sx={{ fontWeight: 500 }}>{a.title}</Typography>
                <Typography variant="caption" color="text.secondary">{a.message}</Typography>
              </Box>) },
            { key: 'asset', label: 'Asset', render: (a) => a.asset_name ?? '—' },
            { key: 'status', label: 'Status', sortKey: 'status', render: (a) => <StatusChip status={a.status} /> },
            { key: 'src', label: 'Source', render: (a) => <Chip size="small" variant="outlined" label={a.suppressed ? `${a.source} · suppressed` : a.source} /> },
            { key: 'n', label: 'Count', align: 'right', render: (a) => a.occurrence_count },
            { key: 'time', label: 'Raised', sortKey: 'created_at', render: (a) => <span title={formatDateTime(a.created_at)}>{timeAgo(a.created_at)}</span> },
          ]} />
      )}
    </Panel>
  );
}

function Incidents() {
  const nav = useNavigate();
  const { data, isLoading } = useIncidentsQuery();
  if (isLoading) return <Loading />;
  if (!data?.items.length) return <Panel><EmptyState title="No open incidents" hint="Related alerts on neighbouring assets within 10 minutes are grouped into an incident automatically." /></Panel>;
  return (
    <Grid container spacing={2}>
      {data.items.map((inc) => (
        <Grid item xs={12} md={6} key={inc.id}>
          <Panel title={inc.title} subtitle={`${inc.alert_count} alerts · opened ${timeAgo(inc.created_at)}`} actions={<SeverityChip severity={inc.severity} />}>
            {inc.root_cause_hint && <Typography variant="body2" sx={{ mb: 1 }}>{inc.root_cause_hint}</Typography>}
            {inc.alerts.map((a) => (
              <Box key={a.id} onClick={() => nav(`/alerts/${a.id}`)} sx={{ display: 'flex', gap: 1, py: 0.5, cursor: 'pointer', alignItems: 'center' }}>
                <SeverityChip severity={a.severity} /><Typography variant="body2" noWrap>{a.title}</Typography>
              </Box>
            ))}
          </Panel>
        </Grid>
      ))}
    </Grid>
  );
}

function Analytics() {
  const [days, setDays] = useState(30);
  const { data, isLoading, error, refetch } = useAnalyticsQuery(days);
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />;
  if (isLoading || !data) return <Loading />;
  const stat = (label: string, v: string) => (
    <Grid item xs={6} md={3}><Panel dense><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h2" component="p">{v}</Typography></Panel></Grid>
  );
  return (
    <>
      <Box sx={{ mb: 2 }}>
        <TextField select size="small" label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {[7, 30, 90].map((d) => <MenuItem key={d} value={d}>Last {d} days</MenuItem>)}
        </TextField>
      </Box>
      <Grid container spacing={1.5} sx={{ mb: 2 }}>
        {stat('Alerts raised', String(data.total))}
        {stat('Mean time to acknowledge', data.mean_time_to_acknowledge_min !== null ? `${formatNumber(data.mean_time_to_acknowledge_min)} min` : '—')}
        {stat('Mean time to resolve', data.mean_time_to_resolve_min !== null ? `${formatNumber(data.mean_time_to_resolve_min)} min` : '—')}
        {stat('False positive rate', data.false_positive_rate_pct !== null ? `${formatNumber(data.false_positive_rate_pct)}%` : '—')}
      </Grid>
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Panel title="Alert volume by severity">
            <ResponsiveContainer width="100%" height={260}>
              <BarChart data={data.volume_trend}>
                <CartesianGrid vertical={false} strokeOpacity={0.15} />
                <XAxis dataKey="date" tickFormatter={(d) => formatDay(d)} fontSize={11} />
                <YAxis fontSize={11} allowDecimals={false} />
                <Tooltip />
                {SEVERITIES.map((s) => <Bar key={s} dataKey={s} stackId="a" fill={severityColor(s)} name={s} />)}
              </BarChart>
            </ResponsiveContainer>
          </Panel>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Panel title="Top assets by alert count" subtitle="Pareto: investigate from the top">
            {data.pareto_by_asset.map((p) => (
              <Box key={p.name} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.4 }}>
                <Typography variant="body2" sx={{ flex: 1 }} noWrap>{p.name}</Typography>
                <Box sx={{ width: 120, height: 6, bgcolor: 'divider', borderRadius: 3 }}>
                  <Box sx={{ width: `${(p.count / data.pareto_by_asset[0].count) * 100}%`, height: 6, bgcolor: 'text.secondary', borderRadius: 3 }} />
                </Box>
                <Typography variant="body2" sx={{ width: 32, textAlign: 'right' }}>{p.count}</Typography>
              </Box>
            ))}
          </Panel>
        </Grid>
        <Grid item xs={12}>
          <Panel title="Operator response" subtitle="Average time from trigger to acknowledgement">
            {data.operator_response.length ? data.operator_response.map((o) => (
              <Box key={o.operator} sx={{ display: 'flex', gap: 2, py: 0.4 }}>
                <Typography variant="body2" sx={{ width: 200 }}>{o.operator}</Typography>
                <Typography variant="body2" color="text.secondary">{o.acknowledged} acknowledged</Typography>
                <Typography variant="body2">{formatNumber(o.avg_ack_min)} min</Typography>
              </Box>
            )) : <EmptyState title="No acknowledgements in this period" />}
          </Panel>
        </Grid>
      </Grid>
    </>
  );
}
