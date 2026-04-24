/** @odoo-module **/

import "@pos_yavin/wizard/discover_wizard";
import { YavinDiscoverWizardController } from "@pos_yavin/wizard/discover_wizard";
import { getFixture, patchWithCleanup } from "@web/../tests/helpers/utils";

QUnit.module("pos_yavin discover wizard", (hooks) => {
    hooks.beforeEach(function () {
        this.target = getFixture();
        this.target.innerHTML = `
            <div id="yavin_discovery_progress_bar" class="progress-bar"></div>
            <span id="yavin_discovery_progress_text"></span>
        `;
    });

    QUnit.test("updateProgressBar shows indeterminate state", function (assert) {
        const controller = {
            model: { root: { data: { discovery_progress: 0 } } },
        };

        YavinDiscoverWizardController.prototype.updateProgressBar.call(controller, true);

        const bar = this.target.querySelector("#yavin_discovery_progress_bar");
        const text = this.target.querySelector("#yavin_discovery_progress_text");
        assert.strictEqual(bar.style.width, "100%");
        assert.ok(bar.classList.contains("progress-bar-striped"));
        assert.ok(bar.classList.contains("progress-bar-animated"));
        assert.strictEqual(text.textContent, "...");
    });

    QUnit.test("updateProgressBar shows backend percentage", function (assert) {
        const controller = {
            model: { root: { data: { discovery_progress: 37.6 } } },
        };

        YavinDiscoverWizardController.prototype.updateProgressBar.call(controller, false);

        const bar = this.target.querySelector("#yavin_discovery_progress_bar");
        const text = this.target.querySelector("#yavin_discovery_progress_text");
        assert.strictEqual(bar.style.width, "37.6%");
        assert.strictEqual(bar.getAttribute("aria-valuenow"), "38");
        assert.strictEqual(text.textContent, "38%");
    });

    QUnit.test("performDiscovery calls backend and reloads on success", async function (assert) {
        assert.expect(5);
        const calls = [];
        let reloads = 0;
        const controller = {
            _isDiscoveryRunning: false,
            orm: {
                call: async (...args) => {
                    calls.push(args);
                },
            },
            model: {
                root: {
                    resModel: "yavin.discover.wizard",
                    resId: 7,
                    load: async () => {
                        reloads++;
                    },
                },
            },
            updateProgressBar: (indeterminate) => {
                if (indeterminate) {
                    assert.step("indeterminate");
                }
            },
        };

        patchWithCleanup(globalThis, {
            requestAnimationFrame: (cb) => cb(),
            setTimeout: (cb) => {
                cb();
                return 0;
            },
        });

        await YavinDiscoverWizardController.prototype.performDiscovery.call(controller);

        assert.verifySteps(["indeterminate"]);
        assert.deepEqual(calls, [["yavin.discover.wizard", "action_start_discovery", [7]]]);
        assert.strictEqual(reloads, 1);
        assert.strictEqual(controller._isDiscoveryRunning, false);
    });

    QUnit.test("performDiscovery reloads after backend failure", async function (assert) {
        let reloads = 0;
        const controller = {
            _isDiscoveryRunning: false,
            orm: {
                call: async () => {
                    throw new Error("boom");
                },
            },
            model: {
                root: {
                    resModel: "yavin.discover.wizard",
                    resId: 8,
                    load: async () => {
                        reloads++;
                    },
                },
            },
            updateProgressBar() {},
        };

        patchWithCleanup(globalThis, {
            requestAnimationFrame: (cb) => cb(),
            setTimeout: (cb) => {
                cb();
                return 0;
            },
        });

        await YavinDiscoverWizardController.prototype.performDiscovery.call(controller);

        assert.strictEqual(reloads, 1);
        assert.strictEqual(controller._isDiscoveryRunning, false);
    });

    QUnit.test("performDiscovery blocks duplicate concurrent runs", async function (assert) {
        const deferred = new Promise((resolve) => {
            this.resolveDiscovery = resolve;
        });
        let calls = 0;
        const controller = {
            _isDiscoveryRunning: false,
            orm: {
                call: async () => {
                    calls++;
                    await deferred;
                },
            },
            model: {
                root: {
                    resModel: "yavin.discover.wizard",
                    resId: 9,
                    load: async () => {},
                },
            },
            updateProgressBar() {},
        };

        patchWithCleanup(globalThis, {
            requestAnimationFrame: (cb) => cb(),
            setTimeout: (cb) => {
                cb();
                return 0;
            },
        });

        const firstRun = YavinDiscoverWizardController.prototype.performDiscovery.call(controller);
        const secondRun = YavinDiscoverWizardController.prototype.performDiscovery.call(controller);
        await secondRun;
        this.resolveDiscovery();
        await firstRun;

        assert.strictEqual(calls, 1);
        assert.strictEqual(controller._isDiscoveryRunning, false);
    });
});
