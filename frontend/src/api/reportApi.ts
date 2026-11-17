import type { Paged } from '@/types/api';
import type { Report, ReportSchedule } from '@/types/models';
import { API_URL, baseApi, unwrap, unwrapPaged } from './baseApi';

export interface ComplianceParameter {
  parameter: string;
  display_name: string;
  unit: string;
  limit_min: number | null;
  limit_max: number | null;
  regulation: string;
  samples: number;
  exceedances: number;
  compliance_pct: number | null;
  coverage_pct: number | null;
  status: string;
  series: { period: string; samples: number; exceedances: number; avg_value: number }[];
}

export interface ComplianceSummary {
  period: { start: string; end: string };
  overall_compliance_pct: number | null;
  total_samples: number;
  total_exceedances: number;
  parameters: ComplianceParameter[];
}

export interface Exceedance {
  time: string;
  value: number;
  tag: string;
  parameter: string;
  unit: string;
  asset_name: string;
  limit_min: number | null;
  limit_max: number | null;
  regulation: string;
  type: string;
}

export interface ReportRequest {
  report_type: string;
  format: 'pdf' | 'excel' | 'html';
  name?: string;
  sections?: string[];
  start?: string;
  end?: string;
}

export const reportApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    reports: b.query<Paged<Report>, number | void>({
      query: (page) => `/reports?per_page=25&page=${page ?? 1}`,
      transformResponse: unwrapPaged<Report>,
      providesTags: ['Report'],
    }),
    sections: b.query<{ types: Record<string, string[]>; all: string[] }, void>({ query: () => '/reports/sections', transformResponse: unwrap }),
    generateReport: b.mutation<Report, ReportRequest>({
      query: (body) => ({ url: '/reports/generate', method: 'POST', body }),
      transformResponse: unwrap<Report>,
      invalidatesTags: ['Report'],
    }),
    previewReport: b.mutation<string, ReportRequest>({
      query: (body) => ({ url: '/reports/preview', method: 'POST', body, responseHandler: 'text' }),
    }),
    schedules: b.query<ReportSchedule[], void>({ query: () => '/reports/schedules', transformResponse: unwrap<ReportSchedule[]>, providesTags: ['Schedule'] }),
    createSchedule: b.mutation<ReportSchedule, Record<string, unknown>>({
      query: (body) => ({ url: '/reports/schedules', method: 'POST', body }),
      transformResponse: unwrap<ReportSchedule>,
      invalidatesTags: ['Schedule'],
    }),
    deleteSchedule: b.mutation<void, string>({ query: (id) => ({ url: `/reports/schedules/${id}`, method: 'DELETE' }), invalidatesTags: ['Schedule'] }),
    complianceDaily: b.query<ComplianceSummary, string | void>({ query: (day) => `/compliance/summary/daily${day ? `?day=${day}` : ''}`, transformResponse: unwrap<ComplianceSummary> }),
    complianceMonthly: b.query<ComplianceSummary, void>({ query: () => '/compliance/summary/monthly', transformResponse: unwrap<ComplianceSummary> }),
    exceedances: b.query<Exceedance[], { parameter?: string } | void>({
      query: (p) => `/compliance/exceedances?limit=200${p?.parameter ? `&parameter=${p.parameter}` : ''}`,
      transformResponse: unwrap<Exceedance[]>,
    }),
  }),
});

/** Authenticated binary download (RTK Query caches JSON, so files are fetched directly). */
export async function downloadReport(id: string, name: string, token: string | null): Promise<void> {
  const res = await fetch(`${API_URL}/reports/${id}/download`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') ?? '';
  const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? name;
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

export const {
  useReportsQuery, useSectionsQuery, useGenerateReportMutation, usePreviewReportMutation, useSchedulesQuery,
  useCreateScheduleMutation, useDeleteScheduleMutation, useComplianceDailyQuery, useComplianceMonthlyQuery, useExceedancesQuery,
} = reportApi;
