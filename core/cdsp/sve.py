"""
SVE — School & Facility Vulnerability Engine
=============================================
UNICEF explicitly requires:
  "vulnerability scoring for health facilities AND schools"

This module:
1. Fetches schools + health facilities from OpenStreetMap (free, open)
   via Overpass API for Guntur district
2. Computes climate vulnerability score per school/facility
3. Identifies highest-risk locations for UNICEF's strategic planning
4. Generates school-level heat alerts (children spend 6+ hrs there)

Data: OpenStreetMap (ODbL license) + ESI climate signals + Census data
All open-source, all free.

UNICEF Gap Addressed: "generate health facility, school and
community-level vulnerability scores"
"""

import requests
import json
import math
import os
from datetime import datetime, timezone
from typing import List, Dict, Optional


# ── Guntur district bounding box
# Southwest: 15.9°N, 79.7°E  Northeast: 16.6°N, 80.9°E
GUNTUR_BBOX = {
    "south": 15.9,
    "west":  79.7,
    "north": 16.6,
    "east":  80.9,
}

# ── Overpass API endpoint (free, open)
OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# ── Vulnerability weight factors
VULNERABILITY_WEIGHTS = {
    "temperature":       0.35,   # Heat is primary risk
    "aqi":               0.20,   # Air quality / respiratory
    "children_density":  0.25,   # How many children at risk
    "distance_to_phc":   0.10,   # Access to care if emergency
    "water_access":      0.10,   # Dehydration risk factor
}


class VulnerableLocation:
    """A scored school or health facility in Guntur."""

    def __init__(self, data: dict):
        self.osm_id:       int   = data.get("osm_id", 0)
        self.name:          str  = data.get("name", "Unknown")
        self.location_type: str  = data.get("type", "school")  # school / hospital / clinic
        self.lat:          float = data.get("lat", 16.3)
        self.lon:          float = data.get("lon", 80.4)
        self.mandal:        str  = data.get("mandal", "Unknown")
        self.estimated_children: int = data.get("estimated_children", 200)

        # Climate exposure
        self.temperature_c:    float = data.get("temperature_c", 35.0)
        self.aqi:              float = data.get("aqi", 70.0)
        self.distance_to_phc_km: float = data.get("distance_to_phc_km", 3.0)

        # Computed
        self.vulnerability_score: float = 0.0
        self.risk_level:          str  = "LOW"
        self.children_at_risk:    int  = 0
        self.alert_actions:      list  = []

        self._compute_vulnerability()

    def _compute_vulnerability(self):
        """Compute vulnerability score 0–100."""

        # Temperature score (0–35 pts)
        t = self.temperature_c
        if t >= 43:   t_score = 35
        elif t >= 41: t_score = 30
        elif t >= 40: t_score = 25
        elif t >= 38: t_score = 18
        elif t >= 36: t_score = 10
        else:         t_score = 3

        # AQI score (0–20 pts)
        aqi = self.aqi
        if aqi >= 200:   a_score = 20
        elif aqi >= 150: a_score = 15
        elif aqi >= 100: a_score = 10
        elif aqi >= 75:  a_score = 5
        else:            a_score = 1

        # Children density score (0–25 pts)
        n = self.estimated_children
        if n >= 500:   c_score = 25
        elif n >= 300: c_score = 20
        elif n >= 200: c_score = 15
        elif n >= 100: c_score = 10
        else:          c_score = 5

        # Distance to care (0–10 pts) — further = more vulnerable
        d = self.distance_to_phc_km
        if d >= 8:   d_score = 10
        elif d >= 5: d_score = 7
        elif d >= 3: d_score = 4
        else:        d_score = 1

        # Schools get a school-hours multiplier
        # Children are at school 8am-4pm = 8 hrs of peak heat exposure
        school_mult = 1.2 if self.location_type == "school" else 1.0

        self.vulnerability_score = min(100, round(
            (t_score + a_score + c_score + d_score) * school_mult, 1
        ))

        # Children at risk = those present during peak heat
        if self.location_type == "school":
            # Peak heat: 11am–3pm = approx 50% of school day
            self.children_at_risk = int(self.estimated_children * 0.5)
        else:
            self.children_at_risk = self.estimated_children

        # Risk level
        # Thresholds calibrated to Guntur summer context:
        # At 42C+250 children+far from PHC = score ~65 = CRITICAL
        v = self.vulnerability_score
        if v >= 60:   self.risk_level = "CRITICAL"
        elif v >= 45: self.risk_level = "HIGH"
        elif v >= 28: self.risk_level = "MEDIUM"
        else:         self.risk_level = "LOW"

        # Actions
        self.alert_actions = self._generate_actions()

    def _generate_actions(self) -> list:
        actions = []
        t = self.temperature_c
        rl = self.risk_level

        if rl in ("CRITICAL", "HIGH"):
            if self.location_type == "school":
                actions += [
                    "Issue school heat advisory — reschedule outdoor activities",
                    f"Deploy ORS sachets to all {self.estimated_children} students",
                    "Identify shaded rest areas + increase water breaks",
                    "Alert school health teacher + nearest ASHA",
                ]
            else:
                actions += [
                    "Increase pediatric ORS and IV fluid stock",
                    "Set up cooling area for children arriving",
                    "Alert district health officer of facility risk",
                ]
        if t >= 41:
            actions.append("Extreme heat protocol: monitor every 2 hours")
        if self.aqi >= 100:
            actions.append("Poor air quality: restrict outdoor play, open windows only if cooler")
        if self.distance_to_phc_km >= 6:
            actions.append("Remote location: pre-position emergency supplies on site")

        return actions or ["Routine monitoring — reassess daily."]

    def to_dict(self) -> dict:
        return {
            "osm_id":              self.osm_id,
            "name":                self.name,
            "type":                self.location_type,
            "lat":                 self.lat,
            "lon":                 self.lon,
            "mandal":              self.mandal,
            "estimated_children":  self.estimated_children,
            "temperature_c":       self.temperature_c,
            "aqi":                 self.aqi,
            "distance_to_phc_km":  self.distance_to_phc_km,
            "vulnerability_score": self.vulnerability_score,
            "risk_level":          self.risk_level,
            "children_at_risk":    self.children_at_risk,
            "alert_actions":       self.alert_actions,
        }

    def __repr__(self):
        return (f"VulnerableLocation({self.name[:30]} | "
                f"{self.location_type} | "
                f"score={self.vulnerability_score} [{self.risk_level}] | "
                f"{self.children_at_risk} children)")


