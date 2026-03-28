"""Debug script to test Gemini extraction with gemini-2.5-pro."""
import os, json, traceback

# Load .env
with open(".env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

try:
    from google import genai
    from google.genai import types as genai_types
    import re

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    text = "Meri maa ko 3 din se bukhaar hai 103F, pet mein dard hai, ulti ho rahi hai. Wo paracetamol 500mg aur ibuprofen dono le rahi hai. BP 150/95 hai. Age 58 saal."
    prompt_text = (
        "You are a clinical data extraction assistant for Indian rural healthcare.\n"
        f"Patient input: {text}\n\n"
        "Return ONLY valid JSON:\n"
        '{"patient_complaints":["fever"],"duration":"3 days","medicines_mentioned":["paracetamol"],'
        '"lab_values":{},"allergies":[],"age_mentioned":58,"gender_mentioned":null,'
        '"vital_signs":{"bp":"150/95","temp":"103F","pulse":null},"raw_summary":"summary"}'
    )

    response = client.models.generate_content(
        model="gemini-2.5-pro",
        contents=[genai_types.Part.from_text(text=prompt_text)],
    )
    raw = response.text
    print("Raw response:", raw)

except Exception as e:
    print("EXTRACTION ERROR:", type(e).__name__, str(e))
    traceback.print_exc()
