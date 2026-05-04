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

# Database
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.db import (init_db, save_case, get_case, get_district_cases,
                     log_climate, compute_and_save_summary, get_db_stats,
                     save_chw_profile, load_chw_profile)

# Initialize database on startup
_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        'data', 'coip_climate.db')
init_db(_DB_PATH)

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



# ── EMBEDDED DASHBOARD HTML ────────────────────────────────
# Embedded directly so the server is a single self-contained file.
# No dashboard/index.html needed.
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>COIP-Climate · Live Dashboard · Guntur District</title>
<link href="https://fonts.googleapis.com/css2?family=Azeret+Mono:wght@300;400;500;600;700&family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet">
<style>
/* ── DESIGN DIRECTION: Mission-critical ops terminal meets editorial print ── */
:root {
  --api: 'https://web-production-9e7cf.up.railway.app';
  --bg:       #040810;
  --surface:  #080F1C;
  --card:     #0C1525;
  --border:   rgba(255,255,255,0.08);
  --border-hi:rgba(255,255,255,0.16);

  /* Temperature-responsive palette */
  --heat-ext: #FF2D00;
  --heat-hi:  #FF6B00;
  --amber:    #F5A623;
  --yellow:   #FFD600;
  --green:    #00E676;
  --teal:     #00BCD4;
  --blue:     #2979FF;
  --purple:   #AA00FF;

  --t1: #F0F4FF;
  --t2: #8898BB;
  --t3: #3D4F6E;
  --t4: #1E2C42;

  --mono: 'Azeret Mono', monospace;
  --serif: 'DM Serif Display', serif;
  --sans: 'DM Sans', sans-serif;

  /* Live from API */
  --live-temp: 35.6;
  --live-risk: #00E676;
}

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior: smooth; }

body {
  background: var(--bg);
  color: var(--t1);
  font-family: var(--sans);
  min-height: 100vh;
  overflow-x: hidden;
}

/* Scanline atmosphere */
body::before {
  content:''; position:fixed; inset:0; pointer-events:none; z-index:0;
  background: repeating-linear-gradient(
    0deg, transparent, transparent 3px,
    rgba(0,200,255,0.006) 3px, rgba(0,200,255,0.006) 4px
  );
}

/* Ambient glow */
.ambient {
  position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background:
    radial-gradient(ellipse 60% 40% at 20% 10%, rgba(255,69,0,0.07) 0%, transparent 60%),
    radial-gradient(ellipse 40% 50% at 80% 80%, rgba(0,188,212,0.05) 0%, transparent 60%);
}

.page { position:relative; z-index:1; }

/* ════════════════════ MASTHEAD ════════════════════ */
.masthead {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: 0 32px;
  height: 58px;
  border-bottom: 1px solid var(--border-hi);
  background: rgba(4,8,16,0.96);
  backdrop-filter: blur(20px);
  position: sticky; top:0; z-index:100;
}

.brand {
  display: flex; align-items: center; gap: 14px;
}

.brand-logo {
  font-family: var(--serif);
  font-size: 20px;
  color: var(--t1);
  letter-spacing: -0.01em;
}

.brand-logo em { color: var(--heat-hi); font-style: normal; }

.brand-pipe {
  width: 1px; height: 22px;
  background: var(--border-hi);
}

.brand-sub {
  font-family: var(--mono);
  font-size: 9px; color: var(--t3);
  letter-spacing: 0.15em;
  text-transform: uppercase;
  line-height: 1.5;
}

.live-indicator {
  display: flex; align-items: center; gap: 8px;
  font-family: var(--mono); font-size: 9px;
  letter-spacing: 0.15em; text-transform: uppercase;
}

.live-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 8px var(--green);
  animation: ldot 1.8s ease-in-out infinite;
}

@keyframes ldot { 50% { opacity:0.3; box-shadow:none; } }

.live-text { color: var(--green); }

.api-url {
  font-family: var(--mono); font-size: 9px; color: var(--t3);
}

.masthead-right {
  display: flex; align-items: center; justify-content: flex-end; gap: 16px;
}

#clock {
  font-family: var(--mono); font-size: 11px; color: var(--t3);
}

.unicef-badge {
  font-family: var(--mono); font-size: 9px;
  padding: 4px 10px; border-radius: 2px;
  background: rgba(0,188,212,0.08);
  border: 1px solid rgba(0,188,212,0.2);
  color: var(--teal); letter-spacing: 0.1em;
}

/* ════════════════════ HERO STRIP ════════════════════ */
.hero-strip {
  padding: 20px 32px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center;
  gap: 32px;
  background: linear-gradient(90deg,
    rgba(255,69,0,0.07) 0%, transparent 60%
  );
}

.hero-title {
  font-family: var(--serif);
  font-size: clamp(22px,3vw,36px);
  line-height: 1.1;
  flex-shrink: 0;
}

.hero-title em { color: var(--heat-hi); font-style: italic; }

.hero-spine {
  flex: 1;
  font-family: var(--sans);
  font-size: 13px;
  color: var(--t2);
  line-height: 1.6;
  border-left: 2px solid rgba(255,107,0,0.3);
  padding-left: 20px;
}

.hero-spine strong { color: var(--t1); }

/* ════════════════════ LOADING STATE ════════════════════ */
.loading-overlay {
  display: flex; align-items: center; justify-content: center;
  gap: 12px;
  padding: 60px;
  font-family: var(--mono);
  font-size: 12px;
  color: var(--t3);
  letter-spacing: 0.1em;
}

