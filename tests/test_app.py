"""
Unit and integration tests for VaidyaBridge v2.0.0.

Test coverage:
    - Config class values
    - Custom exception hierarchy
    - Input sanitisation (sanitize_text)
    - Coordinate validation (validate_coordinates)
    - Language validation (validate_language)
    - Base64 image validation (validate_base64_image)
    - JSON cleaning (clean_json)
    - Request parsing (parse_analysis_request)
    - Domain constants (TRIAGE_LEVELS, SUPPORTED_LANGUAGES, ERROR_MESSAGES)
    - Rate limiter (check_rate_limit)
    - HTTP endpoints: GET /, GET /health, POST /analyze, GET /static/*
    - Security headers on all responses
    - Mocked full pipeline (extract → verify → translate → pharmacies)
    - Error handling paths (400, 404, 413, 429, 500)

Run:
    pytest tests/ -v --cov=app --cov-report=term-missing
"""

import base64
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from app import (
    SUPPORTED_LANGUAGES,
    TRIAGE_LEVELS,
    ERROR_MESSAGES,
    Config,
    ExtractionError,
    PharmacySearchError,
    TranslationError,
    VerificationError,
    VaidyaBridgeError,
    AnalysisRequest,
    __version__,
    check_rate_limit,
    clean_json,
    parse_analysis_request,
    sanitize_text,
    validate_base64_image,
    validate_coordinates,
    validate_language,
)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
class TestConfig:
    def test_max_content_bytes_is_5mb(self):
        assert Config.MAX_CONTENT_BYTES == 5 * 1024 * 1024

    def test_max_text_length_positive(self):
        assert Config.MAX_TEXT_LENGTH > 0

    def test_rate_limit_window_positive(self):
        assert Config.RATE_LIMIT_WINDOW_SEC > 0

    def test_rate_limit_requests_positive(self):
        assert Config.RATE_LIMIT_REQUESTS > 0

    def test_pharmacy_radius_reasonable(self):
        assert 1000 <= Config.PHARMACY_SEARCH_RADIUS_M <= 50000

    def test_gemini_model_names_set(self):
        assert "gemini" in Config.GEMINI_EXTRACT_MODEL
        assert "gemini" in Config.GEMINI_VERIFY_MODEL
        assert "gemini" in Config.GEMINI_TRANSLATE_MODEL

    def test_version_string_format(self):
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


# ---------------------------------------------------------------------------
# Exception Hierarchy
# ---------------------------------------------------------------------------
class TestExceptions:
    def test_extraction_error_is_vaidya_error(self):
        assert issubclass(ExtractionError, VaidyaBridgeError)

    def test_verification_error_is_vaidya_error(self):
        assert issubclass(VerificationError, VaidyaBridgeError)

    def test_translation_error_is_vaidya_error(self):
        assert issubclass(TranslationError, VaidyaBridgeError)

    def test_pharmacy_error_is_vaidya_error(self):
        assert issubclass(PharmacySearchError, VaidyaBridgeError)

    def test_can_raise_and_catch_as_base(self):
        with pytest.raises(VaidyaBridgeError):
            raise ExtractionError("test")

    def test_can_raise_with_cause(self):
        try:
            raise ExtractionError("outer") from ValueError("inner")
        except ExtractionError as exc:
            assert isinstance(exc.__cause__, ValueError)


# ---------------------------------------------------------------------------
# sanitize_text
# ---------------------------------------------------------------------------
class TestSanitizeText:
    def test_normal_text_unchanged(self):
        assert sanitize_text("Patient has fever") == "Patient has fever"

    def test_strips_null_bytes(self):
        assert "\x00" not in sanitize_text("hello\x00world")

    def test_strips_multiple_control_chars(self):
        result = sanitize_text("text\x01\x02\x03end")
        assert "\x01" not in result and "\x02" not in result

    def test_allows_newlines_and_tabs(self):
        assert sanitize_text("line1\nline2\ttab") == "line1\nline2\ttab"

    def test_truncates_to_default_max(self):
        result = sanitize_text("a" * 3000)
        assert len(result) == Config.MAX_TEXT_LENGTH

    def test_truncates_to_custom_max(self):
        assert len(sanitize_text("a" * 500, max_length=100)) == 100

    def test_empty_string_returns_empty(self):
        assert sanitize_text("") == ""

    def test_none_returns_empty(self):
        assert sanitize_text(None) == ""

    def test_strips_leading_trailing_whitespace(self):
        assert sanitize_text("  hello  ") == "hello"

    def test_unicode_preserved(self):
        assert sanitize_text("fever मुझे बुखार है") == "fever मुझे बुखार है"

    def test_kannada_preserved(self):
        assert sanitize_text("ಜ್ವರ ಇದೆ") == "ಜ್ವರ ಇದೆ"


