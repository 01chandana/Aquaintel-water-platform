import { Box, Chip, Grid, MenuItem, Table, TableBody, TableCell, TableRow, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useAdminLogsQuery, useAdminMetricsQuery, useHealthQuery, useQueueStatusQuery, useUsageStatsQuery } from '@/api/operationsApi';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { Loading } from '@/components/common/States';
import { tokens } from '@/theme/palette';
import { formatDateTime } from '@/utils/formatDate';

const tone = (s: unknown) => (s === 'healthy' ? 'text.secondary' : s === 'degraded' ? tokens.alarm.major : tokens.alarm.critical);

export default function SystemPage() {
  const { data: health } = useHealthQuery(undefined, { pollingInterval: 15_000 });
  const { data: metrics } = useAdminMetricsQuery(undefined, { pollingInterval: 30_000 });
  const { data: usage } = useUsageStatsQuery();
  const { data: queue } = useQueueStatusQuery(undefined, { pollingInterval: 30_000 });
  const [level, setLevel] = useState('');
  const { data: logs } = useAdminLogsQuery(level || undefined, { pollingInterval: 10_000 });
  return (
    <>
      <PageHeader title="System" description="Dependency health, runtime metrics, task queues and recent structured logs. Degraded means a fallback is active (for example the in-process event bus instead of Kafka)." />
      <Grid container spacing={2}>
        <Grid item xs={12} md={5}>
          <Panel title="Health" subtitle={health ? `v${health.version} · up ${Math.round(health.uptime_seconds / 60)} min` : undefined}
            actions={health && <Typography sx={{ color: tone(health.status), fontWeight: 600, textTransform: 'capitalize' }}>{health.status}</Typography>}>
            {!health ? <Loading /> : (
              <Table size="small"><TableBody>
                {Object.entries(health.checks).map(([k, c]) => (
                  <TableRow key={k}>
                    <TableCell sx={{ textTransform: 'capitalize' }}>{k}</TableCell>
                    <TableCell sx={{ color: tone(c.status), textTransform: 'capitalize' }}>{String(c.status)}</TableCell>
                    <TableCell>{c.backend ? String(c.backend) : ''} {c.latency_ms !== undefined ? `${c.latency_ms} ms` : ''} {c.timescaledb !== undefined ? `timescaledb ${c.timescaledb ? 'on' : 'off'}` : ''}</TableCell>
                  </TableRow>
                ))}
              </TableBody></Table>
            )}
          </Panel>
          <Panel title="Task queue" sx={{ mt: 2 }}>
            <Typography variant="body2">Mode: {String(queue?.mode ?? '—')} · workers {String(queue?.workers ?? 0)}</Typography>
            <Box sx={{ mt: 1, display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
              {Object.entries((queue?.stats ?? queue?.queue_depth ?? {}) as Record<string, number>).map(([k, v]) => <Chip key={k} size="small" variant="outlined" label={`${k}: ${v}`} />)}
            </Box>
          </Panel>
          <Panel title="Circuit breakers" sx={{ mt: 2 }}>
            {Object.entries((metrics?.circuit_breakers ?? {}) as Record<string, string>).map(([k, v]) => (
              <Typography key={k} variant="body2" sx={{ color: v === 'closed' ? 'text.secondary' : tokens.alarm.major }}>{k}: {v}</Typography>
            ))}
          </Panel>
        </Grid>
        <Grid item xs={12} md={7}>
          <Panel title="Usage">
            {usage && (
              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 2 }}>
                {[['Users', usage.users.total], ['Active (7 d)', usage.users.active_7d], ['Sessions', usage.users.active_sessions], ['Assets', usage.assets],
                  ['Points (24 h)', usage.telemetry_points_24h.toLocaleString()], ['Open alerts', usage.alerts.open], ['Reports (30 d)', usage.reports_generated_30d],
                  ['Models in production', usage.models_in_production]].map(([l, v]) => (
                  <Box key={l as string}><Typography variant="caption" color="text.secondary">{l}</Typography><Typography variant="h3" component="p">{v as string}</Typography></Box>
                ))}
              </Box>
            )}
          </Panel>
          <Panel title="Recent logs" sx={{ mt: 2 }} actions={
            <TextField select size="small" value={level} onChange={(e) => setLevel(e.target.value)} inputProps={{ 'aria-label': 'Log level' }}>
              <MenuItem value="">All levels</MenuItem>{['info', 'warning', 'error'].map((l) => <MenuItem key={l} value={l}>{l}</MenuItem>)}
            </TextField>}>
            <Box sx={{ maxHeight: 420, overflow: 'auto', fontSize: 12 }}>
              {logs?.map((l, i) => (
                <Box key={i} sx={{ display: 'flex', gap: 1.5, py: 0.4, borderBottom: 1, borderColor: 'divider' }}>
                  <Box sx={{ width: 110, color: 'text.secondary', flexShrink: 0 }}>{formatDateTime(String(l.timestamp ?? ''))}</Box>
                  <Box sx={{ width: 60, color: l.level === 'error' ? tokens.alarm.critical : l.level === 'warning' ? tokens.alarm.major : 'text.secondary' }}>{String(l.level)}</Box>
                  <Box sx={{ flex: 1, wordBreak: 'break-all' }}>{String(l.message ?? '')} <Box component="span" sx={{ color: 'text.secondary' }}>{String(l.logger ?? '')}</Box></Box>
                </Box>
              ))}
            </Box>
          </Panel>
        </Grid>
      </Grid>
    </>
  );
}
