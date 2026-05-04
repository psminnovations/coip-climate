"""
RDT Engine v2 — Reaction-Decision-Execution Time Intelligence
==============================================================
FIXES FROM v1:
  1. deviation_pct: was (total/t_adj)*100 → now (deviation/t_adj)*100
  2. Negative timestamp guard — invalid data flagged, not silently zero'd
  3. delay_cause: MODERATE now handled correctly
  4. Per-stage deviation added (RT/DT/ET each have own deviation_pct)
  5. Bottleneck identification: which stage caused the delay
  6. SLA breach detection per stage
  7. compute_district_rdt_summary() for evidence reporting
  8. data_quality field tracks timestamp validity
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Dict


GUNTUR_BASELINES = {
    "rt_min":    8.0,
    "dt_min":   12.0,
    "et_min":   18.0,
    "total_min": 38.0,
    "current_avg_actual_min": 72.0,
    "target_with_coip_min":   30.0,
}

STAGE_SLA = {
    "rt_sla_min": 12.0,
    "dt_sla_min": 18.0,
    "et_sla_min": 25.0,
}

DELAY_THRESHOLDS = {
    "NORMAL":   (0.0,  1.0),
    "MODERATE": (1.0,  1.3),
    "DELAYED":  (1.3,  1.6),
    "CRITICAL": (1.6,  2.2),
    "EMERGENCY":(2.2, 99.9),
}

CLIMATE_CIF_THRESHOLD = 0.35


@dataclass
class CaseRDT:
    case_id:          str
    child_age_months: int
    child_weight_kg:  float
    symptom:          str
    mandal:           str
    village:          str
    chw_id:           str

    temperature_c:    float
    aqi:              float
    humidity_pct:     float
    bus_score:        float
    cif_score:        float

    ts_reported:      str
    ts_acknowledged:  Optional[str] = None
    ts_decided:       Optional[str] = None
    ts_action_start:  Optional[str] = None
    ts_resolved:      Optional[str] = None

    # Stage times
    rt_min: float = 0.0
    dt_min: float = 0.0
    et_min: float = 0.0
    total_rdt_min: float = 0.0

    # T_adj per stage
    t_adj_rt:    float = 0.0
    t_adj_dt:    float = 0.0
    t_adj_et:    float = 0.0
    t_adj_total: float = 0.0

    # Deviation — FIXED formula: (deviation_minutes / t_adj) * 100
    deviation:     float = 0.0   # minutes over/under target
    deviation_pct: float = 0.0   # % over/under target (not ratio*100)

    # Per-stage deviation
    rt_deviation_pct: float = 0.0
    dt_deviation_pct: float = 0.0
    et_deviation_pct: float = 0.0

    delay_class:  str = "PENDING"
    delay_cause:  str = "UNKNOWN"
    bottleneck:   str = "NONE"

    rt_sla_breach: bool = False
    dt_sla_breach: bool = False
    et_sla_breach: bool = False

    data_quality: str = "OK"
    data_notes:   str = ""

    is_complete:  bool = False
    intervention_triggered: bool = False
    intervention_type:      str  = "NONE"
    escalated_to:           str  = "NONE"

    climate_pathway: str = "UNKNOWN"
    outcome:         str = "PENDING"

    def compute(self) -> "CaseRDT":
        from core.cvbm.cvbm import compute_bus

        bus = compute_bus(
            self.child_age_months, self.child_weight_kg,
            self.temperature_c, self.aqi, self.humidity_pct,
            time_exposed_min=30.0
        )
        f = bus.rdt_t_adj_factor

        self.t_adj_rt    = round(GUNTUR_BASELINES["rt_min"]    * f, 1)
        self.t_adj_dt    = round(GUNTUR_BASELINES["dt_min"]    * f, 1)
        self.t_adj_et    = round(GUNTUR_BASELINES["et_min"]    * f, 1)
        self.t_adj_total = round(GUNTUR_BASELINES["total_min"] * f, 1)

        def _diff(t0: str, t1: str, stage: str) -> float:
            if not t0 or not t1:
                return 0.0
            try:
                s = datetime.fromisoformat(t0.replace("Z", "+00:00"))
                e = datetime.fromisoformat(t1.replace("Z", "+00:00"))
                diff = round((e - s).total_seconds() / 60.0, 2)
                if diff < 0:
                    self.data_quality = "ERROR"
                    self.data_notes += f"{stage} negative ({diff}min). "
                    return 0.0
                if diff > 480:
                    self.data_quality = "WARNING"
                    self.data_notes += f"{stage} long ({diff}min). "
                return diff
            except Exception as ex:
                self.data_quality = "ERROR"
                self.data_notes += f"{stage} parse error. "
                return 0.0

        if self.ts_acknowledged:
            self.rt_min = _diff(self.ts_reported, self.ts_acknowledged, "RT")
        if self.ts_acknowledged and self.ts_decided:
            self.dt_min = _diff(self.ts_acknowledged, self.ts_decided, "DT")
        if self.ts_decided and self.ts_action_start:
            self.et_min = _diff(self.ts_decided, self.ts_action_start, "ET")

        self.total_rdt_min = round(self.rt_min + self.dt_min + self.et_min, 2)

        # FIXED: deviation_pct = (deviation_minutes / t_adj) * 100
        # NOT: (total / t_adj) * 100
        if self.total_rdt_min > 0 and self.t_adj_total > 0:
            self.deviation = round(self.total_rdt_min - self.t_adj_total, 2)
            self.deviation_pct = round(
                (self.deviation / self.t_adj_total) * 100, 1
            )

        # Per-stage deviation_pct
        if self.rt_min > 0 and self.t_adj_rt > 0:
            self.rt_deviation_pct = round(
                (self.rt_min - self.t_adj_rt) / self.t_adj_rt * 100, 1)
        if self.dt_min > 0 and self.t_adj_dt > 0:
            self.dt_deviation_pct = round(
                (self.dt_min - self.t_adj_dt) / self.t_adj_dt * 100, 1)
        if self.et_min > 0 and self.t_adj_et > 0:
            self.et_deviation_pct = round(
                (self.et_min - self.t_adj_et) / self.t_adj_et * 100, 1)

        # Delay classification
        if self.total_rdt_min > 0 and self.t_adj_total > 0:
            ratio = self.total_rdt_min / self.t_adj_total
            for cls, (lo, hi) in DELAY_THRESHOLDS.items():
                if lo <= ratio < hi:
                    self.delay_class = cls
                    break

        # SLA breach
        self.rt_sla_breach = self.rt_min > STAGE_SLA["rt_sla_min"] and self.rt_min > 0
        self.dt_sla_breach = self.dt_min > STAGE_SLA["dt_sla_min"] and self.dt_min > 0
        self.et_sla_breach = self.et_min > STAGE_SLA["et_sla_min"] and self.et_min > 0

        # Bottleneck
        self.bottleneck = self._identify_bottleneck()

        # Delay cause — FIXED for all 5 classes
        self.delay_cause = self._attribute_delay_cause()

        self.is_complete = bool(self.ts_action_start or self.ts_resolved)
        return self

    def _identify_bottleneck(self) -> str:
        stages = {}
        if self.rt_min > 0 and self.t_adj_rt > 0:
            stages["RT"] = self.rt_min / self.t_adj_rt
        if self.dt_min > 0 and self.t_adj_dt > 0:
            stages["DT"] = self.dt_min / self.t_adj_dt
        if self.et_min > 0 and self.t_adj_et > 0:
            stages["ET"] = self.et_min / self.t_adj_et
        if not stages:
            return "NONE"
        worst = max(stages, key=stages.get)
        if stages[worst] <= 1.0:
            return "NONE"
        return {"RT":"ALERTING_FAILURE",
                "DT":"DECISION_BOTTLENECK",
                "ET":"ACCESS_LOGISTICS"}.get(worst, worst)

    def _attribute_delay_cause(self) -> str:
        if self.delay_class == "NORMAL":
            return "NO_DELAY"
        if self.delay_class == "PENDING":
            return "PENDING"
        if self.data_quality == "ERROR":
            return "DATA_ERROR"

        cif = self.cif_score
        if cif >= CLIMATE_CIF_THRESHOLD:
            if self.delay_class in ("CRITICAL", "EMERGENCY"):
                return "CLIMATE_CAUSED"
            elif self.delay_class in ("DELAYED", "MODERATE"):
                return "CLIMATE_LIKELY"
            return "CLIMATE_MIXED"
        if cif < 0.20:
            return "SYSTEM_OR_BEHAVIORAL"
        return "MIXED"

    def get_stage_breakdown(self) -> dict:
        def _stage(actual, t_adj, sla, label, meaning):
            if actual <= 0:
                return {"actual": 0, "target": t_adj,
                        "deviation_min": 0, "deviation_pct": 0,
                        "status": "NO_DATA", "sla_breach": False,
                        "meaning": meaning}
            dev = round(actual - t_adj, 2)
            dev_pct = round(dev / t_adj * 100, 1) if t_adj > 0 else 0
            breach = actual > sla
            status = "ON_TIME" if actual <= t_adj else ("SLA_BREACH" if breach else "OVER")
            return {"actual": actual, "target": t_adj,
                    "deviation_min": dev, "deviation_pct": dev_pct,
                    "status": status, "sla_breach": breach, "meaning": meaning}

        return {
            "RT": _stage(self.rt_min, self.t_adj_rt, STAGE_SLA["rt_sla_min"],
                         "RT", "Report → CHW Acknowledged"),
            "DT": _stage(self.dt_min, self.t_adj_dt, STAGE_SLA["dt_sla_min"],
                         "DT", "Acknowledged → Decision Made"),
            "ET": _stage(self.et_min, self.t_adj_et, STAGE_SLA["et_sla_min"],
                         "ET", "Decision → Child Reached / Treatment Started"),
        }

    def get_chw_instructions(self) -> dict:
        is_impaired = self.cif_score > 0.4
        if is_impaired or self.delay_class in ("CRITICAL", "EMERGENCY"):
            steps = [
                "Call family NOW: Give 5mL ORS every 2 minutes",
                f"Go directly to: {self.village}, {self.mandal}",
                "Check: urinating? tears when crying? alert?",
            ]
        else:
            steps = [
                "Alert family: Start ORS immediately (5mL every 2 min)",
                f"Travel to: {self.village}, {self.mandal}",
                "Assess: hydration, temperature, responsiveness",
                f"Apply: WHO IMCI protocol for age {self.child_age_months}mo",
                "Document: vitals + intervention in COIP app",
            ]
        pct_faster = round((1 - self.t_adj_total / GUNTUR_BASELINES["total_min"]) * 100)
        return {
            "case_id":        self.case_id,
            "urgency":        self.delay_class,
            "climate_alert":  f"{self.temperature_c}°C | AQI {self.aqi}",
            "child_profile":  f"Age: {self.child_age_months}mo | {self.child_weight_kg}kg",
            "bus_score":      self.bus_score,
            "your_target_min": self.t_adj_total,
            "normal_target":  GUNTUR_BASELINES["total_min"],
            "why_adjusted":   f"BUS={self.bus_score} → {pct_faster}% faster needed",
            "bottleneck":     self.bottleneck,
            "steps":          steps,
            "escalation":     (f"If >{round(self.t_adj_total)}min: call supervisor"
                               if self.delay_class in ("CRITICAL","EMERGENCY") else ""),
            "not_your_fault": ("Today's heat adjusted your target — climate, not you."
                               if is_impaired else ""),
        }

    def to_dict(self) -> dict:
        return {
            "case_id":           self.case_id,
            "child_age_m":       self.child_age_months,
            "child_weight_kg":   self.child_weight_kg,
            "symptom":           self.symptom,
            "mandal":            self.mandal,
            "village":           self.village,
            "chw_id":            self.chw_id,
            "temperature_c":     self.temperature_c,
            "aqi":               self.aqi,
            "bus_score":         self.bus_score,
            "cif_score":         self.cif_score,
            "ts_reported":       self.ts_reported,
            "rt_min":            self.rt_min,
            "dt_min":            self.dt_min,
            "et_min":            self.et_min,
            "total_rdt_min":     self.total_rdt_min,
            "t_adj_rt":          self.t_adj_rt,
            "t_adj_dt":          self.t_adj_dt,
            "t_adj_et":          self.t_adj_et,
            "t_adj_total":       self.t_adj_total,
            "deviation_min":     self.deviation,
            "deviation_pct":     self.deviation_pct,
            "rt_deviation_pct":  self.rt_deviation_pct,
            "dt_deviation_pct":  self.dt_deviation_pct,
            "et_deviation_pct":  self.et_deviation_pct,
            "delay_class":       self.delay_class,
            "delay_cause":       self.delay_cause,
            "bottleneck":        self.bottleneck,
            "rt_sla_breach":     self.rt_sla_breach,
            "dt_sla_breach":     self.dt_sla_breach,
            "et_sla_breach":     self.et_sla_breach,
            "data_quality":      self.data_quality,
            "data_notes":        self.data_notes,
            "climate_pathway":   self.climate_pathway,
            "outcome":           self.outcome,
            "is_complete":       self.is_complete,
        }

    def __repr__(self):
        if self.delay_class == "PENDING":
            return f"CaseRDT({self.case_id}: PENDING)"
        return (f"CaseRDT({self.case_id}) "
                f"RDT={self.total_rdt_min}min T_adj={self.t_adj_total}min "
                f"dev={self.deviation:+.1f}min ({self.deviation_pct:+.1f}%) "
                f"[{self.delay_class}] bn={self.bottleneck}")


def run_rdt_pipeline(case: CaseRDT) -> CaseRDT:
    case.compute()
    if case.delay_class in ("DELAYED", "CRITICAL", "EMERGENCY"):
        case.intervention_triggered = True
        if case.delay_class == "EMERGENCY":
            case.intervention_type = "IMMEDIATE_ESCALATION"
            case.escalated_to      = "SUPERVISOR_AND_FACILITY"
        elif case.delay_class == "CRITICAL":
            case.intervention_type = "ESCALATION"
            case.escalated_to      = "SUPERVISOR"
        else:
            case.intervention_type = "ALERT_CHW"
            case.escalated_to      = "CHW_ONLY"
    return case


def compute_district_rdt_summary(cases: list) -> dict:
    completed = [c for c in cases
                 if c.get("is_complete") and c.get("total_rdt_min", 0) > 0]
    if not completed:
        return {"error": "No completed cases"}
    n = len(completed)
    rdts  = [c["total_rdt_min"]   for c in completed]
    devs  = [c["deviation_pct"]   for c in completed]
    t_adjs = [c["t_adj_total"]    for c in completed]

    delays = {}
    causes = {}
    bottlenecks = {}
    sla_rt = sla_dt = sla_et = 0
    for c in completed:
        delays[c.get("delay_class","?")] = delays.get(c.get("delay_class","?"),0) + 1
        causes[c.get("delay_cause","?")] = causes.get(c.get("delay_cause","?"),0) + 1
        bottlenecks[c.get("bottleneck","NONE")] = bottlenecks.get(c.get("bottleneck","NONE"),0) + 1
        if c.get("rt_sla_breach"): sla_rt += 1
        if c.get("dt_sla_breach"): sla_dt += 1
        if c.get("et_sla_breach"): sla_et += 1

    baseline = GUNTUR_BASELINES["total_min"]
    avg_rdt  = round(sum(rdts)/n, 1)
    climate_caused = (causes.get("CLIMATE_CAUSED",0) + causes.get("CLIMATE_LIKELY",0))
    critical = (delays.get("CRITICAL",0) + delays.get("EMERGENCY",0))

    return {
        "total_cases":               n,
        "avg_rdt_min":               avg_rdt,
        "avg_t_adj_min":             round(sum(t_adjs)/n, 1),
        "avg_deviation_pct":         round(sum(devs)/n, 1),
        "baseline_min":              baseline,
        "improvement_vs_baseline":   round((baseline-avg_rdt)/baseline*100, 1),
        "pct_on_time":               round(delays.get("NORMAL",0)/n*100, 1),
        "pct_critical_emergency":    round(critical/n*100, 1),
        "pct_climate_caused":        round(climate_caused/n*100, 1),
        "delay_distribution":        {k: round(v/n*100,1) for k,v in delays.items()},
        "cause_distribution":        {k: round(v/n*100,1) for k,v in causes.items()},
        "top_bottleneck":            max(bottlenecks, key=bottlenecks.get) if bottlenecks else "NONE",
        "sla_breach_pct":            {"RT": round(sla_rt/n*100,1),
                                      "DT": round(sla_dt/n*100,1),
                                      "ET": round(sla_et/n*100,1)},
    }


if __name__ == "__main__":
    from datetime import timedelta

    print("=" * 60)
    print("RDT Engine v2 — All Bugs Fixed")
    print("=" * 60)

    base = datetime(2026, 5, 3, 9, 14, tzinfo=timezone.utc)
    iso  = lambda d: d.isoformat()

    for label, rt, dt, et in [
        ("Fast",     3,  5, 12),
        ("On-time",  6, 10, 18),
        ("Moderate", 9, 15, 30),
        ("Critical",18, 25, 50),
        ("Emergency",22,32, 65),
    ]:
        c = CaseRDT(
            f"GNT-{label[:3].upper()}", 18, 10.2, "Heat exhaustion",
            "Tadikonda", "Rentachintala", "ASHA-GNT-042",
            42.0, 95.0, 55.0, 75.0, 0.42,
            iso(base),
            ts_acknowledged=iso(base+timedelta(minutes=rt)),
            ts_decided=iso(base+timedelta(minutes=rt+dt)),
            ts_action_start=iso(base+timedelta(minutes=rt+dt+et)),
            climate_pathway="HEAT_DIRECT",
        )
        c = run_rdt_pipeline(c)
        s = c.get_stage_breakdown()
        print(f"\n{label}: RDT={c.total_rdt_min}min T_adj={c.t_adj_total}min")
        print(f"  deviation={c.deviation:+.1f}min ({c.deviation_pct:+.1f}% of target)  ← FIXED")
        print(f"  [{c.delay_class}] cause={c.delay_cause}  bottleneck={c.bottleneck}")
        print(f"  RT: {s['RT']['actual']}vs{s['RT']['target']} ({s['RT']['deviation_pct']:+.1f}%) {s['RT']['status']}")
        print(f"  DT: {s['DT']['actual']}vs{s['DT']['target']} ({s['DT']['deviation_pct']:+.1f}%) {s['DT']['status']}")
        print(f"  ET: {s['ET']['actual']}vs{s['ET']['target']} ({s['ET']['deviation_pct']:+.1f}%) {s['ET']['status']}")

    print("\n── Negative timestamp guard:")
    bad = CaseRDT("BAD", 12, 9.0, "test", "X", "Y", "Z",
                  38.0, 60.0, 60.0, 40.0, 0.2,
                  iso(base),
                  ts_acknowledged=iso(base - timedelta(minutes=5)),
                  climate_pathway="HEAT_DIRECT")
    bad = run_rdt_pipeline(bad)
    print(f"  data_quality={bad.data_quality}  rt_min={bad.rt_min} (not -5)")
    print(f"  notes: {bad.data_notes}")
