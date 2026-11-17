import { createSlice, type PayloadAction } from '@reduxjs/toolkit';
import type { TokenPair, User } from '@/types/models';

export interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: User | null;
}

const STORAGE_KEY = 'aquaintel.auth';

function load(): AuthState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as AuthState;
  } catch {
    /* storage unavailable: start signed out */
  }
  return { accessToken: null, refreshToken: null, user: null };
}

const authSlice = createSlice({
  name: 'auth',
  initialState: load,
  reducers: {
    tokensReceived(state, action: PayloadAction<TokenPair>) {
      state.accessToken = action.payload.access_token;
      state.refreshToken = action.payload.refresh_token;
    },
    userLoaded(state, action: PayloadAction<User>) {
      state.user = action.payload;
    },
    loggedOut(state) {
      state.accessToken = null;
      state.refreshToken = null;
      state.user = null;
    },
  },
});

export const { tokensReceived, userLoaded, loggedOut } = authSlice.actions;
export const authReducer = authSlice.reducer;
export { STORAGE_KEY as AUTH_STORAGE_KEY };
