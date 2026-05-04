"""
CVBM — Child Vulnerability Biological Model
=============================================
The architectural heart of COIP-Climate.

The child is NOT the output variable.
The child's biology IS the engine that drives every urgency calculation.

Science basis:
  - Surface-area-to-mass ratio: PMC6770410, PMC12386404
  - Pediatric thermoregulation: PubMed 18347699, 21178371
  - Dehydration thresholds: NCBI NBK560540, PMC5829087
  - ORS clinical evidence: WHO IMCI, Medscape Pediatric Dehydration
"""

import math
from dataclasses import dataclass
from typing import Optional


# ── Age-specific SA:mass ratio lookup (cm²/kg)
# Declines from birth (~648) to adult (~250)
# Source: Mosteller formula + PMC12386404
SA_MASS_RATIO_BY_AGE = {
    0:  648,   # Newborn (0 months)
    1:  610,
    3:  560,
    6:  468,   # 6 months (validated PMC12386404)
    12: 420,
    18: 380,
    24: 350,
    36: 330,
    48: 315,
    60: 310,   # 5 years
    72: 290,
    84: 275,
    120: 260,  # 10 years
}

# Clinical dehydration thresholds (% body weight lost)
MILD_DEHYDRATION_PCT    = 3.0   # Clinical threshold: concern
MODERATE_DEHYDRATION_PCT = 6.0  # Moderate: clinical management
SEVERE_DEHYDRATION_PCT  = 10.0  # Severe: near-shock, IV needed

# Temperature above which dry heat loss reverses for children
COOLING_FAILURE_TEMP_C  = 37.0  # °C ambient — children absorb heat above this
# Source: Multiple studies on pediatric thermoregulation

# ORS treatment rate (WHO IMCI standard)
ORS_VOLUME_ML_PER_KG     = 75.0   # mL/kg for mild-moderate dehydration
ORS_ADMIN_RATE_ML_PER_MIN = 5.0   # 5mL every minute administered  ≈ 300/hr


@dataclass
class BUSResult:
    """
    Biological Urgency Score result.
    The primary output driving T_adj in the RDT engine.
    """
    child_age_months:           int
    child_weight_kg:           float
    temperature_c:             float
    aqi:                       float
    humidity_pct:              float
    time_exposed_min:          float

    bus_score:                 float   # 0–100
    urgency_level:              str    # LOW / MODERATE / HIGH / CRITICAL / EMERGENCY

    sa_mass_ratio:             float   # cm²/kg
    cooling_capacity_pct:      float   # % of normal cooling intact
    heat_absorption_factor:    float

    fluid_reserve_mild_ml:     float   # mL to reach mild dehydration
    fluid_reserve_severe_ml:   float   # mL to reach severe dehydration
    fluid_loss_rate_ml_per_min: float

    minutes_to_mild_dehydration:   float  # from NOW
    minutes_to_severe_dehydration: float  # from NOW
    remaining_safe_window_min:     float  # before mild dehydration if exposed continues

    ors_time_to_rehydrate_min:     float  # mins to rehydrate if ORS given NOW

    rdt_t_adj_factor:          float   # multiplier for T_adj in RDT engine
    recommended_action:         str
    clinical_urgency_note:      str


def _get_sa_mass_ratio(age_months: int) -> float:
    """Interpolate SA:mass ratio for any age from lookup table."""
    ages = sorted(SA_MASS_RATIO_BY_AGE.keys())
    if age_months <= ages[0]:
        return SA_MASS_RATIO_BY_AGE[ages[0]]
    if age_months >= ages[-1]:
        return SA_MASS_RATIO_BY_AGE[ages[-1]]
    for i in range(len(ages) - 1):
        a_lo, a_hi = ages[i], ages[i+1]
        if a_lo <= age_months <= a_hi:
            r_lo = SA_MASS_RATIO_BY_AGE[a_lo]
            r_hi = SA_MASS_RATIO_BY_AGE[a_hi]
            frac = (age_months - a_lo) / (a_hi - a_lo)
            return round(r_lo + frac * (r_hi - r_lo), 1)
    return 300.0  # fallback


