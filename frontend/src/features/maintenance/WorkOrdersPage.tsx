import { zodResolver } from '@hookform/resolvers/zod';
import { Add } from '@mui/icons-material';
import { Alert as MuiAlert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import type { z } from 'zod';
import { useAssetsQuery } from '@/api/assetApi';
import { useAssignWorkOrderMutation, useCompleteWorkOrderMutation, useCreateWorkOrderMutation, useUpdateWorkOrderMutation, useUsersQuery, useWorkOrdersQuery } from '@/api/operationsApi';
import { StatusChip } from '@/components/common/Chips';
import { DataTable } from '@/components/common/DataTable';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { errorMessage } from '@/components/common/States';
import { usePermissions } from '@/hooks/usePermissions';
import type { WorkOrder } from '@/types/models';
import { formatDateTime } from '@/utils/formatDate';
import { completeWorkOrderSchema } from '@/utils/validators';

const STATUS_FILTERS = [{ v: 'open,assigned,in_progress', l: 'Open' }, { v: 'completed', l: 'Completed' }, { v: '', l: 'All' }];

export default function WorkOrdersPage() {
  const [status, setStatus] = useState('open,assigned,in_progress');
  const [type, setType] = useState('');
  const [page, setPage] = useState({ page: 1, per_page: 25 });
  const { data, error, refetch } = useWorkOrdersQuery({ ...page, status, wo_type: type });
  const [selected, setSelected] = useState<WorkOrder | null>(null);
  const [creating, setCreating] = useState(false);
  return (
    <>
      <PageHeader title="Work orders" description="Corrective, preventive, predictive and audit-finding work. Completing a work order resolves its linked alert and returns the asset to service."
        actions={<Button variant="contained" startIcon={<Add />} onClick={() => setCreating(true)}>New work order</Button>} />
      <Panel actions={<Box sx={{ display: 'flex', gap: 1 }}>
        <TextField select size="small" label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUS_FILTERS.map((s) => <MenuItem key={s.l} value={s.v}>{s.l}</MenuItem>)}</TextField>
        <TextField select size="small" label="Type" value={type} onChange={(e) => setType(e.target.value)} sx={{ minWidth: 150 }}>
          <MenuItem value="">Any</MenuItem>{['corrective', 'preventive', 'predictive', 'inspection', 'audit_finding'].map((t) => <MenuItem key={t} value={t}>{t.replace('_', ' ')}</MenuItem>)}
        </TextField>
      </Box>} title="Work">
        <DataTable<WorkOrder> rows={data?.items ?? []} error={error} onRetry={refetch} rowKey={(w) => w.id} total={data?.meta.total} {...page} onPage={(p, pp) => setPage({ page: p, per_page: pp })}
          onRowClick={setSelected} dense columns={[
            { key: 'n', label: 'Number', render: (w) => w.number },
            { key: 't', label: 'Title', render: (w) => <Typography variant="body2" noWrap sx={{ maxWidth: 340 }}>{w.title}</Typography> },
            { key: 'a', label: 'Asset', render: (w) => w.asset_name },
            { key: 'ty', label: 'Type', render: (w) => w.wo_type.replace('_', ' ') },
            { key: 'p', label: 'Priority', render: (w) => w.priority },
            { key: 's', label: 'Status', render: (w) => <StatusChip status={w.status} /> },
            { key: 'd', label: 'Due', render: (w) => formatDateTime(w.due_date) },
          ]} />
      </Panel>
      {selected && <WorkOrderDialog wo={selected} onClose={() => setSelected(null)} />}
      {creating && <CreateDialog onClose={() => setCreating(false)} />}
    </>
  );
}

