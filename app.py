import os
import json
import base64
import re
from flask import Flask, request, jsonify, render_template
import google.generativeai as genai
import requests

app = Flask(__name__)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MAPS_API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

SUPPORTED_LANGUAGES = {
    "hi": "Hindi", "kn": "Kannada", "te": "Telugu",
    "ta": "Tamil", "mr": "Marathi", "bn": "Bengali", "en": "English"
}

TRIAGE_LEVELS = {
    "RED": {"label": "Emergency", "color": "#E24B4A", "action": "Seek immediate hospital care — call 112"},
    "YELLOW": {"label": "Urgent", "color": "#EF9F27", "action": "Visit PHC within 24 hours"},
    "GREEN": {"label": "Stable", "color": "#639922", "action": "Home care with follow-up in 3 days"}
}


def clean_json(raw: str) -> str:
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    return raw.strip()


def extract_health_data(text_input: str, image_base64: str = None, lang: str = "en") -> dict:
    model = genai.GenerativeModel("gemini-1.5-pro")
    lang_name = SUPPORTED_LANGUAGES.get(lang, "English")

    prompt = f"""You are a clinical data extraction assistant for Indian rural healthcare.
Input language: {lang_name}
Text: {text_input}

Return ONLY valid JSON (no markdown):
{{
  "patient_complaints": ["symptoms in English"],
  "duration": "how long",
  "medicines_mentioned": ["medicines"],
  "lab_values": {{}},
  "allergies": [],
  "age_mentioned": null,
  "gender_mentioned": null,
  "vital_signs": {{}},
  "raw_summary": "2-sentence plain English summary"
}}
Extract only what is explicitly mentioned. Never invent data."""

    parts = [prompt]
    if image_base64:
        parts[0] = prompt.replace("Text:", "Text (also see attached medical image):") 
        parts.append({"mime_type": "image/jpeg", "data": image_base64})

    try:
        response = model.generate_content(parts)
        return json.loads(clean_json(response.text))
    except Exception:
        return {
            "patient_complaints": [text_input] if text_input else ["See attached image"],
            "duration": "unknown", "medicines_mentioned": [], "lab_values": {},
            "allergies": [], "age_mentioned": None, "gender_mentioned": None,
            "vital_signs": {}, "raw_summary": text_input or "Medical document provided"
        }


def verify_and_triage(extracted: dict) -> dict:
    model = genai.GenerativeModel("gemini-1.5-pro")
    prompt = f"""You are a senior medical reviewer for Indian rural healthcare.
Verify this extracted health data and assign triage.

Data: {json.dumps(extracted)}

Return ONLY valid JSON:
{{
  "triage_level": "RED or YELLOW or GREEN",
  "triage_reason": "one sentence",
  "drug_interactions": ["dangerous interactions if any"],
  "data_confidence": "HIGH or MEDIUM or LOW",
  "flagged_concerns": ["anything implausible"],
  "abdm_summary": {{
    "chief_complaint": "primary complaint",
    "symptom_duration": "duration",
    "current_medications": [],
    "allergies": [],
    "recommended_action": "specific next step"
  }},
  "asha_instructions": "Step by step plain English for ASHA worker"
}}

Triage: RED=emergency (chest pain/breathing difficulty/unconscious/stroke/high fever>104F), YELLOW=urgent (moderate fever/persistent vomiting/worsening), GREEN=stable (mild/routine)"""

    try:
        response = model.generate_content(prompt)
        return json.loads(clean_json(response.text))
    except Exception:
        return {
            "triage_level": "YELLOW", "triage_reason": "Verification failed — use caution",
            "drug_interactions": [], "data_confidence": "LOW",
            "flagged_concerns": ["Auto-verification failed"], "abdm_summary": extracted,
            "asha_instructions": "Please visit the nearest Primary Health Centre."
        }


def translate_text(text: str, target_lang: str) -> str:
    if target_lang == "en" or not text:
        return text
    try:
        model = genai.GenerativeModel("gemini-1.5-flash")
        lang_name = SUPPORTED_LANGUAGES.get(target_lang, "Hindi")
        resp = model.generate_content(
            f"Translate to {lang_name} for a village health worker. Keep simple and clear:\n\n{text}"
        )
        return resp.text.strip()
    except Exception:
        return text


def find_pharmacies(lat: float, lng: float) -> list:
    if not MAPS_API_KEY or not lat or not lng:
        return []
    try:
        r = requests.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params={"location": f"{lat},{lng}", "radius": 5000,
                    "keyword": "Jan Aushadhi pharmacy medical store", "key": MAPS_API_KEY},
            timeout=5
        )
        return [
            {"name": p.get("name"), "address": p.get("vicinity"),
             "rating": p.get("rating"), "open_now": p.get("opening_hours", {}).get("open_now")}
            for p in r.json().get("results", [])[:3]
        ]
    except Exception:
        return []


@app.route("/")
def index():
    return render_template("index.html", maps_key=MAPS_API_KEY)


@app.route("/analyze", methods=["POST"])
def analyze():
    if not GEMINI_API_KEY:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    data = request.get_json()
    text_input = data.get("text", "")
    image_base64 = data.get("image_base64")
    language = data.get("language", "en")
    lat = data.get("lat")
    lng = data.get("lng")

    if not text_input and not image_base64:
        return jsonify({"error": "Provide text or image input"}), 400

    try:
        extracted = extract_health_data(text_input, image_base64, language)
        verified = verify_and_triage(extracted)
        translated = translate_text(verified.get("asha_instructions", ""), language)
        pharmacies = find_pharmacies(lat, lng) if lat and lng else []
        triage = verified.get("triage_level", "YELLOW")
        triage_info = TRIAGE_LEVELS.get(triage, TRIAGE_LEVELS["YELLOW"])

        return jsonify({
            "success": True,
            "extracted": extracted,
            "triage": {
                "level": triage, "label": triage_info["label"],
                "color": triage_info["color"], "reason": verified.get("triage_reason"),
                "recommended_action": triage_info["action"]
            },
            "drug_interactions": verified.get("drug_interactions", []),
            "data_confidence": verified.get("data_confidence", "MEDIUM"),
            "flagged_concerns": verified.get("flagged_concerns", []),
            "abdm_summary": verified.get("abdm_summary", {}),
            "asha_instructions": verified.get("asha_instructions", ""),
            "asha_instructions_translated": translated,
            "pharmacies": pharmacies,
            "disclaimer": "⚠️ NOT a medical diagnosis. Always consult a qualified doctor. Emergency: call 112."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "VaidyaBridge v1.0"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=False)
