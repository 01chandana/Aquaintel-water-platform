import { Add, Delete, Download } from '@mui/icons-material';
import { Alert as MuiAlert, Box, Button, Grid, IconButton, MenuItem, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { downloadReport, useCreateScheduleMutation, useDeleteScheduleMutation, useGenerateReportMutation, useReportsQuery, useSchedulesQuery } from '@/api/reportApi';
import { StatusChip } from '@/components/common/Chips';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage } from '@/components/common/States';
import { usePermissions } from '@/hooks/usePermissions';
import { useAppSelector } from '@/store';
import type { Report, ReportSchedule } from '@/types/models';
import { REPORT_TYPES } from '@/utils/constants';
import { formatDateTime } from '@/utils/formatDate';
import { formatBytes } from '@/utils/formatNumber';

export default function ReportsPage() {
  const [page, setPage] = useState(1);
  const { data, error, refetch } = useReportsQuery(page, { pollingInterval: 5000 });
  const [generate, gen] = useGenerateReportMutation();
  const token = useAppSelector((s) => s.auth.accessToken);
  const [type, setType] = useState('shift_handover');
  const [format, setFormat] = useState<'pdf' | 'excel' | 'html'>('pdf');
  const [dlError, setDlError] = useState<string | null>(null);
  const { can } = usePermissions();
  return (
    <>
      <PageHeader title="Reports" description="Shift handover, compliance and performance reports in PDF, Excel or HTML. Generation runs in the background." />
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Panel title="Generated reports" actions={
            <Box sx={{ display: 'flex', gap: 1 }}>
              <TextField select size="small" value={type} onChange={(e) => setType(e.target.value)} inputProps={{ 'aria-label': 'Report type' }}>
                {Object.entries(REPORT_TYPES).filter(([k]) => k !== 'custom').map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
              </TextField>
              <TextField select size="small" value={format} onChange={(e) => setFormat(e.target.value as typeof format)} inputProps={{ 'aria-label': 'Format' }}>
                <MenuItem value="pdf">PDF</MenuItem><MenuItem value="excel">Excel</MenuItem><MenuItem value="html">HTML</MenuItem>
              </TextField>
              <Button variant="contained" disabled={gen.isLoading} onClick={() => generate({ report_type: type, format })}>Generate</Button>
            </Box>}>
            {(gen.error || dlError) && <MuiAlert severity="error" sx={{ mb: 1 }}>{dlError ?? errorMessage(gen.error)}</MuiAlert>}
            <DataTable<Report> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(r) => r.id} total={data?.meta.total} page={page} perPage={25} onPage={(p) => setPage(p)} dense
              columns={[
                { key: 'n', label: 'Report', render: (r) => <Box><Typography variant="body2">{r.name}</Typography><Typography variant="caption" color="text.secondary">{REPORT_TYPES[r.report_type] ?? r.report_type}</Typography></Box> },
                { key: 'f', label: 'Format', render: (r) => r.format.toUpperCase() },
                { key: 's', label: 'Status', render: (r) => <StatusChip status={r.status} /> },
                { key: 'size', label: 'Size', align: 'right', render: (r) => formatBytes(r.file_size) },
                { key: 'c', label: 'Created', render: (r) => formatDateTime(r.created_at) },
                { key: 'd', label: '', align: 'right', render: (r) => r.status === 'completed' && r.file_size ? (
                  <IconButton size="small" aria-label={`Download ${r.name}`} onClick={() => downloadReport(r.id, r.name, token).catch((e: Error) => setDlError(e.message))}><Download fontSize="small" /></IconButton>) : null },
              ]} />
          </Panel>
        </Grid>
        <Grid item xs={12} lg={4}>{can('reports:schedule') ? <Schedules /> : null}</Grid>
      </Grid>
    </>
  );
}

function Schedules() {
  const { data } = useSchedulesQuery();
  const [create, cState] = useCreateScheduleMutation();
  const [del] = useDeleteScheduleMutation();
  const [f, setF] = useState({ name: '', report_type: 'kpi_summary', cron: '0 7 * * 1', format: 'pdf' });
  return (
    <Panel title="Schedules" subtitle="Cron expressions in UTC. The shift handover runs 30 minutes before each shift change.">
      {data?.map((s: ReportSchedule) => (
        <Box key={s.id} sx={{ display: 'flex', alignItems: 'center', gap: 1, py: 0.75, borderBottom: 1, borderColor: 'divider' }}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="body2">{s.name}</Typography>
            <Typography variant="caption" color="text.secondary">{s.cron} · next {formatDateTime(s.next_run_at)}</Typography>
          </Box>
          <IconButton size="small" aria-label={`Delete schedule ${s.name}`} onClick={() => del(s.id)}><Delete fontSize="small" /></IconButton>
        </Box>
      ))}
      <Box component="form" sx={{ display: 'grid', gap: 1, mt: 2 }} onSubmit={async (e) => { e.preventDefault(); await create(f); setF({ ...f, name: '' }); }}>
        {cState.error && <MuiAlert severity="error">{errorMessage(cState.error)}</MuiAlert>}
        <TextField size="small" label="Name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <TextField size="small" select label="Report" value={f.report_type} onChange={(e) => setF({ ...f, report_type: e.target.value })}>
          {Object.entries(REPORT_TYPES).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
        </TextField>
        <TextField size="small" label="Cron" value={f.cron} onChange={(e) => setF({ ...f, cron: e.target.value })} helperText="minute hour day month weekday" />
        <Button type="submit" startIcon={<Add />} variant="outlined">Add schedule</Button>
      </Box>
    </Panel>
  );
}
