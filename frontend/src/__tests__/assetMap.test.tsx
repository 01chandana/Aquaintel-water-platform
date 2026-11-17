import { ThemeProvider } from '@mui/material';
import { fireEvent, render, screen } from '@testing-library/react';
import * as d3 from 'd3';
import { describe, expect, it, vi } from 'vitest';
import { AssetMap, framingBox, spreadOverlaps, visibleGraticule } from '@/components/charts/AssetMap';
import { assetsForSite } from '@/features/assets/AssetMapPage';
import { darkTheme } from '@/theme/darkTheme';
import type { Asset } from '@/types/models';

const asset = (id: string, path: string, lon: number, lat: number, extra: Partial<Asset> = {}): Asset => ({
  id, external_id: id, name: id, asset_type_id: 't', parent_id: path.includes('/') ? path.split('/').slice(0, -1).join('/') : null,
  path, location: { type: 'Point', coordinates: [lon, lat] }, metadata: null, status: 'active', created_at: '2026-01-01T00:00:00Z', ...extra,
});

// Two sites a few km apart with equipment, like the demo data.
const ASSETS: Asset[] = [
  asset('plant_a', 'plant_a', -122.308, 47.605),
  asset('plant_a/pump_1', 'plant_a/pump_1', -122.3081, 47.6051),
  asset('plant_a/pump_2', 'plant_a/pump_2', -122.31, 47.607, { status: 'maintenance' }),
  asset('plant_b', 'plant_b', -122.20, 47.52),
  asset('plant_b/tank', 'plant_b/tank', -122.201, 47.521),
];

const fitted = (assets: Asset[], w = 1000, h = 520) =>
  d3.geoMercator().fitExtent([[48, 36], [w - 48, h - 36]], framingBox(assets.map((a) => a.location!.coordinates)));

describe('Asset map geometry', () => {
  it('frames the assets, not the whole planet', () => {
    const p = fitted(ASSETS);
    const pts = ASSETS.map((a) => p(a.location!.coordinates)!);
    const spanX = Math.max(...pts.map((q) => q[0])) - Math.min(...pts.map((q) => q[0]));
    const spanY = Math.max(...pts.map((q) => q[1])) - Math.min(...pts.map((q) => q[1]));
    // the assets fill the frame in at least one direction (a world-sized fit squeezes them into a few pixels)
    expect(Math.max(spanX / (1000 - 96), spanY / (520 - 72))).toBeGreaterThan(0.95);
  });

  it('gives a single asset a finite, sensible frame', () => {
    const p = fitted([ASSETS[0]]);
    expect(Number.isFinite(p.scale())).toBe(true);
    expect(p(ASSETS[0].location!.coordinates)!.every(Number.isFinite)).toBe(true);
  });

  it('draws a small grid for the visible area only (regression: world grid froze the browser)', () => {
    const p = fitted(ASSETS);
    for (const k of [1, 4, 20, 60]) {
      const t = d3.zoomIdentity.scale(k);
      const g = visibleGraticule(p, 1000, 520, t);
      expect(g).not.toBeNull();
      expect(g!.coordinates.length).toBeLessThanOrEqual(60);
      expect((d3.geoPath(p)(g!) ?? '').length).toBeLessThan(50_000);
    }
  });

  it('spreads markers that would sit on top of each other', () => {
    const out = spreadOverlaps([{ id: 'site', x: 100, y: 100, r: 10 }, { id: 'a', x: 100, y: 100, r: 6 }, { id: 'b', x: 101, y: 100, r: 6 }]);
    expect(out.get('site')).toEqual([100, 100]); // the plant stays where it is
    const pts = [...out.values()];
    for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++) {
      expect(Math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])).toBeGreaterThan(8);
    }
  });

  it('filters to the selected site and everything under it', () => {
    expect(assetsForSite(ASSETS, null)).toHaveLength(5);
    expect(assetsForSite(ASSETS, 'plant_b').map((a) => a.id)).toEqual(['plant_b', 'plant_b/tank']);
  });
});

describe('AssetMap component', () => {
  const renderMap = (onSelect = vi.fn(), counts: Record<string, number> = { plant_a: 1, 'plant_a/pump_1': 1 }) =>
    render(<ThemeProvider theme={darkTheme}><AssetMap assets={ASSETS} alertCounts={counts} onSelect={onSelect} /></ThemeProvider>);

  it('renders one keyboard-reachable marker per located asset, with status in its name', () => {
    renderMap();
    expect(screen.getByRole('button', { name: /^plant_a\/pump_1,.*1 open alerts/ })).toHaveAttribute('tabindex', '0');
    expect(screen.getByRole('button', { name: /^plant_a\/pump_2,.*status maintenance/ })).toBeInTheDocument();
    expect(document.querySelectorAll('svg[role=group] g[role=button]')).toHaveLength(5);
  });

  it('opens the asset on click and on Enter', () => {
    const onSelect = vi.fn();
    renderMap(onSelect);
    fireEvent.click(screen.getByRole('button', { name: /^plant_b,/ }));
    fireEvent.keyDown(screen.getByRole('button', { name: /^plant_b\/tank,/ }), { key: 'Enter' });
    expect(onSelect.mock.calls.map(([a]) => a.id)).toEqual(['plant_b', 'plant_b/tank']);
  });

  it('shows counts on the highlight buttons and dims non-matching markers', () => {
    renderMap();
    fireEvent.click(screen.getByRole('button', { name: 'In maintenance (1)' }));
    expect(screen.getByRole('button', { name: /^plant_a\/pump_2,/ })).toHaveAttribute('opacity', '1');
    expect(screen.getByRole('button', { name: /^plant_b,/ })).toHaveAttribute('opacity', '0.2');
    expect(screen.getByRole('button', { name: 'Open alerts (1)' })).toBeInTheDocument();
  });

  it('explains an empty map instead of drawing nothing', () => {
    render(<ThemeProvider theme={darkTheme}><AssetMap assets={[{ ...ASSETS[0], location: null }]} alertCounts={{}} onSelect={vi.fn()} /></ThemeProvider>);
    expect(screen.getByText(/No assets with a location/)).toBeInTheDocument();
  });
});
