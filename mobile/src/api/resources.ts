import { http } from "./client";
import { Envelope, Pagination, Row } from "./types";

/**
 * Generic resource helpers — one set of functions for *every* `/api/v1/`
 * endpoint, so no screen re-implements CRUD. The envelope is unwrapped here:
 * callers get plain rows + pagination, never the wrapper.
 */

export interface Page<T> {
  items: T[];
  pagination?: Pagination;
}

/** List a resource. `url` may be a relative path or an absolute pagination link. */
export async function listResource<T = Row>(
  url: string,
  params?: Record<string, string | number | undefined>
): Promise<Page<T>> {
  const isAbsolute = /^https?:\/\//i.test(url);
  const resp = await http.get<Envelope<T[]>>(isAbsolute ? url : url, {
    // Absolute pagination links already carry the query string.
    params: isAbsolute ? undefined : params,
    baseURL: isAbsolute ? "" : undefined,
  });
  return { items: resp.data.data, pagination: resp.data.meta?.pagination };
}

export async function getResource<T = Row>(path: string, id: number | string): Promise<T> {
  const resp = await http.get<Envelope<T>>(`${path}${id}/`);
  return resp.data.data;
}

export async function createResource<T = Row>(path: string, body: Partial<T>): Promise<T> {
  const resp = await http.post<Envelope<T>>(path, body);
  return resp.data.data;
}

export async function updateResource<T = Row>(
  path: string,
  id: number | string,
  body: Partial<T>
): Promise<T> {
  // PATCH = partial update, the mobile-friendly default.
  const resp = await http.patch<Envelope<T>>(`${path}${id}/`, body);
  return resp.data.data;
}

export async function deleteResource(path: string, id: number | string): Promise<void> {
  await http.delete(`${path}${id}/`);
}
