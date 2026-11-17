import { Alert as MuiAlert, Box, Button, CircularProgress, Skeleton, Typography } from '@mui/material';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import type { SerializedError } from '@reduxjs/toolkit';
import type { ReactNode } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import type { ApiErrorBody } from '@/types/api';

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <Box role="status" aria-live="polite" sx={{ display: 'flex', alignItems: 'center', gap: 1.5, p: 3, color: 'text.secondary' }}>
      <CircularProgress size={18} />
      <Typography variant="body2">{label}…</Typography>
    </Box>
  );
}

export function PanelSkeleton({ height = 160 }: { height?: number }) {
  return <Skeleton variant="rounded" height={height} />;
}

export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <Box sx={{ p: 4, textAlign: 'center' }}>
      <Typography variant="subtitle1">{title}</Typography>
      {hint && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 420, mx: 'auto' }}>{hint}</Typography>}
      {action && <Box sx={{ mt: 2 }}>{action}</Box>}
    </Box>
  );
}

type QueryError = FetchBaseQueryError | SerializedError | undefined;

// RTK Query transport failures, translated into something an operator can act on (QA audit AQ-027)
const TRANSPORT: Record<string, string> = {
  FETCH_ERROR: "Can't reach the AquaIntel server. Check the network connection; data refreshes when it is back.",
  TIMEOUT_ERROR: 'The server took too long to answer. Try again in a moment.',
  PARSING_ERROR: 'The server sent an unexpected response. Try again; if it persists, contact the administrator.',
};

export function errorMessage(err: QueryError): string {
  if (!err) return 'Unknown error';
  if ('status' in err) {
    const body = err.data as ApiErrorBody | undefined;
    if (body?.error) {
      const detail = body.error.details?.[0];
      return detail?.field ? `${body.error.message}: ${detail.field} ${detail.message}` : body.error.message;
    }
    if (typeof err.status === 'string') return TRANSPORT[err.status] ?? 'The request failed. Try again.';
    if (err.status >= 500) return 'The server hit an error. Try again; if it persists, contact the administrator.';
    return `Request failed with status ${err.status}`;
  }
  return err.message ?? 'Unknown error';
}

/** True when the API says the record is not there (404) or the id in the URL is malformed (422). */
export const isMissing = (err: QueryError): boolean =>
  !!err && 'status' in err && (err.status === 404 || err.status === 422);

/**
 * What a detail page shows instead of an endless spinner when its record cannot be loaded (QA audit AQ-026):
 * "not found" with a way back for a bad or unknown id, otherwise the error with Retry.
 */
export function LoadFailed({ error, what, backTo, onRetry }: { error: QueryError; what: string; backTo: { label: string; href: string }; onRetry?: () => void }) {
  if (isMissing(error)) {
    return (
      <EmptyState title={`${what} not found`} hint={`The link may be out of date, or the ${what === what.toUpperCase() ? what : what.toLowerCase()} was removed.`}
        action={<Button variant="outlined" component={RouterLink} to={backTo.href}>{backTo.label}</Button>} />
    );
  }
  return <Box sx={{ p: 2 }}><ErrorState error={error} onRetry={onRetry} /></Box>;
}

export function ErrorState({ error, onRetry }: { error: QueryError; onRetry?: () => void }) {
  return (
    <MuiAlert severity="error" action={onRetry && <Button color="inherit" size="small" onClick={onRetry}>Retry</Button>}>
      {errorMessage(error)}
    </MuiAlert>
  );
}
