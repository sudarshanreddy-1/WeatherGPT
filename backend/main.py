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
    # Defend against trailing/leading whitespace or newlines
    # that sneak in from copy-pasting into env var UIs -
    # these break the Authorization header entirely.
    GROQ_API_KEY = GROQ_API_KEY.strip()

client = Groq(api_key=GROQ_API_KEY)

MODEL_NAME = "openai/gpt-oss-120b"

# Conversation memory: session_id -> list of chat messages
chat_sessions = {}

# Store which browser location belongs to each session
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
# CITY -> LATITUDE + LONGITUDE
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
# GET WEATHER FROM OPEN-METEO
# =========================================================

def get_weather(
    latitude,
    longitude,
    timezone="auto"
):

    url = "https://api.open-meteo.com/v1/forecast"

    params = {

        "latitude": latitude,

        "longitude": longitude,

        # Current weather
        "current": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "wind_speed_10m,"
            "precipitation,"
            "weather_code"
        ),

        # Hourly weather
        "hourly": (
            "temperature_2m,"
            "relative_humidity_2m,"
            "apparent_temperature,"
            "precipitation_probability,"
            "precipitation,"
            "weather_code,"
            "wind_speed_10m"
        ),

        # Daily weather
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

    response = requests.get(
        url,
        params=params,
        timeout=10
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# WEATHER FROM EXACT COORDINATES
# =========================================================

def get_weather_for_coordinates(
    latitude,
    longitude,
    date="today",
    time_of_day="all_day"
):

    # -----------------------------------------------------
    # Get weather
    # -----------------------------------------------------

    weather_data = get_weather(
        latitude,
        longitude,
        "auto"
    )


    # -----------------------------------------------------
    # Daily dates
    # -----------------------------------------------------

    daily_dates = weather_data["daily"]["time"]


    # -----------------------------------------------------
    # Determine requested date
    # -----------------------------------------------------

    if date == "today":

        target_date = daily_dates[0]

    elif date == "tomorrow":

        target_date = daily_dates[1]

    else:

        target_date = date


    # -----------------------------------------------------
    # Check date
    # -----------------------------------------------------

    if target_date not in daily_dates:

        return {
            "success": False,
            "error": (
                f"Weather data is not available "
                f"for {date}."
            )
        }


    # -----------------------------------------------------
    # Find day index
    # -----------------------------------------------------

    day_index = daily_dates.index(
        target_date
    )


    # -----------------------------------------------------
    # Daily weather
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


        # -------------------------------------------------
        # Validate time
        # -------------------------------------------------

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


        # -------------------------------------------------
        # Find matching hours
        # -------------------------------------------------

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
        "daily": daily_result,
        "hourly": hourly_result
    }


# =========================================================
# WEATHER FROM CITY NAME
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
            "error": f"Could not find location: {city}"
        }


    result = get_weather_for_coordinates(

        location["latitude"],

        location["longitude"],

        date,

        time_of_day
    )


    # Add city information
    result["location"] = location


    return result


# =========================================================
# WEATHER TOOL SCHEMA (OpenAI / Groq function-calling format)
# =========================================================

WEATHER_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get real, live weather information for a "
            "location. If the user did not mention a city "
            "and their browser location is available, pass "
            "location as exactly CURRENT_USER_LOCATION. "
            "Otherwise pass the city name."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": (
                        "City name, or exactly "
                        "CURRENT_USER_LOCATION if the user "
                        "did not name a city."
                    )
                },
                "date": {
                    "type": "string",
                    "description": (
                        "today, tomorrow, or an explicit "
                        "YYYY-MM-DD date."
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
                    ],
                    "description": "Part of day requested."
                }
            },
            "required": ["location", "date", "time_of_day"]
        }
    }
}


# =========================================================
# CREATE LOCATION-AWARE WEATHER TOOL FUNCTION
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

        # =================================================
        # USER'S CURRENT LOCATION
        # =================================================

        if (
            location == "CURRENT_USER_LOCATION"
            and user_latitude is not None
            and user_longitude is not None
        ):

            return get_weather_for_coordinates(

                user_latitude,

                user_longitude,

                date,

                time_of_day
            )


        # =================================================
        # EXPLICIT CITY
        # =================================================

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

    "You are WeatherGPT, "
    "a conversational AI "
    "weather assistant. "

    "Always use the weather "
    "tool for live weather "
    "questions. "

    "Never invent current "
    "or forecast weather. "

    "Remember the user's "
    "previously mentioned "
    "location within the "
    "conversation. "

    "If the user asks "
    "a follow-up such as "
    "'what about tomorrow?', "
    "use the same location "
    "from the previous question. "

    "If the user does not "
    "mention a city and the "
    "current browser location "
    "is available, call the "
    "weather tool using exactly "
    "CURRENT_USER_LOCATION. "

    "Do not ask the user "
    "to repeatedly provide "
    "their location. "

    "If the user explicitly "
    "mentions another city, "
    "use that city instead. "

    "For example, if the user "
    "asks 'Can I go play outside "
    "today evening?' without "
    "mentioning a city, use "
    "CURRENT_USER_LOCATION, "
    "today, evening. "

    "For general climate questions, "
    "answer using general knowledge. "

    "Keep answers natural, "
    "clear and concise."
)


# =========================================================
# RETRY HELPER FOR GROQ RATE LIMITS (429)
# =========================================================

MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 3


