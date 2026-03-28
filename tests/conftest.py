"""
Shared pytest fixtures for VaidyaBridge test suite.
"""
import os
import pytest

os.environ.setdefault("GEMINI_API_KEY", "test-gemini-key-placeholder")
os.environ.setdefault("GOOGLE_MAPS_API_KEY", "test-maps-key-placeholder")


@pytest.fixture(scope="session")
def app_instance():
    from app import app as flask_app
    flask_app.config["TESTING"] = True
    flask_app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    return flask_app


@pytest.fixture
def client(app_instance):
    # Reset rate limiter before each test so 127.0.0.1 is never throttled
    import app as app_module
    app_module._rate_store.clear()
    with app_instance.test_client() as c:
        yield c


@pytest.fixture
def valid_text_payload():
    return {"text": "Patient has fever 102F and headache for 2 days", "language": "en"}


@pytest.fixture
def valid_hindi_payload():
    return {"text": "Mujhe bukhaar hai aur sar mein dard hai", "language": "hi"}


@pytest.fixture
def valid_image_payload():
    import base64
    dummy = base64.b64encode(b"fake-jpeg-data-for-testing-purposes").decode()
    return {"text": "Prescription from doctor", "image_base64": dummy, "language": "en"}


@pytest.fixture
def payload_with_location():
    return {"text": "Stomach pain since yesterday", "language": "en",
            "lat": 12.9716, "lng": 77.5946}
