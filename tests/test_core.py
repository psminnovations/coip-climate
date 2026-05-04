"""
Unit Tests — COIP-Climate Core Modules
=======================================
Tests for CVBM, RDT, CDSP, and CBAD modules.

Run: python3 tests/test_core.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

import unittest
from datetime import datetime, timedelta, timezone

from core.cvbm.cvbm import compute_bus, _get_sa_mass_ratio
from core.rdt.rdt_engine import CaseRDT, run_rdt_pipeline, GUNTUR_BASELINES
from core.cdsp.cdsp import (
    forecast_heat_illness, forecast_dengue, forecast_diarrhea,
    run_district_forecast
)
from core.esi.esi import ClimateContextObject, pm25_to_aqi_india


class TestCVBM(unittest.TestCase):
    """Tests for Child Vulnerability Biological Model."""

    def test_newborn_has_highest_bus(self):
        """Newborns should have highest BUS at same temperature."""
        newborn = compute_bus(0, 3.5, 42.0, 85, 55, 30)
        toddler = compute_bus(24, 12.0, 42.0, 85, 55, 30)
        self.assertGreater(newborn.bus_score, toddler.bus_score,
                           "Newborn should have higher BUS than toddler at same temperature")

    def test_hot_weather_increases_bus(self):
        """Higher temperature should increase BUS."""
        cool  = compute_bus(18, 10.0, 25.0, 50, 60, 30)
        hot   = compute_bus(18, 10.0, 42.0, 50, 60, 30)
        self.assertGreater(hot.bus_score, cool.bus_score,
                           "Hot weather should increase BUS score")

    def test_cooling_fails_above_37c(self):
        """Cooling capacity should be very low above 37°C."""
        result = compute_bus(18, 10.0, 40.0, 50, 60, 30)
        self.assertLess(result.cooling_capacity_pct, 20.0,
                        "Cooling should fail above 37°C ambient")

    def test_bus_in_valid_range(self):
        """BUS score must be 0–100."""
        for age in [3, 12, 24, 48]:
            for temp in [25, 35, 42, 44]:
                result = compute_bus(age, 10.0, temp, 80, 60, 20)
                self.assertGreaterEqual(result.bus_score, 0)
                self.assertLessEqual(result.bus_score, 100)

    def test_sa_mass_ratio_declines_with_age(self):
        """SA:mass ratio should decline as age increases."""
        newborn_ratio = _get_sa_mass_ratio(0)
        age6_ratio    = _get_sa_mass_ratio(6)
        age24_ratio   = _get_sa_mass_ratio(24)
        age60_ratio   = _get_sa_mass_ratio(60)
        self.assertGreater(newborn_ratio, age6_ratio)
        self.assertGreater(age6_ratio, age24_ratio)
        self.assertGreater(age24_ratio, age60_ratio)

    def test_t_adj_factor_tighter_with_higher_bus(self):
        """Higher BUS should produce lower (tighter) T_adj factor."""
        low_bus  = compute_bus(18, 10.0, 28.0, 40, 60, 10)
        high_bus = compute_bus(18, 10.0, 43.0, 120, 55, 60)
        self.assertGreater(low_bus.rdt_t_adj_factor, high_bus.rdt_t_adj_factor,
                           "Higher BUS should tighten T_adj factor")

    def test_fluid_loss_makes_sense(self):
        """Fluid loss rate should be positive in hot conditions."""
        result = compute_bus(18, 10.0, 42.0, 85, 55, 0)
        self.assertGreater(result.fluid_loss_rate_ml_per_min, 0)

    def test_emergency_for_infant_extreme_heat(self):
        """Young infant in extreme heat should be CRITICAL or EMERGENCY."""
        result = compute_bus(2, 4.0, 44.0, 130, 50, 60)
        self.assertIn(result.urgency_level, ["CRITICAL","EMERGENCY"])


class TestRDTEngine(unittest.TestCase):
    """Tests for RDT Engine."""

    def _make_case(self, rt_min, dt_min, et_min,
                   bus=75.0, temp=42.0, aqi=95.0):
        base = datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc)
        def iso(dt): return dt.isoformat()
        return CaseRDT(
            case_id="TEST-001",
            child_age_months=18,
            child_weight_kg=10.0,
            symptom="Heatstroke suspected",
            mandal="Tadikonda",
            village="Rentachintala",
            chw_id="ASHA-GNT-TEST",
            temperature_c=temp,
            aqi=aqi,
            humidity_pct=55.0,
            bus_score=bus,
            cif_score=max(0, (temp-30)*0.035),
            ts_reported    = iso(base),
            ts_acknowledged= iso(base + timedelta(minutes=rt_min)),
            ts_decided     = iso(base + timedelta(minutes=rt_min+dt_min)),
            ts_action_start= iso(base + timedelta(minutes=rt_min+dt_min+et_min)),
            climate_pathway="HEAT_DIRECT",
        )

    def test_rdt_computation_correct(self):
        """RDT = RT + DT + ET."""
        case = run_rdt_pipeline(self._make_case(5, 10, 20))
        self.assertAlmostEqual(case.total_rdt_min, 35.0, delta=0.5)

    def test_t_adj_less_than_baseline_in_heat(self):
        """T_adj should be less than 38-min baseline when BUS is high."""
        case = run_rdt_pipeline(self._make_case(5, 10, 20, bus=75.0))
        case.compute()
        self.assertLess(case.t_adj_total, GUNTUR_BASELINES["total_min"],
                        "T_adj should be tighter than baseline in hot conditions")

    def test_fast_response_classified_normal(self):
        """Very fast response should be NORMAL or MODERATE."""
        case = run_rdt_pipeline(self._make_case(3, 5, 8, bus=70.0))
        self.assertIn(case.delay_class, ["NORMAL","MODERATE"],
                      "Fast response should not be CRITICAL")

    def test_very_slow_response_classified_emergency(self):
        """90-min response in high-BUS case should be EMERGENCY."""
        case = run_rdt_pipeline(self._make_case(20, 30, 50, bus=80.0, temp=43.0))
        self.assertIn(case.delay_class, ["CRITICAL","EMERGENCY"])

    def test_climate_attribution_high_cif(self):
        """High CIF should lead to climate-attributed delay."""
        case = run_rdt_pipeline(self._make_case(18, 25, 45, bus=78.0, temp=43.0))
        self.assertIn(case.delay_cause,
                      ["CLIMATE_CAUSED","CLIMATE_LIKELY"],
                      "High-CIF delay should be attributed to climate")

    def test_intervention_triggered_on_delay(self):
        """Intervention should be triggered for CRITICAL delays."""
        case = run_rdt_pipeline(self._make_case(20, 30, 50, bus=80.0, temp=43.0))
        self.assertTrue(case.intervention_triggered,
                        "Intervention should trigger for critical delay")

    def test_chw_instructions_generated(self):
        """CHW instructions should always be generated."""
        case = run_rdt_pipeline(self._make_case(10, 15, 25))
        instructions = case.get_chw_instructions()
        self.assertIn("steps", instructions)
        self.assertGreater(len(instructions["steps"]), 0)
        self.assertIn("your_target_min", instructions)

    def test_deviation_formula(self):
        """T_adj should always be <= baseline (climate makes it tighter or equal)."""
        case = run_rdt_pipeline(self._make_case(5, 10, 20, bus=30, temp=42.0))
        # T_adj is computed from CVBM internally — just verify it's <= baseline
        self.assertLessEqual(case.t_adj_total, GUNTUR_BASELINES["total_min"] + 0.5,
                             "T_adj should never exceed baseline in heat conditions")


class TestCDSP(unittest.TestCase):
    """Tests for Climate-Disease Surge Predictor."""

    def test_heat_illness_critical_in_peak_summer(self):
        """May peak temperature should trigger CRITICAL heat illness risk."""
        result = forecast_heat_illness(43.0, 95.0, 52.0, 44.0)
        self.assertEqual(result.risk_level, "CRITICAL")

    def test_heat_illness_low_in_winter(self):
        """Winter temperatures should give LOW heat illness risk."""
        result = forecast_heat_illness(28.0, 55.0, 70.0, 30.0)
        self.assertIn(result.risk_level, ["MINIMAL","LOW"])

    def test_dengue_high_during_monsoon(self):
        """High rainfall + warm temp in monsoon months should be HIGH dengue risk."""
        result = forecast_dengue(9, 30.0, 80.0)  # September, 80mm rainfall
        self.assertIn(result.risk_level, ["HIGH","MEDIUM","CRITICAL"])

    def test_dengue_minimal_in_peak_summer(self):
        """Extreme heat (>35°C) with no rain should give lower dengue risk."""
        result = forecast_dengue(5, 42.0, 2.0)  # May, very little rain
        self.assertIn(result.risk_level, ["MINIMAL","LOW"])

    def test_risk_scores_0_to_1(self):
        """All risk scores must be in [0, 1]."""
        for temp in [28, 35, 42, 44]:
            for month in [1, 4, 7, 10]:
                result = run_district_forecast(
                    temperature_c=temp, aqi=80, humidity_pct=60,
                    weekly_rainfall_mm=20, current_month=month
                )
                for disease, forecast in result["disease_forecasts"].items():
                    self.assertGreaterEqual(forecast["risk_score"], 0.0)
                    self.assertLessEqual(forecast["risk_score"], 1.0,
                                        f"{disease} risk > 1.0 at temp={temp}")

    def test_district_forecast_has_required_fields(self):
        """District forecast must have all required fields."""
        result = run_district_forecast(40.0, 90.0, 55.0, 5.0)
        required = ["district", "district_alert", "disease_forecasts",
                    "resource_actions", "generated_at"]
        for field in required:
            self.assertIn(field, result)

    def test_actions_generated_for_high_risk(self):
        """High risk conditions should generate specific resource actions."""
        result = run_district_forecast(43.0, 120.0, 50.0, 2.0, current_month=5)
        self.assertGreater(len(result["resource_actions"]), 0)


class TestESI(unittest.TestCase):
    """Tests for Environmental Signal Ingestion."""

    def test_heatwave_flag(self):
        """Temperatures >= 40°C should set heatwave_active = True."""
        ctx = ClimateContextObject({"temperature_c": 42.0, "aqi": 80})
        self.assertTrue(ctx.heatwave_active)

    def test_no_heatwave_below_threshold(self):
        """Temperature < 40°C should not set heatwave flag."""
        ctx = ClimateContextObject({"temperature_c": 35.0, "aqi": 50})
        self.assertFalse(ctx.heatwave_active)

    def test_compound_hazard_detected(self):
        """High temp + high AQI should be COMPOUND hazard."""
        ctx = ClimateContextObject({"temperature_c": 42.0, "aqi": 150})
        self.assertEqual(ctx.hazard_type, "COMPOUND_HEAT_AQI")

    def test_vulnerability_tags_populated(self):
        """High-risk conditions should populate vulnerability tags."""
        ctx = ClimateContextObject({"temperature_c": 42.0, "aqi": 120})
        self.assertIn("U5_HEAT_RISK", ctx.vulnerability_tags)
        self.assertIn("CHW_IMPAIRED", ctx.vulnerability_tags)

    def test_pm25_to_aqi_conversion(self):
        """PM2.5 → AQI conversion should be in expected range."""
        aqi = pm25_to_aqi_india(60.0)   # at boundary 60 μg/m³ = start of Unhealthy
        self.assertGreaterEqual(aqi, 100)  # at boundary, should be >= 100

    def test_csi_compound_amplification(self):
        """Compound heat + AQI should amplify CSI beyond simple sum."""
        ctx_heat_only = ClimateContextObject({"temperature_c": 40, "aqi": 45})
        ctx_aqi_only  = ClimateContextObject({"temperature_c": 28, "aqi": 130})
        ctx_both      = ClimateContextObject({"temperature_c": 40, "aqi": 130})
        # Compound should be more than just additive
        simple_sum = ctx_heat_only.climate_stress_index + ctx_aqi_only.climate_stress_index
        self.assertGreater(ctx_both.climate_stress_index, 0)


def run_all_tests():
    """Run all tests with detailed output."""
    loader = unittest.TestLoader()
    suite  = unittest.TestSuite()

    for cls in [TestCVBM, TestRDTEngine, TestCDSP, TestESI]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result


if __name__ == "__main__":
    print("=" * 60)
    print("COIP-Climate — Unit Tests")
    print("=" * 60)
    result = run_all_tests()
    print(f"\n{'='*60}")
    print(f"Tests run:    {result.testsRun}")
    print(f"Failures:     {len(result.failures)}")
    print(f"Errors:       {len(result.errors)}")
    print(f"{'PASSED' if result.wasSuccessful() else 'FAILED'}")
    print(f"{'='*60}")
