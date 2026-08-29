import requests
import time
from datetime import datetime

from config import WEATHER_API_KEY


# =========================================================
# WEATHER CACHE
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

        query = f"{latitude},{longitude}"

    elif city:

        query = city

    else:

        raise Exception(
            "No location was provided."
        )

    params = {
        "key": WEATHER_API_KEY,
        "q": query,
        "days": 7,
        "aqi": "no",
        "alerts": "yes"
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

    cache_key = (
        round(latitude, 2),
        round(longitude, 2)
    )

    cached = _weather_cache.get(
        cache_key
    )

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

        print(
            f"Weather cache expired for "
            f"{cache_key}"
        )

    print(
        f"Fetching fresh weather from WeatherAPI "
        f"for {cache_key}"
    )

    data = weatherapi_request(
        latitude=latitude,
        longitude=longitude
    )

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
        longitude
    )

    location_data = weather_data.get(
        "location",
        {}
    )

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

    condition_data = day_data.get(
        "condition",
        {}
    )

    astro_data = selected_day.get(
        "astro",
        {}
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

        hours = selected_day.get(
            "hour",
            []
        )

        for hour_data in hours:

            time_string = hour_data.get(
                "time"
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

    cache_key = (
        round(latitude, 2),
        round(longitude, 2)
    )

    _weather_cache[cache_key] = (
        time.time(),
        data
    )

    result = get_weather_for_coordinates(

        latitude,

        longitude,

        date,

        time_of_day
    )

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