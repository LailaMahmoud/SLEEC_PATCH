(function () {
    function toArray(value) {
        return Array.prototype.slice.call(value || []);
    }

    function init(config) {
        const root = config.root || document;
        const steps = toArray(root.querySelectorAll(".wizard-step"));
        const total = config.total || steps.length;
        const labels = config.labels || [];
        const stepper = root.querySelector("[data-wizard-stepper]");
        const backButton = root.querySelector("[data-wizard-back]");
        const nextButton = root.querySelector("[data-wizard-next]");
        const restartButton = root.querySelector("[data-wizard-restart]");
        const counter = root.querySelector("[data-wizard-counter]");
        let currentStep = config.initialStep || 1;

        function canAdvance(step) {
            return !config.canAdvance || config.canAdvance(step);
        }

        function renderStepper() {
            if (!stepper) return;

            let html = "";
            for (let i = 1; i <= total; i += 1) {
                const label = labels[i - 1] || `Step ${i}`;
                const state = i === currentStep ? "is-active" : i < currentStep ? "is-complete" : "";
                html += `
                    <button type="button"
                            class="wizard-dot ${state}"
                            data-step-target="${i}"
                            aria-current="${i === currentStep ? "step" : "false"}">
                        <span>${i}</span>
                        <small>${label}</small>
                    </button>
                `;
            }

            stepper.innerHTML = html;
            toArray(stepper.querySelectorAll("[data-step-target]")).forEach((button) => {
                button.addEventListener("click", () => {
                    const target = Number(button.getAttribute("data-step-target"));
                    if (target <= currentStep || (target === currentStep + 1 && canAdvance(currentStep))) {
                        goToStep(target);
                    }
                });
            });
        }

        function updateControls() {
            if (backButton) backButton.disabled = currentStep <= 1;
            if (nextButton) {
                nextButton.disabled = currentStep >= total || !canAdvance(currentStep);
                nextButton.textContent = currentStep >= total ? "Finish" : "Continue";
            }
            if (counter) {
                const label = labels[currentStep - 1] || `Step ${currentStep}`;
                counter.textContent = counter.dataset.counterMode === "label"
                    ? label
                    : `Step ${currentStep} of ${total}`;
            }
        }

        function goToStep(step) {
            currentStep = Math.min(total, Math.max(1, Number(step) || 1));

            steps.forEach((item) => {
                const isActive = Number(item.getAttribute("data-step")) === currentStep;
                item.classList.toggle("is-active", isActive);
                item.setAttribute("aria-hidden", isActive ? "false" : "true");
            });

            renderStepper();
            updateControls();

            if (config.onStepChange) config.onStepChange(currentStep);

            const activeStep = steps.find((item) => (
                Number(item.getAttribute("data-step")) === currentStep
            ));

            if (activeStep) {
                activeStep.scrollTop = 0;
            }
        }

        if (backButton) {
            backButton.addEventListener("click", () => goToStep(currentStep - 1));
        }

        if (nextButton) {
            nextButton.addEventListener("click", () => {
                if (currentStep >= total) return;
                if (!canAdvance(currentStep)) return;
                goToStep(currentStep + 1);
            });
        }

        if (restartButton && config.onRestart) {
            restartButton.addEventListener("click", () => config.onRestart(api));
        }

        const api = {
            goToStep,
            refresh: updateControls,
            getCurrentStep: () => currentStep
        };

        goToStep(currentStep);
        return api;
    }

    window.SleecWizard = { init };
})();
