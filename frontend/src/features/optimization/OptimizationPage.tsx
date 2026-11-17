import { Alert as MuiAlert, Box, Button, Grid, Slider, Table, TableBody, TableCell, TableRow, TextField, Typography, useTheme } from '@mui/material';
import { useState } from 'react';
import { Bar, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useApprovePlanMutation, useDosingMutation, usePlansQuery, usePumpScheduleMutation } from '@/api/operationsApi';
import { StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, errorMessage, Loading } from '@/components/common/States';
import { useAppSelector } from '@/store';
import { tokens } from '@/theme/palette';
import type { OptimizationPlan } from '@/types/models';
import { formatDateTime, formatTime } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function OptimizationPage() {
  const siteId = useAppSelector((s) => s.ui.siteId);
  const [run, runState] = usePumpScheduleMutation();
  const [dose, doseState] = useDosingMutation();
  const [approve] = useApprovePlanMutation();
  const { data: plans } = usePlansQuery();
  const [levels, setLevels] = useState<number[]>([25, 95]);
  const [target, setTarget] = useState(0.8);
  const plan = runState.data ?? plans?.items.find((p) => p.schedule_type === 'pump');
  const dosing = doseState.data ?? plans?.items.find((p) => p.schedule_type === 'dosing');
  return (
    <>
      <PageHeader title="Optimization" description="Pump schedules that meet forecast demand at the lowest time-of-use energy cost, and chemical dosing setpoints for current raw-water conditions." />
      <Grid container spacing={2}>
        <Grid item xs={12} lg={8}>
          <Panel title="Pump schedule (next 24 h)" subtitle="Mixed-integer programme: pump on/off per hour, reservoir mass balance, tank limits, contracted demand cap"
            actions={<Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
              <Box sx={{ width: 180 }}>
                <Typography variant="caption" color="text.secondary">Reservoir limits {levels[0]}–{levels[1]}%</Typography>
                <Slider size="small" value={levels} min={5} max={100} onChange={(_, v) => setLevels(v as number[])} getAriaLabel={() => 'Reservoir level limits'} />
              </Box>
              <Button variant="contained" disabled={runState.isLoading} onClick={() => run({ site_id: siteId, horizon_hours: 24, min_level_pct: levels[0], max_level_pct: levels[1] })}>Optimize</Button>
            </Box>}>
            {runState.error && <MuiAlert severity="error" sx={{ mb: 1 }}>{errorMessage(runState.error)}</MuiAlert>}
            {runState.isLoading ? <Loading label="Solving" /> : plan ? <PumpPlan plan={plan} onApprove={() => approve(plan.id)} /> : <EmptyState title="No schedule yet" hint="Run the optimizer to propose a plan." />}
          </Panel>
        </Grid>
        <Grid item xs={12} lg={4}>
          <Panel title="Chemical dosing" subtitle="Coagulant from the refitted dose curve; chlorine setpoint from the decay model so the furthest district keeps its residual">
            <Box sx={{ display: 'flex', gap: 1, mb: 2 }}>
              <TextField size="small" type="number" label="Target residual (mg/L)" sx={{ flex: 1 }} value={target} inputProps={{ step: 0.1, min: 0.2, max: 4 }} onChange={(e) => setTarget(Number(e.target.value))} />
              <Button variant="outlined" onClick={() => dose({ site_id: siteId, target_residual_mg_l: target })} disabled={doseState.isLoading}>Recommend</Button>
            </Box>
            {doseState.error && <MuiAlert severity="error">{errorMessage(doseState.error)}</MuiAlert>}
            {dosing && <DosingPlan plan={dosing} />}
          </Panel>
        </Grid>
      </Grid>
    </>
  );
}

