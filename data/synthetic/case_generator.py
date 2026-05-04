"""
Synthetic Case Generator — Guntur District Pilot Data
======================================================
Generates realistic pilot cases based on:
  - Real Guntur demographics (Census 2011)
  - Real climate patterns (historical monthly data)
  - Real ASHA coverage norms (AP NHM)
  - IMCI clinical presentation patterns
  - Realistic RDT delay distributions

These cases serve as:
  1. Training data for CBAD (behavioral anomaly detector)
  2. Demo data for the dashboard
  3. Evidence baseline (what "before COIP" looks like)
  4. Integration testing

All IDs are anonymized. No real personal data.
"""

import random
import math
import json
import csv
import os
from datetime import datetime, timedelta, timezone
from typing import List, Dict

# ── Seed for reproducibility
random.seed(2026)

# ── Real Guntur mandals and villages
GUNTUR_MANDALS = [
    {"name": "Tadikonda",      "lat": 16.435, "lon": 80.520,
     "villages": ["Rentachintala", "Chintala", "Bollapadu", "Korrapadu"],
     "asha_count": 68},
    {"name": "Medikonduru",    "lat": 16.354, "lon": 80.393,
     "villages": ["Medikonduru", "Gollapudi", "Nadendla", "Ippatam"],
     "asha_count": 55},
    {"name": "Pedakakani",     "lat": 16.255, "lon": 80.508,
     "villages": ["Pedakakani", "Undavalli", "Mangalagiri", "Nallapadu"],
     "asha_count": 62},
    {"name": "Phirangipuram",  "lat": 16.205, "lon": 79.985,
     "villages": ["Phirangipuram", "Dachepalli", "Macherla", "Veldurthi"],
     "asha_count": 46},
    {"name": "Prathipadu",     "lat": 16.458, "lon": 80.648,
     "villages": ["Prathipadu", "Repalle", "Bapatla", "Nidubrolu"],
     "asha_count": 39},
]

# ── Clinical symptoms mapped to climate pathways
SYMPTOM_PROFILES = {
    "HEAT_DIRECT": [
        "High fever >39°C + lethargy",
        "Reduced urination + dry mouth (dehydration suspected)",
        "Excessive crying + hot to touch (heatstroke signs)",
        "Vomiting + weakness (heat exhaustion)",
        "Unresponsive / altered consciousness (severe heat stroke)",
    ],
    "VECTOR_BORNE": [
        "Fever 3+ days + rash (dengue suspected)",
        "High fever + joint pain (dengue fever)",
        "Fever + convulsions (malaria/severe dengue)",
        "Intermittent fever (malaria suspected)",
    ],
    "WATER_BORNE": [
        "Watery diarrhea 5+ times/day",
        "Diarrhea + vomiting (gastroenteritis)",
        "Bloody stool + fever",
        "Severe diarrhea + sunken eyes (moderate dehydration)",
    ],
    "RESPIRATORY": [
        "Cough + difficulty breathing",
        "Fast breathing + chest indrawing (ARI/pneumonia signs)",
        "Wheezing + high fever",
    ],
}

# ── Monthly climate data for Guntur (historical averages)
MONTHLY_CLIMATE = {
    1:  {"temp": 30.3, "aqi": 65,  "humidity": 68, "rainfall": 2},
    2:  {"temp": 33.6, "aqi": 70,  "humidity": 62, "rainfall": 1},
    3:  {"temp": 37.0, "aqi": 82,  "humidity": 56, "rainfall": 2},
    4:  {"temp": 39.5, "aqi": 90,  "humidity": 55, "rainfall": 2},
    5:  {"temp": 41.9, "aqi": 95,  "humidity": 53, "rainfall": 3},
    6:  {"temp": 37.5, "aqi": 75,  "humidity": 72, "rainfall": 15},
    7:  {"temp": 34.5, "aqi": 60,  "humidity": 82, "rainfall": 35},
    8:  {"temp": 33.6, "aqi": 58,  "humidity": 85, "rainfall": 38},
    9:  {"temp": 32.7, "aqi": 60,  "humidity": 83, "rainfall": 44},
    10: {"temp": 31.5, "aqi": 68,  "humidity": 75, "rainfall": 30},
    11: {"temp": 30.2, "aqi": 72,  "humidity": 70, "rainfall": 14},
    12: {"temp": 29.7, "aqi": 68,  "humidity": 68, "rainfall": 5},
}

# ── Climate pathway by month (dominant risk)
MONTHLY_PATHWAY = {
    1:"RESPIRATORY", 2:"RESPIRATORY", 3:"HEAT_DIRECT",
    4:"HEAT_DIRECT",  5:"HEAT_DIRECT",  6:"HEAT_DIRECT",
    7:"WATER_BORNE",  8:"WATER_BORNE",  9:"VECTOR_BORNE",
    10:"VECTOR_BORNE", 11:"RESPIRATORY", 12:"RESPIRATORY",
}

