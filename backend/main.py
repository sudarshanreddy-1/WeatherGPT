from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime
import os
import re
import time
import json
import traceback
from dotenv import load_dotenv
from groq import Groq


# =========================================================
# GROQ SETUP
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GROQ_API_KEY:
    GROQ_API_KEY = GROQ_API_KEY.strip()

client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "openai/gpt-oss-120b"


# =========================================================
# CONVERSATION MEMORY
# =========================================================

chat_sessions = {}

session_locations = {}


# =========================================================
# FASTAPI SETUP
# =========================================================

app = FastAPI(title="WeatherGPT API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# CITY → LATITUDE + LONGITUDE
# =========================================================

def get_coordinates(city):

    url = "https://geocoding-api.open-meteo.com/v1/search"

    params = {
        "name": city,
        "count": 5,
        "language": "en",
        "format": "json"
    }

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    if "results" not in data or not data["results"]:
        return None

    result = data["results"][0]

    return {
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "name": result["name"],
        "country": result.get("country", ""),
        "timezone": result.get("timezone", "auto")
    }


# =========================================================
# WEATHER CACHE
# =========================================================
#
# Each location has its own cache.
#
# Hyderabad → separate cache
# Mumbai    → separate cache
# Delhi     → separate cache
#
# Cache lasts 5 minutes.
# =========================================================

_weather_cache = {}

WEATHER_CACHE_TTL_SECONDS = 300


# =========================================================
# GET WEATHER FROM OPEN-METEO
# =========================================================

def get_weather(
    latitude,
    longitude,
    timezone="auto"
):

    # -----------------------------------------------------
    # CACHE KEY
    # -----------------------------------------------------

    cache_key = (
        round(latitude, 2),
        round(longitude, 2)
    )

    # -----------------------------------------------------
    # CHECK CACHE
    # -----------------------------------------------------

    cached = _weather_cache.get(cache_key)

    if cached is not None:

        cached_at, cached_data = cached

        age = time.time() - cached_at

        if age < WEATHER_CACHE_TTL_SECONDS:

            print(
                f"Using cached weather for "
                f"{cache_key} "
                f"(age: {age:.0f}s)"
            )

            return cached_data

        else:

            print(
                f"Cache expired for {cache_key}"
            )

    # -----------------------------------------------------
    # FETCH FRESH WEATHER
    # -----------------------------------------------------

    print(
        f"Fetching fresh weather from Open-Meteo "
        f"for {cache_key}"
    )

    url = "https://api.open-meteo.com/v1/forecast"

    params = {

        "latitude": latitude,

        "longitude": longitude,

        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "wind_speed_10m,"
            "precipitation,"
            "weather_code"
        ),

        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "precipitation_probability,"
            "precipitation,"
            "weather_code,"
            "wind_speed_10m"
        ),

        "daily": (
            "temperature_2m_max,"
            "temperature_2m_min,"
            "precipitation_probability_max,"
            "weather_code,"
            "sunrise,"
            "sunset"
        ),

        "forecast_days": 7,

        "timezone": timezone
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        response.raise_for_status()

        data = response.json()

    except requests.exceptions.HTTPError as error:

        status_code = (
            error.response.status_code
            if error.response is not None
            else None
        )

        if status_code == 429:

            print(
                "Open-Meteo rate limit reached. "
                "Not retrying."
            )

            raise Exception(
                "Open-Meteo is temporarily rate limiting "
                "requests. Please wait a little and try again."
            )

        raise

    # -----------------------------------------------------
    # SAVE TO CACHE
    # -----------------------------------------------------

    _weather_cache[cache_key] = (
        time.time(),
        data
    )

    print(
        f"Weather cached for {cache_key} "
        f"for 5 minutes."
    )

    return data


# =========================================================
# WEATHER FROM EXACT COORDINATES
# =========================================================

