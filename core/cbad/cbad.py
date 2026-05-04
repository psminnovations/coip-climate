"""
CBAD — CHW Behavioral Anomaly Detector
=======================================
ML Model 2: Isolation Forest on CHW timestamp patterns.

The key innovation: distinguishes climate-caused delay from behavioral delay.
This is the fairness engine — a CHW delayed in 43°C heat is different from
a chronically late CHW. The system protects CHWs from unfair blame.

Uses scikit-learn IsolationForest. Trains per-CHW on their own historical
patterns. Anomaly = deviation from that specific CHW's own baseline.
"""

import numpy as np
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    print("[CBAD] sklearn not available — using rule-based fallback")


# ── Behavioral classification labels
BEHAVIOR_TYPES = {
    "EFFECTIVE":   "Timely + Correct — good response pattern. Reinforce.",
    "DELAYED":     "Slow + Correct — system or external delay. Investigate cause.",
    "IMPULSIVE":   "Fast + Wrong — action taken without proper protocol. Redirect.",
    "CONFUSED":    "Slow + Wrong — struggling with decision. Provide support.",
    "CRITICAL":    "Severe delay in high-risk context. Immediate escalation.",
}

# CIF threshold above which delay is likely climate-caused
CLIMATE_ATTRIBUTION_THRESHOLD = 0.35

# CHW performance categories
CHW_PERFORMANCE = {
    "STAR":      "Consistently effective. Positive reinforcement.",
    "RELIABLE":  "Generally effective with occasional delays.",
    "DEVELOPING":"Needs support — training gap detected.",
    "AT_RISK":   "Consistent underperformance. Intervention needed.",
}


