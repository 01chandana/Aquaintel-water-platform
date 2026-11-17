import { ThemeProvider } from '@mui/material';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { BandBar } from '@/components/charts/BandBar';
import { DataTable } from '@/components/common/DataTable';
import { errorMessage, LoadFailed } from '@/components/common/States';
import { KpiCard } from '@/components/widgets/KpiCard';
import { darkTheme } from '@/theme/darkTheme';
import type { KpiCurrent } from '@/types/models';

const wrap = (ui: ReactNode) => render(<ThemeProvider theme={darkTheme}><MemoryRouter>{ui}</MemoryRouter></ThemeProvider>);

const item = (value: number, status: KpiCurrent['status']): KpiCurrent => ({
  kpi: { id: 'k1', code: 'SYSTEM_AVAILABILITY', number: 1, name: 'System Availability', formula: 'a/b', unit: '%', category: 'operational',
    threshold_warning: 98, threshold_critical: 95, aggregation_type: 'avg', description: null, higher_is_better: true, target: null,
    visualization: 'gauge', alert_condition: null, scope: 'site', is_builtin: true },
  asset_id: null, value, status, time: null, previous_value: null, trend_pct: -1.2, sparkline: [99, 98, 97],
});

describe('BandBar', () => {
  it('reports the status of the value', () => {
    wrap(<BandBar value={96} warning={98} critical={95} higherIsBetter />);
    expect(screen.getByRole('img')).toHaveAccessibleName('Value 96, status warning');
  });
  it('handles lower-is-better KPIs', () => {
    wrap(<BandBar value={0.6} warning={0.45} critical={0.55} higherIsBetter={false} />);
    expect(screen.getByRole('img')).toHaveAccessibleName('Value 0.6, status critical');
  });
});

describe('KpiCard', () => {
  it('stays neutral when normal and labels abnormal states', () => {
    const { unmount } = wrap(<KpiCard item={item(99.4, 'normal')} />);
    expect(screen.queryByText('critical')).not.toBeInTheDocument();
    unmount();
    wrap(<KpiCard item={item(93, 'critical')} />);
    expect(screen.getByText('critical')).toBeInTheDocument();
    expect(screen.getByRole('link')).toHaveAttribute('href', '/analytics/kpis/k1');
  });
});

describe('DataTable', () => {
  it('supports selection and row clicks', () => {
    const onSelect = vi.fn();
    const onRow = vi.fn();
    wrap(<DataTable rows={[{ id: 'a', n: 'Pump 1' }, { id: 'b', n: 'Pump 2' }]} rowKey={(r) => r.id} selected={new Set()} onSelect={onSelect}
      onRowClick={onRow} columns={[{ key: 'n', label: 'Name', render: (r) => r.n }]} />);
    fireEvent.click(screen.getByLabelText('Select all rows'));
    expect(onSelect).toHaveBeenCalledWith(new Set(['a', 'b']));
    fireEvent.click(screen.getByText('Pump 2'));
    expect(onRow).toHaveBeenCalledWith({ id: 'b', n: 'Pump 2' });
  });
});

// QA audit regressions (AQ-026 / AQ-027): a failed load must never look like "no data"
describe('load failures', () => {
  const cols = [{ key: 'n', label: 'Name', render: (r: { n: string }) => r.n }];

  it('DataTable shows the error and Retry instead of the empty message', () => {
    const retry = vi.fn();
    wrap(<DataTable rows={[]} rowKey={(r: { n: string }) => r.n} columns={cols} empty="No alerts"
      error={{ status: 'FETCH_ERROR', error: 'TypeError: Failed to fetch' }} onRetry={retry} />);
    expect(screen.queryByText('No alerts')).toBeNull();
    expect(screen.getByText(/Can't reach the AquaIntel server/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(retry).toHaveBeenCalled();
  });

  it('LoadFailed turns 404 / 422 into "not found" with a way back', () => {
    wrap(<LoadFailed error={{ status: 422, data: {} }} what="Asset" backTo={{ label: 'Back to assets', href: '/assets' }} />);
    expect(screen.getByText('Asset not found')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Back to assets' }).getAttribute('href')).toBe('/assets');
  });

  it('errorMessage prefers the API envelope and hides transport codes', () => {
    expect(errorMessage({ status: 409, data: { status: 'error', error: { code: 'CONFLICT', message: 'An identical enabled rule already exists', details: [] } } }))
      .toBe('An identical enabled rule already exists');
    expect(errorMessage({ status: 'TIMEOUT_ERROR', error: 'timeout' })).toMatch(/took too long/);
    expect(errorMessage({ status: 503, data: 'upstream' })).toMatch(/server hit an error/);
  });
});