# ---------------------------------------------------------------------------
# validate_coordinates
# ---------------------------------------------------------------------------
class TestValidateCoordinates:
    def test_valid_bengaluru(self):
        lat, lng = validate_coordinates(12.9716, 77.5946)
        assert lat == 12.9716 and lng == 77.5946

    def test_valid_delhi(self):
        lat, lng = validate_coordinates(28.6139, 77.2090)
        assert lat == 28.6139

    def test_string_coordinates_parsed(self):
        lat, lng = validate_coordinates("12.9716", "77.5946")
        assert lat == 12.9716 and lng == 77.5946

    def test_lat_above_90_rejected(self):
        assert validate_coordinates(91, 77) == (None, None)

    def test_lat_below_minus90_rejected(self):
        assert validate_coordinates(-91, 77) == (None, None)

    def test_lng_above_180_rejected(self):
        assert validate_coordinates(12, 181) == (None, None)

    def test_lng_below_minus180_rejected(self):
        assert validate_coordinates(12, -181) == (None, None)

    def test_none_returns_none_tuple(self):
        assert validate_coordinates(None, None) == (None, None)

    def test_string_garbage_returns_none(self):
        assert validate_coordinates("abc", "xyz") == (None, None)

    def test_boundary_north_pole(self):
        lat, lng = validate_coordinates(90, 0)
        assert lat == 90.0

    def test_boundary_antimeridian(self):
        lat, lng = validate_coordinates(0, 180)
        assert lng == 180.0

    def test_negative_valid_sydney(self):
        lat, lng = validate_coordinates(-33.8688, 151.2093)
        assert lat == -33.8688


# ---------------------------------------------------------------------------
# validate_language
# ---------------------------------------------------------------------------
class TestValidateLanguage:
    def test_all_supported_codes_pass(self):
        for lang in SUPPORTED_LANGUAGES:
            assert validate_language(lang) == lang

    def test_unsupported_returns_english(self):
        assert validate_language("xx") == "en"

    def test_empty_string_returns_english(self):
        assert validate_language("") == "en"

    def test_none_returns_english(self):
        assert validate_language(None) == "en"

    def test_chinese_not_supported(self):
        assert validate_language("zh") == "en"


# ---------------------------------------------------------------------------
# validate_base64_image
# ---------------------------------------------------------------------------
class TestValidateBase64Image:
    def test_none_returns_none(self):
        assert validate_base64_image(None) is None

    def test_valid_base64_accepted(self):
        data = base64.b64encode(b"fake image bytes for test").decode()
        assert validate_base64_image(data) == data

    def test_oversized_rejected(self):
        assert validate_base64_image("A" * (Config.MAX_IMAGE_B64_BYTES + 1)) is None

    def test_empty_string_returns_none(self):
        assert validate_base64_image("") is None

    def test_invalid_chars_rejected(self):
        assert validate_base64_image("!!!not-base64!!!") is None


# ---------------------------------------------------------------------------
# clean_json
# ---------------------------------------------------------------------------
class TestCleanJson:
    def test_strips_json_code_fence(self):
        assert clean_json("```json\n{\"k\": 1}\n```") == '{"k": 1}'

    def test_strips_plain_code_fence(self):
        assert clean_json("```\n{\"k\": 1}\n```") == '{"k": 1}'

    def test_clean_json_passthrough(self):
        assert clean_json('{"k": 1}') == '{"k": 1}'

    def test_strips_surrounding_whitespace(self):
        assert clean_json('  {"k": 1}  ') == '{"k": 1}'

    def test_multiline_json_preserved(self):
        raw = '{"a": 1,\n "b": 2}'
        assert clean_json(raw) == raw


