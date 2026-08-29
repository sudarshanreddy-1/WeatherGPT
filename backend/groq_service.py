import json
import re
import time
import traceback

from groq import Groq

from config import (
    GROQ_API_KEY,
    MODEL_NAME
)

from weather_tool import (
    WEATHER_TOOL_SCHEMA
)


# =========================================================
# GROQ SETUP
# =========================================================

client = Groq(
    api_key=GROQ_API_KEY
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