function CreateDialog({ onClose }: { onClose: () => void }) {
  const { data: assets } = useAssetsQuery({ per_page: 500 });
  const [create, { error }] = useCreateWorkOrderMutation();
  const [f, setF] = useState({ asset_id: '', title: '', description: '', wo_type: 'corrective', priority: 'medium' });
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>New work order</DialogTitle>
      <DialogContent sx={{ display: 'grid', gap: 2, pt: '8px !important' }}>
        {error && <MuiAlert severity="error">{errorMessage(error)}</MuiAlert>}
        <TextField select label="Asset" value={f.asset_id} onChange={(e) => setF({ ...f, asset_id: e.target.value })}>
          {assets?.items.filter((a) => a.parent_id).map((a) => <MenuItem key={a.id} value={a.id}>{a.name} ({a.external_id})</MenuItem>)}
        </TextField>
        <TextField label="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <TextField label="Description" multiline minRows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} />
        <Box sx={{ display: 'flex', gap: 2 }}>
          <TextField select fullWidth label="Type" value={f.wo_type} onChange={(e) => setF({ ...f, wo_type: e.target.value })}>
            {['corrective', 'preventive', 'predictive', 'inspection'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </TextField>
          <TextField select fullWidth label="Priority" value={f.priority} onChange={(e) => setF({ ...f, priority: e.target.value })}>
            {['low', 'medium', 'high', 'urgent'].map((t) => <MenuItem key={t} value={t}>{t}</MenuItem>)}
          </TextField>
        </Box>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={!f.asset_id || f.title.length < 3} onClick={async () => { if (await create(f).unwrap().then(() => true).catch(() => false)) onClose(); }}>Create work order</Button>
      </DialogActions>
    </Dialog>
  );
}

function WorkOrderDialog({ wo, onClose }: { wo: WorkOrder; onClose: () => void }) {
  const { can } = usePermissions();
  const { data: techs } = useUsersQuery({ role: 'technician', per_page: 100 }, { skip: !can('users:manage') });
  const [assign] = useAssignWorkOrderMutation();
  const [update] = useUpdateWorkOrderMutation();
  const [complete, cState] = useCompleteWorkOrderMutation();
  const { register, handleSubmit, formState: { errors } } = useForm<z.input<typeof completeWorkOrderSchema>, unknown, z.output<typeof completeWorkOrderSchema>>({ resolver: zodResolver(completeWorkOrderSchema), defaultValues: { labor_hours: 1 } });
  const open = !['completed', 'cancelled'].includes(wo.status);
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{wo.number}: {wo.title}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>{wo.asset_name} · {wo.wo_type} · {wo.priority} priority · created {formatDateTime(wo.created_at)}</Typography>
        {wo.description && <Typography variant="body2" sx={{ mb: 2 }}>{wo.description}</Typography>}
        {cState.error && <MuiAlert severity="error" sx={{ mb: 2 }}>{errorMessage(cState.error)}</MuiAlert>}
        {open ? (
          <Box sx={{ display: 'grid', gap: 2 }}>
            {can('work_orders:assign') && techs && (
              <TextField select size="small" label="Assign technician" value={wo.assigned_to ?? ''} onChange={(e) => assign({ id: wo.id, assigned_to: e.target.value })}>
                {techs.items.map((t) => <MenuItem key={t.id} value={t.id}>{t.display_name}</MenuItem>)}
              </TextField>
            )}
            {wo.status !== 'in_progress' && <Button variant="outlined" onClick={() => update({ id: wo.id, body: { status: 'in_progress' } })}>Start work (puts asset in maintenance)</Button>}
            {can('work_orders:complete') && <>
              <TextField size="small" label="Resolution notes" multiline minRows={2} {...register('resolution_notes')} error={!!errors.resolution_notes} helperText={errors.resolution_notes?.message} />
              <Box sx={{ display: 'flex', gap: 2 }}>
                <TextField size="small" label="Labour hours" type="number" {...register('labor_hours')} />
                <TextField size="small" label="Cost ($)" type="number" {...register('cost')} />
                <TextField size="small" label="Failure code" {...register('failure_code')} helperText="Feeds model retraining" />
              </Box>
            </>}
          </Box>
        ) : <Typography variant="body2">Completed {formatDateTime(wo.completed_at)}. {wo.failure_code && `Failure code ${wo.failure_code}.`}</Typography>}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
        {open && can('work_orders:complete') && (
          <Button variant="contained" onClick={handleSubmit(async (v) => { if (await complete({ id: wo.id, body: v }).unwrap().then(() => true).catch(() => false)) onClose(); })}>Mark complete</Button>
        )}
      </DialogActions>
    </Dialog>
  );
}
