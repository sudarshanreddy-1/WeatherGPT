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
# WEATHER CACHE
# =========================================================
#
# Each coordinate gets its own cache.
#
# Hyderabad -> cache A
# Mumbai    -> cache B
# Delhi     -> cache C
#
# Cache expires after 5 minutes.
# =========================================================

_weather_cache = {}

WEATHER_CACHE_TTL_SECONDS = 300


# =========================================================
# WEATHERAPI HELPER
# =========================================================

def weatherapi_request(
    latitude=None,
    longitude=None,
    city=None
):

    if not WEATHER_API_KEY:

        raise Exception(
            "WEATHER_API_KEY is not configured."
        )


    url = (
        "https://api.weatherapi.com/v1/"
        "forecast.json"
    )


    # -----------------------------------------------------
    # Location query
    # -----------------------------------------------------

    if (
        latitude is not None
        and longitude is not None
    ):

        query = (
            f"{latitude},{longitude}"
        )

    elif city:

        query = city

    else:

        raise Exception(
            "No location was provided."
        )


    params = {

        "key":
            WEATHER_API_KEY,

        "q":
            query,

        "days":
            7,

        "aqi":
            "no",

        "alerts":
            "yes"
    }


    response = requests.get(
        url,
        params=params,
        timeout=15
    )


    # -----------------------------------------------------
    # HTTP errors
    # -----------------------------------------------------

    if response.status_code == 400:

        try:

            error_data = response.json()

            error_message = (
                error_data
                .get("error", {})
                .get(
                    "message",
                    "Location not found."
                )
            )

        except Exception:

            error_message = (
                "Location not found."
            )


        raise Exception(
            f"WeatherAPI error: {error_message}"
        )


    if response.status_code == 401:

        raise Exception(
            "WeatherAPI authentication failed. "
            "Check WEATHER_API_KEY."
        )


    if response.status_code == 403:

        raise Exception(
            "WeatherAPI access is forbidden. "
            "Check your WeatherAPI plan."
        )


    if response.status_code == 429:

        raise Exception(
            "WeatherAPI rate limit reached. "
            "Please try again later."
        )


    response.raise_for_status()


    data = response.json()


    # -----------------------------------------------------
    # WeatherAPI JSON error
    # -----------------------------------------------------

    if "error" in data:

        error_message = (
            data["error"]
            .get(
                "message",
                "Unknown WeatherAPI error."
            )
        )

        raise Exception(
            f"WeatherAPI error: {error_message}"
        )


    return data


# =========================================================
# GET WEATHER
# =========================================================

