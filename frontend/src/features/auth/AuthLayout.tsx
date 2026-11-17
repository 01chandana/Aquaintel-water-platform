import { WaterDrop } from '@mui/icons-material';
import { Box, Paper, Typography } from '@mui/material';
import type { ReactNode } from 'react';
import { tokens } from '@/theme/palette';

export function AuthLayout({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: { xs: '1fr', md: '1.1fr 1fr' } }}>
      <Box sx={{ display: { xs: 'none', md: 'flex' }, flexDirection: 'column', justifyContent: 'flex-end', p: 6, borderRight: 1, borderColor: 'divider',
        background: `radial-gradient(120% 80% at 0% 100%, ${tokens.brand}1f, transparent 60%)` }}>
        <WaterDrop sx={{ fontSize: 40, color: tokens.brand, mb: 2 }} />
        <Typography variant="h1" sx={{ fontSize: '2.25rem', maxWidth: 460, lineHeight: 1.15 }}>
          Every pump, sample and kilowatt in one operating picture.
        </Typography>
        <Typography color="text.secondary" sx={{ mt: 2, maxWidth: 440 }}>
          Real-time telemetry, alarm management, predictive maintenance and compliance reporting for water treatment and distribution.
        </Typography>
      </Box>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', p: 3 }}>
        <Paper sx={{ p: 4, width: '100%', maxWidth: 400 }}>
          <Typography variant="h2" component="h1" sx={{ mb: 3 }}>{title}</Typography>
          {children}
        </Paper>
      </Box>
    </Box>
  );
}
