import { createSlice, type PayloadAction } from '@reduxjs/toolkit';

export interface LiveAlert {
  alert_id: string;
  title: string;
  severity: string;
  status: string;
  asset_id: string | null;
  created_at?: string | null;
}

export interface UiState {
  themeMode: 'dark' | 'light';
  sidebarCollapsed: boolean;
  siteId: string | null;
  wsStatus: 'connecting' | 'open' | 'closed';
  liveAlerts: LiveAlert[];
  lastTelemetryAt: string | null;
}

const PREFS_KEY = 'aquaintel.ui';

function loadPrefs(): Pick<UiState, 'themeMode' | 'sidebarCollapsed' | 'siteId'> {
  try {
    const raw = localStorage.getItem(PREFS_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* ignore */
  }
  return { themeMode: 'dark', sidebarCollapsed: false, siteId: null };
}

const uiSlice = createSlice({
  name: 'ui',
  initialState: (): UiState => ({ ...loadPrefs(), wsStatus: 'closed', liveAlerts: [], lastTelemetryAt: null }),
  reducers: {
    toggleTheme(state) {
      state.themeMode = state.themeMode === 'dark' ? 'light' : 'dark';
    },
    toggleSidebar(state) {
      state.sidebarCollapsed = !state.sidebarCollapsed;
    },
    siteSelected(state, action: PayloadAction<string | null>) {
      state.siteId = action.payload;
    },
    wsStatusChanged(state, action: PayloadAction<UiState['wsStatus']>) {
      state.wsStatus = action.payload;
    },
    liveAlertReceived(state, action: PayloadAction<LiveAlert>) {
      state.liveAlerts = [action.payload, ...state.liveAlerts.filter((a) => a.alert_id !== action.payload.alert_id)].slice(0, 50);
    },
    telemetryTick(state, action: PayloadAction<string>) {
      state.lastTelemetryAt = action.payload;
    },
  },
});

export const { toggleTheme, toggleSidebar, siteSelected, wsStatusChanged, liveAlertReceived, telemetryTick } = uiSlice.actions;
export const uiReducer = uiSlice.reducer;
export { PREFS_KEY as UI_PREFS_KEY };
