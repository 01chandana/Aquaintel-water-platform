import { Box, Chip, type ChipProps } from '@mui/material';
import { severityColor, statusColor, tokens } from '@/theme/palette';

export function SeverityChip({ severity, ...rest }: { severity: string } & ChipProps) {
  const c = severityColor(severity);
  return (
    <Chip size="small" label={severity} {...rest}
      sx={{ bgcolor: `${c}22`, color: c, border: `1px solid ${c}66`, textTransform: 'capitalize', ...rest.sx }} />
  );
}

const STATUS_TONE: Record<string, string> = {
  triggered: tokens.alarm.critical, escalated: tokens.alarm.major, acknowledged: tokens.alarm.info,
  investigating: tokens.alarm.info, resolved: tokens.alarm.normal, closed: tokens.alarm.normal,
  open: tokens.alarm.major, assigned: tokens.alarm.info, in_progress: tokens.alarm.info, completed: tokens.alarm.normal,
  cancelled: tokens.alarm.normal, production: tokens.brand, staging: tokens.alarm.info, archived: tokens.alarm.normal,
  none: tokens.alarm.normal, pending: tokens.alarm.info, running: tokens.alarm.info, failed: tokens.alarm.critical,
  active: tokens.alarm.normal, maintenance: tokens.alarm.major, inactive: tokens.alarm.normal,
  proposed: tokens.alarm.info, approved: tokens.brand,
};

export function StatusChip({ status }: { status: string }) {
  const c = STATUS_TONE[status] ?? tokens.alarm.normal;
  return <Chip size="small" variant="outlined" label={status.replace('_', ' ')} sx={{ color: c, borderColor: `${c}88`, textTransform: 'capitalize' }} />;
}

/** Small status dot; colour only when abnormal (ISA-101). */
export function StatusDot({ status, size = 8 }: { status: string; size?: number }) {
  return <Box component="span" aria-hidden sx={{ display: 'inline-block', width: size, height: size, borderRadius: '50%', bgcolor: statusColor(status), flexShrink: 0 }} />;
}
