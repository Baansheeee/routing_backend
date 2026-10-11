# Weather-Aware Truck Routing — Backend

Django + DRF API. Business logic lives in `routing/services/`.

## Setup

```powershell
cd backend
.\venv\Scripts\Activate.ps1
copy .env.example .env
# Edit .env — set DJANGO_SECRET_KEY and MAPBOX_TOKEN
python manage.py migrate
python manage.py runserver
```

## Deploy on Render

1. Push this repo to GitHub (**do not commit `.env`**).
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Web Service** → connect the repo.
3. Configure:

| Field | Value |
|--------|--------|
| Runtime | Python 3 |
| Build Command | `bash build.sh` |
| Start Command | `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --timeout 120 --workers 2` |

4. Add environment variables (same names as `.env.example`):

| Key | Production value |
|-----|------------------|
| `DJANGO_SECRET_KEY` | Long random string |
| `DJANGO_DEBUG` | `False` |
| `DJANGO_ALLOWED_HOSTS` | `your-service.onrender.com` |
| `CORS_ALLOWED_ORIGINS` | `https://your-frontend.vercel.app,http://localhost:5173` |
| `CSRF_TRUSTED_ORIGINS` | Same URLs **with** `https://` / `http://` |
| `MAPBOX_TOKEN` | Your Mapbox public token |
| `OPEN_METEO_BASE_URL` | `https://api.open-meteo.com/v1/forecast` |
| `CHECKPOINT_INTERVAL_MILES` | `25` |
| `WEATHER_CACHE_SECONDS` | `1800` |
| `PYTHON_VERSION` | `3.12.8` (optional; `runtime.txt` also sets this) |

5. Deploy, then open `https://your-service.onrender.com/api/health` → `{"status":"ok"}`.
6. Point the frontend `VITE_API_URL` to `https://your-service.onrender.com/api`.

SQLite is fine for this assignment; the Render disk is ephemeral (DB resets on redeploy).

## Risk boundary conventions

Levels: `LOW(1) < MODERATE(2) < HIGH(3) < SEVERE(4) < NO_TRAVEL(5)`

| Factor | LOW | MODERATE | HIGH | SEVERE | NO_TRAVEL |
|--------|-----|----------|------|--------|-----------|
| Wind (mph) | `<25` | `<35` | `<45` | `<55` | else |
| Rain (in/hr) | `<0.10` | `<=0.25` | `<=0.50` | `<=1.00` | else |
| Snow (in/hr) | `<0.5` | `<=1.0` | `<=2.0` | `<=3.0` | else |

Checkpoint base risk = worst of wind/rain/snow. Load rules may only increase risk:

- wind `>=55` → NO_TRAVEL (any load)
- wind `45–54` and load `>30,000` lb → NO_TRAVEL
- wind `35–44` and load `>40,000` lb → at least SEVERE

## Tests

```powershell
python manage.py test routing
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/geocode/suggest?q=` | Autocomplete |
| POST | `/api/analyze` | Routes + weather risk |
| POST | `/api/heatmap` | 0–48h corridor heatmap |

### Example: Dallas → Denver

```powershell
curl -X POST http://127.0.0.1:8000/api/analyze -H "Content-Type: application/json" -d "{\"origin\":\"Dallas, TX\",\"destination\":\"Denver, CO\",\"departure_time\":\"2026-06-15T14:00:00Z\",\"load_weight_lb\":35000,\"checkpoint_interval_miles\":25}"
```

Expected shape:

```json
{
  "origin": {"name": "...", "lat": 0, "lon": 0},
  "destination": {"name": "...", "lat": 0, "lon": 0},
  "routes": [
    {
      "id": "route-1",
      "label": "Route 1",
      "geometry": [[lon, lat]],
      "distance_miles": 0,
      "duration_seconds": 0,
      "summary": {
        "total_miles": 0,
        "severe_miles": 0,
        "high_miles": 0,
        "avg_risk": 0,
        "has_no_travel": false,
        "miles_by_level": {},
        "worst_checkpoint": null
      },
      "checkpoints": [
        {
          "mile": 0,
          "lat": 0,
          "lon": 0,
          "eta": "2026-06-15T14:00:00Z",
          "weather": {"wind_mph": 0, "rain_in_hr": 0, "snow_in_hr": 0},
          "risk": {"level": 1, "level_name": "LOW", "drivers": []}
        }
      ]
    }
  ],
  "recommendation": {
    "recommended_route_id": "route-1",
    "reason": "...",
    "warnings": []
  }
}
```