class CHWBehaviorProfile:
    """
    Per-CHW behavioral profile built from historical RDT data.
    Each CHW gets their own model — no global comparison.
    """

    def __init__(self, chw_id: str):
        self.chw_id = chw_id
        self.history: List[dict] = []   # list of past CaseRDT dicts
        self.model = None
        self.scaler = None
        self.trained = False
        self.performance_category = "DEVELOPING"
        self.climate_sensitivity = 0.5  # How much climate affects this CHW

    def add_case(self, case_dict: dict):
        """Add a completed case to the CHW's history."""
        self.history.append(case_dict)
        if len(self.history) >= 5:
            self._retrain()

    def _feature_vector(self, case: dict) -> List[float]:
        """
        Extract features from a case for anomaly detection.
        Features capture both timing and climate context.
        """
        return [
            float(case.get("rt_min", 0)),
            float(case.get("dt_min", 0)),
            float(case.get("et_min", 0)),
            float(case.get("total_rdt_min", 0)),
            float(case.get("temperature_c", 30)),
            float(case.get("aqi", 50)),
            float(case.get("bus_score", 30)),
            float(case.get("cif_score", 0)),
        ]

    def _retrain(self):
        """Retrain the Isolation Forest on this CHW's history."""
        if not SKLEARN_AVAILABLE or len(self.history) < 5:
            return

        X = np.array([self._feature_vector(c) for c in self.history])
        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X)

        self.model = IsolationForest(
            contamination=0.1,   # expect ~10% anomalous responses
            random_state=42,
            n_estimators=50
        )
        self.model.fit(X_scaled)
        self.trained = True

        # Update performance category
        n = len(self.history)
        n_delayed = sum(1 for c in self.history
                       if c.get("delay_class") in ("DELAYED","CRITICAL","EMERGENCY"))
        delay_rate = n_delayed / n if n > 0 else 0

        if delay_rate < 0.10:     self.performance_category = "STAR"
        elif delay_rate < 0.25:   self.performance_category = "RELIABLE"
        elif delay_rate < 0.45:   self.performance_category = "DEVELOPING"
        else:                     self.performance_category = "AT_RISK"

    def classify_behavior(self, case: dict) -> dict:
        """
        Classify the behavioral pattern for a new case.
        Returns classification + root cause + recommended action.
        """
        rt  = float(case.get("rt_min", 0))
        dt  = float(case.get("dt_min", 0))
        et  = float(case.get("et_min", 0))
        total = rt + dt + et
        t_adj = float(case.get("t_adj_total", 38))
        cif   = float(case.get("cif_score", 0))
        bus   = float(case.get("bus_score", 30))

        ratio = total / t_adj if t_adj > 0 else 1.0

        # ── Anomaly detection using trained model (if available)
        anomaly_score = 0.0
        is_anomalous  = False
        if self.trained and self.model and self.scaler:
            feat = np.array([self._feature_vector(case)])
            feat_scaled = self.scaler.transform(feat)
            score = self.model.decision_function(feat_scaled)[0]
            pred  = self.model.predict(feat_scaled)[0]
            anomaly_score = round(float(-score), 3)  # higher = more anomalous
            is_anomalous  = (pred == -1)

        # ── Behavior classification (rule-based, IMCI-aligned)
        # Fast response = RT < 0.5 × T_adj_RT
        is_fast = rt < (t_adj * 0.3)
        # Correct = delay_class is NORMAL or MODERATE
        delay_class = case.get("delay_class", "NORMAL")
        is_correct  = delay_class in ("NORMAL", "MODERATE")

        if is_fast and is_correct:
            behavior = "EFFECTIVE"
        elif is_fast and not is_correct:
            behavior = "IMPULSIVE"    # rushed, made errors
        elif not is_fast and is_correct:
            behavior = "DELAYED"      # slow but right
        elif not is_fast and not is_correct:
            behavior = "CONFUSED"     # slow and wrong
        else:
            behavior = "EFFECTIVE"

        # Override for severe cases
        if delay_class in ("CRITICAL", "EMERGENCY") and bus >= 70:
            behavior = "CRITICAL"

        # ── Root cause attribution (the fairness engine)
        if cif >= CLIMATE_ATTRIBUTION_THRESHOLD and behavior in ("DELAYED","CRITICAL"):
            cause = "CLIMATE_CAUSED"
            cause_note = (
                f"Delay likely caused by climate stress (CIF={cif:.2f}). "
                f"Temperature={case.get('temperature_c')}°C impairs cognitive performance. "
                "Not a performance issue — environmental compensation needed."
            )
        elif cif >= 0.20 and behavior in ("CONFUSED",):
            cause = "CLIMATE_LIKELY"
            cause_note = (
                f"Confusion may be climate-related (CIF={cif:.2f}). "
                "Provide simplified instructions and check on CHW wellbeing."
            )
        elif cif < 0.15 and behavior in ("DELAYED", "CONFUSED", "CRITICAL"):
            cause = "BEHAVIORAL_OR_SYSTEM"
            cause_note = (
                "Delay not explained by climate. Possible causes: "
                "protocol knowledge gap, workload, or system bottleneck. "
                "Review case and provide targeted support."
            )
        else:
            cause = "MIXED"
            cause_note = "Combination of factors. Review case details."

        # ── CHW-facing feedback message
        if behavior == "EFFECTIVE":
            feedback = f"Great response! You reached the child in {round(total)}min against a {round(t_adj)}min target. Keep it up."
        elif cause == "CLIMATE_CAUSED":
            feedback = (
                f"You responded in {round(total)}min. Today's {case.get('temperature_c')}°C heat "
                f"adjusted the target to {round(t_adj)}min. The heat impaired your response — "
                "this is tracked as climate-caused, not as a performance issue."
            )
        elif behavior == "CONFUSED":
            feedback = (
                "It looks like you needed more time to decide. "
                "A simplified protocol card has been sent to your phone. "
                "Your supervisor is available to support."
            )
        else:
            feedback = f"Response was {round(total)}min against target {round(t_adj)}min. Review case for learnings."

        return {
            "chw_id":            self.chw_id,
            "behavior_type":     behavior,
            "behavior_desc":     BEHAVIOR_TYPES.get(behavior, ""),
            "delay_cause":       cause,
            "cause_note":        cause_note,
            "is_anomalous":      is_anomalous,
            "anomaly_score":     anomaly_score,
            "performance_cat":   self.performance_category,
            "total_rdt_min":     round(total, 1),
            "t_adj_min":         round(t_adj, 1),
            "cif_score":         round(cif, 2),
            "cases_in_profile":  len(self.history),
            "chw_feedback":      feedback,
        }


