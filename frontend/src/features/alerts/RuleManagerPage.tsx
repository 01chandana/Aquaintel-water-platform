import { zodResolver } from '@hookform/resolvers/zod';
import { Add, Delete, Edit, PlayArrow } from '@mui/icons-material';
import {
  Alert as MuiAlert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Grid, IconButton, MenuItem, Switch, TextField, Tooltip, Typography,
} from '@mui/material';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { useCreateRuleMutation, useDeleteRuleMutation, useRulesQuery, useSimulateRuleMutation, useTestRuleMutation, useToggleRuleMutation, useUpdateRuleMutation, type ReplayResult } from '@/api/alertApi';
import { useTagsQuery } from '@/api/telemetryApi';
import { SeverityChip } from '@/components/common/Chips';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage, Loading } from '@/components/common/States';
import { useDebounce } from '@/hooks/useDebounce';
import { usePermissions } from '@/hooks/usePermissions';
import type { Rule } from '@/types/models';
import { SEVERITIES } from '@/utils/constants';
import { formatDateTime, hoursAgo } from '@/utils/formatDate';
import { ruleSchema, type RuleForm, type RuleFormInput } from '@/utils/validators';

function describe(r: Rule): string {
  const c = r.condition as Record<string, unknown>;
  switch (r.rule_type) {
    case 'threshold':
      return `${String(c.operator).replace('_', ' ')} ${c.value ?? `${c.low}–${c.high}`}${c.sustained_seconds ? ` for ${c.sustained_seconds}s` : ''}`;
    case 'rate': return `${c.direction} > ${c.max_change_pct ?? c.max_change_abs}${c.max_change_pct ? '%' : ''} in ${c.window_seconds}s`;
    case 'deviation': return `${c.method} > ${c.n_sigma ?? c.max_deviation_pct}σ`;
    case 'predictive': return `${c.model} ${c.metric} > ${c.value}`;
    default: return `${(c.terms as unknown[] | undefined)?.length ?? 0} conditions (${String(c.logic).toUpperCase()})`;
  }
}

export default function RuleManagerPage() {
  const [q, setQ] = useState('');
  const [page, setPage] = useState({ page: 1, per_page: 25 });
  const search = useDebounce(q);
  const { data, isLoading, error, refetch } = useRulesQuery({ ...page, q: search });
  const [toggle] = useToggleRuleMutation();
  const [del] = useDeleteRuleMutation();
  const [editing, setEditing] = useState<Rule | 'new' | null>(null);
  const [deleting, setDeleting] = useState<Rule | null>(null);
  const [simulating, setSimulating] = useState<Rule | null>(null);
  const { can } = usePermissions();
  return (
    <>
      <PageHeader title="Rule manager" description="Threshold, rate-of-change, statistical, composite and predictive rules. Test a rule against sample values or replay history before enabling it."
        actions={<Button variant="contained" startIcon={<Add />} onClick={() => setEditing('new')}>New rule</Button>} />
      <Panel actions={<TextField size="small" placeholder="Search rules" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ 'aria-label': 'Search rules' }} />} title="Rules">
        {isLoading ? <Loading /> : (
          <DataTable<Rule> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(r) => r.id} total={data?.meta.total} {...page} onPage={(p, pp) => setPage({ page: p, per_page: pp })} dense
            columns={[
              { key: 'on', label: 'Enabled', render: (r) => <Switch size="small" checked={r.enabled} onChange={() => toggle(r.id)} inputProps={{ 'aria-label': `Enable ${r.name}` }} /> },
              { key: 'name', label: 'Rule', render: (r) => <Box><Typography variant="body2">{r.name}</Typography><Typography variant="caption" color="text.secondary">{describe(r)}</Typography></Box> },
              { key: 'type', label: 'Type', render: (r) => r.rule_type },
              { key: 'sev', label: 'Severity', render: (r) => <SeverityChip severity={r.severity} /> },
              { key: 'cd', label: 'Cooldown', render: (r) => `${r.cooldown_minutes} min` },
              { key: 'act', label: '', align: 'right', render: (r) => (
                <Box sx={{ whiteSpace: 'nowrap' }}>
                  {['threshold', 'rate', 'deviation'].includes(r.rule_type) && r.tag_id && (
                    <Tooltip title="Replay history"><IconButton size="small" onClick={() => setSimulating(r)} aria-label={`Simulate ${r.name}`}><PlayArrow fontSize="small" /></IconButton></Tooltip>
                  )}
                  {['threshold', 'rate', 'deviation'].includes(r.rule_type) && <IconButton size="small" onClick={() => setEditing(r)} aria-label={`Edit ${r.name}`}><Edit fontSize="small" /></IconButton>}
                  {can('alerts:rules:delete') && <IconButton size="small" onClick={() => setDeleting(r)} aria-label={`Delete ${r.name}`}><Delete fontSize="small" /></IconButton>}
                </Box>) },
            ]} />
        )}
      </Panel>
      {editing && <RuleDialog rule={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {simulating && <SimulateDialog rule={simulating} onClose={() => setSimulating(null)} />}
      <ConfirmDialog open={!!deleting} title="Delete rule" danger confirmLabel="Delete rule" body={`"${deleting?.name}" stops evaluating immediately. Existing alerts are kept.`}
        onClose={() => setDeleting(null)} onConfirm={() => deleting && del(deleting.id)} />
    </>
  );
}

