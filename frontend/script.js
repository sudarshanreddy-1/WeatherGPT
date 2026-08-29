(function () {

    // ==========================================
    // BACKEND
    // ==========================================

    const API_BASE_URL = 'https://weathergpt-backend.onrender.com';

    const OPEN_METEO_GFS_URL = 'https://api.open-meteo.com/v1/gfs';
    const WEATHER_CACHE_KEY = 'weathergpt_openmeteo_gfs_cache_v2';
    const WEATHER_CACHE_TTL = 15 * 60 * 1000;
    let weatherContextCache = null;


    // ==========================================
    // DOM ELEMENTS
    // ==========================================

    const chatInner =
        document.getElementById("chatInner");

    const chatScroll =
        document.getElementById("chatScroll");

    const emptyState =
        document.getElementById("emptyState");

    const input =
        document.getElementById("chatInput");

    const sendBtn =
        document.getElementById("sendBtn");

    const locationStatus =
        document.getElementById("locationStatus");


    // ==========================================
    // USER LOCATION
    // ==========================================

    let userLatitude = null;
    let userLongitude = null;


    // ==========================================
    // DETECT USER LOCATION
    // ==========================================

    function detectLocation() {

        if (!navigator.geolocation) {

            updateLocationStatus(
                "📍 Location is not supported"
            );

            return;
        }


        updateLocationStatus(
            "📍 Requesting your location..."
        );


        navigator.geolocation.getCurrentPosition(

            function (position) {

                userLatitude =
                    position.coords.latitude;

                userLongitude =
                    position.coords.longitude;


                console.log(
                    "Latitude:",
                    userLatitude
                );

                console.log(
                    "Longitude:",
                    userLongitude
                );


                updateLocationStatus(
                    "📍 Location detected"
                );

            },


            function (error) {

                console.error(
                    "Location error:",
                    error
                );


                updateLocationStatus(
                    "📍 Location permission denied"
                );

            },


            {
                enableHighAccuracy: true,

                timeout: 10000,

                maximumAge: 300000
            }

        );

    }


    // ==========================================
    // LOCATION STATUS
    // ==========================================

    function updateLocationStatus(text) {

        if (locationStatus) {

            locationStatus.textContent =
                text;

        }

    }


    // ==========================================
    // SCROLL
    // ==========================================

    function scrollBottom() {

        requestAnimationFrame(function () {

            chatScroll.scrollTop =
                chatScroll.scrollHeight;

        });

    }


    // ==========================================
    // USER MESSAGE
    // ==========================================

    function addUserMessage(text) {

        if (emptyState) {

            emptyState.remove();

        }


        const el =
            document.createElement("div");


        el.className =
            "msg user";


        el.innerHTML =
            `<div class="bubble"></div>`;


        el
            .querySelector(".bubble")
            .textContent = text;


        chatInner.appendChild(el);


        scrollBottom();

    }


    // ==========================================
    // BOT AVATAR
    // ==========================================

    function botAvatarSVG() {

        return `
            <svg
                viewBox="0 0 24 24"
                fill="none"
            >

                <circle
                    cx="12"
                    cy="12"
                    r="5"
                    fill="var(--ink)"
                />

            </svg>
        `;

    }


    // ==========================================
    // TYPING
    // ==========================================

    function addTyping() {

        const el =
            document.createElement("div");


        el.className =
            "msg assistant";


        el.id =
            "typingMsg";


        el.innerHTML = `

            <div class="avatar">

                ${botAvatarSVG()}

            </div>


            <div class="bubble">

                <span class="typing">

                    <span></span>
                    <span></span>
                    <span></span>

                </span>

            </div>

        `;


        chatInner.appendChild(el);


        scrollBottom();

    }


    // ==========================================
    // REMOVE TYPING
    // ==========================================

    function removeTyping() {

        const typing =
            document.getElementById(
                "typingMsg"
            );


        if (typing) {

            typing.remove();

        }

    }


    // ==========================================
    // ASSISTANT MESSAGE
    // ==========================================

    function addAssistantMessage(text) {

        removeTyping();


        const el =
            document.createElement("div");


        el.className =
            "msg assistant";


        el.innerHTML = `

            <div class="avatar">

                ${botAvatarSVG()}

            </div>


            <div>

                <div class="bubble"></div>

            </div>

        `;


        el
            .querySelector(".bubble")
            .textContent = text;


        chatInner.appendChild(el);


        scrollBottom();

    }


    // ==========================================
    // OPEN-METEO GFS WEATHER CONTEXT
    // ==========================================

    function getCachedWeatherContext() {

        try {
            const raw = localStorage.getItem(WEATHER_CACHE_KEY);
            if (!raw) return null;

            const cached = JSON.parse(raw);

            if (
                Date.now() - cached.timestamp < WEATHER_CACHE_TTL &&
                cached.latitude !== null &&
                cached.longitude !== null
            ) {
                return cached.context;
            }
        } catch (error) {
            console.warn("Weather cache read failed:", error);
        }

        return null;
    }


    async function fetchOpenMeteoGFSContext(force = false) {

        if (
            userLatitude === null ||
            userLongitude === null
        ) {
            return null;
        }

        if (!force) {
            const cached = getCachedWeatherContext();
            if (cached) {
                weatherContextCache = cached;
                return cached;
            }

            if (weatherContextCache) {
                return weatherContextCache;
            }
        }

        // 5 current + 4 daily variables = 9 variables.
        // Keeping this request below 10 variables avoids the
        // extra weighted API-call cost on Open-Meteo's free tier.
        const params = new URLSearchParams({
            latitude: userLatitude,
            longitude: userLongitude,
            timezone: "auto",
            forecast_days: "7",
            current: "temperature_2m,relative_humidity_2m,apparent_temperature,wind_speed_10m,precipitation,weather_code",
            daily: "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code"
        });

        try {
            const response = await fetch(
                `${OPEN_METEO_GFS_URL}?${params.toString()}`,
                {
                    method: "GET",
                    headers: { "Accept": "application/json" },
                    cache: "no-store"
                }
            );

            if (!response.ok) {
                throw new Error(`Open-Meteo returned ${response.status}`);
            }

            const data = await response.json();

            const context = {
                source: "Open-Meteo NOAA GFS",
                fetched_at: new Date().toISOString(),
                timezone: data.timezone,
                latitude: userLatitude,
                longitude: userLongitude,
                current: data.current,
                daily: data.daily
            };

            weatherContextCache = JSON.stringify(context);

            localStorage.setItem(
                WEATHER_CACHE_KEY,
                JSON.stringify({
                    timestamp: Date.now(),
                    latitude: userLatitude,
                    longitude: userLongitude,
                    context: weatherContextCache
                })
            );

            return weatherContextCache;

        } catch (error) {
            console.error("Open-Meteo GFS error:", error);
            return null;
        }
    }


    // ==========================================
    // SEND MESSAGE
    // ==========================================

    async function handleSend(rawText) {

        const text = (

            rawText !== undefined

                ? rawText

                : input.value

        ).trim();


        if (!text) {

            return;

        }


        addUserMessage(text);


        input.value = "";


        sendBtn.disabled = true;


        addTyping();


        try {

            // ==================================
            // BUILD REQUEST
            // ==================================

            const params =
                new URLSearchParams();


            params.append(
                "message",
                text
            );


            // Send user's location
            if (
                userLatitude !== null &&
                userLongitude !== null
            ) {

                params.append(
                    "latitude",
                    userLatitude
                );


                params.append(
                    "longitude",
                    userLongitude
                );

            }


            console.log(
                "Sending weather request:",
                params.toString()
            );


            // ==================================
            // FETCH OPEN-METEO GFS IN BROWSER
            // ==================================

            // The browser calls Open-Meteo directly. This prevents
            // Render's shared outbound IP from being the source of
            // Open-Meteo rate-limit errors.
            const weatherContext =
                await fetchOpenMeteoGFSContext();

            if (weatherContext) {
                params.append(
                    "weather_context",
                    weatherContext
                );
            }


            // ==================================
            // CALL BACKEND
            // ==================================

            const response =
                await fetch(

                    `${API_BASE_URL}/chat?${params.toString()}`,

                    {
                        method: "POST",

                        headers: {
                            "Accept":
                                "application/json"
                        }
                    }

                );


            if (!response.ok) {

                throw new Error(
                    `Backend returned ${response.status}`
                );

            }


            const data =
                await response.json();


            if (!data.response) {

                throw new Error(
                    "No response received"
                );

            }


            addAssistantMessage(
                data.response
            );


        }

        catch (error) {

            console.error(
                "WeatherGPT error:",
                error
            );


            removeTyping();


            addAssistantMessage(
                "I couldn't connect to the WeatherGPT backend. Make sure FastAPI is running on port 8000."
            );

        }


        finally {

            sendBtn.disabled = false;

            input.focus();

        }

    }


    // ==========================================
    // SEND BUTTON
    // ==========================================

    sendBtn.addEventListener(
        "click",
        function () {

            handleSend();

        }
    );


    // ==========================================
    // ENTER KEY
    // ==========================================

    input.addEventListener(
        "keydown",
        function (event) {

            if (
                event.key === "Enter"
            ) {

                handleSend();

            }

        }
    );


    // ==========================================
    // EXAMPLE QUESTIONS
    // ==========================================

    document
        .querySelectorAll(
            ".prompt-chip, .mini-chip"
        )
        .forEach(function (button) {

            button.addEventListener(
                "click",
                function () {

                    handleSend(
                        button.getAttribute(
                            "data-prompt"
                        )
                    );

                }
            );

        });


    // ==========================================
    // START LOCATION DETECTION
    // ==========================================

    detectLocation();


})();