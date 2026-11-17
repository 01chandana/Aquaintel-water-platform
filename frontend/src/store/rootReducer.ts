import { combineReducers } from '@reduxjs/toolkit';
import { baseApi } from '@/api/baseApi';
import { authReducer } from './authSlice';
import { uiReducer } from './uiSlice';

export const rootReducer = combineReducers({
  auth: authReducer,
  ui: uiReducer,
  [baseApi.reducerPath]: baseApi.reducer,
});
