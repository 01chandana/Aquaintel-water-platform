import { configureStore } from '@reduxjs/toolkit';
import { setupListeners } from '@reduxjs/toolkit/query';
import { useDispatch, useSelector } from 'react-redux';
import { baseApi } from '@/api/baseApi';
import { persistenceMiddleware } from './middleware';
import { rootReducer } from './rootReducer';

export const makeStore = () =>
  configureStore({
    reducer: rootReducer,
    middleware: (getDefault) => getDefault().concat(baseApi.middleware, persistenceMiddleware),
  });

export const store = makeStore();
setupListeners(store.dispatch); // refetch on focus / reconnect

export type RootState = ReturnType<typeof rootReducer>;
export type AppDispatch = typeof store.dispatch;
export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
