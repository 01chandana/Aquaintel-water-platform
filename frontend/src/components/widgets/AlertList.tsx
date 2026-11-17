import { Box, List, ListItemButton, ListItemText, Typography } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import { useAlertsQuery } from '@/api/alertApi';
import { SeverityChip } from '@/components/common/Chips';
import { EmptyState, Loading } from '@/components/common/States';
import { usePolling } from '@/hooks/usePolling';
import { timeAgo } from '@/utils/formatDate';

export function AlertList({ severity, limit = 8, assetId }: { severity?: string; limit?: number; assetId?: string }) {
  const nav = useNavigate();
  const { data, isLoading } = useAlertsQuery({ open_only: true, severity, per_page: limit, asset_id: assetId }, { pollingInterval: usePolling() });
  if (isLoading) return <Loading label="Loading alerts" />;
  if (!data?.items.length) return <EmptyState title="No active alerts" hint="Everything within limits." />;
  return (
    <List dense disablePadding aria-label="Active alerts">
      {data.items.map((a) => (
        <ListItemButton key={a.id} onClick={() => nav(`/alerts/${a.id}`)} sx={{ px: 1, borderRadius: 1, gap: 1.5, opacity: a.suppressed ? 0.6 : 1 }}>
          <SeverityChip severity={a.severity} sx={{ minWidth: 72 }} />
          <ListItemText primary={a.title} secondary={`${a.asset_name ?? 'Platform'} · ${timeAgo(a.created_at)}`}
            primaryTypographyProps={{ noWrap: true, variant: 'body2' }} secondaryTypographyProps={{ noWrap: true, variant: 'caption' }} />
          {a.status === 'triggered' && <Box component="span" sx={{ fontSize: 11, color: 'text.secondary' }}>Unacked</Box>}
        </ListItemButton>
      ))}
      {data.meta.total > limit && <Typography variant="caption" color="text.secondary" sx={{ px: 1 }}>{data.meta.total - limit} more in the alert center</Typography>}
    </List>
  );
}
