import { Alert as MuiAlert, Box, Button, Checkbox, FormControlLabel, Grid, Stack, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAcknowledgeMutation, useAlertQuery, useEscalateMutation, useResolveMutation } from '@/api/alertApi';
import { useCreateWorkOrderMutation } from '@/api/operationsApi';
import { LineChart } from '@/components/charts/LineChart';
import { SeverityChip, StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, errorMessage, LoadFailed, Loading } from '@/components/common/States';
import { usePermissions } from '@/hooks/usePermissions';
import { formatDateTime } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function AlertDetailPage() {
  const { id = '' } = useParams();
  const { data: a, isLoading, error, refetch } = useAlertQuery(id);
  const [ack, ackState] = useAcknowledgeMutation();
  const [resolve, resolveState] = useResolveMutation();
  const [escalate] = useEscalateMutation();
  const [createWo, woState] = useCreateWorkOrderMutation();
  const [note, setNote] = useState('');
  const [fp, setFp] = useState(false);
  const { can } = usePermissions();
  if (error && !a) return <LoadFailed error={error} what="Alert" backTo={{ label: 'Back to alert center', href: '/alerts' }} onRetry={refetch} />;
  if (isLoading || !a) return <Loading />;
  const open = ['triggered', 'acknowledged', 'investigating', 'escalated'].includes(a.status);
  const err = ackState.error ?? resolveState.error ?? woState.error;
  const telemetry = (a.related_telemetry ?? []).map((p) => ({ time: p.time, value: p.value }));
  return (
    <>
      <PageHeader title={a.title} description={`${a.asset_name ?? 'Platform'} · raised ${formatDateTime(a.created_at)} · source ${a.source}`}
        actions={<><SeverityChip severity={a.severity} /><StatusChip status={a.status} /></>} />
      {err && <MuiAlert severity="error" sx={{ mb: 2 }}>{errorMessage(err)}</MuiAlert>}
      {woState.data && <MuiAlert severity="success" sx={{ mb: 2 }}>Work order {woState.data.number} created.</MuiAlert>}
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Stack spacing={2}>
            <Panel title="What happened">
              <Typography variant="body2">{a.message}</Typography>
              <Box sx={{ display: 'flex', gap: 4, mt: 1.5, flexWrap: 'wrap' }}>
                <Fact label="Trigger value" value={formatNumber(a.trigger_value)} />
                <Fact label="Threshold" value={formatNumber(a.threshold_value)} />
                <Fact label="Occurrences" value={String(a.occurrence_count)} />
                <Fact label="Escalation level" value={['Not escalated', 'Operator', 'Supervisor', 'Manager'][a.escalation_level] ?? String(a.escalation_level)} />
                {a.fault_code && <Fact label="Fault code" value={a.fault_code} />}
              </Box>
              {a.suppressed && <MuiAlert severity="info" sx={{ mt: 1.5 }}>Notifications were suppressed because a higher-severity alert is already open on this asset.</MuiAlert>}
            </Panel>
            <Panel title="Related telemetry" subtitle="6 hours before to 2 hours after the trigger">
              {telemetry.length ? (
                <LineChart data={telemetry} series={[{ key: 'value', label: 'Value' }]} height={240}
                  thresholds={a.threshold_value !== null ? [{ value: a.threshold_value, label: 'Rule threshold', level: 'critical' }] : []} />
              ) : <EmptyState title="No single-tag telemetry for this alert" />}
            </Panel>
          </Stack>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Stack spacing={2}>
            {open && (can('alerts:acknowledge') || can('alerts:escalate')) && (
              <Panel title="Respond">
                <Stack spacing={1.5}>
                  <TextField size="small" multiline minRows={2} label="Note" value={note} onChange={(e) => setNote(e.target.value)} />
                  {a.status === 'triggered' || a.status === 'escalated' ? (
                    <Button variant="contained" onClick={() => ack({ id, note })} disabled={ackState.isLoading}>Acknowledge</Button>
                  ) : null}
                  <FormControlLabel control={<Checkbox checked={fp} onChange={(e) => setFp(e.target.checked)} />} label="False positive (no actionable finding)" />
                  <Button variant="outlined" onClick={() => resolve({ id, note, is_false_positive: fp })}>Resolve</Button>
                  {can('alerts:escalate') && <Button onClick={() => escalate({ id, note })}>Escalate to next level</Button>}
                  {can('work_orders:write') && a.asset_id && (
                    <Button onClick={() => createWo({ asset_id: a.asset_id, alert_id: a.id, title: `Investigate: ${a.title}`.slice(0, 250), description: a.message,
                      wo_type: a.source === 'ml' ? 'predictive' : 'corrective', priority: a.severity === 'critical' ? 'urgent' : 'high' })}>
                      Create work order
                    </Button>
                  )}
                </Stack>
              </Panel>
            )}
            <Panel title="Timeline">
              <Box component="ol" sx={{ m: 0, pl: 2.5 }}>
                {a.events?.map((e) => (
                  <Box component="li" key={e.id} sx={{ mb: 1.25 }}>
                    <Typography variant="body2" sx={{ fontWeight: 600, textTransform: 'capitalize' }}>{e.to_status}</Typography>
                    <Typography variant="caption" color="text.secondary">{formatDateTime(e.created_at)} · {e.actor ?? 'system'}</Typography>
                    {e.note && <Typography variant="body2">{e.note}</Typography>}
                  </Box>
                ))}
              </Box>
            </Panel>
            {a.rule && <Panel title="Rule"><Typography variant="body2">{a.rule.name}</Typography><Typography variant="caption" color="text.secondary">{a.rule.rule_type} · {JSON.stringify(a.rule.condition)}</Typography></Panel>}
          </Stack>
        </Grid>
      </Grid>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <Box><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="subtitle1">{value}</Typography></Box>;
}
