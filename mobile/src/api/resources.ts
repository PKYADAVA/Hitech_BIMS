import { Platform } from "react-native";

import { toApiPath } from "@/config";

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
  // A pagination link is followed by path, not by host. DRF builds it from
  // whatever address Django saw, which behind the web build's proxy is the
  // backend's own — following that verbatim left the proxy and the browser
  // blocked it, so every list with a second page died on reaching it.
  const resp = await http.get<Envelope<T[]>>(isAbsolute ? toApiPath(url) : url, {
    // The link already carries its query string; params would duplicate it.
    params: isAbsolute ? undefined : params,
  });
  return { items: resp.data.data, pagination: resp.data.meta?.pagination };
}

export async function getResource<T = Row>(path: string, id: number | string): Promise<T> {
  const resp = await http.get<Envelope<T>>(`${path}${id}/`);
  return resp.data.data;
}

/**
 * Per-request overrides for a multipart body (a form carrying captured photos).
 *
 * The shared axios instance defaults to `application/json`, which would stop
 * the file ever being parsed. On native the boundary has to be produced by the
 * runtime, so the header is set explicitly; on web it must be *removed* so the
 * browser can generate the boundary itself — a hand-set multipart header with
 * no boundary is rejected.
 */
function bodyConfig(body: unknown) {
  if (typeof FormData === "undefined" || !(body instanceof FormData)) return undefined;
  return {
    headers: {
      "Content-Type": Platform.OS === "web" ? undefined : "multipart/form-data",
    },
  };
}

export async function createResource<T = Row>(
  path: string,
  body: Partial<T> | FormData
): Promise<T> {
  const resp = await http.post<Envelope<T>>(path, body, bodyConfig(body));
  return resp.data.data;
}

export async function updateResource<T = Row>(
  path: string,
  id: number | string,
  body: Partial<T> | FormData
): Promise<T> {
  // PATCH = partial update, the mobile-friendly default.
  const resp = await http.patch<Envelope<T>>(`${path}${id}/`, body, bodyConfig(body));
  return resp.data.data;
}

export async function deleteResource(path: string, id: number | string): Promise<void> {
  await http.delete(`${path}${id}/`);
}
