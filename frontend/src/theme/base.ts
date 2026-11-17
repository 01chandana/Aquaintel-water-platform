import { type ThemeOptions } from '@mui/material/styles';

export const typography: ThemeOptions['typography'] = {
  fontFamily: '"IBM Plex Sans", "Segoe UI", system-ui, sans-serif',
  fontSize: 14,
  h1: { fontSize: '1.75rem', fontWeight: 600, letterSpacing: '-0.01em' },
  h2: { fontSize: '1.375rem', fontWeight: 600 },
  h3: { fontSize: '1.125rem', fontWeight: 600 },
  h4: { fontSize: '1rem', fontWeight: 600 },
  subtitle1: { fontSize: '0.9375rem', fontWeight: 500 },
  subtitle2: { fontSize: '0.8125rem', fontWeight: 600 },
  body2: { fontSize: '0.8125rem' },
  caption: { fontSize: '0.75rem' },
  button: { textTransform: 'none', fontWeight: 600 },
};

export const shape = { borderRadius: 6 };
