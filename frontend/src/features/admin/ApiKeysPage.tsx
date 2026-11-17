import { Add } from '@mui/icons-material';
import { Alert as MuiAlert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useApiKeysQuery, useCreateApiKeyMutation, useRevokeApiKeyMutation } from '@/api/operationsApi';
import { StatusChip } from '@/components/common/Chips';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage } from '@/components/common/States';
import type { ApiKey } from '@/types/models';
import { formatDateTime } from '@/utils/formatDate';

const SCOPES = ['telemetry:ingest', 'telemetry:read', 'assets:read', 'alerts:read', 'kpis:read'];

export default function ApiKeysPage() {
  const { data, error, refetch } = useApiKeysQuery();
  const [revoke] = useRevokeApiKeyMutation();
  const [creating, setCreating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  return (
    <>
      <PageHeader title="API keys" description="Credentials for SCADA gateways, protocol adapters and other systems. Keys are scoped, rate limited, stored hashed and expire after 90 days by default."
        actions={<Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>Create key</Button>} />
      <Panel>
        <DataTable<ApiKey> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(k) => k.id} dense columns={[
          { key: 'n', label: 'Name', render: (k) => k.name },
          { key: 'p', label: 'Prefix', render: (k) => <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>{k.key_prefix}…</Typography> },
          { key: 's', label: 'Permissions', render: (k) => k.permissions.join(', ') },
          { key: 'u', label: 'Last used', render: (k) => formatDateTime(k.last_used_at) },
          { key: 'e', label: 'Expires', render: (k) => formatDateTime(k.expires_at) },
          { key: 'st', label: 'Status', render: (k) => <StatusChip status={k.revoked ? 'cancelled' : 'active'} /> },
          { key: 'a', label: '', align: 'right', render: (k) => !k.revoked && <Button size="small" color="error" onClick={() => setRevoking(k)}>Revoke</Button> },
        ]} />
      </Panel>
      {creating && <CreateKey onClose={() => setCreating(false)} />}
      <ConfirmDialog open={!!revoking} danger title="Revoke key" confirmLabel="Revoke key" body={`Systems using "${revoking?.name}" stop authenticating immediately.`}
        onClose={() => setRevoking(null)} onConfirm={() => revoking && revoke(revoking.id)} />
    </>
  );
}

function CreateKey({ onClose }: { onClose: () => void }) {
  const [create, { data, error }] = useCreateApiKeyMutation();
  const [name, setName] = useState('');
  const [perms, setPerms] = useState<Set<string>>(new Set(['telemetry:ingest']));
  const [scopes, setScopes] = useState('');
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Create API key</DialogTitle>
      <DialogContent sx={{ display: 'grid', gap: 2, pt: '8px !important' }}>
        {error && <MuiAlert severity="error">{errorMessage(error)}</MuiAlert>}
        {data?.api_key ? (
          <>
            <MuiAlert severity="warning">Copy this key now. It is shown only once and stored only as a hash.</MuiAlert>
            <TextField value={data.api_key} InputProps={{ readOnly: true, sx: { fontFamily: 'monospace' } }} onFocus={(e) => e.target.select()} />
          </>
        ) : (
          <>
            <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} helperText="Which system will use it, e.g. plant-a-scada-gateway" />
            <Box>{SCOPES.map((s) => (
              <FormControlLabel key={s} label={s} control={<Checkbox checked={perms.has(s)} onChange={() => { const n = new Set(perms); if (n.has(s)) n.delete(s); else n.add(s); setPerms(n); }} />} />
            ))}</Box>
            <TextField label="Asset scopes" value={scopes} onChange={(e) => setScopes(e.target.value)} helperText="Optional, comma separated, e.g. plant_a/*" />
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{data ? 'Done' : 'Cancel'}</Button>
        {!data && <Button variant="contained" disabled={name.length < 3 || !perms.size}
          onClick={() => create({ name, permissions: [...perms], asset_scopes: scopes.split(',').map((s) => s.trim()).filter(Boolean), expires_in_days: 90 })}>Create key</Button>}
      </DialogActions>
    </Dialog>
  );
}
