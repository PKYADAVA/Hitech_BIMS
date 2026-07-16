"""Pure geographic math — no Django, no I/O.

Used by the route builder and (later) geofence evaluation. Kept dependency-
free so it is trivially unit-testable.
"""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance between two WGS-84 points, in kilometres."""
    rlat1, rlng1, rlat2, rlng2 = map(math.radians, (float(lat1), float(lng1),
                                                    float(lat2), float(lng2)))
    dlat = rlat2 - rlat1
    dlng = rlng2 - rlng1
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def encode_polyline(points, precision: int = 5) -> str:
    """Encode ``[(lat, lng), …]`` with the Google polyline algorithm.

    The standard format consumed by both Leaflet plugins and the Google Maps
    JS API, so routes render on either map provider.
    """
    factor = 10 ** precision
    output = []
    prev_lat = prev_lng = 0
    for lat, lng in points:
        int_lat = round(float(lat) * factor)
        int_lng = round(float(lng) * factor)
        output.append(_encode_value(int_lat - prev_lat))
        output.append(_encode_value(int_lng - prev_lng))
        prev_lat, prev_lng = int_lat, int_lng
    return "".join(output)


def _encode_value(value: int) -> str:
    value = ~(value << 1) if value < 0 else (value << 1)
    chunks = []
    while value >= 0x20:
        chunks.append(chr((0x20 | (value & 0x1F)) + 63))
        value >>= 5
    chunks.append(chr(value + 63))
    return "".join(chunks)
