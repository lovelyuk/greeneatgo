from __future__ import annotations

from math import atan2, cos, radians, sin, sqrt

EARTH_RADIUS_M = 6_371_000

def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return EARTH_RADIUS_M * c

def gps_far_flag(user_lat: float | None, user_lng: float | None, merchant_lat: float | None, merchant_lng: float | None, threshold_m: int = 500) -> bool:
    if None in (user_lat, user_lng, merchant_lat, merchant_lng):
        return False
    return distance_m(user_lat, user_lng, merchant_lat, merchant_lng) > threshold_m
