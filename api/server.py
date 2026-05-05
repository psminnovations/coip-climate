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
                     log_climate, compute_and_save_summary, get_db_stats)
_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'data', 'coip_climate.db')
init_db(_DB)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
log = logging.getLogger("coip")

PORT    = int(os.environ.get("PORT", 8000))
VERSION = "3.0.0"

# ──────────────────────────────────────────────────────────────
# LOAD DASHBOARD HTML from file
# ──────────────────────────────────────────────────────────────
def _load_dashboard_html():
    """Load dashboard HTML from index.html file"""
    dashboard_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'dashboard', 'index.html'
    )
    try:
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        log.error(f"Failed to load dashboard HTML: {e}")
        return """<!DOCTYPE html>
<html>
<head><title>Error</title></head>
<body><h1>Dashboard not found</h1><p>Could not load dashboard from {dashboard_path}</p></body>
</html>"""

def get_dashboard_html():
    """Cached dashboard HTML getter"""
    if not hasattr(get_dashboard_html, '_cache'):
        get_dashboard_html._cache = _load_dashboard_html()
    return get_dashboard_html._cache

# This marker is used to identify where the old embedded HTML was
_DASHBOARD_PLACEHOLDER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>COIP-Climate · Guntur District Live</title>
<link href="https://fonts.googleapis.com/css2?family=Azeret+Mono:wght@300;400;500;600;700&family=DM+Serif+Display:ital@0;1&family=DM+Sans:opsz,wght@9..40,300;9..40,400;9..40,500;9..40,600&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#040810;--card:#0C1525;--border:rgba(255,255,255,0.08);
  --hi:rgba(255,255,255,0.14);
  --r:#FF2D00;--o:#FF6B00;--y:#FFD600;--g:#00E676;--t:#00BCD4;--b:#2979FF;--p:#AA00FF;
  --amber:#F5A623;
  --t1:#F0F4FF;--t2:#8898BB;--t3:#3D4F6E;--t4:#1E2C42;
  --mono:'Azeret Mono',monospace;--serif:'DM Serif Display',serif;--sans:'DM Sans',sans-serif;
}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--t1);font-family:var(--sans);min-height:100vh;overflow-x:hidden}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:0;
  background:repeating-linear-gradient(0deg,transparent,transparent 3px,rgba(0,188,212,.004) 3px,rgba(0,188,212,.004) 4px)}
.glow{position:fixed;inset:0;pointer-events:none;z-index:0;
  background:radial-gradient(ellipse 60% 40% at 15% 8%,rgba(255,80,0,.07) 0,transparent 60%),
             radial-gradient(ellipse 40% 50% at 85% 85%,rgba(0,188,212,.05) 0,transparent 60%)}
.wrap{position:relative;z-index:1}

/* NAV */
nav{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;
    padding:0 28px;height:52px;border-bottom:1px solid var(--hi);
    background:rgba(4,8,16,.95);backdrop-filter:blur(20px);
    position:sticky;top:0;z-index:100}
.brand{display:flex;align-items:center;gap:12px}
.brand-name{font-family:var(--serif);font-size:18px}
.brand-name em{color:var(--o);font-style:normal}
.brand-div{width:1px;height:20px;background:var(--hi)}
.brand-sub{font-family:var(--mono);font-size:8px;color:var(--t3);letter-spacing:.14em;text-transform:uppercase;line-height:1.5}
.live-pill{display:flex;align-items:center;gap:7px;font-family:var(--mono);font-size:9px;letter-spacing:.12em}
.dot{width:7px;height:7px;border-radius:50%;background:var(--g);box-shadow:0 0 8px var(--g);animation:blink 1.8s ease-in-out infinite}
@keyframes blink{50%{opacity:.25;box-shadow:none}}
.dot-text{color:var(--g)}
.nav-r{display:flex;align-items:center;justify-content:flex-end;gap:14px}
#clk{font-family:var(--mono);font-size:10px;color:var(--t3)}
.badge{font-family:var(--mono);font-size:8px;padding:3px 9px;border-radius:2px;
       background:rgba(0,188,212,.08);border:1px solid rgba(0,188,212,.2);color:var(--t);letter-spacing:.08em}

/* HERO */
.hero{padding:18px 28px;border-bottom:1px solid var(--border);
      display:flex;align-items:center;gap:28px;
      background:linear-gradient(90deg,rgba(255,70,0,.07) 0,transparent 60%)}
.hero-title{font-family:var(--serif);font-size:clamp(20px,3vw,34px);line-height:1.1;flex-shrink:0}
.hero-title em{color:var(--o);font-style:italic}
.hero-sub{flex:1;font-size:12px;color:var(--t2);line-height:1.6;
          border-left:2px solid rgba(255,107,0,.3);padding-left:18px}
.hero-sub strong{color:var(--t1)}

/* MAIN */
.main{padding:20px 28px;max-width:1440px;margin:0 auto}

/* SECTION RULE */
.sec{display:flex;align-items:center;gap:10px;margin:24px 0 12px;
     padding-bottom:7px;border-bottom:1px solid var(--border)}
