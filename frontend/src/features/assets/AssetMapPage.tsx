import { Box, Typography } from '@mui/material';
import { useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAssetTreeQuery, useAssetsQuery } from '@/api/assetApi';
import { AssetMap } from '@/components/charts/AssetMap';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { ErrorState, Loading } from '@/components/common/States';
import { useAppSelector } from '@/store';
import { tokens } from '@/theme/palette';
import type { Asset, AssetNode } from '@/types/models';

/** Keep only the selected site and everything below it (asset paths are "plant_a/area/pump"). */
export function assetsForSite(assets: Asset[], siteId: string | null): Asset[] {
  if (!siteId) return assets;
  const site = assets.find((a) => a.id === siteId);
  if (!site) return assets;
  return assets.filter((a) => a.path === site.path || a.path.startsWith(`${site.path}/`));
}

const LEGEND = [
  { l: 'Treatment plant', ring: tokens.brand, fill: 'transparent', dash: false },
  { l: 'Equipment / area', ring: tokens.alarm.normal, fill: 'transparent', dash: false },
  { l: 'Open alerts', ring: tokens.alarm.critical, fill: tokens.alarm.critical, dash: false },
  { l: 'In maintenance', ring: tokens.alarm.major, fill: tokens.alarm.major, dash: false },
  { l: 'Inactive', ring: tokens.alarm.normal, fill: 'transparent', dash: true },
];

export default function AssetMapPage() {
  const nav = useNavigate();
  const siteId = useAppSelector((s) => s.ui.siteId);
  const { data: assets, isLoading, error, refetch } = useAssetsQuery({ per_page: 500 });
  const { data: tree } = useAssetTreeQuery();
  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    const walk = (n: AssetNode) => { out[n.id] = n.open_alerts; n.children.forEach(walk); };
    tree?.forEach(walk);
    return out;
  }, [tree]);
  const visible = useMemo(() => assetsForSite(assets?.items ?? [], siteId), [assets, siteId]);
  const onSelect = useCallback((a: Asset) => nav(`/assets/${a.id}`), [nav]);

  let body;
  if (isLoading) body = <Loading label="Loading assets" />;
  else if (error) body = <ErrorState error={error} onRetry={refetch} />;
  else body = <AssetMap assets={visible} alertCounts={counts} onSelect={onSelect} />;

  return (
    <>
      <PageHeader title="Asset map"
        description="Geo-located assets linked to their parent. Red markers have open alerts, amber markers are in maintenance. Scroll to zoom, drag to pan, click a marker to open the asset." />
      <Panel>
        {body}
        <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 3, mt: 1.5, color: 'text.secondary' }}>
          {LEGEND.map((x) => (
            <Box key={x.l} sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
              <Box sx={{ width: 10, height: 10, borderRadius: '50%', bgcolor: x.fill, border: `2px ${x.dash ? 'dashed' : 'solid'} ${x.ring}` }} />
              <Typography variant="caption">{x.l}</Typography>
            </Box>
          ))}
        </Box>
      </Panel>
    </>
  );
}