function PumpPlan({ plan, onApprove }: { plan: OptimizationPlan; onApprove: () => void }) {
  const theme = useTheme();
  const hours = (plan.plan.hours ?? []) as { time: string; pumps_running: number; level_pct: number; tariff: number; demand_m3: number; pumped_m3: number }[];
  const peakRate = Math.max(...hours.map((h) => h.tariff));
  // contiguous peak-tariff blocks drawn as background bands
  const peaks: { from: string; to: string }[] = [];
  hours.forEach((h, i) => {
    if (h.tariff !== peakRate) return;
    const last = peaks[peaks.length - 1];
    if (last && hours[i - 1]?.tariff === peakRate) last.to = h.time;
    else peaks.push({ from: h.time, to: h.time });
  });
  return (
    <>
      <Box sx={{ display: 'flex', gap: 4, mb: 2, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        <Stat label="Optimized cost" value={`$${formatNumber(plan.estimated_cost)}`} />
        <Stat label="Follow-demand baseline" value={`$${formatNumber(plan.baseline_cost)}`} />
        <Stat label="Saving" value={`${formatNumber(plan.savings_pct)}%`} />
        <Stat label="Solver" value={plan.solver_status ?? '—'} />
        <Box sx={{ flex: 1 }} />
        <StatusChip status={plan.status} />
        {plan.status === 'proposed' && <Button size="small" onClick={onApprove}>Approve plan</Button>}
      </Box>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={hours}>
          <CartesianGrid vertical={false} stroke={theme.palette.divider} />
          <XAxis dataKey="time" tickFormatter={(t) => formatTime(t)} fontSize={11} />
          <YAxis yAxisId="p" allowDecimals={false} fontSize={11} label={{ value: 'Pumps', angle: -90, position: 'insideLeft', fontSize: 11 }} />
          <YAxis yAxisId="l" orientation="right" domain={[0, 100]} fontSize={11} label={{ value: 'Level %', angle: 90, position: 'insideRight', fontSize: 11 }} />
          <Tooltip labelFormatter={(t) => formatDateTime(String(t))} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Bar yAxisId="p" dataKey="pumps_running" name="Pumps running" fill={theme.palette.text.secondary} fillOpacity={0.35} />
          <Line yAxisId="l" dataKey="level_pct" name="Reservoir level" stroke={tokens.brand} dot={false} strokeWidth={2} />
          {peaks.map((p) => <ReferenceArea key={p.from} yAxisId="p" x1={p.from} x2={p.to} fill={tokens.alarm.major} fillOpacity={0.12} ifOverflow="extendDomain" />)}
        </ComposedChart>
      </ResponsiveContainer>
      <Typography variant="caption" color="text.secondary">Shaded hours use the peak tariff (${formatNumber(peakRate)}/kWh). Demand source: {String(plan.inputs.demand_source ?? '—')} · generated {formatDateTime(plan.created_at)}</Typography>
    </>
  );
}

function DosingPlan({ plan }: { plan: OptimizationPlan }) {
  const p = plan.plan;
  const row = (l: string, v: string) => <TableRow><TableCell sx={{ color: 'text.secondary' }}>{l}</TableCell><TableCell align="right">{v}</TableCell></TableRow>;
  return (
    <Table size="small">
      <TableBody>
        {row('Raw turbidity', `${p.conditions.raw_turbidity_ntu} NTU`)}
        {row('Water temperature', `${p.conditions.water_temperature_c} °C`)}
        {row('Decay rate k', `${p.conditions.decay_k_per_h} /h (${p.conditions.decay_source})`)}
        {row('Coagulant dose', `${p.coagulant.dose_mg_l} mg/L → ${p.coagulant.rate_kg_h} kg/h (now ${p.coagulant.current_kg_h})`)}
        {row('Chlorine setpoint', `${p.chlorine.plant_setpoint_mg_l} mg/L → ${p.chlorine.rate_kg_h} kg/h (now ${p.chlorine.current_kg_h})`)}
        {row('Chemical cost per hour', `$${p.cost_per_hour.recommended} (now $${p.cost_per_hour.current})`)}
      </TableBody>
    </Table>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <Box><Typography variant="caption" color="text.secondary">{label}</Typography><Typography variant="h3" component="p">{value}</Typography></Box>;
}