# ── Age distribution for U5 children (Guntur Census pattern)
AGE_DISTRIBUTION = [
    (0, 3,   5.0),   # 0–3 months: 5%
    (3, 6,   5.0),   # 3–6 months: 5%
    (6, 12,  10.0),  # 6–12 months: 10%
    (12, 24, 20.0),  # 1–2 years: 20%
    (24, 36, 20.0),  # 2–3 years: 20%
    (36, 48, 20.0),  # 3–4 years: 20%
    (48, 60, 20.0),  # 4–5 years: 20%
]

# Weight-for-age approximation (WHO growth standards median, boys)
def age_to_weight(age_months: int) -> float:
    if age_months <= 1:   return random.uniform(3.2, 4.0)
    elif age_months <= 3: return random.uniform(5.0, 6.5)
    elif age_months <= 6: return random.uniform(6.5, 8.0)
    elif age_months <= 12: return random.uniform(8.0, 10.5)
    elif age_months <= 24: return random.uniform(10.0, 12.5)
    elif age_months <= 36: return random.uniform(12.0, 14.5)
    elif age_months <= 48: return random.uniform(13.5, 16.0)
    else:                  return random.uniform(15.0, 18.5)


def _sample_age() -> int:
    """Sample child age in months from Guntur distribution."""
    r = random.random() * 100
    cumulative = 0.0
    for age_lo, age_hi, pct in AGE_DISTRIBUTION:
        cumulative += pct
        if r <= cumulative:
            return random.randint(age_lo, age_hi - 1)
    return 24  # fallback


def _compute_cif(temp_c: float) -> float:
    """Approximate CHW Cognitive Impairment Factor from temperature."""
    if temp_c <= 30:    return 0.0
    elif temp_c <= 35:  return (temp_c - 30) * 0.015
    elif temp_c <= 38:  return 0.075 + (temp_c - 35) * 0.04
    elif temp_c <= 41:  return 0.195 + (temp_c - 38) * 0.06
    else:               return min(0.65, 0.375 + (temp_c - 41) * 0.05)


def _compute_bus_approx(age_months: int, temp_c: float, aqi: float) -> float:
    """Approximate BUS score for synthetic data generation."""
    # Age factor
    if age_months <= 3:   age_f = 1.0
    elif age_months <= 6: age_f = 0.9
    elif age_months <= 12: age_f = 0.8
    elif age_months <= 24: age_f = 0.7
    else:                  age_f = 0.6

    # Temp factor
    if temp_c >= 43:    temp_f = 1.0
    elif temp_c >= 41:  temp_f = 0.85
    elif temp_c >= 40:  temp_f = 0.75
    elif temp_c >= 38:  temp_f = 0.60
    elif temp_c >= 36:  temp_f = 0.40
    else:               temp_f = 0.20

    # AQI factor
    aqi_f = min(0.15, max(0, (aqi - 50) / 600))

    bus = min(100, (temp_f * 70 + aqi_f * 10) * age_f + random.uniform(-5, 5))
    return round(max(0, bus), 1)


def _compute_t_adj(bus_score: float, baseline: float = 38.0) -> float:
    """Compute T_adj from BUS score."""
    if bus_score >= 85:   factor = 0.25
    elif bus_score >= 70: factor = 0.35
    elif bus_score >= 50: factor = 0.55
    elif bus_score >= 30: factor = 0.75
    else:                  factor = 1.00
    return round(baseline * factor, 1)


def _sample_rdt_times(t_adj: float, scenario: str = "baseline") -> dict:
    """
    Sample realistic RDT times for different scenarios.

    Scenarios:
      baseline   = current situation WITHOUT COIP (65-90 min avg)
      with_coip  = WITH COIP (target 25-35 min)
    """
    # Without COIP: mean ~72 min with high variance
    if scenario == "baseline":
        target_total = random.normalvariate(72, 18)
        target_total = max(15, target_total)
        # Split roughly: RT ~15%, DT ~20%, ET ~65%
        rt = target_total * random.uniform(0.10, 0.20)
        dt = target_total * random.uniform(0.18, 0.25)
        et = target_total - rt - dt
    else:
        # With COIP: aiming for T_adj ± 30%
        target_total = t_adj * random.uniform(0.7, 1.4)
        target_total = max(8, target_total)
        rt = target_total * random.uniform(0.15, 0.25)
        dt = target_total * random.uniform(0.20, 0.30)
        et = target_total - rt - dt

    return {
        "rt": round(max(1, rt), 1),
        "dt": round(max(2, dt), 1),
        "et": round(max(5, et), 1),
        "total": round(max(8, rt+dt+et), 1),
    }