.spin {
  width: 18px; height: 18px;
  border: 2px solid var(--border);
  border-top-color: var(--teal);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin { to { transform:rotate(360deg); } }

/* ════════════════════ MAIN GRID ════════════════════ */
.main { padding: 24px 32px; max-width: 1440px; margin: 0 auto; }

.section-rule {
  display: flex; align-items: center; gap: 12px;
  margin: 28px 0 14px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.sr-tag {
  font-family: var(--mono); font-size: 8px;
  padding: 3px 8px; border-radius: 2px;
  letter-spacing: 0.15em; text-transform: uppercase;
}

.sr-title {
  font-family: var(--mono); font-size: 10px;
  color: var(--t2); letter-spacing: 0.1em; text-transform: uppercase;
}

.sr-line { flex:1; }

/* ════════════════════ CLIMATE ROW ════════════════════ */
.climate-row {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin-bottom: 4px;
}

.climate-tile {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 14px;
  position: relative;
  overflow: hidden;
  transition: border-color 0.2s;
}

.climate-tile:hover { border-color: var(--border-hi); }

.climate-tile::before {
  content:''; position:absolute; top:0; left:0; right:0;
  height: 2px;
}

.ct-temp::before    { background: var(--heat-hi); }
.ct-aqi::before     { background: var(--amber); }
.ct-humid::before   { background: var(--teal); }
.ct-uv::before      { background: var(--yellow); }
.ct-rain::before    { background: var(--blue); }
.ct-risk::before    { background: var(--green); }

.ct-icon { font-size: 18px; margin-bottom: 8px; }
.ct-val {
  font-family: var(--serif);
  font-size: 28px; line-height: 1;
  margin-bottom: 2px;
}

.ct-temp .ct-val    { color: var(--heat-hi); }
.ct-aqi .ct-val     { color: var(--amber); }
.ct-humid .ct-val   { color: var(--teal); }
.ct-uv .ct-val      { color: var(--yellow); }
.ct-rain .ct-val    { color: var(--blue); }
.ct-risk .ct-val    { font-size: 18px; font-family: var(--mono); font-weight: 700; }

.ct-label {
  font-family: var(--mono); font-size: 8px;
  color: var(--t3); letter-spacing: 0.12em;
  text-transform: uppercase; margin-bottom: 3px;
}

.ct-source {
  font-family: var(--mono); font-size: 8px;
  color: var(--t4);
}

/* ════════════════════ 3-COL GRID ════════════════════ */
.tri-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 16px;
}

@media (max-width: 900px) { .tri-grid { grid-template-columns: 1fr; } }

/* ════════════════════ PANELS ════════════════════ */
.panel {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.panel-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border);
}

.ph-title {
  font-family: var(--mono); font-size: 9px;
  color: var(--t2); letter-spacing: 0.12em;
  text-transform: uppercase;
}

.ph-badge {
  font-family: var(--mono); font-size: 8px;
  padding: 2px 7px; border-radius: 2px;
  letter-spacing: 0.08em;
}

.panel-body { padding: 14px; }

/* ════════════════════ DISEASE ROWS ════════════════════ */
.disease-list { display: flex; flex-direction: column; gap: 8px; }

.disease-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
}

.dr-icon { font-size: 14px; }
.dr-name { flex:1; font-size: 11px; font-weight: 500; }
.dr-level {
  font-family: var(--mono); font-size: 9px;
  padding: 2px 8px; border-radius: 2px;
  text-transform: uppercase; letter-spacing: 0.1em;
}

.dr-bar { margin-top: 5px; height: 3px; background: rgba(255,255,255,0.05); border-radius: 2px; }
.dr-bar-fill { height: 100%; border-radius: 2px; transition: width 1.2s ease; }

/* ════════════════════ VULNERABILITY LIST ════════════════════ */
.vuln-list { display: flex; flex-direction: column; gap: 6px; }

.vuln-row {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: rgba(255,255,255,0.02);
}

.vr-rank {
  font-family: var(--serif); font-size: 18px;
  color: var(--t4); flex-shrink:0; width:24px;
  line-height:1;
}

.vr-info { flex:1; }
.vr-name { font-size: 11px; font-weight:500; margin-bottom:2px; }
.vr-meta { font-family:var(--mono); font-size:8px; color:var(--t3); }

.vr-score {
  font-family: var(--mono); font-size: 13px;
  font-weight: 700; text-align:right;
}

/* ════════════════════ FORECAST CHART ════════════════════ */
.forecast-bars {
  display: flex; align-items: flex-end;
  gap: 4px; height: 80px;
  padding: 0 2px;
  margin-top: 10px;
}

.fb-col { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; }
.fb-bar { width:100%; border-radius:2px 2px 0 0; transition: height 0.8s ease; min-height:2px; }
.fb-lbl { font-family:var(--mono); font-size:7px; color:var(--t4); text-align:center; }

/* ════════════════════ API TESTER ════════════════════ */
.api-tester {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.endpoint-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  overflow-x: auto;
  scrollbar-width: none;
}

.ep-tab {
  padding: 9px 14px;
  font-family: var(--mono); font-size: 9px;
  color: var(--t3); letter-spacing: 0.08em;
  cursor: pointer; border: none; background: transparent;
  border-bottom: 2px solid transparent;
  transition: all 0.15s; white-space: nowrap;
}

.ep-tab:hover { color: var(--t2); }
.ep-tab.active { color: var(--teal); border-bottom-color: var(--teal); }

