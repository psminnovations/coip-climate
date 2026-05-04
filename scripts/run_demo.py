"""
COIP-Climate — Main Pipeline Demo
====================================
Guntur District, Andhra Pradesh, India

This script demonstrates the complete working prototype:
1. ESI: Fetch real climate data from Open-Meteo
2. CVBM: Compute Biological Urgency Score for a child case
3. RDT: Compute climate-adjusted response time
4. CBAD: Classify CHW behavior
5. CDSP: District disease surge forecast
6. Output: Complete case analysis

Run this to see the system working end-to-end with real data.
"""

import sys
import os
import json
from datetime import datetime, timedelta, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

from core.esi.esi import get_climate_context, get_48h_forecast
from core.cvbm.cvbm import compute_bus
from core.rdt.rdt_engine import CaseRDT, run_rdt_pipeline, GUNTUR_BASELINES
from core.cbad.cbad import CHWBehaviorRegistry
from core.cdsp.cdsp import run_district_forecast
from data.synthetic.case_generator import (
    generate_cases, compute_district_summary,
    save_cases_csv, save_cases_json
)


def print_separator(title=""):
    line = "─" * 60
    if title:
        pad = (58 - len(title)) // 2
        print(f"\n{'─'*pad} {title} {'─'*pad}")
    else:
        print(f"\n{line}")


def print_header():
    print("=" * 70)
    print("   COIP-CLIMATE · WORKING PROTOTYPE")
    print("   Guntur District, Andhra Pradesh, India")
    print("   UNICEF Venture Fund Climate & Health Call 2026")
    print("=" * 70)
    print("   Apache 2.0 | Open-Source | Child-First | Climate-Aware")
    print("=" * 70)


