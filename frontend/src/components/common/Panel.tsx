import { Box, Paper, Typography, type PaperProps } from '@mui/material';
import type { ReactNode } from 'react';

interface Props extends Omit<PaperProps, 'title'> {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  dense?: boolean;
}

/** A titled region. Borders, not shadows, separate content (operator displays stay flat). */
export function Panel({ title, subtitle, actions, children, dense, sx, ...rest }: Props) {
  return (
    <Paper component="section" sx={{ p: dense ? 1.5 : 2, display: 'flex', flexDirection: 'column', minWidth: 0, ...sx }} {...rest}>
      {(title || actions) && (
        <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, mb: 1.5 }}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            {title && <Typography variant="h4" component="h2">{title}</Typography>}
            {subtitle && <Typography variant="body2" color="text.secondary">{subtitle}</Typography>}
          </Box>
          {actions}
        </Box>
      )}
      {children}
    </Paper>
  );
}