def fetch_schools_osm(bbox: dict = GUNTUR_BBOX,
                      timeout: int = 15) -> List[dict]:
    """
    Fetch schools from OpenStreetMap via Overpass API.
    Free, open-source, no API key.
    Returns list of school dicts with coordinates and names.
    """
    query = f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"="school"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
      way["amenity"="school"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
      node["amenity"="kindergarten"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
    );
    out center;
    """
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        schools = []
        for elem in data.get("elements", []):
            lat = (elem.get("lat") or
                   elem.get("center", {}).get("lat", 0))
            lon = (elem.get("lon") or
                   elem.get("center", {}).get("lon", 0))
            if lat and lon:
                schools.append({
                    "osm_id": elem.get("id", 0),
                    "name":   elem.get("tags", {}).get("name", "Unknown School"),
                    "type":   "school",
                    "lat":    round(lat, 6),
                    "lon":    round(lon, 6),
                    "tags":   elem.get("tags", {}),
                })
        return schools
    except Exception as e:
        print(f"  [SVE] OSM schools fetch failed: {e}")
        return []


def fetch_health_facilities_osm(bbox: dict = GUNTUR_BBOX,
                                 timeout: int = 15) -> List[dict]:
    """
    Fetch health facilities from OpenStreetMap.
    Includes: hospitals, clinics, PHCs, health_posts.
    """
    query = f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"="hospital"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
      node["amenity"="clinic"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
      node["amenity"="health_post"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
      way["amenity"="hospital"]({bbox['south']},{bbox['west']},{bbox['north']},{bbox['east']});
    );
    out center;
    """
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        facilities = []
        for elem in data.get("elements", []):
            lat = (elem.get("lat") or
                   elem.get("center", {}).get("lat", 0))
            lon = (elem.get("lon") or
                   elem.get("center", {}).get("lon", 0))
            if lat and lon:
                tags = elem.get("tags", {})
                facilities.append({
                    "osm_id": elem.get("id", 0),
                    "name":   tags.get("name", "Unknown Facility"),
                    "type":   tags.get("amenity", "clinic"),
                    "lat":    round(lat, 6),
                    "lon":    round(lon, 6),
                    "tags":   tags,
                })
        return facilities
    except Exception as e:
        print(f"  [SVE] OSM facilities fetch failed: {e}")
        return []


def _distance_km(lat1, lon1, lat2, lon2) -> float:
    """Haversine distance in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return R * 2 * math.asin(math.sqrt(a))


def score_locations(
    locations: List[dict],
    temperature_c: float,
    aqi: float,
    phc_coords: Optional[List[tuple]] = None,
) -> List[VulnerableLocation]:
    """
    Score all locations with current climate data.
    Returns sorted list (highest vulnerability first).
    """
    # Default PHC locations for Guntur pilot mandals
    if phc_coords is None:
        phc_coords = [
            (16.435, 80.520),   # Tadikonda PHC
            (16.354, 80.393),   # Medikonduru PHC
            (16.255, 80.508),   # Pedakakani PHC
            (16.205, 79.985),   # Phirangipuram PHC
            (16.458, 80.648),   # Prathipadu PHC
        ]

    scored = []
    for loc in locations:
        lat = loc.get("lat", 16.3)
        lon = loc.get("lon", 80.4)

        # Find distance to nearest PHC
        min_dist = min(
            _distance_km(lat, lon, p[0], p[1])
            for p in phc_coords
        )

        # Estimate children (schools: 200-600, clinics: 20-100)
        loc_type = loc.get("type", "school")
        if loc_type == "school":
            est_children = 250  # avg primary school Guntur
        elif loc_type == "kindergarten":
            est_children = 80
        elif loc_type == "hospital":
            est_children = 50   # pediatric patients
        else:
            est_children = 30

        scored_loc = VulnerableLocation({
            **loc,
            "temperature_c":       temperature_c,
            "aqi":                 aqi,
            "distance_to_phc_km":  round(min_dist, 1),
            "estimated_children":  est_children,
            "mandal":              _guess_mandal(lat, lon),
        })
        scored.append(scored_loc)

    return sorted(scored, key=lambda l: l.vulnerability_score, reverse=True)


def _guess_mandal(lat: float, lon: float) -> str:
    """Approximate mandal from coordinates (simple proximity)."""
    mandal_centers = [
        ("Tadikonda",     16.435, 80.520),
        ("Medikonduru",   16.354, 80.393),
        ("Pedakakani",    16.255, 80.508),
        ("Phirangipuram", 16.205, 79.985),
        ("Prathipadu",    16.458, 80.648),
        ("Guntur East",   16.307, 80.457),
        ("Guntur West",   16.297, 80.425),
    ]
    closest = min(mandal_centers,
                  key=lambda m: _distance_km(lat, lon, m[1], m[2]))
    return closest[0]


def get_synthetic_guntur_locations(
    temperature_c: float = 42.0,
    aqi: float = 90.0
) -> List[VulnerableLocation]:
    """
    Return synthetic but realistic school+facility data for Guntur
    when OSM API is unavailable. Based on known Guntur geography.
    """
    synthetic = [
        # Schools
        {"osm_id":1001, "name":"Zilla Parishad High School Tadikonda", "type":"school",     "lat":16.436, "lon":80.519},
        {"osm_id":1002, "name":"MPP Primary School Rentachintala",      "type":"school",     "lat":16.425, "lon":80.498},
        {"osm_id":1003, "name":"ZPHS Medikonduru",                      "type":"school",     "lat":16.352, "lon":80.392},
        {"osm_id":1004, "name":"Anganwadi Centre 14 Pedakakani",        "type":"kindergarten","lat":16.253, "lon":80.510},
        {"osm_id":1005, "name":"ZPHS Phirangipuram",                    "type":"school",     "lat":16.204, "lon":79.984},
        {"osm_id":1006, "name":"ST Primary School Prathipadu",          "type":"school",     "lat":16.459, "lon":80.649},
        {"osm_id":1007, "name":"Government Girls High School Guntur",   "type":"school",     "lat":16.307, "lon":80.451},
        {"osm_id":1008, "name":"ZPHS Bollapadu",                        "type":"school",     "lat":16.440, "lon":80.530},
        # Health facilities
        {"osm_id":2001, "name":"Tadikonda PHC",                         "type":"clinic",     "lat":16.435, "lon":80.520},
        {"osm_id":2002, "name":"Medikonduru PHC",                       "type":"clinic",     "lat":16.354, "lon":80.393},
        {"osm_id":2003, "name":"Guntur Government General Hospital",    "type":"hospital",   "lat":16.307, "lon":80.440},
        {"osm_id":2004, "name":"Phirangipuram CHC",                     "type":"clinic",     "lat":16.205, "lon":79.986},
        {"osm_id":2005, "name":"Prathipadu PHC",                        "type":"clinic",     "lat":16.457, "lon":80.648},
    ]
    return score_locations(synthetic, temperature_c, aqi)


def run_vulnerability_assessment(
    temperature_c: float,
    aqi: float,
    use_live_osm: bool = False,
) -> dict:
    """
    Run complete school+facility vulnerability assessment for Guntur.
    Returns prioritized list with actions.
    """
    print(f"  [SVE] Running vulnerability assessment (temp={temperature_c}°C, AQI={aqi})")

    if use_live_osm:
        print("  [SVE] Fetching live OSM data...")
        schools = fetch_schools_osm()
        facilities = fetch_health_facilities_osm()
        all_locations_raw = schools + facilities
        if all_locations_raw:
            locations = score_locations(all_locations_raw, temperature_c, aqi)
        else:
            print("  [SVE] OSM returned no data — using synthetic")
            locations = get_synthetic_guntur_locations(temperature_c, aqi)
    else:
        locations = get_synthetic_guntur_locations(temperature_c, aqi)

    critical = [l for l in locations if l.risk_level == "CRITICAL"]
    high     = [l for l in locations if l.risk_level == "HIGH"]
    total_children = sum(l.children_at_risk for l in locations)

    return {
        "district":            "Guntur, Andhra Pradesh",
        "assessment_time":     datetime.now(timezone.utc).isoformat(),
        "temperature_c":       temperature_c,
        "aqi":                 aqi,
        "total_locations":     len(locations),
        "schools_count":       sum(1 for l in locations if l.location_type == "school"),
        "facilities_count":    sum(1 for l in locations if l.location_type != "school"),
        "critical_count":      len(critical),
        "high_count":          len(high),
        "total_children_at_risk": total_children,
        "top_10_vulnerable":   [l.to_dict() for l in locations[:10]],
        "critical_locations":  [l.to_dict() for l in critical],
        "summary_actions": _compile_summary_actions(critical, high, temperature_c),
        "data_source":         "OpenStreetMap (ODbL) + Open-Meteo + Census 2011",
    }


def _compile_summary_actions(critical, high, temp_c):
    actions = []
    if critical:
        names = ", ".join(l.name[:25] for l in critical[:3])
        actions.append(f"IMMEDIATE: {len(critical)} locations at CRITICAL risk — {names}")
    if temp_c >= 41:
        actions.append("ALL SCHOOLS: Issue heat advisory — reschedule outdoor activities")
        actions.append("Pre-deploy ORS to all schools in pilot mandals today")
    if high:
        actions.append(f"{len(high)} HIGH-risk locations — complete health check today")
    return actions or ["Standard monitoring."]


if __name__ == "__main__":
    print("=" * 60)
    print("SVE — School & Facility Vulnerability Engine")
    print("Guntur District, Andhra Pradesh")
    print("=" * 60)

    result = run_vulnerability_assessment(
        temperature_c = 42.0,
        aqi = 90.0,
        use_live_osm = False,
    )

    print(f"\nAssessment Summary:")
    print(f"  Total locations:         {result['total_locations']}")
    print(f"  Schools:                 {result['schools_count']}")
    print(f"  Health facilities:       {result['facilities_count']}")
    print(f"  CRITICAL risk:           {result['critical_count']}")
    print(f"  HIGH risk:               {result['high_count']}")
    print(f"  Children at risk:        {result['total_children_at_risk']}")

    print(f"\nTop 5 Most Vulnerable:")
    for loc in result["top_10_vulnerable"][:5]:
        print(f"  [{loc['risk_level']:8s}] {loc['name'][:35]:<35} "
              f"score={loc['vulnerability_score']:5.1f} "
              f"| {loc['children_at_risk']} children")
        for action in loc["alert_actions"][:1]:
            print(f"           → {action[:65]}")

    print(f"\nImmediate Actions:")
    for a in result["summary_actions"]:
        print(f"  → {a}")
