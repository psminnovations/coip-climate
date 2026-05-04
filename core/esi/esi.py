"""
ESI — Environmental Signal Ingestion
=====================================
Layer 0 of COIP-Climate pipeline.

Pulls REAL climate data for Guntur District from free, open APIs:
  - Open-Meteo (temperature, humidity, UV, rainfall, wind)
  - OpenAQ (AQI, PM2.5)

No API keys required. All open-source data.

Guntur coordinates: 16.3067°N, 80.4365°E
"""

import requests
import json
import math
from datetime import datetime, timezone
from typing import Optional

# ── Guntur district coordinates
GUNTUR_LAT  = 16.3067
GUNTUR_LON  = 80.4365
GUNTUR_TZ   = "Asia/Kolkata"


class ClimateContextObject:
    """
    Standardized output object from ESI.
    Attached to every case event in the COIP pipeline.
    Every field has a meaning and is used downstream.
    """

    def __init__(self, data: dict):
        # ── Raw signals
        self.temperature_c:   float = data.get("temperature_c", 0.0)
        self.humidity_pct:    float = data.get("humidity_pct", 50.0)
        self.aqi:             float = data.get("aqi", 50.0)
        self.pm25_ugm3:       float = data.get("pm25_ugm3", 15.0)
        self.uv_index:        float = data.get("uv_index", 5.0)
        self.rainfall_mm:     float = data.get("rainfall_mm", 0.0)
        self.wind_speed_ms:   float = data.get("wind_speed_ms", 2.0)
        self.source:           str  = data.get("source", "unknown")
        self.timestamp:        str  = data.get("timestamp",
                                    datetime.now(timezone.utc).isoformat())

        # ── Computed fields (filled by _compute())
        self.climate_stress_index:      float = 0.0   # 0–1
        self.heatwave_active:            bool = False
        self.hazard_type:                str  = "NONE"
        self.climate_risk_level:         str  = "LOW"
        self.vulnerability_tags:        list  = []

        self._compute()

    def _compute(self):
        """Derive composite risk scores from raw signals."""

        # Climate Stress Index (0–1)
        t = self.temperature_c

        # Temperature component (0–0.6)
        if t >= 44:    t_score = 0.60
        elif t >= 42:  t_score = 0.50
        elif t >= 40:  t_score = 0.40
        elif t >= 38:  t_score = 0.30
        elif t >= 35:  t_score = 0.18
        elif t >= 32:  t_score = 0.08
        else:          t_score = 0.0

        # AQI component (0–0.2)
        aqi = self.aqi
        if aqi >= 200:   a_score = 0.20
        elif aqi >= 150: a_score = 0.14
        elif aqi >= 100: a_score = 0.08
        elif aqi >= 50:  a_score = 0.03
        else:            a_score = 0.0

        # Compound amplifier (both heat + AQI together are worse)
        if t_score > 0.2 and a_score > 0.08:
            self.climate_stress_index = min(1.0, (t_score + a_score) * 1.3)
        else:
            self.climate_stress_index = min(1.0, t_score + a_score)

        # Heatwave flag (IMD Andhra Pradesh definition: ≥40°C)
        self.heatwave_active = (t >= 40.0)

        # Hazard type classification
        if t >= 40 and aqi >= 100:
            self.hazard_type = "COMPOUND_HEAT_AQI"
        elif t >= 40:
            self.hazard_type = "HEATWAVE"
        elif aqi >= 150:
            self.hazard_type = "POOR_AIR_QUALITY"
        elif self.rainfall_mm > 50:
            self.hazard_type = "HEAVY_RAINFALL"
        else:
            self.hazard_type = "NONE"

        # Risk level
        csi = self.climate_stress_index
        if csi >= 0.65:    self.climate_risk_level = "EXTREME"
        elif csi >= 0.45:  self.climate_risk_level = "HIGH"
        elif csi >= 0.25:  self.climate_risk_level = "MEDIUM"
        elif csi >= 0.10:  self.climate_risk_level = "LOW"
        else:              self.climate_risk_level = "MINIMAL"

        # Vulnerability tags
        tags = []
        if t >= 38:             tags.append("U5_HEAT_RISK")
        if t >= 40:             tags.append("INFANT_CRITICAL")
        if aqi >= 100:          tags.append("RESPIRATORY_RISK")
        if aqi >= 150:          tags.append("PREGNANT_WOMEN_RISK")
        if self.rainfall_mm>20: tags.append("FLOOD_WATCH")
        if t >= 38 or aqi>=100: tags.append("CHW_IMPAIRED")
        self.vulnerability_tags = tags

    def to_dict(self) -> dict:
        return {
            "temperature_c":          round(self.temperature_c, 1),
            "humidity_pct":           round(self.humidity_pct, 1),
            "aqi":                    round(self.aqi, 1),
            "pm25_ugm3":              round(self.pm25_ugm3, 1),
            "uv_index":               round(self.uv_index, 1),
            "rainfall_mm":            round(self.rainfall_mm, 1),
            "wind_speed_ms":          round(self.wind_speed_ms, 1),
            "climate_stress_index":   round(self.climate_stress_index, 3),
            "heatwave_active":        self.heatwave_active,
            "hazard_type":            self.hazard_type,
            "climate_risk_level":     self.climate_risk_level,
            "vulnerability_tags":     self.vulnerability_tags,
            "source":                 self.source,
            "timestamp":              self.timestamp,
        }

    def __repr__(self):
        return (f"ClimateContext("
                f"temp={self.temperature_c}°C, "
                f"aqi={self.aqi}, "
                f"risk={self.climate_risk_level}, "
                f"hazard={self.hazard_type})")


