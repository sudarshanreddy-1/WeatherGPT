from weather_service import (
    get_weather_for_coordinates,
    get_weather_for_city
)


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

        return get_weather_for_city(

            location,

            date,

            time_of_day
        )

    return get_weather_tool