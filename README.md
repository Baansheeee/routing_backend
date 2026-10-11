# Weather-Aware Truck Routing — Backend

Django + DRF API. Business logic lives in `routing/services/`.

## Setup

```powershell
cd backend
.\venv\Scripts\Activate.ps1
# Ensure backend\.env exists (not only venv\.env)
python manage.py migrate
python manage.py runserver
```

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