def get_weather_for_coordinates(
    latitude,
    longitude,
    date="today",
    time_of_day="all_day"
):

    weather_data = get_weather(
        latitude,
        longitude,
        "auto"
    )

    daily_dates = weather_data["daily"]["time"]

    # -----------------------------------------------------
    # DETERMINE DATE
    # -----------------------------------------------------

    if date == "today":

        target_date = daily_dates[0]

    elif date == "tomorrow":

        target_date = daily_dates[1]

    else:

        target_date = date

    # -----------------------------------------------------
    # CHECK DATE
    # -----------------------------------------------------

    if target_date not in daily_dates:

        return {
            "success": False,
            "error": (
                f"Weather data is not available "
                f"for {date}."
            )
        }

    day_index = daily_dates.index(
        target_date
    )

    # -----------------------------------------------------
    # DAILY WEATHER
    # -----------------------------------------------------

    daily_result = {

        "date":
            target_date,

        "temperature_max":
            weather_data["daily"]
            ["temperature_2m_max"]
            [day_index],

        "temperature_min":
            weather_data["daily"]
            ["temperature_2m_min"]
            [day_index],

        "rain_probability":
            weather_data["daily"]
            ["precipitation_probability_max"]
            [day_index],

        "weather_code":
            weather_data["daily"]
            ["weather_code"]
            [day_index],

        "sunrise":
            weather_data["daily"]
            ["sunrise"]
            [day_index],

        "sunset":
            weather_data["daily"]
            ["sunset"]
            [day_index]
    }

    # =====================================================
    # HOURLY WEATHER
    # =====================================================

    hourly_result = []

    if time_of_day != "all_day":

        time_ranges = {

            "morning": (6, 12),

            "afternoon": (12, 17),

            "evening": (17, 21),

            "night": (21, 24)
        }

        if time_of_day not in time_ranges:

            return {

                "success": False,

                "error": (
                    "Invalid time_of_day. "
                    "Use morning, afternoon, "
                    "evening, night, or all_day."
                )
            }

        start_hour, end_hour = \
            time_ranges[time_of_day]

        for i, time_string in enumerate(
            weather_data["hourly"]["time"]
        ):

            if not time_string.startswith(
                target_date
            ):

                continue

            hour = datetime.fromisoformat(
                time_string
            ).hour

            if start_hour <= hour < end_hour:

                hourly_result.append({

                    "time":
                        time_string,

                    "temperature":
                        weather_data["hourly"]
                        ["temperature_2m"][i],

                    "feels_like":
                        weather_data["hourly"]
                        ["apparent_temperature"][i],

                    "humidity":
                        weather_data["hourly"]
                        ["relative_humidity_2m"][i],

                    "rain_probability":
                        weather_data["hourly"]
                        ["precipitation_probability"][i],

                    "precipitation":
                        weather_data["hourly"]
                        ["precipitation"][i],

                    "wind_speed":
                        weather_data["hourly"]
                        ["wind_speed_10m"][i],

                    "weather_code":
                        weather_data["hourly"]
                        ["weather_code"][i]
                })

    # =====================================================
    # RETURN
    # =====================================================

    return {

        "success": True,

        "daily":
            daily_result,

        "hourly":
            hourly_result
    }


# =========================================================
# WEATHER FROM CITY
# =========================================================

def get_weather_for_city(
    city,
    date="today",
    time_of_day="all_day"
):

    location = get_coordinates(city)

    if location is None:

        return {

            "success": False,

            "error":
                f"Could not find location: {city}"
        }

    result = get_weather_for_coordinates(

        location["latitude"],

        location["longitude"],

        date,

        time_of_day
    )

    result["location"] = location

    return result


# =========================================================
# GROQ WEATHER TOOL SCHEMA
# =========================================================

WEATHER_TOOL_SCHEMA = {

    "type": "function",

    "function": {

        "name": "get_weather",

        "description": (
            "Get real live weather information. "
            "If the user does not mention a city and "
            "browser GPS is available, use exactly "
            "CURRENT_USER_LOCATION."
        ),

        "parameters": {

            "type": "object",

            "properties": {

                "location": {

                    "type": "string",

                    "description": (
                        "City name or exactly "
                        "CURRENT_USER_LOCATION."
                    )
                },

                "date": {

                    "type": "string",

                    "description": (
                        "today, tomorrow, or "
                        "YYYY-MM-DD."
                    )
                },

                "time_of_day": {

                    "type": "string",

                    "enum": [
                        "morning",
                        "afternoon",
                        "evening",
                        "night",
                        "all_day"
                    ]
                }
            },

            "required": [
                "location",
                "date",
                "time_of_day"
            ]
        }
    }
}