function toPayload(v: RuleForm) {
  const condition =
    v.rule_type === 'threshold'
      ? { operator: v.operator, value: v.value, low: v.low, high: v.high, sustained_seconds: v.sustained_seconds, hysteresis: v.hysteresis }
      : v.rule_type === 'rate'
        ? { window_seconds: v.window_seconds, max_change_pct: v.max_change_pct, direction: v.direction }
        : { method: 'sigma', window_points: 96, n_sigma: v.n_sigma };
  return { name: v.name, rule_type: v.rule_type, severity: v.severity, tag_id: v.tag_id, condition, cooldown_minutes: v.cooldown_minutes };
}

function RuleDialog({ rule, onClose }: { rule: Rule | null; onClose: () => void }) {
  const { data: tags } = useTagsQuery();
  const [create, cState] = useCreateRuleMutation();
  const [update, uState] = useUpdateRuleMutation();
  const [test, tState] = useTestRuleMutation();
  const [sample, setSample] = useState('70, 72, 88, 91, 93, 80, 70');
  const c = (rule?.condition ?? {}) as Record<string, number | string | undefined>;
  const { register, handleSubmit, watch, control, formState: { errors } } = useForm<RuleFormInput, unknown, RuleForm>({
    resolver: zodResolver(ruleSchema),
    defaultValues: {
      name: rule?.name ?? '', rule_type: (rule?.rule_type as RuleForm['rule_type']) ?? 'threshold', severity: rule?.severity ?? 'major',
      tag_id: rule?.tag_id ?? '', operator: (c.operator as string) ?? 'greater_than', value: c.value as number | undefined,
      low: c.low as number | undefined, high: c.high as number | undefined, sustained_seconds: Number(c.sustained_seconds ?? 0),
      hysteresis: Number(c.hysteresis ?? 0), window_seconds: Number(c.window_seconds ?? 300), max_change_pct: c.max_change_pct as number | undefined,
      direction: (c.direction as RuleForm['direction']) ?? 'any', n_sigma: Number(c.n_sigma ?? 3), cooldown_minutes: rule?.cooldown_minutes ?? 15,
    },
  });
  const type = watch('rule_type');
  const op = watch('operator');
  const err = cState.error ?? uState.error ?? tState.error;
  const save = async (v: RuleForm) => {
    const body = toPayload(v);
    const ok = await (rule ? update({ id: rule.id, body }) : create(body)).unwrap().then(() => true).catch(() => false);
    if (ok) onClose();
  };
  const runTest = handleSubmit((v) => test({ rule: toPayload(v), values: sample.split(/[,\s]+/).filter(Boolean).map(Number), interval_seconds: 60 }));
  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{rule ? 'Edit rule' : 'New rule'}</DialogTitle>
      <DialogContent>
        {err && <MuiAlert severity="error" sx={{ mb: 2 }}>{errorMessage(err)}</MuiAlert>}
        <Grid container spacing={2} sx={{ pt: 1 }}>
          <Grid item xs={12} md={8}><TextField fullWidth label="Name" {...register('name')} error={!!errors.name} helperText={errors.name?.message} /></Grid>
          <Grid item xs={6} md={2}>
            <Controller name="rule_type" control={control} render={({ field }) => (
              <TextField select fullWidth label="Type" {...field}>{['threshold', 'rate', 'deviation'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}</TextField>)} />
          </Grid>
          <Grid item xs={6} md={2}>
            <Controller name="severity" control={control} render={({ field }) => (
              <TextField select fullWidth label="Severity" {...field}>{SEVERITIES.map((s) => <MenuItem key={s} value={s}>{s}</MenuItem>)}</TextField>)} />
          </Grid>
          <Grid item xs={12}>
            <Controller name="tag_id" control={control} render={({ field }) => (
              <TextField select fullWidth label="Tag" {...field} error={!!errors.tag_id} helperText={errors.tag_id?.message} SelectProps={{ MenuProps: { PaperProps: { sx: { maxHeight: 360 } } } }}>
                {tags?.map((t) => <MenuItem key={t.id} value={t.id}>{t.external_id} ({t.unit})</MenuItem>)}
              </TextField>)} />
          </Grid>
          {type === 'threshold' && <>
            <Grid item xs={12} md={4}>
              <Controller name="operator" control={control} render={({ field }) => (
                <TextField select fullWidth label="Condition" {...field}>
                  {['greater_than', 'less_than', 'greater_equal', 'less_equal', 'outside_range', 'inside_range'].map((o) => <MenuItem key={o} value={o}>{o.replace('_', ' ')}</MenuItem>)}
                </TextField>)} />
            </Grid>
            {op.includes('range') ? <>
              <Grid item xs={6} md={2}><TextField fullWidth label="Low" type="number" inputProps={{ step: 'any' }} {...register('low')} error={!!errors.low} helperText={errors.low?.message} /></Grid>
              <Grid item xs={6} md={2}><TextField fullWidth label="High" type="number" inputProps={{ step: 'any' }} {...register('high')} /></Grid>
            </> : <Grid item xs={12} md={4}><TextField fullWidth label="Threshold" type="number" inputProps={{ step: 'any' }} {...register('value')} error={!!errors.value} helperText={errors.value?.message} /></Grid>}
            <Grid item xs={6} md={2}><TextField fullWidth label="Sustain (s)" type="number" {...register('sustained_seconds')} /></Grid>
            <Grid item xs={6} md={2}><TextField fullWidth label="Hysteresis" type="number" inputProps={{ step: 'any' }} {...register('hysteresis')} /></Grid>
          </>}
          {type === 'rate' && <>
            <Grid item xs={4}><TextField fullWidth label="Window (s)" type="number" {...register('window_seconds')} /></Grid>
            <Grid item xs={4}><TextField fullWidth label="Max change (%)" type="number" inputProps={{ step: 'any' }} {...register('max_change_pct')} error={!!errors.max_change_pct} helperText={errors.max_change_pct?.message} /></Grid>
            <Grid item xs={4}>
              <Controller name="direction" control={control} render={({ field }) => (
                <TextField select fullWidth label="Direction" {...field}>{['drop', 'rise', 'any'].map((d) => <MenuItem key={d} value={d}>{d}</MenuItem>)}</TextField>)} />
            </Grid>
          </>}
          {type === 'deviation' && <Grid item xs={6}><TextField fullWidth label="Sigma limit" type="number" inputProps={{ step: 'any' }} {...register('n_sigma')} helperText="Alert when a value is this many standard deviations from the recent mean" /></Grid>}
          <Grid item xs={6} md={3}><TextField fullWidth label="Cooldown (min)" type="number" {...register('cooldown_minutes')} helperText="Suppress repeats after resolve" /></Grid>
        </Grid>
        <Box sx={{ mt: 3, p: 2, border: 1, borderColor: 'divider', borderRadius: 1 }}>
          <Typography variant="subtitle2">Test with sample values</Typography>
          <Typography variant="caption" color="text.secondary">One value per minute, separated by commas.</Typography>
          <Box sx={{ display: 'flex', gap: 1, mt: 1 }}>
            <TextField size="small" fullWidth value={sample} onChange={(e) => setSample(e.target.value)} inputProps={{ 'aria-label': 'Sample values' }} />
            <Button variant="outlined" onClick={runTest} disabled={tState.isLoading}>Run test</Button>
          </Box>
          {tState.data && <ReplaySummary result={tState.data} />}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit(save)}>{rule ? 'Save rule' : 'Create rule'}</Button>
      </DialogActions>
    </Dialog>
  );
}

function SimulateDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const [days, setDays] = useState(14);
  const [simulate, { data, isLoading, error }] = useSimulateRuleMutation();
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Replay history: {rule.name}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>Runs the rule over stored telemetry to show how often it would have fired.</Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <TextField select size="small" label="Window" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 14, 30, 60].map((d) => <MenuItem key={d} value={d}>Last {d} days</MenuItem>)}
          </TextField>
          <Button variant="contained" disabled={isLoading} onClick={() => simulate({ id: rule.id, start: hoursAgo(days * 24), end: new Date().toISOString() })}>Replay</Button>
        </Box>
        {error && <MuiAlert severity="error" sx={{ mt: 2 }}>{errorMessage(error)}</MuiAlert>}
        {data && <ReplaySummary result={data} />}
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
    </Dialog>
  );
}

function ReplaySummary({ result }: { result: ReplayResult }) {
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {result.trigger_count === 0 ? 'The rule would not have fired.' : `The rule would have fired ${result.trigger_count} time${result.trigger_count > 1 ? 's' : ''}`}
        {result.points_evaluated !== undefined && ` across ${result.points_evaluated.toLocaleString()} samples`}.
      </Typography>
      {result.episodes.slice(0, 10).map((e, i) => (
        <Typography key={i} variant="body2" color="text.secondary">
          {typeof e.start === 'string' ? formatDateTime(e.start) : `minute ${Number(e.start) / 60}`}: peak {e.peak.toFixed(2)}, {e.message}
        </Typography>
      ))}
    </Box>
  );
}
