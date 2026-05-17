#!/usr/bin/env python3
"""
COIP-Climate — Self-Contained Server
Single file. No external file dependencies. Dashboard HTML embedded inline.

GET  /             → Live Dashboard (HTML)
GET  /health       → Health check
GET  /climate/guntur  → Live Open-Meteo data for Guntur
GET  /climate/forecast → 48h forecast
GET  /cdsp/forecast   → Disease surge forecast
GET  /sve/vulnerability → School & facility scores
GET  /chain/summary   → Blockchain chain status
GET  /geojson/hazard  → GeoJSON hazard map
GET  /demo            → Full pipeline demo
POST /rdt/compute     → Compute RDT for a case
POST /chain/attest    → Attest case to blockchain
POST /rdt/multilingual → CHW instructions in Telugu/Hindi/English

Usage:
  python3 api/server.py
  PORT=8000 python3 api/server.py
"""

import sys, os, json, logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# DB init
from data.db import (init_db, save_case, get_district_cases,
                     log_climate, compute_and_save_summary, get_db_stats,
                     seed_from_csv, get_db_stats)
_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'coip_climate.db')
init_db(_DB)

# Seed pilot data if DB is empty (first deploy on Railway)
def _maybe_seed():
    stats = get_db_stats(_DB)
    if stats.get('cases', 0) == 0:
        csv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                'data', 'guntur', 'cases_baseline.csv')
        if os.path.exists(csv_path):
            n = seed_from_csv(csv_path, _DB)
            compute_and_save_summary(_DB)   # pre-compute evidence
            print(f"[DB] Seeded {n} Guntur pilot cases + computed evidence summary")
        else:
            print("[DB] No CSV found — DB will populate from live API calls")
    else:
        print(f"[DB] {stats['cases']} cases already in DB")

_maybe_seed()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger("coip")

PORT    = int(os.environ.get("PORT", 8000))
VERSION = "3.0.0"

# ──────────────────────────────────────────────────────────────
# DASHBOARD — served from dashboard/index.html
# Cleaner than embedding. Changes to HTML don't require touching server.py.
# ──────────────────────────────────────────────────────────────
_DASHBOARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'dashboard', 'index.html'
)

def _read_dashboard() -> bytes:
    """Read dashboard/index.html from disk."""
    with open(_DASHBOARD_PATH, 'rb') as f:
        return f.read()

