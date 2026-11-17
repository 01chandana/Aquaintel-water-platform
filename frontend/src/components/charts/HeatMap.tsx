import { Box, useTheme } from '@mui/material';
import * as d3 from 'd3';
import { useEffect, useMemo, useRef } from 'react';
import { tokens } from '@/theme/palette';

export interface HeatCell {
  row: string;
  col: string;
  value: number;
}

interface Props {
  cells: HeatCell[];
  height?: number;
  domain?: [number, number];
  formatCol?: (c: string) => string;
  label?: string;
}

/**
 * D3 heat map (Ch. 4.3.4 custom visualization) - KPI 22 "heat map by asset category".
 * Low scores are drawn in alarm colours; healthy cells fade toward the neutral surface.
 */
export function HeatMap({ cells, height = 280, domain = [40, 100], formatCol = (c) => c, label = 'Heat map' }: Props) {
  const ref = useRef<SVGSVGElement>(null);
  const theme = useTheme();
  const rows = useMemo(() => [...new Set(cells.map((c) => c.row))], [cells]);
  const cols = useMemo(() => [...new Set(cells.map((c) => c.col))].sort(), [cells]);

  useEffect(() => {
    const svg = d3.select(ref.current);
    const width = ref.current?.clientWidth ?? 600;
    const m = { top: 8, right: 8, bottom: 24, left: 150 };
    svg.selectAll('*').remove();
    const x = d3.scaleBand().domain(cols).range([m.left, width - m.right]).padding(0.06);
    const y = d3.scaleBand().domain(rows).range([m.top, height - m.bottom]).padding(0.08);
    const color = d3.scaleLinear<string>().domain([domain[0], (domain[0] + domain[1]) / 2, domain[1]])
      .range([tokens.alarm.critical, tokens.alarm.major, theme.palette.mode === 'dark' ? '#2A4655' : '#CFE0E6']).clamp(true);
    const tip = d3.select(ref.current?.parentElement ?? null).select<HTMLDivElement>('.hm-tip');
    svg.append('g').selectAll('rect').data(cells).join('rect')
      .attr('x', (d) => x(d.col) ?? 0).attr('y', (d) => y(d.row) ?? 0)
      .attr('width', x.bandwidth()).attr('height', y.bandwidth()).attr('rx', 2)
      .attr('fill', (d) => color(d.value))
      .on('mousemove', (ev: MouseEvent, d) => {
        tip.style('opacity', '1').style('left', `${ev.offsetX + 12}px`).style('top', `${ev.offsetY - 10}px`)
          .text(`${d.row} · ${formatCol(d.col)}: ${d.value.toFixed(1)}`);
      })
      .on('mouseleave', () => tip.style('opacity', '0'));
    svg.append('g').attr('transform', `translate(${m.left - 6},0)`).selectAll('text').data(rows).join('text')
      .attr('y', (d) => (y(d) ?? 0) + y.bandwidth() / 2).attr('dy', '0.35em').attr('text-anchor', 'end')
      .attr('fill', theme.palette.text.secondary).attr('font-size', 11).text((d) => d);
    // label each day once (columns are hourly), thinning if there are many days
    const firsts = cols.filter((c, i) => i === 0 || formatCol(c) !== formatCol(cols[i - 1]));
    const step = Math.max(1, Math.ceil(firsts.length / 10));
    let lastX = -Infinity;
    const labelled = firsts.filter((c, i) => {
      const px = x(c) ?? 0;
      if (i % step !== 0 || px - lastX < 44) return false; // skip a partial first day that would collide
      lastX = px;
      return true;
    });
    svg.append('g').selectAll('text').data(labelled).join('text')
      .attr('x', (d) => x(d) ?? 0).attr('y', height - 6).attr('text-anchor', 'start')
      .attr('fill', theme.palette.text.secondary).attr('font-size', 10).text((d) => formatCol(d));
  }, [cells, rows, cols, height, domain, theme, formatCol]);

  return (
    <Box sx={{ position: 'relative', width: '100%' }}>
      <svg ref={ref} width="100%" height={height} role="img" aria-label={label} />
      <Box className="hm-tip" sx={{ position: 'absolute', pointerEvents: 'none', opacity: 0, bgcolor: 'background.paper', border: 1, borderColor: 'divider', px: 1, py: 0.5, fontSize: 12, borderRadius: 1, whiteSpace: 'nowrap' }} />
    </Box>
  );
}