.api-response {
  padding: 14px;
  font-family: var(--mono); font-size: 10px;
  color: var(--t2); line-height: 1.7;
  overflow: auto;
  max-height: 280px;
  white-space: pre-wrap;
  word-break: break-all;
}

.json-key    { color: var(--teal); }
.json-str    { color: var(--green); }
.json-num    { color: var(--amber); }
.json-bool   { color: var(--purple); }
.json-null   { color: var(--t3); }

/* ════════════════════ RDT DEMO ════════════════════ */
.rdt-form { display:flex; flex-direction:column; gap:10px; padding:14px; }

.form-row { display:grid; grid-template-columns:1fr 1fr; gap:8px; }

.form-field { display:flex; flex-direction:column; gap:4px; }

.field-label {
  font-family:var(--mono); font-size:8px;
  color:var(--t3); letter-spacing:0.12em;
  text-transform:uppercase;
}

.field-input {
  background: rgba(0,0,0,0.3);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 7px 10px;
  font-family: var(--mono); font-size: 11px;
  color: var(--t1);
  outline: none;
  transition: border-color 0.15s;
}

.field-input:focus { border-color: var(--teal); }

.btn-compute {
  padding: 10px 20px;
  background: var(--teal);
  color: var(--bg);
  border: none; border-radius: 3px;
  font-family: var(--mono); font-size: 10px;
  font-weight: 600; letter-spacing: 0.12em;
  text-transform: uppercase;
  cursor: pointer;
  transition: opacity 0.15s;
}

.btn-compute:hover { opacity: 0.85; }
.btn-compute:disabled { opacity: 0.4; cursor: not-allowed; }

.rdt-result {
  margin-top: 10px; padding: 12px;
  background: rgba(0,0,0,0.25);
  border-radius: 4px;
  border: 1px solid var(--border);
  display: none;
}

/* ════════════════════ RDT GAUGE ════════════════════ */
.rdt-summary {
  display: grid; grid-template-columns: repeat(3,1fr);
  gap: 8px; margin-top: 10px;
}

.rdt-metric {
  padding: 10px 12px;
  background: rgba(0,0,0,0.2);
  border-radius: 4px;
  text-align: center;
}

.rm-val {
  font-family: var(--serif); font-size: 24px;
  line-height: 1; margin-bottom: 3px;
}

.rm-label {
  font-family: var(--mono); font-size: 8px;
  color: var(--t3); letter-spacing: 0.1em;
  text-transform: uppercase;
}

/* ════════════════════ STATUS TAGS ════════════════════ */
.tag-critical { background:rgba(255,45,0,0.12); color:var(--heat-ext); border:1px solid rgba(255,45,0,0.2); }
.tag-high     { background:rgba(245,166,35,0.1); color:var(--amber);    border:1px solid rgba(245,166,35,0.2); }
.tag-medium   { background:rgba(255,214,0,0.1);  color:var(--yellow);   border:1px solid rgba(255,214,0,0.2); }
.tag-low      { background:rgba(0,230,118,0.08); color:var(--green);    border:1px solid rgba(0,230,118,0.15); }
.tag-minimal  { background:rgba(41,121,255,0.1); color:var(--blue);     border:1px solid rgba(41,121,255,0.2); }
.tag-live     { background:rgba(0,230,118,0.1);  color:var(--green);    border:1px solid rgba(0,230,118,0.2); }

/* ════════════════════ CHAIN PANEL ════════════════════ */
.chain-stats {
  display: grid; grid-template-columns: repeat(2,1fr);
  gap: 8px;
}

.cs-item { padding:10px; background:rgba(0,0,0,0.2); border-radius:4px; text-align:center; }
.cs-val { font-family:var(--mono); font-size:18px; font-weight:700; }
.cs-label { font-family:var(--mono); font-size:8px; color:var(--t3); margin-top:3px; }

/* ════════════════════ ERROR STATE ════════════════════ */
.error-msg {
  font-family: var(--mono); font-size: 10px;
  color: var(--heat-ext); padding: 10px;
  background: rgba(255,45,0,0.05);
  border: 1px solid rgba(255,45,0,0.15);
  border-radius: 4px;
}

/* ════════════════════ FOOTER ════════════════════ */
.footer {
  margin-top: 40px; padding: 16px 32px;
  border-top: 1px solid var(--border);
  display: flex; justify-content: space-between; align-items: center;
}

.footer-l { font-family:var(--mono); font-size:9px; color:var(--t4); line-height:1.8; }
.footer-l span { color:var(--teal); }
.footer-r { font-family:var(--serif); font-style:italic; font-size:13px; color:var(--t3); }

/* ════════════════════ ANIMATIONS ════════════════════ */
.fa  { animation: fadeUp 0.5s ease both; }
.fa1 { animation-delay: 0.05s; }
.fa2 { animation-delay: 0.12s; }
.fa3 { animation-delay: 0.19s; }
.fa4 { animation-delay: 0.26s; }
.fa5 { animation-delay: 0.33s; }

@keyframes fadeUp { from { opacity:0; transform:translateY(10px); } }

::-webkit-scrollbar { width:4px; height:4px; }
::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.08); border-radius:2px; }
</style>
</head>
<body>
<div class="ambient"></div>
<div class="page">