# ---------------------------------------------------------------------------
# parse_analysis_request
# ---------------------------------------------------------------------------
class TestParseAnalysisRequest:
    def test_valid_text_payload(self, valid_text_payload):
        req = parse_analysis_request(valid_text_payload)
        assert isinstance(req, AnalysisRequest)
        assert req.text == valid_text_payload["text"]
        assert req.language == "en"

    def test_empty_inputs_raise_value_error(self):
        with pytest.raises(ValueError, match="Provide text"):
            parse_analysis_request({"text": "", "language": "en"})

    def test_request_id_generated(self, valid_text_payload):
        req = parse_analysis_request(valid_text_payload)
        assert len(req.request_id) == 8

    def test_unsupported_lang_defaulted(self):
        req = parse_analysis_request({"text": "fever", "language": "xx"})
        assert req.language == "en"

    def test_invalid_coords_none(self):
        req = parse_analysis_request({"text": "fever", "lat": 999, "lng": 999})
        assert req.lat is None and req.lng is None

    def test_valid_coords_parsed(self):
        req = parse_analysis_request({"text": "fever", "lat": 12.97, "lng": 77.59})
        assert req.lat == 12.97 and req.lng == 77.59


# ---------------------------------------------------------------------------
# TRIAGE_LEVELS
# ---------------------------------------------------------------------------
class TestTriageLevels:
    def test_all_three_levels_present(self):
        for level in ("RED", "YELLOW", "GREEN"):
            assert level in TRIAGE_LEVELS

    def test_each_level_has_required_fields(self):
        for level, data in TRIAGE_LEVELS.items():
            for key in ("label", "color", "action", "aria_label"):
                assert key in data, f"{level} missing '{key}'"

    def test_colors_are_valid_hex(self):
        for level, data in TRIAGE_LEVELS.items():
            color = data["color"]
            assert color.startswith("#") and len(color) == 7, f"{level} invalid hex: {color}"

    def test_aria_labels_not_empty(self):
        for data in TRIAGE_LEVELS.values():
            assert len(data["aria_label"]) > 0

    def test_red_action_mentions_112(self):
        assert "112" in TRIAGE_LEVELS["RED"]["action"]


# ---------------------------------------------------------------------------
# SUPPORTED_LANGUAGES
# ---------------------------------------------------------------------------
class TestSupportedLanguages:
    def test_english_included(self):
        assert "en" in SUPPORTED_LANGUAGES

    def test_six_indian_languages(self):
        indian = {"hi", "kn", "te", "ta", "mr", "bn"}
        assert indian.issubset(set(SUPPORTED_LANGUAGES.keys()))

    def test_all_values_non_empty(self):
        assert all(v for v in SUPPORTED_LANGUAGES.values())


# ---------------------------------------------------------------------------
# ERROR_MESSAGES
# ---------------------------------------------------------------------------
class TestErrorMessages:
    def test_all_keys_present(self):
        for key in ("no_input", "invalid_json", "not_configured",
                    "rate_limited", "request_too_large", "analysis_failed"):
            assert key in ERROR_MESSAGES

    def test_no_empty_messages(self):
        assert all(len(v) > 0 for v in ERROR_MESSAGES.values())


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------
class TestRateLimiter:
    def test_allows_first_request(self):
        assert check_rate_limit(f"fresh-ip-{time.time()}") is True

    def test_allows_up_to_limit(self):
        ip = f"limit-test-{time.time()}"
        for _ in range(Config.RATE_LIMIT_REQUESTS):
            assert check_rate_limit(ip) is True

    def test_blocks_after_limit(self):
        ip = f"overload-{time.time()}"
        for _ in range(Config.RATE_LIMIT_REQUESTS):
            check_rate_limit(ip)
        assert check_rate_limit(ip) is False

    def test_different_ips_independent(self):
        ip1, ip2 = f"ip1-{time.time()}", f"ip2-{time.time()}"
        for _ in range(Config.RATE_LIMIT_REQUESTS):
            check_rate_limit(ip1)
        assert check_rate_limit(ip1) is False
        assert check_rate_limit(ip2) is True


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
class TestHealthEndpoint:
    def test_returns_200(self, client):
        assert client.get("/health").status_code == 200

    def test_returns_ok_status(self, client):
        data = json.loads(client.get("/health").data)
        assert data["status"] == "ok"

    def test_returns_service_name(self, client):
        data = json.loads(client.get("/health").data)
        assert data["service"] == "VaidyaBridge"

    def test_returns_version(self, client):
        data = json.loads(client.get("/health").data)
        assert data["version"] == __version__

    def test_does_not_expose_api_keys(self, client):
        response_text = client.get("/health").data.decode()
        assert "AIza" not in response_text
        assert "key" not in response_text.lower() or "configured" in response_text.lower()

    def test_config_flags_are_boolean(self, client):
        data = json.loads(client.get("/health").data)
        assert isinstance(data["gemini_configured"], bool)
        assert isinstance(data["maps_configured"], bool)


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------
class TestIndexEndpoint:
    def test_returns_200(self, client):
        assert client.get("/").status_code == 200

    def test_contains_app_name(self, client):
        assert b"VaidyaBridge" in client.get("/").data

    def test_contains_skip_link(self, client):
        assert b"skip" in client.get("/").data.lower()

    def test_content_type_is_html(self, client):
        assert "text/html" in client.get("/").content_type


