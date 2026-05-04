#!/usr/bin/env python3
"""
COIP-Climate API Server
========================
Deployable HTTP API — zero external dependencies beyond stdlib.
Uses Python's built-in http.server — no FastAPI, no Flask, no uvicorn.

Endpoints:
  GET  /health             → system health check
  GET  /climate/guntur     → live climate context for Guntur district
  GET  /climate/forecast   → 48-hour climate forecast
  POST /rdt/compute        → compute RDT for a case (JSON body)
  GET  /cdsp/forecast      → disease surge forecast for current conditions
  GET  /sve/vulnerability  → school & facility vulnerability scores
  GET  /chain/summary      → blockchain attestation chain summary
  POST /chain/attest       → attest a case record
  GET  /geojson/hazard     → GeoJSON hazard map for Guntur district

Deploy free on Railway, Render, Fly.io — all support Python stdlib servers.

Usage:
  python3 api/server.py           → runs on http://localhost:8000
  PORT=8000 python3 api/server.py → specify port via env var

Public URL (deploy to Railway):
  railway up → https://coip-climate.railway.app
"""

import sys
import os
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("coip-api")

PORT = int(os.environ.get("PORT", 8000))
VERSION = "2.0.0"
BUILD = "2026-05-04"


def _json(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


def _ok(data: dict) -> dict:
    return {"status": "ok", "version": VERSION, **data}


def _err(msg: str, code: int = 400) -> tuple:
    return {"status": "error", "message": msg}, code


class COIPHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        log.info(f"{self.address_string()} {fmt % args}")

    def _send(self, data: dict, code: int = 200):
        body = _json(data).encode()
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
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        try:
            if path == "" or path == "/":
                self._send(_ok({
                    "name": "COIP-Climate API",
                    "description": "Climate-aware RDT intelligence for child health — Guntur District, AP",
                    "pilot": "Guntur District, Andhra Pradesh, India",
                    "license": "Apache 2.0",
                    "unicef": "UNICEF Venture Fund Climate Ventures 2026",
                    "endpoints": [
                        "GET  /health",
                        "GET  /climate/guntur",
                        "GET  /climate/forecast",
                        "GET  /cdsp/forecast",
                        "GET  /sve/vulnerability",
                        "GET  /chain/summary",
                        "GET  /geojson/hazard",
                        "POST /rdt/compute",
                        "POST /chain/attest",
                    ],
                }))

            elif path == "/health":
                self._send(_ok({
                    "healthy":    True,
                    "timestamp":  datetime.now(timezone.utc).isoformat(),
                    "pilot":      "Guntur District, AP",
                    "modules":    ["ESI","CVBM","RDT","CBAD","CDSP","SVE","MLLE","BCAL"],
                }))

            elif path == "/climate/guntur":
                from core.esi.esi import get_climate_context
                ctx = get_climate_context()
                self._send(_ok({
                    "district":      "Guntur, Andhra Pradesh",
                    "coordinates":   {"lat": 16.3067, "lon": 80.4365},
                    "climate":       ctx.to_dict(),
                    "note": ("source='open-meteo-live' means real API data. "
                             "source='synthetic-*' means API unavailable — historical average used.")
                }))

            elif path == "/climate/forecast":
                from core.esi.esi import get_48h_forecast
                forecast = get_48h_forecast()
                self._send(_ok({
                    "district":  "Guntur, Andhra Pradesh",
                    "hours":     48,
                    "forecast":  forecast,
                }))

            elif path == "/cdsp/forecast":
                from core.esi.esi import get_climate_context, get_48h_forecast
                from core.cdsp.cdsp import run_district_forecast
                ctx = get_climate_context()
                fc  = get_48h_forecast()
                peak = max((f["temperature_c"] for f in fc),
                           default=ctx.temperature_c)
                result = run_district_forecast(
                    temperature_c          = ctx.temperature_c,
                    aqi                    = ctx.aqi,
                    humidity_pct           = ctx.humidity_pct,
                    weekly_rainfall_mm     = ctx.rainfall_mm * 7,
                    forecast_max_temp_48h  = peak,
                )
                self._send(_ok(result))

            elif path == "/sve/vulnerability":
                from core.esi.esi import get_climate_context
                from core.cdsp.sve import run_vulnerability_assessment
                ctx = get_climate_context()
                result = run_vulnerability_assessment(ctx.temperature_c, ctx.aqi)
                self._send(_ok(result))

            elif path == "/chain/summary":
                from core.albe.bcal import COIPChain
                chain = COIPChain()
                self._send(_ok(chain.get_chain_summary()))

            elif path == "/geojson/hazard":
                from core.esi.esi import get_climate_context, export_geojson
                ctx = get_climate_context()
                # export_geojson added inline here to avoid import issues
                from core.esi.esi import export_geojson_hazard
                geojson = export_geojson_hazard(ctx)
                self._send(_ok({"geojson": geojson}))

            elif path == "/demo":
                # Quick demo showing complete pipeline with synthetic data
                from core.esi.esi import _synthetic_guntur_context
                from core.cvbm.cvbm import compute_bus
                from core.cdsp.cdsp import run_district_forecast
                from core.cdsp.malaria import forecast_malaria
                ctx = _synthetic_guntur_context()
                bus = compute_bus(18, 10.2, ctx.temperature_c,
                                  ctx.aqi, ctx.humidity_pct, 45.0)
                forecast = run_district_forecast(
                    ctx.temperature_c, ctx.aqi, ctx.humidity_pct,
                    ctx.rainfall_mm * 7
                )
                self._send(_ok({
                    "demo": True,
                    "description": "Complete COIP-Climate pipeline on Guntur data",
                    "climate": ctx.to_dict(),
                    "child_case_example": {
                        "child": "18mo/10.2kg",
                        "bus_score": bus.bus_score,
                        "urgency": bus.urgency_level,
                        "safe_window_min": bus.remaining_safe_window_min,
                        "t_adj_factor": bus.rdt_t_adj_factor,
                        "t_adj_example": f"{round(38*bus.rdt_t_adj_factor,1)} min (vs 38 min baseline)",
                    },
                    "district_forecast": {
                        "alert_level": forecast["district_alert"],
                        "diseases": {
                            k: {"risk": v["risk_level"], "score": v["risk_score"]}
                            for k, v in forecast["disease_forecasts"].items()
                        }
                    }
                }))

            else:
                self._send({"status": "not_found",
                            "path": path,
                            "try": "GET /  for endpoint list"}, 404)

        except Exception as e:
            log.error(f"GET {path} error: {e}", exc_info=True)
            self._send({"status": "error", "message": str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(body)
        except Exception:
            self._send({"status": "error", "message": "Invalid JSON body"}, 400)
            return

        try:
            if path == "/rdt/compute":
                """
                Compute RDT for a case.
                Required fields:
                  child_age_months, child_weight_kg, temperature_c, aqi, humidity_pct,
                  bus_score, cif_score, ts_reported, ts_acknowledged (optional),
                  ts_decided (optional), ts_action_start (optional)
                """
                from core.rdt.rdt_engine import CaseRDT, run_rdt_pipeline

                required = ["child_age_months", "child_weight_kg",
                            "temperature_c", "aqi", "humidity_pct", "ts_reported"]
                missing = [r for r in required if r not in payload]
                if missing:
                    self._send({"status":"error",
                                "missing_fields": missing}, 400)
                    return

                case = CaseRDT(
                    case_id          = payload.get("case_id", f"API-{int(datetime.now().timestamp())}"),
                    child_age_months = payload["child_age_months"],
                    child_weight_kg  = payload["child_weight_kg"],
                    symptom          = payload.get("symptom", "unspecified"),
                    mandal           = payload.get("mandal", "Guntur"),
                    village          = payload.get("village", "unspecified"),
                    chw_id           = payload.get("chw_id", "unspecified"),
                    temperature_c    = payload["temperature_c"],
                    aqi              = payload["aqi"],
                    humidity_pct     = payload["humidity_pct"],
                    bus_score        = payload.get("bus_score", 50.0),
                    cif_score        = payload.get("cif_score", 0.0),
                    ts_reported      = payload["ts_reported"],
                    ts_acknowledged  = payload.get("ts_acknowledged"),
                    ts_decided       = payload.get("ts_decided"),
                    ts_action_start  = payload.get("ts_action_start"),
                    ts_resolved      = payload.get("ts_resolved"),
                    climate_pathway  = payload.get("climate_pathway", "UNKNOWN"),
                )
                case = run_rdt_pipeline(case)
                self._send(_ok({
                    "rdt":            case.to_dict(),
                    "stage_breakdown": case.get_stage_breakdown(),
                    "chw_instructions": case.get_chw_instructions(),
                }))

            elif path == "/chain/attest":
                """
                Attest a case record to the blockchain.
                Required: case_id, child_age_months, ts_reported, delay_class, outcome
                """
                from core.albe.bcal import COIPChain
                required = ["case_id", "child_age_months", "ts_reported"]
                missing = [r for r in required if r not in payload]
                if missing:
                    self._send({"status":"error", "missing_fields": missing}, 400)
                    return
                chain = COIPChain()
                receipt = chain.attest_case(payload)
                self._send(_ok({"attestation": receipt}))

            elif path == "/rdt/multilingual":
                """
                Get CHW instructions in target language.
                Required: language (te/hi/en), protocol_type, child_age_months,
                          child_weight_kg, bus_score, t_adj_min, urgency_level, hci_score
                """
                from core.albe.mlle import TranscreationEngine
                lang = payload.get("language", "te")
                engine = TranscreationEngine(lang)
                result = engine.generate_chw_protocol(
                    protocol_type    = payload.get("protocol_type", "heat"),
                    child_age_months = payload.get("child_age_months", 18),
                    child_weight_kg  = payload.get("child_weight_kg", 10.0),
                    bus_score        = payload.get("bus_score", 50.0),
                    t_adj_min        = payload.get("t_adj_min", 25.0),
                    urgency_level    = payload.get("urgency_level", "HIGH"),
                    hci_score        = payload.get("hci_score", 0.0),
                    language         = lang,
                )
                self._send(_ok(result))

            else:
                self._send({"status": "not_found", "path": path}, 404)

        except Exception as e:
            log.error(f"POST {path} error: {e}", exc_info=True)
            self._send({"status": "error", "message": str(e)}, 500)


def main():
    server = HTTPServer(("0.0.0.0", PORT), COIPHandler)
    log.info(f"COIP-Climate API v{VERSION} started on http://0.0.0.0:{PORT}")
    log.info(f"Pilot: Guntur District, Andhra Pradesh, India")
    log.info(f"Try:   curl http://localhost:{PORT}/demo")
    log.info(f"Try:   curl http://localhost:{PORT}/climate/guntur")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
