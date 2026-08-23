from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from datetime import datetime
import os
from dotenv import load_dotenv
from google import genai


# =========================================================
# GEMINI SETUP
# =========================================================

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(
    api_key=GEMINI_API_KEY
)

# Conversation memory
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

        "location": {

            "latitude":
                latitude,

            "longitude":
                longitude
        },

        "date":
            target_date,

        "time_of_day":
            time_of_day,

        "current":
            weather_data["current"],

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
                f"I couldn't find the location '{city}'."
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
# CREATE LOCATION-AWARE GEMINI TOOL
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

        """
        Get real weather information.

        If location is CURRENT_USER_LOCATION,
        use the user's exact browser coordinates.

        Otherwise use the city name.
        """

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
    # CREATE NEW GEMINI SESSION
    # =====================================================
    #
    # We recreate the session if the browser location
    # changes. This prevents an old location from being
    # stuck inside the previous tool.
    #

    if (
        session_id not in chat_sessions
        or old_location != new_location
    ):

        chat_sessions[session_id] = \
            client.chats.create(

                model=
                    "gemini-3.1-flash-lite",

                config={

                    "tools": [
                        weather_tool
                    ],

                    "system_instruction": (

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
                }
            )


        # Save location associated with session
        session_locations[session_id] = \
            new_location


    # =====================================================
    # GET CHAT SESSION
    # =====================================================

    chat_session = \
        chat_sessions[session_id]


    # =====================================================
    # GIVE GEMINI LOCATION INFORMATION
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


    # =====================================================
    # SEND TO GEMINI
    # =====================================================

    try:

        response = chat_session.send_message(
            final_message
        )


        # =================================================
        # RETURN RESPONSE
        # =================================================

        return {

            "response":
                response.text,

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


        return {

            "response": (
                "I couldn't retrieve the "
                "weather right now. "
                "Please try again."
            ),

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