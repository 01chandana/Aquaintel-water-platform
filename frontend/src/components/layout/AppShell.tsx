import { Box, LinearProgress } from '@mui/material';
import { Suspense } from 'react';
import { Outlet } from 'react-router-dom';
import { useWebSocket } from '@/hooks/useWebSocket';
import { Header } from './Header';
import { Sidebar } from './Sidebar';

export function AppShell() {
  useWebSocket();
  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <a href="#main" className="skip-link">Skip to content</a>
      <Sidebar />
      <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        <Header />
        <Box component="main" id="main" tabIndex={-1} sx={{ p: { xs: 1.5, md: 3 }, flex: 1, maxWidth: 1680, width: '100%', mx: 'auto' }}>
          <Suspense fallback={<LinearProgress aria-label="Loading page" />}>
            <Outlet />
          </Suspense>
        </Box>
      </Box>
      <Box id="live-region" aria-live="polite" sx={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }} />
    </Box>
  );
}