def _classify_delay(total_rdt: float, t_adj: float) -> str:
    if t_adj <= 0: return "UNKNOWN"
    ratio = total_rdt / t_adj
    if ratio <= 1.0:   return "NORMAL"
    elif ratio <= 1.3: return "MODERATE"
    elif ratio <= 1.6: return "DELAYED"
    elif ratio <= 2.2: return "CRITICAL"
    else:               return "EMERGENCY"


def generate_cases(
    n_cases: int = 100,
    start_date: datetime = None,
    scenario: str = "baseline",
    months: list = None,
) -> List[dict]:
    """
    Generate n_cases synthetic child health cases for Guntur district.

    Args:
        n_cases:    Number of cases to generate
        start_date: Starting date for case timestamps
        scenario:   "baseline" (without COIP) or "with_coip"
        months:     List of months to sample from (default: all)

    Returns:
        List of case dicts matching CaseRDT structure
    """
    if start_date is None:
        start_date = datetime(2025, 3, 1, tzinfo=timezone.utc)
    if months is None:
        months = list(range(1, 13))

    cases = []

    for i in range(n_cases):
        # ── Sample month and climate
        month = random.choice(months)
        climate = MONTHLY_CLIMATE[month]
        pathway = MONTHLY_PATHWAY[month]

        # Add daily variance
        temp    = climate["temp"] + random.uniform(-2, 3)
        aqi     = climate["aqi"]  + random.uniform(-15, 20)
        humidity = climate["humidity"] + random.uniform(-5, 10)
        rainfall = climate["rainfall"] + random.uniform(-2, 5)

        # ── Sample child
        age_months = _sample_age()
        weight_kg  = age_to_weight(age_months)
        sex        = random.choice(["M","F"])

        # ── Sample location
        mandal = random.choice(GUNTUR_MANDALS)
        village = random.choice(mandal["villages"])
        chw_id = f"ASHA-GNT-{mandal['name'][:3].upper()}-{random.randint(1, mandal['asha_count']):03d}"

        # ── Compute derived scores
        cif   = round(_compute_cif(temp), 3)
        bus   = _compute_bus_approx(age_months, temp, aqi)
        t_adj = _compute_t_adj(bus)

        # ── Sample RDT times
        rdt   = _sample_rdt_times(t_adj, scenario)

        # ── Sample symptom
        symptom = random.choice(SYMPTOM_PROFILES.get(pathway, SYMPTOM_PROFILES["HEAT_DIRECT"]))

        # ── Generate timestamps
        # Space cases over the date range
        days_offset = int((i / n_cases) * 90)  # spread over 90 days
        hour_offset = random.randint(6, 18)
        t_report = start_date + timedelta(days=days_offset, hours=hour_offset,
                                          minutes=random.randint(0, 59))

        t_ack    = t_report + timedelta(minutes=rdt["rt"])
        t_decide = t_ack    + timedelta(minutes=rdt["dt"])
        t_action = t_decide + timedelta(minutes=rdt["et"])

        # ── Classify
        delay_class = _classify_delay(rdt["total"], t_adj)

        # ── Delay cause
        if cif >= 0.35 and delay_class in ("DELAYED","CRITICAL","EMERGENCY"):
            delay_cause = "CLIMATE_CAUSED"
        elif cif < 0.15 and delay_class in ("DELAYED","CRITICAL"):
            delay_cause = "BEHAVIORAL_OR_SYSTEM"
        elif delay_class == "NORMAL":
            delay_cause = "NO_DELAY"
        else:
            delay_cause = "MIXED"

        # ── Outcome
        if delay_class in ("EMERGENCY",):
            outcome = random.choices(["FACILITY","EMERGENCY_REFERRAL"], [0.6, 0.4])[0]
        elif delay_class in ("CRITICAL","DELAYED"):
            outcome = random.choices(["ORS_HOME","FACILITY"], [0.4, 0.6])[0]
        else:
            outcome = random.choices(["ORS_HOME","FACILITY","RESOLVED"], [0.5, 0.3, 0.2])[0]

        case = {
            "case_id":          f"GNT-{scenario[:3].upper()}-{i+1:04d}",
            "scenario":         scenario,
            "chw_id":           chw_id,
            "mandal":           mandal["name"],
            "village":          village,
            "child_age_months": age_months,
            "child_weight_kg":  round(weight_kg, 1),
            "child_sex":        sex,
            "symptom":          symptom,
            "climate_pathway":  pathway,
            "month":            month,
            "temperature_c":    round(temp, 1),
            "aqi":              round(aqi, 1),
            "humidity_pct":     round(humidity, 1),
            "rainfall_mm":      round(max(0, rainfall), 1),
            "cif_score":        cif,
            "bus_score":        bus,
            "t_adj_total":      t_adj,
            "rt_min":           rdt["rt"],
            "dt_min":           rdt["dt"],
            "et_min":           rdt["et"],
            "total_rdt_min":    rdt["total"],
            "delay_class":      delay_class,
            "delay_cause":      delay_cause,
            "outcome":          outcome,
            "ts_reported":      t_report.isoformat(),
            "ts_acknowledged":  t_ack.isoformat(),
            "ts_decided":       t_decide.isoformat(),
            "ts_action_start":  t_action.isoformat(),
            "is_complete":      True,
        }
        cases.append(case)

    return cases


