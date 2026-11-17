import { useKpiCurrentQuery, useKpisQuery } from '@/api/kpiApi';
import { GaugeChart } from '@/components/charts/GaugeChart';
import { Panel } from '@/components/common/Panel';
import { PanelSkeleton } from '@/components/common/States';
import { KpiCard } from '@/components/widgets/KpiCard';
import { useAppSelector } from '@/store';

export function KpiWidget({ code, gauge }: { code: string; gauge?: boolean }) {
  const siteId = useAppSelector((s) => s.ui.siteId);
  const { data: defs } = useKpisQuery();
  const kpi = defs?.find((d) => d.code === code);
  const { data } = useKpiCurrentQuery({ id: kpi?.id ?? '', asset_id: siteId ?? undefined }, { skip: !kpi });
  if (!data || !kpi) return <PanelSkeleton height={130} />;
  if (!gauge) return <KpiCard item={data} />;
  const max = kpi.unit === '%' ? 100 : Math.max(1, (data.value ?? 0) * 1.5, (kpi.threshold_critical ?? 0) * 1.3, (kpi.threshold_warning ?? 0) * 1.3);
  const min = kpi.unit === '%' ? Math.min(50, (kpi.threshold_critical ?? 50) - 10) : 0;
  return (
    <Panel title={kpi.name}>
      <GaugeChart value={data.value} min={min} max={max} warning={kpi.threshold_warning} critical={kpi.threshold_critical}
        higherIsBetter={kpi.higher_is_better} unit={kpi.unit} label={data.status === 'normal' ? 'Within limits' : `Status: ${data.status}`} />
    </Panel>
  );
}
