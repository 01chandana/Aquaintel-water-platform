import { Alert as MuiAlert, Box, Button, Chip, Grid, MenuItem, Table, TableBody, TableCell, TableHead, TableRow, TextField, Typography } from '@mui/material';
import { useMemo, useState } from 'react';
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useAssetsQuery } from '@/api/assetApi';
import { useDeployModelMutation, useDriftQuery, useModelsQuery, usePredictMutation, useTrainModelMutation } from '@/api/operationsApi';
import { LineChart } from '@/components/charts/LineChart';
import { StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage, Loading } from '@/components/common/States';
import { usePermissions } from '@/hooks/usePermissions';
import { tokens } from '@/theme/palette';
import type { MlModel } from '@/types/models';
import { MODEL_LABELS } from '@/utils/constants';
import { formatDateTime } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function MlModelsPage() {
  const { data, isLoading } = useModelsQuery();
  const [name, setName] = useState('pump_failure');
  const versions = useMemo(() => (data ?? []).filter((m) => m.name === name), [data, name]);
  const production = versions.find((m) => m.stage === 'production');
  const names = [...new Set((data ?? []).map((m) => m.name))];
  if (isLoading) return <Loading />;
  return (
    <>
      <PageHeader title="ML models" description="Registry, champion/challenger stages and live inference. Promotion to production needs a second approver." />
      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        {names.map((n) => <Chip key={n} label={MODEL_LABELS[n] ?? n} onClick={() => setName(n)} color={n === name ? 'primary' : 'default'} variant={n === name ? 'filled' : 'outlined'} />)}
      </Box>
      <Grid container spacing={2}>
        <Grid item xs={12} lg={7}>
          <VersionsPanel versions={versions} />
          {production && <Box sx={{ mt: 2 }}><MetricsPanel model={production} /></Box>}
        </Grid>
        <Grid item xs={12} lg={5}>
          {production && <InferencePanel model={production} />}
          <Box sx={{ mt: 2 }}><DriftPanel name={name} /></Box>
        </Grid>
      </Grid>
    </>
  );
}

