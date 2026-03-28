"""
VaidyaBridge — Universal AI Health Bridge for Rural India
==========================================================
Converts messy, multilingual patient inputs (voice text, prescription photos,
lab reports) into structured, verified, ABDM-compliant health actions for
ASHA workers and rural communities.

Architecture:
    Pass 1 (Gemini 1.5 Pro): Multimodal clinical data extraction
    Pass 2 (Gemini 1.5 Pro): Independent verification + hallucination guard
    Google Cloud Vision API:  Dedicated OCR for prescription/lab images
    Google Cloud Translation: Regional language ASHA instructions
    Google Maps Places API:   Nearby Jan Aushadhi pharmacy locator
    Google Cloud Run:         Serverless auto-scaling deployment
    Google Cloud Build:       CI/CD test → build → deploy pipeline

Version: 2.0.0
DPDP Act compliant: zero data persistence, fully stateless.
"""

from __future__ import annotations

import base64 as b64lib
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional

import requests
from flask import Flask, Response, g, jsonify, render_template, request
from google import genai
from google.genai import types as genai_types
from google.cloud import translate_v2 as cloud_translate
from google.cloud import vision

# ---------------------------------------------------------------------------
# Version
# ---------------------------------------------------------------------------
__version__ = "2.0.0"

# ---------------------------------------------------------------------------
# Logging — structured JSON for Google Cloud Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
)
logger = logging.getLogger("vaidyabridge")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
class Config:
    """Centralised application configuration loaded from environment variables."""

    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    MAPS_API_KEY: str = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    MAX_CONTENT_BYTES: int = 5 * 1024 * 1024
    MAX_TEXT_LENGTH: int = 2000
    MAX_IMAGE_B64_BYTES: int = 4 * 1024 * 1024
    RATE_LIMIT_REQUESTS: int = 10
    RATE_LIMIT_WINDOW_SEC: int = 60
    PHARMACY_SEARCH_RADIUS_M: int = 5000
    PHARMACY_MAX_RESULTS: int = 3
    REQUESTS_TIMEOUT_SEC: int = 5
    GEMINI_EXTRACT_MODEL: str = "gemini-1.5-pro"
    GEMINI_VERIFY_MODEL: str = "gemini-1.5-pro"
    GEMINI_TRANSLATE_MODEL: str = "gemini-1.5-flash"


# ---------------------------------------------------------------------------
# Domain Constants
# ---------------------------------------------------------------------------
SUPPORTED_LANGUAGES: dict[str, str] = {
    "hi": "Hindi", "kn": "Kannada", "te": "Telugu",
    "ta": "Tamil",  "mr": "Marathi", "bn": "Bengali", "en": "English",
}

TRIAGE_LEVELS: dict[str, dict[str, str]] = {
    "RED": {
        "label": "Emergency",
        "color": "#C0392B",
        "action": "Seek immediate hospital care — call 112 now",
        "aria_label": "Emergency — immediate action required",
    },
    "YELLOW": {
        "label": "Urgent",
        "color": "#D68910",
        "action": "Visit Primary Health Centre within 24 hours",
        "aria_label": "Urgent — visit PHC within 24 hours",
    },
    "GREEN": {
        "label": "Stable",
        "color": "#1E8449",
        "action": "Home care with PHC follow-up in 3 days",
        "aria_label": "Stable — home care appropriate",
    },
}

ERROR_MESSAGES: dict[str, str] = {
    "no_input":        "Provide text symptoms or upload a medical image.",
    "invalid_json":    "Invalid JSON payload.",
    "not_configured":  "Service not configured. Contact administrator.",
    "rate_limited":    "Too many requests. Please wait a moment.",
    "request_too_large": "Request too large. Maximum 5 MB allowed.",
    "analysis_failed": "Analysis failed. Please try again.",
}


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class VaidyaBridgeError(Exception):
    """Base exception for VaidyaBridge application errors."""

class ExtractionError(VaidyaBridgeError):
    """Raised when Gemini extraction pass fails."""

class VerificationError(VaidyaBridgeError):
    """Raised when Gemini verification pass fails."""

class TranslationError(VaidyaBridgeError):
    """Raised when translation fails."""