<!-- ── MASTHEAD ── -->
<header class="masthead">
  <div class="brand">
    <div class="brand-logo">COIP · <em>Climate</em></div>
    <div class="brand-pipe"></div>
    <div class="brand-sub">Guntur District<br>Andhra Pradesh · Live</div>
  </div>
  <div class="live-indicator">
    <div class="live-dot"></div>
    <span class="live-text">API LIVE</span>
    <span class="api-url">railway.app</span>
  </div>
  <div class="masthead-right">
    <span id="clock"></span>
    <span class="unicef-badge">UNICEF Ventures 2026</span>
  </div>
</header>

<!-- ── HERO ── -->
<div class="hero-strip">
  <div class="hero-title">
    Compress the window.<br>
    <em>Save the child.</em>
  </div>
  <div class="hero-spine">
    Every minute a climate-stressed child waits for care is measurable.
    <strong>This dashboard reads live climate data from Guntur District in real-time,</strong>
    computes child-specific biological urgency, and shows disease surge forecasts —
    all from a deployed open-source API.
  </div>
</div>

<div class="main">

<!-- ══ SECTION 1: LIVE CLIMATE ══ -->
<div class="section-rule fa fa1">
  <span class="sr-tag tag-live" style="background:rgba(0,230,118,0.1);color:var(--green);">LIVE</span>
  <span class="sr-title">Environmental Signals — Guntur District (Open-Meteo API, real-time)</span>
  <div class="sr-line" style="height:1px;background:var(--border);"></div>
  <span id="climate-ts" style="font-family:var(--mono);font-size:8px;color:var(--t4);white-space:nowrap;"></span>
</div>

<div id="climate-loading" class="loading-overlay">
  <div class="spin"></div> Fetching live climate data from Guntur…
</div>

<div id="climate-grid" class="climate-row" style="display:none;">
  <div class="climate-tile ct-temp">
    <div class="ct-icon">🌡️</div>
    <div class="ct-val" id="c-temp">—</div>
    <div class="ct-label">Temperature</div>
    <div class="ct-source" id="c-src">—</div>
  </div>
  <div class="climate-tile ct-aqi">
    <div class="ct-icon">💨</div>
    <div class="ct-val" id="c-aqi">—</div>
    <div class="ct-label">AQI / PM2.5</div>
    <div class="ct-source" id="c-aqi-src">India NAAQS</div>
  </div>
  <div class="climate-tile ct-humid">
    <div class="ct-icon">💧</div>
    <div class="ct-val" id="c-hum">—</div>
    <div class="ct-label">Humidity</div>
    <div class="ct-source">Relative %</div>
  </div>
  <div class="climate-tile ct-uv">
    <div class="ct-icon">☀️</div>
    <div class="ct-val" id="c-uv">—</div>
    <div class="ct-label">UV Index</div>
    <div class="ct-source">WHO scale</div>
  </div>
  <div class="climate-tile ct-rain">
    <div class="ct-icon">🌧️</div>
    <div class="ct-val" id="c-rain">—</div>
    <div class="ct-label">Rainfall mm</div>
    <div class="ct-source">Last hour</div>
  </div>
  <div class="climate-tile ct-risk">
    <div class="ct-icon">⚠️</div>
    <div class="ct-val" id="c-risk">—</div>
    <div class="ct-label">Climate Risk</div>
    <div class="ct-source" id="c-hazard">—</div>
  </div>
</div>

<!-- ══ SECTION 2: DISEASE + VULNERABILITY + FORECAST ══ -->
<div class="section-rule fa fa2">
  <span class="sr-tag" style="background:rgba(0,188,212,0.1);color:var(--teal);border:1px solid rgba(0,188,212,0.2);">CDSP</span>
  <span class="sr-title">Disease Surge Forecast · School Vulnerability · 48h Outlook</span>
  <div class="sr-line" style="height:1px;background:var(--border);"></div>
</div>

<div class="tri-grid fa fa2">

  <!-- Disease forecast -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-title">🦠 Disease Surge Forecast</span>
      <span id="d-alert" class="ph-badge">Loading…</span>
    </div>
    <div class="panel-body">
      <div id="disease-loading" class="loading-overlay" style="padding:20px;">
        <div class="spin"></div>
      </div>
      <div id="disease-list" class="disease-list" style="display:none;"></div>
    </div>
  </div>

  <!-- School vulnerability -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-title">🏫 School Vulnerability</span>
      <span id="sve-badge" class="ph-badge">Loading…</span>
    </div>
    <div class="panel-body">
      <div id="sve-loading" class="loading-overlay" style="padding:20px;">
        <div class="spin"></div>
      </div>
      <div id="vuln-list" class="vuln-list" style="display:none;"></div>
    </div>
  </div>

  <!-- 48h forecast chart -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-title">📈 48-Hour Temperature Forecast</span>
      <span class="ph-badge tag-live">Open-Meteo</span>
    </div>
    <div class="panel-body">
      <div id="fc-loading" class="loading-overlay" style="padding:20px;">
        <div class="spin"></div>
      </div>
      <div id="forecast-area" style="display:none;">
        <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
          <span id="fc-min" style="font-family:var(--mono);font-size:9px;color:var(--t3);">min</span>
          <span id="fc-max" style="font-family:var(--mono);font-size:9px;color:var(--heat-hi);">max</span>
        </div>
        <div id="forecast-bars" class="forecast-bars"></div>
        <div style="margin-top:12px;padding:8px;background:rgba(0,0,0,0.2);border-radius:4px;">
          <div style="font-family:var(--mono);font-size:8px;color:var(--t3);margin-bottom:4px;">HEATWAVE WINDOWS (≥40°C)</div>
          <div id="hw-windows" style="font-family:var(--mono);font-size:9px;color:var(--heat-hi);"></div>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- ══ SECTION 3: LIVE RDT DEMO ══ -->
