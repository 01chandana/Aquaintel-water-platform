import { Add, CenterFocusStrong, Remove } from '@mui/icons-material';
import { Box, Chip, FormControlLabel, IconButton, Paper, Switch, ToggleButton, ToggleButtonGroup, Tooltip, Typography, useTheme } from '@mui/material';
import * as d3 from 'd3';
import { useEffect, useMemo, useRef, useState } from 'react';
import { tokens } from '@/theme/palette';
import type { Asset } from '@/types/models';

export type MapOverlay = 'all' | 'alerts' | 'maintenance';

interface Props {
  assets: Asset[];
  alertCounts: Record<string, number>;
  onSelect: (a: Asset) => void;
  height?: number;
}

type Located = Asset & { location: NonNullable<Asset['location']> };

const MIN_SPAN_DEG = 0.004; // ~400 m: keeps a single asset (or a tight cluster) from zooming to infinity
const GRID_STEPS = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 20];
const MAX_GRID_LINES = 60;

/**
 * Bounding box of the assets, padded so a lone asset still has a sensible frame.
 * Returned as the four corners (a MultiPoint) for projection.fitExtent. Not a Polygon: d3 treats
 * polygons as spherical and reads ring order, so a box with the "wrong" winding means "the whole
 * globe except this box" and the map zooms out to the planet.
 */
export function framingBox(points: [number, number][]): GeoJSON.MultiPoint {
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of points) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const padX = Math.max(0, (MIN_SPAN_DEG - (x1 - x0)) / 2);
  const padY = Math.max(0, (MIN_SPAN_DEG - (y1 - y0)) / 2);
  x0 -= padX; x1 += padX; y0 -= padY; y1 += padY;
  return { type: 'MultiPoint', coordinates: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] };
}

/**
 * Graticule for the part of the map that is on screen only, with a step chosen for ~8 lines.
 * (A world-wide graticule at a fine step is ~40k lines and a multi-hundred-MB SVG path, which
 * froze the browser.) Never returns more than MAX_GRID_LINES lines.
 */
export function visibleGraticule(projection: d3.GeoProjection, width: number, height: number, t: d3.ZoomTransform = d3.zoomIdentity) {
  const tl = projection.invert?.(t.invert([0, 0]));
  const br = projection.invert?.(t.invert([width, height]));
  if (!tl || !br || ![...tl, ...br].every(Number.isFinite)) return null;
  const lonSpan = Math.abs(br[0] - tl[0]);
  const latSpan = Math.abs(tl[1] - br[1]);
  const step = GRID_STEPS.find((s) => s >= Math.max(lonSpan, latSpan) / 8) ?? 20;
  const x0 = Math.floor(Math.min(tl[0], br[0]) / step) * step - step;
  const x1 = Math.ceil(Math.max(tl[0], br[0]) / step) * step + step;
  const y0 = Math.max(-85, Math.floor(Math.min(tl[1], br[1]) / step) * step - step);
  const y1 = Math.min(85, Math.ceil(Math.max(tl[1], br[1]) / step) * step + step);
  if ((x1 - x0) / step + (y1 - y0) / step > MAX_GRID_LINES) return null;
  return d3.geoGraticule().extent([[x0, y0], [x1, y1]]).step([step, step]).precision(step)();
}

/**
 * Nudge markers that overlap on screen apart (a few relaxation passes), so every asset stays
 * clickable even when two sit metres apart. Positions are screen pixels; returns new positions.
 */
export function spreadOverlaps(points: { id: string; x: number; y: number; r: number }[], gap = 3, passes = 16) {
  const out = points.map((p) => ({ ...p }));
  for (let pass = 0; pass < passes; pass++) {
    let moved = false;
    for (let i = 0; i < out.length; i++) {
      for (let j = i + 1; j < out.length; j++) {
        const a = out[i]; const b = out[j];
        const min = a.r + b.r + gap;
        let dx = b.x - a.x; let dy = b.y - a.y;
        const d = Math.hypot(dx, dy);
        if (d >= min) continue;
        if (d < 1e-6) { const ang = (j * 2.399963) % (2 * Math.PI); dx = Math.cos(ang); dy = Math.sin(ang); } else { dx /= d; dy /= d; }
        const push = (min - d) / 2;
        // the bigger marker (a site) stays put; the smaller one moves
        const wa = a.r > b.r ? 0 : b.r > a.r ? 1 : 0.5;
        a.x -= dx * push * 2 * wa; a.y -= dy * push * 2 * wa;
        b.x += dx * push * 2 * (1 - wa); b.y += dy * push * 2 * (1 - wa);
        moved = true;
      }
    }
    if (!moved) break;
  }
  return new Map(out.map((p) => [p.id, [p.x, p.y] as [number, number]]));
}

