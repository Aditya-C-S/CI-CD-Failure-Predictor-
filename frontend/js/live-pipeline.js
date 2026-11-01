/**
 * frontend/js/live-pipeline.js
 * Live Pipeline Monitoring Controller for UI Batch B.
 * Implements: Pipeline Run Header with adjacent Copy Demo ID, Live Risk Gauge,
 * Checkpoint Timeline, Terminal-Style Log Viewer, Parser V2 Evidence Stream,
 * and Early Warning Panel.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";
import { navigation } from "./navigation.js";

export class LivePipelineController {
  constructor() {
    this.activeRunId = null;
    this.runData = null;
    this.pollTimer = null;
    this.pollIntervalMs = 2500;
    this.isPolling = false;
    this.autoScrollEnabled = true;
    this.displayedLogsBuffer = "";
    this.connectionStatus = "DISCONNECTED"; // "CONNECTED" | "RECONNECTING" | "DISCONNECTED"
    this.lastLogTimestamp = null;
    this.elapsedSeconds = 0;
    this.durationTimer = null;
  }

  init() {
    this.bindEvents();

    // Check if an active run ID was persisted or passed via URL param
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.get("empty") === "1") {
      this.activeRunId = null;
      const emptyState = document.getElementById("live-pipeline-empty-state");
      const liveContent = document.getElementById("live-pipeline-content-area");
      if (emptyState) emptyState.style.display = "flex";
      if (liveContent) liveContent.style.display = "none";
      return;
    }

    const queryRunId = urlParams.get("run_id");
    const storedRunId = queryRunId || localStorage.getItem("cicd_active_demo_run_id");
    if (storedRunId) {
      this.setActiveRun(storedRunId);
    } else {
      this.showEmptyState();
      this.loadRecentRunsForDropdown();
    }

    // Refresh when route activates
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "live-pipeline") {
        this.onResumeRoute();
      } else {
        this.onPauseRoute();
      }
    });
  }

  bindEvents() {
    // Empty state launch button
    const btnLaunchEmpty = document.getElementById("live-empty-launch-btn");
    if (btnLaunchEmpty) {
      btnLaunchEmpty.addEventListener("click", () => navigation.navigate("demo-control"));
    }

    // Run switcher dropdown if multiple runs exist
    const runSelect = document.getElementById("live-run-select");
    if (runSelect) {
      runSelect.addEventListener("change", (e) => {
        if (e.target.value) {
          this.setActiveRun(e.target.value);
        }
      });
    }

    // Log viewer controls
    const btnAutoScroll = document.getElementById("btn-toggle-autoscroll");
    if (btnAutoScroll) {
      btnAutoScroll.addEventListener("click", () => {
        this.autoScrollEnabled = !this.autoScrollEnabled;
        btnAutoScroll.classList.toggle("active", this.autoScrollEnabled);
        btnAutoScroll.textContent = this.autoScrollEnabled ? "Auto-scroll: ON" : "Auto-scroll: PAUSED";
      });
    }

    const btnClearLogs = document.getElementById("btn-clear-log-view");
    if (btnClearLogs) {
      btnClearLogs.addEventListener("click", () => {
        this.displayedLogsBuffer = "";
        const terminal = document.getElementById("live-terminal-content");
        if (terminal) {
          terminal.innerHTML = `<span class="terminal-dim">// Log display buffer cleared by user. Backend logs remain intact.</span>\n`;
        }
        Utils.showToast("Local terminal view cleared", "info", 2000);
      });
    }

    const btnCopyLogs = document.getElementById("btn-copy-visible-logs");
    if (btnCopyLogs) {
      btnCopyLogs.addEventListener("click", async () => {
        if (!this.displayedLogsBuffer) {
          Utils.showToast("No logs currently displayed to copy", "info", 2000);
          return;
        }
        const ok = await Utils.copyToClipboard(this.displayedLogsBuffer);
        if (ok) {
          Utils.showToast("Visible terminal logs copied to clipboard", "success", 2500);
        } else {
          Utils.showToast("Failed to copy logs to clipboard", "error", 3000);
        }
      });
    }

    // Manual refresh button
    const btnRefresh = document.getElementById("live-pipeline-refresh-btn");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => this.fetchRunData(true));
    }

    // Clear live session button
    const btnClearLiveSession = document.getElementById("btn-clear-live-session");
    if (btnClearLiveSession) {
      btnClearLiveSession.addEventListener("click", () => this.confirmAndClearLiveSession());
    }
  }

  confirmAndClearLiveSession() {
    const isLiveRunning = this.runData && (
      this.runData.status === "running" ||
      this.runData.scenario_execution?.execution_status === "RUNNING"
    );

    if (isLiveRunning) {
      const proceed = window.confirm(
        "A live GitHub Actions workflow is currently executing.\n\n" +
        "Clearing the view will disconnect this monitoring session, but the workflow will continue executing on GitHub and its telemetry will remain saved in Run History.\n\n" +
        "Do you want to proceed and clear the live monitoring session?"
      );
      if (!proceed) return;
    }

    this.clearLiveSession();
  }

  clearLiveSession() {
    this.stopPolling();
    this.activeRunId = null;
    this.runData = null;
    this.displayedLogsBuffer = "";
    localStorage.removeItem("cicd_active_demo_run_id");
    sessionStorage.removeItem("cicd_active_demo_run_id");

    // Clean URL query parameter so page reloads or route switches don't re-select it
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.has("run_id")) {
        url.searchParams.delete("run_id");
        window.history.replaceState({}, document.title, url.pathname + (url.searchParams.toString() ? "?" + url.searchParams.toString() : "") + url.hash);
      }
    } catch (e) {
      console.warn("Could not clear URL run_id parameter:", e);
    }

    const runSelect = document.getElementById("live-run-select");
    if (runSelect) {
      runSelect.value = "";
    }

    this.showEmptyState();
    this.loadRecentRunsForDropdown();
    Utils.showToast("Live session cleared. Historical execution data remains preserved in Run History.", "info", 3500);
  }

  showEmptyState() {
    this.stopPolling();
    this.activeRunId = null;
    this.runData = null;
    this.displayedLogsBuffer = "";
    localStorage.removeItem("cicd_active_demo_run_id");
    sessionStorage.removeItem("cicd_active_demo_run_id");

    const emptyState = document.getElementById("live-pipeline-empty-state");
    const liveContent = document.getElementById("live-pipeline-content-area");
    if (emptyState) emptyState.style.display = "flex";
    if (liveContent) liveContent.style.display = "none";

    // Also reset live header Demo ID
    const runIdEl = document.getElementById("live-header-run-id");
    if (runIdEl) runIdEl.textContent = "—";

    // Reset gauge and timeline to clean initial states
    const pctEl = document.getElementById("live-risk-percent");
    if (pctEl) {
      pctEl.textContent = "0.0%";
      pctEl.className = "risk-pct-value font-bold text-muted";
    }
    const tierEl = document.getElementById("live-risk-tier-badge");
    if (tierEl) {
      tierEl.className = "badge badge-neutral";
      tierEl.textContent = "IDLE / READY";
    }
    const terminal = document.getElementById("live-terminal-content");
    if (terminal) {
      terminal.innerHTML = `<span class="terminal-dim">// Live session cleared. Select a run or launch a new execution from Demo Control.</span>\n`;
    }
    this.renderPendingCheckpoints();
  }

  resetRunUI(runId) {
    this.runData = null;
    this.displayedLogsBuffer = "";
    this.lastLogTimestamp = null;
    this.connectionStatus = "WAITING";

    // Show live content, hide empty state
    const emptyState = document.getElementById("live-pipeline-empty-state");
    const liveContent = document.getElementById("live-pipeline-content-area");
    if (emptyState) emptyState.style.display = "none";
    if (liveContent) liveContent.style.display = "flex";

    // Reset Header elements
    const runIdEl = document.getElementById("live-header-run-id");
    if (runIdEl) runIdEl.textContent = runId || "—";
    const statusEl = document.getElementById("live-header-status-badge");
    if (statusEl) statusEl.innerHTML = Utils.renderBadge("DISPATCHED");
    const durationEl = document.getElementById("live-elapsed-duration");
    if (durationEl) durationEl.textContent = "—";
    const startEl = document.getElementById("live-header-started-at");
    if (startEl) startEl.textContent = "Awaiting runner start";
    const sourceEl = document.getElementById("live-header-source");
    if (sourceEl) sourceEl.innerHTML = `<span class="badge badge-neutral">AWAITING TELEMETRY</span>`;

    // Reset Risk Gauge
    const pctEl = document.getElementById("live-risk-percent");
    if (pctEl) {
      pctEl.textContent = "—";
      pctEl.className = "risk-pct-value font-bold text-muted";
    }
    const tierEl = document.getElementById("live-risk-tier-badge");
    if (tierEl) {
      tierEl.className = "badge badge-neutral";
      tierEl.textContent = "AWAITING TELEMETRY";
    }
    const depthEl = document.getElementById("live-risk-depth");
    if (depthEl) depthEl.textContent = "Depth: —";
    const modelEl = document.getElementById("live-risk-model");
    if (modelEl) modelEl.textContent = "Predictor: Awaiting telemetry";
    const tsEl = document.getElementById("live-risk-timestamp");
    if (tsEl) tsEl.textContent = "Last Evaluated: Awaiting telemetry";

    const circle = document.getElementById("live-risk-gauge-circle");
    if (circle) {
      const circumference = 339.29;
      circle.style.strokeDasharray = `${circumference}`;
      circle.style.strokeDashoffset = `${circumference}`;
      circle.style.stroke = "var(--border-subtle, #334155)";
    }

    // Reset Sparkline
    const sparkline = document.getElementById("live-risk-progression-graph");
    if (sparkline) {
      sparkline.innerHTML = `<span class="text-muted text-xs">Waiting for GitHub Actions telemetry. No predictions evaluated yet.</span>`;
    }

    // Reset Checkpoint Timeline (all PENDING)
    this.renderPendingCheckpoints();

    // Reset Log Viewer
    const terminal = document.getElementById("live-terminal-content");
    const countEl = document.getElementById("live-log-lines-count");
    const lastTsEl = document.getElementById("live-last-log-timestamp");
    if (terminal) {
      terminal.innerHTML = `<span class="terminal-dim">// Waiting for GitHub Actions telemetry from runner (Demo ID: ${Utils.escapeHtml(runId)})...</span>\n`;
    }
    if (countEl) countEl.textContent = "0 lines";
    if (lastTsEl) lastTsEl.textContent = "Waiting for telemetry";

    // Reset Parser V2 Evidence
    const evidenceContainer = document.getElementById("live-evidence-stream-container");
    if (evidenceContainer) {
      evidenceContainer.innerHTML = `
        <div class="evidence-empty-box">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-muted">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span class="text-muted text-sm">No evidence received yet. Waiting for GitHub Actions telemetry.</span>
        </div>
      `;
    }

    // Reset Early Warnings
    const warningsContainer = document.getElementById("live-early-warnings-container");
    const countBadge = document.getElementById("live-warnings-count-badge");
    if (countBadge) countBadge.textContent = "0";
    if (warningsContainer) {
      warningsContainer.innerHTML = `
        <div class="warning-empty-box">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-muted">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span class="text-muted text-sm">No warning events yet. Awaiting runtime predictions from incoming telemetry.</span>
        </div>
      `;
    }

    // Reset Connection Status Pill
    this.updateConnectionPill();
  }

  renderPendingCheckpoints() {
    const timelineContainer = document.getElementById("live-checkpoint-timeline");
    if (!timelineContainer) return;
    const depths = [25, 50, 75, 100];
    const depthLabels = {
      25: "Runner Init & Setup",
      50: "Dependency Installation",
      75: "Validation & Compiling",
      100: "Unit Test & Post-Mortem"
    };
    timelineContainer.innerHTML = depths.map(d => `
      <div class="timeline-checkpoint-card state-pending" style="border: 1px solid var(--border-subtle);">
        <div class="checkpoint-top-row">
          <span class="checkpoint-depth-pill">${d}%</span>
          <span class="checkpoint-type-badge type-pending">PENDING</span>
        </div>
        <h4 class="checkpoint-stage-name">${depthLabels[d]}</h4>
        <div class="checkpoint-metrics">
          <div class="checkpoint-metric-item">
            <span class="cp-label">Failure Risk:</span>
            <span class="cp-val font-bold text-muted">—</span>
          </div>
          <div class="checkpoint-metric-item">
            <span class="cp-label">Timestamp:</span>
            <span class="cp-val font-mono text-xs">—</span>
          </div>
        </div>
        <div class="checkpoint-status-bar">
          <span class="status-indicator-dot"></span>
          <span class="status-indicator-text">PENDING</span>
        </div>
      </div>
    `).join("");
  }

  setActiveRun(runId) {
    if (!runId) return;
    this.activeRunId = runId;
    localStorage.setItem("cicd_active_demo_run_id", runId);
    this.resetRunUI(runId);
    this.fetchRunData(true);
    this.startPolling();
  }

  onResumeRoute() {
    const stored = localStorage.getItem("cicd_active_demo_run_id");
    if (stored) {
      if (stored !== this.activeRunId) {
        this.setActiveRun(stored);
      } else {
        this.fetchRunData(false);
        this.startPolling();
      }
    } else {
      this.showEmptyState();
      this.loadRecentRunsForDropdown();
    }
  }

  onPauseRoute() {
    this.stopPolling();
  }

  startPolling() {
    if (this.pollTimer) clearInterval(this.pollTimer);
    this.pollTimer = setInterval(() => {
      this.fetchRunData(false);
    }, this.pollIntervalMs);
  }

  stopPolling() {
    if (this.pollTimer) {
      clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }



  async loadRecentRunsForDropdown() {
    try {
      const runs = await api.getRecentRuns(10);
      const select = document.getElementById("live-run-select");
      if (select && Array.isArray(runs) && runs.length > 0) {
        select.innerHTML = `<option value="">-- Select Active / Recent Run --</option>` +
          runs.map(r => `<option value="${r.run_id}">${Utils.escapeHtml(r.run_id)} (${Utils.escapeHtml(r.scenario_preset || "scenario")})</option>`).join("");
      }
    } catch {
      // Fallback
    }
  }

  async fetchRunData(showToastFeedback = false) {
    if (!this.activeRunId) return;

    try {
      const run = await api.getRunDetails(this.activeRunId);
      this.runData = run;

      // Update connection status
      const hasLogs = Boolean(run && ((run.log_chunks && run.log_chunks.length > 0) || (run.accumulated_log && run.accumulated_log.trim().length > 0)));
      this.connectionStatus = hasLogs ? "CONNECTED" : "WAITING";
      this.updateConnectionPill();

      this.renderHeader(run);
      this.renderRiskGauge(run);
      this.renderCheckpointTimeline(run);
      this.renderLogViewer(run);
      this.renderEvidenceStream(run);
      this.renderEarlyWarnings(run);

      // Manage duration timer
      this.updateDurationTimer(run);

      // If run reached terminal state, stop aggressive polling
      if (["completed", "failed"].includes(run.status) || ["success", "failure"].includes(run.actual_outcome)) {
        if (this.pollTimer) {
          clearInterval(this.pollTimer);
          // Set to a relaxed poll (10s)
          this.pollTimer = setInterval(() => this.fetchRunData(false), 10000);
        }
      }

      if (showToastFeedback) {
        Utils.showToast("Live pipeline telemetry updated", "info", 1500);
      }
    } catch (err) {
      console.warn("Failed to fetch live run telemetry:", err);
      this.connectionStatus = "RECONNECTING";
      this.updateConnectionPill();
      if (showToastFeedback) {
        Utils.showToast(`Telemetry fetch error: ${err.message}`, "error", 3500);
      }
    }
  }

  updateConnectionPill() {
    const pill = document.getElementById("live-connection-status-pill");
    if (!pill) return;
    if (this.connectionStatus === "RECONNECTING") {
      pill.className = "badge badge-degraded";
      pill.innerHTML = `<span class="status-dot"></span> RECONNECTING`;
      return;
    }

    const run = this.runData;
    const hasLogs = Boolean(run && ((run.log_chunks && run.log_chunks.length > 0) || (run.accumulated_log && run.accumulated_log.trim().length > 0)));
    const isCompleted = run && (["completed", "failed"].includes(run.status) || ["success", "failure"].includes(run.actual_outcome));

    if (isCompleted) {
      pill.className = "badge badge-neutral";
      pill.innerHTML = `<span class="status-dot"></span> SESSION FINISHED`;
    } else if (hasLogs) {
      pill.className = "badge badge-healthy";
      pill.innerHTML = `<span class="status-dot pulse"></span> CONNECTED`;
    } else {
      pill.className = "badge badge-neutral";
      pill.innerHTML = `<span class="status-dot pulse"></span> WAITING FOR TELEMETRY`;
    }
  }

  updateDurationTimer(run) {
    const durationEl = document.getElementById("live-elapsed-duration");
    if (!durationEl) return;

    const ciExec = run.ci_execution || {};
    if (ciExec.duration_seconds !== undefined && ciExec.duration_seconds !== null) {
      durationEl.textContent = Utils.formatDuration(ciExec.duration_seconds);
      return;
    }

    if (ciExec.started_at) {
      const startTime = new Date(ciExec.started_at).getTime();
      const endTime = ciExec.completed_at ? new Date(ciExec.completed_at).getTime() : Date.now();
      const diffSecs = Math.max(0, Math.floor((endTime - startTime) / 1000));
      durationEl.textContent = Utils.formatDuration(diffSecs);
    } else {
      durationEl.textContent = "—";
    }
  }

  /* =========================================================================
     1.1 Pipeline Run Header
     ========================================================================= */
  renderHeader(run) {
    // Show live content, hide empty state
    const emptyState = document.getElementById("live-pipeline-empty-state");
    const liveContent = document.getElementById("live-pipeline-content-area");
    if (emptyState) emptyState.style.display = "none";
    if (liveContent) liveContent.style.display = "flex";

    // Run ID
    const runIdEl = document.getElementById("live-header-run-id");
    if (runIdEl) runIdEl.textContent = run.run_id || "—";

    // Copy Demo ID Button
    const copyBtn = document.getElementById("btn-live-copy-demo-id");
    if (copyBtn) {
      // Re-bind to ensure current activeRunId
      copyBtn.onclick = async () => {
        const ok = await Utils.copyToClipboard(run.run_id);
        const feedbackText = copyBtn.querySelector(".copy-feedback-text");
        if (ok) {
          copyBtn.classList.add("copied");
          if (feedbackText) feedbackText.textContent = "Copied!";
          Utils.showToast(`Copied Demo ID: ${run.run_id}`, "success", 2500);
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            if (feedbackText) feedbackText.textContent = "Copy Demo ID";
          }, 2000);
        } else {
          Utils.showToast("Failed to copy Demo ID", "error", 3000);
        }
      };
    }

    // Repository
    const repoEl = document.getElementById("live-header-repo");
    if (repoEl) repoEl.textContent = run.commit_info?.repo_id || run.repo_id || "Aditya-C-S/demo-order-service";

    // Commit SHA
    const commitEl = document.getElementById("live-header-commit");
    const rawCommit = run.commit_info?.commit_sha || run.commit_sha || "HEAD";
    if (commitEl) commitEl.textContent = rawCommit.slice(0, 7);

    // Scenario
    const scenarioEl = document.getElementById("live-header-scenario");
    if (scenarioEl) {
      const sc = run.scenario_preset || run.scenario_id || "none";
      scenarioEl.textContent = sc.toUpperCase();
    }

    // Predictor
    const modelEl = document.getElementById("live-header-predictor");
    if (modelEl) {
      const m = run.runtime_model || "bilstm2";
      const modelLabels = {
        "bilstm2": "BiLSTM v2 (5-Fold Ensemble)",
        "svm": "TF-IDF + Linear SVM",
        "logistic_regression": "TF-IDF + Logistic Regression"
      };
      modelEl.textContent = modelLabels[m] || m;
    }

    // Status Badge
    const statusEl = document.getElementById("live-header-status-badge");
    if (statusEl) {
      const rawStatus = run.actual_outcome === "success" ? "SUCCESS" :
                        run.actual_outcome === "failure" ? "FAILED" :
                        (run.status || "RUNNING").toUpperCase();
      statusEl.innerHTML = Utils.renderBadge(rawStatus);
    }

    // Started At
    const startEl = document.getElementById("live-header-started-at");
    if (startEl) {
      const ts = run.ci_execution?.started_at || run.created_at;
      startEl.textContent = Utils.formatDateTime(ts);
    }

    // Execution Source
    const sourceEl = document.getElementById("live-header-source");
    if (sourceEl) {
      const src = run.execution_source || "LOCAL SIMULATION / BENCHMARK REPLAY";
      const isLive = src.includes("GITHUB") || src.includes("LIVE");
      sourceEl.innerHTML = `<span class="badge ${isLive ? 'badge-info' : 'badge-neutral'}">${Utils.escapeHtml(src)}</span>`;
    }
  }

  /* =========================================================================
     1.2 Live Risk Monitoring (Risk Gauge & Historical Progression)
     ========================================================================= */
  renderRiskGauge(run) {
    const curPred = run.current_runtime_prediction || {};
    const probPct = curPred.failure_probability_pct !== undefined 
      ? curPred.failure_probability_pct 
      : (curPred.failure_probability !== undefined ? Math.round(curPred.failure_probability * 100) : 0);

    const probVal = curPred.failure_probability !== undefined ? curPred.failure_probability : (probPct / 100);
    const depth = curPred.depth_percentage || curPred.checkpoint || 25;
    const model = curPred.model_name || run.runtime_model || "bilstm2";
    const ts = curPred.timestamp ? Utils.formatDateTime(curPred.timestamp) : "Awaiting telemetry";

    // Use unified risk classifier
    const riskInfo = Utils.classifyRisk(probVal);

    // Elements
    const pctEl = document.getElementById("live-risk-percent");
    if (pctEl) {
      pctEl.textContent = `${riskInfo.percentage}%`;
      pctEl.className = `risk-pct-value font-bold ${riskInfo.textClass}`;
    }

    const tierEl = document.getElementById("live-risk-tier-badge");
    if (tierEl) {
      tierEl.className = `badge ${riskInfo.badgeClass}`;
      tierEl.textContent = riskInfo.label;
    }

    const depthEl = document.getElementById("live-risk-depth");
    if (depthEl) depthEl.textContent = `Depth: ${depth}%`;

    const modelEl = document.getElementById("live-risk-model");
    if (modelEl) modelEl.textContent = `Predictor: ${model}`;

    const tsEl = document.getElementById("live-risk-timestamp");
    if (tsEl) tsEl.textContent = `Last Evaluated: ${ts}`;

    // SVG Circular Progress Ring
    const circle = document.getElementById("live-risk-gauge-circle");
    if (circle) {
      // Circumference for r=54 is 2 * PI * 54 = 339.29
      const circumference = 339.29;
      const offset = circumference - (riskInfo.percentage / 100) * circumference;
      circle.style.strokeDasharray = `${circumference}`;
      circle.style.strokeDashoffset = `${offset}`;
      circle.style.stroke = riskInfo.colorVar;
    }

    // Render Risk Progression Mini Sparkline / History
    this.renderRiskProgressionGraph(run);
  }

  renderRiskProgressionGraph(run) {
    const container = document.getElementById("live-risk-progression-graph");
    if (!container) return;

    const history = Array.isArray(run.prediction_history) && run.prediction_history.length > 0 
      ? run.prediction_history 
      : (Array.isArray(run.runtime_predictions) ? run.runtime_predictions : []);

    if (history.length === 0) {
      container.innerHTML = `<span class="text-muted text-xs">No prediction history points yet.</span>`;
      return;
    }

    // Render step points
    container.innerHTML = `
      <div class="risk-progression-steps">
        ${history.map((pt, idx) => {
          const depth = pt.depth_percentage || pt.checkpoint || `${(idx + 1) * 25}%`;
          const rawPct = pt.failure_probability_pct !== undefined ? pt.failure_probability_pct : (pt.failure_probability ? Math.round(pt.failure_probability * 100) : 0);
          const isAct = pt.prediction_type === "ACTUAL" || !pt.is_projected;
          const riskInfo = Utils.classifyRisk(rawPct);
          return `
            <div class="risk-point-col">
              <span class="risk-col-val font-bold ${riskInfo.textClass}">${riskInfo.percentage}%</span>
              <div class="risk-bar-container">
                <div class="risk-bar-fill ${riskInfo.bgClass}" style="height: ${Math.max(10, riskInfo.percentage)}%; background-color: ${riskInfo.colorVar};"></div>
              </div>
              <span class="risk-col-depth">${depth}%</span>
              <span class="risk-col-type ${isAct ? 'type-actual' : 'type-projected'}">${isAct ? 'ACTUAL' : 'PROJ'}</span>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  /* =========================================================================
     1.3 Checkpoint Timeline (25%, 50%, 75%, 100%)
     Strictly distinguishes ACTUAL vs PROJECTED checkpoints.
     ========================================================================= */
  renderCheckpointTimeline(run) {
    const timelineContainer = document.getElementById("live-checkpoint-timeline");
    if (!timelineContainer) return;

    const depths = [25, 50, 75, 100];
    const depthLabels = {
      25: "Runner Init & Setup",
      50: "Dependency Installation",
      75: "Validation & Compiling",
      100: "Unit Test & Post-Mortem"
    };

    // Actual predictions by depth
    const actualMap = {};
    (run.runtime_predictions || []).forEach(p => {
      const d = p.depth_percentage || p.checkpoint;
      if (d && p.prediction_type === "ACTUAL" && !p.is_projected) {
        actualMap[d] = p;
      }
    });

    // Checkpoint projections dictionary from backend
    const projMap = run.checkpoint_projections || {};

    // Determine highest actual depth reached
    const actualDepths = Object.keys(actualMap).map(Number);
    const maxActualDepth = actualDepths.length > 0 ? Math.max(...actualDepths) : 0;
    const isFailed = run.actual_outcome === "failure" || (run.ci_execution && run.ci_execution.exit_code === 1);

    timelineContainer.innerHTML = depths.map((d) => {
      const actualPred = actualMap[d];
      const projPred = projMap[d] || {};

      let state = "pending"; // completed, active, failed, skipped, projected, pending
      let typeLabel = "PENDING";
      let riskDisplay = "—";
      let timestampDisplay = "—";
      let riskInfo = Utils.classifyRisk(null);
      let statusIndicatorText = "PENDING";

      if (actualPred) {
        if (actualPred.is_skipped) {
          state = "skipped";
          typeLabel = "SKIPPED";
          riskDisplay = "Not Executed";
          timestampDisplay = "Step Skipped";
          statusIndicatorText = "SKIPPED";
        } else if (isFailed && d === maxActualDepth) {
          state = "failed";
          typeLabel = "ACTUAL";
          riskInfo = Utils.classifyRisk(actualPred.failure_probability_pct ?? actualPred.failure_probability * 100);
          riskDisplay = `${riskInfo.percentage}%`;
          timestampDisplay = Utils.formatDateTime(actualPred.timestamp);
          statusIndicatorText = "FAILED";
        } else {
          state = "completed";
          typeLabel = "ACTUAL";
          riskInfo = Utils.classifyRisk(actualPred.failure_probability_pct ?? actualPred.failure_probability * 100);
          riskDisplay = `${riskInfo.percentage}%`;
          timestampDisplay = Utils.formatDateTime(actualPred.timestamp);
          statusIndicatorText = "EVALUATED";
        }
      } else if (projPred && projPred.type === "PROJECTED") {
        state = "projected";
        typeLabel = "PROJECTED";
        riskInfo = Utils.classifyRisk(projPred.failure_probability_pct);
        riskDisplay = `${projPred.failure_probability_pct}% (Proj)`;
        if (isFailed && d > maxActualDepth) {
          timestampDisplay = "Projected (Stage Skipped)";
          statusIndicatorText = "PROJECTED (SKIPPED)";
        } else {
          timestampDisplay = "Projected Estimate";
          statusIndicatorText = "PROJECTED";
        }
      } else if (isFailed && d > maxActualDepth) {
        state = "skipped";
        typeLabel = "SKIPPED";
        riskDisplay = "Not Executed";
        timestampDisplay = "Halted on failure";
        statusIndicatorText = "SKIPPED";
      } else if (d === 25 && (!run.status || run.status === "running")) {
        state = "active";
        typeLabel = "IN PROGRESS";
        statusIndicatorText = "RUNNING";
      }

      // Checkpoint card styling based on state & calibrated risk
      let cardBorder = "";
      if (state === "failed") {
        cardBorder = "border: 1px solid var(--status-unhealthy);";
      } else if (state === "projected") {
        cardBorder = `border: 1px dashed ${riskInfo.colorVar};`;
      } else if (state === "completed") {
        cardBorder = `border: 1px solid ${riskInfo.colorVar};`;
      }

      return `
        <div class="timeline-checkpoint-card state-${state}" style="${cardBorder}">
          <div class="checkpoint-top-row">
            <span class="checkpoint-depth-pill">${d}%</span>
            <span class="checkpoint-type-badge type-${typeLabel.toLowerCase().replace(/[^a-z]/g, '')}">${typeLabel}</span>
          </div>
          <h4 class="checkpoint-stage-name">${depthLabels[d]}</h4>
          <div class="checkpoint-metrics">
            <div class="checkpoint-metric-item">
              <span class="cp-label">Failure Risk:</span>
              <span class="cp-val font-bold ${riskInfo.textClass}">${riskDisplay}</span>
            </div>
            <div class="checkpoint-metric-item">
              <span class="cp-label">Timestamp:</span>
              <span class="cp-val font-mono text-xs">${timestampDisplay}</span>
            </div>
          </div>
          <div class="checkpoint-status-bar">
            <span class="status-indicator-dot"></span>
            <span class="status-indicator-text">${statusIndicatorText}</span>
          </div>
        </div>
      `;
    }).join("");
  }

  /* =========================================================================
     1.4 Dedicated Terminal Log Viewer
     ========================================================================= */
  renderLogViewer(run) {
    const terminal = document.getElementById("live-terminal-content");
    const countEl = document.getElementById("live-log-lines-count");
    const lastTsEl = document.getElementById("live-last-log-timestamp");
    if (!terminal) return;

    const accumulated = run.accumulated_log || "";
    this.displayedLogsBuffer = accumulated;

    const lines = accumulated ? accumulated.splitlines ? accumulated.splitlines() : accumulated.split("\n") : [];
    if (countEl) countEl.textContent = `${lines.length} lines`;

    if (lines.length > 0) {
      this.lastLogTimestamp = new Date().toLocaleTimeString();
      if (lastTsEl) lastTsEl.textContent = `Last chunk: ${this.lastLogTimestamp}`;
    }

    if (lines.length === 0) {
      terminal.innerHTML = `<span class="terminal-dim">// Awaiting incoming telemetry stream from CI runner...</span>\n`;
      return;
    }

    // Format lines with line numbers and stderr highlighting
    const formattedHtml = lines.map((line, idx) => {
      const lineNum = idx + 1;
      const isErr = /error|failed|failure|fatal|exception|traceback|exit code [1-9]/i.test(line);
      const isWarn = /warning|warn|deprecated/i.test(line);
      const isGroup = /##\[group\]|##\[endgroup\]/i.test(line);

      let lineClass = "terminal-line";
      if (isErr) lineClass += " terminal-err";
      else if (isWarn) lineClass += " terminal-warn";
      else if (isGroup) lineClass += " terminal-group";

      return `<div class="${lineClass}"><span class="terminal-line-num">${lineNum}</span><span class="terminal-line-text">${Utils.escapeHtml(line)}</span></div>`;
    }).join("");

    terminal.innerHTML = formattedHtml;

    // Auto-scroll to bottom if enabled
    if (this.autoScrollEnabled) {
      terminal.scrollTop = terminal.scrollHeight;
    }
  }

  /* =========================================================================
     1.5 Parser V2 Structured Evidence Stream
     ========================================================================= */
  renderEvidenceStream(run) {
    const container = document.getElementById("live-evidence-stream-container");
    if (!container) return;

    const p2 = run.parser_v2_result;
    const rca = run.rca_result;
    const evidenceItems = rca?.evidence_items || [];

    // Also extract raw evidence lines from Parser V2
    const evidenceLines = p2?.evidence_lines || [];
    const tracebackLines = p2?.traceback_lines || [];

    const hasEvidence = (evidenceItems.length > 0) || (evidenceLines.length > 0) || (p2 && p2.failure_class && p2.failure_class !== "none");

    if (!hasEvidence) {
      container.innerHTML = `
        <div class="evidence-empty-box">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-muted">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <span class="text-muted text-sm">No failure evidence detected in ingested telemetry. Pipeline execution is nominal.</span>
        </div>
      `;
      return;
    }

    const category = p2?.failure_class || rca?.primary_category || "UNKNOWN";
    const subcategory = p2?.failure_subcategory || "—";
    const failedStep = p2?.failed_step || rca?.where_failed || "—";
    const confidence = p2?.parser_confidence !== undefined ? Math.round(p2.parser_confidence * 100) : (rca?.rca_confidence ? Math.round(rca.rca_confidence * 100) : 85);
    const excerpt = evidenceLines.slice(0, 4).join("\n") || p2?.error_message || "Evidence isolated from telemetry stream.";

    container.innerHTML = `
      <div class="evidence-card">
        <div class="evidence-card-header">
          <div class="evidence-category-group">
            <span class="badge badge-unhealthy">${Utils.escapeHtml(category)}</span>
            <span class="badge-scenario">${Utils.escapeHtml(subcategory)}</span>
          </div>
          <span class="evidence-confidence-tag">Confidence: ${confidence}%</span>
        </div>
        <div class="evidence-card-body">
          <div class="evidence-meta-row">
            <span class="ev-label">Failed Step:</span>
            <span class="ev-val font-bold">${Utils.escapeHtml(failedStep)}</span>
          </div>
          <div class="evidence-code-box">
            <pre class="font-mono text-xs">${Utils.escapeHtml(excerpt)}</pre>
          </div>
        </div>
      </div>
    `;
  }

  /* =========================================================================
     1.6 Early Warning Panel (Threshold = 70%)
     ========================================================================= */
  renderEarlyWarnings(run) {
    const container = document.getElementById("live-early-warnings-container");
    const countBadge = document.getElementById("live-warnings-count-badge");
    if (!container) return;

    const warnings = Array.isArray(run.warning_history) ? run.warning_history : (run.early_warning ? [run.early_warning] : []);
    if (countBadge) countBadge.textContent = warnings.length;

    if (warnings.length === 0) {
      container.innerHTML = `
        <div class="warning-empty-box">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-success">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
            <polyline points="22 4 12 14.01 9 11.01"></polyline>
          </svg>
          <span class="text-muted text-sm">No threshold crossings detected. Failure probability has remained below the 70% early-warning threshold.</span>
        </div>
      `;
      return;
    }

    container.innerHTML = warnings.map((w, idx) => {
      const riskPct = w.failure_probability_pct ?? Math.round((w.failure_probability || 0) * 100);
      const thresholdPct = w.threshold_pct ?? 70.0;
      const model = w.model_name || w.model || "Predictor";
      const cp = w.depth_percentage || w.checkpoint || "—";
      const timeAgo = Utils.formatRelativeTime(w.timestamp);

      return `
        <div class="early-warning-alert-item">
          <div class="warning-alert-icon">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
          </div>
          <div class="warning-alert-content">
            <div class="warning-top-row">
              <span class="warning-type-title">EARLY WARNING #${idx + 1}</span>
              <span class="warning-time-ago">${timeAgo}</span>
            </div>
            <p class="warning-message-text">${Utils.escapeHtml(w.message || `Failure risk reached ${riskPct}% (Threshold: ${thresholdPct}%).`)}</p>
            <div class="warning-pills-row">
              <span class="warning-pill">Risk: <strong>${riskPct}%</strong></span>
              <span class="warning-pill">Checkpoint: <strong>${cp}%</strong></span>
              <span class="warning-pill">Predictor: <strong>${Utils.escapeHtml(model)}</strong></span>
              <span class="warning-pill">Threshold: <strong>${thresholdPct}%</strong></span>
            </div>
          </div>
        </div>
      `;
    }).join("");
  }
}

export const livePipelineController = new LivePipelineController();

