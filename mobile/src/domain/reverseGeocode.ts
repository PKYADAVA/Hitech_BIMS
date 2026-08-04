import { http } from "@/api/client";
import { Envelope } from "@/api/types";

/**
 * A pin looked up as an address — the same result the ERP's
 * `window.reverseGeocode` produces, from the same Nominatim reply.
 *
 * Nominatim names the same administrative level differently by country and by
 * how built up the place is, so each part takes the first key that answers.
 * Getting that wrong is not a blank field, it is a plausible-looking wrong
 * one: `county` holding a city name reads exactly like a district.
 *
 * Never throws and never rejects. The coordinates are the record; the address
 * is a convenience on top, and a capture taken in a shed with no usable signal
 * has to save with the pin it has.
 */

export interface Place {
  /** The full formatted address, as offered for the Farm Address box. */
  display: string;
  state: string;
  district: string;
  area: string;
}

/** Nominatim's `address` object — every key optional, by its own contract. */
interface NominatimAddress {
  state?: string;
  state_district?: string;
  county?: string;
  district?: string;
  suburb?: string;
  village?: string;
  town?: string;
  city_district?: string;
  neighbourhood?: string;
  hamlet?: string;
  city?: string;
}

/** The parts of a Nominatim reply this uses. */
export interface NominatimReply {
  display_name?: string;
  address?: NominatimAddress;
}

const first = (...values: (string | undefined)[]) => values.find(Boolean) ?? "";

/** The mapping alone, so the key precedence can be tested without a network. */
export function placeFromReply(data: NominatimReply | null): Place | null {
  if (!data || !data.display_name) return null;
  const a = data.address ?? {};
  return {
    display: data.display_name,
    state: first(a.state),
    district: first(a.state_district, a.county, a.district),
    area: first(a.suburb, a.village, a.town, a.city_district, a.neighbourhood, a.hamlet, a.city),
  };
}

/**
 * Looked up through our own server, not straight from the device.
 *
 * Nominatim answers 403 to a request with no User-Agent, which is exactly what
 * React Native's fetch sends — so calling it directly returned nothing at all
 * on a phone while the same lookup worked in the ERP, whose browser always
 * sends one. The server proxy adds the header, caches the answer, and applies
 * `placeFromReply` for both clients.
 */
export async function reverseGeocode(
  latitude: number | string,
  longitude: number | string,
): Promise<Place | null> {
  try {
    const { data } = await http.get<Envelope<Place>>(
      "/geo/reverse", { params: { lat: String(latitude), lon: String(longitude) } });
    return data.data?.display ? data.data : null;
  } catch {
    // The coordinates are the record; the address is a convenience on top, so
    // a capture taken out of signal still saves the pin it has.
    return null;
  }
}
