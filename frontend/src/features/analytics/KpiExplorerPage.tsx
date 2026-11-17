import { Add } from '@mui/icons-material';
import { Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, Grid, InputAdornment, MenuItem, Paper, TextField, ToggleButton, ToggleButtonGroup, Typography } from '@mui/material';
import { Search } from '@mui/icons-material';
import { useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import { useCreateKpiMutation, useKpisQuery } from '@/api/kpiApi';
import { PageHeader } from '@/components/common/PageHeader';
import { errorMessage, Loading } from '@/components/common/States';
import { useDebounce } from '@/hooks/useDebounce';
import { usePermissions } from '@/hooks/usePermissions';
import { KPI_CATEGORIES } from '@/utils/constants';

export default function KpiExplorerPage() {
  const [cat, setCat] = useState<string>('');
  const [q, setQ] = useState('');
  const search = useDebounce(q);
  const { data, isLoading } = useKpisQuery({ category: cat || undefined, q: search || undefined });
  const [open, setOpen] = useState(false);
  const { can } = usePermissions();
  return (
    <>
      <PageHeader title="KPI explorer" description="The 30-KPI catalogue across six categories, plus any custom KPIs your engineers define. Each KPI has a formula, thresholds and an alert condition."
        actions={can('kpis:write') && <Button startIcon={<Add />} variant="contained" onClick={() => setOpen(true)}>New custom KPI</Button>} />
      <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
        <ToggleButtonGroup size="small" exclusive value={cat} onChange={(_, v) => setCat(v ?? '')} aria-label="Category">
          <ToggleButton value="">All</ToggleButton>
          {KPI_CATEGORIES.map((c) => <ToggleButton key={c} value={c} sx={{ textTransform: 'capitalize' }}>{c}</ToggleButton>)}
        </ToggleButtonGroup>
        <TextField size="small" placeholder="Search KPIs" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ 'aria-label': 'Search KPIs' }}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
      </Box>
      {isLoading ? <Loading /> : (
        <Grid container spacing={1.5}>
          {data?.map((k) => (
            <Grid item xs={12} sm={6} lg={4} key={k.id}>
              <Paper component={RouterLink} to={`/analytics/kpis/${k.id}`} sx={{ p: 2, display: 'block', textDecoration: 'none', color: 'inherit', height: '100%', '&:hover': { borderColor: 'text.secondary' } }}>
                <Box sx={{ display: 'flex', gap: 1, alignItems: 'baseline' }}>
                  <Typography variant="body2" color="text.secondary" sx={{ width: 24 }}>{k.number ?? '·'}</Typography>
                  <Typography variant="subtitle1" sx={{ flex: 1 }}>{k.name}</Typography>
                  <Chip size="small" variant="outlined" label={k.category} sx={{ textTransform: 'capitalize' }} />
                </Box>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1, pl: 4 }}>{k.formula}</Typography>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1, pl: 4 }}>
                  {k.threshold_warning !== null ? `Warning ${k.higher_is_better ? '<' : '>'} ${k.threshold_warning} · critical ${k.higher_is_better ? '<' : '>'} ${k.threshold_critical} ${k.unit}` : `Unit: ${k.unit}`}
                </Typography>
              </Paper>
            </Grid>
          ))}
        </Grid>
      )}
      {open && <CreateKpiDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function CreateKpiDialog({ onClose }: { onClose: () => void }) {
  const [create, { error, isLoading }] = useCreateKpiMutation();
  const [f, setF] = useState({ code: '', name: '', source_parameter: 'ph', aggregation_type: 'avg', unit: '', category: 'quality', threshold_warning: '', threshold_critical: '', higher_is_better: 'true' });
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>New custom KPI</DialogTitle>
      <DialogContent sx={{ display: 'grid', gap: 2, gridTemplateColumns: '1fr 1fr', pt: '8px !important' }}>
        {error && <Typography color="error" sx={{ gridColumn: '1 / -1' }}>{errorMessage(error)}</Typography>}
        <TextField label="Code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_') })} helperText="e.g. AVG_RAW_TURBIDITY" />
        <TextField label="Name" value={f.name} onChange={set('name')} />
        <TextField label="Telemetry parameter" value={f.source_parameter} onChange={set('source_parameter')} helperText="e.g. raw_turbidity, ph, tank_level" />
        <TextField select label="Aggregation" value={f.aggregation_type} onChange={set('aggregation_type')}>
          {['avg', 'min', 'max', 'sum', 'count', 'time_weighted'].map((a) => <MenuItem key={a} value={a}>{a}</MenuItem>)}
        </TextField>
        <TextField label="Unit" value={f.unit} onChange={set('unit')} />
        <TextField select label="Category" value={f.category} onChange={set('category')}>{KPI_CATEGORIES.map((c) => <MenuItem key={c} value={c}>{c}</MenuItem>)}</TextField>
        <TextField label="Warning threshold" type="number" value={f.threshold_warning} onChange={set('threshold_warning')} />
        <TextField label="Critical threshold" type="number" value={f.threshold_critical} onChange={set('threshold_critical')} />
        <TextField select label="Better when" value={f.higher_is_better} onChange={set('higher_is_better')}><MenuItem value="true">Higher</MenuItem><MenuItem value="false">Lower</MenuItem></TextField>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={isLoading || !f.code || !f.name || !f.unit}
          onClick={async () => {
            const ok = await create({ ...f, formula: `${f.aggregation_type}(${f.source_parameter})`, higher_is_better: f.higher_is_better === 'true',
              threshold_warning: f.threshold_warning === '' ? null : Number(f.threshold_warning), threshold_critical: f.threshold_critical === '' ? null : Number(f.threshold_critical) })
              .unwrap().then(() => true).catch(() => false);
            if (ok) onClose();
          }}>Create KPI</Button>
      </DialogActions>
    </Dialog>
  );
}
