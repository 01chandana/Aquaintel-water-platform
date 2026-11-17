import { Box, Button, Grid, InputAdornment, TextField, Typography } from '@mui/material';
import { Search } from '@mui/icons-material';
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAssetTreeQuery } from '@/api/assetApi';
import { StatusChip } from '@/components/common/Chips';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, ErrorState, Loading } from '@/components/common/States';
import { AlertList } from '@/components/widgets/AlertList';
import { AssetTree } from '@/components/widgets/AssetTree';
import { TelemetryTable } from '@/components/widgets/TelemetryTable';
import { useDebounce } from '@/hooks/useDebounce';
import type { AssetNode } from '@/types/models';

export default function AssetsPage() {
  const { data, isLoading, error } = useAssetTreeQuery();
  const [selected, setSelected] = useState<AssetNode | null>(null);
  const [q, setQ] = useState('');
  const filter = useDebounce(q);
  const nav = useNavigate();
  return (
    <>
      <PageHeader title="Assets" description="Plants, process areas and equipment. Counts show open alerts rolled up through the hierarchy." />
      <Grid container spacing={2}>
        <Grid item xs={12} md={5} lg={4}>
          <Panel title="Hierarchy">
            <TextField size="small" placeholder="Filter by name or tag" value={q} onChange={(e) => setQ(e.target.value)} sx={{ mb: 1 }}
              InputProps={{ startAdornment: <InputAdornment position="start"><Search fontSize="small" /></InputAdornment> }} inputProps={{ 'aria-label': 'Filter assets' }} />
            {error && <ErrorState error={error} />}
            {isLoading ? <Loading /> : <Box sx={{ maxHeight: '70vh', overflow: 'auto' }}><AssetTree nodes={data ?? []} selectedId={selected?.id} onSelect={setSelected} filter={filter} /></Box>}
          </Panel>
        </Grid>
        <Grid item xs={12} md={7} lg={8}>
          {!selected ? <Panel><EmptyState title="Select an asset" hint="Choose an asset in the hierarchy to see its live values and alerts." /></Panel> : (
            <Panel title={selected.name} subtitle={selected.path}
              actions={<Button variant="outlined" size="small" onClick={() => nav(`/assets/${selected.id}`)}>Open asset</Button>}>
              <Box sx={{ display: 'flex', gap: 2, mb: 2, flexWrap: 'wrap' }}>
                <StatusChip status={selected.status} />
                <Typography variant="body2" color="text.secondary">{selected.asset_type?.name}</Typography>
                <Typography variant="body2" color="text.secondary">Tag {selected.external_id}</Typography>
              </Box>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>Live values</Typography>
              {selected.children.length === 0 ? <TelemetryTable assetId={selected.id} height={300} /> : (
                <Typography variant="body2" color="text.secondary">{selected.children.length} child assets. Select one to see its telemetry.</Typography>
              )}
              <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Open alerts</Typography>
              <AlertList assetId={selected.children.length ? undefined : selected.id} limit={6} />
            </Panel>
          )}
        </Grid>
      </Grid>
    </>
  );
}
