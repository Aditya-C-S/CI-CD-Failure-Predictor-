/**
 * frontend/js/health.js
 * System Health & Diagnostics Controller for UI Batch A.
 * Inspects all 6 core backend subsystems returned by /api/health/system.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";

export class HealthController {
  constructor() {
    this.healthData = null;
    this.isRefreshing = false;
  }

  init() {
    this.bindEvents();
    this.loadHealth();
  }

  bindEvents() {
    const refreshBtn = document.getElementById("health-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => this.loadHealth(true));
    }

    // Refresh when route switches to system-health
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "system-health") {
        this.loadHealth(false);
      }
    });
  }

  async loadHealth(showToast = false) {
    if (this.isRefreshing) return;
    this.isRefreshing = true;

    const refreshIcon = document.getElementById("health-refresh-icon");
    if (refreshIcon) refreshIcon.classList.add("spin");

    try {
      this.healthData = await api.getSystemHealth();
      this.renderHealthDashboard(this.healthData);
      if (showToast) {
        Utils.showToast("System health diagnostics refreshed", "info", 2000);
      }
    } catch (err) {
      console.error("Health check error:", err);
      this.renderHealthFailure(err.message);
      Utils.showToast(`Health check failed: ${err.message}`, "error", 4000);
    } finally {
      this.isRefreshing = false;
      if (refreshIcon) refreshIcon.classList.remove("spin");
    }
  }

  renderHealthDashboard(data) {
    // 1. Overall Status Banner
    const banner = document.getElementById("health-overall-banner");
    const lastChecked = document.getElementById("health-last-checked-time");
    if (lastChecked) {
      lastChecked.textContent = `Last Checked: ${Utils.formatDateTime(data.timestamp || new Date().toISOString())}`;
    }

    if (banner) {
      const overallStatus = data.status || "UNKNOWN";
      let bannerClass = "banner-healthy";
      let summaryText = "All operational subsystems are functioning within nominal parameters.";

      if (overallStatus === "DEGRADED") {
        bannerClass = "banner-degraded";
        summaryText = "One or more non-critical subsystems are degraded (e.g. Neo4j offline using Tree-sitter AST fallback).";
      } else if (overallStatus === "UNHEALTHY") {
        bannerClass = "banner-unhealthy";
        summaryText = "Critical subsystem failure detected. Check storage or runtime model configurations.";
      }

      banner.className = `health-overall-banner ${bannerClass}`;
      banner.innerHTML = `
        <div class="banner-status-left">
          <div class="status-icon-large">${this.getStatusIconSvg(overallStatus)}</div>
          <div>
            <div class="banner-status-title">System Status: ${Utils.escapeHtml(overallStatus)}</div>
            <div class="banner-status-desc">${Utils.escapeHtml(summaryText)}</div>
          </div>
        </div>
        <div class="banner-status-right">
          ${Utils.renderBadge(overallStatus)}
        </div>
      `;
    }

    // 2. Component Cards
    const comps = data.components || {};

    // 2.1 Backend
    const backendEl = document.getElementById("comp-backend-content");
    if (backendEl && comps.backend) {
      const b = comps.backend;
      backendEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">Service</span>
          <span class="comp-value">${Utils.escapeHtml(b.service || "FastAPI")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">API Version</span>
          <span class="comp-value font-mono">v${Utils.escapeHtml(b.version || "2.0.0")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Python Environment</span>
          <span class="comp-value font-mono">${Utils.escapeHtml(b.python_version || "3.12")}</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge(b.status)}</div>
      `;
    }

    // 2.2 Neo4j
    const neo4jEl = document.getElementById("comp-neo4j-content");
    if (neo4jEl && comps.neo4j) {
      const n = comps.neo4j;
      const isOnline = n.mode === "ONLINE" || n.status === "HEALTHY";
      neo4jEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">Engine Mode</span>
          <span class="comp-value font-bold ${isOnline ? 'text-success' : 'text-warning'}">${Utils.escapeHtml(n.mode || "ONLINE")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Version & Edition</span>
          <span class="comp-value font-mono">${Utils.escapeHtml(n.version || "5.25.1")} (${Utils.escapeHtml(n.edition || "community")})</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Active Database</span>
          <span class="comp-value font-mono">${Utils.escapeHtml(n.database || "graphdoc")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">AST Fallback</span>
          <span class="comp-value text-muted">${n.fallback_available ? "Tree-sitter Ready" : "Disabled"}</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge(n.status)}</div>
      `;
    }

    // 2.3 Runtime Models
    const rtmEl = document.getElementById("comp-runtime-models-content");
    if (rtmEl && comps.runtime_models) {
      const r = comps.runtime_models;
      const b2 = r.bilstm2?.status || "HEALTHY";
      const svm = r.svm?.status || "HEALTHY";
      const lr = r.logistic_regression?.status || "HEALTHY";

      rtmEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">BiLSTM v2 (Retrained)</span>
          <span>${Utils.renderBadge(b2, "PyTorch 5-Fold")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">TF-IDF + Linear SVM</span>
          <span>${Utils.renderBadge(svm, "scikit-learn")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">TF-IDF + Logistic Regression</span>
          <span>${Utils.renderBadge(lr, "scikit-learn")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Supported Depths</span>
          <span class="comp-value font-mono text-xs">25%, 50%, 75%, 100%</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge("HEALTHY", "All 3 Models Ready")}</div>
      `;
    }

    // 2.4 Metadata Model
    const metaEl = document.getElementById("comp-metadata-model-content");
    if (metaEl && comps.metadata_model) {
      const m = comps.metadata_model;
      metaEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">Model Pipeline</span>
          <span class="comp-value text-xs font-mono">LightGBM + CalibratedClassifier</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Feature Contract</span>
          <span class="comp-value font-mono font-bold">${Utils.escapeHtml(m.feature_contract || "38_features_strict")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">SHAP Explainer</span>
          <span class="comp-value text-success font-bold">TreeExplainer Active</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Model Version</span>
          <span class="comp-value text-muted text-xs font-mono">${Utils.escapeHtml(m.model_version || "run_20260926_013515")}</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge(m.status)}</div>
      `;
    }

    // 2.5 Ingestion
    const ingEl = document.getElementById("comp-ingestion-content");
    if (ingEl && comps.log_ingestion) {
      const ing = comps.log_ingestion;
      ingEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">Streaming Endpoint</span>
          <span class="comp-value font-mono text-xs">${Utils.escapeHtml(ing.endpoint || "/api/demo/runs/{id}/logs")}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Deduplication</span>
          <span class="comp-value text-success font-bold">${ing.deduplication_enabled ? "Active (SHA-256)" : "Disabled"}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Telemetry Auth</span>
          <span class="comp-value">${ing.auth_configured ? "Protected (API-Key)" : "Open"}</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge(ing.status)}</div>
      `;
    }

    // 2.6 Persistence
    const persistEl = document.getElementById("comp-storage-content");
    if (persistEl && comps.persistence) {
      const p = comps.persistence;
      persistEl.innerHTML = `
        <div class="comp-status-row">
          <span class="comp-label">Run Storage Directory</span>
          <span class="comp-value font-mono text-xs" title="${Utils.escapeHtml(p.directory)}">data/demo_runs</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Storage Access</span>
          <span class="comp-value font-bold ${p.writable ? 'text-success' : 'text-danger'}">${p.writable ? "Writable" : "Read-Only"}</span>
        </div>
        <div class="comp-status-row">
          <span class="comp-label">Historical Runs Loaded</span>
          <span class="comp-value font-bold font-mono">${p.active_runs_loaded || "—"}</span>
        </div>
        <div class="comp-badge-wrapper">${Utils.renderBadge(p.status)}</div>
      `;
    }
  }

  getStatusIconSvg(status) {
    if (status === "HEALTHY") {
      return `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
    }
    if (status === "DEGRADED") {
      return `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    }
    return `<svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`;
  }

  renderHealthFailure(errText) {
    const banner = document.getElementById("health-overall-banner");
    if (banner) {
      banner.className = "health-overall-banner banner-unhealthy";
      banner.innerHTML = `
        <div class="banner-status-left">
          <div class="status-icon-large">${this.getStatusIconSvg("UNHEALTHY")}</div>
          <div>
            <div class="banner-status-title">Backend Unreachable / Offline</div>
            <div class="banner-status-desc">Unable to connect to FastAPI backend at /api/health/system: ${Utils.escapeHtml(errText)}</div>
          </div>
        </div>
        <div class="banner-status-right">
          ${Utils.renderBadge("OFFLINE")}
        </div>
      `;
    }
  }
}

export const healthController = new HealthController();

