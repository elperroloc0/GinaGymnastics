import os

import requests


class TraccarAPIError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def _base_url() -> str:
    return os.environ.get("TRACCAR_API_URL", "http://traccar:8082")


def _auth() -> tuple[str, str]:
    return (os.environ["TRACCAR_API_EMAIL"], os.environ["TRACCAR_API_PASSWORD"])


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


def get_device_id(imei: str) -> int:
    # Van stores the tracker's IMEI, which Traccar calls uniqueId - but the
    # permissions API below wants Traccar's own numeric device id.
    response = _request("GET", "/api/devices", params={"uniqueId": imei})
    devices = response.json()
    if not devices:
        raise TraccarAPIError(f"No Traccar device with uniqueId {imei}")
    return devices[0]["id"]


def list_device_geofence_ids(device_id: int) -> list[int]:
    # Without ?deviceId this endpoint lists every geofence the API user owns,
    # not the ones linked to the device - only linked ones generate events.
    response = _request("GET", "/api/geofences", params={"deviceId": device_id})
    return [g["id"] for g in response.json()]


def link_geofence(device_id: int, geofence_id: int) -> None:
    # Traccar only computes geofence enter/exit for geofences linked to the
    # device (a permission), creating the geofence alone is not enough.
    try:
        _request("POST", "/api/permissions", json={"deviceId": device_id, "geofenceId": geofence_id})
    except TraccarAPIError as e:
        # 400 = link already exists, which is the state we want.
        if e.status_code != 400:
            raise


def unlink_geofence(device_id: int, geofence_id: int) -> None:
    try:
        _request("DELETE", "/api/permissions", json={"deviceId": device_id, "geofenceId": geofence_id})
    except TraccarAPIError as e:
        if e.status_code != 404:
            raise


def delete_geofence(traccar_id: int) -> None:
    # Callers treat failures here as best-effort (log and move on) rather than
    # letting a Traccar-side failure block deleting our own row - see
    # GeoFenceViewSet.perform_destroy. 404 means it's already gone, not an error.
    try:
        _request("DELETE", f"/api/geofences/{traccar_id}")
    except TraccarAPIError as e:
        if e.status_code != 404:
            raise
