(function () {

    // ==========================================
    // BACKEND
    // ==========================================

    const API_BASE_URL = 'https://weathergpt-backend.onrender.com';


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
                    fill="#0F1626"
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