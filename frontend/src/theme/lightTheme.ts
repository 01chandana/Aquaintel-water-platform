import { createTheme } from '@mui/material/styles';
import { shape, typography } from './base';
import { tokens } from './palette';

const t = tokens.light;

export const lightTheme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: tokens.brandDeep, contrastText: '#FFFFFF' },
    secondary: { main: '#5A7380' },
    error: { main: '#C9353A' },
    warning: { main: '#C46F1E' },
    info: { main: '#3F78AD' },
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
        '*:focus-visible': { outline: `2px solid ${tokens.brandDeep}`, outlineOffset: 2 },
      },
    },
    MuiPaper: { defaultProps: { elevation: 0 }, styleOverrides: { root: { border: `1px solid ${t.rule}` } } },
    MuiAppBar: { styleOverrides: { root: { border: 'none', borderBottom: `1px solid ${t.rule}`, background: t.surface, color: t.ink } } },
    MuiDrawer: { styleOverrides: { paper: { background: t.surface, borderRight: `1px solid ${t.rule}` } } },
    MuiTableCell: { styleOverrides: { root: { borderColor: t.rule }, head: { color: t.inkMuted, fontWeight: 600 } } },
    MuiButton: { defaultProps: { disableElevation: true } },
  },
});
