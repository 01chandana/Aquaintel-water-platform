import { VerifiedUser } from '@mui/icons-material';
import { Alert as MuiAlert, Box, Button, MenuItem, TextField, Tooltip, Typography } from '@mui/material';
import { useState } from 'react';
import { useAuditLogQuery, useVerifyAuditMutation } from '@/api/operationsApi';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { useDebounce } from '@/hooks/useDebounce';
import type { AuditEntry } from '@/types/models';
import { formatDateTime } from '@/utils/formatDate';

export default function AuditLogPage() {
  const [page, setPage] = useState({ page: 1, per_page: 50 });
  const [action, setAction] = useState('');
  const [entity, setEntity] = useState('');
  const search = useDebounce(action);
  const { data, error, refetch } = useAuditLogQuery({ ...page, action: search, entity_type: entity });
  const [verify, v] = useVerifyAuditMutation();
  return (
    <>
      <PageHeader title="Audit log" description="Append-only and hash-chained: each entry includes the hash of the previous one, so any edit or deletion breaks the chain."
        actions={<Button variant="outlined" startIcon={<VerifiedUser />} onClick={() => verify()} disabled={v.isLoading}>Verify chain</Button>} />
      {v.data && (
        <MuiAlert severity={v.data.valid ? 'success' : 'error'} sx={{ mb: 2 }}>
          {v.data.valid ? `Chain intact: ${v.data.checked.toLocaleString()} entries verified. Head ${v.data.head_hash?.slice(0, 16)}…` : `Chain broken at entry ${v.data.broken_at_id}: ${v.data.reason}`}
        </MuiAlert>
      )}
      <Panel title="Entries" actions={<Box sx={{ display: 'flex', gap: 1 }}>
        <TextField size="small" placeholder="Action contains" value={action} onChange={(e) => setAction(e.target.value)} inputProps={{ 'aria-label': 'Filter by action' }} />
        <TextField select size="small" label="Entity" value={entity} onChange={(e) => setEntity(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">Any</MenuItem>
          {['user', 'asset', 'alert', 'alert_rule', 'work_order', 'report', 'ml_model', 'system_config', 'api_key', 'schedule'].map((e) => <MenuItem key={e} value={e}>{e}</MenuItem>)}
        </TextField>
      </Box>}>
        <DataTable<AuditEntry> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(r) => String(r.id)} total={data?.meta.total} {...page} onPage={(p, pp) => setPage({ page: p, per_page: pp })} dense columns={[
          { key: 'id', label: '#', render: (r) => r.id },
          { key: 't', label: 'Time', render: (r) => formatDateTime(r.created_at) },
          { key: 'a', label: 'Actor', render: (r) => r.actor ?? 'system' },
          { key: 'x', label: 'Action', render: (r) => r.action },
          { key: 'e', label: 'Entity', render: (r) => `${r.entity_type}${r.entity_id ? ` ${r.entity_id.slice(0, 8)}` : ''}` },
          { key: 'ip', label: 'Source IP', render: (r) => r.source_ip ?? '—' },
          { key: 'h', label: 'Hash', render: (r) => <Tooltip title={`prev ${r.prev_hash}`}><Typography variant="caption" sx={{ fontFamily: 'monospace' }}>{r.hash.slice(0, 12)}</Typography></Tooltip> },
        ]} />
      </Panel>
    </>
  );
}