class PharmacySearchError(VaidyaBridgeError):
    """Raised when Google Maps pharmacy search fails."""


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class AnalysisRequest:
    """Validated and sanitised inbound analysis request."""
    text: str
    image_base64: Optional[str]
    language: str
    lat: Optional[float]
    lng: Optional[float]
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])


@dataclass
class TriageResult:
    """Structured triage output."""
    level: str
    label: str
    color: str
    reason: str
    recommended_action: str
    aria_label: str


# ---------------------------------------------------------------------------
# App + Gemini Initialisation
# ---------------------------------------------------------------------------
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = Config.MAX_CONTENT_BYTES

# Gemini client — initialised once at startup, reused across all requests
_gemini_client: Optional[genai.Client] = None

if Config.GEMINI_API_KEY:
    _gemini_client = genai.Client(api_key=Config.GEMINI_API_KEY)
    logger.info(
        "Gemini client initialised. Models: %s / %s / %s",
        Config.GEMINI_EXTRACT_MODEL,
        Config.GEMINI_VERIFY_MODEL,
        Config.GEMINI_TRANSLATE_MODEL,
    )
else:
    logger.warning("GEMINI_API_KEY not set — /analyze will return 503")

# HTTP session — connection pooling for Maps API
_http_session = requests.Session()
_http_session.headers.update({"User-Agent": f"VaidyaBridge/{__version__}"})

# In-memory rate limiter: {ip: [epoch_timestamps]}
_rate_store: dict[str, list[float]] = {}


# ---------------------------------------------------------------------------
# Security Helpers
# ---------------------------------------------------------------------------
def check_rate_limit(ip: str) -> bool:
    """
    Sliding-window rate limiter.

    Args:
        ip: Client IP address string.

    Returns:
        True if within limit, False if exceeded.
    """
    now = time.time()
    window = _rate_store.get(ip, [])
    window = [t for t in window if now - t < Config.RATE_LIMIT_WINDOW_SEC]
    if len(window) >= Config.RATE_LIMIT_REQUESTS:
        return False
    window.append(now)
    _rate_store[ip] = window
    return True


def sanitize_text(text: Optional[str], max_length: int = Config.MAX_TEXT_LENGTH) -> str:
    """
    Remove dangerous control characters and truncate to max_length.

    Args:
        text: Raw input string (may be None).
        max_length: Maximum allowed character count.

    Returns:
        Sanitised, truncated string.
    """
    if not text:
        return ""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text))
    return text[:max_length].strip()


def validate_coordinates(
    lat: object, lng: object
) -> tuple[Optional[float], Optional[float]]:
    """
    Parse and validate geographic coordinates.

    Args:
        lat: Latitude value (str, float, int, or None).
        lng: Longitude value (str, float, int, or None).

    Returns:
        Validated (lat, lng) floats, or (None, None) if invalid.
    """
    try:
        lat_f, lng_f = float(lat), float(lng)  # type: ignore[arg-type]
        if -90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0:
            return lat_f, lng_f
    except (TypeError, ValueError):
        pass
    return None, None


def validate_language(lang: Optional[str]) -> str:
    """Return lang code if supported, else fall back to 'en'."""
    return lang if lang in SUPPORTED_LANGUAGES else "en"


def validate_base64_image(data: Optional[str]) -> Optional[str]:
    """
    Validate that image data is plausible base64 within size limits.

    Args:
        data: Base64-encoded image string.

    Returns:
        data if valid, else None.
    """
    if not data:
        return None
    if len(data) > Config.MAX_IMAGE_B64_BYTES:
        logger.warning("Image rejected: exceeds %d bytes", Config.MAX_IMAGE_B64_BYTES)
        return None
    if not re.match(r"^[A-Za-z0-9+/=]{4,}$", data[:200]):
        return None
    return data


def clean_json(raw: str) -> str:
    """Strip Gemini markdown code fences from JSON responses."""
    raw = re.sub(r"```json\s*", "", raw)
    raw = re.sub(r"```\s*", "", raw)
    return raw.strip()