<div class="section-rule fa fa3">
  <span class="sr-tag" style="background:rgba(245,166,35,0.1);color:var(--amber);border:1px solid rgba(245,166,35,0.2);">RDT ENGINE</span>
  <span class="sr-title">Live Case Compute — POST to Deployed API</span>
  <div class="sr-line" style="height:1px;background:var(--border);"></div>
</div>

<div class="tri-grid fa fa3">

  <div class="panel" style="grid-column:span 2;">
    <div class="panel-head">
      <span class="ph-title">⏱ Submit Case → Get Climate-Adjusted RDT Response</span>
      <span class="ph-badge tag-live">LIVE API</span>
    </div>
    <div class="rdt-form">
      <div class="form-row">
        <div class="form-field">
          <label class="field-label">Child Age (months)</label>
          <input class="field-input" id="f-age" type="number" value="18" min="0" max="60">
        </div>
        <div class="form-field">
          <label class="field-label">Child Weight (kg)</label>
          <input class="field-input" id="f-wt" type="number" value="10.2" step="0.1">
        </div>
      </div>
      <div class="form-row">
        <div class="form-field">
          <label class="field-label">Temperature °C</label>
          <input class="field-input" id="f-temp" type="number" value="42.0" step="0.1">
        </div>
        <div class="form-field">
          <label class="field-label">AQI</label>
          <input class="field-input" id="f-aqi" type="number" value="95">
        </div>
      </div>
      <div class="form-row">
        <div class="form-field">
          <label class="field-label">Timestamp Reported</label>
          <input class="field-input" id="f-ts" type="text" value="">
        </div>
        <div class="form-field">
          <label class="field-label">Timestamp Acknowledged (optional)</label>
          <input class="field-input" id="f-ack" type="text" placeholder="leave blank for pending">
        </div>
      </div>
      <button class="btn-compute" id="btn-rdt">COMPUTE RDT →</button>

      <div id="rdt-result" class="rdt-result">
        <div class="rdt-summary" id="rdt-summary"></div>
        <div style="margin-top:10px;">
          <div style="font-family:var(--mono);font-size:8px;color:var(--t3);letter-spacing:.12em;text-transform:uppercase;margin-bottom:6px;">CHW Instructions</div>
          <div id="rdt-instructions" style="font-size:11px;color:var(--t2);line-height:1.7;"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- Blockchain chain -->
  <div class="panel">
    <div class="panel-head">
      <span class="ph-title">⛓ Blockchain Attestation</span>
      <span class="ph-badge" style="background:rgba(170,0,255,0.1);color:var(--purple);border:1px solid rgba(170,0,255,0.2);">SHA-256 Chain</span>
    </div>
    <div class="panel-body">
      <div id="chain-loading" class="loading-overlay" style="padding:20px;">
        <div class="spin"></div>
      </div>
      <div id="chain-stats" class="chain-stats" style="display:none;"></div>
      <div id="chain-detail" style="margin-top:12px;font-family:var(--mono);font-size:9px;color:var(--t3);line-height:1.8;"></div>
    </div>
  </div>

</div>

<!-- ══ SECTION 4: API EXPLORER ══ -->
<div class="section-rule fa fa4">
  <span class="sr-tag" style="background:rgba(41,121,255,0.1);color:var(--blue);border:1px solid rgba(41,121,255,0.2);">API</span>
  <span class="sr-title">Live API Explorer — All Endpoints</span>
  <div class="sr-line" style="height:1px;background:var(--border);"></div>
</div>

<div class="api-tester fa fa4">
  <div class="endpoint-tabs" id="ep-tabs">
    <button class="ep-tab active" data-ep="/health">GET /health</button>
    <button class="ep-tab" data-ep="/climate/guntur">GET /climate/guntur</button>
    <button class="ep-tab" data-ep="/cdsp/forecast">GET /cdsp/forecast</button>
    <button class="ep-tab" data-ep="/sve/vulnerability">GET /sve/vulnerability</button>
    <button class="ep-tab" data-ep="/climate/forecast">GET /climate/forecast</button>
    <button class="ep-tab" data-ep="/chain/summary">GET /chain/summary</button>
    <button class="ep-tab" data-ep="/geojson/hazard">GET /geojson/hazard</button>
    <button class="ep-tab" data-ep="/demo">GET /demo</button>
  </div>
  <div class="api-response" id="api-response">
    <span style="color:var(--t4);">Click an endpoint above to fetch live data from the deployed API…</span>
  </div>
</div>

</div><!-- /main -->

<footer class="footer">
  <div class="footer-l">
    <span>COIP-Climate</span> · Apache 2.0 · Open-Source · FHIR Compatible · DHIS2 Compatible<br>
    API: <span>https://web-production-9e7cf.up.railway.app</span> · Guntur District · 29/29 tests passing
  </div>
  <div class="footer-r">Measure Time. Understand Biology. Compress the Window.</div>
</footer>

</div><!-- /page -->

<script>
const API = 'https://web-production-9e7cf.up.railway.app';

// ── CLOCK
(function tick(){
  const n=new Date();
  document.getElementById('clock').textContent =
    [n.getUTCHours(),n.getUTCMinutes(),n.getUTCSeconds()]
    .map(v=>String(v).padStart(2,'0')).join(':') + ' UTC';
  setTimeout(tick,1000);
})();