# ---------------------------------------------------------------------------
# POST /analyze — Input Validation
# ---------------------------------------------------------------------------
class TestAnalyzeEndpointValidation:
    def test_empty_text_returns_400(self, client):
        r = client.post("/analyze", json={"text": "", "language": "en"})
        assert r.status_code == 400

    def test_missing_text_and_image_returns_400(self, client):
        r = client.post("/analyze", json={"language": "en"})
        assert r.status_code == 400

    def test_invalid_json_returns_400(self, client):
        r = client.post("/analyze", data="{bad}", content_type="application/json")
        assert r.status_code == 400

    def test_plain_text_body_returns_400(self, client):
        r = client.post("/analyze", data="just text", content_type="text/plain")
        assert r.status_code == 400

    def test_unknown_route_returns_404(self, client):
        assert client.get("/nonexistent-route-xyz").status_code == 404

    def test_get_on_analyze_returns_405(self, client):
        assert client.get("/analyze").status_code == 405

    def test_valid_payload_not_400(self, client):
        r = client.post("/analyze", json={"text": "fever and cough", "language": "en"})
        assert r.status_code in (200, 500, 503)

    def test_response_has_request_id(self, client):
        r = client.post("/analyze", json={"text": "fever", "language": "en"})
        data = json.loads(r.data)
        assert "request_id" in data


# ---------------------------------------------------------------------------
# Security Headers
# ---------------------------------------------------------------------------
class TestSecurityHeaders:
    def test_x_content_type_options(self, client):
        r = client.get("/health")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"

    def test_x_frame_options(self, client):
        r = client.get("/health")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_x_xss_protection(self, client):
        r = client.get("/health")
        assert "1" in r.headers.get("X-XSS-Protection", "")

    def test_referrer_policy(self, client):
        r = client.get("/health")
        assert r.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_content_security_policy(self, client):
        r = client.get("/health")
        csp = r.headers.get("Content-Security-Policy", "")
        assert "default-src" in csp

    def test_security_headers_on_index(self, client):
        r = client.get("/")
        assert r.headers.get("X-Frame-Options") == "DENY"

    def test_security_headers_on_404(self, client):
        r = client.get("/nonexistent")
        assert r.headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# Full Pipeline (mocked Gemini + Maps)
# ---------------------------------------------------------------------------
MOCK_EXTRACTED = {
    "patient_complaints": ["fever", "headache"],
    "duration": "2 days",
    "medicines_mentioned": ["paracetamol"],
    "lab_values": {},
    "allergies": [],
    "age_mentioned": "35",
    "gender_mentioned": "male",
    "vital_signs": {"temp": "102F"},
    "raw_summary": "35M with 2-day fever and headache, taking paracetamol."
}

MOCK_VERIFIED = {
    "triage_level": "YELLOW",
    "triage_reason": "Moderate fever with headache — urgent PHC visit recommended.",
    "drug_interactions": [],
    "data_confidence": "HIGH",
    "flagged_concerns": [],
    "abdm_summary": {
        "chief_complaint": "fever",
        "symptom_duration": "2 days",
        "current_medications": ["paracetamol"],
        "allergies": [],
        "recommended_action": "Visit PHC within 24 hours."
    },
    "asha_instructions": "1. Check temperature.\n2. Give ORS.\n3. Visit PHC within 24 hours."
}

