/** @odoo-module **/

import { formView } from "@web/views/form/form_view";
import { registry } from "@web/core/registry";
import { useEffect, onPatched, onMounted } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class YavinDiscoverWizardController extends formView.Controller {
    setup() {
        super.setup();
        this.orm = useService("orm");

        // Update progress bar on mount and patch to ensure it matches state
        onMounted(() => {
            this.updateProgressBar();
            // Trigger discovery on initial mount if is_discovering is true
            // (useEffect only triggers on change, not initial value)
            if (this.model.root.data.is_discovering) {
                this.performDiscovery();
            }
        });
        onPatched(() => this.updateProgressBar());

        useEffect(
            (isDiscovering) => {
                if (isDiscovering) {
                    this.performDiscovery();
                } else {
                    this.updateProgressBar();
                }
            },
            () => [this.model.root.data.is_discovering]
        );
    }



    async performDiscovery() {
        if (this._isDiscoveryRunning) return;
        this._isDiscoveryRunning = true;

        // Indicate working state visually - use requestAnimationFrame to ensure DOM is ready
        requestAnimationFrame(() => this.updateProgressBar(true));

        // Give the browser a moment to render the animation before blocking
        await new Promise(resolve => setTimeout(resolve, 50));

        try {
            // Call the synchronous discovery action
            // This will block the UI for a few seconds (timeout)
            await this.orm.call(
                this.model.root.resModel,
                "action_start_discovery",
                [this.model.root.resId]
            );

            // Reload data to show results and updated status
            await this.model.root.load();
        } catch {
            // Try to reload to see if backend wrote error message
            try {
                await this.model.root.load();
            } catch {
                // If wizard is closed/gone, ignore
            }
        } finally {
            this._isDiscoveryRunning = false;
        }
    }

    updateProgressBar(indeterminate = false) {
        if (!this.model || !this.model.root) {
            return;
        }

        const progressBar = document.getElementById("yavin_discovery_progress_bar");
        const progressText = document.getElementById("yavin_discovery_progress_text");

        if (indeterminate) {
            // Show indeterminate/animated state during discovery
            if (progressBar) {
                progressBar.style.width = "100%";
                progressBar.classList.add("progress-bar-striped", "progress-bar-animated");
                progressBar.setAttribute("aria-valuenow", "");
            }
            if (progressText) {
                progressText.textContent = "...";
            }
        } else {
            // Show actual progress from backend
            const progress = this.model.root.data.discovery_progress || 0;
            if (progressBar) {
                progressBar.style.width = `${progress}%`;
                progressBar.setAttribute("aria-valuenow", Math.round(progress));
            }
            if (progressText) {
                progressText.textContent = `${Math.round(progress)}%`;
            }
        }
    }
}

export const YavinDiscoverWizardView = {
    ...formView,
    Controller: YavinDiscoverWizardController,
};

registry.category("views").add("yavin_discover_wizard", YavinDiscoverWizardView);
