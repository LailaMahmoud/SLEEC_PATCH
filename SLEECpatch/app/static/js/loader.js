(function () {
    let activeRequests = 0;
    let loader;
    let loaderText;

    function ensureLoader() {
        if (loader) return loader;

        loader = document.getElementById("appLoader");

        if (!loader) {
            loader = document.createElement("div");
            loader.id = "appLoader";
            loader.className = "app-loader";
            loader.setAttribute("aria-hidden", "true");
            loader.innerHTML = `
                <div class="loader-card" role="status" aria-live="polite">
                    <div class="spinner" aria-hidden="true"></div>
                    <p class="loader-text">Working...</p>
                </div>
            `;
            document.body.appendChild(loader);
        }

        loaderText = loader.querySelector(".loader-text");
        return loader;
    }

    window.showLoader = function showLoader(text) {
        ensureLoader();
        activeRequests += 1;
        if (loaderText) loaderText.textContent = text || "Working...";
        loader.classList.add("is-active");
        loader.setAttribute("aria-hidden", "false");
    };

    window.hideLoader = function hideLoader() {
        ensureLoader();
        activeRequests = Math.max(0, activeRequests - 1);
        if (activeRequests > 0) return;
        loader.classList.remove("is-active");
        loader.setAttribute("aria-hidden", "true");
    };

    window.withLoader = async function withLoader(work, text) {
        window.showLoader(text);
        try {
            return await work();
        } finally {
            window.hideLoader();
        }
    };

    document.addEventListener("DOMContentLoaded", ensureLoader);
})();
