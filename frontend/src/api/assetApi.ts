import type { ListParams, Paged } from '@/types/api';
import type { Alert, Asset, AssetNode, AssetType, LatestValue, Tag, TelemetryPoint, WorkOrder } from '@/types/models';
import { baseApi, clean, unwrap, unwrapPaged } from './baseApi';

export interface AssetKpi {
  code: string;
  name: string;
  unit: string;
  category: string;
  value: number;
  status: string;
  time: string;
  threshold_warning: number | null;
  threshold_critical: number | null;
}

export const assetApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    assetTree: b.query<AssetNode[], void>({ query: () => '/assets?view=tree', transformResponse: unwrap<AssetNode[]>, providesTags: ['AssetTree'] }),
    assets: b.query<Paged<Asset>, ListParams | void>({
      query: (p) => ({ url: '/assets', params: clean({ per_page: 200, ...(p ?? {}) }) }),
      transformResponse: unwrapPaged<Asset>,
      providesTags: ['Asset'],
    }),
    asset: b.query<Asset, string>({ query: (id) => `/assets/${id}`, transformResponse: unwrap<Asset>, providesTags: (_r, _e, id) => [{ type: 'Asset', id }] }),
    assetTypes: b.query<AssetType[], void>({ query: () => '/assets/types', transformResponse: unwrap<AssetType[]> }),
    searchAssets: b.query<Asset[], string>({ query: (q) => ({ url: '/assets/search', params: { q } }), transformResponse: unwrap<Asset[]> }),
    assetTelemetry: b.query<{ tags: Tag[]; points: (TelemetryPoint & { bucket?: string; avg_value?: number })[] }, { id: string; start?: string; end?: string; interval?: string; parameter?: string }>({
      query: ({ id, ...p }) => ({ url: `/assets/${id}/telemetry`, params: clean(p) }),
      transformResponse: unwrap,
    }),
    assetLatest: b.query<LatestValue[], string>({ query: (id) => `/assets/${id}/telemetry/latest`, transformResponse: unwrap<LatestValue[]> }),
    assetKpis: b.query<AssetKpi[], string>({ query: (id) => `/assets/${id}/kpis`, transformResponse: unwrap<AssetKpi[]> }),
    assetAlerts: b.query<Paged<Alert>, string>({ query: (id) => `/assets/${id}/alerts?per_page=25`, transformResponse: unwrapPaged<Alert>, providesTags: ['Alert'] }),
    assetWorkOrders: b.query<Paged<WorkOrder>, string>({ query: (id) => `/assets/${id}/work-orders?per_page=25`, transformResponse: unwrapPaged<WorkOrder>, providesTags: ['WorkOrder'] }),
    updateAsset: b.mutation<Asset, { id: string; body: Partial<Asset> }>({
      query: ({ id, body }) => ({ url: `/assets/${id}`, method: 'PUT', body }),
      transformResponse: unwrap<Asset>,
      invalidatesTags: (_r, _e, { id }) => [{ type: 'Asset', id }, 'Asset', 'AssetTree'],
    }),
    createAsset: b.mutation<Asset, Record<string, unknown>>({
      query: (body) => ({ url: '/assets', method: 'POST', body }),
      transformResponse: unwrap<Asset>,
      invalidatesTags: ['Asset', 'AssetTree'],
    }),
  }),
});

export const {
  useAssetTreeQuery, useAssetsQuery, useAssetQuery, useAssetTypesQuery, useSearchAssetsQuery, useAssetTelemetryQuery,
  useAssetLatestQuery, useAssetKpisQuery, useAssetAlertsQuery, useAssetWorkOrdersQuery, useUpdateAssetMutation,
  useCreateAssetMutation,
} = assetApi;