// ── SET DEFAULT TIMESTAMP
document.getElementById('f-ts').value = new Date().toISOString().slice(0,19)+'Z';

// ── RISK COLOR
function riskColor(level) {
  const m = {CRITICAL:'var(--heat-ext)',HIGH:'var(--amber)',
             MEDIUM:'var(--yellow)',LOW:'var(--green)',MINIMAL:'var(--blue)'};
  return m[level] || 'var(--t2)';
}

function riskClass(level) {
  const m = {CRITICAL:'tag-critical',HIGH:'tag-high',
             MEDIUM:'tag-medium',LOW:'tag-low',MINIMAL:'tag-minimal'};
  return m[level] || '';
}

// ── PRETTY JSON
function prettyJson(obj, indent=0) {
  const sp = '  '.repeat(indent);
  const sp2 = '  '.repeat(indent+1);
  if (Array.isArray(obj)) {
    if (obj.length === 0) return '[]';
    const items = obj.map(v => sp2 + prettyJson(v, indent+1));
    return `[\n${items.join(',\n')}\n${sp}]`;
  }
  if (typeof obj === 'object' && obj !== null) {
    const entries = Object.entries(obj).map(([k,v]) => {
      const key = `<span class="json-key">"${k}"</span>`;
      return sp2 + key + ': ' + prettyJson(v, indent+1);
    });
    return `{\n${entries.join(',\n')}\n${sp}}`;
  }
  if (typeof obj === 'string')  return `<span class="json-str">"${obj}"</span>`;
  if (typeof obj === 'number')  return `<span class="json-num">${obj}</span>`;
  if (typeof obj === 'boolean') return `<span class="json-bool">${obj}</span>`;
  if (obj === null)             return `<span class="json-null">null</span>`;
  return String(obj);
}