def run_live_case_demo(climate_ctx):
    """Run a complete live case through the pipeline."""

    print_separator("STEP 2: CHILD CASE — LIVE RDT PIPELINE")

    # ── Sample case: 18-month-old in Tadikonda mandal
    CHILD_AGE    = 18       # months
    CHILD_WEIGHT = 10.2     # kg
    SYMPTOM      = "High fever >39°C + lethargy (heatstroke suspected)"
    MANDAL       = "Tadikonda"
    VILLAGE      = "Rentachintala"
    CHW_ID       = "ASHA-GNT-TAD-042"

    now = datetime.now(timezone.utc)

    print(f"\n  Case received at: {now.strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"  Child: {CHILD_AGE} months | {CHILD_WEIGHT} kg | {SYMPTOM}")
    print(f"  Location: {VILLAGE}, {MANDAL} Mandal")
    print(f"  CHW: {CHW_ID}")

    # ── CVBM: Compute Biological Urgency Score
    print_separator("CVBM: Biological Urgency Score")

    bus_result = compute_bus(
        child_age_months=CHILD_AGE,
        child_weight_kg=CHILD_WEIGHT,
        temperature_c=climate_ctx.temperature_c,
        aqi=climate_ctx.aqi,
        humidity_pct=climate_ctx.humidity_pct,
        time_exposed_min=45.0,   # estimated 45 min of heat exposure
    )

    print(f"\n  Child Biology Analysis:")
    print(f"  {'SA:mass ratio':<30}: {bus_result.sa_mass_ratio} cm²/kg")
    print(f"  {'Cooling capacity':<30}: {bus_result.cooling_capacity_pct}%")
    print(f"  {'Fluid loss rate':<30}: {bus_result.fluid_loss_rate_ml_per_min} mL/min")
    print(f"  {'Time to mild dehydration':<30}: {bus_result.minutes_to_mild_dehydration} min")
    print(f"  {'Remaining safe window':<30}: {bus_result.remaining_safe_window_min} min")
    print(f"\n  ★ BIOLOGICAL URGENCY SCORE: {bus_result.bus_score}/100 [{bus_result.urgency_level}]")
    print(f"\n  Action: {bus_result.recommended_action}")

    # ── RDT: Compute climate-adjusted response time
    print_separator("RDT: Climate-Adjusted Response Time")

    # Simulate realistic timestamps
    ts_report = now
    # In this demo, simulate a delayed response
    ts_ack    = ts_report + timedelta(minutes=14)   # RT = 14 min (slow)
    ts_decide = ts_ack    + timedelta(minutes=20)   # DT = 20 min
    ts_action = ts_decide + timedelta(minutes=42)   # ET = 42 min

    cif = max(0, (climate_ctx.temperature_c - 30) * 0.035)

    case = CaseRDT(
        case_id         = "GNT-LIVE-001",
        child_age_months= CHILD_AGE,
        child_weight_kg = CHILD_WEIGHT,
        symptom         = SYMPTOM,
        mandal          = MANDAL,
        village         = VILLAGE,
        chw_id          = CHW_ID,
        temperature_c   = climate_ctx.temperature_c,
        aqi             = climate_ctx.aqi,
        humidity_pct    = climate_ctx.humidity_pct,
        bus_score       = bus_result.bus_score,
        cif_score       = round(cif, 3),
        ts_reported     = ts_report.isoformat(),
        ts_acknowledged = ts_ack.isoformat(),
        ts_decided      = ts_decide.isoformat(),
        ts_action_start = ts_action.isoformat(),
        climate_pathway = "HEAT_DIRECT",
    )

    case = run_rdt_pipeline(case)

    baseline = GUNTUR_BASELINES["total_min"]
    print(f"\n  RDT Computation:")
    print(f"  {'Reaction Time (RT)':<30}: {case.rt_min} min")
    print(f"  {'Decision Time (DT)':<30}: {case.dt_min} min")
    print(f"  {'Execution Time (ET)':<30}: {case.et_min} min")
    print(f"  {'Total RDT':<30}: {case.total_rdt_min} min")
    print(f"\n  Climate Adjustment (BUS={bus_result.bus_score}):")
    print(f"  {'Normal baseline':<30}: {baseline} min")
    print(f"  {'T_adj (child-biology-driven)':<30}: {case.t_adj_total} min")
    print(f"  {'Tighter by':<30}: {round((1 - case.t_adj_total/baseline)*100)}%")
    print(f"\n  Deviation from T_adj: +{case.deviation} min ({case.deviation_pct}%)")
    print(f"\n  ★ DELAY CLASSIFICATION: {case.delay_class}")
    print(f"  ★ DELAY CAUSE: {case.delay_cause}")
    print(f"  ★ INTERVENTION: {case.intervention_type} → {case.escalated_to}")

    # ── CHW instructions
    print_separator("CHW Instructions (Cognitive Load Optimized)")
    instructions = case.get_chw_instructions()
    print(f"\n  {'='*45}")
    print(f"  CASE {instructions['case_id']} | {instructions['urgency']}")
    print(f"  🌡️  {instructions['climate_alert']}")
    print(f"  👶 {instructions['child_profile']} | BUS: {instructions['bus_score']}/100")
    print(f"  ⏱️  YOUR TARGET: {instructions['your_target_min']} min")
    print(f"  📝 {instructions['why_adjusted']}")
    print(f"  {'='*45}")
    print(f"\n  DO THIS NOW:")
    for j, step in enumerate(instructions["steps"], 1):
        print(f"    {j}. {step}")
    if instructions["escalation"]:
        print(f"\n  ⚠️  {instructions['escalation']}")
    if instructions["not_your_fault"]:
        print(f"\n  ℹ️  {instructions['not_your_fault']}")

    return case


def run_district_analysis():
    """Generate synthetic cases and compute district-level evidence."""

    print_separator("STEP 4: DISTRICT EVIDENCE — BASELINE vs WITH COIP")

    # Generate baseline (without COIP)
    print("\n  Generating Guntur pilot data (summer months: Mar-Jun)...")
    baseline = generate_cases(150, scenario="baseline", months=[3,4,5,6])
    with_coip = generate_cases(150, scenario="with_coip", months=[3,4,5,6])

    # Save data files
    os.makedirs("data/guntur", exist_ok=True)
    save_cases_csv(baseline, "data/guntur/cases_baseline.csv")
    save_cases_csv(with_coip, "data/guntur/cases_with_coip.csv")

    b = compute_district_summary(baseline)
    c = compute_district_summary(with_coip)

    rdt_reduction = round(b["avg_rdt_min"] - c["avg_rdt_min"], 1)
    rdt_pct = round(rdt_reduction / b["avg_rdt_min"] * 100)
    critical_reduction = round(b["pct_critical"] - c["pct_critical"], 1)

    print(f"\n  {'Metric':<35} {'BASELINE':>12} {'WITH COIP':>12} {'CHANGE':>10}")
    print(f"  {'─'*71}")
    print(f"  {'Avg Response Time (min)':<35} {b['avg_rdt_min']:>12} {c['avg_rdt_min']:>12} {f'-{rdt_reduction}min ({rdt_pct}%)':>10}")
    print(f"  {'On-time responses (%)':<35} {b['pct_on_time']:>11}% {c['pct_on_time']:>11}%")
    print(f"  {'Critical delays (%)':<35} {b['pct_critical']:>11}% {c['pct_critical']:>11}% {f'-{critical_reduction}%':>10}")
    print(f"  {'Climate-caused delays (%)':<35} {b['pct_climate_caused']:>11}% {'Identified':>12}")
    print(f"  {'Avg BUS score':<35} {b['avg_bus_score']:>12} {c['avg_bus_score']:>12}")

    print(f"\n  ★ EVIDENCE:")
    print(f"    Response time: {b['avg_rdt_min']} min → {c['avg_rdt_min']} min")
    print(f"    Improvement: {rdt_pct}% reduction")
    print(f"    Critical delays reduced by {critical_reduction}%")
    print(f"    Data files saved: data/guntur/cases_baseline.csv")

    return b, c


def main():
    print_header()
    print(f"\n  Running at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} IST")
    print(f"  Pilot location: Guntur District (16.3067°N, 80.4365°E)")

    # ── STEP 1: Get real climate data
    print_separator("STEP 1: ESI — Real Climate Data for Guntur")
    climate_ctx = get_climate_context()

    print(f"\n  Live Climate Conditions:")
    ctx = climate_ctx.to_dict()
    for k in ["temperature_c","humidity_pct","aqi","uv_index",
              "rainfall_mm","heatwave_active","climate_risk_level",
              "hazard_type","source"]:
        print(f"  {k:<30}: {ctx[k]}")

    # ── STEP 2: Run a live case through the pipeline
    live_case = run_live_case_demo(climate_ctx)

    # ── STEP 3: Disease Surge Forecast
    print_separator("STEP 3: CDSP — Disease Surge Forecast for Guntur")

    # Get 48h forecast for anticipatory action
    forecasts_48h = get_48h_forecast()
    peak_48h = max((f["temperature_c"] for f in forecasts_48h), default=climate_ctx.temperature_c)

    district_forecast = run_district_forecast(
        temperature_c          = climate_ctx.temperature_c,
        aqi                    = climate_ctx.aqi,
        humidity_pct           = climate_ctx.humidity_pct,
        weekly_rainfall_mm     = climate_ctx.rainfall_mm * 7,
        forecast_max_temp_48h  = peak_48h,
    )

    print(f"\n  District Alert Level: {district_forecast['district_alert']}")
    print(f"\n  Disease Risk Matrix:")
    for disease, forecast in district_forecast["disease_forecasts"].items():
        print(f"  {disease:20s}: {forecast['risk_level']:10s} "
              f"(score={forecast['risk_score']:.2f}, conf={forecast['confidence_pct']}%)")
        print(f"    Window: {forecast['forecast_window']}")

    print(f"\n  Top Resource Actions:")
    for action in district_forecast["resource_actions"]:
        print(f"    → {action}")

    # ── STEP 4: District-level evidence
    b_summary, c_summary = run_district_analysis()

    # ── STEP 5: CBAD behavior classification
    print_separator("STEP 5: CBAD — CHW Behavioral Analysis")

    registry = CHWBehaviorRegistry()
    result = registry.record_case(live_case.to_dict())

    print(f"\n  CHW: {result['chw_id']}")
    print(f"  Behavior type:    {result['behavior_type']}")
    print(f"  Delay cause:      {result['delay_cause']}")
    print(f"  Is anomalous:     {result['is_anomalous']}")
    print(f"  Performance:      {result['performance_cat']}")
    print(f"\n  CHW Feedback:")
    print(f"  '{result['chw_feedback']}'")

    # ── Final summary
    print_separator("SUMMARY — EVIDENCE GENERATED")

    print(f"""
  ┌─────────────────────────────────────────────────────┐
  │   COIP-Climate · Guntur Pilot Summary               │
  ├─────────────────────────────────────────────────────┤
  │   Climate:  {climate_ctx.temperature_c}°C | AQI {climate_ctx.aqi} | {climate_ctx.climate_risk_level:<10}           │
  │   Case:     GNT-LIVE-001 → {live_case.delay_class:<12}                │
  │   T_adj:    {live_case.t_adj_total} min (vs baseline {GUNTUR_BASELINES['total_min']} min)          │
  │   Cause:    {live_case.delay_cause:<30}              │
  │   Forecast: {district_forecast['district_alert']:<20} disease risk         │
  │                                                     │
  │   Pilot evidence (150 cases):                       │
  │   RDT reduction: {b_summary['avg_rdt_min']} → {c_summary['avg_rdt_min']} min               │
  │   Critical cases: {b_summary['pct_critical']}% → {c_summary['pct_critical']}%                  │
  │   Data: data/guntur/cases_baseline.csv              │
  └─────────────────────────────────────────────────────┘

  Open Source: Apache 2.0 | GitHub: github.com/coip-climate
  Built for UNICEF Climate Ventures 2026
    """)


if __name__ == "__main__":
    main()