def get_weather(
    latitude,
    longitude
):

    # -----------------------------------------------------
    # Cache key
    # -----------------------------------------------------

    cache_key = (
        round(latitude, 2),
        round(longitude, 2)
    )


    # -----------------------------------------------------
    # Check cache
    # -----------------------------------------------------

    cached = _weather_cache.get(
        cache_key
    )


    if cached is not None:

        cached_at, cached_data = cached

        age = (
            time.time() - cached_at
        )


        if age < WEATHER_CACHE_TTL_SECONDS:

            print(
                f"Using cached weather for "
                f"{cache_key} "
                f"(age: {age:.0f}s)"
            )

            return cached_data


        print(
            f"Weather cache expired for "
            f"{cache_key}"
        )


    # -----------------------------------------------------
    # Fetch fresh data
    # -----------------------------------------------------

    print(
        f"Fetching fresh weather from WeatherAPI "
        f"for {cache_key}"
    )


    data = weatherapi_request(
        latitude=latitude,
        longitude=longitude
    )


    # -----------------------------------------------------
    # Save cache
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

    # -----------------------------------------------------
    # Get weather
    # -----------------------------------------------------

    weather_data = get_weather(
        latitude,
        longitude
    )


    # -----------------------------------------------------
    # Location
    # -----------------------------------------------------

    location_data = weather_data.get(
        "location",
        {}
    )


    # -----------------------------------------------------
    # Forecast
    # -----------------------------------------------------

    forecast_data = weather_data.get(
        "forecast",
        {}
    )


    forecast_days = forecast_data.get(
        "forecastday",
        []
    )


    if not forecast_days:

        return {
            "success": False,
            "error": (
                "No forecast data was returned."
            )
        }


    # =====================================================
    # DETERMINE DATE
    # =====================================================

    if date == "today":

        target_date = forecast_days[0]["date"]


    elif date == "tomorrow":

        if len(forecast_days) < 2:

            return {
                "success": False,
                "error": (
                    "Tomorrow's weather "
                    "is unavailable."
                )
            }

        target_date = forecast_days[1]["date"]


    else:

        target_date = date


    # =====================================================
    # FIND REQUESTED DAY
    # =====================================================

    selected_day = None


    for day in forecast_days:

        if day["date"] == target_date:

            selected_day = day

            break


    if selected_day is None:

        return {

            "success": False,

            "error": (
                f"Weather data is not available "
                f"for {date}."
            )
        }


    # =====================================================
    # DAILY WEATHER
    # =====================================================

    day_data = selected_day.get(
        "day",
        {}
    )


    condition_data = (
        day_data.get(
            "condition",
            {}
        )
    )


    astro_data = (
        selected_day.get(
            "astro",
            {}
        )
    )


    daily_result = {

        "date":
            target_date,

        "temperature_max":
            day_data.get(
                "maxtemp_c"
            ),

        "temperature_min":
            day_data.get(
                "mintemp_c"
            ),

        "rain_probability":
            day_data.get(
                "daily_chance_of_rain"
            ),

        "weather_code":
            condition_data.get(
                "code"
            ),

        "condition":
            condition_data.get(
                "text"
            ),

        "sunrise":
            astro_data.get(
                "sunrise"
            ),

        "sunset":
            astro_data.get(
                "sunset"
            )
    }


    # =====================================================
    # HOURLY WEATHER
    # =====================================================

    hourly_result = []


    if time_of_day != "all_day":

        time_ranges = {

            "morning":
                (6, 12),

            "afternoon":
                (12, 17),

            "evening":
                (17, 21),

            "night":
                (21, 24)
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


        start_hour, end_hour = (
            time_ranges[time_of_day]
        )


        # -------------------------------------------------
        # Get hourly data
        # -------------------------------------------------

        hours = selected_day.get(
            "hour",
            []
        )


        for hour_data in hours:

            time_string = (
                hour_data.get(
                    "time"
                )
            )


            if not time_string:

                continue


            try:

                hour = datetime.strptime(
                    time_string,
                    "%Y-%m-%d %H:%M"
                ).hour

            except ValueError:

                continue


            if (
                start_hour
                <= hour
                < end_hour
            ):

                hourly_condition = (
                    hour_data.get(
                        "condition",
                        {}
                    )
                )


                hourly_result.append({

                    "time":
                        time_string,

                    "temperature":
                        hour_data.get(
                            "temp_c"
                        ),

                    "feels_like":
                        hour_data.get(
                            "feelslike_c"
                        ),

                    "humidity":
                        hour_data.get(
                            "humidity"
                        ),

                    "rain_probability":
                        hour_data.get(
                            "chance_of_rain"
                        ),

                    "precipitation":
                        hour_data.get(
                            "precip_mm"
                        ),

                    "wind_speed":
                        hour_data.get(
                            "wind_kph"
                        ),

                    "weather_code":
                        hourly_condition.get(
                            "code"
                        ),

                    "condition":
                        hourly_condition.get(
                            "text"
                        )
                })


    # =====================================================
    # CURRENT WEATHER
    # =====================================================

    current_data = weather_data.get(
        "current",
        {}
    )


    current_condition = (
        current_data.get(
            "condition",
            {}
        )
    )


    current_result = {

        "temperature":
            current_data.get(
                "temp_c"
            ),

        "feels_like":
            current_data.get(
                "feelslike_c"
            ),

        "humidity":
            current_data.get(
                "humidity"
            ),

        "wind_speed":
            current_data.get(
                "wind_kph"
            ),

        "precipitation":
            current_data.get(
                "precip_mm"
            ),

        "weather_code":
            current_condition.get(
                "code"
            ),

        "condition":
            current_condition.get(
                "text"
            )
    }


    # =====================================================
    # RETURN
    # =====================================================

    return {

        "success":
            True,

        "location": {

            "latitude":
                latitude,

            "longitude":
                longitude,

            "name":
                location_data.get(
                    "name"
                ),

            "country":
                location_data.get(
                    "country"
                ),

            "timezone":
                location_data.get(
                    "tz_id"
                )
        },

        "date":
            target_date,

        "time_of_day":
            time_of_day,

        "current":
            current_result,

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

    if not WEATHER_API_KEY:

        return {

            "success": False,

            "error":
                "WEATHER_API_KEY is not configured."
        }


    try:

        data = weatherapi_request(
            city=city
        )


    except Exception as error:

        return {

            "success": False,

            "error":
                str(error)
        }


    # -----------------------------------------------------
    # Get coordinates
    # -----------------------------------------------------

    location = data.get(
        "location",
        {}
    )


    latitude = location.get(
        "lat"
    )


    longitude = location.get(
        "lon"
    )


    if (
        latitude is None
        or longitude is None
    ):

        return {

            "success": False,

            "error":
                f"Could not find location: {city}"
        }


    # -----------------------------------------------------
    # Put already-fetched data into cache
    #
    # This prevents another WeatherAPI request.
    # -----------------------------------------------------

    cache_key = (

        round(latitude, 2),

        round(longitude, 2)
    )


    _weather_cache[cache_key] = (

        time.time(),

        data
    )


    # -----------------------------------------------------
    # Process weather
    # -----------------------------------------------------

    result = get_weather_for_coordinates(

        latitude,

        longitude,

        date,

        time_of_day
    )


    # -----------------------------------------------------
    # Add complete location information
    # -----------------------------------------------------

    result["location"] = {

        "latitude":
            latitude,

        "longitude":
            longitude,

        "name":
            location.get(
                "name"
            ),

        "country":
            location.get(
                "country"
            ),

        "timezone":
            location.get(
                "tz_id",
                "auto"
            )
    }


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

    "You are WeatherGPT, a friendly, natural, human-like weather assistant. "
    "Talk like a helpful friend who happens to know the weather, not like a weather API, report, dashboard, or technical assistant. "

    "Always use the weather tool for live weather questions. "
    "Never invent weather information. "

    "NATURAL CONVERSATION RULES: "

    "Answer in simple everyday language. "
    "Make your responses sound like something a real person would say in a normal conversation. "
    "Do not dump weather values one after another. "
    "Do not use labels such as 'Condition:', 'Temperature:', 'Humidity:', 'Wind:', 'Precipitation:', or similar report-style formatting. "
    "Do not use tables or report-style formatting for normal weather questions. "
    "Do not unnecessarily repeat the user's city or location in every response. "
    "Do not mention APIs, tools, function calls, JSON, coordinates, weather providers, or technical details. "

    "Keep normal answers short and natural, usually 1-3 sentences. "
    "Use contractions naturally, such as 'it's', 'you'll', 'I'd', 'won't', and 'there's'. "
    "Use casual phrases such as 'Looks like...', 'You should be good to go', "
    "'I'd probably...', 'You could...', and 'It's looking pretty nice outside' when appropriate. "

    "MOST IMPORTANT: Be useful and proactive. "
    "Don't just tell the user the weather. Help them decide what they can actually do because of the weather. "

    "When the weather is pleasant, suggest suitable outdoor activities naturally. "
    "You can suggest going for a walk, playing outside, going for a bike ride, jogging, "
    "meeting friends outdoors, having a picnic, going to a park, or simply spending some time outside. "
    "Only suggest activities that make sense for the actual weather. "

    "For example, if the weather is comfortable and there is little chance of rain, "
    "say something like: "
    "'Looks like a pretty nice day outside. You could go for a bike ride or play outside for a while.' "

    "If the weather is especially good in the evening, you can say: "
    "'The evening looks pretty comfortable. If you're free, it's a good time for a walk, bike ride, or hanging out with friends.' "

    "If it is hot, avoid recommending intense outdoor activities during the hottest part of the day. "
    "Instead suggest staying hydrated, going outside during cooler hours, "
    "taking a relaxed evening walk, or doing something indoors. "

    "If it is rainy, don't encourage outdoor activities. "
    "Give a practical alternative when useful. "
    "For example: "
    "'I'd skip the outdoor plans today. Rain looks likely, so it might be better to stay in or plan something indoors.' "

    "If there is strong wind, lightning, thunderstorms, extreme heat, or other dangerous weather, "
    "prioritize safety and clearly advise the user not to do unsuitable outdoor activities. "

    "WHEN THE USER ASKS ABOUT CURRENT WEATHER: "

    "If the user asks 'What's the weather here right now?', "
    "give a short natural description instead of listing every weather value. "

    "For example: "
    "'It's warm and cloudy right now, around 33°C, and it feels a little hotter. "
    "No rain at the moment, so you should be good to head outside.' "

    "Do not copy this example exactly every time. "
    "Generate a natural response based on the actual weather. "

    "WHEN THE USER ASKS ABOUT RAIN OR UMBRELLAS: "

    "Give a practical recommendation instead of simply repeating the rain percentage. "

    "For example: "
    "'You probably won't need an umbrella today. Rain doesn't look very likely, so you should be fine without one.' "

    "If rain is likely, say so clearly: "
    "'I'd take an umbrella with you. There's a decent chance of rain later, so it's better to have one.' "

    "WHEN THE USER ASKS WHAT THEY CAN DO: "

    "Use the actual weather conditions to suggest activities. "
    "For good weather, recommend outdoor activities. "
    "For bad weather, recommend indoor activities. "
    "For very hot weather, recommend activities during cooler parts of the day. "

    "For example: "
    "'It's looking pretty good outside today. A bike ride, a game with friends, or just a walk in the evening would be a nice fit.' "

    "WHEN THE USER ASKS ABOUT WIND: "

    "Don't simply state the wind speed. "
    "Explain what it means practically. "
    "For example, light wind can be described as comfortable, while strong wind may make cycling or outdoor activities unpleasant. "

    "WHEN THE USER ASKS ABOUT TOMORROW OR A FOLLOW-UP: "

    "Remember the location from earlier in the conversation. "
    "If the user says 'what about tomorrow?', 'what about evening?', or similar, "
    "understand that they are referring to the same location unless they mention another city. "

    "LOCATION RULES: "

    "If the user does not mention a city and browser GPS is available, use exactly CURRENT_USER_LOCATION. "
    "Do not repeatedly ask the user for their location. "
    "If the user explicitly mentions another city, use that city. "

    "DETAILED FORECASTS: "

    "Only provide detailed information when the user asks for a detailed forecast, "
    "7-day forecast, hourly forecast, or similar. "
    "Even detailed forecasts should be easy to read and conversational, not raw API data. "

    "Use °C for temperature and km/h for wind speed. "

    "Never invent weather information. "
    "Always base weather answers on the weather tool results. "

    "Do not over-explain. "
    "Answer what the user asked first, then add one useful weather-based suggestion when it genuinely helps. "

    "Be friendly, casual, concise, practical, and natural."
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
            "WeatherAPI",

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

    longitude: float = None

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
