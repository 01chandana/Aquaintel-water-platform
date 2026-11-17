import { Box, Checkbox, Table, TableBody, TableCell, TableContainer, TableHead, TablePagination, TableRow, TableSortLabel } from '@mui/material';
import type { SerializedError } from '@reduxjs/toolkit';
import type { FetchBaseQueryError } from '@reduxjs/toolkit/query';
import type { ReactNode } from 'react';
import { EmptyState, ErrorState } from './States';

export interface Column<T> {
  key: string;
  label: string;
  render: (row: T) => ReactNode;
  sortKey?: string;
  align?: 'left' | 'right' | 'center';
  width?: number | string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  total?: number;
  page?: number;
  perPage?: number;
  onPage?: (page: number, perPage: number) => void;
  sort?: string;
  onSort?: (sort: string) => void;
  onRowClick?: (row: T) => void;
  selected?: Set<string>;
  onSelect?: (ids: Set<string>) => void;
  empty?: string;
  /** Load error from the query: shown instead of the empty message, so a failed load never reads as "no data" */
  error?: FetchBaseQueryError | SerializedError;
  onRetry?: () => void;
  dense?: boolean;
}

/** Server-paginated, sortable, optionally selectable table (Alert Center bulk actions). */
export function DataTable<T>({ rows, columns, rowKey, total, page = 1, perPage = 25, onPage, sort, onSort, onRowClick, selected, onSelect, empty = 'No records', dense, error, onRetry }: Props<T>) {
  const allIds = rows.map(rowKey);
  const allSelected = !!selected && allIds.length > 0 && allIds.every((id) => selected.has(id));
  return (
    <Box>
      <TableContainer>
        <Table size={dense ? 'small' : 'medium'} stickyHeader>
          <TableHead>
            <TableRow>
              {onSelect && (
                <TableCell padding="checkbox">
                  <Checkbox size="small" checked={allSelected} indeterminate={!!selected?.size && !allSelected}
                    inputProps={{ 'aria-label': 'Select all rows' }}
                    onChange={() => onSelect(allSelected ? new Set() : new Set(allIds))} />
                </TableCell>
              )}
              {columns.map((c) => (
                <TableCell key={c.key} align={c.align} sx={{ width: c.width }}>
                  {c.sortKey && onSort ? (
                    <TableSortLabel active={sort?.replace('-', '') === c.sortKey} direction={sort?.startsWith('-') ? 'desc' : 'asc'}
                      onClick={() => onSort(sort === `-${c.sortKey}` ? c.sortKey! : `-${c.sortKey}`)}>
                      {c.label}
                    </TableSortLabel>
                  ) : c.label}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((r) => {
              const id = rowKey(r);
              return (
                <TableRow key={id} hover={!!onRowClick} onClick={onRowClick ? () => onRowClick(r) : undefined}
                  sx={{ cursor: onRowClick ? 'pointer' : undefined }} tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={onRowClick ? (e) => e.key === 'Enter' && onRowClick(r) : undefined}>
                  {onSelect && selected && (
                    <TableCell padding="checkbox" onClick={(e) => e.stopPropagation()}>
                      <Checkbox size="small" checked={selected.has(id)} inputProps={{ 'aria-label': 'Select row' }}
                        onChange={() => {
                          const next = new Set(selected);
                          if (next.has(id)) next.delete(id);
                          else next.add(id);
                          onSelect(next);
                        }} />
                    </TableCell>
                  )}
                  {columns.map((c) => <TableCell key={c.key} align={c.align}>{c.render(r)}</TableCell>)}
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>
      {error && <Box sx={{ p: 2 }}><ErrorState error={error} onRetry={onRetry} /></Box>}
      {rows.length === 0 && !error && <EmptyState title={empty} />}
      {onPage && total !== undefined && (
        <TablePagination component="div" count={total} page={page - 1} rowsPerPage={perPage} rowsPerPageOptions={[10, 25, 50, 100]}
          onPageChange={(_, p) => onPage(p + 1, perPage)} onRowsPerPageChange={(e) => onPage(1, Number(e.target.value))} />
      )}
    </Box>
  );
}
