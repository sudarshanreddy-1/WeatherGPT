from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime
import os
import re
import time
import json
import traceback
from threading import Lock
from dotenv import load_dotenv
from groq import Groq


# =========================================================
# ENVIRONMENT
# =========================================================

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if GROQ_API_KEY:
    GROQ_API_KEY = GROQ_API_KEY.strip()


# =========================================================
# GROQ SETUP
# =========================================================

if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not configured."
    )

client = Groq(
    api_key=GROQ_API_KEY
)

MODEL_NAME = "openai/gpt-oss-120b"


# =========================================================
# CONVERSATION MEMORY
# =========================================================

chat_sessions = {}

session_locations = {}


# =========================================================
# FASTAPI SETUP
# =========================================================

app = FastAPI(
    title="WeatherGPT API"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# WEATHER / GEOCODING CACHE
# =========================================================

_weather_cache = {}
_weather_cache_locks = {}
_geocode_cache = {}
_cache_lock = Lock()

# GFS updates every few hours, so a 15-minute application cache
# dramatically reduces repeated upstream requests.
WEATHER_CACHE_TTL_SECONDS = 900
GEOCODE_CACHE_TTL_SECONDS = 3600


# =========================================================
# OPEN-METEO GEOCODING
# =========================================================

OPEN_METEO_GEOCODING_URL = (
    "https://geocoding-api.open-meteo.com/v1/search"
)

OPEN_METEO_GFS_URL = (
    "https://api.open-meteo.com/v1/gfs"
)


def get_coordinates(city):

    """Resolve a city name to coordinates using Open-Meteo."""

    cache_key = city.strip().lower()
    cached = _geocode_cache.get(cache_key)

    if cached is not None:
        cached_at, cached_data = cached
        if time.time() - cached_at < GEOCODE_CACHE_TTL_SECONDS:
            return cached_data

    response = requests.get(
        OPEN_METEO_GEOCODING_URL,
        params={
            "name": city,
            "count": 1,
            "language": "en",
            "format": "json"
        },
        timeout=10
    )
    response.raise_for_status()

    data = response.json()
    results = data.get("results") or []
    if not results:
        return None

    result = results[0]
    location = {
        "latitude": result["latitude"],
        "longitude": result["longitude"],
        "name": result.get("name", city),
        "country": result.get("country", ""),
        "timezone": result.get("timezone", "auto")
    }

    _geocode_cache[cache_key] = (time.time(), location)
    return location


# =========================================================
# WMO WEATHER CODE → HUMAN READABLE CONDITION
# =========================================================

WMO_CONDITIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail"
}


def weather_condition(weather_code):
    return WMO_CONDITIONS.get(
        weather_code,
        "Unknown conditions"
    )


# =========================================================
# GET WEATHER FROM OPEN-METEO GFS
# =========================================================