def save_cases_csv(cases: List[dict], filepath: str):
    """Save cases to CSV for analysis / DHIS2 export."""
    if not cases:
        return
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cases[0].keys())
        writer.writeheader()
        writer.writerows(cases)
    print(f"  Saved {len(cases)} cases to {filepath}")


def save_cases_json(cases: List[dict], filepath: str):
    """Save cases to JSON."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w") as f:
        json.dump(cases, f, indent=2, default=str)
    print(f"  Saved {len(cases)} cases to {filepath}")


def compute_district_summary(cases: List[dict]) -> dict:
    """Compute summary statistics from a set of cases."""
    n = len(cases)
    if n == 0:
        return {}

    delays = [c["total_rdt_min"] for c in cases]
    t_adjs = [c["t_adj_total"] for c in cases]
    buses  = [c["bus_score"] for c in cases]
    temps  = [c["temperature_c"] for c in cases]

    delay_classes = {}
    for c in cases:
        dc = c["delay_class"]
        delay_classes[dc] = delay_classes.get(dc, 0) + 1

    causes = {}
    for c in cases:
        cause = c["delay_cause"]
        causes[cause] = causes.get(cause, 0) + 1

    critical_cases = sum(1 for c in cases if c["delay_class"] in ("CRITICAL","EMERGENCY"))
    climate_cases  = sum(1 for c in cases if c["delay_cause"] == "CLIMATE_CAUSED")

    return {
        "total_cases":          n,
        "avg_rdt_min":          round(sum(delays)/n, 1),
        "avg_t_adj_min":        round(sum(t_adjs)/n, 1),
        "avg_bus_score":        round(sum(buses)/n, 1),
        "avg_temperature_c":    round(sum(temps)/n, 1),
        "median_rdt_min":       round(sorted(delays)[n//2], 1),
        "pct_on_time":          round(delay_classes.get("NORMAL",0)/n*100, 1),
        "pct_critical":         round(critical_cases/n*100, 1),
        "pct_climate_caused":   round(climate_cases/n*100, 1),
        "delay_distribution":   {k: round(v/n*100,1) for k,v in delay_classes.items()},
        "delay_cause_distribution": {k: round(v/n*100,1) for k,v in causes.items()},
    }


if __name__ == "__main__":
    import os

    print("=" * 60)
    print("Synthetic Case Generator — Guntur District")
    print("=" * 60)

    # Generate baseline cases (without COIP)
    print("\nGenerating 200 baseline cases (without COIP)...")
    baseline = generate_cases(200, scenario="baseline",
                              months=[3,4,5,6,7,8,9,10])
    save_cases_csv(baseline, "data/guntur/cases_baseline.csv")
    save_cases_json(baseline, "data/guntur/cases_baseline.json")

    b_summary = compute_district_summary(baseline)
    print(f"\nBaseline Summary:")
    print(f"  Avg RDT:          {b_summary['avg_rdt_min']} min")
    print(f"  On-time cases:    {b_summary['pct_on_time']}%")
    print(f"  Critical delays:  {b_summary['pct_critical']}%")
    print(f"  Climate-caused:   {b_summary['pct_climate_caused']}%")

    # Generate with_coip cases (with COIP active)
    print("\nGenerating 200 cases (with COIP active)...")
    with_coip = generate_cases(200, scenario="with_coip",
                               months=[3,4,5,6,7,8,9,10])
    save_cases_csv(with_coip, "data/guntur/cases_with_coip.csv")
    save_cases_json(with_coip, "data/guntur/cases_with_coip.json")

    c_summary = compute_district_summary(with_coip)
    print(f"\nWith COIP Summary:")
    print(f"  Avg RDT:          {c_summary['avg_rdt_min']} min")
    print(f"  On-time cases:    {c_summary['pct_on_time']}%")
    print(f"  Critical delays:  {c_summary['pct_critical']}%")

    print(f"\nImprovement:")
    print(f"  RDT reduction:    {b_summary['avg_rdt_min']} → {c_summary['avg_rdt_min']} min "
          f"(-{round(b_summary['avg_rdt_min']-c_summary['avg_rdt_min'],1)} min, "
          f"{round((b_summary['avg_rdt_min']-c_summary['avg_rdt_min'])/b_summary['avg_rdt_min']*100)}%)")
    print(f"  Critical reduced: {b_summary['pct_critical']}% → {c_summary['pct_critical']}%")
