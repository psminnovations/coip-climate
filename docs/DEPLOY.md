# COIP-Climate — GitHub Repository Setup
## Exact Commands to Create Public GitHub Repo

### Step 1: Create repo on GitHub
1. Go to https://github.com/new
2. Name: `coip-climate`
3. Description: `Climate-aware RDT intelligence for child health — Guntur District pilot`
4. Visibility: **PUBLIC** (required for UNICEF)
5. Do NOT initialize with README (we have our own)
6. Click "Create repository"

### Step 2: Push code from this ZIP
```bash
# Extract the zip
unzip coip-climate-v2-complete.zip
cd coip-climate

# Initialize git
git init
git add .
git commit -m "Initial commit — COIP-Climate v2.0 — UNICEF Climate Ventures 2026

- ESI: Real-time climate signals (Open-Meteo, OpenAQ) for Guntur District
- CVBM: Child Vulnerability Biological Model — SA:mass ratio, BUS score
- RDT Engine v2: Fixed deviation_pct formula, negative timestamp guard, bottleneck detection
- CBAD: CHW Behavioral Anomaly Detector (Isolation Forest)
- CDSP: Disease surge prediction — Heat, Dengue, Diarrhea, Malaria, ARI
- SVE: School and facility vulnerability scoring (OSM data)
- MLLE: Multilingual triage — Telugu + Hindi + English (100% offline)
- BCAL: Blockchain attestation chain (reload bug fixed)
- API: Deployable HTTP server (stdlib only, no dependencies)
- Tests: 29/29 passing
- Data: 400 synthetic Guntur pilot cases"

# Set remote (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/coip-climate.git
git branch -M main
git push -u origin main
```

### Step 3: Deploy to Railway (free, public URL in 5 minutes)
```bash
# Install Railway CLI
npm install -g @railway/cli  # or: curl -fsSL https://railway.app/install.sh | sh

# Login
railway login

# Deploy
cd coip-climate
railway init
railway up

# Get your URL
railway status
# → https://coip-climate-production.up.railway.app
```

### Step 4: Test your live deployment
```bash
# These should all return JSON
curl https://YOUR-APP.railway.app/health
curl https://YOUR-APP.railway.app/climate/guntur
curl https://YOUR-APP.railway.app/demo
curl https://YOUR-APP.railway.app/cdsp/forecast

# Test RDT compute
curl -X POST https://YOUR-APP.railway.app/rdt/compute \
  -H "Content-Type: application/json" \
  -d '{
    "child_age_months": 18,
    "child_weight_kg": 10.2,
    "temperature_c": 42.0,
    "aqi": 95.0,
    "humidity_pct": 55.0,
    "bus_score": 75.0,
    "cif_score": 0.42,
    "ts_reported": "2026-05-03T09:14:00+00:00",
    "ts_acknowledged": "2026-05-03T09:28:00+00:00",
    "ts_decided": "2026-05-03T09:45:00+00:00",
    "climate_pathway": "HEAT_DIRECT"
  }'
```

### Step 5: Alternative — Render.com (also free)
1. Go to https://render.com
2. "New Web Service" → Connect GitHub → select `coip-climate`
3. Start command: `python3 api/server.py`
4. Deploy → get URL like `https://coip-climate.onrender.com`

### What UNICEF Will See
- GitHub: Public repo, Apache 2.0, 26 Python files, 29 tests passing
- Live URL: Real climate data for Guntur returned on every GET /climate/guntur
- Open source: Anyone can fork, deploy, modify without depending on us
- Blockchain: GET /chain/summary shows attestation chain
- Multilingual: POST /rdt/multilingual returns Telugu protocols

### The UNICEF hard requirement satisfied:
"The company will need to provide some type of real-time data
that can be accessed through Internet."
→ GET /climate/guntur returns live Open-Meteo data for Guntur, 24/7