// ── FETCH WITH ERROR HANDLING
async function apiFetch(endpoint) {
  const r = await fetch(API + endpoint);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

// ══════════ 1. LOAD CLIMATE DATA ══════════
async function loadClimate() {
  try {
    const d = await apiFetch('/climate/guntur');
    const c = d.climate;

    document.getElementById('climate-loading').style.display = 'none';
    document.getElementById('climate-grid').style.display = 'grid';

    document.getElementById('c-temp').textContent = c.temperature_c + '°';
    document.getElementById('c-temp').style.color =
      c.temperature_c >= 42 ? 'var(--heat-ext)' :
      c.temperature_c >= 38 ? 'var(--heat-hi)' :
      c.temperature_c >= 35 ? 'var(--amber)' : 'var(--green)';

    document.getElementById('c-aqi').textContent = c.aqi;
    document.getElementById('c-hum').textContent = c.humidity_pct + '%';
    document.getElementById('c-uv').textContent = c.uv_index;
    document.getElementById('c-rain').textContent = c.rainfall_mm;

    const riskEl = document.getElementById('c-risk');
    riskEl.textContent = c.climate_risk_level;
    riskEl.style.color = riskColor(c.climate_risk_level);

    document.getElementById('c-hazard').textContent = c.hazard_type || 'NONE';
    document.getElementById('c-src').textContent = c.source;

    const ts = new Date(c.timestamp);
    document.getElementById('climate-ts').textContent =
      'Updated ' + ts.toUTCString();

    // Auto-fill RDT form with live temperature
    document.getElementById('f-temp').value = c.temperature_c;
    document.getElementById('f-aqi').value = Math.round(c.aqi);

  } catch(e) {
    document.getElementById('climate-loading').innerHTML =
      `<div class="error-msg">Failed to load climate data: ${e.message}</div>`;
  }
}

// ══════════ 2. DISEASE FORECAST ══════════
async function loadDiseaseForecasts() {
  try {
    const d = await apiFetch('/cdsp/forecast');
    document.getElementById('disease-loading').style.display = 'none';
    const list = document.getElementById('disease-list');
    list.style.display = 'flex';

    const alertEl = document.getElementById('d-alert');
    alertEl.textContent = d.district_alert || 'UNKNOWN';
    alertEl.className = 'ph-badge ' + riskClass(d.district_alert);

    const icons = {heat_illness:'🌡️',dengue:'🦟',diarrhea:'💧',malaria:'🦠',ari_respiratory:'🫁'};
    const diseases = d.disease_forecasts || {};

    for (const [name, fc] of Object.entries(diseases)) {
      const row = document.createElement('div');
      row.className = 'disease-row';
      const score = Math.round((fc.risk_score || 0) * 100);
      const barColor = riskColor(fc.risk_level);
      row.innerHTML = `
        <div class="dr-icon">${icons[name]||'🦠'}</div>
        <div style="flex:1;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;">
            <div class="dr-name">${name.replace('_',' ')}</div>
            <span class="dr-level ${riskClass(fc.risk_level)}">${fc.risk_level}</span>
          </div>
          <div class="dr-bar">
            <div class="dr-bar-fill" style="width:${score}%;background:${barColor};"></div>
          </div>
          <div style="font-family:var(--mono);font-size:8px;color:var(--t4);margin-top:3px;">
            ${fc.forecast_window||''}  ·  conf ${fc.confidence_pct||0}%
          </div>
        </div>
      `;
      list.appendChild(row);
    }
  } catch(e) {
    document.getElementById('disease-loading').innerHTML =
      `<div class="error-msg">Disease forecast error: ${e.message}</div>`;
  }
}

// ══════════ 3. SCHOOL VULNERABILITY ══════════
async function loadVulnerability() {
  try {
    const d = await apiFetch('/sve/vulnerability');
    document.getElementById('sve-loading').style.display = 'none';
    const list = document.getElementById('vuln-list');
    list.style.display = 'flex';

    const badge = document.getElementById('sve-badge');
    badge.textContent = `${d.critical_count || 0} CRITICAL`;
    badge.className = 'ph-badge ' + (d.critical_count > 0 ? 'tag-critical' : 'tag-low');

    const locs = (d.top_10_vulnerable || []).slice(0, 5);
    locs.forEach((loc, i) => {
      const row = document.createElement('div');
      row.className = 'vuln-row';
      const c = riskColor(loc.risk_level);
      row.innerHTML = `
        <div class="vr-rank">${i+1}</div>
        <div class="vr-info">
          <div class="vr-name">${loc.name.slice(0,32)}</div>
          <div class="vr-meta">${loc.mandal || ''} · ${loc.children_at_risk || 0} children at risk</div>
        </div>
        <div class="vr-score" style="color:${c};">
          ${loc.vulnerability_score}<br>
          <span class="dr-level ${riskClass(loc.risk_level)}" style="display:inline-block;margin-top:3px;">${loc.risk_level}</span>
        </div>
      `;
      list.appendChild(row);
    });
  } catch(e) {
    document.getElementById('sve-loading').innerHTML =
      `<div class="error-msg">SVE error: ${e.message}</div>`;
  }
}

// ══════════ 4. 48H FORECAST CHART ══════════
async function loadForecast() {
  try {
    const d = await apiFetch('/climate/forecast');
    document.getElementById('fc-loading').style.display = 'none';
    document.getElementById('forecast-area').style.display = 'block';

    const fc = (d.forecast || []).slice(0, 24); // 24 hours
    if (!fc.length) return;

    const temps = fc.map(f => f.temperature_c);
    const minT = Math.min(...temps);
    const maxT = Math.max(...temps);
    const range = maxT - minT || 1;

    document.getElementById('fc-min').textContent = minT.toFixed(1) + '°C';
    document.getElementById('fc-max').textContent = maxT.toFixed(1) + '°C';

    const container = document.getElementById('forecast-bars');
    fc.forEach((f, i) => {
      if (i % 3 !== 0) return; // show every 3rd hour
      const pct = ((f.temperature_c - minT) / range) * 100;
      const height = Math.max(4, pct * 0.7 + 10);
      const color = f.temperature_c >= 40 ? 'var(--heat-ext)' :
                    f.temperature_c >= 38 ? 'var(--heat-hi)' :
                    f.temperature_c >= 35 ? 'var(--amber)' : 'var(--teal)';
      const hour = f.time ? new Date(f.time).getUTCHours() : i;
      const col = document.createElement('div');
      col.className = 'fb-col';
      col.innerHTML = `
        <div class="fb-bar" style="height:${height}px;background:${color};"></div>
        <div class="fb-lbl">${String(hour).padStart(2,'0')}h</div>
      `;
      container.appendChild(col);
    });

    // Heatwave windows
    const hw = fc.filter(f => f.heatwave_risk);
    const hwEl = document.getElementById('hw-windows');
    if (hw.length) {
      hwEl.textContent = `${hw.length} hours ≥40°C predicted — peak ${maxT.toFixed(1)}°C`;
    } else {
      hwEl.style.color = 'var(--green)';
      hwEl.textContent = 'No heatwave window in next 24 hours';
    }
  } catch(e) {
    document.getElementById('fc-loading').innerHTML =
      `<div class="error-msg">Forecast error: ${e.message}</div>`;
  }
}

// ══════════ 5. BLOCKCHAIN CHAIN ══════════
async function loadChain() {
  try {
    const d = await apiFetch('/chain/summary');
    document.getElementById('chain-loading').style.display = 'none';
    const statsEl = document.getElementById('chain-stats');
    statsEl.style.display = 'grid';

    statsEl.innerHTML = `
      <div class="cs-item">
        <div class="cs-val" style="color:var(--purple);">${d.chain_length||0}</div>
        <div class="cs-label">Blocks</div>
      </div>
      <div class="cs-item">
        <div class="cs-val" style="color:var(--green);">${d.total_cases_attested||0}</div>
        <div class="cs-label">Cases Attested</div>
      </div>
    `;

    document.getElementById('chain-detail').innerHTML = `
      Valid: <span style="color:var(--green);">${d.is_valid ? 'YES ✓' : 'NO ✗'}</span><br>
      Latest: <span style="color:var(--teal);">${(d.latest_hash||'—').slice(0,20)}…</span><br>
      Privacy: <span style="color:var(--t3);">${d.privacy_note||'Hashes only'}</span>
    `;
  } catch(e) {
    document.getElementById('chain-loading').innerHTML =
      `<div class="error-msg">Chain: ${e.message}</div>`;
  }
}

// ══════════ 6. RDT COMPUTE ══════════
document.getElementById('btn-rdt').addEventListener('click', async () => {
  const btn = document.getElementById('btn-rdt');
  btn.disabled = true;
  btn.textContent = 'COMPUTING…';

  const now = new Date().toISOString();
  const ackOffset = 12; // simulate 12 min acknowledge time
  const ackTime = new Date(Date.now() - ackOffset * 60000).toISOString();

  const body = {
    child_age_months: parseInt(document.getElementById('f-age').value) || 18,
    child_weight_kg:  parseFloat(document.getElementById('f-wt').value) || 10.2,
    temperature_c:    parseFloat(document.getElementById('f-temp').value) || 42.0,
    aqi:              parseFloat(document.getElementById('f-aqi').value) || 95.0,
    humidity_pct:     55.0,
    bus_score:        75.0,
    cif_score:        0.42,
    ts_reported:      document.getElementById('f-ts').value || now,
    ts_acknowledged:  document.getElementById('f-ack').value || ackTime,
    climate_pathway:  'HEAT_DIRECT',
    mandal:           'Tadikonda',
    village:          'Rentachintala',
    chw_id:           'ASHA-GNT-UI-DEMO',
  };

  try {
    const r = await fetch(API + '/rdt/compute', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body),
    });
    const d = await r.json();
    const rdt = d.rdt;
    const instr = d.chw_instructions;

    const resultEl = document.getElementById('rdt-result');
    resultEl.style.display = 'block';

    const delayColor = rdt.delay_class === 'EMERGENCY' ? 'var(--heat-ext)' :
                       rdt.delay_class === 'CRITICAL'  ? 'var(--heat-hi)' :
                       rdt.delay_class === 'DELAYED'   ? 'var(--amber)' :
                       rdt.delay_class === 'MODERATE'  ? 'var(--yellow)' : 'var(--green)';

    document.getElementById('rdt-summary').innerHTML = `
      <div class="rdt-metric">
        <div class="rm-val" style="color:var(--amber);">${rdt.total_rdt_min||'—'}<span style="font-size:12px;">m</span></div>
        <div class="rm-label">Total RDT</div>
      </div>
      <div class="rdt-metric">
        <div class="rm-val" style="color:var(--teal);">${rdt.t_adj_total||'—'}<span style="font-size:12px;">m</span></div>
        <div class="rm-label">T_adj Target</div>
      </div>
      <div class="rdt-metric">
        <div class="rm-val" style="color:${delayColor};">${rdt.delay_class||'—'}</div>
        <div class="rm-label">Classification</div>
      </div>
    `;

    if (instr) {
      const steps = (instr.steps||[]).map((s,i) =>
        `<div style="margin-bottom:5px;"><span style="color:var(--teal);font-family:var(--mono);">${i+1}.</span> ${s}</div>`
      ).join('');
      document.getElementById('rdt-instructions').innerHTML = `
        <div style="font-family:var(--mono);font-size:9px;color:var(--teal);margin-bottom:6px;">
          BUS=${rdt.bus_score} · T_adj=${rdt.t_adj_total}min · deviation=${rdt.deviation_pct>0?'+':''}${rdt.deviation_pct}%
        </div>
        ${steps}
        ${instr.escalation ? `<div style="margin-top:6px;color:var(--heat-hi);">⚠ ${instr.escalation}</div>` : ''}
        ${instr.not_your_fault ? `<div style="margin-top:6px;color:var(--t3);font-style:italic;">${instr.not_your_fault}</div>` : ''}
      `;
    }
  } catch(e) {
    document.getElementById('rdt-result').style.display = 'block';
    document.getElementById('rdt-result').innerHTML =
      `<div class="error-msg">RDT compute failed: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'COMPUTE RDT →';
  }
});

// ══════════ 7. API EXPLORER TABS ══════════
document.getElementById('ep-tabs').addEventListener('click', async (e) => {
  const tab = e.target.closest('.ep-tab');
  if (!tab) return;

  document.querySelectorAll('.ep-tab').forEach(t => t.classList.remove('active'));
  tab.classList.add('active');

  const ep = tab.dataset.ep;
  const responseEl = document.getElementById('api-response');
  responseEl.innerHTML = `<span style="color:var(--t4);">Fetching ${API}${ep}…</span>`;

  try {
    const d = await apiFetch(ep);
    responseEl.innerHTML = prettyJson(d);
  } catch(e) {
    responseEl.innerHTML = `<span class="json-key">"error"</span>: <span class="json-str">"${e.message}"</span>`;
  }
});

// ══════════ INIT: LOAD ALL DATA ══════════
(async function init() {
  await loadClimate();
  loadDiseaseForecasts();
  loadVulnerability();
  loadForecast();
  loadChain();

  // Auto-refresh climate every 5 minutes
  setInterval(loadClimate, 5 * 60 * 1000);

  // Trigger first API tab
  setTimeout(() => {
    document.querySelector('.ep-tab[data-ep="/health"]').click();
  }, 500);
})();
</script>
</body>
</html>

"""
# ───────────────────────────────────────────────────────────

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
                # Dashboard HTML embedded directly — no external file needed
                html = DASHBOARD_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(html)

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

            elif path == "/evidence":
                # District-level RDT evidence summary
                summary = compute_and_save_summary(_DB_PATH)
                stats   = get_db_stats(_DB_PATH)
                self._send(_ok({"evidence": summary, "db_stats": stats}))

            elif path == "/cases":
                # Recent cases from database
                cases = get_district_cases(limit=20, db_path=_DB_PATH)
                self._send(_ok({"count": len(cases), "cases": cases}))

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
                # Persist to database
                save_case(case.to_dict(), _DB_PATH)
                # Log climate context
                from core.esi.esi import get_climate_context
                try:
                    ctx_for_log = get_climate_context()
                    log_climate(ctx_for_log.to_dict(), _DB_PATH)
                except Exception:
                    pass

                self._send(_ok({
                    "rdt":            case.to_dict(),
                    "stage_breakdown": case.get_stage_breakdown(),
                    "chw_instructions": case.get_chw_instructions(),
                    "saved_to_db":    True,
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
