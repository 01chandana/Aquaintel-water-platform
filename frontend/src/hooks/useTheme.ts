import { useMemo } from 'react';
import { useAppSelector } from '@/store';
import { darkTheme } from '@/theme/darkTheme';
import { lightTheme } from '@/theme/lightTheme';

export function useAppTheme() {
  const mode = useAppSelector((s) => s.ui.themeMode);
  return useMemo(() => (mode === 'dark' ? darkTheme : lightTheme), [mode]);
}
