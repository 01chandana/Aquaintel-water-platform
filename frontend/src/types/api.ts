/** Standard response envelope (spec Ch. 7.2.3 / 7.2.4). */
export interface PageMeta {
  page: number;
  per_page: number;
  total: number;
  total_pages: number;
}

export interface Envelope<T> {
  status: 'success';
  data: T;
  meta?: PageMeta & Record<string, unknown>;
  request_id: string;
}

export interface ApiErrorBody {
  status: 'error';
  error: { code: string; message: string; details: { field: string; message: string; code: string }[] };
  request_id: string;
}

export interface Paged<T> {
  items: T[];
  meta: PageMeta;
}

export interface ListParams {
  page?: number;
  per_page?: number;
  [key: string]: string | number | boolean | undefined | null;
}
