import { Box, Grid, MenuItem, Table, TableBody, TableCell, TableHead, TableRow, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { useState } from 'react';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { useComplianceDailyQuery, useComplianceMonthlyQuery, useExceedancesQuery } from '@/api/reportApi';
import { StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, Loading } from '@/components/common/States';
import { tokens } from '@/theme/palette';
import { formatDateTime, formatDay } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

export default function CompliancePage() {
  const [period, setPeriod] = useState<'daily' | 'monthly'>('monthly');
  const daily = useComplianceDailyQuery(undefined, { skip: period !== 'daily' });
  const monthly = useComplianceMonthlyQuery(undefined, { skip: period !== 'monthly' });
  const data = period === 'daily' ? daily.data : monthly.data;
  const [param, setParam] = useState('');
  const { data: exceed } = useExceedancesQuery({ parameter: param || undefined });
  const series = data?.parameters.find((p) => p.parameter === (param || data.parameters[0]?.parameter))?.series ?? [];
  return (
    <>
      <PageHeader title="Compliance" description="Regulated parameters against SDWA limits: sample coverage, exceedances and compliance rate."
        actions={<ToggleButtonGroup size="small" exclusive value={period} onChange={(_, v) => v && setPeriod(v)}>
          <ToggleButton value="daily">Today</ToggleButton><ToggleButton value="monthly">This month</ToggleButton>
        </ToggleButtonGroup>} />
      {!data ? <Loading /> : (
        <Grid container spacing={2}>
          <Grid item xs={12} md={4}>
            <Panel title="Overall compliance">
              <Typography sx={{ fontSize: 40, fontWeight: 600, color: (data.overall_compliance_pct ?? 100) < 99.5 ? tokens.alarm.major : 'text.primary' }}>
                {formatNumber(data.overall_compliance_pct)}%
              </Typography>
              <Typography variant="body2" color="text.secondary">{data.total_samples.toLocaleString()} samples · {data.total_exceedances} exceedances · target 99.5%</Typography>
            </Panel>
          </Grid>
          <Grid item xs={12} md={8}>
            <Panel title="Daily exceedances" actions={
              <TextField select size="small" value={param || data.parameters[0]?.parameter || ''} onChange={(e) => setParam(e.target.value)} inputProps={{ 'aria-label': 'Parameter' }}>
                {data.parameters.map((p) => <MenuItem key={p.parameter} value={p.parameter}>{p.display_name}</MenuItem>)}
              </TextField>}>
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={series}>
                  <CartesianGrid vertical={false} strokeOpacity={0.15} />
                  <XAxis dataKey="period" tickFormatter={(d) => formatDay(d)} fontSize={11} />
                  <YAxis fontSize={11} allowDecimals={false} />
                  <Tooltip labelFormatter={(d) => formatDay(String(d))} />
                  <Bar dataKey="exceedances" fill={tokens.alarm.major} name="Exceedances" />
                </BarChart>
              </ResponsiveContainer>
            </Panel>
          </Grid>
          <Grid item xs={12}>
            <Panel title="Parameters">
              <Table size="small">
                <TableHead><TableRow>
                  <TableCell>Parameter</TableCell><TableCell>Regulation</TableCell><TableCell align="right">Limit</TableCell><TableCell align="right">Samples</TableCell>
                  <TableCell align="right">Coverage</TableCell><TableCell align="right">Exceedances</TableCell><TableCell align="right">Compliance</TableCell><TableCell>Status</TableCell>
                </TableRow></TableHead>
                <TableBody>
                  {data.parameters.map((p) => (
                    <TableRow key={p.parameter}>
                      <TableCell>{p.display_name}</TableCell>
                      <TableCell>{p.regulation}</TableCell>
                      <TableCell align="right">{p.limit_min !== null ? `${p.limit_min}–` : '≤ '}{p.limit_max ?? '—'} {p.unit}</TableCell>
                      <TableCell align="right">{p.samples.toLocaleString()}</TableCell>
                      <TableCell align="right">{formatNumber(p.coverage_pct)}%</TableCell>
                      <TableCell align="right">{p.exceedances}</TableCell>
                      <TableCell align="right">{formatNumber(p.compliance_pct)}%</TableCell>
                      <TableCell><StatusChip status={p.status === 'compliant' ? 'resolved' : 'triggered'} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Panel>
          </Grid>
          <Grid item xs={12}>
            <Panel title="Exceedance log" subtitle="Last 30 days">
              {!exceed?.length ? <EmptyState title="No exceedances" /> : (
                <Box sx={{ maxHeight: 360, overflow: 'auto' }}>
                  <Table size="small" stickyHeader>
                    <TableHead><TableRow><TableCell>Time</TableCell><TableCell>Location</TableCell><TableCell>Tag</TableCell><TableCell align="right">Value</TableCell><TableCell>Limit</TableCell></TableRow></TableHead>
                    <TableBody>
                      {exceed.map((e, i) => (
                        <TableRow key={i}>
                          <TableCell>{formatDateTime(e.time)}</TableCell><TableCell>{e.asset_name}</TableCell><TableCell>{e.tag}</TableCell>
                          <TableCell align="right" sx={{ fontWeight: 600 }}>{formatNumber(e.value, e.unit)}</TableCell>
                          <TableCell>{e.type === 'above_max' ? `max ${e.limit_max}` : `min ${e.limit_min}`} ({e.regulation})</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </Box>
              )}
            </Panel>
          </Grid>
        </Grid>
      )}
    </>
  );
}
