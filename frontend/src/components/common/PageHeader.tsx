import { Box, Typography } from '@mui/material';
import type { ReactNode } from 'react';

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <Box sx={{ display: 'flex', alignItems: { xs: 'flex-start', md: 'center' }, flexDirection: { xs: 'column', md: 'row' }, gap: 1.5, mb: 2.5 }}>
      <Box sx={{ flex: 1 }}>
        <Typography variant="h1">{title}</Typography>
        {description && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, maxWidth: 760 }}>{description}</Typography>}
      </Box>
      {actions && <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>{actions}</Box>}
    </Box>
  );
}