function VersionsPanel({ versions }: { versions: MlModel[] }) {
  const [deploy, { error }] = useDeployModelMutation();
  const [train, trainState] = useTrainModelMutation();
  const { can } = usePermissions();
  return (
    <Panel title="Versions" actions={can('ml:register') && <Button size="small" variant="outlined" disabled={trainState.isLoading} onClick={() => train(versions[0]?.name)}>Retrain now</Button>}>
      {error && <MuiAlert severity="error" sx={{ mb: 1 }}>{errorMessage(error)}</MuiAlert>}
      {trainState.isSuccess && <MuiAlert severity="info" sx={{ mb: 1 }}>Retraining started. The new version appears in staging when it finishes.</MuiAlert>}
      <Table size="small">
        <TableHead><TableRow><TableCell>Version</TableCell><TableCell>Stage</TableCell><TableCell>Acceptance</TableCell><TableCell>Trained</TableCell><TableCell /></TableRow></TableHead>
        <TableBody>
          {versions.map((m) => (
            <TableRow key={m.id}>
              <TableCell>{m.version}<Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>{m.model_type}</Typography></TableCell>
              <TableCell><StatusChip status={m.stage} /></TableCell>
              <TableCell>{m.acceptance ? (m.acceptance.passed ? 'Passed' : 'Failed') : '—'}</TableCell>
              <TableCell>{formatDateTime(m.created_at)}</TableCell>
              <TableCell align="right">
                {can('ml:deploy') && m.stage !== 'production' && m.stage !== 'archived' && <Button size="small" onClick={() => deploy({ id: m.id, stage: m.stage === 'none' ? 'staging' : 'production', note: 'Approved from console' })}>
                  {m.stage === 'none' ? 'Move to staging' : 'Promote'}</Button>}
                {can('ml:deploy') && m.stage === 'archived' && <Button size="small" onClick={() => deploy({ id: m.id, stage: 'production', note: 'Rollback' })}>Roll back</Button>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </Panel>
  );
}

function MetricsPanel({ model }: { model: MlModel }) {
  const metrics = Object.entries(model.metrics).filter(([, v]) => v !== null && typeof v === 'number');
  const importance = Object.entries((model.params as Record<string, unknown>).feature_importance as Record<string, number> ?? {});
  return (
    <Panel title={`Production v${model.version}`} subtitle={model.training_window ? `Trained on ${model.training_window.rows.toLocaleString()} rows, ${formatDateTime(model.training_window.start)} to ${formatDateTime(model.training_window.end)}` : undefined}>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 1.5 }}>
        {metrics.map(([k, v]) => (
          <Box key={k}><Typography variant="caption" color="text.secondary">{k.replace(/_/g, ' ')}</Typography><Typography variant="subtitle1">{formatNumber(v as number)}</Typography></Box>
        ))}
      </Box>
      {model.acceptance && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="subtitle2">Acceptance criteria</Typography>
          {Object.entries(model.acceptance.checks).map(([k, c]) => (
            <Typography key={k} variant="body2" sx={{ color: c.passed ? 'text.secondary' : tokens.alarm.major }}>{c.passed ? 'Pass' : 'Fail'}: {k.replace(/_/g, ' ')} ({formatNumber(c.value)})</Typography>
          ))}
        </Box>
      )}
      {importance.length > 0 && (
        <ResponsiveContainer width="100%" height={importance.length * 22 + 20}>
          <BarChart data={importance.map(([f, v]) => ({ f, v }))} layout="vertical" margin={{ left: 150 }}>
            <XAxis type="number" hide /><YAxis type="category" dataKey="f" fontSize={11} width={150} />
            <Tooltip /><Bar dataKey="v" fill={tokens.brand} name="Importance" />
          </BarChart>
        </ResponsiveContainer>
      )}
    </Panel>
  );
}

function InferencePanel({ model }: { model: MlModel }) {
  const { data: assets } = useAssetsQuery({ per_page: 500 });
  const [predict, { data, error, isLoading }] = usePredictMutation();
  const pumpModel = ['pump_failure', 'anomaly_detection'].includes(model.name);
  const targets = (assets?.items ?? []).filter((a) => (pumpModel ? a.asset_type?.category === 'pump' : !a.parent_id));
  const [asset, setAsset] = useState('');
  const expl = data?.explanation as Record<string, number> | undefined;
  return (
    <Panel title="Run inference" subtitle="Real-time REST scoring with the production model">
      <Box sx={{ display: 'flex', gap: 1 }}>
        {model.name !== 'chlorine_decay' && model.name !== 'energy_optimization' && (
          <TextField select size="small" fullWidth label={pumpModel ? 'Pump' : 'Site'} value={asset} onChange={(e) => setAsset(e.target.value)}>
            {targets.map((a) => <MenuItem key={a.id} value={a.id}>{a.name} ({a.external_id})</MenuItem>)}
          </TextField>
        )}
        <Button variant="contained" disabled={isLoading || (pumpModel && !asset)} onClick={() => predict({ id: model.id, asset_id: asset || undefined, horizon_hours: 48 })}>Score</Button>
      </Box>
      {error && <MuiAlert severity="error" sx={{ mt: 2 }}>{errorMessage(error)}</MuiAlert>}
      {data && (
        <Box sx={{ mt: 2 }}>
          <Typography variant="h2" component="p">{formatNumber(data.value)} <Typography component="span" color="text.secondary">{String(data.label ?? data.unit ?? '')}</Typography></Typography>
          <Typography variant="caption" color="text.secondary">v{data.version} · {data.latency_ms} ms</Typography>
          {typeof data.recommendation === 'string' && <Typography variant="body2" sx={{ mt: 1 }}>{data.recommendation}</Typography>}
          {expl && (
            <Box sx={{ mt: 1.5 }}>
              <Typography variant="subtitle2">Why: SHAP contributions</Typography>
              {Object.entries(expl).filter(([k]) => k !== '_bias').map(([k, v]) => (
                <Box key={k} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="caption" sx={{ width: 170 }} noWrap>{k}</Typography>
                  <Box sx={{ flex: 1, display: 'flex', justifyContent: v > 0 ? 'flex-start' : 'flex-end' }}>
                    <Box sx={{ height: 6, width: `${Math.min(100, Math.abs(v) * 40)}%`, bgcolor: v > 0 ? tokens.alarm.major : 'text.secondary', borderRadius: 3 }} />
                  </Box>
                  <Typography variant="caption" sx={{ width: 50, textAlign: 'right' }}>{v.toFixed(2)}</Typography>
                </Box>
              ))}
            </Box>
          )}
          {Array.isArray(data.forecast) && (
            <LineChart data={(data.forecast as { time: string; value: number; lower: number; upper: number }[])}
              series={[{ key: 'value', label: 'Forecast' }, { key: 'lower', label: 'Lower bound', dashed: true }, { key: 'upper', label: 'Upper bound', dashed: true }]} height={200} unit="m3/h" />
          )}
          {Array.isArray(data.endpoints) && (data.endpoints as { dma: string; predicted_mg_l: number; measured_mg_l: number; status: string }[]).map((e) => (
            <Typography key={e.dma} variant="body2">{e.dma}: predicted {e.predicted_mg_l} mg/L, measured {e.measured_mg_l} mg/L ({e.status})</Typography>
          ))}
          {Array.isArray(data.options) && (data.options as { pumps_running: number; predicted_sec: number }[]).map((o) => (
            <Typography key={o.pumps_running} variant="body2">{o.pumps_running} pumps: {o.predicted_sec} kWh/m3</Typography>
          ))}
        </Box>
      )}
    </Panel>
  );
}

function DriftPanel({ name }: { name: string }) {
  const { data, isFetching, refetch } = useDriftQuery();
  const rep = data?.find((d) => d.model === name);
  return (
    <Panel title="Drift" subtitle="Unseen data since training (up to 7 days) vs the last 30 days of training data. PSI above 0.2 on an equipment or process feature raises an alert."
      actions={<Button size="small" onClick={() => refetch()} disabled={isFetching}>Recheck</Button>}>
      {isFetching ? <Loading label="Computing drift" /> : !rep ? <Typography variant="body2" color="text.secondary">No drift report for this model.</Typography> : rep.status === 'collecting' ? (
        <Typography variant="body2" color="text.secondary">
          Collecting unseen data since {formatDateTime(rep.window_start)} ({rep.rows} rows so far). A report needs at least 20.
        </Typography>
      ) : (
        <>
          <Typography variant="body2" sx={{ mb: 1, color: rep.drift_detected ? tokens.alarm.major : 'text.secondary' }}>
            {rep.drift_detected
              ? `Equipment/process drift (PSI ${rep.monitored_max_psi}): retraining recommended`
              : `Equipment and process features stable (max PSI ${rep.monitored_max_psi})`}
            {rep.retrain_recommended && !rep.drift_detected ? '. Seasonal inputs have shifted; the monthly retrain will absorb it.' : ''}
          </Typography>
          <Table size="small">
            <TableHead><TableRow><TableCell>Feature</TableCell><TableCell align="right">PSI</TableCell><TableCell align="right">KS</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
            <TableBody>
              {rep.features.slice(0, 8).map((f) => (
                <TableRow key={f.feature}><TableCell>{f.feature}</TableCell><TableCell align="right">{f.psi}</TableCell><TableCell align="right">{f.ks_statistic}</TableCell><TableCell>{f.seasonal ? `${f.status} (seasonal)` : f.status}</TableCell></TableRow>
              ))}
            </TableBody>
          </Table>
        </>
      )}
    </Panel>
  );
}
