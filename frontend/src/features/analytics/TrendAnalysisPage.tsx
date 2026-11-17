import { Autocomplete, Box, Checkbox, FormControlLabel, MenuItem, TextField } from '@mui/material';
import { useMemo, useState } from 'react';
import { useAggregateQuery, useTagsQuery } from '@/api/telemetryApi';
import { LineChart, type Series } from '@/components/charts/LineChart';
import { PageHeader } from '@/components/common/PageHeader';
import { Panel } from '@/components/common/Panel';
import { EmptyState, Loading } from '@/components/common/States';
import type { Tag } from '@/types/models';

const RANGES = [{ h: 24, label: 'Last 24 h', interval: '15m' }, { h: 72, label: 'Last 3 days', interval: '1h' }, { h: 168, label: 'Last 7 days', interval: '1h' }, { h: 720, label: 'Last 30 days', interval: '6h' }];

/** Custom time-range analysis with a previous-period comparison overlay (Ch. 8.5.4). */
export default function TrendAnalysisPage() {
  const { data: tags } = useTagsQuery();
  const [picked, setPicked] = useState<Tag[]>([]);
  const [range, setRange] = useState(RANGES[1]);
  const [compare, setCompare] = useState(false);
  const { end, start, prevStart } = useMemo(() => {
    const e = Date.now();
    return { end: new Date(e).toISOString(), start: new Date(e - range.h * 3600_000).toISOString(), prevStart: new Date(e - 2 * range.h * 3600_000).toISOString() };
  }, [range]);
  const ids = picked.map((t) => t.id);
  const cur = useAggregateQuery({ tagIds: ids, start, end, interval: range.interval }, { skip: !ids.length });
  const prev = useAggregateQuery({ tagIds: ids, start: prevStart, end: start, interval: range.interval }, { skip: !ids.length || !compare });

  const { rows, series } = useMemo(() => {
    const byTime = new Map<string, Record<string, number | string | null>>();
    const shift = range.h * 3600_000;
    for (const p of cur.data ?? []) {
      const r = byTime.get(p.bucket) ?? { time: p.bucket };
      r[p.tag_id] = p.avg_value;
      byTime.set(p.bucket, r);
    }
    for (const p of prev.data ?? []) {
      const t = new Date(new Date(p.bucket).getTime() + shift).toISOString();
      const key = [...byTime.keys()].find((k) => Math.abs(new Date(k).getTime() - new Date(t).getTime()) < 60_000) ?? t;
      const r = byTime.get(key) ?? { time: key };
      r[`${p.tag_id}_prev`] = p.avg_value;
      byTime.set(key, r);
    }
    const s: Series[] = picked.flatMap((t) => [{ key: t.id, label: t.external_id }, ...(compare ? [{ key: `${t.id}_prev`, label: `${t.external_id} (previous period)`, dashed: true }] : [])]);
    return { rows: [...byTime.values()].sort((a, b) => String(a.time).localeCompare(String(b.time))), series: s };
  }, [cur.data, prev.data, picked, compare, range]);

  return (
    <>
      <PageHeader title="Trend analysis" description="Overlay any tags over a custom window and compare against the previous period of the same length." />
      <Panel>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2, alignItems: 'center' }}>
          <Autocomplete multiple size="small" options={tags ?? []} value={picked} onChange={(_, v) => setPicked(v.slice(0, 6))}
            getOptionLabel={(t) => `${t.external_id} (${t.unit})`} sx={{ minWidth: 380, flex: 1 }}
            renderInput={(p) => <TextField {...p} label="Tags (up to 6)" />} />
          <TextField select size="small" label="Range" value={range.h} onChange={(e) => setRange(RANGES.find((r) => r.h === Number(e.target.value))!)}>
            {RANGES.map((r) => <MenuItem key={r.h} value={r.h}>{r.label}</MenuItem>)}
          </TextField>
          <FormControlLabel control={<Checkbox checked={compare} onChange={(e) => setCompare(e.target.checked)} />} label="Compare with previous period" />
        </Box>
        {!ids.length ? <EmptyState title="Pick one or more tags" hint="For example a pump's flow and power, or chlorine at the plant and at a district endpoint." />
          : cur.isFetching && !rows.length ? <Loading /> : <LineChart data={rows} series={series} height={420} brush showLegend />}
      </Panel>
    </>
  );
}