const matches = (a: Asset, overlay: MapOverlay, alerts: number) =>
  overlay === 'all' || (overlay === 'alerts' ? alerts > 0 : a.status === 'maintenance');

/**
 * Asset Map (spec: "geo-located assets on interactive map with status overlays").
 * D3 with a plain Mercator projection, so no tile server or internet access is needed.
 * Zoom with the wheel, buttons or double-click; drag to pan; hover or focus a marker for details;
 * click or press Enter to open the asset.
 */
export function AssetMap({ assets, alertCounts, onSelect, height = 520 }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<d3.ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const transformRef = useRef<d3.ZoomTransform>(d3.zoomIdentity);
  const theme = useTheme();
  const [width, setWidth] = useState(0);
  const [overlay, setOverlay] = useState<MapOverlay>('all');
  const [showLinks, setShowLinks] = useState(true);
  // below: show the card under the marker when there is no room above it (marker near the top edge)
  const [hover, setHover] = useState<{ asset: Located; x: number; y: number; below: boolean; h: number } | null>(null);

  const located = useMemo(() => assets.filter((a): a is Located => !!a.location?.coordinates
    && a.location.coordinates.every(Number.isFinite)), [assets]);
  const byId = useMemo(() => new Map(located.map((a) => [a.id, a])), [located]);
  const summary = useMemo(() => ({
    total: located.length,
    alerts: located.filter((a) => (alertCounts[a.id] ?? 0) > 0 && a.parent_id).length,
    maintenance: located.filter((a) => a.status === 'maintenance').length,
  }), [located, alertCounts]);

  // Track the container width so the map fits any screen and re-fits on resize.
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    setWidth(el.clientWidth || 800);
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width) || 800));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    const el = svgRef.current;
    if (!el || !width) return;
    const svg = d3.select(el);
    svg.selectAll('*').remove();
    svg.on('.zoom', null);
    if (!located.length) return;

    const muted = theme.palette.text.secondary;
    const projection = d3.geoMercator().fitExtent([[48, 36], [width - 48, height - 36]], framingBox(located.map((a) => a.location.coordinates)));
    const xy = new Map<string, [number, number]>(located.map((a) => [a.id, projection(a.location.coordinates) ?? [0, 0]]));
    const isSite = (a: Asset) => !a.parent_id;
    const count = (a: Asset) => alertCounts[a.id] ?? 0;

    svg.append('rect').attr('width', width).attr('height', height).attr('fill', 'transparent');
    const gridPath = svg.append('path').attr('fill', 'none').attr('stroke', muted).attr('stroke-opacity', 0.18)
      .attr('stroke-width', 0.7).attr('vector-effect', 'non-scaling-stroke').attr('pointer-events', 'none');
    const linkData = showLinks ? located.filter((a) => a.parent_id && byId.has(a.parent_id)) : [];
    const links = svg.append('g').attr('aria-hidden', true).selectAll('line').data(linkData).join('line')
      .attr('stroke', muted).attr('stroke-opacity', 0.5).attr('stroke-width', 1).attr('pointer-events', 'none')
      .attr('opacity', (a) => (matches(a, overlay, count(a)) ? 1 : 0.25));

    // Draw children first and sites last so plant markers sit on top.
    const ordered = [...located].sort((a, b) => Number(isSite(a)) - Number(isSite(b)));
    const nodes = svg.append('g').selectAll<SVGGElement, Located>('g').data(ordered, (a) => a.id).join('g')
      .attr('tabindex', 0).attr('role', 'button')
      .attr('aria-label', (a) => `${a.name}, ${a.asset_type?.name ?? 'asset'}, status ${a.status}, ${count(a)} open alerts`)
      .attr('opacity', (a) => (matches(a, overlay, count(a)) ? 1 : 0.2))
      .style('cursor', 'pointer').style('outline', 'none')
      .on('click', (_, a) => onSelect(a))
      .on('keydown', (ev: KeyboardEvent, a) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); onSelect(a); } })
      .on('mouseenter focus', (ev: Event, a) => {
        const rect = el.getBoundingClientRect();
        const target = (ev.currentTarget as SVGGElement).getBoundingClientRect();
        setHover({ asset: a, x: target.left - rect.left + target.width / 2, y: target.top - rect.top, below: target.top - rect.top < 120, h: target.height });
      })
      .on('mouseleave blur', () => setHover(null));

    nodes.append('circle').attr('class', 'focus-ring').attr('r', (a) => (isSite(a) ? 14 : 9))
      .attr('fill', 'none').attr('stroke', tokens.brand).attr('stroke-width', 2).attr('opacity', 0)
      .attr('pointer-events', 'none'); // visual only: must not steal clicks from neighbours
    nodes.on('focus.ring', function () { d3.select(this).select('.focus-ring').attr('opacity', 1); })
      .on('blur.ring', function () { d3.select(this).select('.focus-ring').attr('opacity', 0); });
    nodes.append('circle').attr('r', (a) => (isSite(a) ? 9 : 5))
      .attr('fill', (a) => (count(a) > 0 ? tokens.alarm.critical : a.status === 'maintenance' ? tokens.alarm.major : theme.palette.background.paper))
      .attr('stroke', (a) => (isSite(a) ? tokens.brand : a.status === 'maintenance' ? tokens.alarm.major : muted))
      .attr('stroke-dasharray', (a) => (a.status === 'inactive' ? '2 2' : null))
      .attr('stroke-width', (a) => (isSite(a) ? 2 : 1.5));
    nodes.filter((a) => count(a) > 0 && isSite(a)).append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('font-size', 9).attr('font-weight', 700).attr('fill', '#fff').attr('pointer-events', 'none').text((a) => String(count(a)));
    const labels = nodes.append('text').attr('class', 'label').attr('x', (a) => (isSite(a) ? 14 : 9)).attr('dy', '0.35em')
      .attr('font-size', (a) => (isSite(a) ? 12 : 10.5)).attr('font-weight', (a) => (isSite(a) ? 600 : 400))
      .attr('fill', theme.palette.text.primary).attr('paint-order', 'stroke')
      .attr('stroke', theme.palette.background.paper).attr('stroke-width', 3).attr('pointer-events', 'none').text((a) => a.name);

    const place = (t: d3.ZoomTransform) => {
      const grid = visibleGraticule(projection, width, height, t);
      gridPath.attr('d', grid ? d3.geoPath(projection)(grid) : null).attr('transform', t.toString());
      const spread = spreadOverlaps(located.map((a) => {
        const [x, y] = t.apply(xy.get(a.id) ?? [0, 0]);
        return { id: a.id, x, y, r: isSite(a) ? 10 : 6 };
      }));
      const at = (id: string) => spread.get(id) ?? [0, 0];
      links.attr('x1', (a) => at(a.id)[0]).attr('y1', (a) => at(a.id)[1])
        .attr('x2', (a) => at(a.parent_id!)[0]).attr('y2', (a) => at(a.parent_id!)[1]);
      nodes.attr('transform', (a) => `translate(${at(a.id).join(',')})`);
      // Equipment names appear once zoomed in, so the overview stays readable.
      labels.attr('display', (a) => (isSite(a) || count(a) > 0 || t.k >= 3 ? null : 'none'));
    };

    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([1, 60])
      .extent([[0, 0], [width, height]]) // explicit: don't depend on the browser reporting SVG size
      .translateExtent([[-width, -height], [2 * width, 2 * height]])
      .on('zoom', (ev: d3.D3ZoomEvent<SVGSVGElement, unknown>) => { transformRef.current = ev.transform; setHover(null); place(ev.transform); });
    zoomRef.current = zoom;
    svg.call(zoom).call(zoom.transform, transformRef.current);
    place(transformRef.current);
  }, [located, byId, alertCounts, onSelect, width, height, theme, overlay, showLinks]);

  const zoomBy = (k: number) => { if (svgRef.current && zoomRef.current) d3.select(svgRef.current).transition().duration(250).call(zoomRef.current.scaleBy, k); };
  const resetZoom = () => { if (svgRef.current && zoomRef.current) d3.select(svgRef.current).transition().duration(300).call(zoomRef.current.transform, d3.zoomIdentity); };

  const hovered = hover?.asset;
  const parent = hovered?.parent_id ? byId.get(hovered.parent_id) : undefined;

  return (
    <Box>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 2, mb: 1.5 }}>
        <ToggleButtonGroup size="small" exclusive value={overlay} onChange={(_, v: MapOverlay | null) => v && setOverlay(v)} aria-label="Highlight">
          <ToggleButton value="all">All assets ({summary.total})</ToggleButton>
          <ToggleButton value="alerts">Open alerts ({summary.alerts})</ToggleButton>
          <ToggleButton value="maintenance">In maintenance ({summary.maintenance})</ToggleButton>
        </ToggleButtonGroup>
        <FormControlLabel control={<Switch size="small" checked={showLinks} onChange={(e) => setShowLinks(e.target.checked)} />} label="Network links" />
        <Box sx={{ ml: 'auto', display: 'flex', gap: 0.5 }}>
          <Tooltip title="Zoom in"><IconButton size="small" aria-label="Zoom in" onClick={() => zoomBy(1.6)}><Add fontSize="small" /></IconButton></Tooltip>
          <Tooltip title="Zoom out"><IconButton size="small" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.6)}><Remove fontSize="small" /></IconButton></Tooltip>
          <Tooltip title="Fit all assets"><IconButton size="small" aria-label="Fit all assets" onClick={resetZoom}><CenterFocusStrong fontSize="small" /></IconButton></Tooltip>
        </Box>
      </Box>
      <Box ref={wrapRef} sx={{ position: 'relative', width: '100%', borderRadius: 1, bgcolor: 'action.hover', overflow: 'hidden' }}>
        <svg ref={svgRef} width="100%" height={height} style={{ display: 'block', touchAction: 'none' }} role="group"
          aria-label={`Asset map with ${summary.total} assets. Scroll or use the buttons to zoom, drag to pan.`} />
        {!located.length && (
          <Box sx={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: 'text.secondary' }}>
            <Typography variant="body2">No assets with a location to show. Add coordinates to an asset to place it on the map.</Typography>
          </Box>
        )}
        {hovered && hover && (
          <Paper elevation={6} sx={{ position: 'absolute', left: Math.min(Math.max(hover.x, 120), width - 120),
            top: hover.below ? hover.y + hover.h + 8 : hover.y - 8,
            transform: hover.below ? 'translateX(-50%)' : 'translate(-50%, -100%)', px: 1.5, py: 1, pointerEvents: 'none', minWidth: 200, maxWidth: 260 }}>
            <Typography variant="subtitle2" noWrap>{hovered.name}</Typography>
            <Typography variant="caption" color="text.secondary" component="div">
              {hovered.asset_type?.name ?? 'Asset'}{parent ? ` in ${parent.name}` : ''}
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.75, mt: 0.75, flexWrap: 'wrap' }}>
              <Chip size="small" label={hovered.status} variant="outlined"
                sx={hovered.status === 'maintenance' ? { borderColor: tokens.alarm.major, color: tokens.alarm.major } : undefined} />
              <Chip size="small" variant="outlined"
                label={`${alertCounts[hovered.id] ?? 0} open alert${(alertCounts[hovered.id] ?? 0) === 1 ? '' : 's'}`}
                sx={(alertCounts[hovered.id] ?? 0) > 0 ? { borderColor: tokens.alarm.critical, color: tokens.alarm.critical } : undefined} />
            </Box>
            <Typography variant="caption" color="text.secondary" component="div" sx={{ mt: 0.5 }}>Click to open</Typography>
          </Paper>
        )}
      </Box>
    </Box>
  );
}
