import { Alert, Box, Button, Chip, Grid, Stack, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useConfirmMfaMutation, useMeQuery, useSetupMfaMutation, useUpdateMeMutation } from '@/api/authApi';
import { Panel } from '@/components/common/Panel';
import { PageHeader } from '@/components/common/PageHeader';
import { errorMessage } from '@/components/common/States';
import { ROLE_LABELS } from '@/utils/constants';

export default function ProfilePage() {
  const { data: me } = useMeQuery();
  const [setup, setupState] = useSetupMfaMutation();
  const [confirm, confirmState] = useConfirmMfaMutation();
  const [update, updateState] = useUpdateMeMutation();
  const [code, setCode] = useState('');
  const [pw, setPw] = useState({ current: '', next: '' });
  if (!me) return null;
  return (
    <>
      <PageHeader title="Profile & security" description="Your account, permissions and sign-in protection." />
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <Panel title={me.display_name} subtitle={me.email}>
            <Typography variant="body2">Role: {ROLE_LABELS[me.role]}</Typography>
            <Typography variant="body2" sx={{ mt: 0.5 }}>Asset scope: {me.asset_scopes.length ? me.asset_scopes.join(', ') : 'all sites'}</Typography>
            <Typography variant="subtitle2" sx={{ mt: 2, mb: 1 }}>Permissions</Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>{me.permissions?.map((p) => <Chip key={p} label={p} size="small" variant="outlined" />)}</Box>
          </Panel>
        </Grid>
        <Grid item xs={12} md={6}>
          <Stack spacing={2}>
            <Panel title="Two-step verification" subtitle={me.mfa_enabled ? 'Enabled with an authenticator app.' : 'Required for admin roles. Uses TOTP codes from an authenticator app.'}>
              {!me.mfa_enabled && !setupState.data && <Button variant="outlined" onClick={() => setup()}>Set up authenticator</Button>}
              {setupState.data && !me.mfa_enabled && (
                <Stack spacing={1.5}>
                  <Typography variant="body2">Add this key to your authenticator app, then enter the code it shows.</Typography>
                  <TextField label="Setup key" value={setupState.data.secret} InputProps={{ readOnly: true }} size="small" />
                  <Typography variant="body2">Backup codes (store them safely; each works once):</Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 0.5 }}>
                    {setupState.data.backup_codes.map((c) => <Typography key={c} variant="body2" sx={{ fontFamily: 'monospace' }}>{c}</Typography>)}
                  </Box>
                  <Box sx={{ display: 'flex', gap: 1 }}>
                    <TextField size="small" label="6-digit code" value={code} onChange={(e) => setCode(e.target.value)} />
                    <Button variant="contained" onClick={() => confirm(code)} disabled={code.length !== 6}>Turn on</Button>
                  </Box>
                  {confirmState.error && <Alert severity="error">{errorMessage(confirmState.error)}</Alert>}
                </Stack>
              )}
            </Panel>
            <Panel title="Change password">
              <Stack spacing={1.5}>
                {updateState.isSuccess && <Alert severity="success">Password updated.</Alert>}
                {updateState.error && <Alert severity="error">{errorMessage(updateState.error)}</Alert>}
                <TextField size="small" type="password" label="Current password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
                <TextField size="small" type="password" label="New password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
                <Button variant="outlined" disabled={!pw.current || !pw.next} onClick={() => update({ current_password: pw.current, new_password: pw.next })}>Update password</Button>
              </Stack>
            </Panel>
          </Stack>
        </Grid>
      </Grid>
    </>
  );
}