# ──────────────────────────────────────────────────────────────
# HTTP HANDLER
# ──────────────────────────────────────────────────────────────
class COIPHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} {fmt % args}")

    def _send(self, data: dict, code: int = 200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-COIP-Version", VERSION)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if path == "/":
                body = _read_dashboard()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)

            elif path == "/health":
                self._send({"status":"ok","version":VERSION,"healthy":True,
                            "timestamp":datetime.now(timezone.utc).isoformat(),
                            "pilot":"Guntur District, AP",
                            "modules":["ESI","CVBM","RDT","CBAD","CDSP","SVE","MLLE","BCAL","DB"]})

            elif path == "/climate/guntur":
                from core.esi.esi import get_climate_context
                ctx = get_climate_context()
                try: log_climate(ctx.to_dict(), _DB)
                except: pass
                self._send({"status":"ok","version":VERSION,
                            "district":"Guntur, Andhra Pradesh",
                            "coordinates":{"lat":16.3067,"lon":80.4365},
                            "climate":ctx.to_dict()})

            elif path == "/climate/forecast":
                from core.esi.esi import get_48h_forecast
                self._send({"status":"ok","version":VERSION,
                            "district":"Guntur, Andhra Pradesh",
                            "hours":48,"forecast":get_48h_forecast()})

            elif path == "/cdsp/forecast":
                from core.esi.esi import get_climate_context, get_48h_forecast
                from core.cdsp.cdsp import run_district_forecast
                ctx = get_climate_context()
                fc  = get_48h_forecast()
                peak = max((f["temperature_c"] for f in fc), default=ctx.temperature_c)
                result = run_district_forecast(
                    temperature_c=ctx.temperature_c, aqi=ctx.aqi,
                    humidity_pct=ctx.humidity_pct,
                    weekly_rainfall_mm=ctx.rainfall_mm * 7,
                    forecast_max_temp_48h=peak)
                self._send({"status":"ok","version":VERSION, **result})

            elif path == "/sve/vulnerability":
                from core.esi.esi import get_climate_context
                from core.cdsp.sve import run_vulnerability_assessment
                ctx = get_climate_context()
                result = run_vulnerability_assessment(ctx.temperature_c, ctx.aqi)
                self._send({"status":"ok","version":VERSION, **result})

            elif path == "/chain/summary":
                from core.albe.bcal import COIPChain
                self._send({"status":"ok","version":VERSION,
                            **COIPChain().get_chain_summary()})

            elif path == "/geojson/hazard":
                from core.esi.esi import get_climate_context, export_geojson_hazard
                ctx = get_climate_context()
                self._send({"status":"ok","version":VERSION,
                            "geojson":export_geojson_hazard(ctx)})

            elif path == "/evidence":
                summary = compute_and_save_summary(_DB)
                stats   = get_db_stats(_DB)
                self._send({"status":"ok","version":VERSION,
                            "evidence":summary,"db_stats":stats})

            elif path == "/cases":
                cases = get_district_cases(limit=20, db_path=_DB)
                self._send({"status":"ok","version":VERSION,
                            "count":len(cases),"cases":cases})

            elif path == "/demo":
                from core.esi.esi import _synthetic_guntur_context
                from core.cvbm.cvbm import compute_bus
                from core.cdsp.cdsp import run_district_forecast
                ctx = _synthetic_guntur_context()
                bus = compute_bus(18, 10.2, ctx.temperature_c,
                                  ctx.aqi, ctx.humidity_pct, 45.0)
                fc  = run_district_forecast(ctx.temperature_c, ctx.aqi,
                                            ctx.humidity_pct, ctx.rainfall_mm*7)
                self._send({"status":"ok","version":VERSION,
                            "demo":True,
                            "climate":ctx.to_dict(),
                            "child_case":{
                                "age_months":18,"weight_kg":10.2,
                                "bus_score":bus.bus_score,
                                "urgency":bus.urgency_level,
                                "safe_window_min":bus.remaining_safe_window_min,
                                "t_adj_factor":bus.rdt_t_adj_factor,
                                "t_adj_example":f"{round(38*bus.rdt_t_adj_factor,1)}min vs 38min baseline",
                            },
                            "district_forecast":{
                                "alert":fc["district_alert"],
                                "diseases":{k:{"risk":v["risk_level"],"score":round(v["risk_score"],3)}
                                            for k,v in fc["disease_forecasts"].items()}
                            }})

            else:
                self._send({"status":"not_found","path":path,
                            "try":"GET / for dashboard"}, 404)

        except Exception as e:
            log.error(f"GET {path}: {e}", exc_info=True)
            self._send({"status":"error","message":str(e)}, 500)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except:
            self._send({"status":"error","message":"Invalid JSON"}, 400)
            return
        try:
            if path == "/rdt/compute":
                from core.rdt.rdt_engine import CaseRDT, run_rdt_pipeline
                required = ["child_age_months","child_weight_kg",
                            "temperature_c","aqi","humidity_pct","ts_reported"]
                missing  = [r for r in required if r not in payload]
                if missing:
                    self._send({"status":"error","missing":missing}, 400)
                    return
                case = CaseRDT(
                    case_id         = payload.get("case_id", f"API-{int(datetime.now().timestamp())}"),
                    child_age_months= payload["child_age_months"],
                    child_weight_kg = payload["child_weight_kg"],
                    symptom         = payload.get("symptom","unspecified"),
                    mandal          = payload.get("mandal","Guntur"),
                    village         = payload.get("village","unspecified"),
                    chw_id          = payload.get("chw_id","unspecified"),
                    temperature_c   = payload["temperature_c"],
                    aqi             = payload["aqi"],
                    humidity_pct    = payload["humidity_pct"],
                    bus_score       = payload.get("bus_score", 50.0),
                    cif_score       = payload.get("cif_score", 0.0),
                    ts_reported     = payload["ts_reported"],
                    ts_acknowledged = payload.get("ts_acknowledged"),
                    ts_decided      = payload.get("ts_decided"),
                    ts_action_start = payload.get("ts_action_start"),
                    ts_resolved     = payload.get("ts_resolved"),
                    climate_pathway = payload.get("climate_pathway","UNKNOWN"),
                )
                case = run_rdt_pipeline(case)
                try: save_case(case.to_dict(), _DB)
                except: pass
                self._send({"status":"ok","version":VERSION,
                            "rdt":case.to_dict(),
                            "stage_breakdown":case.get_stage_breakdown(),
                            "chw_instructions":case.get_chw_instructions(),
                            "saved_to_db":True})

            elif path == "/chain/attest":
                from core.albe.bcal import COIPChain
                required = ["case_id","child_age_months","ts_reported"]
                missing  = [r for r in required if r not in payload]
                if missing:
                    self._send({"status":"error","missing":missing}, 400)
                    return
                receipt = COIPChain().attest_case(payload)
                self._send({"status":"ok","version":VERSION,"attestation":receipt})

            elif path == "/rdt/multilingual":
                from core.albe.mlle import TranscreationEngine
                lang   = payload.get("language","te")
                engine = TranscreationEngine(lang)
                result = engine.generate_chw_protocol(
                    protocol_type    = payload.get("protocol_type","heat"),
                    child_age_months = payload.get("child_age_months",18),
                    child_weight_kg  = payload.get("child_weight_kg",10.0),
                    bus_score        = payload.get("bus_score",50.0),
                    t_adj_min        = payload.get("t_adj_min",25.0),
                    urgency_level    = payload.get("urgency_level","HIGH"),
                    hci_score        = payload.get("hci_score",0.0),
                    language         = lang,
                )
                self._send({"status":"ok","version":VERSION, **result})

            else:
                self._send({"status":"not_found","path":path}, 404)

        except Exception as e:
            log.error(f"POST {path}: {e}", exc_info=True)
            self._send({"status":"error","message":str(e)}, 500)


def main():
    server = HTTPServer(("0.0.0.0", PORT), COIPHandler)
    log.info(f"COIP-Climate v{VERSION} on http://0.0.0.0:{PORT}")
    log.info(f"Dashboard: http://localhost:{PORT}/")
    log.info(f"Climate:   http://localhost:{PORT}/climate/guntur")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
