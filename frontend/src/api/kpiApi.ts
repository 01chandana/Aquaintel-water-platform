import type { KpiCurrent, KpiDefinition, KpiValue } from '@/types/models';
import { baseApi, clean, unwrap } from './baseApi';

export type DashboardView = 'executive' | 'operations' | 'energy' | 'quality' | 'maintenance' | 'compliance';

export const kpiApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    kpis: b.query<KpiDefinition[], { category?: string; q?: string } | void>({
      query: (p) => ({ url: '/kpis', params: clean(p ?? {}) }),
      transformResponse: unwrap<KpiDefinition[]>,
      providesTags: ['Kpi'],
    }),
    kpi: b.query<KpiDefinition, string>({ query: (id) => `/kpis/${id}`, transformResponse: unwrap<KpiDefinition> }),
    kpiValues: b.query<KpiValue[], { id: string; start?: string; end?: string; asset_id?: string; bucket?: 'hour' | 'day' }>({
      query: ({ id, ...p }) => ({ url: `/kpis/${id}/values`, params: clean(p) }),
      transformResponse: unwrap<KpiValue[]>,
      providesTags: ['Kpi'],
    }),
    kpiCurrent: b.query<KpiCurrent, { id: string; asset_id?: string }>({
      query: ({ id, ...p }) => ({ url: `/kpis/${id}/current`, params: clean(p) }),
      transformResponse: unwrap<KpiCurrent>,
      providesTags: ['Kpi'],
    }),
    dashboardKpis: b.query<KpiCurrent[], { view: DashboardView; site_id?: string | null }>({
      query: (p) => ({ url: '/kpis/dashboard', params: clean(p) }),
      transformResponse: unwrap<KpiCurrent[]>,
      providesTags: ['Kpi'],
    }),
    categories: b.query<string[], void>({ query: () => '/kpis/categories', transformResponse: unwrap<string[]> }),
    healthHeatmap: b.query<{ asset_id: string; asset: string; category: string; time: string; value: number }[], void>({
      query: () => '/kpis/health-heatmap',
      transformResponse: unwrap,
      providesTags: ['Kpi'],
    }),
    createKpi: b.mutation<KpiDefinition, Record<string, unknown>>({
      query: (body) => ({ url: '/kpis', method: 'POST', body }),
      transformResponse: unwrap<KpiDefinition>,
      invalidatesTags: ['Kpi'],
    }),
    computeKpis: b.mutation<{ task_id: string }, void>({ query: () => ({ url: '/kpis/compute', method: 'POST' }), transformResponse: unwrap, invalidatesTags: ['Kpi'] }),
  }),
});

export const {
  useKpisQuery, useKpiQuery, useKpiValuesQuery, useKpiCurrentQuery, useDashboardKpisQuery, useCategoriesQuery,
  useHealthHeatmapQuery, useCreateKpiMutation, useComputeKpisMutation,
} = kpiApi;
