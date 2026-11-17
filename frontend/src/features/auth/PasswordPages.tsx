import { Alert, Button, Link, Stack, TextField } from '@mui/material';
import { useState } from 'react';
import { Link as RouterLink, useNavigate, useSearchParams } from 'react-router-dom';
import { useForgotPasswordMutation, useResetPasswordMutation } from '@/api/authApi';
import { errorMessage } from '@/components/common/States';
import { passwordSchema } from '@/utils/validators';
import { AuthLayout } from './AuthLayout';

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [send, { isSuccess, isLoading, error }] = useForgotPasswordMutation();
  return (
    <AuthLayout title="Reset your password">
      <Stack component="form" spacing={2} onSubmit={(e) => { e.preventDefault(); send(email); }}>
        {isSuccess && <Alert severity="success">If an account exists for {email}, a reset token has been sent.</Alert>}
        {error && <Alert severity="error">{errorMessage(error)}</Alert>}
        <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <Button type="submit" variant="contained" disabled={isLoading}>Send reset token</Button>
        <Link component={RouterLink} to="/reset-password" variant="body2">I already have a token</Link>
        <Link component={RouterLink} to="/login" variant="body2">Back to sign in</Link>
      </Stack>
    </AuthLayout>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const nav = useNavigate();
  const [token, setToken] = useState(params.get('token') ?? '');
  const [pw, setPw] = useState('');
  const [reset, { isLoading, error }] = useResetPasswordMutation();
  const check = passwordSchema.safeParse(pw);
  return (
    <AuthLayout title="Choose a new password">
      <Stack component="form" spacing={2} onSubmit={async (e) => { e.preventDefault(); if (await reset({ token, new_password: pw }).unwrap().then(() => true).catch(() => false)) nav('/login'); }}>
        {error && <Alert severity="error">{errorMessage(error)}</Alert>}
        <TextField label="Reset token" value={token} onChange={(e) => setToken(e.target.value)} required />
        <TextField label="New password" type="password" value={pw} onChange={(e) => setPw(e.target.value)} error={!!pw && !check.success}
          helperText={pw && !check.success ? check.error.issues[0].message : 'At least 10 characters, one uppercase letter and one digit'} />
        <Button type="submit" variant="contained" disabled={isLoading || !check.success || !token}>Update password</Button>
      </Stack>
    </AuthLayout>
  );
}
