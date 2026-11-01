/**
 * frontend/js/rca.js
 * Assisted Root Cause Analysis & Remediation Engine (Module III).
 * Synthesizes Parser V2 error patterns, chronological evidence timeline,
 * candidate root causes, and copyable prescriptive remediation commands.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";

export class RcaController {
  constructor() {
    this.currentRunId = null;
    this.rcaData = null;
    this.recentRuns = [];
  }

  init() {
    this.bindEvents();
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "rca") {
        this.loadRcaView();
      }
    });
  }

  bindEvents() {
    const runSelect = document.getElementById("rca-run-select");
    if (runSelect) {
      runSelect.addEventListener("change", (e) => {
        const runId = e.target.value;
        if (runId) {
          this.currentRunId = runId;
          this.loadRunRca(runId);
        }
      });
    }

    const btnRefresh = document.getElementById("rca-btn-refresh");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => {
        if (this.currentRunId) {
          this.loadRunRca(this.currentRunId);
        } else {
          this.loadRcaView();
        }
      });
    }

    // Trigger on-demand RCA analysis button
    const btnReanalyze = document.getElementById("rca-btn-reanalyze");
    if (btnReanalyze) {
      btnReanalyze.addEventListener("click", () => {
        if (this.currentRunId) {
          this.triggerOnDemandRca(this.currentRunId);
        }
      });
    }
  }

  async loadRcaView() {
    try {
      this.recentRuns = await api.getRecentRuns(15);
      this.populateRunDropdown();

      const activeStored = localStorage.getItem("cicd_active_demo_run_id");
      const targetRun = (activeStored && this.recentRuns.some(r => r.run_id === activeStored))
        ? activeStored
        : (this.recentRuns.length > 0 ? this.recentRuns[0].run_id : null);

      if (targetRun) {
        this.currentRunId = targetRun;
        const sel = document.getElementById("rca-run-select");
        if (sel) sel.value = targetRun;
        await this.loadRunRca(targetRun);
      } else {
        this.renderCleanRunState("No recent pipeline executions found.");
      }
    } catch (err) {
      console.error("Failed to load RCA view:", err);
      Utils.showToast("Failed to load RCA view: " + err.message, "error");
    }
  }

  populateRunDropdown() {
    const sel = document.getElementById("rca-run-select");
    if (!sel) return;

    const opts = ['<option value="">-- Select Run (Demo ID) --</option>'];
    this.recentRuns.forEach(r => {
      const outcome = (r.actual_outcome || r.status || "run").toUpperCase();
      opts.push(`<option value="${r.run_id}">${r.run_id.substring(0, 26)}... [${outcome}]</option>`);
    });
    sel.innerHTML = opts.join("");
  }

  async loadRunRca(runId) {
    const spinner = document.getElementById("rca-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const data = await api.getRunRca(runId);
      this.rcaData = data;

      if (!data || data.primary_category === "NONE" || data.primary_category === "CLEAN_RUN" || data.status === "NOMINAL") {
        this.renderCleanRunState(`Run ${runId.substring(0, 16)}... passed without failure signatures.`);
      } else {
        this.renderRcaContent(data, runId);
      }
      Utils.showToast("RCA diagnostic loaded", "info", 1500);
    } catch (err) {
      console.warn("Could not load RCA for run:", err);
      // Try triggering RCA
      try {
        const trigData = await api.triggerRunRca(runId);
        this.rcaData = trigData;
        this.renderRcaContent(trigData, runId);
      } catch (trigErr) {
        this.renderCleanRunState("No root cause failures detected for this run.");
      }
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  async triggerOnDemandRca(runId) {
    const spinner = document.getElementById("rca-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const data = await api.triggerRunRca(runId);
      this.rcaData = data;
      this.renderRcaContent(data, runId);
      Utils.showToast("On-demand Parser V2 RCA re-synthesis complete", "success", 2500);
    } catch (err) {
      Utils.showToast("RCA re-analysis failed: " + err.message, "error", 3500);
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  renderRcaContent(data, runId) {
    const emptyState = document.getElementById("rca-clean-run-card");
    const contentArea = document.getElementById("rca-content-area");
    if (emptyState) emptyState.style.display = "none";
    if (contentArea) contentArea.style.display = "block";

    // 5.1 Overview
    this.renderOverview(data, runId);

    // 5.2 Evidence Timeline
    this.renderEvidenceTimeline(data.evidence_items || []);

    // 5.3 Candidate Root Causes
    this.renderRootCauses(data.root_causes || []);

    // 5.4 Remediation Suggestions
    this.renderRemediation(data.remediation || {});
  }

  renderOverview(data, runId) {
    const catBadge = document.getElementById("rca-category-badge");
    const summaryEl = document.getElementById("rca-summary-text");
    const confEl = document.getElementById("rca-confidence-val");
    const confBar = document.getElementById("rca-confidence-bar");
    const rationaleEl = document.getElementById("rca-confidence-rationale");
    const stageEl = document.getElementById("rca-stage-val");
    const evCountEl = document.getElementById("rca-evidence-count-val");
    const runIdEl = document.getElementById("rca-run-id-display");

    const category = data.primary_category || data.causal_category || "UNKNOWN_FAILURE";
    let catBadgeClass = "badge-unhealthy";
    if (category.includes("SYNTAX")) catBadgeClass = "badge-degraded";
    else if (category.includes("DEPENDENCY")) catBadgeClass = "badge-info";

    if (catBadge) {
      catBadge.className = `status-pill ${catBadgeClass} font-bold`;
      catBadge.textContent = category.replace(/_/g, " ");
    }

    if (summaryEl) {
      summaryEl.textContent = data.detected_error || data.summary || data.likely_cause || "Pipeline execution encountered fatal failure exception.";
    }

    const confPct = Math.round((data.rca_confidence ?? data.confidence ?? 0.85) * 100);
    if (confEl) confEl.textContent = confPct + "%";
    if (confBar) {
      confBar.style.width = confPct + "%";
      confBar.style.backgroundColor = confPct >= 75 ? "var(--accent-primary)" : "var(--status-degraded)";
    }

    if (rationaleEl) {
      rationaleEl.textContent = data.confidence_rationale || "Definitive error signature matched by Parser V2 with AST stack trace context.";
    }

    if (stageEl) stageEl.textContent = (data.relevant_pipeline_stage || "build").toUpperCase();
    if (evCountEl) evCountEl.textContent = (data.evidence_items?.length || 0) + " signals";
    if (runIdEl) runIdEl.textContent = runId;
  }

  renderEvidenceTimeline(items) {
    const container = document.getElementById("rca-evidence-timeline-container");
    if (!container) return;

    if (items.length === 0) {
      container.innerHTML = `<div class="text-xs text-muted" style="padding: 1rem 0;">No chronological log evidence items parsed.</div>`;
      return;
    }

    const fatalItems = items.filter((it, idx) => idx === 0 || it.source_type === "parser_v2" || String(it.error_text || '').includes("Error") || String(it.relationship || '').includes("FATAL"));
    const supportItems = items.filter(it => !fatalItems.includes(it));

    let html = `<div class="rca-evidence-split-view">`;

    if (fatalItems.length > 0) {
      html += `
        <div class="evidence-section-header" style="margin-bottom: 0.75rem;">
          <span class="status-pill badge-unhealthy text-xs font-bold">CONFIRMED FAILURE SIGNALS (${fatalItems.length})</span>
          <span class="text-xs text-muted" style="margin-left: 8px;">Direct error patterns matched by Parser V2</span>
        </div>
        <div class="rca-timeline" style="margin-bottom: 1.25rem;">
      `;
      fatalItems.forEach(item => {
        const lineNum = item.line_number || item.line_start || "N/A";
        const step = item.step_name || item.stage_name || "build";
        const rel = item.relationship || "Fatal error traceback matched in build log";

        html += `
          <div class="timeline-item item-primary">
            <div class="timeline-marker" style="background-color: var(--status-unhealthy, #ef4444); border-color: #fca5a5;"></div>
            <div class="timeline-content card-subtle" style="border-left: 3px solid var(--status-unhealthy, #ef4444);">
              <div class="timeline-header">
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                  <span class="status-pill badge-unhealthy font-mono text-xs">
                    Line ${lineNum}
                  </span>
                  <span class="font-semibold text-xs text-accent">${Utils.escapeHtml(step)}</span>
                </div>
                <span class="status-pill badge-neutral text-xs font-mono">${Utils.escapeHtml(item.source_type || 'parser_v2')}</span>
              </div>
              <div class="timeline-code-snippet font-mono text-xs" style="margin-top: 0.5rem; background: rgba(239, 68, 68, 0.08); padding: 0.5rem; border-radius: 4px; border: 1px solid rgba(239, 68, 68, 0.2);">
                <code style="color: #f87171;">${Utils.escapeHtml(item.error_text || item.text || item.snippet || '')}</code>
              </div>
              <div class="timeline-relation text-xs text-muted" style="margin-top: 0.35rem;">
                ${Utils.escapeHtml(rel)}
              </div>
            </div>
          </div>
        `;
      });
      html += `</div>`;
    }

    if (supportItems.length > 0) {
      html += `
        <div class="evidence-section-header" style="margin-bottom: 0.75rem;">
          <span class="status-pill badge-neutral text-xs font-bold">SUPPORTING LOG CONTEXT (${supportItems.length})</span>
          <span class="text-xs text-muted" style="margin-left: 8px;">Preceding steps and environment setup</span>
        </div>
        <div class="rca-timeline">
      `;
      supportItems.forEach(item => {
        const lineNum = item.line_number || item.line_start || "N/A";
        const step = item.step_name || item.stage_name || "ci";

        html += `
          <div class="timeline-item">
            <div class="timeline-marker"></div>
            <div class="timeline-content card-subtle">
              <div class="timeline-header">
                <div style="display: flex; gap: 0.5rem; align-items: center;">
                  <span class="status-pill badge-neutral font-mono text-xs">
                    Line ${lineNum}
                  </span>
                  <span class="font-semibold text-xs text-muted">${Utils.escapeHtml(step)}</span>
                </div>
                <span class="text-xs text-muted font-mono">${Utils.escapeHtml(item.source_type || 'runtime_log')}</span>
              </div>
              <div class="timeline-code-snippet font-mono text-xs" style="margin-top: 0.5rem;">
                <code>${Utils.escapeHtml(item.error_text || item.text || item.snippet || '')}</code>
              </div>
            </div>
          </div>
        `;
      });
      html += `</div>`;
    }

    html += `</div>`;
    container.innerHTML = html;
  }

  renderRootCauses(causes) {
    const container = document.getElementById("rca-candidates-container");
    if (!container) return;

    if (causes.length === 0) {
      container.innerHTML = `<div class="text-xs text-muted" style="padding: 1rem 0;">No distinct candidate root causes synthesized.</div>`;
      return;
    }

    const primary = causes[0];
    const secondary = causes.slice(1);
    const primConf = Math.round((primary.confidence || 0.85) * 100);

    let html = `
      <div class="primary-rca-hero card-subtle" style="margin-bottom: 1.25rem; padding: 1.25rem; border-left: 4px solid var(--accent-primary, #6366f1); border-radius: 8px; background: rgba(99, 102, 241, 0.04);">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span class="status-pill badge-accent font-bold">PRIMARY DETERMINED ROOT CAUSE</span>
            <span class="text-xs text-muted font-mono">Rank #1</span>
          </div>
          <span class="font-mono font-bold text-sm text-accent">${primConf}% Model Confidence</span>
        </div>
        <h3 class="font-bold text-base" style="margin: 0.75rem 0 0.5rem 0; color: var(--text-primary);">${Utils.escapeHtml(primary.what_failed || primary.category || 'Pipeline Failure')}</h3>
        <div class="rca-hero-fields" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-top: 0.75rem;">
          <div class="hero-field-box">
            <span class="text-xs font-semibold text-muted uppercase tracking-wider">Where it occurred:</span>
            <div class="font-mono text-xs text-accent" style="margin-top: 4px; word-break: break-all;">${Utils.escapeHtml(primary.where_failed || 'Pipeline Execution Stage')}</div>
          </div>
          <div class="hero-field-box">
            <span class="text-xs font-semibold text-muted uppercase tracking-wider">Underlying Causal Mechanism:</span>
            <div class="text-xs text-secondary" style="margin-top: 4px; line-height: 1.5;">${Utils.escapeHtml(primary.why_failed || primary.description || 'Fatal exception during execution')}</div>
          </div>
        </div>
      </div>
    `;

    if (secondary.length > 0) {
      html += `
        <div style="margin-bottom: 0.5rem;">
          <span class="text-xs font-bold text-muted uppercase tracking-wider">Alternative Hypotheses &amp; Contributing Factors:</span>
        </div>
        <div class="dashboard-grid-2">
      `;
      secondary.forEach(c => {
        const conf = Math.round((c.confidence || 0.60) * 100);
        html += `
          <div class="card-subtle" style="padding: 1rem; border-radius: 8px;">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span class="status-pill badge-neutral text-xs font-semibold">CONTRIBUTING FACTOR</span>
              <span class="font-mono text-xs text-muted">${conf}% Confidence</span>
            </div>
            <h4 class="font-bold text-sm" style="margin: 0.5rem 0 0.25rem 0;">${Utils.escapeHtml(c.what_failed || c.category || 'Secondary Signal')}</h4>
            <div class="text-xs text-muted"><strong>Where:</strong> <span class="font-mono">${Utils.escapeHtml(c.where_failed || 'Pipeline Context')}</span></div>
            <div class="text-xs text-secondary" style="margin-top: 0.35rem; line-height: 1.5;">
              <strong>Why:</strong> ${Utils.escapeHtml(c.why_failed || c.description || '')}
            </div>
          </div>
        `;
      });
      html += `</div>`;
    }

    container.innerHTML = html;
  }

  renderRemediation(rem) {
    const container = document.getElementById("rca-remediation-container");
    if (!container) return;

    const fixes = rem.confirmed_fixes || [];
    const troubleshooting = rem.troubleshooting || [];
    const primary = rem.primary_action || "Investigate the failure log excerpt and correct the exception.";

    let html = `
      <div class="remediation-primary-box" style="margin-bottom: 1rem;">
        <span class="text-xs text-muted font-semibold uppercase">Recommended Primary Action:</span>
        <p class="font-semibold text-sm" style="margin-top: 4px; color: var(--text-primary);">${Utils.escapeHtml(primary)}</p>
      </div>

      <div class="dashboard-grid-2">
        <!-- Confirmed Fixes -->
        <div>
          <h4 class="font-semibold text-sm" style="margin-bottom: 0.5rem; color: var(--status-healthy);">
            Confirmed Fixes &amp; Patches
          </h4>
    `;

    if (fixes.length === 0) {
      html += `<div class="text-xs text-muted">No automatic code patches available. Follow troubleshooting steps below.</div>`;
    } else {
      fixes.forEach((f, i) => {
        html += `
          <div class="remediation-card card-subtle" style="margin-bottom: 0.75rem; padding: 0.75rem;">
            <div class="text-xs font-semibold">${Utils.escapeHtml(f.action || 'Remediation Step')}</div>
            ${f.command ? `
              <div class="command-box" style="margin-top: 0.5rem;">
                <code class="font-mono text-xs">${Utils.escapeHtml(f.command)}</code>
                <button type="button" class="btn-copy-code" data-copy-cmd="${Utils.escapeHtml(f.command)}" title="Copy Command">
                  Copy
                </button>
              </div>
            ` : ''}
          </div>
        `;
      });
    }

    html += `
        </div>
        <!-- Troubleshooting -->
        <div>
          <h4 class="font-semibold text-sm" style="margin-bottom: 0.5rem; color: var(--status-info);">
            Diagnostic &amp; Troubleshooting Commands
          </h4>
    `;

    if (troubleshooting.length === 0) {
      html += `<div class="text-xs text-muted">No additional troubleshooting commands required.</div>`;
    } else {
      troubleshooting.forEach((t, i) => {
        html += `
          <div class="remediation-card card-subtle" style="margin-bottom: 0.75rem; padding: 0.75rem;">
            <div class="text-xs font-semibold">${Utils.escapeHtml(t.action || 'Diagnostic Step')}</div>
            ${t.command ? `
              <div class="command-box" style="margin-top: 0.5rem;">
                <code class="font-mono text-xs">${Utils.escapeHtml(t.command)}</code>
                <button type="button" class="btn-copy-code" data-copy-cmd="${Utils.escapeHtml(t.command)}" title="Copy Command">
                  Copy
                </button>
              </div>
            ` : ''}
          </div>
        `;
      });
    }

    html += `
        </div>
      </div>
    `;

    container.innerHTML = html;

    // Bind copy command buttons
    container.querySelectorAll("[data-copy-cmd]").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        const cmd = e.currentTarget.getAttribute("data-copy-cmd");
        if (cmd) {
          const ok = await Utils.copyToClipboard(cmd);
          if (ok) {
            e.currentTarget.textContent = "Copied!";
            setTimeout(() => { e.currentTarget.textContent = "Copy"; }, 2000);
            Utils.showToast("Command copied to clipboard", "success", 2000);
          }
        }
      });
    });
  }

  renderCleanRunState(msg) {
    const emptyState = document.getElementById("rca-clean-run-card");
    const contentArea = document.getElementById("rca-content-area");
    if (emptyState) {
      emptyState.style.display = "block";
      const desc = document.getElementById("rca-clean-run-desc");
      if (desc) desc.textContent = msg;
    }
    if (contentArea) contentArea.style.display = "none";
  }
}

export const rcaController = new RcaController();

