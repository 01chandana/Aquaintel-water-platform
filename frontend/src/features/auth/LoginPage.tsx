import { zodResolver } from '@hookform/resolvers/zod';
import { Alert, Button, Link, Stack, TextField, Typography } from '@mui/material';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link as RouterLink, useLocation, useNavigate } from 'react-router-dom';
import type { z } from 'zod';
import { useLoginMutation, useVerifyMfaMutation } from '@/api/authApi';
import { errorMessage } from '@/components/common/States';
import { useAppDispatch } from '@/store';
import { tokensReceived } from '@/store/authSlice';
import type { LoginResult } from '@/types/models';
import { loginSchema } from '@/utils/validators';
import { AuthLayout } from './AuthLayout';

type Form = z.infer<typeof loginSchema>;

export default function LoginPage() {
  const dispatch = useAppDispatch();
  const nav = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? '/dashboard/executive';
  const [login, loginState] = useLoginMutation();
  const [verify, verifyState] = useVerifyMfaMutation();
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const { register, handleSubmit, formState: { errors } } = useForm<Form>({ resolver: zodResolver(loginSchema) });

  const finish = (r: LoginResult) => {
    if (r.tokens) {
      dispatch(tokensReceived(r.tokens));
      nav(from, { replace: true });
    }
  };
  const onSubmit = async (v: Form) => {
    const r = await login(v).unwrap().catch(() => null);
    if (!r) return;
    if (r.mfa_required && r.mfa_token) setMfaToken(r.mfa_token);
    else finish(r);
  };
  const error = loginState.error ?? verifyState.error;

  if (mfaToken) {
    return (
      <AuthLayout title="Two-step verification">
        <Stack component="form" spacing={2} onSubmit={async (e) => { e.preventDefault(); const r = await verify({ mfaToken, code }).unwrap().catch(() => null); if (r) finish(r); }}>
          <Typography variant="body2" color="text.secondary">Enter the 6-digit code from your authenticator app, or a backup code.</Typography>
          {error && <Alert severity="error">{errorMessage(error)}</Alert>}
          <TextField label="Verification code" value={code} onChange={(e) => setCode(e.target.value)} autoFocus inputProps={{ inputMode: 'numeric', autoComplete: 'one-time-code' }} />
          <Button type="submit" variant="contained" disabled={verifyState.isLoading || code.length < 6}>Verify and sign in</Button>
          <Button onClick={() => setMfaToken(null)}>Use a different account</Button>
        </Stack>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout title="Sign in">
      <Stack component="form" spacing={2} onSubmit={handleSubmit(onSubmit)} noValidate>
        {error && <Alert severity="error">{errorMessage(error)}</Alert>}
        <TextField label="Email" type="email" autoComplete="username" autoFocus {...register('email')} error={!!errors.email} helperText={errors.email?.message} />
        <TextField label="Password" type="password" autoComplete="current-password" {...register('password')} error={!!errors.password} helperText={errors.password?.message} />
        <Button type="submit" variant="contained" size="large" disabled={loginState.isLoading}>Sign in</Button>
        <Link component={RouterLink} to="/forgot-password" variant="body2">Forgot your password?</Link>
        <Typography variant="caption" color="text.secondary">
          Demo accounts: operator@aquaintel.io, engineer@aquaintel.io, admin@aquaintel.io (password AquaIntel!2026).
        </Typography>
      </Stack>
    </AuthLayout>
  );
}
