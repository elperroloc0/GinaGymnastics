# Setup from scratch

Two repositories, cloned side by side:
- `GinaGymnastics` (this one) — backend + Traccar + Caddy, brought up together via `compose.yaml`.
- `gina-ride-tracker-web` — frontend (React), a separate process, not part of `compose.yaml`.

For a clean local run, the real hardware (Teltonika FMM00A) isn't required for the first pass — the whole stack except the actual GPS signal can be verified without a tracker (Traccar simply won't receive any positions).

## 1. Requirements

- Docker + Docker Compose
- Node.js 20+ (frontend only, the backend doesn't use Node)
- git

## 2. Clone

```bash
git clone <url-backend> GinaGymnastics
git clone <url-frontend> gina-ride-tracker-web
```

## 3. Backend: environment variables

```bash
cd GinaGymnastics
cp .env.example .env
```

Fill in `.env` for a local run:

- `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` — any values, this is a local DB in a container.
- `DOMAIN=http://localhost` — the explicit `http://` scheme tells Caddy not to attempt a real TLS certificate and just serve plain HTTP on `:80`.
- `DJANGO_SECRET_KEY` — any random string, e.g.: `python3 -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `DEBUG=True` — otherwise `settings.py` forces HTTPS redirects (`SECURE_SSL_REDIRECT`), which break a local plain-HTTP Caddy.
- `ALLOWED_HOSTS=localhost,127.0.0.1` — in DEBUG mode these two hosts are already added by default, but it's worth setting them explicitly, since the same list is reused by `AllowedHostsOriginValidator` to check the Origin header on the WebSocket upgrade.
- `TRACCAR_WEBHOOK_SECRET` — any random string; it's wired into Traccar automatically (see step 5.3).
- `TRACCAR_API_EMAIL` / `TRACCAR_API_PASSWORD` — filled in after step 5, once the API user is created in Traccar.
- `TWILIO_*`, `EMAIL_HOST_*` — can be left blank for a first run. The backend starts fine without them; only actual SMS/email delivery breaks (the Celery task retries and eventually fails) — the "tracker → webhook → live map" flow doesn't depend on it.

## 4. Device: Teltonika FMM00A

The tracker plugs into the van's OBD-II port (under the dash, plug-and-play — there's no power wiring or mounting decision to make, there's one connector).

1. Insert the IoT SIM into the tracker.
2. Activate the SIM in the Hologram dashboard (a Hologram SIM won't pass data until activated there).
3. Configure the tracker over SMS: text the tracker's own SIM number (the Hologram number assigned to this SIM) with:

   ```
   setparam 2001:hologram;2002:none;2003:none;2004:<VPS_IP>;2005:5027;2006:0
   ```

   Param IDs: `2001` APN, `2002`/`2003` APN username/password (Hologram needs neither), `2004` server domain/IP — replace `<VPS_IP>` with the deployed VPS's address, `2005` server port (`5027`, the port `compose.yaml` already exposes for Traccar: `5027:5027` + `5027:5027/udp`), `2006` protocol (`0` = TCP). The device applies the settings and normally replies confirming.

   Data protocol on the wire is Teltonika Codec 8 — the default, nothing extra to enable.

Locally, Traccar listens on `localhost:5027`, but a real tracker on the cellular network can't reach `localhost` — an end-to-end check with live hardware needs either an already-deployed VPS with a public IP/domain, or a tunnel back to your machine: `ngrok tcp 5027` (matches the `2006:0` TCP setting above; ngrok's free tier doesn't do UDP tunnels). Put the ngrok-assigned host/port into `2004`/`2005` instead of the VPS address.345

## 5. Traccar

```bash
docker compose up -d postgres redis traccar
```

The Traccar container publishes its web UI on `127.0.0.1:8082`. Locally that's just `http://localhost:8082` in a browser; on the actual VPS it's only reachable via SSH tunnel (`ssh -L 8082:localhost:8082 ...`) — the UI has no TLS and is only password-protected, so it must never be exposed publicly (see README).

1. Open `http://localhost:8082`. The first visit creates the admin account automatically (Traccar shows a registration form on first load if the database is empty) — set a real password.
2. Create a separate user for the backend integration (Settings → Users → New user) — its email/password go into `TRACCAR_API_EMAIL`/`TRACCAR_API_PASSWORD` in `.env`. Keeping it separate from the admin account means its permissions can be scoped down later without touching the human's login.
3. `TRACCAR_WEBHOOK_SECRET` from `.env` doesn't need to be touched in `traccar/traccar.xml` — that file doesn't contain this key at all. The secret reaches the webhook header (`X-Webhook-Secret`) via `EVENT_FORWARD_HEADER`/`FORWARD_HEADER` in `compose.yaml` (`CONFIG_USE_ENVIRONMENT_VARIABLES: "true"` makes Traccar read its config from the container's environment) — the value is already substituted automatically on `docker compose up`.
4. Register the tracker: Devices → Add Device → Identifier = the IMEI printed on the FMM00A's case (this is the `uniqueId` that `fleet/traccar_client.py` looks up when linking geofences). Name it something like the van's plate number.

Django does **not** create the device in Traccar itself — it only links/unlinks geofences to an already-existing `deviceId` (`fleet/traccar_client.link_geofence`). Registering the device is a manual, one-time step in the Traccar UI.

## 6. Backend

```bash
docker compose up -d
```

Migrations and `collectstatic` run automatically when the `django` container starts (`backend/entrypoint.sh`).

Create the first operator (there's no one to invite it, so the first account always goes through `createsuperuser`, not the API):

```bash
docker compose exec django python manage.py createsuperuser
```

A superuser passes every role check the same way an operator does (`tracking/consumers.py`: `user.role == OPERATOR or user.is_superuser`), so setting `role=OPERATOR` via `/admin` separately isn't required — but it's worth doing if you want a predictable operator account for the UI rather than a service superuser.

**Important:** `Van`, `GeoFence`, and `Route` need to be created through the API (`/api/vans/`, `/api/geofences/`, `/api/routes/`), not `/admin`. `fleet/admin.py` is a bare `admin.site.register()` with no overrides — it's specifically `GeoFenceViewSet`/`RouteViewSet` (DRF, `fleet/views.py`) whose `perform_create`/`perform_update`/`perform_destroy` sync the geofence with Traccar (create it there and link it to the device). Creating a geofence through `/admin` leaves it in Django only, with no matching geofence in Traccar — no enter/exit events will ever fire for it.

While `DEBUG=True`, the browsable DRF UI is available at `/api/...` — you can open `http://localhost:8000/api/geofences/` in a browser, log in via `api-auth/`, and create records through the form, no Postman/curl needed.

Order: `Van` (`name` + `tracker_imei`, the same IMEI registered in Traccar in step 5.4) → two `GeoFence`s (school and gym, `location_type=SCHOOL`/`GYM`) → `Route`, linking van + origin + destination.

## 7. Frontend

```bash
cd ../gina-ride-tracker-web
npm install
cp .env.example .env.local
```

In `.env.local`:
- `VITE_MAPBOX_TOKEN` — a public token (`pk....`) from `account.mapbox.com/access-tokens`. Without it the map falls back to a static placeholder instead of rendering.
- `VITE_API_URL` — leave it blank for a local run: `vite.config.ts` already proxies `/api` and `/ws` to `http://127.0.0.1:8000`, so the frontend and backend behave as one origin and CORS never comes into play.

```bash
npm run dev
```

This opens on `http://localhost:5173` (Vite's default port) — `CORS_ALLOWED_ORIGINS` in `.env.example` already includes `http://localhost:5173` by default for `DEBUG=True`, so even a direct (non-proxied) request from the frontend is accepted by the backend.

## 8. End-to-end check

1. `docker compose ps` — every service `healthy`/`running`.
2. The tracker (or a manual POST to `/webhooks/position/`, if hardware isn't in hand yet) sends a position → it shows up in the Traccar UI (Positions).
3. Traccar detects a geofence enter/exit → posts a webhook to `django:8000/webhooks/...` → an `ArrivalEvent` appears in Django (check `/admin`).
4. Open the frontend as an operator — a live van marker should appear on the map (WebSocket channel `van_position_{van_id}`).
5. Open the frontend as a parent of a child on that route, during an active ride (`is_ride_active`) — the same marker should be visible, but scoped to their own van only, not anyone else's.
