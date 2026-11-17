import type { Middleware } from '@reduxjs/toolkit';
import { AUTH_STORAGE_KEY } from './authSlice';
import { UI_PREFS_KEY } from './uiSlice';

/** Local-storage persistence for the auth and UI preference slices (Figure 8.2). */
export const persistenceMiddleware: Middleware = (api) => (next) => (action) => {
  const result = next(action);
  const state = api.getState() as { auth: unknown; ui: { themeMode: string; sidebarCollapsed: boolean; siteId: string | null } };
  try {
    localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(state.auth));
    const { themeMode, sidebarCollapsed, siteId } = state.ui;
    localStorage.setItem(UI_PREFS_KEY, JSON.stringify({ themeMode, sidebarCollapsed, siteId }));
  } catch {
    /* storage may be unavailable (private mode); state still lives in memory */
  }
  return result;
};
