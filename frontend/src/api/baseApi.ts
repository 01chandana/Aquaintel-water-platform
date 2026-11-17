import { createApi, fetchBaseQuery, type BaseQueryFn, type FetchArgs, type FetchBaseQueryError } from '@reduxjs/toolkit/query/react';
import { loggedOut, tokensReceived } from '@/store/authSlice';
import type { Envelope, Paged } from '@/types/api';
import type { TokenPair } from '@/types/models';

export const API_URL = (import.meta.env.VITE_API_URL ?? '') + '/v1';

const rawBaseQuery = fetchBaseQuery({
  baseUrl: API_URL,
  prepareHeaders: (headers, { getState }) => {
    const token = (getState() as { auth: { accessToken: string | null } }).auth.accessToken;
    if (token) headers.set('Authorization', `Bearer ${token}`);
    return headers;
  },
});

let refreshing: Promise<boolean> | null = null;

/** Transparent access-token refresh with rotation (Ch. 17.2.1); one refresh in flight at a time. */
const baseQueryWithReauth: BaseQueryFn<string | FetchArgs, unknown, FetchBaseQueryError> = async (args, api, extra) => {
  let result = await rawBaseQuery(args, api, extra);
  if (result.error?.status === 401) {
    const refreshToken = (api.getState() as { auth: { refreshToken: string | null } }).auth.refreshToken;
    if (!refreshToken) {
      api.dispatch(loggedOut());
      return result;
    }
    refreshing ??= (async () => {
      const r = await rawBaseQuery({ url: '/auth/refresh', method: 'POST', body: { refresh_token: refreshToken } }, api, extra);
      if (r.data) {
        api.dispatch(tokensReceived((r.data as Envelope<TokenPair>).data));
        return true;
      }
      api.dispatch(loggedOut());
      return false;
    })().finally(() => {
      refreshing = null;
    });
    if (await refreshing) result = await rawBaseQuery(args, api, extra);
  }
  return result;
};

export const TAGS = [
  'Asset', 'AssetTree', 'Tag', 'Alert', 'Rule', 'Kpi', 'Dashboard', 'Report', 'Schedule', 'WorkOrder',
  'Model', 'Plan', 'User', 'ApiKey', 'Config', 'Audit',
] as const;

export const baseApi = createApi({
  reducerPath: 'api',
  baseQuery: baseQueryWithReauth,
  tagTypes: TAGS,
  endpoints: () => ({}),
});

/** Unwrap the `{status, data, meta}` envelope. */
export const unwrap = <T,>(r: Envelope<T>): T => r.data;
export const unwrapPaged = <T,>(r: Envelope<T[]>): Paged<T> => ({
  items: r.data,
  meta: (r.meta ?? { page: 1, per_page: r.data.length, total: r.data.length, total_pages: 1 }) as Paged<T>['meta'],
});

export const clean = (params?: Record<string, unknown>): Record<string, string> =>
  Object.fromEntries(
    Object.entries(params ?? {})
      .filter(([, v]) => v !== undefined && v !== null && v !== '')
      .map(([k, v]) => [k, String(v)]),
  );