# =========================================================
# LOCATION-AWARE WEATHER TOOL
# =========================================================

def create_weather_tool(
    user_latitude=None,
    user_longitude=None
):

    def get_weather_tool(
        location: str,
        date: str,
        time_of_day: str
    ) -> dict:

        # -------------------------------------------------
        # CURRENT USER LOCATION
        # -------------------------------------------------

        if (

            location ==
            "CURRENT_USER_LOCATION"

            and user_latitude is not None

            and user_longitude is not None

        ):

            return get_weather_for_coordinates(

                user_latitude,

                user_longitude,

                date,

                time_of_day
            )

        # -------------------------------------------------
        # CITY LOCATION
        # -------------------------------------------------

        return get_weather_for_city(

            location,

            date,

            time_of_day
        )

    return get_weather_tool


# =========================================================
# SYSTEM PROMPT
# =========================================================

SYSTEM_PROMPT = (

    "You are WeatherGPT, a conversational AI "
    "weather assistant. "

    "Always use the weather tool for live weather "
    "questions. "

    "Never invent current or forecast weather. "

    "Remember the user's previously mentioned "
    "location within the conversation. "

    "If the user asks a follow-up such as "
    "'what about tomorrow?', use the same location. "

    "If the user does not mention a city and "
    "browser location is available, use exactly "
    "CURRENT_USER_LOCATION. "

    "Do not repeatedly ask the user for location. "

    "If the user explicitly mentions another city, "
    "use that city instead. "

    "Keep answers natural, clear and concise."
)


# =========================================================
# GROQ RETRY
# =========================================================

MAX_RETRIES = 3

DEFAULT_BACKOFF_SECONDS = 3


def _is_rate_limit_error(error):

    message = str(error)

    return (

        "429" in message

        or "rate_limit" in message.lower()

        or "rate limit" in message.lower()
    )


def _extract_retry_delay(error):

    message = str(error)

    match = re.search(

        r"retry(?:[-_ ]?after)?['\"]?"
        r"\s*[:\s]\s*['\"]?"
        r"(\d+(?:\.\d+)?)",

        message,

        re.IGNORECASE
    )

    if match:

        return float(match.group(1)) + 1

    return DEFAULT_BACKOFF_SECONDS


def create_completion_with_retry(**kwargs):

    last_error = None

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            return client.chat.completions.create(
                **kwargs
            )

        except Exception as error:

            last_error = error

            if not _is_rate_limit_error(error):

                raise

            if attempt == MAX_RETRIES:

                break

            delay = _extract_retry_delay(
                error
            )

            print(
                f"Groq rate limited "
                f"(attempt {attempt}/{MAX_RETRIES}). "
                f"Retrying in {delay:.1f}s..."
            )

            time.sleep(delay)

    raise last_error


# =========================================================
# GROQ CHAT + TOOL LOOP
# =========================================================

