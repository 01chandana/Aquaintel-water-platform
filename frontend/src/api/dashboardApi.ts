import type { Dashboard, Widget } from '@/types/models';
import { baseApi, unwrap } from './baseApi';

export const dashboardApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    dashboards: b.query<Dashboard[], void>({ query: () => '/dashboards', transformResponse: unwrap<Dashboard[]>, providesTags: ['Dashboard'] }),
    templates: b.query<Dashboard[], void>({ query: () => '/dashboards/templates', transformResponse: unwrap<Dashboard[]> }),
    dashboard: b.query<Dashboard, string>({ query: (id) => `/dashboards/${id}`, transformResponse: unwrap<Dashboard>, providesTags: (_r, _e, id) => [{ type: 'Dashboard', id }] }),
    createDashboard: b.mutation<Dashboard, { name: string; template_id?: string; is_shared?: boolean }>({
      query: (body) => ({ url: '/dashboards', method: 'POST', body }),
      transformResponse: unwrap<Dashboard>,
      invalidatesTags: ['Dashboard'],
    }),
    updateDashboard: b.mutation<Dashboard, { id: string; body: Record<string, unknown> }>({
      query: ({ id, body }) => ({ url: `/dashboards/${id}`, method: 'PUT', body }),
      transformResponse: unwrap<Dashboard>,
      invalidatesTags: (_r, _e, { id }) => [{ type: 'Dashboard', id }, 'Dashboard'],
    }),
    deleteDashboard: b.mutation<void, string>({ query: (id) => ({ url: `/dashboards/${id}`, method: 'DELETE' }), invalidatesTags: ['Dashboard'] }),
    addWidget: b.mutation<Widget, { id: string; body: Omit<Widget, 'id' | 'position_index'> & { position_index?: number } }>({
      query: ({ id, body }) => ({ url: `/dashboards/${id}/widgets`, method: 'POST', body }),
      transformResponse: unwrap<Widget>,
      invalidatesTags: (_r, _e, { id }) => [{ type: 'Dashboard', id }],
    }),
    updateWidget: b.mutation<Widget, { id: string; wid: string; body: Omit<Widget, 'id'> }>({
      query: ({ id, wid, body }) => ({ url: `/dashboards/${id}/widgets/${wid}`, method: 'PUT', body }),
      transformResponse: unwrap<Widget>,
      invalidatesTags: (_r, _e, { id }) => [{ type: 'Dashboard', id }],
    }),
    deleteWidget: b.mutation<void, { id: string; wid: string }>({
      query: ({ id, wid }) => ({ url: `/dashboards/${id}/widgets/${wid}`, method: 'DELETE' }),
      invalidatesTags: (_r, _e, { id }) => [{ type: 'Dashboard', id }],
    }),
  }),
});

export const {
  useDashboardsQuery, useTemplatesQuery, useDashboardQuery, useCreateDashboardMutation, useUpdateDashboardMutation,
  useDeleteDashboardMutation, useAddWidgetMutation, useUpdateWidgetMutation, useDeleteWidgetMutation,
} = dashboardApi;