def get_weather(
    latitude,
    longitude,
    timezone="auto",
    include_hourly=False
):

    cache_key = (
        round(latitude, 2),
        round(longitude, 2),
        bool(include_hourly)
    )

    cached = _weather_cache.get(cache_key)

    if cached is not None:
        cached_at, cached_data = cached
        age = time.time() - cached_at

        if age < WEATHER_CACHE_TTL_SECONDS:
            print(
                f"Using cached GFS weather for {cache_key} "
                f"(age: {age:.0f}s)"
            )
            return cached_data

    # Prevent several simultaneous requests for the same location from
    # all reaching Open-Meteo at once (important on shared deployments).
    with _cache_lock:
        lock = _weather_cache_locks.setdefault(cache_key, Lock())

    with lock:
        cached = _weather_cache.get(cache_key)
        if cached is not None:
            cached_at, cached_data = cached
            age = time.time() - cached_at
            if age < WEATHER_CACHE_TTL_SECONDS:
                return cached_data

        print(
            f"Fetching fresh weather from Open-Meteo GFS "
            f"for {cache_key}"
        )

        # Keep each request at <=10 weather variables. Open-Meteo's
        # free-tier request weighting increases when more than 10
        # variables are requested in one call.
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "forecast_days": 7,
            "timezone": timezone,
            "daily": (
                "temperature_2m_max,"
                "temperature_2m_min,"
                "precipitation_probability_max,"
                "weather_code"
            )
        }

        if include_hourly:
            params["hourly"] = (
                "temperature_2m,"
                "apparent_temperature,"
                "precipitation_probability,"
                "precipitation,"
                "wind_speed_10m,"
                "weather_code"
            )
        else:
            params["current"] = (
                "temperature_2m,"
                "relative_humidity_2m,"
                "apparent_temperature,"
                "wind_speed_10m,"
                "weather_code"
            )

        try:
            response = requests.get(
                OPEN_METEO_GFS_URL,
                params=params,
                timeout=15
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
                # If we have an older cache, serve it instead of making
                # the user wait or repeatedly retrying a rate-limited API.
                stale = _weather_cache.get(cache_key)
                if stale is not None:
                    print(
                        f"Open-Meteo rate limited; serving cached GFS "
                        f"weather for {cache_key}."
                    )
                    return stale[1]

                raise Exception(
                    "Open-Meteo is temporarily rate limiting requests. "
                    "Please wait about a minute and try again."
                )

            raise Exception(
                f"Open-Meteo request failed (HTTP {status_code})."
            )

        _weather_cache[cache_key] = (time.time(), data)

        print(
            f"GFS weather cached for {cache_key} for "
            f"{WEATHER_CACHE_TTL_SECONDS // 60} minutes."
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
        "auto",
        include_hourly=(time_of_day != "all_day")
    )

    daily = weather_data.get("daily", {})
    daily_dates = daily.get("time", [])

    if not daily_dates:
        return {
            "success": False,
            "error": "No daily forecast data was returned."
        }

    if date == "today":
        target_date = daily_dates[0]
    elif date == "tomorrow":
        if len(daily_dates) < 2:
            return {
                "success": False,
                "error": "Tomorrow's weather is unavailable."
            }
        target_date = daily_dates[1]
    else:
        target_date = date

    if target_date not in daily_dates:
        return {
            "success": False,
            "error": (
                f"Weather data is not available for {date}."
            )
        }

    day_index = daily_dates.index(target_date)

    daily_result = {
        "date": target_date,
        "temperature_max": daily["temperature_2m_max"][day_index],
        "temperature_min": daily["temperature_2m_min"][day_index],
        "rain_probability": daily["precipitation_probability_max"][day_index],
        "weather_code": daily["weather_code"][day_index],
        "condition": weather_condition(daily["weather_code"][day_index])
    }

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
                    "Invalid time_of_day. Use morning, afternoon, "
                    "evening, night, or all_day."
                )
            }

        start_hour, end_hour = time_ranges[time_of_day]
        hourly = weather_data.get("hourly", {})

        for i, time_string in enumerate(hourly.get("time", [])):
            if not time_string.startswith(target_date):
                continue

            try:
                hour = datetime.fromisoformat(time_string).hour
            except ValueError:
                continue

            if start_hour <= hour < end_hour:
                code = hourly["weather_code"][i]
                hourly_result.append({
                    "time": time_string,
                    "temperature": hourly["temperature_2m"][i],
                    "feels_like": hourly["apparent_temperature"][i],
                    "humidity": hourly["relative_humidity_2m"][i],
                    "rain_probability": hourly["precipitation_probability"][i],
                    "precipitation": hourly["precipitation"][i],
                    "wind_speed": hourly["wind_speed_10m"][i],
                    "weather_code": code,
                    "condition": weather_condition(code)
                })

    current = weather_data.get("current", {})
    current_code = current.get("weather_code")

    current_result = {
        "temperature": current.get("temperature_2m"),
        "feels_like": current.get("apparent_temperature"),
        "humidity": current.get("relative_humidity_2m"),
        "wind_speed": current.get("wind_speed_10m"),
        "precipitation": current.get("precipitation"),
        "weather_code": current_code,
        "condition": weather_condition(current_code)
    }

    return {
        "success": True,
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "timezone": weather_data.get("timezone", "auto")
        },
        "date": target_date,
        "time_of_day": time_of_day,
        "current": current_result,
        "daily": daily_result,
        "hourly": hourly_result
    }


# =========================================================
# WEATHER FROM CITY
# =========================================================

def get_weather_for_city(
    city,
    date="today",
    time_of_day="all_day"
):

    try:
        location = get_coordinates(city)
    except Exception as error:
        return {
            "success": False,
            "error": f"Could not find location: {error}"
        }

    if location is None:
        return {
            "success": False,
            "error": f"Could not find location: {city}"
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

            location
            == "CURRENT_USER_LOCATION"

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

    "You are WeatherGPT, a friendly and natural conversational "
    "weather assistant. "

    "Your job is to answer weather questions using the weather "
    "tool and then explain the results naturally, like a helpful "
    "friend, not like a weather report or API response. "

    "Always use the weather tool for live weather questions. "
    "Never invent weather information. "

    "IMPORTANT RESPONSE STYLE: "

    "Do not simply list weather values one after another. "

    "Do not use repetitive templates such as "
    "'Currently in your location...', "
    "'The humidity is...', "
    "'The wind is...', "
    "or 'Based on today's forecast...' unless they genuinely "
    "fit the conversation. "

    "Instead, combine the weather information into a natural "
    "sentence and focus on what the user actually wants to know. "

    "For example, if the user asks "
    "'What's the weather here right now?', "
    "give a short natural response such as: "
    "'It's pretty warm and cloudy right now, around 33°C, "
    "and it feels closer to 36°C. There's no rain at the moment.' "

    "If the user asks "
    "'Should I carry an umbrella?', "
    "don't just repeat the rain probability. "
    "Give a practical recommendation based on the forecast. "

    "For example: "
    "'I'd take a small umbrella with you. There's a decent "
    "chance of rain later today, so it's better to have one.' "

    "If the weather is clearly good, say so naturally. "
    "For example: "
    "'Looks like a good evening to head outside. It'll be "
    "fairly comfortable with no significant rain expected.' "

    "If the weather is bad, explain it naturally and mention "
    "the important reason. "

    "Keep normal answers to around 1-4 sentences. "

    "Only provide detailed information when the user asks for "
    "a detailed forecast, 7-day forecast, hourly forecast, "
    "or similar. "

    "Use °C for temperature and km/h for wind speed. "

    "Don't mention APIs, tools, function calls, coordinates, "
    "JSON, or technical implementation details. "

    "Remember the user's previously mentioned location within "
    "the conversation. "

    "If the user asks a follow-up such as "
    "'what about tomorrow?', use the same location. "

    "If the user does not mention a city and browser GPS is "
    "available, use exactly CURRENT_USER_LOCATION. "

    "Do not repeatedly ask the user for their location. "

    "If the user explicitly mentions another city, use that city. "

    "You can use casual phrases such as "
    "'Looks like...', "
    "'I'd say...', "
    "'You should be fine...', "
    "'I'd probably take an umbrella...', "
    "when appropriate. "

    "Be helpful, concise, natural, and conversational."
)