def compute_bus(
    child_age_months: int,
    child_weight_kg: float,
    temperature_c: float,
    aqi: float = 55.0,
    humidity_pct: float = 60.0,
    time_exposed_min: float = 30.0,
    activity_level: float = 1.0,   # 1.0 = normal toddler activity
) -> BUSResult:
    """
    Compute the Biological Urgency Score (BUS) for a child.

    This is the core child-biology calculation that drives T_adj.
    All parameters grounded in pediatric thermoregulation literature.

    Args:
        child_age_months:  Child's age in months
        child_weight_kg:   Child's weight in kg
        temperature_c:     Current ambient temperature
        aqi:               Air Quality Index
        humidity_pct:      Relative humidity %
        time_exposed_min:  Estimated time already exposed to conditions
        activity_level:    1.0 = normal activity, 0.5 = resting, 1.5 = active play

    Returns:
        BUSResult with full biological analysis and T_adj factor
    """

    # ── 1. Surface area to mass ratio
    sa_mass = _get_sa_mass_ratio(child_age_months)

    # ── 2. Heat absorption factor
    # Above COOLING_FAILURE_TEMP_C (37°C), children ABSORB heat
    # Rate proportional to SA:mass ratio relative to adult (250 cm²/kg)
    if temperature_c > COOLING_FAILURE_TEMP_C:
        heat_excess = temperature_c - COOLING_FAILURE_TEMP_C
        heat_absorption_factor = heat_excess * (sa_mass / 250.0)
    else:
        heat_absorption_factor = 0.0

    # ── 3. Effective cooling capacity (evaporative + dry)
    # Sweating fails progressively above 30°C
    # Dry heat loss fails above 37°C
    if temperature_c <= 30:
        cooling_capacity = 1.0
    elif temperature_c <= 37:
        # Partial: sweating still helps but declines
        cooling_capacity = max(0.3, 1.0 - (temperature_c - 30) / 20)
    else:
        # Above 37°C: evaporative cooling unreliable for children
        # Only small residual from sweating (lower rate than adults)
        cooling_capacity = max(0.0, 0.3 - (temperature_c - 37) * 0.04)

    # Humidity adjustment: high humidity reduces evaporative cooling
    humidity_factor = max(0.3, 1.0 - (humidity_pct - 40) / 100)
    effective_cooling = cooling_capacity * humidity_factor

    # ── 4. Fluid loss rate (mL/min)
    # Approximated from activity, temperature, and SA:mass
    if temperature_c > 30:
        base_loss_ml_hr = (temperature_c - 20) * child_weight_kg * 0.8 * activity_level
        # SA:mass amplifier: higher ratio = proportionally more surface loss
        samass_amplifier = (sa_mass / 300.0)
        total_loss_ml_hr = base_loss_ml_hr * samass_amplifier
        fluid_loss_rate_ml_min = max(0.0, total_loss_ml_hr / 60.0)
    else:
        fluid_loss_rate_ml_min = 0.5  # baseline

    # ── 5. Dehydration thresholds (absolute mL)
    body_fluid_total_ml = child_weight_kg * 1000 * 0.65  # ~65% body water
    mild_threshold_ml   = child_weight_kg * 1000 * (MILD_DEHYDRATION_PCT / 100)
    severe_threshold_ml = child_weight_kg * 1000 * (SEVERE_DEHYDRATION_PCT / 100)

    # ── 6. Time to dehydration thresholds
    already_lost_ml = fluid_loss_rate_ml_min * time_exposed_min

    remaining_to_mild   = max(0.0, mild_threshold_ml   - already_lost_ml)
    remaining_to_severe = max(0.0, severe_threshold_ml - already_lost_ml)

    if fluid_loss_rate_ml_min > 0:
        t_to_mild   = remaining_to_mild   / fluid_loss_rate_ml_min
        t_to_severe = remaining_to_severe / fluid_loss_rate_ml_min
    else:
        t_to_mild   = 999.0
        t_to_severe = 999.0

    # Time remaining as safe window (before mild dehydration from now)
    remaining_safe_min = max(0.0, t_to_mild)

    # ── 7. ORS rehydration time if given NOW
    deficit_ml = min(already_lost_ml, severe_threshold_ml)
    ors_volume_needed = max(mild_threshold_ml, deficit_ml * 1.5)
    ors_time_min = ors_volume_needed / ORS_ADMIN_RATE_ML_PER_MIN

    # ── 8. AQI respiratory burden (additional metabolic stress)
    if aqi >= 150:   aqi_burden = 0.15
    elif aqi >= 100: aqi_burden = 0.08
    elif aqi >= 50:  aqi_burden = 0.03
    else:            aqi_burden = 0.0

    # ── 9. Compute BUS (0–100)
    # Components:
    # A) Heat absorption intensity         (0–30 points)
    # B) Cooling capacity deficit           (0–25 points)
    # C) Time pressure (window remaining)  (0–30 points)
    # D) AQI burden                        (0–10 points)
    # E) Already exposed                   (0–5 points)

    comp_A = min(30, heat_absorption_factor * 5)

    comp_B = min(25, (1 - effective_cooling) * 25)

    # Time pressure: more points as window shrinks
    if remaining_safe_min <= 0:
        comp_C = 30
    elif remaining_safe_min <= 10:
        comp_C = 28
    elif remaining_safe_min <= 20:
        comp_C = 22
    elif remaining_safe_min <= 40:
        comp_C = 14
    elif remaining_safe_min <= 60:
        comp_C = 8
    else:
        comp_C = 2

    comp_D = min(10, aqi_burden * 67)

    # Already exposed fraction of severe threshold
    exposure_frac = min(1.0, already_lost_ml / severe_threshold_ml)
    comp_E = min(5, exposure_frac * 5)

    bus = round(min(100, comp_A + comp_B + comp_C + comp_D + comp_E), 1)

    # ── 10. Urgency level
    if bus >= 85:    urgency = "EMERGENCY"
    elif bus >= 70:  urgency = "CRITICAL"
    elif bus >= 50:  urgency = "HIGH"
    elif bus >= 30:  urgency = "MODERATE"
    else:            urgency = "LOW"

    # ── 11. T_adj factor (RDT engine uses this to compress response window)
    # Higher BUS = tighter response deadline
    if bus >= 85:    t_adj_factor = 0.25   # 75% tighter — near-emergency
    elif bus >= 70:  t_adj_factor = 0.35   # 65% tighter
    elif bus >= 50:  t_adj_factor = 0.55   # 45% tighter
    elif bus >= 30:  t_adj_factor = 0.75   # 25% tighter
    else:            t_adj_factor = 1.00   # no change

    # ── 12. Recommended action
    if urgency == "EMERGENCY":
        action = "IMMEDIATE_EMERGENCY: Call 108 NOW. Start ORS immediately. Rush to hospital."
    elif urgency == "CRITICAL":
        action = "CRITICAL_VISIT: CHW must reach child within 10 minutes. Start ORS en route."
    elif urgency == "HIGH":
        action = "URGENT_VISIT: CHW visit within T_adj. Give ORS on arrival. Monitor."
    elif urgency == "MODERATE":
        action = "WATCH: Monitor closely. Give ORS. CHW visit within T_adj."
    else:
        action = "ROUTINE: Standard care. Ensure hydration. Normal follow-up."

    # ── 13. Clinical note
    note = (
        f"Child {child_age_months}m/{child_weight_kg}kg at {temperature_c}°C. "
        f"SA:mass ratio={sa_mass}cm²/kg. "
        f"Cooling={round(effective_cooling*100)}%. "
        f"Window={round(remaining_safe_min)}min before mild dehydration. "
        f"ORS now saves {round(ors_time_min)}min of recovery."
    )

    return BUSResult(
        child_age_months=child_age_months,
        child_weight_kg=child_weight_kg,
        temperature_c=temperature_c,
        aqi=aqi,
        humidity_pct=humidity_pct,
        time_exposed_min=time_exposed_min,
        bus_score=bus,
        urgency_level=urgency,
        sa_mass_ratio=sa_mass,
        cooling_capacity_pct=round(effective_cooling * 100, 1),
        heat_absorption_factor=round(heat_absorption_factor, 2),
        fluid_reserve_mild_ml=round(mild_threshold_ml, 1),
        fluid_reserve_severe_ml=round(severe_threshold_ml, 1),
        fluid_loss_rate_ml_per_min=round(fluid_loss_rate_ml_min, 2),
        minutes_to_mild_dehydration=round(t_to_mild, 1),
        minutes_to_severe_dehydration=round(t_to_severe, 1),
        remaining_safe_window_min=round(remaining_safe_min, 1),
        ors_time_to_rehydrate_min=round(ors_time_min, 1),
        rdt_t_adj_factor=t_adj_factor,
        recommended_action=action,
        clinical_urgency_note=note,
    )


if __name__ == "__main__":
    print("=" * 60)
    print("CVBM — Child Vulnerability Biological Model")
    print("Demo: Guntur District summer scenario (May, 42°C)")
    print("=" * 60)

    cases = [
        (3,  5.5,  "Newborn 3mo/5.5kg"),
        (12, 9.0,  "Infant 12mo/9kg"),
        (18, 10.2, "Toddler 18mo/10.2kg"),
        (36, 13.5, "Child 3yr/13.5kg"),
        (60, 18.0, "Child 5yr/18kg"),
    ]

    temp = 42.0  # Guntur May typical peak

    for age_m, wt, label in cases:
        result = compute_bus(age_m, wt, temp, aqi=85, humidity_pct=55, time_exposed_min=45)
        print(f"\n{label}:")
        print(f"  BUS Score:      {result.bus_score}/100 [{result.urgency_level}]")
        print(f"  SA:mass ratio:  {result.sa_mass_ratio} cm²/kg")
        print(f"  Cooling:        {result.cooling_capacity_pct}%")
        print(f"  Window:         {result.remaining_safe_window_min} min remaining")
        print(f"  T_adj factor:   ×{result.rdt_t_adj_factor}")
        print(f"  Action:         {result.recommended_action[:60]}...")
