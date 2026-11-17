import type { ListParams, Paged } from '@/types/api';
import type { Alert, Rule } from '@/types/models';
import { baseApi, clean, unwrap, unwrapPaged } from './baseApi';

export interface AlertAnalytics {
  total: number;
  open: number;
  mean_time_to_acknowledge_min: number | null;
  mean_time_to_resolve_min: number | null;
  false_positive_rate_pct: number | null;
  suppressed: number;
  by_severity: Record<string, number>;
  volume_trend: ({ date: string } & Record<string, number | string>)[];
  pareto_by_asset: { name: string; count: number }[];
  pareto_by_rule_type: { name: string; count: number }[];
  operator_response: { operator: string; acknowledged: number; avg_ack_min: number }[];
}

export interface ReplayResult {
  triggered: boolean;
  trigger_count: number;
  episodes: { start: number | string; end: number | string | null; peak: number; message: string; samples: number }[];
  points_evaluated?: number;
}

export interface Incident {
  id: string;
  title: string;
  severity: string;
  status: string;
  alert_count: number;
  root_cause_hint: string | null;
  created_at: string;
  alerts: Alert[];
}

export const alertApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    alerts: b.query<Paged<Alert>, ListParams>({
      query: (p) => ({ url: '/alerts', params: clean(p) }),
      transformResponse: unwrapPaged<Alert>,
      providesTags: ['Alert'],
    }),
    alert: b.query<Alert, string>({ query: (id) => `/alerts/${id}`, transformResponse: unwrap<Alert>, providesTags: (_r, _e, id) => [{ type: 'Alert', id }] }),
    acknowledge: b.mutation<Alert, { id: string; note?: string }>({
      query: ({ id, note }) => ({ url: `/alerts/${id}/acknowledge`, method: 'POST', body: { note } }),
      transformResponse: unwrap<Alert>,
      // optimistic update of the cached list (Ch. 8.7 "optimistic updates")
      async onQueryStarted({ id }, { dispatch, queryFulfilled, getState }) {
        const patches = alertApi.util.selectInvalidatedBy(getState(), ['Alert']).map((entry) =>
          entry.endpointName === 'alerts'
            ? dispatch(alertApi.util.updateQueryData('alerts', entry.originalArgs as ListParams, (draft) => {
                const a = draft.items.find((x) => x.id === id);
                if (a) a.status = 'acknowledged';
              }))
            : null,
        );
        try {
          await queryFulfilled;
        } catch {
          patches.forEach((p) => p?.undo());
        }
      },
      invalidatesTags: ['Alert'],
    }),
    resolve: b.mutation<Alert, { id: string; note?: string; is_false_positive?: boolean; close?: boolean }>({
      query: ({ id, ...body }) => ({ url: `/alerts/${id}/resolve`, method: 'POST', body }),
      transformResponse: unwrap<Alert>,
      invalidatesTags: ['Alert', 'AssetTree'],
    }),
    escalate: b.mutation<Alert, { id: string; note?: string }>({
      query: ({ id, note }) => ({ url: `/alerts/${id}/escalate`, method: 'POST', body: { note } }),
      transformResponse: unwrap<Alert>,
      invalidatesTags: ['Alert'],
    }),
    bulkAlerts: b.mutation<{ succeeded: string[]; failed: unknown[] }, { alert_ids: string[]; action: 'acknowledge' | 'resolve' }>({
      query: (body) => ({ url: '/alerts/bulk', method: 'POST', body }),
      transformResponse: unwrap<{ succeeded: string[]; failed: unknown[] }>,
      invalidatesTags: ['Alert', 'AssetTree'],
    }),
    analytics: b.query<AlertAnalytics, number>({ query: (days) => `/alerts/analytics?days=${days}`, transformResponse: unwrap<AlertAnalytics>, providesTags: ['Alert'] }),
    incidents: b.query<Paged<Incident>, void>({ query: () => '/alerts/incidents?per_page=20', transformResponse: unwrapPaged<Incident>, providesTags: ['Alert'] }),
    rules: b.query<Paged<Rule>, ListParams>({ query: (p) => ({ url: '/alerts/rules', params: clean(p) }), transformResponse: unwrapPaged<Rule>, providesTags: ['Rule'] }),
    createRule: b.mutation<Rule, Partial<Rule>>({ query: (body) => ({ url: '/alerts/rules', method: 'POST', body }), transformResponse: unwrap<Rule>, invalidatesTags: ['Rule'] }),
    updateRule: b.mutation<Rule, { id: string; body: Partial<Rule> }>({
      query: ({ id, body }) => ({ url: `/alerts/rules/${id}`, method: 'PUT', body }),
      transformResponse: unwrap<Rule>,
      invalidatesTags: ['Rule'],
    }),
    toggleRule: b.mutation<Rule, string>({ query: (id) => ({ url: `/alerts/rules/${id}/toggle`, method: 'PUT' }), transformResponse: unwrap<Rule>, invalidatesTags: ['Rule'] }),
    deleteRule: b.mutation<void, string>({ query: (id) => ({ url: `/alerts/rules/${id}`, method: 'DELETE' }), invalidatesTags: ['Rule'] }),
    testRule: b.mutation<ReplayResult, { rule: Partial<Rule>; values: number[]; interval_seconds: number }>({
      query: (body) => ({ url: '/alerts/rules/test', method: 'POST', body }),
      transformResponse: unwrap<ReplayResult>,
    }),
    simulateRule: b.mutation<ReplayResult, { id: string; start: string; end: string }>({
      query: ({ id, ...body }) => ({ url: `/alerts/rules/${id}/simulate`, method: 'POST', body }),
      transformResponse: unwrap<ReplayResult>,
    }),
  }),
});

export const {
  useAlertsQuery, useAlertQuery, useAcknowledgeMutation, useResolveMutation, useEscalateMutation, useBulkAlertsMutation,
  useAnalyticsQuery, useIncidentsQuery, useRulesQuery, useCreateRuleMutation, useUpdateRuleMutation, useToggleRuleMutation,
  useDeleteRuleMutation, useTestRuleMutation, useSimulateRuleMutation,
} = alertApi;