def run_chat_turn(
    messages,
    weather_tool_fn
):

    MAX_TOOL_ITERATIONS = 5

    for iteration in range(
        MAX_TOOL_ITERATIONS
    ):

        response = create_completion_with_retry(

            model=MODEL_NAME,

            messages=messages,

            tools=[
                WEATHER_TOOL_SCHEMA
            ]
        )

        message = response.choices[0].message

        messages.append(message)

        tool_calls = getattr(
            message,
            "tool_calls",
            None
        )

        # -------------------------------------------------
        # FINAL ANSWER
        # -------------------------------------------------

        if not tool_calls:

            return (
                message.content,
                messages
            )

        # -------------------------------------------------
        # TOOL CALLS
        # -------------------------------------------------

        for tool_call in tool_calls:

            try:

                args = json.loads(
                    tool_call.function.arguments
                )

                print(
                    "WeatherGPT calling tool:",
                    args
                )

                result = weather_tool_fn(

                    location=args.get(
                        "location",
                        "CURRENT_USER_LOCATION"
                    ),

                    date=args.get(
                        "date",
                        "today"
                    ),

                    time_of_day=args.get(
                        "time_of_day",
                        "all_day"
                    )
                )

                print(
                    "WeatherGPT tool result:",
                    result
                )

            except Exception as tool_error:

                print(
                    "WeatherGPT tool call FAILED:",
                    tool_error
                )

                traceback.print_exc()

                result = {

                    "success": False,

                    "error":
                        str(tool_error)
                }

            messages.append({

                "role": "tool",

                "tool_call_id":
                    tool_call.id,

                "name":
                    tool_call.function.name,

                "content":
                    json.dumps(result)
            })

    # =====================================================
    # SAFETY FALLBACK
    # =====================================================

    final_response = create_completion_with_retry(

        model=MODEL_NAME,

        messages=messages,

        tools=[
            WEATHER_TOOL_SCHEMA
        ],

        tool_choice="none"
    )

    final_message = \
        final_response.choices[0].message

    messages.append(
        final_message
    )

    return (
        final_message.content,
        messages
    )


# =========================================================
# HOME
# =========================================================

@app.get("/")
def home():

    return {

        "message":
            "WeatherGPT API is running"
    }


# =========================================================
# WEATHER ENDPOINT
# =========================================================

@app.get("/weather")
def weather(

    city: str,

    date: str = "today",

    time_of_day: str = "all_day"

):

    return get_weather_for_city(

        city,

        date,

        time_of_day
    )


# =========================================================
# CHAT ENDPOINT
# =========================================================

@app.post("/chat")
def chat(

    message: str,

    session_id: str = "default",

    latitude: float = None,

    longitude: float = None

):

    # -----------------------------------------------------
    # CREATE WEATHER TOOL
    # -----------------------------------------------------

    weather_tool = create_weather_tool(

        latitude,

        longitude
    )

    # -----------------------------------------------------
    # CHECK LOCATION
    # -----------------------------------------------------

    old_location = session_locations.get(
        session_id
    )

    new_location = (
        latitude,
        longitude
    )

    # -----------------------------------------------------
    # CREATE / RESET SESSION
    # -----------------------------------------------------

    if (

        session_id not in chat_sessions

        or old_location != new_location

    ):

        chat_sessions[session_id] = [

            {
                "role": "system",
                "content": SYSTEM_PROMPT
            }

        ]

        session_locations[
            session_id
        ] = new_location

    messages = chat_sessions[
        session_id
    ]

    # -----------------------------------------------------
    # LOCATION CONTEXT
    # -----------------------------------------------------

    if (

        latitude is not None

        and longitude is not None

    ):

        final_message = (

            "The user's browser has provided "
            "their current location. "

            "If the user does not explicitly "
            "mention another city, use "
            "CURRENT_USER_LOCATION. "

            f"Current latitude: {latitude}. "

            f"Current longitude: {longitude}. "

            f"User's message: {message}"

        )

    else:

        final_message = message

    messages.append({

        "role": "user",

        "content": final_message
    })

    # -----------------------------------------------------
    # RUN GROQ
    # -----------------------------------------------------

    try:

        answer_text, messages = run_chat_turn(

            messages,

            weather_tool
        )

        chat_sessions[
            session_id
        ] = messages

        return {

            "response":
                answer_text,

            "session_id":
                session_id,

            "location": {

                "latitude":
                    latitude,

                "longitude":
                    longitude
            }
        }

    except Exception as error:

        print(
            "WeatherGPT error:",
            error
        )

        traceback.print_exc()

        if _is_rate_limit_error(error):

            reply_text = (

                "WeatherGPT is getting a lot "
                "of requests right now. "
                "Please wait a few seconds "
                "and try again."
            )

        else:

            reply_text = (

                "I couldn't retrieve the "
                "weather right now. "
                "Please try again."
            )

        return {

            "response":
                reply_text,

            "session_id":
                session_id,

            "location": {

                "latitude":
                    latitude,

                "longitude":
                    longitude
            },

            "error":
                str(error)
        }