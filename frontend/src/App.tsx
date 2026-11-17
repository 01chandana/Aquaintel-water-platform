import { CssBaseline, LinearProgress, ThemeProvider } from '@mui/material';
import { Suspense } from 'react';
import { RouterProvider } from 'react-router-dom';
import { useAppTheme } from '@/hooks/useTheme';
import { router } from './Router';

export function App() {
  const theme = useAppTheme();
  return (
    <ThemeProvider theme={theme}>
      <CssBaseline enableColorScheme />
      <Suspense fallback={<LinearProgress />}>
        <RouterProvider router={router} />
      </Suspense>
    </ThemeProvider>
  );
}
