"""
Guntur District Configuration
Andhra Pradesh, India
All data from Census 2011, NFHS-5 (2021), AP Health Department
"""

GUNTUR = {
    "district": "Guntur",
    "state": "Andhra Pradesh",
    "country": "India",

    # Real GPS coordinates — district center
    "latitude":  16.3067,
    "longitude": 80.4365,

    # Census 2011 demographics
    "total_population":    4_887_813,
    "children_0_6":          495_729,   # 10.14% of total
    "children_under_5":      412_000,   # estimated from 0-6 data
    "rural_population":    3_235_075,
    "urban_population":    1_652_738,
    "households":          1_296_609,
    "sex_ratio":               1003,    # females per 1000 males
    "literacy_rate":           60.57,   # %

    # Administrative units (Census 2011)
    "mandals":  57,
    "villages": 712,
    "towns":    19,

    # ASHA/CHW workforce (AP NHM norms)
    "asha_norm_per_population": 1000,   # 1 ASHA per 1000 people
    "estimated_ashas":          4888,   # total_population / 1000
    "asha_urban_norm":          2500,   # 1 per 2500 in urban
    "rural_ashas_approx":       3235,
    "urban_ashas_approx":        661,

    # Climate data (historical averages + extremes)
    "climate": {
        "classification": "Tropical wet-dry savanna (Aw)",
        "yearly_avg_temp_c": 28.4,
        "yearly_avg_max_c":  30.75,
        "yearly_rainfall_mm": 966,

        # Monthly max temps (°C) — averages
        "monthly_max_avg": {
            "Jan": 30.3, "Feb": 33.6, "Mar": 37.0,
            "Apr": 39.5, "May": 41.9, "Jun": 37.5,
            "Jul": 34.5, "Aug": 33.6, "Sep": 32.7,
            "Oct": 31.5, "Nov": 30.2, "Dec": 29.7
        },

        # Monthly rainfall (mm) — averages
        "monthly_rainfall_mm": {
            "Jan": 8,   "Feb": 5,   "Mar": 7,
            "Apr": 10,  "May": 15,  "Jun": 60,
            "Jul": 140, "Aug": 150, "Sep": 175,
            "Oct": 120, "Nov": 55,  "Dec": 20
        },

        # Recorded extremes (from historical data)
        "max_recorded_temp_c": 44.0,   # April peak
        "critical_heat_months": ["Mar", "Apr", "May", "Jun"],
        "dengue_risk_months":   ["Jul", "Aug", "Sep", "Oct"],
        "flood_risk_months":    ["Jun", "Jul", "Aug", "Sep"],

        # Heatwave threshold for AP (IMD definition)
        "heatwave_threshold_c": 40.0,
        "severe_heatwave_c":    43.0,
    },

    # Child health indicators (NFHS-5 AP 2021, Guntur approximated)
    "child_health": {
        "ors_coverage_pct":          42.0,   # % diarrhea cases receiving ORS
        "exclusive_breastfeeding_pct": 63.5,
        "full_immunization_pct":     65.8,
        "stunting_pct_u5":           31.2,
        "wasting_pct_u5":            19.4,
        "under_5_mortality_per_1000": 34,
        "infant_mortality_per_1000":  28,
        "institutional_delivery_pct": 91.0,
    },

    # Real mandals for pilot (top 5 rural mandals for CHW density)
    "pilot_mandals": [
        {
            "name": "Tadikonda",
            "code": "GNT001",
            "lat": 16.435, "lon": 80.520,
            "population": 68420,
            "villages": 14,
            "asha_workers": 68,
            "children_u5_approx": 5786,
            "phc_name": "Tadikonda PHC",
            "phc_distance_km_avg": 3.2,
        },
        {
            "name": "Medikonduru",
            "code": "GNT002",
            "lat": 16.354, "lon": 80.393,
            "population": 55210,
            "villages": 11,
            "asha_workers": 55,
            "children_u5_approx": 4670,
            "phc_name": "Medikonduru PHC",
            "phc_distance_km_avg": 4.1,
        },
        {
            "name": "Pedakakani",
            "code": "GNT003",
            "lat": 16.255, "lon": 80.508,
            "population": 62340,
            "villages": 13,
            "asha_workers": 62,
            "children_u5_approx": 5278,
            "phc_name": "Pedakakani PHC",
            "phc_distance_km_avg": 3.8,
        },
        {
            "name": "Phirangipuram",
            "code": "GNT004",
            "lat": 16.205, "lon": 79.985,
            "population": 45780,
            "villages": 9,
            "asha_workers": 46,
            "children_u5_approx": 3874,
            "phc_name": "Phirangipuram PHC",
            "phc_distance_km_avg": 5.2,
        },
        {
            "name": "Prathipadu",
            "code": "GNT005",
            "lat": 16.458, "lon": 80.648,
            "population": 38920,
            "villages": 8,
            "asha_workers": 39,
            "children_u5_approx": 3294,
            "phc_name": "Prathipadu PHC",
            "phc_distance_km_avg": 4.7,
        },
    ],

    # Response time baselines (from RTBIP/AP Health Dept methodology)
    "rdt_baselines": {
        "rt_baseline_min":    8.0,   # Report → Acknowledged
        "dt_baseline_min":   12.0,   # Acknowledged → Decision
        "et_baseline_min":   18.0,   # Decision → Action
        "total_rdt_baseline": 38.0,  # Total baseline in minutes
        "current_avg_actual": 72.0,  # Observed average (65-90 range midpoint)
        "target_with_coip":   30.0,  # Target with COIP-Climate
    }
}
