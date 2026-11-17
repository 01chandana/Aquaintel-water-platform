import { InputAdornment, MenuItem, TextField } from '@mui/material';
import { Search } from '@mui/icons-material';
import { useState } from 'react';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { TelemetryTable } from '@/components/widgets/TelemetryTable';
import { useDebounce } from '@/hooks/useDebounce';
import { useAppSelector } from '@/store';
import { timeAgo } from '@/utils/formatDate';

const PARAMS = ['', 'flow', 'production_flow', 'discharge_pressure', 'pressure', 'power_kw', 'vibration', 'bearing_temperature', 'chlorine', 'turbidity', 'ph', 'tank_level'];

export default function LiveTelemetryPage() {
  const [param, setParam] = useState('');
  const [q, setQ] = useState('');
  const filter = useDebounce(q);
  const last = useAppSelector((s) => s.ui.lastTelemetryAt);
  return (
    <>
      <PageHeader title="Live telemetry" description={`Latest value of every tag. Rows update in place as samples are processed${last ? ` (last push ${timeAgo(last)})` : ''}.`} />
      <Panel actions={<>
        <TextField size="small" placeholder="Filter tags" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ 'aria-label': 'Filter tags' }}
          InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} />
        <TextField select size="small" label="Parameter" value={param} onChange={(e) => setParam(e.target.value)} sx={{ minWidth: 180 }}>
          {PARAMS.map((p) => <MenuItem key={p} value={p}>{p ? p.replace(/_/g, ' ') : 'All parameters'}</MenuItem>)}
        </TextField>
      </>} title="Tags">
        <TelemetryTable parameter={param || undefined} filter={filter} height={640} />
      </Panel>
    </>
  );
}