def parse_analysis_request(payload: dict) -> AnalysisRequest:
    """
    Build and validate an AnalysisRequest from raw JSON payload.

    Args:
        payload: Decoded JSON dict from request body.

    Returns:
        Validated AnalysisRequest dataclass instance.

    Raises:
        ValueError: If neither text nor image is provided.
    """
    text = sanitize_text(payload.get("text", ""))
    image = validate_base64_image(payload.get("image_base64"))
    language = validate_language(payload.get("language", "en"))
    lat, lng = validate_coordinates(payload.get("lat"), payload.get("lng"))

    if not text and not image:
        raise ValueError(ERROR_MESSAGES["no_input"])

    return AnalysisRequest(
        text=text, image_base64=image,
        language=language, lat=lat, lng=lng,
    )


# ---------------------------------------------------------------------------
# Google Cloud Vision — dedicated OCR
# ---------------------------------------------------------------------------
def ocr_image_with_vision(image_base64: str) -> str:
    """
    Extract text from a medical image using Google Cloud Vision API.

    Gracefully falls back to empty string if Vision API is unavailable —
    Gemini will process the raw image bytes directly in that case.

    Args:
        image_base64: Base64-encoded JPEG/PNG image.

    Returns:
        Extracted text string, or empty string on failure.
    """
    try:
        client = vision.ImageAnnotatorClient()
        image_bytes = b64lib.b64decode(image_base64)
        vision_image = vision.Image(content=image_bytes)
        response = client.text_detection(image=vision_image)
        if response.error.message:
            logger.warning("Vision API error: %s", response.error.message)
            return ""
        texts = response.text_annotations
        extracted = texts[0].description if texts else ""
        logger.info("Vision OCR extracted %d characters", len(extracted))
        return extracted
    except Exception as exc:
        logger.warning("Vision OCR unavailable — Gemini vision will handle image: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Google Cloud Translation
# ---------------------------------------------------------------------------
def translate_with_cloud_api(text: str, target_lang: str) -> Optional[str]:
    """
    Translate text using Google Cloud Translation API v2.

    Args:
        text: Source text in English.
        target_lang: BCP-47 target language code.

    Returns:
        Translated string, or None if unavailable.
    """
    try:
        client = cloud_translate.Client()
        result = client.translate(text, target_language=target_lang)
        logger.info("Cloud Translation API: translated to %s", target_lang)
        return result["translatedText"]
    except Exception as exc:
        logger.warning("Cloud Translation API unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Gemini — Pass 1: Extraction
# ---------------------------------------------------------------------------
def extract_health_data(req: AnalysisRequest, ocr_text: str = "") -> dict:
    """
    Gemini Pass 1: Extract structured clinical data from multimodal input.

    Combines raw text, optional Cloud Vision OCR text, and optional raw
    image bytes for Gemini's native vision understanding.

    Args:
        req: Validated AnalysisRequest instance.
        ocr_text: Pre-extracted text from Cloud Vision (may be empty).

    Returns:
        Dict with patient_complaints, medicines_mentioned, lab_values, etc.

    Raises:
        ExtractionError: If Gemini call or JSON parse fails.
    """
    if not _gemini_client:
        raise ExtractionError("Gemini not configured")

    lang_name = SUPPORTED_LANGUAGES.get(req.language, "English")
    combined_text = req.text
    if ocr_text:
        combined_text = f"{req.text}\n\n[OCR from uploaded image]:\n{ocr_text}".strip()

    prompt_text = (
        f"You are a clinical data extraction assistant for Indian rural healthcare (ASHA workers).\n"
        f"Input language hint: {lang_name}\n"
        f"Patient input: {combined_text}\n\n"
        "Rules: Extract ONLY what is explicitly stated. NEVER invent or infer data. "
        "Translate symptom and medicine names to English. "
        "Return ONLY valid JSON with no markdown fences.\n\n"
        'Schema: {"patient_complaints":["symptoms in English"],'
        '"duration":"symptom duration or unknown",'
        '"medicines_mentioned":["drug names"],'
        '"lab_values":{"test_name":"value"},'
        '"allergies":[],'
        '"age_mentioned":null,'
        '"gender_mentioned":null,'
        '"vital_signs":{"bp":null,"temp":null,"pulse":null},'
        '"raw_summary":"2-sentence plain English clinical summary"}'
    )

    # Build content parts for new SDK
    contents: list = [genai_types.Part.from_text(text=prompt_text)]
    if req.image_base64:
        contents[0] = genai_types.Part.from_text(
            text=prompt_text.replace(
                "Patient input:", "Patient input (also analyse the attached medical image):"
            )
        )
        contents.append(
            genai_types.Part.from_bytes(
                data=b64lib.b64decode(req.image_base64),
                mime_type="image/jpeg"
            )
        )

    try:
        response = _gemini_client.models.generate_content(
            model=Config.GEMINI_EXTRACT_MODEL,
            contents=contents,
        )
        result: dict = json.loads(clean_json(response.text))
        logger.info(
            "[%s] Extraction complete — %d complaints, %d medicines",
            req.request_id,
            len(result.get("patient_complaints", [])),
            len(result.get("medicines_mentioned", [])),
        )
        return result
    except json.JSONDecodeError as exc:
        logger.error("[%s] JSON parse in extraction: %s", req.request_id, exc)
        raise ExtractionError(f"Could not parse extraction response: {exc}") from exc
    except Exception as exc:
        logger.error("[%s] Extraction pass failed: %s", req.request_id, exc)
        raise ExtractionError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Gemini — Pass 2: Verification + Hallucination Guard
# ---------------------------------------------------------------------------
def verify_and_triage(extracted: dict, request_id: str = "") -> dict:
    """
    Gemini Pass 2: Independent verification, hallucination guard, and triage.

    A separate Gemini call critically reviews Pass 1 output, assigns
    RED/YELLOW/GREEN triage, detects drug interactions, and flags
    any implausible extracted data.

    Args:
        extracted: Output dict from extract_health_data().
        request_id: Tracing ID for log correlation.

    Returns:
        Dict with triage_level, drug_interactions, confidence, abdm_summary,
        asha_instructions.

    Raises:
        VerificationError: If Gemini call or JSON parse fails.
    """
    if not _gemini_client:
        raise VerificationError("Gemini not configured")

    prompt_text = (
        "You are a senior medical reviewer verifying AI-extracted health data "
        "for Indian rural healthcare. Critically review and flag anything implausible.\n\n"
        f"Extracted data: {json.dumps(extracted, ensure_ascii=False)}\n\n"
        "Return ONLY valid JSON:\n"
        '{"triage_level":"RED or YELLOW or GREEN",'
        '"triage_reason":"one concise clinical sentence",'
        '"drug_interactions":["dangerous combinations found, or empty list"],'
        '"data_confidence":"HIGH or MEDIUM or LOW",'
        '"flagged_concerns":["implausible items, or empty list"],'
        '"abdm_summary":{'
        '"chief_complaint":"primary complaint",'
        '"symptom_duration":"duration",'
        '"current_medications":[],'
        '"allergies":[],'
        '"recommended_action":"specific ASHA worker next step"},'
        '"asha_instructions":"Numbered step-by-step plain English for ASHA worker"}\n\n'
        "Triage: RED=emergency (chest pain/dyspnoea/unconscious/stroke/fever>104F/bleeding); "
        "YELLOW=urgent (fever 100-104F/persistent vomiting/worsening chronic/severe pain); "
        "GREEN=stable (mild/routine/follow-up)"
    )

    try:
        response = _gemini_client.models.generate_content(
            model=Config.GEMINI_VERIFY_MODEL,
            contents=[genai_types.Part.from_text(text=prompt_text)],
        )
        result: dict = json.loads(clean_json(response.text))
        logger.info(
            "[%s] Verification complete — triage: %s, confidence: %s",
            request_id,
            result.get("triage_level"),
            result.get("data_confidence"),
        )
        return result
    except json.JSONDecodeError as exc:
        logger.error("[%s] JSON parse in verification: %s", request_id, exc)
        raise VerificationError(f"Could not parse verification response: {exc}") from exc
    except Exception as exc:
        logger.error("[%s] Verification pass failed: %s", request_id, exc)
        raise VerificationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Translation — Cloud API first, Gemini fallback, LRU cached
# ---------------------------------------------------------------------------
@lru_cache(maxsize=256)
def _cached_gemini_translation(text_hash: str, target_lang: str, text: str) -> str:
    """LRU-cached Gemini Flash translation fallback."""
    if not _gemini_client:
        return text
    try:
        lang_name = SUPPORTED_LANGUAGES.get(target_lang, "Hindi")
        response = _gemini_client.models.generate_content(
            model=Config.GEMINI_TRANSLATE_MODEL,
            contents=[genai_types.Part.from_text(
                text=f"Translate to {lang_name} for a village health worker. "
                     "Keep simple and culturally appropriate. "
                     "No commentary:\n\n" + text
            )],
        )
        return response.text.strip()
    except Exception as exc:
        logger.warning("Gemini translation fallback failed: %s", exc)
        return text


def translate_text(text: str, target_lang: str) -> str:
    """
    Translate ASHA instructions to a regional Indian language.

    Uses Cloud Translation API first, then Gemini Flash fallback.
    Results are LRU-cached by SHA-256 content hash.

    Args:
        text: English instructions to translate.
        target_lang: BCP-47 language code.

    Returns:
        Translated text string (falls back to English on failure).
    """
    if target_lang == "en" or not text:
        return text

    cloud_result = translate_with_cloud_api(text, target_lang)
    if cloud_result:
        return cloud_result

    text_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    return _cached_gemini_translation(text_hash, target_lang, text)


# ---------------------------------------------------------------------------
# Google Maps — Pharmacy Locator
# ---------------------------------------------------------------------------
def find_pharmacies(lat: float, lng: float) -> list[dict]:
    """
    Find nearby Jan Aushadhi stores via Google Maps Places API.

    Uses connection-pooled HTTP session for efficiency.

    Args:
        lat: User latitude (pre-validated).
        lng: User longitude (pre-validated).

    Returns:
        List of up to 3 nearby pharmacy dicts.
    """
    if not Config.MAPS_API_KEY:
        logger.warning("GOOGLE_MAPS_API_KEY not set — skipping pharmacy search")
        return []
    try:
        response = _http_session.get(
            "https://maps.googleapis.com/maps/api/place/nearbysearch/json",
            params={
                "location": f"{lat},{lng}",
                "radius": Config.PHARMACY_SEARCH_RADIUS_M,
                "keyword": "Jan Aushadhi pharmacy medical store",
                "key": Config.MAPS_API_KEY,
            },
            timeout=Config.REQUESTS_TIMEOUT_SEC,
        )
        response.raise_for_status()
        results = response.json().get("results", [])[:Config.PHARMACY_MAX_RESULTS]
        pharmacies = [
            {
                "name": p.get("name"),
                "address": p.get("vicinity"),
                "rating": p.get("rating"),
                "open_now": p.get("opening_hours", {}).get("open_now"),
            }
            for p in results
        ]
        logger.info("Found %d nearby pharmacies", len(pharmacies))
        return pharmacies
    except requests.RequestException as exc:
        logger.error("Pharmacy search failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Security Middleware
# ---------------------------------------------------------------------------
@app.after_request
def add_security_headers(response: Response) -> Response:
    """Attach security headers to every outbound response."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://maps.googleapis.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://maps.googleapis.com;"
    )
    return response


@app.before_request
def attach_request_id() -> None:
    """Attach a unique request ID to Flask g for log tracing."""
    g.request_id = str(uuid.uuid4())[:8]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index() -> str:
    """Serve the VaidyaBridge main UI."""
    return render_template("index.html", maps_key=Config.MAPS_API_KEY)


@app.route("/static/<path:filename>")
def static_files(filename: str) -> Response:
    """Serve static assets (manifest.json, icons, etc.)."""
    from flask import send_from_directory
    return send_from_directory("static", filename)


@app.route("/analyze", methods=["POST"])
def analyze() -> tuple[Response, int]:
    """
    Main analysis endpoint — full dual-pass Gemini pipeline.

    Accepts JSON body:
        text (str): Symptom description in any language.
        image_base64 (str, optional): Base64 prescription/lab image.
        language (str, optional): BCP-47 code, default 'en'.
        lat (float, optional): Latitude for pharmacy search.
        lng (float, optional): Longitude for pharmacy search.

    Returns:
        JSON with triage, extracted clinical data, ASHA instructions,
        ABDM-formatted summary, pharmacy list, and safety disclaimer.

    HTTP Status:
        200 Success | 400 Bad input | 429 Rate limited |
        500 Pipeline error | 503 Not configured
    """
    request_id = getattr(g, "request_id", "unknown")

    client_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown")
    if not check_rate_limit(client_ip):
        logger.warning("[%s] Rate limit exceeded for %s", request_id, client_ip)
        return jsonify({"error": ERROR_MESSAGES["rate_limited"], "request_id": request_id}), 429

    if not Config.GEMINI_API_KEY:
        return jsonify({"error": ERROR_MESSAGES["not_configured"], "request_id": request_id}), 503

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error": ERROR_MESSAGES["invalid_json"], "request_id": request_id}), 400

    try:
        req = parse_analysis_request(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc), "request_id": request_id}), 400

    logger.info(
        "[%s] Analysis — lang:%s image:%s location:%s",
        request_id, req.language, bool(req.image_base64), bool(req.lat),
    )

    try:
        # Google Cloud Vision: dedicated OCR pass
        ocr_text = ocr_image_with_vision(req.image_base64) if req.image_base64 else ""

        # Pass 1: Gemini multimodal extraction
        extracted = extract_health_data(req, ocr_text)

        # Pass 2: Gemini verification + hallucination guard + triage
        verified = verify_and_triage(extracted, request_id)

        # Google Cloud Translation (Gemini Flash fallback, LRU cached)
        translated = translate_text(verified.get("asha_instructions", ""), req.language)

        # Google Maps: nearby Jan Aushadhi pharmacies
        pharmacies = find_pharmacies(req.lat, req.lng) if req.lat and req.lng else []

        triage_key = verified.get("triage_level", "YELLOW")
        triage_info = TRIAGE_LEVELS.get(triage_key, TRIAGE_LEVELS["YELLOW"])

        return jsonify({
            "success": True,
            "request_id": request_id,
            "version": __version__,
            "extracted": extracted,
            "triage": {
                "level": triage_key,
                "label": triage_info["label"],
                "color": triage_info["color"],
                "reason": verified.get("triage_reason", ""),
                "recommended_action": triage_info["action"],
                "aria_label": triage_info["aria_label"],
            },
            "drug_interactions": verified.get("drug_interactions", []),
            "data_confidence": verified.get("data_confidence", "MEDIUM"),
            "flagged_concerns": verified.get("flagged_concerns", []),
            "abdm_summary": verified.get("abdm_summary", {}),
            "asha_instructions": verified.get("asha_instructions", ""),
            "asha_instructions_translated": translated,
            "pharmacies": pharmacies,
            "ocr_used": bool(ocr_text),
            "disclaimer": (
                "⚠️ NOT a medical diagnosis. "
                "Always consult a qualified doctor. "
                "Emergency: call 112."
            ),
        }), 200

    except (ExtractionError, VerificationError) as exc:
        logger.error("[%s] Pipeline error: %s", request_id, exc)
        return jsonify({"error": ERROR_MESSAGES["analysis_failed"], "request_id": request_id}), 500
    except Exception as exc:
        logger.exception("[%s] Unexpected error: %s", request_id, exc)
        return jsonify({"error": ERROR_MESSAGES["analysis_failed"], "request_id": request_id}), 500


@app.route("/health")
def health_check() -> tuple[Response, int]:
    """Health check for Cloud Run readiness/liveness probes. Never exposes keys."""
    return jsonify({
        "status": "ok",
        "service": "VaidyaBridge",
        "version": __version__,
        "gemini_configured": bool(Config.GEMINI_API_KEY),
        "maps_configured": bool(Config.MAPS_API_KEY),
    }), 200


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------
@app.errorhandler(400)
def bad_request(exc: Exception) -> tuple[Response, int]:
    return jsonify({"error": "Bad request", "detail": str(exc)}), 400

@app.errorhandler(404)
def not_found(exc: Exception) -> tuple[Response, int]:
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(413)
def request_too_large(exc: Exception) -> tuple[Response, int]:
    return jsonify({"error": ERROR_MESSAGES["request_too_large"]}), 413

@app.errorhandler(429)
def too_many_requests(exc: Exception) -> tuple[Response, int]:
    return jsonify({"error": ERROR_MESSAGES["rate_limited"]}), 429

@app.errorhandler(500)
def internal_error(exc: Exception) -> tuple[Response, int]:
    return jsonify({"error": "Internal server error"}), 500


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    logger.info("VaidyaBridge v%s starting on port %d (debug=%s)", __version__, port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
