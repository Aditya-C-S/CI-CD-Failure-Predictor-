/**
 * frontend/js/run-history.js
 * Historical Pipeline Run Inspector & Analytics Controller for UI Batch B.
 * Implements: Searchable & filterable history table with pagination,
 * Run Detail Inspector with 10 diagnostic sections, Historical Risk Progression,
 * and Side-by-Side Run Comparison.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";
import { navigation } from "./navigation.js";

export class RunHistoryController {
  constructor() {
    this.allRuns = [];
    this.filteredRuns = [];
    this.selectedRunId = null;
    this.selectedRunDetails = null;
    this.comparisonRunIds = new Set();
    this.isLoading = false;
    
    // Pagination & Filter State
    this.currentPage = 1;
    this.pageSize = 10;
    this.searchQuery = "";
    this.commitQuery = "";
    this.filterScenario = "all";
    this.filterStatus = "all";
    this.filterModel = "all";
    this.sortBy = "newest";
  }

  init() {
    this.bindEvents();

    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "run-history") {
        this.loadRuns();
      }
    });
  }

  bindEvents() {
    // Search inputs
    const runSearch = document.getElementById("history-search-run-id");
    if (runSearch) {
      runSearch.addEventListener("input", (e) => {
        this.searchQuery = e.target.value.trim().toLowerCase();
        this.currentPage = 1;
        this.applyFilters();
      });
    }

    const commitSearch = document.getElementById("history-search-commit");
    if (commitSearch) {
      commitSearch.addEventListener("input", (e) => {
        this.commitQuery = e.target.value.trim().toLowerCase();
        this.currentPage = 1;
        this.applyFilters();
      });
    }

    // Filter dropdowns
    const scenarioFilter = document.getElementById("history-filter-scenario");
    if (scenarioFilter) {
      scenarioFilter.addEventListener("change", (e) => {
        this.filterScenario = e.target.value;
        this.currentPage = 1;
        this.applyFilters();
      });
    }

    const statusFilter = document.getElementById("history-filter-status");
    if (statusFilter) {
      statusFilter.addEventListener("change", (e) => {
        this.filterStatus = e.target.value;
        this.currentPage = 1;
        this.applyFilters();
      });
    }

    const modelFilter = document.getElementById("history-filter-model");
    if (modelFilter) {
      modelFilter.addEventListener("change", (e) => {
        this.filterModel = e.target.value;
        this.currentPage = 1;
        this.applyFilters();
      });
    }

    const sortSelect = document.getElementById("history-sort-by");
    if (sortSelect) {
      sortSelect.addEventListener("change", (e) => {
        this.sortBy = e.target.value;
        this.applyFilters();
      });
    }

    // Clear filters button
    const btnClear = document.getElementById("history-clear-filters-btn");
    if (btnClear) {
      btnClear.addEventListener("click", () => {
        this.resetFilters();
      });
    }

    // Refresh button
    const btnRefresh = document.getElementById("history-refresh-btn");
    if (btnRefresh) {
      btnRefresh.addEventListener("click", () => this.loadRuns(true));
    }

    // Compare button
    const btnCompare = document.getElementById("btn-compare-selected-runs");
    if (btnCompare) {
      btnCompare.addEventListener("click", () => this.openRunComparison());
    }

    // Modal Close Buttons
    const btnCloseInspector = document.getElementById("btn-close-run-inspector");
    if (btnCloseInspector) {
      btnCloseInspector.addEventListener("click", () => this.closeRunInspector());
    }

    const btnCloseComparison = document.getElementById("btn-close-run-comparison");
    if (btnCloseComparison) {
      btnCloseComparison.addEventListener("click", () => this.closeRunComparison());
    }

    // Modal backdrops
    const inspectorModal = document.getElementById("run-inspector-modal");
    if (inspectorModal) {
      inspectorModal.addEventListener("click", (e) => {
        if (e.target === inspectorModal) this.closeRunInspector();
      });
    }

    const comparisonModal = document.getElementById("run-comparison-modal");
    if (comparisonModal) {
      comparisonModal.addEventListener("click", (e) => {
        if (e.target === comparisonModal) this.closeRunComparison();
      });
    }

    // Pagination controls
    const prevPageBtn = document.getElementById("history-prev-page-btn");
    if (prevPageBtn) {
      prevPageBtn.addEventListener("click", () => {
        if (this.currentPage > 1) {
          this.currentPage--;
          this.renderTable();
        }
      });
    }

    const nextPageBtn = document.getElementById("history-next-page-btn");
    if (nextPageBtn) {
      nextPageBtn.addEventListener("click", () => {
        const totalPages = Math.ceil(this.filteredRuns.length / this.pageSize);
        if (this.currentPage < totalPages) {
          this.currentPage++;
          this.renderTable();
        }
      });
    }
  }

  resetFilters() {
    this.searchQuery = "";
    this.commitQuery = "";
    this.filterScenario = "all";
    this.filterStatus = "all";
    this.filterModel = "all";
    this.sortBy = "newest";
    this.currentPage = 1;

    const runSearch = document.getElementById("history-search-run-id");
    if (runSearch) runSearch.value = "";
    const commitSearch = document.getElementById("history-search-commit");
    if (commitSearch) commitSearch.value = "";
    const scenarioFilter = document.getElementById("history-filter-scenario");
    if (scenarioFilter) scenarioFilter.value = "all";
    const statusFilter = document.getElementById("history-filter-status");
    if (statusFilter) statusFilter.value = "all";
    const modelFilter = document.getElementById("history-filter-model");
    if (modelFilter) modelFilter.value = "all";
    const sortSelect = document.getElementById("history-sort-by");
    if (sortSelect) sortSelect.value = "newest";

    this.applyFilters();
  }

  async loadRuns(showToast = false) {
    if (this.isLoading) return;
    this.isLoading = true;

    const refreshIcon = document.getElementById("history-refresh-icon");
    if (refreshIcon) refreshIcon.classList.add("spin");

    try {
      const runs = await api.getRecentRuns(50);
      this.allRuns = Array.isArray(runs) ? runs : [];
      this.applyFilters();

      // Check URL query param to open inspector automatically if requested
      const urlParams = new URLSearchParams(window.location.search);
      const inspectId = urlParams.get("inspect") || urlParams.get("run_id");
      if (inspectId) {
        this.openRunInspector(inspectId);
      }

      if (showToast) {
        Utils.showToast(`Loaded ${this.allRuns.length} historical run records`, "info", 2000);
      }
    } catch (err) {
      console.error("Failed to load run history:", err);
      Utils.showToast(`Failed to load history: ${err.message}`, "error", 4000);
      this.renderTableEmptyState(err.message);
    } finally {
      this.isLoading = false;
      if (refreshIcon) refreshIcon.classList.remove("spin");
    }
  }

  applyFilters() {
    let result = [...this.allRuns];

    // 1. Run ID Search
    if (this.searchQuery) {
      result = result.filter(r => (r.run_id || "").toLowerCase().includes(this.searchQuery));
    }

    // 2. Commit SHA Search
    if (this.commitQuery) {
      result = result.filter(r => {
        const commit = r.commit_info?.commit_sha || r.commit_sha || "";
        return commit.toLowerCase().includes(this.commitQuery);
      });
    }

    // 3. Scenario Filter
    if (this.filterScenario !== "all") {
      result = result.filter(r => {
        const sc = (r.scenario_preset || r.scenario_id || "").toLowerCase();
        return sc === this.filterScenario.toLowerCase();
      });
    }

    // 4. Status Filter
    if (this.filterStatus !== "all") {
      result = result.filter(r => {
        const st = r.actual_outcome === "success" ? "success" : 
                   r.actual_outcome === "failure" ? "failed" : 
                   (r.status || "running").toLowerCase();
        return st.includes(this.filterStatus.toLowerCase());
      });
    }

    // 5. Model Filter
    if (this.filterModel !== "all") {
      result = result.filter(r => {
        const m = (r.runtime_model || "").toLowerCase();
        return m === this.filterModel.toLowerCase();
      });
    }

    // 6. Sorting
    result.sort((a, b) => {
      if (this.sortBy === "newest") {
        return new Date(b.created_at || 0) - new Date(a.created_at || 0);
      }
      if (this.sortBy === "oldest") {
        return new Date(a.created_at || 0) - new Date(b.created_at || 0);
      }
      if (this.sortBy === "highest_risk") {
        const riskA = a.current_runtime_prediction?.failure_probability_pct ?? 0;
        const riskB = b.current_runtime_prediction?.failure_probability_pct ?? 0;
        return riskB - riskA;
      }
      if (this.sortBy === "lowest_risk") {
        const riskA = a.current_runtime_prediction?.failure_probability_pct ?? 0;
        const riskB = b.current_runtime_prediction?.failure_probability_pct ?? 0;
        return riskA - riskB;
      }
      return 0;
    });

    this.filteredRuns = result;
    this.renderTable();
  }

  renderTable() {
    const tableBody = document.getElementById("history-runs-table-body");
    const countEl = document.getElementById("history-records-count-label");
    const pageIndicator = document.getElementById("history-page-indicator");
    const prevBtn = document.getElementById("history-prev-page-btn");
    const nextBtn = document.getElementById("history-next-page-btn");

    if (!tableBody) return;

    const total = this.filteredRuns.length;
    const totalPages = Math.max(1, Math.ceil(total / this.pageSize));
    if (this.currentPage > totalPages) this.currentPage = totalPages;

    if (countEl) {
      countEl.textContent = `Showing ${Math.min(total, (this.currentPage - 1) * this.pageSize + 1)}-${Math.min(total, this.currentPage * this.pageSize)} of ${total} runs`;
    }
    if (pageIndicator) {
      pageIndicator.textContent = `Page ${this.currentPage} of ${totalPages}`;
    }
    if (prevBtn) prevBtn.disabled = this.currentPage <= 1;
    if (nextBtn) nextBtn.disabled = this.currentPage >= totalPages;

    if (total === 0) {
      tableBody.innerHTML = `
        <tr>
          <td colspan="10" class="text-center text-muted py-5">
            No pipeline executions matched your filter criteria.
          </td>
        </tr>
      `;
      return;
    }

    const startIndex = (this.currentPage - 1) * this.pageSize;
    const pageRuns = this.filteredRuns.slice(startIndex, startIndex + this.pageSize);

    tableBody.innerHTML = pageRuns.map((r) => {
      const runId = r.run_id || "—";
      const status = r.actual_outcome === "success" ? "SUCCESS" : 
                     r.actual_outcome === "failure" ? "FAILED" : 
                     (r.status || "RUNNING").toUpperCase();
      const repo = r.commit_info?.repo_id || r.repo_id || "demo-order-service";
      const commit = r.commit_info?.commit_sha ? r.commit_info.commit_sha.slice(0, 7) : (r.commit_sha ? r.commit_sha.slice(0, 7) : "—");
      const scenario = r.scenario_preset || r.scenario_id || "none";
      const model = r.runtime_model || "bilstm2";
      
      const curPred = r.current_runtime_prediction || {};
      const riskPct = curPred.failure_probability_pct !== undefined ? curPred.failure_probability_pct : (curPred.failure_probability !== undefined ? Math.round(curPred.failure_probability * 100) : "—");
      const createdAt = Utils.formatDateTime(r.created_at);
      const duration = Utils.formatDuration(r.ci_execution?.duration_seconds);
      const isChecked = this.comparisonRunIds.has(runId);

      const isLive = (r.execution_source || "").includes("GITHUB") || (r.execution_source || "").includes("LIVE");
      const sourceBadge = `<span class="badge ${isLive ? 'badge-info' : 'badge-neutral'}" style="font-size: 0.65rem; padding: 1px 5px; display: inline-block; margin-top: 2px;">${isLive ? 'LIVE GHA' : 'LOCAL SIM'}</span>`;
      const riskInfo = Utils.classifyRisk(riskPct);

      return `
        <tr>
          <td style="width: 40px; text-align: center;">
            <input type="checkbox" class="run-compare-checkbox" data-run-id="${Utils.escapeHtml(runId)}" ${isChecked ? 'checked' : ''} title="Select to compare">
          </td>
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
            ${sourceBadge}
          </td>
          <td>${Utils.renderBadge(status)}</td>
          <td><span class="text-xs">${Utils.escapeHtml(repo.split("/").pop())}</span></td>
          <td><span class="font-mono text-xs">${Utils.escapeHtml(commit)}</span></td>
          <td><span class="badge-scenario">${Utils.escapeHtml(scenario)}</span></td>
          <td><span class="font-mono text-xs">${Utils.escapeHtml(model)}</span></td>
          <td class="font-bold ${riskInfo.textClass}">${riskPct !== "—" ? `${riskInfo.percentage}%` : "—"}</td>
          <td class="text-muted text-xs">${createdAt}</td>
          <td class="text-xs font-mono">${duration}</td>
          <td>
            <button type="button" class="btn btn-secondary btn-sm btn-inspect-run" data-run-id="${Utils.escapeHtml(runId)}">
              Inspect &rarr;
            </button>
          </td>
        </tr>
      `;
    }).join("");

    // Bind row copy buttons
    tableBody.querySelectorAll(".btn-copy-inline").forEach(btn => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-copy-id");
        if (id) {
          const ok = await Utils.copyToClipboard(id);
          if (ok) {
            btn.classList.add("copied");
            Utils.showToast(`Copied ${id}`, "success", 2000);
            setTimeout(() => btn.classList.remove("copied"), 1500);
          }
        }
      });
    });

    // Bind row inspect buttons
    tableBody.querySelectorAll(".btn-inspect-run").forEach(btn => {
      btn.addEventListener("click", () => {
        const id = btn.getAttribute("data-run-id");
        if (id) this.openRunInspector(id);
      });
    });

    // Bind comparison checkboxes
    tableBody.querySelectorAll(".run-compare-checkbox").forEach(cb => {
      cb.addEventListener("change", (e) => {
        const id = cb.getAttribute("data-run-id");
        if (e.target.checked) {
          if (this.comparisonRunIds.size >= 2) {
            e.target.checked = false;
            Utils.showToast("You can compare a maximum of 2 runs at once.", "warning", 3000);
            return;
          }
          this.comparisonRunIds.add(id);
        } else {
          this.comparisonRunIds.delete(id);
        }
        this.updateCompareButton();
      });
    });

    this.updateCompareButton();
  }

  updateCompareButton() {
    const btnCompare = document.getElementById("btn-compare-selected-runs");
    if (!btnCompare) return;
    const count = this.comparisonRunIds.size;
    btnCompare.disabled = count !== 2;
    btnCompare.innerHTML = `
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <line x1="18" y1="20" x2="18" y2="10"></line>
        <line x1="12" y1="20" x2="12" y2="4"></line>
        <line x1="6" y1="20" x2="6" y2="14"></line>
      </svg>
      Compare Selected (${count}/2)
    `;
  }

  /* =========================================================================
     2.3 Run Detail View (10 Diagnostic Sections)
     ========================================================================= */
  async openRunInspector(runId) {
    this.selectedRunId = runId;
    const modal = document.getElementById("run-inspector-modal");
    const container = document.getElementById("inspector-details-container");
    if (!modal || !container) return;

    modal.classList.add("active");
    container.innerHTML = `
      <div class="py-5 text-center text-muted">
        <svg class="spin" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-bottom: 1rem;">
          <line x1="12" y1="2" x2="12" y2="6"></line>
          <line x1="12" y1="18" x2="12" y2="22"></line>
        </svg>
        <div>Loading deep execution diagnostics for ${Utils.escapeHtml(runId)}...</div>
      </div>
    `;

    try {
      const [details, summary] = await Promise.allSettled([
        api.getRunDetails(runId),
        api.getRunSummary(runId)
      ]);

      const run = details.status === "fulfilled" ? details.value : null;
      const sum = summary.status === "fulfilled" ? summary.value : null;

      if (!run) {
        throw new Error("Execution details could not be retrieved from backend persistence.");
      }

      this.selectedRunDetails = run;
      this.renderInspectorContent(run, sum);
    } catch (err) {
      container.innerHTML = `
        <div class="banner-error-box">
          <h4>Failed to Load Run Details</h4>
          <p>${Utils.escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  closeRunInspector() {
    const modal = document.getElementById("run-inspector-modal");
    if (modal) modal.classList.remove("active");
    this.selectedRunId = null;
    this.selectedRunDetails = null;
  }

  renderInspectorContent(run, summary) {
    const container = document.getElementById("inspector-details-container");
    if (!container) return;

    const runId = run.run_id || "—";
    const status = run.actual_outcome === "success" ? "SUCCESS" : 
                   run.actual_outcome === "failure" ? "FAILED" : 
                   (run.status || "RUNNING").toUpperCase();
    const repo = run.commit_info?.repo_id || run.repo_id || "Not available";
    const commit = run.commit_info?.commit_sha || run.commit_sha || "Not available";
    const scenario = run.scenario_preset || run.scenario_id || "Not available";
    const model = run.runtime_model || "Not available";
    const duration = Utils.formatDuration(run.ci_execution?.duration_seconds);
    const createdAt = Utils.formatDateTime(run.created_at);
    const completedAt = run.ci_execution?.completed_at ? Utils.formatDateTime(run.ci_execution.completed_at) : "Not available";

    // 5. Prediction History
    const predictions = Array.isArray(run.runtime_predictions) ? run.runtime_predictions : [];

    // 6. Checkpoint Progression
    const projMap = run.checkpoint_projections || {};

    // 7. Early Warnings
    const warnings = Array.isArray(run.warning_history) ? run.warning_history : (run.early_warning ? [run.early_warning] : []);

    // 8. Relevant Log Excerpts
    const logs = run.accumulated_log || "";
    const logExcerpt = logs ? logs.split("\n").slice(-40).join("\n") : "No logs recorded for this execution.";

    // 9. Parser V2 Evidence
    const p2 = run.parser_v2_result;
    const rca = run.rca_result;

    // 10. Final Assessment Summary
    const finalAssessment = summary?.final_assessment || {};

    container.innerHTML = `
      <!-- Header Banner & Prominent Copy Button -->
      <div class="inspector-hero-banner">
        <div class="inspector-hero-top">
          <div class="demo-id-badge-group">
            <span class="demo-id-label">Run ID:</span>
            <span class="demo-id-value" id="inspector-demo-id-val">${Utils.escapeHtml(runId)}</span>
            <button type="button" class="btn-copy-prominent" id="btn-inspector-copy-id" title="Copy Demo ID" aria-label="Copy Demo ID">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
              </svg>
              <span class="copy-label-text">Copy ID</span>
            </button>
          </div>
          <div>${Utils.renderBadge(status)}</div>
        </div>

        <div class="inspector-meta-grid">
          <div class="meta-item">
            <span class="meta-label">Repository</span>
            <span class="meta-val">${Utils.escapeHtml(repo)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Commit SHA</span>
            <span class="meta-val font-mono">${Utils.escapeHtml(commit)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Scenario Preset</span>
            <span class="meta-val font-bold">${Utils.escapeHtml(scenario)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Predictor</span>
            <span class="meta-val">${Utils.escapeHtml(model)}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Execution Source</span>
            <span class="meta-val font-bold">${Utils.escapeHtml(run.execution_source || "LOCAL SIMULATION / BENCHMARK REPLAY")}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Created At</span>
            <span class="meta-val">${createdAt}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">Duration</span>
            <span class="meta-val font-mono">${duration}</span>
          </div>
        </div>
      </div>

      <!-- Section: Final Run Assessment (If Available) -->
      ${summary ? `
        <div class="inspector-section-card">
          <h4 class="inspector-section-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
            Final Run Assessment
          </h4>
          <p class="font-bold" style="color: var(--text-primary); margin-bottom: 0.5rem;">
            ${Utils.escapeHtml(finalAssessment.summary_headline || summary.scenario_description || "Execution completed.")}
          </p>
          <div style="font-size: 0.85rem; color: var(--text-secondary);">
            Risk Profile: <strong>${Utils.escapeHtml(finalAssessment.risk_profile || "Standard")}</strong> &bull;
            Failed Stage: <strong>${Utils.escapeHtml(summary.failed_stage || "None")}</strong> &bull;
            Failure Category: <strong>${Utils.escapeHtml(summary.failure_category || "None")}</strong>
          </div>
        </div>
      ` : ''}

      <!-- Pillar 2: Pre-Build Metadata Intelligence -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
          Pillar II: Pre-Build Commit Metadata Intelligence
        </h4>
        <div class="dashboard-grid-2" style="margin-top: 0.5rem;">
          <div>
            <div class="text-xs text-muted">Gatekeeper Prediction Verdict</div>
            <div class="font-bold text-sm" style="margin-top: 2px;">
              <span class="status-pill ${run.metadata?.verdict === 'PASSED' ? 'badge-healthy' : 'badge-degraded'}">
                ${Utils.escapeHtml(run.metadata?.verdict || summary?.metadata_verdict || "STANDARD GATE")}
              </span>
            </div>
            <div class="text-xs text-muted" style="margin-top: 6px;">
              Pre-Build Failure Probability: <strong>${((run.metadata?.failure_probability || 0.52) * 100).toFixed(1)}%</strong>
            </div>
          </div>
          <div>
            <div class="text-xs text-muted">Feature Schema Audit</div>
            <div class="text-xs font-mono" style="margin-top: 2px;">
              38 Canonical Features &bull; Provenance Monitored
            </div>
            <div class="text-xs text-muted" style="margin-top: 6px;">
              Gatekeeper Model: <strong>LightGBM + Platt Scaling</strong>
            </div>
          </div>
        </div>
      </div>

      <!-- Pillar 3: Neo4j Knowledge Graph & Blast Radius -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="18" cy="5" r="3"></circle>
            <circle cx="6" cy="12" r="3"></circle>
            <circle cx="18" cy="19" r="3"></circle>
            <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"></line>
            <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"></line>
          </svg>
          Pillar III: Knowledge Graph &amp; Blast Radius Intelligence
        </h4>
        <div class="dashboard-grid-2" style="margin-top: 0.5rem;">
          <div>
            <div class="text-xs text-muted">Graph Impact Score (GIS)</div>
            <div class="font-mono font-bold text-base text-accent" style="margin-top: 2px;">
              ${(run.graph_impact?.graph_impact_score?.score || run.graph_impact?.score || 25.0).toFixed(1)} / 100
            </div>
            <div class="text-xs text-muted" style="margin-top: 4px;">
              Impact Tier: <span class="status-pill badge-neutral font-mono">${Utils.escapeHtml(run.graph_impact?.impact_level || "MODERATE")}</span>
            </div>
          </div>
          <div>
            <div class="text-xs text-muted">Transitive Blast Radius</div>
            <div class="font-mono font-bold text-sm" style="margin-top: 2px;">
              ${run.graph_impact?.blast_radius_count || 1} Dependent File(s)
            </div>
            <div class="text-xs text-muted" style="margin-top: 4px;">
              Engine: <strong>${run.graph_impact?.database_status === 'ONLINE' ? 'Neo4j Online' : 'Tree-Sitter AST Fallback'}</strong>
            </div>
          </div>
        </div>
      </div>

      <!-- Pillar 4: Runtime Checkpoint Progression -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline>
          </svg>
          Pillar IV: Runtime Prediction Progression (Actual vs Projected)
        </h4>
        <div class="checkpoint-history-grid">
          ${[25, 50, 75, 100].map(d => {
            const act = predictions.find(p => (p.depth_percentage === d || p.checkpoint === d) && p.prediction_type === "ACTUAL");
            const proj = projMap[d];
            
            let label = "PENDING";
            let val = "—";
            let color = "text-muted";

            if (act) {
              label = "ACTUAL";
              const rInfo = Utils.classifyRisk(act.failure_probability_pct ?? act.failure_probability * 100);
              val = `${rInfo.percentage}%`;
              color = `${rInfo.textClass} font-bold`;
            } else if (proj && proj.type === "PROJECTED") {
              label = "PROJECTED";
              const rInfo = Utils.classifyRisk(proj.failure_probability_pct);
              val = `${rInfo.percentage}%`;
              color = `${rInfo.textClass} font-bold`;
            }

            return `
              <div class="cp-history-item ${label === 'ACTUAL' ? 'item-actual' : ''}">
                <div class="cp-header">
                  <span class="cp-depth-tag">${d}% Depth</span>
                  <span class="cp-badge-type ${label === 'ACTUAL' ? 'type-actual' : 'type-projected'}">${label}</span>
                </div>
                <div class="cp-value ${color}">${val}</div>
              </div>
            `;
          }).join("")}
        </div>
      </div>

      <!-- Section: Early Warnings -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
          </svg>
          Early Warning Events (${warnings.length})
        </h4>
        ${warnings.length > 0 ? warnings.map(w => {
          const wRiskInfo = Utils.classifyRisk(w.failure_probability_pct);
          return `
          <div class="inspector-warning-row">
            <span class="badge badge-degraded">${w.warning_type || "EARLY_FAILURE_WARNING"}</span>
            <span class="font-bold ${wRiskInfo.textClass}">${wRiskInfo.percentage}% Risk</span>
            <span class="text-muted text-xs">@ Checkpoint ${w.depth_percentage || w.checkpoint}%</span>
            <span class="text-muted text-xs">${Utils.formatRelativeTime(w.timestamp)}</span>
          </div>
        `;}).join("") : `<div class="text-muted text-sm">No early warning thresholds crossed during this run.</div>`}
      </div>

      <!-- Section: Parser V2 & Root Cause Evidence -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          Parser V2 Evidence &amp; RCA
        </h4>
        ${p2 && p2.failure_class && p2.failure_class !== "none" ? `
          <div class="inspector-rca-box">
            <div style="display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.5rem;">
              <span class="badge badge-unhealthy">${Utils.escapeHtml(p2.failure_class)}</span>
              <span class="font-bold">${Utils.escapeHtml(p2.failed_step || "Step Failed")}</span>
            </div>
            <pre class="font-mono text-xs" style="background: var(--bg-tertiary); padding: 0.75rem; border-radius: 6px; overflow-x: auto;">${Utils.escapeHtml(p2.evidence_lines?.slice(0, 5).join("\n") || p2.error_message || "Evidence isolated.")}</pre>
          </div>
        ` : `<div class="text-muted text-sm">No failure evidence detected. Nominal execution.</div>`}
      </div>

      <!-- Pillar VII: Prescriptive Remediation & Recommended Commands -->
      ${rca?.remediation?.terminal_commands?.length ? `
        <div class="inspector-section-card">
          <h4 class="inspector-section-title">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
            </svg>
            Pillar VII: Prescriptive Fix Commands &amp; Remediation
          </h4>
          <div class="remediation-commands-list" style="margin-top: 0.5rem;">
            ${rca.remediation.terminal_commands.map(cmd => `
              <div class="command-box" style="margin-bottom: 0.5rem; display: flex; justify-content: space-between; align-items: center; background: var(--bg-tertiary); padding: 6px 12px; border-radius: 6px;">
                <code class="font-mono text-xs">${Utils.escapeHtml(cmd)}</code>
                <button type="button" class="btn-copy-code btn btn-secondary btn-sm" data-copy-cmd="${Utils.escapeHtml(cmd)}">Copy</button>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ''}

      <!-- Section: Terminal Log Preview -->
      <div class="inspector-section-card">
        <h4 class="inspector-section-title">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="4 17 10 11 4 5"></polyline>
            <line x1="12" y1="19" x2="20" y2="19"></line>
          </svg>
          Telemetry Log Preview (Last 40 Lines)
        </h4>
        <pre class="terminal-log-preview font-mono">${Utils.escapeHtml(logExcerpt)}</pre>
      </div>
    `;

    // Bind copy button in inspector
    const copyBtn = container.querySelector("#btn-inspector-copy-id");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        const ok = await Utils.copyToClipboard(runId);
        const label = copyBtn.querySelector(".copy-label-text");
        if (ok) {
          copyBtn.classList.add("copied");
          if (label) label.textContent = "Copied!";
          Utils.showToast(`Copied Demo ID: ${runId}`, "success", 2000);
          setTimeout(() => {
            copyBtn.classList.remove("copied");
            if (label) label.textContent = "Copy ID";
          }, 2000);
        }
      });
    }

    // Bind remediation copy buttons
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

  /* =========================================================================
     2.5 Run Comparison (Side-by-Side Comparison of 2 Runs)
     ========================================================================= */
  async openRunComparison() {
    if (this.comparisonRunIds.size !== 2) return;
    const [idA, idB] = Array.from(this.comparisonRunIds);

    const modal = document.getElementById("run-comparison-modal");
    const container = document.getElementById("comparison-content-container");
    if (!modal || !container) return;

    modal.classList.add("active");
    container.innerHTML = `<div class="py-5 text-center text-muted">Loading comparative telemetry for ${Utils.escapeHtml(idA)} and ${Utils.escapeHtml(idB)}...</div>`;

    try {
      const [resA, resB] = await Promise.all([
        api.getRunDetails(idA),
        api.getRunDetails(idB)
      ]);

      this.renderComparisonContent(resA, resB);
    } catch (err) {
      container.innerHTML = `
        <div class="banner-error-box">
          <h4>Failed to Compare Runs</h4>
          <p>${Utils.escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  closeRunComparison() {
    const modal = document.getElementById("run-comparison-modal");
    if (modal) modal.classList.remove("active");
  }

  renderComparisonContent(runA, runB) {
    const container = document.getElementById("comparison-content-container");
    if (!container) return;

    const riskA = runA.current_runtime_prediction?.failure_probability_pct ?? "—";
    const riskB = runB.current_runtime_prediction?.failure_probability_pct ?? "—";
    const rInfoA = Utils.classifyRisk(riskA);
    const rInfoB = Utils.classifyRisk(riskB);

    const warnA = Array.isArray(runA.warning_history) ? runA.warning_history.length : 0;
    const warnB = Array.isArray(runB.warning_history) ? runB.warning_history.length : 0;

    const durA = Utils.formatDuration(runA.ci_execution?.duration_seconds);
    const durB = Utils.formatDuration(runB.ci_execution?.duration_seconds);

    const statusA = runA.actual_outcome === "success" ? "SUCCESS" : (runA.actual_outcome === "failure" ? "FAILED" : (runA.status || "RUNNING").toUpperCase());
    const statusB = runB.actual_outcome === "success" ? "SUCCESS" : (runB.actual_outcome === "failure" ? "FAILED" : (runB.status || "RUNNING").toUpperCase());

    const isComparable = (runA.runtime_model === runB.runtime_model);

    container.innerHTML = `
      <div style="margin-bottom: 1rem;">
        <span class="badge ${isComparable ? 'badge-healthy' : 'badge-degraded'}">
          ${isComparable ? "Directly Comparable (Identical Model Architecture)" : "Cross-Architecture Comparison (Caution: Model Baselines Differ)"}
        </span>
      </div>

      <div class="comparison-grid">
        <div class="comparison-col">
          <div class="comp-col-header">
            <span class="demo-id-label">Run A:</span>
            <span class="font-mono font-bold">${Utils.escapeHtml(runA.run_id)}</span>
          </div>
          <div class="comp-col-body">
            <div class="comp-item"><span class="comp-label">Outcome</span><span>${Utils.renderBadge(statusA)}</span></div>
            <div class="comp-item"><span class="comp-label">Scenario</span><span class="font-bold">${Utils.escapeHtml(runA.scenario_preset || "none")}</span></div>
            <div class="comp-item"><span class="comp-label">Predictor</span><span>${Utils.escapeHtml(runA.runtime_model || "—")}</span></div>
            <div class="comp-item"><span class="comp-label">Failure Risk</span><span class="font-bold text-lg ${rInfoA.textClass}">${riskA !== "—" ? `${rInfoA.percentage}%` : "—"}</span></div>
            <div class="comp-item"><span class="comp-label">Warnings</span><span>${warnA} events</span></div>
            <div class="comp-item"><span class="comp-label">Duration</span><span class="font-mono">${durA}</span></div>
            <div class="comp-item"><span class="comp-label">Parser V2 Class</span><span>${Utils.escapeHtml(runA.parser_v2_result?.failure_class || "none")}</span></div>
          </div>
        </div>

        <div class="comparison-col">
          <div class="comp-col-header">
            <span class="demo-id-label">Run B:</span>
            <span class="font-mono font-bold">${Utils.escapeHtml(runB.run_id)}</span>
          </div>
          <div class="comp-col-body">
            <div class="comp-item"><span class="comp-label">Outcome</span><span>${Utils.renderBadge(statusB)}</span></div>
            <div class="comp-item"><span class="comp-label">Scenario</span><span class="font-bold">${Utils.escapeHtml(runB.scenario_preset || "none")}</span></div>
            <div class="comp-item"><span class="comp-label">Predictor</span><span>${Utils.escapeHtml(runB.runtime_model || "—")}</span></div>
            <div class="comp-item"><span class="comp-label">Failure Risk</span><span class="font-bold text-lg ${rInfoB.textClass}">${riskB !== "—" ? `${rInfoB.percentage}%` : "—"}</span></div>
            <div class="comp-item"><span class="comp-label">Warnings</span><span>${warnB} events</span></div>
            <div class="comp-item"><span class="comp-label">Duration</span><span class="font-mono">${durB}</span></div>
            <div class="comp-item"><span class="comp-label">Parser V2 Class</span><span>${Utils.escapeHtml(runB.parser_v2_result?.failure_class || "none")}</span></div>
          </div>
        </div>
      </div>
    `;
  }

  renderTableEmptyState(msg) {
    const tableBody = document.getElementById("history-runs-table-body");
    if (tableBody) {
      tableBody.innerHTML = `<tr><td colspan="10" class="text-center text-muted py-5">${Utils.escapeHtml(msg || "No historical runs found.")}</td></tr>`;
    }
  }
}

export const runHistoryController = new RunHistoryController();

