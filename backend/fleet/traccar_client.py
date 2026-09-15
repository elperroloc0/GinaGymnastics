import os

import requests


class TraccarAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    return os.environ.get("TRACCAR_API_URL", "http://traccar:8082")


def _auth() -> tuple[str, str]:
    return (os.environ["TRACCAR_API_USERNAME"], os.environ["TRACCAR_API_PASSWORD"])


def _wkt_circle(latitude: float, longitude: float, radius: float) -> str:
    # Traccar's own non-standard WKT convention: latitude first, then
    # longitude, then radius in meters (see GeofenceCircle.toWkt() upstream).
    return f"CIRCLE ({latitude} {longitude}, {radius})"


def _request(method: str, path: str, **kwargs) -> requests.Response:
    try:
        response = requests.request(method, f"{_base_url()}{path}", auth=_auth(), timeout=5, **kwargs)
    except requests.RequestException as e:
        raise TraccarAPIError(f"{method} {path} failed: {e}") from e

    if not response.ok:
        raise TraccarAPIError(
            f"{method} {path} returned {response.status_code}: {response.text}",
            status_code=response.status_code,
        )

    return response


def create_geofence(name: str, latitude: float, longitude: float, radius: float) -> int:
    response = _request(
        "POST",
        "/api/geofences",
        json={"name": name, "area": _wkt_circle(latitude, longitude, radius)},
    )
    return response.json()["id"]


def update_geofence(traccar_id: int, name: str, latitude: float, longitude: float, radius: float) -> None:
    _request(
        "PUT",
        f"/api/geofences/{traccar_id}",
        json={"id": traccar_id, "name": name, "area": _wkt_circle(latitude, longitude, radius)},
    )


def delete_geofence(traccar_id: int) -> None:
    # Callers treat failures here as best-effort (log and move on) rather than
    # letting a Traccar-side failure block deleting our own row - see
    # GeoFenceViewSet.perform_destroy. 404 means it's already gone, not an error.
    try:
        _request("DELETE", f"/api/geofences/{traccar_id}")
    except TraccarAPIError as e:
        if e.status_code != 404:
            raise
