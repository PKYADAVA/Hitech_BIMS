/**
 * Server lookups a form asks mid-edit — what an item costs, what is in stock,
 * which batches a farm is running.
 *
 * These live apart from `config/forms.ts` because `config/documents.ts` needs
 * them too, and forms.ts already imports documents.ts: putting them in either
 * config module makes the two import each other. Nothing here knows about a
 * form; each is one request and its answer.
 */
import { http } from "@/api/client";
import { Envelope } from "@/api/types";

export interface ItemLookup {
  unit: string;
  rate: string;
  price_missing: boolean;
  message: string;
}

/** An item's unit and its Item Price Master rate on a date. */
export const stockTransferItem = async (
  itemId: string,
  date?: string
): Promise<ItemLookup> =>
  (await http.get<Envelope<ItemLookup>>("/inventory/stock-transfer-item", {
    params: { item: itemId, ...(date ? { date } : {}) },
  })).data.data;

/** What is actually at a location on a date — the figure the save enforces. */
export const stockTransferStock = async (
  locationType: string,
  locationId: string,
  itemId: string,
  date: string
): Promise<string> =>
  (await http.get<Envelope<{ stock: string }>>("/inventory/stock-transfer-stock", {
    params: { location_type: locationType, location_id: locationId, item: itemId, date },
  })).data.data.stock;

export interface FarmBatch {
  id: number;
  batch_name: string;
  is_active: boolean;
}

/**
 * A farm's batches, for a transfer's Batch box.
 *
 * Every batch with the current one flagged, as the web lookup reports them —
 * chicks go onto a fresh flock, but a correction filed a week later belongs to
 * the batch it was about.
 */
export const farmBatches = async (farmId: string): Promise<FarmBatch[]> =>
  (await http.get<Envelope<FarmBatch[]>>("/inventory/farm-batches", {
    params: { farm: farmId },
  })).data.data;
