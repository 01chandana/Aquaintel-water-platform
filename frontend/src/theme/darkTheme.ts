import { createTheme } from '@mui/material/styles';
import { shape, typography } from './base';
import { tokens } from './palette';

const t = tokens.dark;

export const darkTheme = createTheme({
  palette: {
    mode: 'dark',
    primary: { main: tokens.brand, dark: tokens.brandDeep, contrastText: '#06232A' },
    secondary: { main: '#9DB4C0' },
    error: { main: tokens.alarm.critical },
    warning: { main: tokens.alarm.major },
    info: { main: tokens.alarm.info },
    success: { main: '#7FC8A9' },
    background: { default: t.basin, paper: t.surface },
    text: { primary: t.ink, secondary: t.inkMuted },
    divider: t.rule,
  },
  typography,
  shape,
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: { fontVariantNumeric: 'tabular-nums' },
        '*:focus-visible': { outline: `2px solid ${tokens.brand}`, outlineOffset: 2 },
        '@media print': { body: { background: '#fff', color: '#000' } },
      },
    },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { backgroundImage: 'none', border: `1px solid ${t.rule}` } } },
    MuiAppBar: { styleOverrides: { root: { border: 'none', borderBottom: `1px solid ${t.rule}`, background: t.basin } } },
    MuiDrawer: { styleOverrides: { paper: { background: t.basin, borderRight: `1px solid ${t.rule}` } } },
    MuiTableCell: { styleOverrides: { root: { borderColor: t.rule }, head: { color: t.inkMuted, fontWeight: 600 } } },
    MuiButton: { defaultProps: { disableElevation: true } },
    MuiChip: { styleOverrides: { root: { fontWeight: 600 } } },
    MuiTooltip: { styleOverrides: { tooltip: { background: t.raised, border: `1px solid ${t.rule}`, color: t.ink } } },
  },
});