def fetch_openmeteo(lat: float = GUNTUR_LAT,
                    lon: float = GUNTUR_LON,
                    timeout: int = 10) -> Optional[ClimateContextObject]:
    """
    Fetch REAL current weather from Open-Meteo API.
    Free, no API key, open-source data.
    https://open-meteo.com/en/docs

    Returns ClimateContextObject or None on failure.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,"
        "precipitation,wind_speed_10m,uv_index"
        f"&timezone={GUNTUR_TZ}"
    )

    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        d = resp.json()
        c = d.get("current", {})

        return ClimateContextObject({
            "temperature_c":  c.get("temperature_2m", 30.0),
            "humidity_pct":   c.get("relative_humidity_2m", 60.0),
            "rainfall_mm":    c.get("precipitation", 0.0),
            "wind_speed_ms":  c.get("wind_speed_10m", 3.0) / 3.6,  # km/h → m/s
            "uv_index":       c.get("uv_index", 5.0),
            "aqi":            50.0,   # filled by fetch_openaq if available
            "pm25_ugm3":      15.0,
            "source":         "open-meteo-live",
            "timestamp":      datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:
        print(f"  [ESI] Open-Meteo fetch failed: {e}")
        return None


def fetch_openaq_guntur(timeout: int = 10) -> dict:
    """
    Fetch AQI data for Guntur from OpenAQ API.
    Free, no API key needed.
    https://docs.openaq.org/

    Returns dict with aqi and pm25 or defaults.
    """
    url = (
        "https://api.openaq.org/v3/locations"
        "?coordinates=16.3067,80.4365"
        "&radius=50000"
        "&limit=5"
        "&parameters=pm25"
    )

    try:
        resp = requests.get(url, timeout=timeout,
                            headers={"Accept": "application/json"})
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            # Get latest measurement from nearest station
            for loc in results:
                sensors = loc.get("sensors", [])
                for s in sensors:
                    if s.get("parameter", {}).get("name") == "pm25":
                        pm25 = s.get("latest", {}).get("value", 15.0)
                        if pm25 and pm25 > 0:
                            # Convert PM2.5 to approximate AQI (India NAAQS)
                            aqi = pm25_to_aqi_india(pm25)
                            return {"aqi": aqi, "pm25_ugm3": pm25,
                                    "source": "openaq-live"}
    except Exception as e:
        print(f"  [ESI] OpenAQ fetch failed: {e}")

    return {"aqi": 55.0, "pm25_ugm3": 18.0, "source": "default"}


def pm25_to_aqi_india(pm25: float) -> float:
    """
    Convert PM2.5 (μg/m³) to AQI using India NAAQS breakpoints.
    Source: CPCB India Air Quality Index calculation.
    """
    breakpoints = [
        (0,   30,    0,   50),
        (30,  60,   51,  100),
        (60,  90,  101,  200),
        (90, 120,  201,  300),
        (120, 250, 301,  400),
        (250, 500, 401,  500),
    ]
    for (c_lo, c_hi, i_lo, i_hi) in breakpoints:
        if c_lo <= pm25 <= c_hi:
            return round(i_lo + (pm25 - c_lo) * (i_hi - i_lo) / (c_hi - c_lo), 1)
    return 500.0 if pm25 > 500 else 0.0


def get_climate_context(lat: float = GUNTUR_LAT,
                         lon: float = GUNTUR_LON,
                         fallback: bool = True) -> ClimateContextObject:
    """
    Main entry point.
    Fetches real climate context for Guntur.
    Falls back to season-appropriate synthetic data if APIs unavailable.
    """
    print("  [ESI] Fetching real climate data for Guntur District...")

    ctx = fetch_openmeteo(lat, lon)

    if ctx:
        # Enrich with AQI if available
        aq  = fetch_openaq_guntur()
        ctx.aqi       = aq["aqi"]
        ctx.pm25_ugm3 = aq["pm25_ugm3"]
        # Recompute with actual AQI
        ctx._compute()
        print(f"  [ESI] ✓ Live data: {ctx}")
        return ctx

    if fallback:
        print("  [ESI] ⚠ API unavailable — using season-appropriate synthetic data")
        return _synthetic_guntur_context()

    raise RuntimeError("ESI: Could not fetch climate data and fallback disabled")


def _synthetic_guntur_context() -> ClimateContextObject:
    """
    Season-appropriate synthetic data for Guntur when APIs unavailable.
    Based on historical averages from Weather Atlas / IMD data.
    """
    month = datetime.now().month
    monthly_temps = {
        1: 30.3, 2: 33.6, 3: 37.0, 4: 39.5,
        5: 41.9, 6: 37.5, 7: 34.5, 8: 33.6,
        9: 32.7, 10: 31.5, 11: 30.2, 12: 29.7
    }
    monthly_rain = {
        1: 0, 2: 0, 3: 0, 4: 2, 5: 3,
        6: 8, 7: 20, 8: 18, 9: 22, 10: 12, 11: 5, 12: 1
    }
    temp = monthly_temps.get(month, 35.0)
    # Add small daily variance
    import random
    temp += random.uniform(-1.5, 1.5)

    return ClimateContextObject({
        "temperature_c": round(temp, 1),
        "humidity_pct":  72.0 if month in [7,8,9] else 57.0,
        "aqi":           85.0 if month in [3,4,5] else 55.0,
        "pm25_ugm3":     28.0 if month in [3,4,5] else 18.0,
        "uv_index":      11.0 if month in [3,4,5,6] else 7.0,
        "rainfall_mm":   monthly_rain.get(month, 0),
        "wind_speed_ms": 2.9,
        "source":        "synthetic-guntur-historical",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    })


def get_48h_forecast(lat: float = GUNTUR_LAT,
                     lon: float = GUNTUR_LON,
                     timeout: int = 10) -> list:
    """
    Fetch 48-hour temperature + rainfall forecast for Guntur.
    Used by Anticipatory Action Engine.
    Returns list of hourly forecasts.
    """
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=temperature_2m,precipitation,uv_index"
        "&forecast_days=3"
        f"&timezone={GUNTUR_TZ}"
    )
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        d = resp.json()
        hourly = d.get("hourly", {})
        times  = hourly.get("time", [])
        temps  = hourly.get("temperature_2m", [])
        rain   = hourly.get("precipitation", [])
        uv     = hourly.get("uv_index", [])

        forecasts = []
        for i, t in enumerate(times[:48]):
            forecasts.append({
                "time":           t,
                "temperature_c":  temps[i]  if i < len(temps) else 35.0,
                "rainfall_mm":    rain[i]   if i < len(rain)  else 0.0,
                "uv_index":       uv[i]     if i < len(uv)    else 7.0,
                "heatwave_risk":  (temps[i] if i < len(temps) else 35.0) >= 40.0,
            })
        return forecasts
    except Exception as e:
        print(f"  [ESI] Forecast fetch failed: {e}")
        return []


if __name__ == "__main__":
    print("=" * 60)
    print("ESI — Environmental Signal Ingestion")
    print("Guntur District, Andhra Pradesh")
    print("=" * 60)

    ctx = get_climate_context()
    print("\nClimate Context Object:")
    for k, v in ctx.to_dict().items():
        print(f"  {k:30s}: {v}")

    print("\n48-Hour Forecast (first 6 hours):")
    forecast = get_48h_forecast()
    for f in forecast[:6]:
        hw = "🔥 HEATWAVE" if f["heatwave_risk"] else ""
        print(f"  {f['time']}  {f['temperature_c']}°C  {f['rainfall_mm']}mm  {hw}")


def export_geojson_hazard(ctx, mandals: list = None) -> dict:
    """
    Export ESI climate context as GeoJSON for hazard mapping.
    Addresses UNICEF requirement: 'hazard mapping for local governments'.
    Output is a valid GeoJSON FeatureCollection any GIS tool can open.
    
    Args:
        ctx: ClimateContextObject
        mandals: list of mandal dicts with lat/lon (from config.py)
    """
    from data.guntur.config import GUNTUR
    if mandals is None:
        mandals = GUNTUR["pilot_mandals"]

    features = []
    for m in mandals:
        # Each mandal gets a point feature with climate risk properties
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [m["lon"], m["lat"]]
            },
            "properties": {
                "name":               m["name"],
                "code":               m.get("code", ""),
                "temperature_c":      ctx.temperature_c,
                "aqi":                ctx.aqi,
                "climate_risk":       ctx.climate_risk_level,
                "hazard_type":        ctx.hazard_type,
                "csi":                round(ctx.climate_stress_index, 3),
                "heatwave_active":    ctx.heatwave_active,
                "children_u5":        m.get("children_u5_approx", 0),
                "asha_workers":       m.get("asha_workers", 0),
                "vulnerability_tags": ctx.vulnerability_tags,
                "timestamp":          ctx.timestamp,
                "source":             ctx.source,
                # Styling hint for GIS tools
                "marker_color": (
                    "#FF2D55" if ctx.climate_risk_level in ("EXTREME","HIGH")
                    else "#FFB020" if ctx.climate_risk_level == "MEDIUM"
                    else "#00E87A"
                ),
            }
        }
        features.append(feature)

    return {
        "type": "FeatureCollection",
        "name": "COIP-Climate Hazard Map — Guntur District",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "district_alert": ctx.climate_risk_level,
        "features": features,
    }

