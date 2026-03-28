# 🏥 VaidyaBridge

**Universal AI bridge between messy patient inputs and life-saving health actions for rural India.**

> Built for Google PromptWars 2026 · Powered by Gemini 1.5 Pro · ABDM Compliant

---

## Chosen Vertical

**Healthcare — Rural India Last-Mile Health Bridge**

India has 0.7 doctors per 1,000 people (WHO recommends 1+) while carrying 20% of the world's disease burden. VaidyaBridge empowers ASHA (Accredited Social Health Activist) workers and rural patients by converting chaotic, multilingual health inputs into structured, verified, actionable outputs — instantly.

---

## Problem Statement Alignment

| Requirement | VaidyaBridge Solution |
|---|---|
| Unstructured, messy real-world inputs | Voice descriptions, crumpled prescription photos, blurry lab reports, WhatsApp-style mixed-language text |
| Structured, verified outputs | ABDM-formatted health summaries with dual-pass Gemini verification |
| Life-saving actions | RED/YELLOW/GREEN triage, drug interaction warnings, nearest pharmacy routing |
| Universal bridge | Works across 6 Indian languages, any input format |

---

## Approach and Logic

### Architecture

```
[Messy Input] → [Gemini Pass 1: Extract] → [Gemini Pass 2: Verify + Triage] → [Structured Output]
     ↓                                              ↓
Voice/Text/Image                         Google Cloud APIs
(any language)                      Speech · Vision · Translate · Maps
```

### Two-Pass Gemini Architecture (Hallucination Guard)

**Pass 1 — Extraction:**
- Gemini 1.5 Pro processes multimodal input (text + image simultaneously)
- Extracts: symptoms, medicines, lab values, vitals, duration, allergies
- Handles 6 Indian languages natively

**Pass 2 — Verification:**
- Independent Gemini instance reviews Pass 1 output
- Assigns triage level (RED/YELLOW/GREEN) based on clinical urgency rules
- Detects drug interactions
- Flags implausible or potentially hallucinated data
- Returns confidence score (HIGH/MEDIUM/LOW)

### Google Services Integration

| Service | Usage |
|---|---|
| **Gemini 1.5 Pro** | Dual-pass clinical extraction and verification |
| **Gemini 1.5 Flash** | Regional language translation (fallback) |
| **Google Cloud Vision API** | OCR on prescription/lab report images |
| **Google Cloud Translation API** | ASHA instructions in Hindi/Kannada/Telugu/Tamil/Marathi |
| **Google Maps Places API** | Nearest Jan Aushadhi pharmacy locator |

---

## How the Solution Works

### User Flow

1. **ASHA worker or patient opens VaidyaBridge**
2. **Selects language** (English/Hindi/Kannada/Telugu/Tamil/Marathi)
3. **Provides input** — any combination of:
   - Typed/spoken symptom description in any language
   - Photo of prescription (handwritten, crumpled, any quality)
   - Photo of lab report (blurry, thermal print, any format)
4. **Optionally shares location** for pharmacy search
5. **Taps Analyze** → results in ~10 seconds

### Output Structure

```json
{
  "triage": {
    "level": "RED | YELLOW | GREEN",
    "label": "Emergency | Urgent | Stable",
    "reason": "Clinical justification",
    "recommended_action": "Specific next step"
  },
  "extracted": {
    "patient_complaints": ["symptoms"],
    "medicines_mentioned": ["drugs"],
    "lab_values": {"test": "value"},
    "duration": "symptom duration"
  },
  "drug_interactions": ["dangerous combinations if any"],
  "data_confidence": "HIGH | MEDIUM | LOW",
  "flagged_concerns": ["implausible data warnings"],
  "abdm_summary": { ... },
  "asha_instructions": "Step by step plain English",
  "asha_instructions_translated": "Regional language translation",
  "pharmacies": [{ "name": "...", "address": "...", "open_now": true }],
  "disclaimer": "NOT a medical diagnosis warning"
}
```

---

## Safety and Compliance

- **DPDP Act compliance**: No patient data stored; all processing is stateless
- **Hallucination guard**: Every extraction is independently verified by a second Gemini pass
- **Medical disclaimer**: Prominently shown on every result — "NOT a medical diagnosis. Always consult a qualified doctor. Emergency: call 112."
- **Confidence scoring**: LOW confidence results explicitly warn ASHA workers
- **India-native**: ABDM (Ayushman Bharat Digital Mission) output format

---

## Assumptions Made

1. Users may have low internet bandwidth — UI is minimal and fast-loading
2. Prescription images may be low quality — Gemini's vision handles gracefully
3. Google Maps API may not have all Jan Aushadhi stores — falls back to "pharmacy" keyword search
4. Translation quality for medical terms varies — English instructions always shown alongside regional
5. This is a decision-support tool, not a diagnostic system — doctor consultation always recommended

---

## Tech Stack

- **Backend**: Python 3.11, Flask, Gunicorn
- **AI**: Google Gemini 1.5 Pro (dual-pass), Gemini 1.5 Flash (translation fallback)
- **Google APIs**: Cloud Vision, Cloud Translation, Maps Places
- **Deployment**: Google Cloud Run (containerized, auto-scaling)
- **Frontend**: Vanilla HTML/CSS/JS (no framework dependency, works on low-end devices)

---

## Local Development

```bash
git clone https://github.com/niranjan-ellur/vaidya-bridge
cd vaidya-bridge
pip install -r requirements.txt
export GEMINI_API_KEY=your_key_here
export GOOGLE_MAPS_API_KEY=your_maps_key_here
python app.py
# Open http://localhost:8080
```

---

## Deployment (Cloud Run)

```bash
gcloud builds submit --tag gcr.io/vaidya-bridge/vaidya-bridge
gcloud run deploy vaidya-bridge \
  --image gcr.io/vaidya-bridge/vaidya-bridge \
  --platform managed \
  --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=your_key,GOOGLE_MAPS_API_KEY=your_maps_key
```

---

## Changes/Updates in Deployed Version

### v1.0 — Initial Deployment
- Dual-pass Gemini architecture for hallucination guard
- Multimodal input: simultaneous text + image processing
- Triage system: RED/YELLOW/GREEN with clinical urgency rules
- ABDM-compliant structured output format
- 6 Indian language support (Hindi, Kannada, Telugu, Tamil, Marathi, English)
- Drug interaction detection via Gemini verification pass
- Data confidence scoring (HIGH/MEDIUM/LOW)
- DPDP Act compliant: zero data persistence, stateless processing
- Jan Aushadhi pharmacy locator via Google Maps Places API
- Mobile-responsive UI optimized for low-end Android devices
- Prominent medical disclaimer on all results
- Emergency contact (112) always visible in RED triage

---

## Impact Potential

- **1.3 million ASHA workers** in India who can use this immediately
- **650,000+ villages** with limited doctor access
- Directly aligned with **Ayushman Bharat Digital Mission (ABDM)** national initiative
- Compatible with **National Health Stack** output format

---

*VaidyaBridge — Because every life deserves a bridge to care.*
