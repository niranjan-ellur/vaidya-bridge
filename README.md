# 🏥 VaidyaBridge

> **Universal AI bridge between messy patient inputs and life-saving health actions for rural India.**

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/flask-3.0-green.svg)](https://flask.palletsprojects.com)
gemini 2.5flash
[![ABDM Ready](https://img.shields.io/badge/ABDM-ready-teal.svg)](https://abdm.gov.in)
[![Tests](https://img.shields.io/badge/tests-98%20passing-brightgreen.svg)]()

**Built for Google PromptWars 2026** · Powered by Gemini 2.5 flash · DPDP Act Compliant

---

## The Problem

India has **0.7 doctors per 1,000 people** (WHO recommends 1+) while carrying **20% of the world's disease burden**. 1.3 million ASHA workers bridge this gap — but they receive patients with crumpled prescriptions, blurry lab reports, and voice descriptions in 22+ languages. There is no tool to turn this chaos into action.

## The Solution

VaidyaBridge takes **any combination of messy inputs** and returns **structured, verified, life-saving outputs** in under 10 seconds.

```
[Voice/Text in any Indian language]  ┐
[Photo of handwritten prescription]  ├─▶ VaidyaBridge ─▶ [Triage + ASHA instructions]
[Blurry lab report scan]             ┘    (Gemini AI)      [ABDM health summary]
                                                            [Nearby Jan Aushadhi pharmacy]
                                                            [Regional language translation]
```

---

## Architecture

### Dual-Pass Gemini Pipeline

```
Input ──▶ Cloud Vision OCR ──▶ Gemini 2.5 flash (Pass 1: Extract) ──▶ Gemini 2.5 flash (Pass 2: Verify)
                                      │                                        │
                                 Clinical data                         Hallucination guard
                                 extraction                            + RED/YELLOW/GREEN triage
                                                                       + Drug interaction check
                                                                       + Confidence scoring
```

### Google Services Used

| Service | Purpose |
|---|---|
| **Gemini 2.5 flash** | Pass 1: Multimodal clinical extraction (text + image) |
| **Gemini 2.5 flash** | Pass 2: Independent verification + hallucination guard |
| **Gemini 2.5 Flash** | Regional language translation fallback |
| **Google Cloud Vision API** | Dedicated OCR for prescription/lab report images |
| **Google Cloud Translation API** | High-quality ASHA instruction translation |
| **Google Maps Places API** | Nearest Jan Aushadhi pharmacy locator |
| **Google Cloud Run** | Serverless, auto-scaling deployment |
| **Google Cloud Build** | CI/CD: tests → build → deploy pipeline |

---

## Features

- 🔬 **Dual-pass Gemini** — Extract then independently verify to catch hallucinations
- 🌐 **6 Indian languages** — Hindi, Kannada, Telugu, Tamil, Marathi, Bengali
- 🚨 **RED/YELLOW/GREEN triage** — Clinical urgency engine with 112 emergency contact
- 💊 **Drug interaction detection** — Flags dangerous medication combinations
- 📋 **ABDM-compliant output** — Ayushman Bharat Digital Mission format
- 🏪 **Jan Aushadhi locator** — Google Maps pharmacy finder with open/closed status
- 🔒 **DPDP Act compliant** — Zero data persistence, fully stateless
- ♿ **Fully accessible** — ARIA labels, skip links, live regions, keyboard navigation
- 🛡️ **Security hardened** — Rate limiting, input sanitisation, CSP headers, non-root Docker

---

## Quick Start

```bash
git clone https://github.com/niranjan-ellur/vaidya-bridge
cd vaidya-bridge



pip install -r requirements.txt
python app.py
# Open http://localhost:8080
```

---

## Running Tests

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
# 98 tests, >80% coverage
```

---


## Project Structure

```
vaidya-bridge/
├── app.py                  # Main Flask application (2.0.0)
├── templates/
│   └── index.html          # Accessible single-page UI
├── static/
│   └── manifest.json       # PWA web app manifest
├── tests/
│   ├── conftest.py         # Shared fixtures
│   └── test_app.py         # 98 unit + integration tests
├── Dockerfile              # Multi-stage, non-root build
├── cloudbuild.yaml         # CI/CD: test → build → deploy
├── requirements.txt        # Pinned dependencies
├── pyproject.toml          # Tool config (pytest, ruff, mypy)
├── .env.example            # Environment variable template
├── SECURITY.md             # Security policy
└── README.md
```

---

## API Reference

### `POST /analyze`

**Request:**
```json
{
  "text": "Patient has fever 103F and chest pain",
  "image_base64": "<base64-encoded-image>",
  "language": "hi",
  "lat": 12.9716,
  "lng": 77.5946
}
```

**Response:**
```json
{
  "success": true,
  "triage": {
    "level": "RED",
    "label": "Emergency",
    "reason": "Chest pain with high fever requires immediate evaluation",
    "recommended_action": "Seek immediate hospital care — call 112 now"
  },
  "extracted": {
    "patient_complaints": ["chest pain", "fever 103F"],
    "medicines_mentioned": [],
    "lab_values": {}
  },
  "drug_interactions": [],
  "data_confidence": "HIGH",
  "abdm_summary": { ... },
  "asha_instructions": "1. Call 112 immediately...",
  "asha_instructions_translated": "१. तुरंत 112 पर कॉल करें...",
  "pharmacies": [{ "name": "Jan Aushadhi Store", "address": "...", "open_now": true }],
  "disclaimer": "⚠️ NOT a medical diagnosis. Always consult a qualified doctor."
}
```

### `GET /health`
Returns service status and configuration flags.

---


---

## Impact

- **1.3 million ASHA workers** in India who can use this immediately
- **650,000+ villages** with limited doctor access
- Aligned with **Ayushman Bharat Digital Mission (ABDM)** national initiative
- Addresses India's **0.7 doctors per 1,000 people** healthcare gap

---

*VaidyaBridge — Because every life deserves a bridge to care.*
