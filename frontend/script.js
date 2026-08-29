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

        if (userLatitude === null || userLongitude === null) {
            return null;
        }

        return fetchOpenMeteoForCoordinates(
            userLatitude,
            userLongitude,
            "Current location",
            force,
            WEATHER_CACHE_KEY
        );
    }


    async function fetchOpenMeteoForCoordinates(
        latitude,
        longitude,
        locationName,
        force = false,
        cacheKey = null
    ) {

        if (!force && cacheKey) {
            try {
                const raw = localStorage.getItem(cacheKey);
                if (raw) {
                    const cached = JSON.parse(raw);
                    if (
                        Date.now() - cached.timestamp < WEATHER_CACHE_TTL &&
                        cached.latitude !== null &&
                        cached.longitude !== null
                    ) {
                        return cached.context;
                    }
                }
            } catch (error) {
                console.warn("Weather cache read failed:", error);
            }
        }

        const params = new URLSearchParams({
            latitude,
            longitude,
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
                location: locationName,
                fetched_at: new Date().toISOString(),
                timezone: data.timezone,
                latitude,
                longitude,
                current: data.current,
                daily: data.daily
            };

            const contextString = JSON.stringify(context);

            if (cacheKey) {
                localStorage.setItem(
                    cacheKey,
                    JSON.stringify({
                        timestamp: Date.now(),
                        latitude,
                        longitude,
                        context: contextString
                    })
                );
            }

            return contextString;

        } catch (error) {
            console.error(`Open-Meteo GFS error for ${locationName}:`, error);
            return null;
        }
    }


    function extractRequestedCity(text) {

        const patterns = [
            /\b(?:in|for|at|near)\s+([A-Za-z][A-Za-z .'-]{1,60}?)(?=\s+(?:right now|now|today|tomorrow|tonight|this morning|this afternoon|this evening|weather|forecast)\b|[?.!,]|$)/i,
            /^\s*([A-Za-z][A-Za-z .'-]{1,60}?)\s+(?:weather|forecast)\b/i
        ];

        for (const pattern of patterns) {
            const match = text.match(pattern);
            if (match && match[1]) {
                const city = match[1]
                    .replace(/\s+/g, " ")
                    .trim()
                    .replace(/[?.!,]+$/, "");

                const blocked = new Set([
                    "the weather",
                    "weather",
                    "here",
                    "there",
                    "my location",
                    "current location",
                    "what is the",
                    "what's the"
                ]);

                if (city && !blocked.has(city.toLowerCase())) {
                    return city;
                }
            }
        }

        return null;
    }


    async function fetchOpenMeteoForCity(city) {

        const cacheKey = `weathergpt_city_gfs_${city.toLowerCase()}`;

        try {
            const raw = localStorage.getItem(cacheKey);
            if (raw) {
                const cached = JSON.parse(raw);
                if (Date.now() - cached.timestamp < WEATHER_CACHE_TTL) {
                    return cached.context;
                }
            }
        } catch (error) {
            console.warn("City weather cache read failed:", error);
        }

        const geoParams = new URLSearchParams({
            name: city,
            count: "1",
            language: "en",
            format: "json"
        });

        const geoResponse = await fetch(
            `https://geocoding-api.open-meteo.com/v1/search?${geoParams.toString()}`,
            {
                headers: { "Accept": "application/json" },
                cache: "no-store"
            }
        );

        if (!geoResponse.ok) {
            throw new Error(`Open-Meteo geocoding returned ${geoResponse.status}`);
        }

        const geoData = await geoResponse.json();
        const place = geoData.results && geoData.results[0];

        if (!place) {
            throw new Error(`City not found: ${city}`);
        }

        const displayName = [
            place.name,
            place.admin1,
            place.country
        ].filter(Boolean).join(", ");

        return fetchOpenMeteoForCoordinates(
            place.latitude,
            place.longitude,
            displayName,
            false,
            cacheKey
        );
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

            // If the user names a city, resolve that city and fetch
            // its GFS data directly from the browser. This avoids
            // Render's shared outbound IP being rate-limited.
            const requestedCity = extractRequestedCity(text);

            let weatherContext = null;

            if (requestedCity) {
                try {
                    weatherContext = await fetchOpenMeteoForCity(requestedCity);
                } catch (error) {
                    console.error("City Open-Meteo lookup failed:", error);
                }
            }

            // If no explicit city was requested, use the user's
            // current GPS location.
            if (!weatherContext) {
                weatherContext = await fetchOpenMeteoGFSContext();
            }

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