class CHWBehaviorRegistry:
    """
    Registry of all CHW behavior profiles.
    One IsolationForest per CHW — local, fair, federated.
    """

    def __init__(self):
        self._profiles: Dict[str, CHWBehaviorProfile] = {}

    def get_or_create(self, chw_id: str) -> CHWBehaviorProfile:
        if chw_id not in self._profiles:
            self._profiles[chw_id] = CHWBehaviorProfile(chw_id)
        return self._profiles[chw_id]

    def record_case(self, case_dict: dict) -> dict:
        """
        Record a completed case and classify the behavior.
        Returns the behavior classification result.
        """
        chw_id  = case_dict.get("chw_id", "UNKNOWN")
        profile = self.get_or_create(chw_id)
        result  = profile.classify_behavior(case_dict)
        profile.add_case(case_dict)
        return result

    def get_district_summary(self) -> dict:
        """
        District-level behavioral summary.
        Shows aggregate patterns without individual blame.
        """
        total_cases   = sum(len(p.history) for p in self._profiles.values())
        climate_delays = 0
        behavior_delays = 0
        star_chws = 0
        at_risk_chws = 0

        for profile in self._profiles.values():
            for c in profile.history:
                if c.get("delay_cause") == "CLIMATE_CAUSED":
                    climate_delays += 1
                elif c.get("delay_cause") == "BEHAVIORAL_OR_SYSTEM":
                    behavior_delays += 1
            if profile.performance_category == "STAR":
                star_chws += 1
            elif profile.performance_category == "AT_RISK":
                at_risk_chws += 1

        return {
            "total_chws":          len(self._profiles),
            "total_cases":         total_cases,
            "climate_delay_cases": climate_delays,
            "behavioral_delay_cases": behavior_delays,
            "climate_delay_pct":   round(climate_delays/max(total_cases,1)*100, 1),
            "star_chws":           star_chws,
            "at_risk_chws":        at_risk_chws,
            "note": "Climate-caused delays are environmental, not performance issues."
        }


# Module-level registry (singleton for session)
_registry = CHWBehaviorRegistry()

def get_registry() -> CHWBehaviorRegistry:
    return _registry


if __name__ == "__main__":
    print("=" * 60)
    print("CBAD — CHW Behavioral Anomaly Detector Demo")
    print("=" * 60)

    registry = CHWBehaviorRegistry()

    # Simulate 10 historical cases for a CHW (training data)
    import random
    random.seed(42)

    chw_id = "ASHA-GNT-042"
    profile = registry.get_or_create(chw_id)

    # Add historical cases to build the profile
    for i in range(15):
        temp = random.uniform(34, 44)
        cif  = max(0, (temp - 30) * 0.04)
        rt   = random.uniform(5, 15)
        dt   = random.uniform(8, 20)
        et   = random.uniform(12, 35)
        total = rt + dt + et
        t_adj = 38 * (1 - min(0.65, cif * 0.8))

        hist_case = {
            "case_id":      f"GNT-HIST-{i:03d}",
            "chw_id":       chw_id,
            "rt_min":       round(rt,1),
            "dt_min":       round(dt,1),
            "et_min":       round(et,1),
            "total_rdt_min":round(total,1),
            "t_adj_total":  round(t_adj,1),
            "temperature_c":round(temp,1),
            "aqi":          random.uniform(50,140),
            "bus_score":    random.uniform(30,80),
            "cif_score":    round(cif,2),
            "delay_class":  "CRITICAL" if total > t_adj*1.6 else ("DELAYED" if total > t_adj*1.3 else "NORMAL"),
        }
        profile.add_case(hist_case)

    print(f"\nProfile for {chw_id}: {len(profile.history)} cases, category={profile.performance_category}")

    # Classify a new case
    test_case = {
        "case_id":       "GNT-2847",
        "chw_id":        chw_id,
        "rt_min":        18.0,   # slow to acknowledge
        "dt_min":        22.0,   # slow to decide
        "et_min":        45.0,   # slow to reach
        "total_rdt_min": 85.0,
        "t_adj_total":   21.0,   # tight because BUS=78 at 43°C
        "temperature_c": 43.0,
        "aqi":           127.0,
        "bus_score":     78.0,
        "cif_score":     0.42,   # CHW at 58% cognitive capacity
        "delay_class":   "EMERGENCY",
    }

    result = registry.record_case(test_case)
    print(f"\nCase GNT-2847 Classification:")
    for k, v in result.items():
        print(f"  {k:25s}: {v}")