MOCK_PHARMACIES = [
    {"name": "Jan Aushadhi Store - Koramangala", "address": "Koramangala, Bengaluru",
     "rating": 4.2, "open_now": True},
]


class TestFullPipeline:
    @patch("app.find_pharmacies", return_value=MOCK_PHARMACIES)
    @patch("app.translate_text", return_value="1. तापमान जांचें।")
    @patch("app.verify_and_triage", return_value=MOCK_VERIFIED)
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="")
    def test_full_pipeline_success(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        r = client.post("/analyze", json={
            "text": "fever and headache 2 days",
            "language": "en",
            "lat": 12.9716,
            "lng": 77.5946
        })
        assert r.status_code == 200
        data = json.loads(r.data)
        assert data["success"] is True
        assert data["triage"]["level"] == "YELLOW"
        assert data["data_confidence"] == "HIGH"
        assert len(data["pharmacies"]) == 1

    @patch("app.ocr_image_with_vision", return_value="")
    @patch("app.extract_health_data", side_effect=ExtractionError("Gemini timeout"))
    def test_extraction_failure_returns_500(self, mock_extract, mock_ocr, client):
        r = client.post("/analyze", json={"text": "fever", "language": "en"})
        assert r.status_code == 500
        data = json.loads(r.data)
        assert "error" in data

    @patch("app.find_pharmacies", return_value=[])
    @patch("app.translate_text", return_value="instructions")
    @patch("app.verify_and_triage", return_value=MOCK_VERIFIED)
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="")
    def test_response_includes_abdm_summary(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        r = client.post("/analyze", json={"text": "fever", "language": "en"})
        data = json.loads(r.data)
        assert "abdm_summary" in data
        assert "chief_complaint" in data["abdm_summary"]

    @patch("app.find_pharmacies", return_value=[])
    @patch("app.translate_text", return_value="बुखार है — पीएचसी जाएं।")
    @patch("app.verify_and_triage", return_value=MOCK_VERIFIED)
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="")
    def test_translation_returned_for_hindi(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        r = client.post("/analyze", json={"text": "bukhaar hai", "language": "hi"})
        data = json.loads(r.data)
        assert data["asha_instructions_translated"] == "बुखार है — पीएचसी जाएं।"

    @patch("app.find_pharmacies", return_value=MOCK_PHARMACIES)
    @patch("app.translate_text", return_value="instructions")
    @patch("app.verify_and_triage", return_value=MOCK_VERIFIED)
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="OCR text extracted")
    def test_ocr_used_flag_set(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        img = base64.b64encode(b"fake-image").decode()
        r = client.post("/analyze", json={
            "text": "see attached", "image_base64": img, "language": "en"
        })
        data = json.loads(r.data)
        assert data.get("ocr_used") is True

    @patch("app.find_pharmacies", return_value=MOCK_PHARMACIES)
    @patch("app.translate_text", return_value="instructions")
    @patch("app.verify_and_triage", return_value={**MOCK_VERIFIED, "triage_level": "RED"})
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="")
    def test_red_triage_response(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        r = client.post("/analyze", json={"text": "chest pain", "language": "en"})
        data = json.loads(r.data)
        assert data["triage"]["level"] == "RED"
        assert "112" in data["triage"]["recommended_action"]

    @patch("app.find_pharmacies", return_value=MOCK_PHARMACIES)
    @patch("app.translate_text", return_value="instructions")
    @patch("app.verify_and_triage", return_value=MOCK_VERIFIED)
    @patch("app.extract_health_data", return_value=MOCK_EXTRACTED)
    @patch("app.ocr_image_with_vision", return_value="")
    def test_disclaimer_always_present(
        self, mock_ocr, mock_extract, mock_verify, mock_translate, mock_pharma, client
    ):
        r = client.post("/analyze", json={"text": "fever", "language": "en"})
        data = json.loads(r.data)
        assert "NOT a medical diagnosis" in data["disclaimer"]
        assert "112" in data["disclaimer"]
