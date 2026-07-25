/** Shapes mirroring the backend's `/api/v1/` response envelope. */

export interface Envelope<T> {
  success: boolean;
  data: T;
  error: ApiErrorBody | null;
  meta: { pagination?: Pagination };
}

export interface ApiErrorBody {
  code: string;
  message: string;
  fields: Record<string, string[]>;
}

export type Pagination = PagePagination | CursorPagination;

export interface PagePagination {
  type: "page";
  count: number;
  page: number;
  num_pages: number;
  page_size: number;
  next: string | null;
  previous: string | null;
}

export interface CursorPagination {
  type: "cursor";
  page_size: number;
  next: string | null;
  previous: string | null;
}

export interface AuthUser {
  id: number;
  username: string;
  email: string;
  full_name: string;
  is_staff: boolean;
  is_superuser: boolean;
  role: string;
  department: string;
  groups: string[];
}

export interface LoginResult {
  access: string;
  refresh: string;
  user: AuthUser;
}

/** Domain rows come back from `__all__` serializers, so they're open records. */
export type Row = Record<string, unknown> & { id: number };

/** Thrown by the axios layer for any non-2xx response. */
export class ApiError extends Error {
  code: string;
  fields: Record<string, string[]>;
  status?: number;

  constructor(body: ApiErrorBody, status?: number) {
    super(body.message || "Request failed");
    this.name = "ApiError";
    this.code = body.code || "error";
    this.fields = body.fields || {};
    this.status = status;
  }
}
