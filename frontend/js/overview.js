/**
 * frontend/js/overview.js
 * Overview Dashboard Controller & Renderer for UI Batch A.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";
import { navigation } from "./navigation.js";

export class OverviewController {
  constructor() {
    this.latestRun = null;
    this.systemHealth = null;
    this.recentRuns = [];
    this.recentWarnings = [];
    this.isRefreshing = false;
  }

  init() {
    this.bindEvents();
    this.loadData();
  }

  bindEvents() {
    const refreshBtn = document.getElementById("overview-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => this.loadData(true));
    }

    const quickLaunchBtn = document.getElementById("quick-action-launch-demo");
    if (quickLaunchBtn) {
      quickLaunchBtn.addEventListener("click", () => navigation.navigate("demo-control"));
    }

    const quickHealthBtn = document.getElementById("quick-action-view-health");
    if (quickHealthBtn) {
      quickHealthBtn.addEventListener("click", () => navigation.navigate("system-health"));
    }

    // Refresh when route switches back to overview
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "overview") {
        this.loadData(false);
      }
    });
  }

  async loadData(showToastFeedback = false) {
    if (this.isRefreshing) return;
    this.isRefreshing = true;

    const refreshIcon = document.getElementById("overview-refresh-icon");
    if (refreshIcon) refreshIcon.classList.add("spin");

    try {
      // Parallel fetch of actual backend metrics
      const [healthData, runsData, warningsData] = await Promise.allSettled([
        api.getSystemHealth(),
        api.getRecentRuns(15),
        api.getRecentWarnings(10)
      ]);

      if (healthData.status === "fulfilled") {
        this.systemHealth = healthData.value;
        this.renderSystemCards(this.systemHealth);
        this.updateHeaderHealthBadge(this.systemHealth.status);
      } else {
        console.error("Health fetch failed:", healthData.reason);
        this.renderHealthError(healthData.reason.message);
        this.updateHeaderHealthBadge("OFFLINE");
      }

      if (runsData.status === "fulfilled" && Array.isArray(runsData.value)) {
        this.recentRuns = runsData.value;
        this.latestRun = this.recentRuns.length > 0 ? this.recentRuns[0] : null;
        this.renderLatestRunCard(this.latestRun);
        this.renderRecentActivity(this.recentRuns);
      } else {
        this.renderLatestRunCard(null);
        this.renderRecentActivity([]);
      }

      if (warningsData.status === "fulfilled" && Array.isArray(warningsData.value)) {
        this.recentWarnings = warningsData.value;
        this.renderWarningsCount(this.recentWarnings.length);
      } else {
        this.renderWarningsCount(0);
      }

      if (showToastFeedback) {
        Utils.showToast("Overview dashboard updated", "info", 2000);
      }
    } catch (err) {
      console.error("Overview data load error:", err);
      Utils.showToast(`Error updating overview: ${err.message}`, "error", 4000);
    } finally {
      this.isRefreshing = false;
      if (refreshIcon) refreshIcon.classList.remove("spin");
    }
  }

  updateHeaderHealthBadge(status) {
    const badgeEl = document.getElementById("header-system-status");
    if (!badgeEl) return;
    badgeEl.innerHTML = Utils.renderBadge(status || "UNKNOWN", status ? `System: ${status}` : "System: Checking");
  }

  renderSystemCards(health) {
    // 1. Overall status
    const statusVal = document.getElementById("metric-overall-status");
    if (statusVal) {
      statusVal.innerHTML = Utils.renderBadge(health.status);
    }

    // 2. Neo4j Status
    const neo4jVal = document.getElementById("metric-neo4j-status");
    if (neo4jVal) {
      const n4j = health.components?.neo4j;
      const n4jStatus = n4j?.status || "UNKNOWN";
      const modeLabel = n4j?.mode ? ` (${n4j.mode})` : "";
      neo4jVal.innerHTML = Utils.renderBadge(n4jStatus, `${n4jStatus}${modeLabel}`);
    }

    // 3. Runtime Models
    const modelsVal = document.getElementById("metric-runtime-models");
    if (modelsVal) {
      const rtm = health.components?.runtime_models || {};
      const readyCount = Object.values(rtm).filter(m => m.status === "HEALTHY").length;
      const totalCount = Object.keys(rtm).length || 3;
      modelsVal.innerHTML = `
        <span class="metric-number">${readyCount}/${totalCount}</span>
        <span class="metric-sublabel">BiLSTM v2, SVM, LR Online</span>
      `;
    }

    // 4. Metadata Model
    const metaVal = document.getElementById("metric-metadata-model");
    if (metaVal) {
      const meta = health.components?.metadata_model;
      const isReady = meta?.status === "HEALTHY";
      metaVal.innerHTML = Utils.renderBadge(isReady ? "HEALTHY" : "DEGRADED", isReady ? "LightGBM Ready (38 Feat)" : "Metadata Offline");
    }
  }

  renderWarningsCount(count) {
    const warningEl = document.getElementById("metric-warnings-count");
    if (warningEl) {
      warningEl.innerHTML = `
        <span class="metric-number ${count > 0 ? 'text-warning' : 'text-muted'}">${count}</span>
        <span class="metric-sublabel">Active early warning events</span>
      `;
    }
  }

  renderHealthError(errorMsg) {
    const statusVal = document.getElementById("metric-overall-status");
    if (statusVal) {
      statusVal.innerHTML = Utils.renderBadge("UNHEALTHY", "Offline / Unreachable");
    }
  }

  renderLatestRunCard(run) {
    const container = document.getElementById("latest-run-card-container");
    if (!container) return;

    if (!run) {
      container.innerHTML = `
        <div class="empty-state-card">
          <div class="empty-icon">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
          </div>
          <h4 class="empty-title">No Pipeline Runs Recorded Yet</h4>
          <p class="empty-desc">Create your first demo scenario run to view real-time predictions, telemetry checkpoints, and root cause analysis.</p>
          <button type="button" class="btn btn-primary" id="btn-empty-create-run">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            Launch Demo Scenario
          </button>
        </div>
      `;
      const btn = container.querySelector("#btn-empty-create-run");
      if (btn) btn.addEventListener("click", () => navigation.navigate("demo-control"));
      return;
    }

    // Determine status & risk metrics
    const runId = run.run_id || "—";
    const status = run.actual_outcome === "success" ? "SUCCESS" : (run.actual_outcome === "failure" ? "FAILED" : (run.status || "RUNNING").toUpperCase());
    const repo = run.repo_id || "Aditya-C-S/demo-order-service";
    const commit = run.commit_sha ? run.commit_sha.slice(0, 7) : (run.commit_info?.sha ? run.commit_info.sha.slice(0, 7) : "—");
    const scenario = run.scenario_preset || run.scenario_id || "Standard";
    
    // Risk score
    const curPred = run.current_runtime_prediction || {};
    const riskPct = curPred.failure_probability_pct !== undefined ? curPred.failure_probability_pct : (curPred.failure_probability !== undefined ? Math.round(curPred.failure_probability * 100) : "—");
    const warningCount = Array.isArray(run.warning_history) ? run.warning_history.length : 0;
    const createdAt = Utils.formatDateTime(run.created_at);
    const duration = Utils.formatDuration(run.ci_execution?.duration_seconds);

    container.innerHTML = `
      <div class="run-featured-card">
        <div class="run-featured-header">
          <div class="run-id-badge-group">
            <span class="run-id-label">Active / Latest Run:</span>
            <span class="run-id-mono" id="overview-featured-run-id">${Utils.escapeHtml(runId)}</span>
            <button type="button" class="btn-copy-id" id="btn-copy-latest-run" title="Copy Demo ID" aria-label="Copy Demo ID">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span class="copy-feedback-text">Copy ID</span>
            </button>
          </div>
          <div class="run-status-wrapper">
            ${Utils.renderBadge(status)}
          </div>
        </div>

        <div class="run-featured-grid">
          <div class="run-field-item">
            <span class="field-label">Repository</span>
            <span class="field-value">${Utils.escapeHtml(repo)}</span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Commit SHA</span>
            <span class="field-value font-mono"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="display:inline; margin-right:4px;"><circle cx="12" cy="12" r="4"/><line x1="1.05" y1="12" x2="7" y2="12"/><line x1="17.01" y1="12" x2="22.96" y2="12"/></svg>${Utils.escapeHtml(commit)}</span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Scenario</span>
            <span class="field-value">${Utils.escapeHtml(scenario)}</span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Execution Source</span>
            <span class="field-value font-bold">${Utils.escapeHtml(run.execution_source || "LOCAL SIMULATION / BENCHMARK REPLAY")}</span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Runtime Failure Risk</span>
            <span class="field-value font-bold ${Utils.classifyRisk(riskPct).textClass}">
              ${riskPct !== "—" ? `${Utils.classifyRisk(riskPct).percentage}%` : "—"}
            </span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Warning Alerts</span>
            <span class="field-value ${warningCount > 0 ? 'text-warning font-bold' : ''}">
              ${warningCount} event${warningCount === 1 ? '' : 's'}
            </span>
          </div>

          <div class="run-field-item">
            <span class="field-label">Executed At</span>
            <span class="field-value text-muted">${createdAt}</span>
          </div>
        </div>

        <div class="run-featured-footer">
          <span class="run-duration-tag">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            Duration: ${duration}
          </span>
          <div class="run-actions-group">
            <button type="button" class="btn btn-secondary btn-sm" id="btn-view-run-controls">
              Orchestrate Scenarios &rarr;
            </button>
          </div>
        </div>
      </div>
    `;

    // Bind copy button on the latest run
    const copyBtn = container.querySelector("#btn-copy-latest-run");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const ok = await Utils.copyToClipboard(runId);
        const feedbackText = copyBtn.querySelector(".copy-feedback-text");
        if (ok) {
          copyBtn.classList.add("copied");
          if (feedbackText) feedbackText.textContent = "Copied!";
          Utils.showToast(`Copied Demo ID: ${runId}`, "success", 2500);
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            if (feedbackText) feedbackText.textContent = "Copy ID";
          }, 2000);
        } else {
          Utils.showToast("Failed to copy to clipboard", "error", 3000);
        }
      });
    }

    const viewControlsBtn = container.querySelector("#btn-view-run-controls");
    if (viewControlsBtn) {
      viewControlsBtn.addEventListener("click", () => navigation.navigate("demo-control"));
    }
  }

  renderRecentActivity(runs) {
    const tableBody = document.getElementById("recent-runs-table-body");
    if (!tableBody) return;

    if (!runs || runs.length === 0) {
      tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-muted py-4">No recent pipeline execution records.</td></tr>`;
      return;
    }

    tableBody.innerHTML = runs.slice(0, 8).map((r) => {
      const runId = r.run_id || "—";
      const status = r.actual_outcome === "success" ? "SUCCESS" : (r.actual_outcome === "failure" ? "FAILED" : (r.status || "RUNNING").toUpperCase());
      const scenario = r.scenario_preset || r.scenario_id || "Standard";
      const timeAgo = Utils.formatRelativeTime(r.created_at);
      const commit = r.commit_sha ? r.commit_sha.slice(0, 7) : (r.commit_info?.sha ? r.commit_info.sha.slice(0, 7) : "—");
      
      const pred = r.current_runtime_prediction || {};
      const risk = pred.failure_probability_pct !== undefined ? `${pred.failure_probability_pct}%` : (pred.failure_probability !== undefined ? `${Math.round(pred.failure_probability * 100)}%` : "—");

      return `
        <tr>
          <td>
            <div class="table-id-cell">
              <span class="font-mono text-sm">${Utils.escapeHtml(runId)}</span>
              <button type="button" class="btn-copy-inline" data-copy-id="${Utils.escapeHtml(runId)}" title="Copy Demo ID" aria-label="Copy Demo ID">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>
              </button>
            </div>
          </td>
          <td>${Utils.renderBadge(status)}</td>
          <td><span class="badge-scenario">${Utils.escapeHtml(scenario)}</span></td>
          <td><span class="font-mono text-xs">${Utils.escapeHtml(commit)}</span></td>
          <td class="font-bold">${risk}</td>
          <td class="text-muted text-sm">${timeAgo}</td>
        </tr>
      `;
    }).join("");

    // Bind inline copy buttons in table
    tableBody.querySelectorAll(".btn-copy-inline").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const idToCopy = btn.getAttribute("data-copy-id");
        if (idToCopy) {
          const ok = await Utils.copyToClipboard(idToCopy);
          if (ok) {
            btn.classList.add("copied");
            Utils.showToast(`Copied ${idToCopy}`, "success", 2000);
            setTimeout(() => btn.classList.remove("copied"), 1500);
          } else {
            Utils.showToast("Failed to copy ID", "error", 2500);
          }
        }
      });
    });
  }
}

export const overviewController = new OverviewController();