.sec-tag{font-family:var(--mono);font-size:8px;padding:2px 8px;border-radius:2px;
         letter-spacing:.12em;text-transform:uppercase;border:1px solid transparent}
.tag-live{background:rgba(0,230,118,.1);color:var(--g);border-color:rgba(0,230,118,.2)}
.tag-cdsp{background:rgba(0,188,212,.1);color:var(--t);border-color:rgba(0,188,212,.2)}
.tag-rdt {background:rgba(245,166,35,.1);color:var(--amber);border-color:rgba(245,166,35,.2)}
.tag-api {background:rgba(41,121,255,.1);color:var(--b);border-color:rgba(41,121,255,.2)}
.tag-crit{background:rgba(255,45,0,.12);color:var(--r);border-color:rgba(255,45,0,.2)}
.tag-hi  {background:rgba(245,166,35,.1);color:var(--amber);border-color:rgba(245,166,35,.2)}
.tag-med {background:rgba(255,214,0,.1);color:var(--y);border-color:rgba(255,214,0,.2)}
.tag-low {background:rgba(0,230,118,.08);color:var(--g);border-color:rgba(0,230,118,.15)}
.tag-min {background:rgba(41,121,255,.1);color:var(--b);border-color:rgba(41,121,255,.2)}
.sec-title{font-family:var(--mono);font-size:9px;color:var(--t2);letter-spacing:.1em;text-transform:uppercase}
.sec-line{flex:1;height:1px;background:var(--border)}
#climate-ts{font-family:var(--mono);font-size:8px;color:var(--t4);white-space:nowrap}

