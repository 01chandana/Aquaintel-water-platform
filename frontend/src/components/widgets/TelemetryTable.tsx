import { Box, Typography } from '@mui/material';
import { useEffect, useMemo, useState } from 'react';
import { FixedSizeList, type ListChildComponentProps } from 'react-window';
import { useLatestQuery } from '@/api/telemetryApi';
import { StatusDot } from '@/components/common/Chips';
import { Loading } from '@/components/common/States';
import { onTelemetry } from '@/hooks/useWebSocket';
import type { LatestValue } from '@/types/models';
import { timeAgo } from '@/utils/formatDate';
import { formatNumber } from '@/utils/formatNumber';

const ROW = 34;

/**
 * Live telemetry grid: seeded from GET /telemetry/latest, then patched in place by WebSocket
 * pushes. Virtualised with react-window so hundreds of tags stay smooth (Ch. 8.10).
 */
export function TelemetryTable({ parameter, assetId, height = 360, filter = '' }: { parameter?: string; assetId?: string; height?: number; filter?: string }) {
  const { data, isLoading } = useLatestQuery({ parameter, asset_id: assetId });
  const [live, setLive] = useState<Record<string, LatestValue>>({});
  useEffect(() => onTelemetry((pts) => {
    setLive((prev) => {
      const next = { ...prev };
      for (const p of pts) if ((!parameter || p.parameter === parameter) && (!assetId || p.asset_id === assetId)) next[p.tag_id] = p;
      return next;
    });
  }), [parameter, assetId]);
  const rows = useMemo(() => {
    const merged = new Map<string, LatestValue>((data ?? []).map((d) => [d.tag_id, d]));
    Object.values(live).forEach((v) => merged.set(v.tag_id, { ...merged.get(v.tag_id), ...v }));
    const f = filter.toLowerCase();
    return [...merged.values()].filter((r) => !f || (r.tag ?? '').toLowerCase().includes(f)).sort((a, b) => (a.tag ?? '').localeCompare(b.tag ?? ''));
  }, [data, live, filter]);
  if (isLoading) return <Loading label="Loading telemetry" />;

  const Row = ({ index, style }: ListChildComponentProps) => {
    const r = rows[index];
    const fresh = live[r.tag_id] !== undefined;
    return (
      <Box style={style} sx={{ display: 'grid', gridTemplateColumns: '18px 1fr 120px 90px', alignItems: 'center', gap: 1, px: 1, borderBottom: 1, borderColor: 'divider' }}>
        <StatusDot status={r.status === 'bad' ? 'critical' : r.status === 'suspect' ? 'warning' : 'normal'} />
        <Typography variant="body2" noWrap title={r.tag ?? r.tag_id}>{r.tag}</Typography>
        <Typography variant="body2" align="right" sx={{ fontWeight: fresh ? 600 : 400 }}>{formatNumber(r.value, r.unit ?? undefined)}</Typography>
        <Typography variant="caption" color="text.secondary" align="right">{timeAgo(r.time)}</Typography>
      </Box>
    );
  };
  return (
    <Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: '18px 1fr 120px 90px', gap: 1, px: 1, pb: 0.5, color: 'text.secondary', fontSize: 12 }}>
        <span /> <span>Tag</span> <span style={{ textAlign: 'right' }}>Value</span> <span style={{ textAlign: 'right' }}>Updated</span>
      </Box>
      <FixedSizeList height={Math.min(height, rows.length * ROW + 2)} itemCount={rows.length} itemSize={ROW} width="100%">{Row}</FixedSizeList>
    </Box>
  );
}
