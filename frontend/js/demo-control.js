/**
 * frontend/js/demo-control.js
 * Demo Control & Scenario Orchestration Controller for UI Batch A.
 * Implements: 4 scenario cards, model selector, dispatch orchestration,
 * prominent Demo ID banner, and the specialized Copy Demo ID button.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";

export class DemoControlController {
  constructor() {
    this.scenarios = [];
    this.selectedScenarioId = "dependency"; // Default to common demo scenario
    this.selectedModel = "bilstm2";
    this.isDispatching = false;
    this.activeRun = null;
    this.pollInterval = null;
  }

  init() {
    this.bindEvents();
    this.loadScenarios();
  }

  bindEvents() {
    // Model selector change
    const modelSelect = document.getElementById("demo-model-select");
    if (modelSelect) {
      modelSelect.addEventListener("change", (e) => {
        this.selectedModel = e.target.value;
      });
    }

    // Launch button
    const launchBtn = document.getElementById("btn-dispatch-scenario");
    if (launchBtn) {
      launchBtn.addEventListener("click", () => this.handleDispatch());
    }

    // Mode toggle (Simulation vs Live GitHub Actions)
    const dryRunCheck = document.getElementById("demo-dry-run-toggle");
    if (dryRunCheck) {
      dryRunCheck.addEventListener("change", (e) => {
        const hint = document.getElementById("demo-mode-hint");
        if (hint) {
          hint.textContent = e.target.checked
            ? "Local Simulation Mode: simulates CI telemetry checkpoints instantly without requiring GitHub token."
            : "Live GitHub Actions Mode: invokes real workflow via gh CLI or GitHub Actions REST API.";
        }
      });
    }
  }

  async loadScenarios() {
    const container = document.getElementById("scenario-cards-grid");
    if (!container) return;

    try {
      this.scenarios = await api.getScenarios();
      this.renderScenarioCards(this.scenarios);
    } catch (err) {
      console.warn("Failed to fetch scenarios from API, using canonical fallback:", err);
      this.scenarios = [
        {
          scenario_id: "none",
          display_name: "Clean Pipeline",
          description: "Nominal CI/CD execution with zero faults injected. All checks, builds, and unit tests pass.",
          expected_failure_stage: null,
          expected_outcome: "success"
        },
        {
          scenario_id: "dependency",
          display_name: "Dependency Resolution Failure",
          description: "Controlled injection of unresolvable package requirement during pip install at the 50% build checkpoint.",
          expected_failure_stage: "50%",
          expected_outcome: "failure"
        },
        {
          scenario_id: "syntax",
          display_name: "Syntax Validation Failure",
          description: "Controlled injection of invalid Python syntax and module validation error at the 75% build checkpoint.",
          expected_failure_stage: "75%",
          expected_outcome: "failure"
        },
        {
          scenario_id: "pytest",
          display_name: "Test Execution Failure",
          description: "Controlled injection of assertion mismatch in test_order_creation during pytest execution at 100%.",
          expected_failure_stage: "100%",
          expected_outcome: "failure"
        }
      ];
      this.renderScenarioCards(this.scenarios);
    }
  }

  renderScenarioCards(scenarios) {
    const container = document.getElementById("scenario-cards-grid");
    if (!container) return;

    container.innerHTML = scenarios.map((s) => {
      const isSelected = s.scenario_id === this.selectedScenarioId;
      const isClean = s.expected_outcome === "success";
      
      const iconSvg = isClean
        ? `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`
        : `<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>`;

      const stageBadge = s.expected_failure_stage
        ? `<span class="scenario-stage-tag stage-fail">Injected at ${s.expected_failure_stage}</span>`
        : `<span class="scenario-stage-tag stage-clean">Nominal (100% Pass)</span>`;

      return `
        <div class="scenario-card ${isSelected ? 'selected' : ''} ${isClean ? 'scenario-clean' : 'scenario-fault'}" 
             data-scenario-id="${Utils.escapeHtml(s.scenario_id)}"
             tabindex="0"
             role="radio"
             aria-checked="${isSelected}">
          <div class="scenario-card-header">
            <div class="scenario-icon-wrapper">${iconSvg}</div>
            <div class="scenario-title-area">
              <h4 class="scenario-name">${Utils.escapeHtml(s.display_name)}</h4>
              <span class="scenario-id-code">ID: ${Utils.escapeHtml(s.scenario_id)}</span>
            </div>
            <div class="scenario-check-indicator">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
          </div>
          <p class="scenario-desc">${Utils.escapeHtml(s.description)}</p>
          <div class="scenario-card-footer">
            ${stageBadge}
            <span class="scenario-outcome-tag">${isClean ? 'Expected: SUCCESS' : 'Expected: FAILURE'}</span>
          </div>
        </div>
      `;
    }).join("");

    // Bind card selection clicks & keyboard space/enter
    container.querySelectorAll(".scenario-card").forEach((card) => {
      const selectCard = () => {
        const id = card.getAttribute("data-scenario-id");
        if (id) {
          this.selectedScenarioId = id;
          container.querySelectorAll(".scenario-card").forEach(c => {
            const active = c.getAttribute("data-scenario-id") === id;
            c.classList.toggle("selected", active);
            c.setAttribute("aria-checked", active ? "true" : "false");
          });
        }
      };

      card.addEventListener("click", selectCard);
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          selectCard();
        }
      });
    });
  }

  async handleDispatch() {
    if (this.isDispatching) return;
    this.isDispatching = true;

    const launchBtn = document.getElementById("btn-dispatch-scenario");
    const launchText = document.getElementById("dispatch-btn-text");
    const launchSpinner = document.getElementById("dispatch-btn-spinner");
    const dryRunToggle = document.getElementById("demo-dry-run-toggle");
    const isDryRun = dryRunToggle ? dryRunToggle.checked : true;

    if (launchBtn) launchBtn.disabled = true;
    if (launchText) launchText.textContent = "Orchestrating Run...";
    if (launchSpinner) launchSpinner.classList.remove("hidden");

    try {
      const result = await api.dispatchScenario({
        scenario_id: this.selectedScenarioId,
        repo_id: "Aditya-C-S/demo-order-service",
        runtime_model: this.selectedModel,
        dry_run: isDryRun
      });

      this.activeRun = result;
      localStorage.setItem("cicd_active_demo_run_id", result.run_id);

      // If local simulation mode is selected, execute sample telemetry replay
      if (isDryRun) {
        const scenarioSampleMap = {
          "dependency": "F2/run_0005.log",
          "syntax": "F1/run_0001.log",
          "pytest": "F3/107108441055.log",
          "none": "success/F1/run_0001.log"
        };
        const sampleFile = scenarioSampleMap[this.selectedScenarioId] || "F2/run_0005.log";
        try {
          await api.replaySampleStream(result.run_id, sampleFile, 40);
        } catch (replayErr) {
          console.warn("Local simulation replay error:", replayErr);
        }
      }

      this.renderActiveRunBanner(result);
      Utils.showToast(`Run created: ${result.run_id}`, "success", 4000);

      // Start status monitoring
      this.startStatusPolling(result.run_id);
    } catch (err) {
      console.error("Dispatch error:", err);
      Utils.showToast(`Failed to dispatch scenario: ${err.message}`, "error", 5000);
      this.renderDispatchError(err.message);
    } finally {
      this.isDispatching = false;
      if (launchBtn) launchBtn.disabled = false;
      if (launchText) launchText.textContent = "Launch Demo Scenario";
      if (launchSpinner) launchSpinner.classList.add("hidden");
    }
  }

  /**
   * Prominently display the generated Demo ID with the specialized Copy button.
   */
  renderActiveRunBanner(runData) {
    const container = document.getElementById("active-demo-run-banner-container");
    if (!container) return;

    const runId = runData.run_id || "—";
    const status = runData.status || "TRIGGERED";
    const scenario = runData.scenario_id || this.selectedScenarioId;
    const isDryRun = runData.dry_run !== false;

    container.innerHTML = `
      <div class="active-run-banner fade-in" id="active-run-banner">
        <div class="banner-top-row">
          <div class="banner-title-area">
            <span class="pulse-indicator"></span>
            <span class="banner-heading">Active Demo Run Generated</span>
            <span class="banner-mode-pill ${isDryRun ? 'mode-sim' : 'mode-gha'}">
              ${isDryRun ? 'Local Simulation' : 'Live GitHub Actions'}
            </span>
          </div>
          <div class="banner-status-badge">
            ${Utils.renderBadge(status)}
          </div>
        </div>

        <!-- SPECIAL REQUIREMENT: Prominent Demo ID Display & Copy Button -->
        <div class="demo-id-highlight-box">
          <div class="demo-id-content">
            <span class="demo-id-prefix">Demo ID:</span>
            <span class="demo-id-value" id="prominent-demo-id">${Utils.escapeHtml(runId)}</span>
          </div>
          <button type="button" 
                  class="btn-copy-prominent" 
                  id="btn-copy-prominent-demo-id" 
                  title="Copy Demo ID to clipboard" 
                  aria-label="Copy Demo ID">
            <svg class="copy-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
            </svg>
            <span class="copy-label-text">Copy Demo ID</span>
          </button>
        </div>

        <div class="banner-meta-grid">
          <div class="meta-item">
            <span class="meta-label">Selected Scenario:</span>
            <span class="meta-val font-bold">${Utils.escapeHtml(scenario)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Active Predictor:</span>
            <span class="meta-val">${Utils.escapeHtml(this.selectedModel)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Execution State:</span>
            <span class="meta-val font-mono" id="banner-execution-state">${Utils.escapeHtml(status)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Created At:</span>
            <span class="meta-val text-muted">${Utils.formatDateTime(new Date().toISOString())}</span>
          </div>
        </div>

        <div class="banner-instructions">
          <p class="instruction-text">
            <strong>Presenter Tip:</strong> In live GitHub Actions workflows, the telemetry reporter streams logs matching this Demo ID via the <code>--demo-run-id</code> parameter. Use the <strong>Copy Demo ID</strong> button above to provide this ID to manual workflow dispatches.
          </p>
          <div style="margin-top: 0.75rem;">
            <button type="button" class="btn btn-secondary btn-sm" id="btn-open-in-live-pipeline">
              View in Live Pipeline &rarr;
            </button>
          </div>
        </div>
      </div>
    `;

    // Bind navigation to live pipeline
    const liveBtn = container.querySelector("#btn-open-in-live-pipeline");
    if (liveBtn) {
      liveBtn.addEventListener("click", () => {
        window.location.hash = "#live-pipeline";
      });
    }

    // Bind the specialized Copy Demo ID button
    const copyBtn = container.querySelector("#btn-copy-prominent-demo-id");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const ok = await Utils.copyToClipboard(runId);
        const labelText = copyBtn.querySelector(".copy-label-text");
        if (ok) {
          copyBtn.classList.add("copied");
          if (labelText) labelText.textContent = "Copied!";
          Utils.showToast(`Copied Demo ID: ${runId}`, "success", 2500);
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            if (labelText) labelText.textContent = "Copy Demo ID";
          }, 2000);
        } else {
          Utils.showToast("Clipboard copy failed. Please select and copy manually.", "error", 3500);
        }
      });
    }
  }

  renderDispatchError(errorMsg) {
    const container = document.getElementById("active-demo-run-banner-container");
    if (!container) return;
    container.innerHTML = `
      <div class="banner-error-box fade-in">
        <div class="error-icon">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
        </div>
        <div class="error-content">
          <h4>Failed to Orchestrate Scenario</h4>
          <p>${Utils.escapeHtml(errorMsg)}</p>
        </div>
      </div>
    `;
  }

  startStatusPolling(runId) {
    if (this.pollInterval) clearInterval(this.pollInterval);

    let attempts = 0;
    this.pollInterval = setInterval(async () => {
      attempts++;
      if (attempts > 30) {
        clearInterval(this.pollInterval);
        return;
      }

      try {
        const statusResp = await api.getScenarioStatus(runId);
        const execStatus = statusResp.execution_status || statusResp.execution_state || "UNKNOWN";
        const stateEl = document.getElementById("banner-execution-state");
        if (stateEl) {
          stateEl.textContent = execStatus;
        }

        // If completed or failed, stop polling
        if (["COMPLETED", "FAILED", "CANCELLED"].includes(execStatus)) {
          clearInterval(this.pollInterval);
        }
      } catch {
        // Run may not have written status yet
      }
    }, 3000);
  }
}

export const demoControlController = new DemoControlController();

