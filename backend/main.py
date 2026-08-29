from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import traceback

from config import WEATHER_API_KEY

from weather_service import (
    get_weather_for_city
)

from weather_tool import (
    create_weather_tool
)

from prompts import (
    SYSTEM_PROMPT
)

from groq_service import (
    run_chat_turn,
    _is_rate_limit_error
)


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