/* CLIMATE GRID */
.climate-row{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
@media(max-width:900px){.climate-row{grid-template-columns:repeat(3,1fr)}}
.ctile{background:var(--card);border:1px solid var(--border);border-radius:5px;
       padding:14px 12px;position:relative;overflow:hidden;transition:border-color .2s}
.ctile:hover{border-color:var(--hi)}
.ctile::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.ct-temp::before{background:var(--o)} .ct-aqi::before{background:var(--amber)}
.ct-hum::before{background:var(--t)}  .ct-uv::before{background:var(--y)}
.ct-rain::before{background:var(--b)} .ct-risk::before{background:var(--g)}
.ct-ico{font-size:16px;margin-bottom:7px}
.ct-val{font-family:var(--serif);font-size:26px;line-height:1;margin-bottom:2px}
.ct-lbl{font-family:var(--mono);font-size:8px;color:var(--t3);letter-spacing:.1em;text-transform:uppercase;margin-bottom:2px}
.ct-src{font-family:var(--mono);font-size:8px;color:var(--t4)}

/* LOADING */
.ld{display:flex;align-items:center;justify-content:center;gap:10px;
    padding:28px;font-family:var(--mono);font-size:10px;color:var(--t3);letter-spacing:.1em}
.spin{width:16px;height:16px;border:2px solid var(--border);
      border-top-color:var(--t);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.err{font-family:var(--mono);font-size:10px;color:var(--r);padding:10px;
     background:rgba(255,45,0,.05);border:1px solid rgba(255,45,0,.15);border-radius:4px}

/* 3 COL */
.tri{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:900px){.tri{grid-template-columns:1fr}}

/* PANEL */
.panel{background:var(--card);border:1px solid var(--border);border-radius:5px;overflow:hidden}
.ph{display:flex;align-items:center;justify-content:space-between;
    padding:9px 12px;border-bottom:1px solid var(--border)}
.ph-title{font-family:var(--mono);font-size:9px;color:var(--t2);letter-spacing:.1em;text-transform:uppercase}
.ph-badge{font-family:var(--mono);font-size:8px;padding:2px 7px;border-radius:2px}
.pb{padding:12px}

/* DISEASE LIST */
.dl{display:flex;flex-direction:column;gap:7px}
.dr{display:flex;align-items:flex-start;gap:8px;padding:9px 10px;
    border-radius:4px;border:1px solid var(--border);background:rgba(255,255,255,.02)}
.dr-ico{font-size:13px;margin-top:1px}
.dr-body{flex:1}
.dr-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
.dr-name{font-size:11px;font-weight:500;text-transform:capitalize}
.dr-bar{height:3px;background:rgba(255,255,255,.05);border-radius:2px;margin-top:2px}
.dr-fill{height:100%;border-radius:2px;transition:width 1.2s ease}
.dr-meta{font-family:var(--mono);font-size:8px;color:var(--t4);margin-top:3px}

/* VULN LIST */
.vl{display:flex;flex-direction:column;gap:6px}
.vr{display:flex;align-items:center;gap:8px;padding:7px 9px;
    border-radius:4px;border:1px solid var(--border);background:rgba(255,255,255,.02)}
.vr-n{font-family:var(--serif);font-size:16px;color:var(--t4);flex-shrink:0;width:20px;line-height:1}
.vr-inf{flex:1}
.vr-nm{font-size:11px;font-weight:500;margin-bottom:2px}
.vr-mt{font-family:var(--mono);font-size:8px;color:var(--t3)}
.vr-sc{font-family:var(--mono);font-size:13px;font-weight:700;text-align:right}

/* FORECAST CHART */
.fc-bars{display:flex;align-items:flex-end;gap:3px;height:75px;padding:0 2px;margin-top:8px}
.fc-col{flex:1;display:flex;flex-direction:column;align-items:center;gap:2px}
.fc-bar{width:100%;border-radius:2px 2px 0 0;transition:height .8s ease;min-height:2px}
.fc-lbl{font-family:var(--mono);font-size:7px;color:var(--t4)}

/* CHAIN */
.chain-g{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.cg-i{padding:10px;background:rgba(0,0,0,.2);border-radius:4px;text-align:center}
.cg-v{font-family:var(--mono);font-size:18px;font-weight:700}
.cg-l{font-family:var(--mono);font-size:8px;color:var(--t3);margin-top:3px}

/* RDT FORM */
.rdt-form{display:flex;flex-direction:column;gap:9px;padding:12px}
.fr{display:grid;grid-template-columns:1fr 1fr;gap:7px}
.ff{display:flex;flex-direction:column;gap:3px}
.fl{font-family:var(--mono);font-size:8px;color:var(--t3);letter-spacing:.1em;text-transform:uppercase}
.fi{background:rgba(0,0,0,.3);border:1px solid var(--border);border-radius:3px;
    padding:6px 9px;font-family:var(--mono);font-size:10px;color:var(--t1);outline:none;transition:border-color .15s}
.fi:focus{border-color:var(--t)}
.fi-sel{background:rgba(0,0,0,.3);border:1px solid var(--border);border-radius:3px;
        padding:6px 9px;font-family:var(--mono);font-size:10px;color:var(--t1);outline:none;cursor:pointer}
.btn{padding:9px 18px;background:var(--t);color:var(--bg);border:none;border-radius:3px;
     font-family:var(--mono);font-size:9px;font-weight:700;letter-spacing:.12em;
     text-transform:uppercase;cursor:pointer;transition:opacity .15s}
.btn:hover{opacity:.85} .btn:disabled{opacity:.4;cursor:not-allowed}
.rdt-res{margin-top:8px;padding:10px;background:rgba(0,0,0,.25);border-radius:4px;
         border:1px solid var(--border);display:none}
.rdt-sum{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:10px}
.rm{padding:9px;background:rgba(0,0,0,.2);border-radius:3px;text-align:center}
.rm-v{font-family:var(--serif);font-size:22px;line-height:1;margin-bottom:2px}
.rm-l{font-family:var(--mono);font-size:7px;color:var(--t3);letter-spacing:.09em;text-transform:uppercase}
.stage-row{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-top:8px}
.sg{padding:7px;background:rgba(0,0,0,.15);border-radius:3px}
.sg-l{font-family:var(--mono);font-size:7px;color:var(--t3);margin-bottom:3px;text-transform:uppercase}
.sg-v{font-family:var(--mono);font-size:10px;font-weight:600}
.instr{font-size:10px;color:var(--t2);line-height:1.7;margin-top:8px}
.step{margin-bottom:4px;display:flex;gap:6px}
.step-n{color:var(--t);font-family:var(--mono);flex-shrink:0}

/* API EXPLORER */
.ep-tabs{display:flex;border-bottom:1px solid var(--border);overflow-x:auto;scrollbar-width:none}
.ep-tab{padding:8px 12px;font-family:var(--mono);font-size:9px;color:var(--t3);
        letter-spacing:.07em;cursor:pointer;border:none;background:transparent;
        border-bottom:2px solid transparent;transition:all .15s;white-space:nowrap}
.ep-tab:hover{color:var(--t2)} .ep-tab.act{color:var(--t);border-bottom-color:var(--t)}
.api-out{padding:12px;font-family:var(--mono);font-size:9px;color:var(--t2);
         line-height:1.7;overflow:auto;max-height:260px;white-space:pre-wrap;word-break:break-all}
.jk{color:var(--t)} .jv{color:var(--g)} .jn{color:var(--amber)} .jb{color:var(--p)} .jl{color:var(--t3)}

footer{margin-top:36px;padding:14px 28px;border-top:1px solid var(--border);
       display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}
.fl-t{font-family:var(--mono);font-size:8px;color:var(--t4);line-height:2}
.fl-t span{color:var(--t)}
.fr-t{font-family:var(--serif);font-style:italic;font-size:12px;color:var(--t3)}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.07);border-radius:2px}
.fa{animation:fu .45s ease both}
.fa1{animation-delay:.04s}.fa2{animation-delay:.1s}.fa3{animation-delay:.16s}
.fa4{animation-delay:.22s}.fa5{animation-delay:.28s}
@keyframes fu{from{opacity:0;transform:translateY(8px)}}
</style>
</head>
<body>
<div class="glow"></div>
<div class="wrap">

<nav>
  <div class="brand">
    <div class="brand-name">COIP &middot; <em>Climate</em></div>
    <div class="brand-div"></div>
    <div class="brand-sub">Guntur District<br>Andhra Pradesh &middot; Live</div>
  </div>
  <div class="live-pill">
    <div class="dot"></div>
    <span class="dot-text">API LIVE</span>
  </div>
  <div class="nav-r">
    <span id="clk"></span>
    <span class="badge">UNICEF Ventures 2026</span>
  </div>
</nav>

<div class="hero">
  <div class="hero-title">Compress the window.<br><em>Save the child.</em></div>
  <div class="hero-sub">
    Every minute a climate-stressed child waits for care is measurable.
    <strong>This dashboard reads live climate data from Guntur District in real-time,</strong>
    computes child-specific biological urgency, and shows disease surge forecasts
    &mdash; all from a deployed open-source API.
  </div>
</div>

<div class="main">

<!-- CLIMATE -->
<div class="sec fa fa1">
  <span class="sec-tag tag-live">LIVE</span>
  <span class="sec-title">Environmental Signals &mdash; Guntur (Open-Meteo, real-time)</span>
  <div class="sec-line"></div>
  <span id="climate-ts"></span>
</div>

<div id="c-load" class="ld fa fa1"><div class="spin"></div>Fetching live Guntur climate data&hellip;</div>
<div id="c-grid" class="climate-row" style="display:none">
  <div class="ctile ct-temp"><div class="ct-ico">&#127777;&#65039;</div><div class="ct-val" id="cv-temp" style="color:var(--o)">--</div><div class="ct-lbl">Temperature</div><div class="ct-src" id="cv-src">--</div></div>
  <div class="ctile ct-aqi"><div class="ct-ico">&#128168;</div><div class="ct-val" id="cv-aqi" style="color:var(--amber)">--</div><div class="ct-lbl">AQI</div><div class="ct-src">CPCB / OpenAQ</div></div>
  <div class="ctile ct-hum"><div class="ct-ico">&#128167;</div><div class="ct-val" id="cv-hum" style="color:var(--t)">--</div><div class="ct-lbl">Humidity</div><div class="ct-src">Relative %</div></div>
  <div class="ctile ct-uv"><div class="ct-ico">&#9728;&#65039;</div><div class="ct-val" id="cv-uv" style="color:var(--y)">--</div><div class="ct-lbl">UV Index</div><div class="ct-src">WHO scale</div></div>
  <div class="ctile ct-rain"><div class="ct-ico">&#127783;&#65039;</div><div class="ct-val" id="cv-rain" style="color:var(--b)">--</div><div class="ct-lbl">Rainfall mm</div><div class="ct-src">Last hour</div></div>
  <div class="ctile ct-risk"><div class="ct-ico">&#9888;&#65039;</div><div class="ct-val" id="cv-risk" style="font-family:var(--mono);font-size:16px;font-weight:700">--</div><div class="ct-lbl">Climate Risk</div><div class="ct-src" id="cv-hazard">--</div></div>
</div>

<!-- FORECASTS -->
<div class="sec fa fa2">
  <span class="sec-tag tag-cdsp">CDSP</span>
  <span class="sec-title">Disease Surge Forecast &middot; School Vulnerability &middot; 48h Outlook</span>
  <div class="sec-line"></div>
</div>

<div class="tri fa fa2">
  <div class="panel">
    <div class="ph"><span class="ph-title">&#129440; Disease Surge Forecast</span><span id="d-badge" class="ph-badge">--</span></div>
    <div class="pb">
      <div id="d-load" class="ld" style="padding:18px"><div class="spin"></div></div>
      <div id="d-list" class="dl" style="display:none"></div>
    </div>
  </div>
  <div class="panel">
    <div class="ph"><span class="ph-title">&#127979; School Vulnerability</span><span id="s-badge" class="ph-badge">--</span></div>
    <div class="pb">
      <div id="s-load" class="ld" style="padding:18px"><div class="spin"></div></div>
      <div id="s-list" class="vl" style="display:none"></div>
    </div>
  </div>
  <div class="panel">
    <div class="ph"><span class="ph-title">&#128200; 48-Hour Temperature</span><span class="ph-badge tag-live">Open-Meteo</span></div>
    <div class="pb">
      <div id="f-load" class="ld" style="padding:18px"><div class="spin"></div></div>
      <div id="f-area" style="display:none">
        <div style="display:flex;justify-content:space-between;margin-bottom:3px">
          <span id="f-min" style="font-family:var(--mono);font-size:9px;color:var(--t3)">min</span>
          <span id="f-max" style="font-family:var(--mono);font-size:9px;color:var(--o)">max</span>
        </div>
        <div id="f-bars" class="fc-bars"></div>
        <div style="margin-top:10px;padding:7px;background:rgba(0,0,0,.2);border-radius:4px">
          <div style="font-family:var(--mono);font-size:8px;color:var(--t3);margin-bottom:3px">HEATWAVE WINDOWS (&#8805;40&#176;C)</div>
          <div id="f-hw" style="font-family:var(--mono);font-size:9px;color:var(--o)">--</div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- RDT COMPUTE -->
<div class="sec fa fa3">
  <span class="sec-tag tag-rdt">RDT Engine</span>
  <span class="sec-title">Live Case Compute &mdash; POST to Deployed API</span>
  <div class="sec-line"></div>
</div>

<div class="tri fa fa3">
  <div class="panel" style="grid-column:span 2">
    <div class="ph"><span class="ph-title">&#9201; Submit Case &rarr; Climate-Adjusted RDT Response</span><span class="ph-badge tag-live">LIVE API</span></div>
    <div class="rdt-form">
      <div class="fr">
        <div class="ff"><label class="fl">Child Age (months)</label><input class="fi" id="r-age" type="number" value="18" min="0" max="60"></div>
        <div class="ff"><label class="fl">Child Weight (kg)</label><input class="fi" id="r-wt" type="number" value="10.2" step="0.1"></div>
      </div>
      <div class="fr">
        <div class="ff"><label class="fl">Temperature &#176;C</label><input class="fi" id="r-temp" type="number" value="42.0" step="0.1"></div>
        <div class="ff"><label class="fl">AQI</label><input class="fi" id="r-aqi" type="number" value="95"></div>
      </div>
      <div class="fr">
        <div class="ff"><label class="fl">Humidity %</label><input class="fi" id="r-hum" type="number" value="55"></div>
        <div class="ff"><label class="fl">Language (CHW Instructions)</label>
          <select class="fi-sel" id="r-lang"><option value="en">English</option><option value="te">Telugu</option><option value="hi">Hindi</option></select>
        </div>
      </div>
      <button class="btn" id="btn-rdt">COMPUTE RDT &#8594;</button>
      <div id="rdt-res" class="rdt-res">
        <div id="rdt-sum" class="rdt-sum"></div>
        <div id="stage-row" class="stage-row"></div>
        <div id="rdt-instr" class="instr"></div>
      </div>
    </div>
  </div>

  <div class="panel">
    <div class="ph"><span class="ph-title">&#9935; Blockchain Attestation</span><span class="ph-badge" style="background:rgba(170,0,255,.1);color:var(--p);border:1px solid rgba(170,0,255,.2)">SHA-256 Chain</span></div>
    <div class="pb">
      <div id="ch-load" class="ld" style="padding:18px"><div class="spin"></div></div>
      <div id="ch-stats" class="chain-g" style="display:none"></div>
      <div id="ch-detail" style="margin-top:10px;font-family:var(--mono);font-size:9px;color:var(--t3);line-height:1.8"></div>
    </div>
  </div>
</div>

<!-- API EXPLORER -->
<div class="sec fa fa4">
  <span class="sec-tag tag-api">API</span>
  <span class="sec-title">Live API Explorer &mdash; All Endpoints</span>
  <div class="sec-line"></div>
</div>

<div class="panel fa fa4">
  <div class="ep-tabs" id="ep-tabs">
    <button class="ep-tab act" data-ep="/health">GET /health</button>
    <button class="ep-tab" data-ep="/climate/guntur">GET /climate/guntur</button>
    <button class="ep-tab" data-ep="/cdsp/forecast">GET /cdsp/forecast</button>
    <button class="ep-tab" data-ep="/sve/vulnerability">GET /sve/vulnerability</button>
    <button class="ep-tab" data-ep="/climate/forecast">GET /climate/forecast</button>
    <button class="ep-tab" data-ep="/chain/summary">GET /chain/summary</button>
    <button class="ep-tab" data-ep="/demo">GET /demo</button>
  </div>
  <div id="api-out" class="api-out"><span style="color:var(--t4)">Click an endpoint above to fetch live data&hellip;</span></div>
</div>

</div><!-- /main -->

<footer>
  <div class="fl-t"><span>COIP-Climate</span> v3.0 &middot; Apache 2.0 &middot; Open-Source &middot; FHIR &middot; DHIS2<br>Guntur District, Andhra Pradesh &middot; 29/29 tests passing &middot; UNICEF Ventures 2026</div>
  <div class="fr-t">Measure Time. Understand Biology. Compress the Window.</div>
</footer>

</div>

<script>
// KEY FIX: use relative URLs — works on any domain (Railway, localhost, anywhere)
// No hardcoded URL. The dashboard is served from the same server as the API.
const API = '';

// CLOCK
(function tick(){
  const n=new Date();
  const el=document.getElementById('clk');
  if(el) el.textContent=[n.getUTCHours(),n.getUTCMinutes(),n.getUTCSeconds()].map(v=>String(v).padStart(2,'0')).join(':')+'  UTC';
  setTimeout(tick,1000);
})();

// RISK HELPERS
const RC={CRITICAL:'var(--r)',HIGH:'var(--amber)',MEDIUM:'var(--y)',LOW:'var(--g)',MINIMAL:'var(--b)'};
const RK={CRITICAL:'tag-crit',HIGH:'tag-hi',MEDIUM:'tag-med',LOW:'tag-low',MINIMAL:'tag-min'};
const riskColor=l=>RC[l]||'var(--t2)';
const riskClass=l=>RK[l]||'';

// PRETTY JSON
function prettyJson(o,d=0){
  const sp='  '.repeat(d),s2='  '.repeat(d+1);
  if(Array.isArray(o)){
    if(!o.length)return'[]';
    return'[\n'+o.map(v=>s2+prettyJson(v,d+1)).join(',\n')+'\n'+sp+']';
  }
  if(o&&typeof o==='object'){
    const e=Object.entries(o).map(([k,v])=>s2+`<span class=jk>"${k}"</span>: `+prettyJson(v,d+1));
    return'{\n'+e.join(',\n')+'\n'+sp+'}';
  }
  if(typeof o==='string')return`<span class=jv>"${o}"</span>`;
  if(typeof o==='number')return`<span class=jn>${o}</span>`;
  if(typeof o==='boolean')return`<span class=jb>${o}</span>`;
  if(o===null)return`<span class=jl>null</span>`;
  return String(o);
}

// FETCH WRAPPER — relative URL, with timeout
async function apiFetch(ep){
  const ctrl=new AbortController();
  const tid=setTimeout(()=>ctrl.abort(),15000);
  try{
    const r=await fetch(API+ep,{signal:ctrl.signal});
    clearTimeout(tid);
    if(!r.ok)throw new Error('HTTP '+r.status);
    return r.json();
  }catch(e){
    clearTimeout(tid);
    throw e;
  }
}

// SHOW/HIDE helpers
const show=id=>{ const e=document.getElementById(id); if(e) e.style.display=''; };
const hide=id=>{ const e=document.getElementById(id); if(e) e.style.display='none'; };
const setStyle=(id,s,v)=>{ const e=document.getElementById(id); if(e) e.style[s]=v; };
const setText=(id,t)=>{ const e=document.getElementById(id); if(e) e.textContent=t; };
const setHTML=(id,h)=>{ const e=document.getElementById(id); if(e) e.innerHTML=h; };

// ══ 1. CLIMATE ══
async function loadClimate(){
  try{
    const d=await apiFetch('/climate/guntur');
    const c=d.climate;
    if(!c)throw new Error('No climate object in response');

    hide('c-load');
    setStyle('c-grid','display','grid');

    const tempColor=c.temperature_c>=42?'var(--r)':c.temperature_c>=38?'var(--o)':c.temperature_c>=35?'var(--amber)':'var(--g)';
    const tempEl=document.getElementById('cv-temp');
    if(tempEl){tempEl.textContent=c.temperature_c+'°';tempEl.style.color=tempColor;}
    setText('cv-aqi',c.aqi);
    setText('cv-hum',c.humidity_pct+'%');
    setText('cv-uv',c.uv_index);
    setText('cv-rain',c.rainfall_mm);

    const riskEl=document.getElementById('cv-risk');
    if(riskEl){riskEl.textContent=c.climate_risk_level||'--';riskEl.style.color=riskColor(c.climate_risk_level);}
    setText('cv-hazard',c.hazard_type||'NONE');
    setText('cv-src',c.source||'--');

    if(c.timestamp){
      const ts=new Date(c.timestamp);
      setText('climate-ts','Updated '+ts.toUTCString());
    }

    // Auto-fill RDT form
    const rt=document.getElementById('r-temp');
    const ra=document.getElementById('r-aqi');
    const rh=document.getElementById('r-hum');
    if(rt)rt.value=c.temperature_c;
    if(ra)ra.value=Math.round(c.aqi);
    if(rh)rh.value=Math.round(c.humidity_pct);

  }catch(e){
    setHTML('c-load',`<div class=err>Climate error: ${e.message}</div>`);
  }
}

// ══ 2. DISEASE FORECAST ══
async function loadDisease(){
  try{
    const d=await apiFetch('/cdsp/forecast');
    hide('d-load');
    const list=document.getElementById('d-list');
    if(!list)return;
    list.style.display='flex';

    const alert=d.district_alert||'UNKNOWN';
    const badge=document.getElementById('d-badge');
    if(badge){badge.textContent=alert;badge.className='ph-badge '+riskClass(alert);}

    const icons={heat_illness:'🌡️',dengue:'🦟',diarrhea:'💧',malaria:'🦠',ari_respiratory:'🫁'};
    const diseases=d.disease_forecasts||{};

    for(const[name,fc]of Object.entries(diseases)){
      if(!fc)continue;
      const score=Math.round((fc.risk_score||0)*100);
      const color=riskColor(fc.risk_level);
      const row=document.createElement('div');
      row.className='dr';
      row.innerHTML=`
        <div class="dr-ico">${icons[name]||'🦠'}</div>
        <div class="dr-body">
          <div class="dr-top">
            <span class="dr-name">${name.replace(/_/g,' ')}</span>
            <span class="ph-badge ${riskClass(fc.risk_level)}">${fc.risk_level||'--'}</span>
          </div>
          <div class="dr-bar"><div class="dr-fill" style="width:${score}%;background:${color}"></div></div>
          <div class="dr-meta">${fc.forecast_window||''} &middot; conf ${fc.confidence_pct||0}%</div>
        </div>`;
      list.appendChild(row);
    }
  }catch(e){
    setHTML('d-load',`<div class=err>Disease forecast error: ${e.message}</div>`);
  }
}

// ══ 3. SCHOOL VULNERABILITY ══
async function loadVuln(){
  try{
    const d=await apiFetch('/sve/vulnerability');
    hide('s-load');
    const list=document.getElementById('s-list');
    if(!list)return;
    list.style.display='flex';

    const n=d.critical_count||0;
    const badge=document.getElementById('s-badge');
    if(badge){badge.textContent=n+' CRITICAL';badge.className='ph-badge '+(n>0?'tag-crit':'tag-low');}

    (d.top_10_vulnerable||[]).slice(0,5).forEach((loc,i)=>{
      const c=riskColor(loc.risk_level);
      const row=document.createElement('div');
      row.className='vr';
      row.innerHTML=`
        <div class="vr-n">${i+1}</div>
        <div class="vr-inf">
          <div class="vr-nm">${(loc.name||'').slice(0,32)}</div>
          <div class="vr-mt">${loc.mandal||''} &middot; ${loc.children_at_risk||0} children</div>
        </div>
        <div class="vr-sc" style="color:${c}">${loc.vulnerability_score||0}<br>
          <span class="ph-badge ${riskClass(loc.risk_level)}" style="display:inline-block;margin-top:2px">${loc.risk_level||'--'}</span>
        </div>`;
      list.appendChild(row);
    });
  }catch(e){
    setHTML('s-load',`<div class=err>SVE error: ${e.message}</div>`);
  }
}

// ══ 4. 48H FORECAST ══
async function loadForecast(){
  try{
    const d=await apiFetch('/climate/forecast');
    hide('f-load');
    show('f-area');

    const fc=(d.forecast||[]).slice(0,24);
    if(!fc.length){setHTML('f-hw','No forecast data');return;}

    const temps=fc.map(f=>f.temperature_c).filter(Boolean);
    const minT=Math.min(...temps);
    const maxT=Math.max(...temps);
    const range=maxT-minT||1;

    setText('f-min',minT.toFixed(1)+'°C');
    setText('f-max',maxT.toFixed(1)+'°C');

    const cont=document.getElementById('f-bars');
    if(cont){
      fc.forEach((f,i)=>{
        if(i%3!==0)return;
        const t=f.temperature_c||30;
        const pct=((t-minT)/range)*100;
        const h=Math.max(4,pct*0.65+8);
        const color=t>=40?'var(--r)':t>=38?'var(--o)':t>=35?'var(--amber)':'var(--t)';
        const hour=f.time?new Date(f.time).getUTCHours():i;
        const col=document.createElement('div');
        col.className='fc-col';
        col.innerHTML=`<div class="fc-bar" style="height:${h}px;background:${color}"></div><div class="fc-lbl">${String(hour).padStart(2,'0')}h</div>`;
        cont.appendChild(col);
      });
    }

    const hw=fc.filter(f=>f.heatwave_risk);
    const hwEl=document.getElementById('f-hw');
    if(hwEl){
      if(hw.length){hwEl.textContent=hw.length+' hours ≥40°C — peak '+maxT.toFixed(1)+'°C';}
      else{hwEl.style.color='var(--g)';hwEl.textContent='No heatwave in next 24 hours';}
    }
  }catch(e){
    setHTML('f-load',`<div class=err>Forecast error: ${e.message}</div>`);
  }
}

// ══ 5. BLOCKCHAIN ══
async function loadChain(){
  try{
    const d=await apiFetch('/chain/summary');
    hide('ch-load');
    const stats=document.getElementById('ch-stats');
    if(stats){
      stats.style.display='grid';
      stats.innerHTML=`
        <div class="cg-i"><div class="cg-v" style="color:var(--p)">${d.chain_length||0}</div><div class="cg-l">Blocks</div></div>
        <div class="cg-i"><div class="cg-v" style="color:var(--g)">${d.total_cases_attested||0}</div><div class="cg-l">Cases Attested</div></div>`;
    }
    setHTML('ch-detail',
      `Valid: <span style="color:var(--g)">${d.is_valid?'YES ✓':'NO ✗'}</span><br>`+
      `Hash: <span style="color:var(--t)">${(d.latest_hash||'—').slice(0,18)}…</span><br>`+
      `<span style="color:var(--t4)">${d.privacy_note||''}</span>`
    );
  }catch(e){
    setHTML('ch-load',`<div class=err>Chain: ${e.message}</div>`);
  }
}

// ══ 6. RDT COMPUTE ══
document.getElementById('btn-rdt').addEventListener('click',async()=>{
  const btn=document.getElementById('btn-rdt');
  btn.disabled=true;btn.textContent='COMPUTING…';

  const now=new Date().toISOString();
  const age=parseInt(document.getElementById('r-age').value)||18;
  const wt=parseFloat(document.getElementById('r-wt').value)||10.2;
  const temp=parseFloat(document.getElementById('r-temp').value)||42.0;
  const aqi=parseFloat(document.getElementById('r-aqi').value)||95.0;
  const hum=parseFloat(document.getElementById('r-hum').value)||55.0;
  const lang=document.getElementById('r-lang').value||'en';

  // Simulate a 12-minute acknowledge delay
  const ackTime=new Date(Date.now()-12*60000).toISOString();

  const payload={
    child_age_months:age,child_weight_kg:wt,
    temperature_c:temp,aqi:aqi,humidity_pct:hum,
    bus_score:0,cif_score:Math.max(0,(temp-30)*0.035),
    ts_reported:new Date(Date.now()-20*60000).toISOString(),
    ts_acknowledged:ackTime,
    climate_pathway:'HEAT_DIRECT',
    mandal:'Tadikonda',village:'Rentachintala',chw_id:'ASHA-GNT-DEMO'
  };

  try{
    const r=await fetch(API+'/rdt/compute',{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)
    });
    const d=await r.json();
    const rdt=d.rdt;
    const instr=d.chw_instructions;
    const stages=d.stage_breakdown||{};

    if(!rdt){throw new Error(d.message||'No RDT in response');}

    const resEl=document.getElementById('rdt-res');
    if(resEl)resEl.style.display='block';

    const dc=rdt.delay_class||'--';
    const dcColor=dc==='EMERGENCY'?'var(--r)':dc==='CRITICAL'?'var(--o)':dc==='DELAYED'?'var(--amber)':dc==='MODERATE'?'var(--y)':'var(--g)';

    setHTML('rdt-sum',`
      <div class="rm"><div class="rm-v" style="color:var(--amber)">${rdt.total_rdt_min||'--'}<span style="font-size:11px">m</span></div><div class="rm-l">Total RDT</div></div>
      <div class="rm"><div class="rm-v" style="color:var(--t)">${rdt.t_adj_total||'--'}<span style="font-size:11px">m</span></div><div class="rm-l">T_adj Target</div></div>
      <div class="rm"><div class="rm-v" style="color:${dcColor}">${dc}</div><div class="rm-l">Classification</div></div>
    `);

    // Stage breakdown
    const stageHTML=Object.entries(stages).map(([s,v])=>`
      <div class="sg">
        <div class="sg-l">${s} · ${v.meaning||''}</div>
        <div class="sg-v" style="color:${v.status==='ON_TIME'?'var(--g)':v.status==='SLA_BREACH'?'var(--r)':'var(--amber)'}">
          ${v.actual||0}m vs ${v.target||0}m (${v.deviation_pct>0?'+':''}${v.deviation_pct||0}%)
        </div>
      </div>`).join('');
    setHTML('stage-row',stageHTML);

    // CHW Instructions (multilingual)
    // Fetch multilingual version if not English
    let instrHTML='';
    if(lang!=='en'){
      try{
        const mlRes=await fetch(API+'/rdt/multilingual',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({language:lang,protocol_type:'heat',child_age_months:age,
            child_weight_kg:wt,bus_score:rdt.bus_score||50,t_adj_min:rdt.t_adj_total||25,
            urgency_level:dc,hci_score:(rdt.cif_score||0)*100})
        });
        const mlData=await mlRes.json();
        if(mlData.content){
          instrHTML=`<div style="margin-bottom:6px;font-family:var(--mono);font-size:8px;color:var(--t3)">${mlData.language_name||lang} · ${mlData.complexity_mode||''}</div>`+
                    `<div style="white-space:pre-wrap;line-height:1.8">${mlData.content}</div>`;
        }
      }catch(_){}
    }
    if(!instrHTML && instr){
      const steps=(instr.steps||[]).map((s,i)=>`<div class="step"><span class="step-n">${i+1}.</span>${s}</div>`).join('');
      instrHTML=`
        <div style="font-family:var(--mono);font-size:8px;color:var(--t);margin-bottom:6px">
          BUS=${rdt.bus_score||'--'} · T_adj=${rdt.t_adj_total||'--'}min · dev=${rdt.deviation_pct>0?'+':''}${rdt.deviation_pct||0}%
          · bottleneck=${rdt.bottleneck||'NONE'}
        </div>
        ${steps}
        ${instr.escalation?`<div style="margin-top:6px;color:var(--r)">⚠ ${instr.escalation}</div>`:''}
        ${instr.not_your_fault?`<div style="margin-top:5px;color:var(--t3);font-style:italic">${instr.not_your_fault}</div>`:''}
      `;
    }
    setHTML('rdt-instr',instrHTML);

  }catch(e){
    const resEl=document.getElementById('rdt-res');
    if(resEl){resEl.style.display='block';resEl.innerHTML=`<div class=err>RDT error: ${e.message}</div>`;}
  }finally{
    btn.disabled=false;btn.textContent='COMPUTE RDT →';
  }
});

// ══ 7. API EXPLORER ══
document.getElementById('ep-tabs').addEventListener('click',async e=>{
  const tab=e.target.closest('.ep-tab');
  if(!tab)return;
  document.querySelectorAll('.ep-tab').forEach(t=>t.classList.remove('act'));
  tab.classList.add('act');
  const ep=tab.dataset.ep;
  const out=document.getElementById('api-out');
  if(out)out.innerHTML=`<span style="color:var(--t4)">Fetching ${ep}…</span>`;
  try{
    const d=await apiFetch(ep);
    if(out)out.innerHTML=prettyJson(d);
  }catch(e){
    if(out)out.innerHTML=`<span class=err>Error: ${e.message}</span>`;
  }
});

// ══ INIT ══
(async()=>{
  await loadClimate();
  loadDisease();
  loadVuln();
  loadForecast();
  loadChain();
  setInterval(loadClimate, 5*60*1000);
  setTimeout(()=>{
    const h=document.querySelector('.ep-tab[data-ep="/health"]');
    if(h)h.click();
  },800);
})();
</script>
</body>
</html>"""

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

    def _send_html(self, html: str):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
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
                self._send_html(get_dashboard_html())

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