# =========================================================
# GROQ RATE LIMIT HELPERS
# =========================================================

MAX_RETRIES = 3

DEFAULT_BACKOFF_SECONDS = 3


def _is_rate_limit_error(error):

    message = str(error)

    return (

        "429" in message

        or "rate_limit"
        in message.lower()

        or "rate limit"
        in message.lower()

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

        return (
            float(match.group(1))
            + 1
        )


    return DEFAULT_BACKOFF_SECONDS


def create_completion_with_retry(
    **kwargs
):

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


            if not _is_rate_limit_error(
                error
            ):

                raise


            if attempt == MAX_RETRIES:

                break


            delay = _extract_retry_delay(
                error
            )


            print(

                f"Groq rate limited "
                f"(attempt {attempt}/"
                f"{MAX_RETRIES}). "
                f"Retrying in "
                f"{delay:.1f}s..."

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

        response = (
            create_completion_with_retry(

                model=MODEL_NAME,

                messages=messages,

                tools=[
                    WEATHER_TOOL_SCHEMA
                ]

            )
        )


        message = (
            response
            .choices[0]
            .message
        )


        messages.append(
            message
        )


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
        # EXECUTE TOOL CALLS
        # -------------------------------------------------

        for tool_call in tool_calls:

            try:

                args = json.loads(

                    tool_call
                    .function
                    .arguments

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

                    "WeatherGPT tool "
                    "call FAILED:",

                    tool_error

                )


                traceback.print_exc()


                result = {

                    "success":
                        False,

                    "error":
                        str(tool_error)

                }


            messages.append({

                "role":
                    "tool",

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

    final_response = (
        create_completion_with_retry(

            model=MODEL_NAME,

            messages=messages,

            tools=[
                WEATHER_TOOL_SCHEMA
            ],

            tool_choice="none"

        )
    )


    final_message = (
        final_response
        .choices[0]
        .message
    )


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
            "WeatherGPT API is running",

        "weather_provider":
            "Open-Meteo GFS",

        "ai_provider":
            "Groq"

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

    longitude: float = None,

    weather_context: str = None

):

    # -----------------------------------------------------
    # Create location-aware tool
    # -----------------------------------------------------

    weather_tool = create_weather_tool(

        latitude,

        longitude

    )


    # -----------------------------------------------------
    # Check location
    # -----------------------------------------------------

    old_location = (
        session_locations.get(
            session_id
        )
    )


    new_location = (

        latitude,

        longitude

    )


    # -----------------------------------------------------
    # Create / reset session
    # -----------------------------------------------------

    if (

        session_id not in chat_sessions

        or old_location
        != new_location

    ):

        chat_sessions[
            session_id
        ] = [

            {

                "role":
                    "system",

                "content":
                    SYSTEM_PROMPT

            }

        ]


        session_locations[
            session_id
        ] = new_location


    messages = chat_sessions[
        session_id
    ]


    # -----------------------------------------------------
    # Location context
    # -----------------------------------------------------

    if weather_context:

        final_message = (

            "The browser has already fetched live weather data "
            "directly from Open-Meteo GFS. The supplied context may "
            "represent the user's current GPS location OR an explicitly "
            "requested city. Use the supplied weather context for the "
            "location named in the context. Do NOT call the weather tool "
            "when the supplied context matches the user's requested "
            "location. Never invent weather values that are not present "
            "in the supplied context.\n\n"
            f"Weather context:\n{weather_context}\n\n"
            f"User's message: {message}"

        )

    elif (

        latitude is not None

        and longitude is not None

    ):

        final_message = (

            "The user's browser has provided their current location. "
            "If the user does not explicitly mention another city, use "
            "CURRENT_USER_LOCATION. "
            f"Current latitude: {latitude}. "
            f"Current longitude: {longitude}. "
            f"User's message: {message}"

        )

    else:

        final_message = message


    messages.append({

        "role":
            "user",

        "content":
            final_message

    })


    # -----------------------------------------------------
    # Run Groq
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


        if _is_rate_limit_error(
            error
        ):

            reply_text = (

                "WeatherGPT is getting "
                "a lot of requests right now. "
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