import os
from dotenv import load_dotenv


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")

if GROQ_API_KEY:
    GROQ_API_KEY = GROQ_API_KEY.strip()

if WEATHER_API_KEY:
    WEATHER_API_KEY = WEATHER_API_KEY.strip()


# =========================================================
# GROQ CONFIGURATION
# =========================================================

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not configured."
    )

MODEL_NAME = "openai/gpt-oss-120b"