def _is_rate_limit_error(error) -> bool:

    message = str(error)

    return (
        "RESOURCE_EXHAUSTED" in message
        or "429" in message
        or "rate_limit" in message.lower()
    )


def _extract_retry_delay(error) -> float:

    message = str(error)

    match = re.search(
        r"retry(?:[-_ ]?after)?['\"]?\s*[:\s]\s*['\"]?(\d+(?:\.\d+)?)",
        message,
        re.IGNORECASE
    )

    if match:
        return float(match.group(1)) + 1  # small buffer

    return DEFAULT_BACKOFF_SECONDS


def create_completion_with_retry(**kwargs):

    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):

        try:

            return client.chat.completions.create(**kwargs)

        except Exception as error:

            last_error = error

            if not _is_rate_limit_error(error):
                raise

            if attempt == MAX_RETRIES:
                break

            delay = _extract_retry_delay(error)

            print(
                f"WeatherGPT rate limited "
                f"(attempt {attempt}/{MAX_RETRIES}). "
                f"Retrying in {delay:.1f}s..."
            )

            time.sleep(delay)

    raise last_error


# =========================================================
# MANUAL TOOL-CALLING CHAT LOOP
# =========================================================
#
# Groq (like OpenAI) requires us to manage the tool-calling
# loop ourselves: send messages -> check for tool_calls ->
# run the python function -> send the result back -> get
# the final natural-language answer. Each of those two API
# calls is retried independently.
#

def run_chat_turn(messages, weather_tool_fn):

    MAX_TOOL_ITERATIONS = 5

    for iteration in range(MAX_TOOL_ITERATIONS):

        # Always offer the tool. gpt-oss-120b will keep
        # attempting tool calls on follow-up turns even
        # after receiving a tool result, and Groq rejects
        # a tool call made when tools weren't offered on
        # that specific request - so every call in this
        # loop must include the schema.

        response = create_completion_with_retry(
            model=MODEL_NAME,
            messages=messages,
            tools=[WEATHER_TOOL_SCHEMA],
        )

        message = response.choices[0].message

        messages.append(message)


        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            # Model produced a final natural-language answer
            return message.content, messages


        # ---- Execute each requested tool call ----

        for tool_call in tool_calls:

            try:

                args = json.loads(
                    tool_call.function.arguments
                )

                print(
                    "WeatherGPT calling tool with args:",
                    args
                )

                result = weather_tool_fn(
                    location=args.get("location", "CURRENT_USER_LOCATION"),
                    date=args.get("date", "today"),
                    time_of_day=args.get("time_of_day", "all_day"),
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
                    "error": str(tool_error)
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "name": tool_call.function.name,
                "content": json.dumps(result)
            })

        # Loop back around so the model can either use the
        # tool result to answer, or (rarely) call the tool
        # again with different arguments.


    # Safety net: hit the iteration cap without a plain
    # text answer. Ask one last time with the tool
    # disabled so the model is forced to summarize
    # whatever tool results it already has.

    final_response = create_completion_with_retry(
        model=MODEL_NAME,
        messages=messages,
        tools=[WEATHER_TOOL_SCHEMA],
        tool_choice="none",
    )

    final_message = final_response.choices[0].message

    messages.append(final_message)

    return final_message.content, messages


# =========================================================
# HOME ENDPOINT
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

    # =====================================================
    # CREATE LOCATION-AWARE WEATHER TOOL
    # =====================================================

    weather_tool = create_weather_tool(

        latitude,

        longitude
    )


    # =====================================================
    # CHECK WHETHER LOCATION CHANGED
    # =====================================================

    old_location = session_locations.get(
        session_id
    )

    new_location = (
        latitude,
        longitude
    )


    # =====================================================
    # CREATE / RESET SESSION MESSAGE HISTORY
    # =====================================================
    #
    # We reset history if the browser location changes.
    # This prevents an old location from being stuck in
    # the conversation context.
    #

    if (
        session_id not in chat_sessions
        or old_location != new_location
    ):

        chat_sessions[session_id] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]

        # Save location associated with session
        session_locations[session_id] = \
            new_location


    messages = chat_sessions[session_id]


    # =====================================================
    # GIVE MODEL LOCATION INFORMATION
    # =====================================================

    if (
        latitude is not None
        and longitude is not None
    ):

        final_message = (

            "The user's browser has provided "
            "their current location. "

            "If the weather question does not "
            "explicitly mention another city, "
            "use CURRENT_USER_LOCATION with "
            "the weather tool. "

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


    # =====================================================
    # SEND TO GROQ
    # =====================================================

    try:

        answer_text, messages = run_chat_turn(
            messages,
            weather_tool
        )

        chat_sessions[session_id] = messages


        # =================================================
        # RETURN RESPONSE
        # =================================================

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

        # Print the full traceback AND the underlying
        # cause chain (e.g. the real httpx/socket error
        # hiding behind a generic "Connection error.")
        # so it shows up in Render's logs.
        traceback.print_exc()

        cause = error.__cause__

        depth = 0

        while cause is not None and depth < 5:

            print(
                f"  caused by ({type(cause).__name__}):",
                cause
            )

            cause = getattr(cause, "__cause__", None)

            depth += 1


        if _is_rate_limit_error(error):

            reply_text = (
                "WeatherGPT is getting a lot of "
                "requests right now and hit its "
                "rate limit. Please wait a few "
                "seconds and try again."
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