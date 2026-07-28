import { http } from "./client";
import { Envelope } from "./types";

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
