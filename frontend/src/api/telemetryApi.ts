import type { AggregatePoint, LatestValue, Tag, TelemetryPoint } from '@/types/models';
import { baseApi, clean, unwrap } from './baseApi';

const tagParams = (ids: string[]) => ids.map((id) => `tag_ids=${encodeURIComponent(id)}`).join('&');

export const telemetryApi = baseApi.injectEndpoints({
  endpoints: (b) => ({
    tags: b.query<Tag[], { asset_id?: string; parameter?: string } | void>({
      query: (p) => ({ url: '/telemetry/tags', params: clean(p ?? {}) }),
      transformResponse: unwrap<Tag[]>,
      providesTags: ['Tag'],
    }),
    latest: b.query<LatestValue[], { parameter?: string; asset_id?: string } | void>({
      query: (p) => ({ url: '/telemetry/latest', params: clean(p ?? {}) }),
      transformResponse: unwrap<LatestValue[]>,
    }),
    rawSeries: b.query<TelemetryPoint[], { tagIds: string[]; start?: string; end?: string }>({
      query: ({ tagIds, ...p }) => `/telemetry/query?${tagParams(tagIds)}&${new URLSearchParams(clean(p))}`,
      transformResponse: unwrap<TelemetryPoint[]>,
    }),
    aggregate: b.query<AggregatePoint[], { tagIds: string[]; start?: string; end?: string; interval?: string; gapfill?: boolean }>({
      query: ({ tagIds, ...p }) => `/telemetry/query/aggregate?${tagParams(tagIds)}&${new URLSearchParams(clean(p))}`,
      transformResponse: unwrap<AggregatePoint[]>,
    }),
  }),
});

export const { useTagsQuery, useLatestQuery, useRawSeriesQuery, useAggregateQuery } = telemetryApi;
