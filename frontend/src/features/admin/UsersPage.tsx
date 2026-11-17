import { zodResolver } from '@hookform/resolvers/zod';
import { Add } from '@mui/icons-material';
import { Alert as MuiAlert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Switch, TextField } from '@mui/material';
import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';
import type { z } from 'zod';
import { useAssignRoleMutation, useCreateUserMutation, useUpdateUserMutation, useUsersQuery } from '@/api/operationsApi';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage } from '@/components/common/States';
import { useDebounce } from '@/hooks/useDebounce';
import type { User } from '@/types/models';
import { ROLE_LABELS } from '@/utils/constants';
import { formatDateTime } from '@/utils/formatDate';
import { userSchema } from '@/utils/validators';

export default function UsersPage() {
  const [q, setQ] = useState('');
  const [page, setPage] = useState({ page: 1, per_page: 25 });
  const search = useDebounce(q);
  const { data, error: loadError, refetch } = useUsersQuery({ ...page, q: search });
  const [assign] = useAssignRoleMutation();
  const [update] = useUpdateUserMutation();
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Users" description="Accounts, roles and asset scopes. Deactivated users keep their audit history." actions={<Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>Add user</Button>} />
      <Panel title="Accounts" actions={<TextField size="small" placeholder="Search users" value={q} onChange={(e) => setQ(e.target.value)} inputProps={{ 'aria-label': 'Search users' }} />}>
        <DataTable<User> rows={data?.items ?? []} error={loadError} onRetry={refetch} rowKey={(u) => u.id} total={data?.meta.total} {...page} onPage={(p, pp) => setPage({ page: p, per_page: pp })} dense columns={[
          { key: 'n', label: 'Name', render: (u) => u.display_name },
          { key: 'e', label: 'Email', render: (u) => u.email },
          { key: 'r', label: 'Role', render: (u) => (
            <TextField select size="small" value={u.role} onChange={(e) => assign({ id: u.id, role: e.target.value })} variant="standard" inputProps={{ 'aria-label': `Role for ${u.email}` }}>
              {Object.entries(ROLE_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}
            </TextField>) },
          { key: 's', label: 'Scope', render: (u) => (u.asset_scopes.length ? u.asset_scopes.join(', ') : 'All sites') },
          { key: 'm', label: 'MFA', render: (u) => (u.mfa_enabled ? 'On' : 'Off') },
          { key: 'l', label: 'Last sign-in', render: (u) => formatDateTime(u.last_login) },
          { key: 'a', label: 'Active', render: (u) => <Switch size="small" checked={u.is_active} onChange={() => update({ id: u.id, body: { is_active: !u.is_active } })} inputProps={{ 'aria-label': `Active ${u.email}` }} /> },
        ]} />
      </Panel>
      {creating && <CreateUser onClose={() => setCreating(false)} />}
    </>
  );
}

function CreateUser({ onClose }: { onClose: () => void }) {
  const [create, { error }] = useCreateUserMutation();
  const { register, handleSubmit, control, formState: { errors } } = useForm<z.infer<typeof userSchema>>({ resolver: zodResolver(userSchema), defaultValues: { role: 'operator' } });
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Add user</DialogTitle>
      <DialogContent sx={{ display: 'grid', gap: 2, pt: '8px !important' }}>
        {error && <MuiAlert severity="error">{errorMessage(error)}</MuiAlert>}
        <TextField label="Name" {...register('display_name')} error={!!errors.display_name} helperText={errors.display_name?.message} />
        <TextField label="Email" {...register('email')} error={!!errors.email} helperText={errors.email?.message} />
        <TextField label="Temporary password" type="password" {...register('password')} error={!!errors.password} helperText={errors.password?.message ?? 'At least 10 characters, one uppercase letter and one digit'} />
        <Controller name="role" control={control} render={({ field }) => (
          <TextField select label="Role" {...field}>{Object.entries(ROLE_LABELS).map(([k, v]) => <MenuItem key={k} value={k}>{v}</MenuItem>)}</TextField>)} />
        <TextField label="Asset scopes" {...register('asset_scopes')} helperText="Comma separated, e.g. plant_a/*. Leave empty for all sites." />
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit(async (v) => {
          const ok = await create({ ...v, asset_scopes: (v.asset_scopes ?? '').split(',').map((s) => s.trim()).filter(Boolean) }).unwrap().then(() => true).catch(() => false);
          if (ok) onClose();
        })}>Add user</Button>
      </DialogActions>
    </Dialog>
  );
}
