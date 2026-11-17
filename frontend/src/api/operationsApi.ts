/** Work orders, ML, optimization and admin endpoints. */
import type { ListParams, Paged } from '@/types/api';
import type { ApiKey, AuditEntry, MlModel, OptimizationPlan, User, WorkOrder } from '@/types/models';
import { baseApi, clean, unwrap, unwrapPaged } from './baseApi';

export interface Prediction {
  value: number;
  label?: string;
  latency_ms: number;
  version: string;
  [key: string]: unknown;
}

export interface DriftFeature {
  feature: string;
  psi: number;
  kl_divergence: number;
  ks_statistic: number;
  baseline_mean: number;
  current_mean: number;
  seasonal: boolean;
  status: string;
}

export interface DriftReport {
  model: string;
  version: string;
  status: 'ok' | 'drift' | 'collecting';
  window_start: string;
  rows: number;
  max_psi: number | null;
  monitored_max_psi: number | null;
  drift_detected: boolean;
  retrain_recommended: boolean;
  features: DriftFeature[];
}

export interface ConfigItem {
  key: string;
  value: unknown;
  description: string;
  readonly?: boolean;
  updated_at?: string | null;
}

export const operationsApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    workOrders: b.query<Paged<WorkOrder>, ListParams>({
      query: (p) => ({ url: '/work-orders', params: clean(p) }),
      transformResponse: unwrapPaged<WorkOrder>,
      providesTags: ['WorkOrder'],
    }),
    createWorkOrder: b.mutation<WorkOrder, Record<string, unknown>>({
      query: (body) => ({ url: '/work-orders', method: 'POST', body }),
      transformResponse: unwrap<WorkOrder>,
      invalidatesTags: ['WorkOrder', 'Alert'],
    }),
    updateWorkOrder: b.mutation<WorkOrder, { id: string; body: Record<string, unknown> }>({
      query: ({ id, body }) => ({ url: `/work-orders/${id}`, method: 'PUT', body }),
      transformResponse: unwrap<WorkOrder>,
      invalidatesTags: ['WorkOrder'],
    }),
    assignWorkOrder: b.mutation<WorkOrder, { id: string; assigned_to: string }>({
      query: ({ id, assigned_to }) => ({ url: `/work-orders/${id}/assign`, method: 'POST', body: { assigned_to } }),
      transformResponse: unwrap<WorkOrder>,
      invalidatesTags: ['WorkOrder'],
    }),
    completeWorkOrder: b.mutation<WorkOrder, { id: string; body: Record<string, unknown> }>({
      query: ({ id, body }) => ({ url: `/work-orders/${id}/complete`, method: 'POST', body }),
      transformResponse: unwrap<WorkOrder>,
      invalidatesTags: ['WorkOrder', 'Alert'],
    }),
    models: b.query<MlModel[], { stage?: string } | void>({
      query: (p) => ({ url: '/ml/models', params: clean(p ?? {}) }),
      transformResponse: unwrap<MlModel[]>,
      providesTags: ['Model'],
    }),
    deployModel: b.mutation<MlModel, { id: string; stage: string; note?: string }>({
      query: ({ id, ...body }) => ({ url: `/ml/models/${id}/deploy`, method: 'POST', body }),
      transformResponse: unwrap<MlModel>,
      invalidatesTags: ['Model'],
    }),
    trainModel: b.mutation<{ task_id: string }, string>({ query: (name) => ({ url: `/ml/models/train?name=${name}`, method: 'POST' }), transformResponse: unwrap }),
    predict: b.mutation<Prediction, { id: string; asset_id?: string; horizon_hours?: number }>({
      query: ({ id, ...body }) => ({ url: `/ml/models/${id}/predict`, method: 'POST', body }),
      transformResponse: unwrap<Prediction>,
    }),
    modelPerformance: b.query<Record<string, any>, string>({ query: (id) => `/ml/models/${id}/performance`, transformResponse: unwrap }), // eslint-disable-line @typescript-eslint/no-explicit-any
    drift: b.query<DriftReport[], void>({ query: () => '/ml/drift/report', transformResponse: unwrap<DriftReport[]> }),
    pumpSchedule: b.mutation<OptimizationPlan, Record<string, unknown>>({
      query: (body) => ({ url: '/optimization/pump-schedule', method: 'POST', body }),
      transformResponse: unwrap<OptimizationPlan>,
      invalidatesTags: ['Plan'],
    }),
    dosing: b.mutation<OptimizationPlan, Record<string, unknown>>({
      query: (body) => ({ url: '/optimization/dosing', method: 'POST', body }),
      transformResponse: unwrap<OptimizationPlan>,
      invalidatesTags: ['Plan'],
    }),
    plans: b.query<Paged<OptimizationPlan>, string | void>({
      query: (t) => `/optimization/schedules?per_page=20${t ? `&schedule_type=${t}` : ''}`,
      transformResponse: unwrapPaged<OptimizationPlan>,
      providesTags: ['Plan'],
    }),
    approvePlan: b.mutation<OptimizationPlan, string>({ query: (id) => ({ url: `/optimization/schedules/${id}/approve`, method: 'POST' }), transformResponse: unwrap<OptimizationPlan>, invalidatesTags: ['Plan'] }),
    users: b.query<Paged<User>, ListParams>({ query: (p) => ({ url: '/users', params: clean(p) }), transformResponse: unwrapPaged<User>, providesTags: ['User'] }),
    createUser: b.mutation<User, Record<string, unknown>>({ query: (body) => ({ url: '/users', method: 'POST', body }), transformResponse: unwrap<User>, invalidatesTags: ['User'] }),
    updateUser: b.mutation<User, { id: string; body: Record<string, unknown> }>({ query: ({ id, body }) => ({ url: `/users/${id}`, method: 'PUT', body }), transformResponse: unwrap<User>, invalidatesTags: ['User'] }),
    assignRole: b.mutation<User, { id: string; role: string }>({ query: ({ id, role }) => ({ url: `/users/${id}/role`, method: 'PUT', body: { role } }), transformResponse: unwrap<User>, invalidatesTags: ['User'] }),
    deactivateUser: b.mutation<void, string>({ query: (id) => ({ url: `/users/${id}`, method: 'DELETE' }), invalidatesTags: ['User'] }),
    auditLog: b.query<Paged<AuditEntry>, ListParams>({ query: (p) => ({ url: '/admin/audit-log', params: clean(p) }), transformResponse: unwrapPaged<AuditEntry>, providesTags: ['Audit'] }),
    verifyAudit: b.mutation<{ valid: boolean; checked: number; head_hash?: string; broken_at_id?: number; reason?: string }, void>({
      query: () => '/admin/audit-log/verify',
      transformResponse: unwrap,
    }),
    systemConfig: b.query<ConfigItem[], void>({ query: () => '/admin/system-config', transformResponse: unwrap<ConfigItem[]>, providesTags: ['Config'] }),
    updateConfig: b.mutation<ConfigItem[], Record<string, unknown>>({
      query: (values) => ({ url: '/admin/system-config', method: 'PUT', body: { values } }),
      transformResponse: unwrap<ConfigItem[]>,
      invalidatesTags: ['Config', 'Audit'],
    }),
    adminMetrics: b.query<Record<string, any>, void>({ query: () => '/admin/metrics', transformResponse: unwrap }), // eslint-disable-line @typescript-eslint/no-explicit-any
    usageStats: b.query<Record<string, any>, void>({ query: () => '/admin/usage-stats', transformResponse: unwrap }), // eslint-disable-line @typescript-eslint/no-explicit-any
    queueStatus: b.query<Record<string, any>, void>({ query: () => '/admin/queue-status', transformResponse: unwrap }), // eslint-disable-line @typescript-eslint/no-explicit-any
    health: b.query<{ status: string; version: string; uptime_seconds: number; checks: Record<string, Record<string, unknown>> }, void>({ query: () => ({ url: '/health/ready' }) }),
    adminLogs: b.query<Record<string, unknown>[], string | void>({ query: (level) => `/admin/logs?limit=200${level ? `&level=${level}` : ''}`, transformResponse: unwrap }),
    apiKeys: b.query<Paged<ApiKey>, void>({ query: () => '/admin/api-keys', transformResponse: unwrapPaged<ApiKey>, providesTags: ['ApiKey'] }),
    createApiKey: b.mutation<ApiKey, { name: string; permissions: string[]; asset_scopes: string[]; expires_in_days: number }>({
      query: (body) => ({ url: '/admin/api-keys', method: 'POST', body }),
      transformResponse: unwrap<ApiKey>,
      invalidatesTags: ['ApiKey'],
    }),
    revokeApiKey: b.mutation<void, string>({ query: (id) => ({ url: `/admin/api-keys/${id}`, method: 'DELETE' }), invalidatesTags: ['ApiKey'] }),
  }),
});

export const {
  useWorkOrdersQuery, useCreateWorkOrderMutation, useUpdateWorkOrderMutation, useAssignWorkOrderMutation,
  useCompleteWorkOrderMutation, useModelsQuery, useDeployModelMutation, useTrainModelMutation, usePredictMutation,
  useModelPerformanceQuery, useDriftQuery, usePumpScheduleMutation, useDosingMutation, usePlansQuery, useApprovePlanMutation,
  useUsersQuery, useCreateUserMutation, useUpdateUserMutation, useAssignRoleMutation, useDeactivateUserMutation,
  useAuditLogQuery, useVerifyAuditMutation, useSystemConfigQuery, useUpdateConfigMutation, useAdminMetricsQuery,
  useUsageStatsQuery, useQueueStatusQuery, useHealthQuery, useAdminLogsQuery, useApiKeysQuery, useCreateApiKeyMutation,
  useRevokeApiKeyMutation,
} = operationsApi;
