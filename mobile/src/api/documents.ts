import { http } from "./client";
import { Envelope } from "./types";

export interface DocumentDetail {
  header: Record<string, string>;
  items: Record<string, string>[];
}

/** Load an existing document (header + line items) in the form's field shape. */
export async function loadDocument(
  savePath: string,
  id: number | string
): Promise<DocumentDetail> {
  return (await http.get<Envelope<DocumentDetail>>(`${savePath}/${id}`)).data.data;
}

/** Delete a transaction document (reuses the web unposting). */
export async function deleteDocument(savePath: string, id: number | string): Promise<void> {
  await http.delete(`${savePath}/${id}`);
}

/**
 * Create (POST) or update (PUT) a transaction *document* (header + line items)
 * through its `/save` endpoint. Unlike the generic resource CRUD, these reuse
 * the web posting logic on the backend (stock movement, ledger, validation).
 */
export async function saveDocument(
  savePath: string,
  payload: unknown,
  id?: number | string | null
): Promise<unknown> {
  if (id != null) {
    return (await http.put<Envelope<unknown>>(`${savePath}/${id}`, payload)).data.data;
  }
  return (await http.post<Envelope<unknown>>(savePath, payload)).data.data;
}
