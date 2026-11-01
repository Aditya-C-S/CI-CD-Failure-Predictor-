/**
 * frontend/js/metadata-intel.js
 * Pre-Build Commit Metadata Intelligence & Risk Gatekeeper (Module I).
 * Displays 38-feature schema inspection, SHAP waterfall drivers,
 * feature completeness & provenance breakdown, and commit comparison.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";

export class MetadataIntelController {
  constructor() {
    this.modelInfo = null;
    this.provenanceSpec = null;
    this.currentPrediction = null;
    this.comparisonPrediction = null;
    this.currentCommit = "HEAD";
    this.currentRepo = "Aditya-C-S/demo-order-service";
    this.activeRunId = null;
    this.recentRuns = [];
  }

  init() {
    this.bindEvents();
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "metadata-intel") {
        this.loadMetadataView();
      }
    });
    const hash = window.location.hash.replace(/^#/, "");
    if (hash === "metadata-intel") {
      this.loadMetadataView();
    }
    const params = new URLSearchParams(window.location.search);
    const presetParam = params.get("meta_preset") || params.get("preset");
    if (presetParam) {
      setTimeout(() => this.loadPresetMetadata(presetParam), 500);
    }
  }

  identifyScenario(run) {
    if (!run) return { label: "CUSTOM COMMIT", class: "badge-neutral" };
    const preset = (run.scenario_preset || "").toLowerCase();
    const outcome = (run.actual_outcome || run.status || "").toLowerCase();
    const rcaCat = (run.rca_result?.primary_category || run.rca_result?.category || run.stages?.rca_remediation?.category || "").toUpperCase();
    const execId = (run.scenario_execution?.scenario_id || "").toLowerCase();

    if (preset.includes("syntax") || execId.includes("syntax") || rcaCat.includes("SYNTAX")) {
      return { label: "SYNTAX FAILURE", class: "badge-unhealthy" };
    }
    if (preset.includes("dependency") || execId.includes("dependency") || rcaCat.includes("DEPENDENCY") || rcaCat.includes("ENV")) {
      return { label: "DEPENDENCY FAILURE", class: "badge-degraded" };
    }
    if (preset.includes("pytest") || preset.includes("test") || execId.includes("test") || rcaCat.includes("TEST") || rcaCat.includes("PYTEST")) {
      return { label: "PYTEST / TEST FAILURE", class: "badge-degraded" };
    }
    if (preset.includes("clean") || preset.includes("fast_track") || preset.includes("nominal") || outcome === "success") {
      return { label: "CLEAN / SUCCESS", class: "badge-healthy" };
    }
    return { label: "CUSTOM COMMIT", class: "badge-neutral" };
  }

  setModeIndicator(text, badgeClass) {
    const el = document.getElementById("meta-mode-indicator");
    if (el) {
      el.textContent = text;
      el.className = `status-pill ${badgeClass} font-mono`;
    }
  }

  setScenarioBadge(info) {
    const el = document.getElementById("meta-run-scenario-badge");
    if (el && info) {
      el.textContent = info.label;
      el.className = `status-pill ${info.class} font-semibold`;
      el.style.display = "inline-block";
    }
  }

  clearStaleState() {
    const gaugeEl = document.getElementById("meta-risk-gauge-val");
    if (gaugeEl) {
      gaugeEl.textContent = "--%";
      gaugeEl.style.color = "var(--text-muted)";
    }
    const arcFill = document.getElementById("meta-gauge-arc-fill");
    if (arcFill) {
      arcFill.style.strokeDashoffset = "188.5";
      arcFill.style.stroke = "var(--text-muted)";
    }
    const gaugeBar = document.getElementById("meta-risk-gauge-bar");
    if (gaugeBar) {
      gaugeBar.style.width = "0%";
    }
    const verdictEl = document.getElementById("meta-verdict-badge");
    if (verdictEl) {
      verdictEl.className = "status-pill badge-neutral";
      verdictEl.textContent = "EVALUATING";
    }
    const descEl = document.getElementById("meta-verdict-desc");
    if (descEl) descEl.textContent = "Evaluating commit telemetry...";

    const latencyEl = document.getElementById("meta-latency-val");
    if (latencyEl) latencyEl.textContent = "--";
    const rawScoreEl = document.getElementById("meta-raw-score-val");
    if (rawScoreEl) rawScoreEl.textContent = "--";

    const pctEl = document.getElementById("meta-completeness-pct");
    if (pctEl) pctEl.textContent = "--%";
    const summaryEl = document.getElementById("meta-completeness-summary");
    if (summaryEl) summaryEl.textContent = "Calculating feature completeness...";
    const subtextEl = document.getElementById("meta-completeness-subtext");
    if (subtextEl) subtextEl.textContent = "Extracting telemetry...";

    const segMeasured = document.getElementById("meta-prov-seg-measured");
    if (segMeasured) segMeasured.style.width = "0%";
    const segDerived = document.getElementById("meta-prov-seg-derived");
    if (segDerived) segDerived.style.width = "0%";
    const segPreset = document.getElementById("meta-prov-seg-preset");
    if (segPreset) segPreset.style.width = "0%";
    const segDefault = document.getElementById("meta-prov-seg-default");
    if (segDefault) segDefault.style.width = "0%";

    ["kpi-files-changed", "kpi-source-churn", "kpi-test-churn", "kpi-test-ratio", "kpi-churn-density", "kpi-build-num"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.textContent = "--";
    });

    const shapContainer = document.getElementById("meta-shap-drivers-container");
    if (shapContainer) {
      shapContainer.innerHTML = '<div style="padding: 1.5rem; text-align: center; color: var(--text-muted);"><span class="spinner-small" style="display: inline-block; margin-right: 8px;"></span> Computing local SHAP feature attributions...</div>';
    }
  }

  bindEvents() {
    const runSelect = document.getElementById("meta-run-select");
    if (runSelect) {
      runSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        if (val) {
          const run = this.recentRuns.find(r => r.run_id === val);
          if (run) {
            this.setModeIndicator("ACTUAL RUN PREDICTION", "badge-healthy");
            this.setScenarioBadge(this.identifyScenario(run));
            this.currentCommit = run.commit_sha || "HEAD";
            this.currentRepo = run.repo_id || "Aditya-C-S/demo-order-service";
            this.activeRunId = run.run_id;

            const input = document.getElementById("meta-commit-input");
            if (input) input.value = this.currentCommit;
            const repoInput = document.getElementById("meta-repo-input");
            if (repoInput) repoInput.value = this.currentRepo;

            this.clearStaleState();
            this.analyzeCommit(this.currentCommit, this.currentRepo, this.activeRunId);
          }
        }
      });
    }

    const analyzeBtn = document.getElementById("meta-btn-analyze");
    if (analyzeBtn) {
      analyzeBtn.addEventListener("click", () => {
        const input = document.getElementById("meta-commit-input");
        const commit = input ? input.value.trim() : "HEAD";
        const repoInput = document.getElementById("meta-repo-input");
        const repo = repoInput ? repoInput.value.trim() : this.currentRepo;

        this.setModeIndicator("ACTUAL RUN PREDICTION", "badge-healthy");
        this.clearStaleState();
        this.analyzeCommit(commit || "HEAD", repo || this.currentRepo, this.activeRunId);
      });
    }

    const compareSelect = document.getElementById("meta-compare-select");
    if (compareSelect) {
      compareSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        if (val) {
          this.loadComparisonCommit(val);
        } else {
          const compContainer = document.getElementById("meta-comparison-results");
          if (compContainer) compContainer.style.display = "none";
        }
      });
    }

    // Preset quick simulation buttons
    document.querySelectorAll("[data-meta-preset]").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const preset = e.currentTarget.getAttribute("data-meta-preset");
        this.loadPresetMetadata(preset);
      });
    });
  }

  async loadMetadataView() {
    try {
      if (!this.modelInfo) {
        this.modelInfo = await api.getMetadataModelInfo();
        this.renderModelInfoBanner();
      }
      if (!this.provenanceSpec) {
        this.provenanceSpec = await api.getCanonicalProvenance();
      }
      await this.loadRecentRunsDropdown();
      const firstRun = this.recentRuns && this.recentRuns.length > 0 ? this.recentRuns[0] : null;
      if (firstRun) {
        this.setModeIndicator("ACTUAL RUN PREDICTION", "badge-healthy");
        this.setScenarioBadge(this.identifyScenario(firstRun));
        this.currentCommit = firstRun.commit_sha || "HEAD";
        this.currentRepo = firstRun.repo_id || "Aditya-C-S/demo-order-service";
        this.activeRunId = firstRun.run_id;

        const sel = document.getElementById("meta-run-select");
        if (sel) sel.value = firstRun.run_id;
        const input = document.getElementById("meta-commit-input");
        if (input) input.value = this.currentCommit;
        const repoInput = document.getElementById("meta-repo-input");
        if (repoInput) repoInput.value = this.currentRepo;

        this.clearStaleState();
        await this.analyzeCommit(this.currentCommit, this.currentRepo, this.activeRunId);
      } else {
        this.setModeIndicator("ACTUAL RUN PREDICTION", "badge-healthy");
        await this.analyzeCommit(this.currentCommit, this.currentRepo);
      }
    } catch (err) {
      console.error("Failed to load metadata view:", err);
      Utils.showToast("Failed to load metadata intelligence: " + err.message, "error");
    }
  }

  async loadRecentRunsDropdown() {
    try {
      this.recentRuns = await api.getRecentRuns(15);
      const sel = document.getElementById("meta-run-select");
      const compSel = document.getElementById("meta-compare-select");
      if (!sel) return;

      const opts = ['<option value="">-- Select Run / Commit --</option>'];
      const compOpts = ['<option value="">-- None (Select run to compare) --</option>'];

      this.recentRuns.forEach(r => {
        const sha = (r.commit_sha || "HEAD").substring(0, 8);
        const scenario = this.identifyScenario(r).label;
        const label = `${r.run_id.substring(0, 24)}... (${sha} - ${scenario})`;
        opts.push(`<option value="${r.run_id}">${label}</option>`);
        compOpts.push(`<option value="${r.run_id}">${label}</option>`);
      });

      sel.innerHTML = opts.join("");
      if (compSel) compSel.innerHTML = compOpts.join("");
    } catch (err) {
      console.warn("Could not load recent runs for metadata dropdown:", err);
    }
  }

  renderModelInfoBanner() {
    const el = document.getElementById("meta-model-info-banner");
    if (!el || !this.modelInfo) return;

    el.innerHTML = `
      <div class="meta-info-grid">
        <div class="meta-info-item">
          <span class="info-label">Gatekeeper Algorithm</span>
          <span class="info-val font-semibold">${Utils.escapeHtml(this.modelInfo.algorithm || "LightGBM + CalibratedClassifierCV")}</span>
        </div>
        <div class="meta-info-item">
          <span class="info-label">Feature Schema</span>
          <span class="info-val">${this.modelInfo.feature_count || 38} Canonical Pre-Build Features</span>
        </div>
        <div class="meta-info-item">
          <span class="info-label">Model Version</span>
          <span class="info-val font-mono">${Utils.escapeHtml(this.modelInfo.model_version || "v1.1.0")}</span>
        </div>
        <div class="meta-info-item">
          <span class="info-label">Inference Latency (p50)</span>
          <span class="info-val font-semibold text-accent">${this.modelInfo.benchmark_latency_p50_ms || 3.4} ms</span>
        </div>
        <div class="meta-info-item">
          <span class="info-label">Training Source</span>
          <span class="info-val text-muted" title="${Utils.escapeHtml(this.modelInfo.training_source || '')}">TravisTorrent (919k builds)</span>
        </div>
      </div>
    `;
  }

  async analyzeCommit(commitHash, repo, runId = null) {
    const spinner = document.getElementById("meta-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const payload = {
        commit_hash: commitHash || "HEAD",
        repository: repo || this.currentRepo
      };
      if (runId) {
        payload.run_id = runId;
      }

      const result = await api.predictMetadata(payload);
      this.currentPrediction = result;
      this.renderOverviewCard(result);
      this.renderCompletenessCard(result);
      this.renderCommitSummary(result);
      this.renderShapDrivers(result);
      this.renderFeatureAccordion(result);
      Utils.showToast("Metadata analyzed for " + (commitHash ? commitHash.substring(0, 8) : "commit"), "success", 2000);
    } catch (err) {
      console.error("Metadata analysis failed:", err);
      Utils.showToast("Analysis failed: " + err.message, "error", 4000);
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  async loadPresetMetadata(presetKey) {
    let norm = (presetKey || "clean").toLowerCase().trim();
    if (norm === "clean-pass" || norm === "clean_pass") norm = "clean";
    if (norm === "dependency-failure" || norm === "dependency_failure") norm = "dependency";
    if (norm === "syntax-error" || norm === "syntax_error") norm = "syntax";
    if (norm === "pytest-failure" || norm === "pytest_failure") norm = "pytest";

    const presetLabels = {
      clean: { label: "SIMULATION: CLEAN (~18.0%)", class: "badge-healthy" },
      dependency: { label: "SIMULATION: DEPENDENCY (~46.2%)", class: "badge-degraded" },
      pytest: { label: "SIMULATION: PYTEST (~64.0%)", class: "badge-degraded" },
      syntax: { label: "SIMULATION: SYNTAX (~68.4%)", class: "badge-unhealthy" }
    };
    const info = presetLabels[norm] || { label: `SIMULATION: ${norm.toUpperCase()}`, class: "badge-neutral" };

    this.setModeIndicator("SCENARIO SIMULATION", "badge-neutral");
    this.setScenarioBadge(info);
    this.clearStaleState();

    const spinner = document.getElementById("meta-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const res = await api.predictMetadata({
        commit_hash: `preset_${norm}`,
        repository: this.currentRepo,
        scenario_preset_name: norm
      });
      this.currentPrediction = res;
      this.renderOverviewCard(res);
      this.renderCompletenessCard(res);
      this.renderCommitSummary(res);
      this.renderShapDrivers(res);
      this.renderFeatureAccordion(res);
      Utils.showToast(`Simulated preset scenario: ${norm} (${res.verdict})`, "info", 2500);
    } catch (err) {
      console.warn("Preset simulation error:", err);
      Utils.showToast("Preset simulation error: " + err.message, "error", 4000);
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  async loadComparisonCommit(runId) {
    const compContainer = document.getElementById("meta-comparison-results");
    if (!compContainer) return;

    try {
      const run = this.recentRuns.find(r => r.run_id === runId);
      const commitSha = run ? (run.commit_sha || run.run_id) : runId;
      const result = await api.predictMetadata({
        run_id: run ? run.run_id : undefined,
        commit_hash: commitSha,
        repository: run ? run.repo_id : this.currentRepo
      });
      this.comparisonPrediction = result;
      this.renderCommitComparison(this.currentPrediction, result, run);
      compContainer.style.display = "block";
    } catch (err) {
      Utils.showToast("Failed to load comparison metadata: " + err.message, "error");
    }
  }

  renderOverviewCard(data) {
    const probPct = data.failure_probability_pct ?? ((data.failure_probability || 0) * 100);
    const probDisplay = probPct.toFixed(1) + "%";

    // Calibrated color rules: <=40% Green, >40% and <70% Yellow, >=70% Red
    let riskColor = "var(--risk-green, #10b981)";
    let riskTier = "LOW";
    if (probPct >= 70) {
      riskColor = "var(--risk-red, #ef4444)";
      riskTier = "CRITICAL";
    } else if (probPct > 40) {
      riskColor = "var(--risk-yellow, #f59e0b)";
      riskTier = "MODERATE";
    }

    // Verdict styling
    const verdict = data.verdict || "STANDARD GATE";
    let verdictClass = "badge-neutral";
    if (verdict === "FAST-TRACK" || verdict === "PASSED") verdictClass = "badge-healthy";
    else if (verdict === "ALERT" || verdict === "FLAGGED") verdictClass = "badge-degraded";
    else if (verdict === "PRE-MERGE BLOCK" || verdict === "ELEVATED RISK") verdictClass = "badge-unhealthy";

    const gaugeEl = document.getElementById("meta-risk-gauge-val");
    if (gaugeEl) {
      gaugeEl.textContent = probDisplay;
      gaugeEl.style.color = riskColor;
    }

    // Dynamic Semicircular SVG Gauge arc
    const arcFill = document.getElementById("meta-gauge-arc-fill");
    if (arcFill) {
      const maxOffset = 188.5;
      const clampedPct = Math.min(100, Math.max(0, probPct));
      const offset = maxOffset - (maxOffset * (clampedPct / 100));
      arcFill.style.strokeDashoffset = offset;
      arcFill.style.stroke = riskColor;
    }

    const gaugeBar = document.getElementById("meta-risk-gauge-bar");
    if (gaugeBar) {
      gaugeBar.style.width = Math.min(100, Math.max(5, probPct)) + "%";
      gaugeBar.style.backgroundColor = riskColor;
    }

    const verdictEl = document.getElementById("meta-verdict-badge");
    if (verdictEl) {
      verdictEl.className = `status-pill ${verdictClass}`;
      verdictEl.textContent = verdict;
    }

    const descEl = document.getElementById("meta-verdict-desc");
    if (descEl) {
      descEl.textContent = data.verdict_description || `Gatekeeper risk assessment: ${riskTier} risk profile based on commit telemetry.`;
    }

    const latencyEl = document.getElementById("meta-latency-val");
    if (latencyEl) {
      latencyEl.textContent = (data.latency_ms ? data.latency_ms.toFixed(1) : "3.4") + " ms";
    }

    const rawScoreEl = document.getElementById("meta-raw-score-val");
    if (rawScoreEl) {
      rawScoreEl.textContent = (data.raw_score !== undefined ? data.raw_score.toFixed(4) : (data.failure_probability || 0).toFixed(4));
    }

    const commitEl = document.getElementById("meta-commit-display");
    if (commitEl) {
      commitEl.textContent = (this.currentCommit || "HEAD").substring(0, 10);
    }

    const modelDisplay = document.getElementById("meta-model-name-display");
    if (modelDisplay) {
      modelDisplay.textContent = this.modelInfo?.algorithm || "LightGBM Calibrated";
    }
  }

  renderCompletenessCard(data) {
    const comp = data.completeness || {};
    const total = comp.total_features || 38;
    const observed = comp.observed_features || 0;
    const derived = comp.derived_features || 0;
    const preset = comp.preset_features || 0;
    const def = comp.default_features || Math.max(0, total - observed - derived - preset);
    const pct = comp.completeness_pct !== undefined ? comp.completeness_pct : ((observed / total) * 100);

    const pctEl = document.getElementById("meta-completeness-pct");
    if (pctEl) pctEl.textContent = pct.toFixed(1) + "%";

    const meterEl = document.getElementById("meta-completeness-meter-bar");
    if (meterEl) {
      meterEl.style.width = pct.toFixed(1) + "%";
      meterEl.style.backgroundColor = pct >= 50 ? "var(--accent-primary)" : "var(--status-degraded)";
    }

    const summaryEl = document.getElementById("meta-completeness-summary");
    if (summaryEl) {
      summaryEl.textContent = `${observed} of ${total} measured`;
    }

    const subtextEl = document.getElementById("meta-completeness-subtext");
    if (subtextEl) {
      subtextEl.textContent = `${pct.toFixed(1)}% observed commit telemetry (${def} defaults)`;
    }

    // Stacked segments
    const segMeasured = document.getElementById("meta-prov-seg-measured");
    const segDerived = document.getElementById("meta-prov-seg-derived");
    const segPreset = document.getElementById("meta-prov-seg-preset");
    const segDefault = document.getElementById("meta-prov-seg-default");

    if (segMeasured) {
      segMeasured.style.width = ((observed / total) * 100).toFixed(1) + "%";
      segMeasured.title = `${observed} Measured Git/CI features`;
    }
    if (segDerived) {
      segDerived.style.width = ((derived / total) * 100).toFixed(1) + "%";
      segDerived.title = `${derived} Derived ratio features`;
    }
    if (segPreset) {
      segPreset.style.width = ((preset / total) * 100).toFixed(1) + "%";
      segPreset.title = `${preset} Scenario preset features`;
    }
    if (segDefault) {
      segDefault.style.width = ((def / total) * 100).toFixed(1) + "%";
      segDefault.title = `${def} Calibrated TravisTorrent defaults`;
    }

    const breakdownEl = document.getElementById("meta-completeness-breakdown");
    if (breakdownEl) {
      breakdownEl.innerHTML = `
        <div class="completeness-chip chip-measured" title="Features computed genuinely from repository commit churn and git diffs">
          <span class="chip-count">${observed}</span>
          <span class="chip-label">Measured Git/CI</span>
        </div>
        <div class="completeness-chip chip-derived" title="Mathematically derived ratios combining commit churn and testing volume">
          <span class="chip-count">${derived}</span>
          <span class="chip-label">Derived Ratios</span>
        </div>
        <div class="completeness-chip chip-preset" title="Preset contextual runtime dimensions calibrated for this demo scenario">
          <span class="chip-count">${preset}</span>
          <span class="chip-label">Scenario Presets</span>
        </div>
        <div class="completeness-chip chip-default" title="TravisTorrent 919k-build dataset population medians used for neutral imputation">
          <span class="chip-count">${def}</span>
          <span class="chip-label">Calibrated Defaults</span>
        </div>
      `;
    }
  }

  renderCommitSummary(data) {
    const feat = data.features_analyzed || {};
    const filesChanged = feat.total_files_changed ?? feat.gh_diff_files_modified ?? 1;
    const srcChurn = feat.git_diff_src_churn ?? 0;
    const testChurn = feat.git_diff_test_churn ?? 0;
    const testRatio = feat.test_to_src_churn_ratio !== undefined ? Number(feat.test_to_src_churn_ratio).toFixed(2) : (srcChurn > 0 ? (testChurn / srcChurn).toFixed(2) : "0.00");
    const churnDensity = feat.code_churn_density !== undefined ? Number(feat.code_churn_density).toFixed(1) : (filesChanged > 0 ? (srcChurn / filesChanged).toFixed(1) : "0.0");
    const buildNum = feat.tr_build_number ? `#${feat.tr_build_number}` : "--";

    const elFiles = document.getElementById("kpi-files-changed");
    if (elFiles) elFiles.textContent = filesChanged;
    const elSrc = document.getElementById("kpi-source-churn");
    if (elSrc) elSrc.textContent = srcChurn;
    const elTest = document.getElementById("kpi-test-churn");
    if (elTest) elTest.textContent = testChurn;
    const elRatio = document.getElementById("kpi-test-ratio");
    if (elRatio) elRatio.textContent = testRatio;
    const elDensity = document.getElementById("kpi-churn-density");
    if (elDensity) elDensity.textContent = churnDensity;
    const elBuild = document.getElementById("kpi-build-num");
    if (elBuild) elBuild.textContent = buildNum;
  }

  renderShapDrivers(data) {
    const container = document.getElementById("meta-shap-drivers-container");
    if (!container) return;

    const shap = data.shap_drivers || {};
    const positive = (shap.positive || []).slice(0, 3);
    const negative = (shap.negative || []).slice(0, 3);

    if (positive.length === 0 && negative.length === 0) {
      container.innerHTML = `<div class="empty-state-notice">SHAP feature drivers not computed for this configuration.</div>`;
      return;
    }

    const featureRationales = {
      git_diff_src_churn: "Extensive modifications to source code logic expand the potential bug surface area.",
      git_diff_test_churn: "Comprehensive unit and integration test additions provide verification safeguards.",
      total_files_changed: "High multi-file footprint increases coupling and cross-module integration risk.",
      gh_diff_files_modified: "Modified files require multi-target test suite execution.",
      test_to_src_churn_ratio: "Sufficient testing density relative to code churn mitigates deployment risk.",
      code_churn_density: "Concentrated churn lines per modified file signify elevated architectural complexity.",
      tr_build_number: "Established CI build depth and pipeline stability indicate codebase maturity.",
      gh_repo_age: "Longer repository lifecycle history is associated with lower baseline defect rates.",
      log_team_size: "Collaborative multi-developer review history supports commit verification.",
      gh_by_core_team_member: "Authored by core repository maintainer with established domain knowledge."
    };

    const maxContrib = Math.max(
      ...positive.map(d => Math.abs(d.contribution || 0)),
      ...negative.map(d => Math.abs(d.contribution || 0)),
      0.05
    );

    let html = `
      <div class="shap-columns-grid">
        <div class="shap-col">
          <h4 class="shap-col-header text-danger">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="18 15 12 9 6 15"></polyline>
            </svg>
            Top Risk-Increasing Features (+ SHAP Contribution)
          </h4>
          <div class="shap-bar-list">
    `;

    if (positive.length === 0) {
      html += `<div class="text-muted text-sm" style="padding: 0.5rem 0;">No significant positive risk drivers identified (low risk baseline).</div>`;
    } else {
      positive.forEach(item => {
        const widthPct = Math.min(100, Math.round((Math.abs(item.contribution) / maxContrib) * 100));
        const rationale = featureRationales[item.feature] || "Observed value contributes upward pressure to pre-build failure risk.";
        html += `
          <div class="shap-driver-card">
            <div class="shap-driver-header">
              <span class="font-mono font-semibold text-sm" title="${Utils.escapeHtml(item.feature)}">${Utils.escapeHtml(item.feature)}</span>
              <span class="font-mono font-bold text-danger text-sm">+${item.contribution.toFixed(4)}</span>
            </div>
            <div class="shap-bar-track">
              <div class="shap-bar-fill fill-danger" style="width: ${widthPct}%"></div>
            </div>
            <div class="shap-driver-explanation">${rationale}</div>
          </div>
        `;
      });
    }

    html += `
          </div>
        </div>
        <div class="shap-col">
          <h4 class="shap-col-header text-success">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
            Top Risk-Reducing Features (- SHAP / Supporting Pass)
          </h4>
          <div class="shap-bar-list">
    `;

    if (negative.length === 0) {
      html += `<div class="text-muted text-sm" style="padding: 0.5rem 0;">No significant negative risk mitigators identified.</div>`;
    } else {
      negative.forEach(item => {
        const widthPct = Math.min(100, Math.round((Math.abs(item.contribution) / maxContrib) * 100));
        const rationale = featureRationales[item.feature] || "Observed value acts as a protective factor, reducing predicted failure risk.";
        html += `
          <div class="shap-driver-card">
            <div class="shap-driver-header">
              <span class="font-mono font-semibold text-sm" title="${Utils.escapeHtml(item.feature)}">${Utils.escapeHtml(item.feature)}</span>
              <span class="font-mono font-bold text-success text-sm">${item.contribution.toFixed(4)}</span>
            </div>
            <div class="shap-bar-track">
              <div class="shap-bar-fill fill-success" style="width: ${widthPct}%"></div>
            </div>
            <div class="shap-driver-explanation">${rationale}</div>
          </div>
        `;
      });
    }

    html += `
          </div>
        </div>
      </div>
    `;

    container.innerHTML = html;
  }

  renderFeatureAccordion(data) {
    const container = document.getElementById("meta-features-accordion-container");
    if (!container) return;

    const analyzed = data.features_analyzed || {};
    const prov = data.provenance || {};

    const categories = {
      "Code Churn & Diff (11 features)": [
        "git_diff_src_churn", "git_diff_test_churn", "gh_diff_files_added",
        "gh_diff_files_deleted", "gh_diff_files_modified", "gh_diff_src_files",
        "gh_diff_doc_files", "gh_diff_other_files", "total_files_changed",
        "code_churn_density", "test_to_src_churn_ratio"
      ],
      "Historical & Author Metrics (10 features)": [
        "gh_by_core_team_member", "gh_repo_age", "gh_repo_num_commits",
        "tr_build_number", "log_team_size", "log_built_commits",
        "gh_num_commits_on_files_touched", "has_previous_build",
        "git_prev_commit_resolution_status_merge_found",
        "git_prev_commit_resolution_status_no_previous_build"
      ],
      "Testing & Quality Coverage (6 features)": [
        "gh_diff_tests_added", "gh_diff_tests_deleted", "gh_test_lines_per_kloc",
        "gh_test_cases_per_kloc", "gh_asserts_cases_per_kloc", "gh_sloc"
      ],
      "Environment & CI Context (11 features)": [
        "gh_is_pr", "gh_lang_java", "gh_lang_python", "gh_lang_ruby",
        "gh_num_issue_comments", "gh_num_commit_comments", "gh_num_pr_comments",
        "gh_pr_created_at_year", "gh_pr_created_at_month", "pr_dayofweek",
        "git_merged_with_present"
      ]
    };

    let html = "";
    Object.entries(categories).forEach(([catTitle, featList], idx) => {
      const isExpanded = idx === 0;
      html += `
        <div class="accordion-item ${isExpanded ? 'active' : ''}">
          <button type="button" class="accordion-header" onclick="this.parentElement.classList.toggle('active')">
            <span class="accordion-title font-semibold">${catTitle}</span>
            <span class="accordion-badge">${featList.length} features</span>
            <svg class="accordion-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <div class="accordion-content">
            <div class="table-responsive">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Feature Key</th>
                    <th>Observed Value</th>
                    <th>Type</th>
                    <th>Provenance Source</th>
                    <th>Observation Status &amp; Lineage</th>
                  </tr>
                </thead>
                <tbody>
      `;

      featList.forEach(featKey => {
        const val = analyzed[featKey] !== undefined ? analyzed[featKey] : 0.0;
        const p = prov[featKey] || {};
        const isReal = p.is_real_evidence || p.source_category === "measured";
        const isPreset = p.source_category === "scenario_preset" || p.source_category === "preset";
        const isDerived = p.source_category === "derived";

        let badgeClass = "badge-neutral";
        let badgeText = "Default Fallback";
        if (isReal) {
          badgeClass = "badge-healthy";
          badgeText = "Measured Git/CI";
        } else if (isPreset) {
          badgeClass = "badge-info";
          badgeText = "Scenario Preset";
        } else if (isDerived) {
          badgeClass = "badge-scenario";
          badgeText = "Derived Ratio";
        }

        const formatVal = typeof val === "number" ? (Number.isInteger(val) ? val.toString() : val.toFixed(3)) : String(val);

        html += `
          <tr>
            <td class="font-mono font-semibold">${Utils.escapeHtml(featKey)}</td>
            <td class="font-mono font-bold">${Utils.escapeHtml(formatVal)}</td>
            <td class="text-muted text-xs">${featKey.startsWith("gh_lang_") || featKey === "gh_is_pr" ? "binary" : "float"}</td>
            <td><span class="status-pill ${badgeClass}">${badgeText}</span></td>
            <td class="text-xs text-muted" title="${Utils.escapeHtml(p.description || '')}">${Utils.escapeHtml(p.description || (isReal ? "Extracted directly from git" : "TravisTorrent population median"))}</td>
          </tr>
        `;
      });

      html += `
                </tbody>
              </table>
            </div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
  }

  renderCommitComparison(predA, predB, runB) {
    const compBody = document.getElementById("meta-comparison-tbody");
    if (!compBody || !predA || !predB) return;

    const probAVal = predA.failure_probability_pct ?? ((predA.failure_probability || 0) * 100);
    const probBVal = predB.failure_probability_pct ?? ((predB.failure_probability || 0) * 100);
    const probA = probAVal.toFixed(1);
    const probB = probBVal.toFixed(1);
    const deltaProb = (probBVal - probAVal).toFixed(1);

    const featA = predA.features_analyzed || {};
    const featB = predB.features_analyzed || {};

    const shaB = runB ? (runB.commit_sha || runB.run_id) : "Comparison Run";
    const shaA = this.currentCommit || "Primary Run";
    const isSameCommit = Boolean(shaA && shaB && (shaA === shaB || (shaA.length >= 8 && shaB.length >= 8 && shaA.substring(0, 8) === shaB.substring(0, 8))));

    const noticeEl = document.getElementById("meta-comparison-notice");
    if (noticeEl) {
      if (isSameCommit) {
        if (probA === probB) {
          noticeEl.className = "alert alert-info";
          noticeEl.style.display = "block";
          noticeEl.innerHTML = `<strong>Identical Commit SHA (${Utils.escapeHtml(shaA.substring(0, 8))}):</strong> Both runs evaluated the exact same commit; Git diff statistics, feature lineage, and LightGBM pre-build risk are identical.`;
        } else {
          noticeEl.className = "alert alert-warning";
          noticeEl.style.display = "block";
          noticeEl.innerHTML = `<strong>Same Commit SHA (<code>${Utils.escapeHtml(shaA.substring(0, 8))}</code>) under Differing Scenario Presets:</strong> Both runs evaluated commit <code>${Utils.escapeHtml(shaA.substring(0, 8))}</code> with identical Git churn. Selection A evaluated under preset <code>${Utils.escapeHtml(predA.scenario_preset_name || "standard")}</code> (${probA}% risk) while Selection B evaluated under preset <code>${Utils.escapeHtml(runB?.scenario_preset || predB.scenario_preset_name || "comparison")}</code> (${probB}% risk). The delta reflects differing simulated environment conditions.`;
        }
      } else {
        noticeEl.className = "alert alert-neutral";
        noticeEl.style.display = "block";
        noticeEl.innerHTML = `<strong>Distinct Commits:</strong> Comparing primary commit <code>${Utils.escapeHtml(shaA.substring(0, 8))}</code> vs comparison commit <code>${Utils.escapeHtml(shaB.substring(0, 8))}</code>. Variance reflects different code changes and modified files.`;
      }
    }

    // Comparison KPI row cards
    const kpiContainer = document.getElementById("meta-comparison-kpis");
    if (kpiContainer) {
      const churnA = featA.git_diff_src_churn ?? 0;
      const churnB = featB.git_diff_src_churn ?? 0;
      const filesA = featA.total_files_changed ?? featA.gh_diff_files_modified ?? 1;
      const filesB = featB.total_files_changed ?? featB.gh_diff_files_modified ?? 1;
      const compPctA = predA.completeness?.completeness_pct ? predA.completeness.completeness_pct.toFixed(0) : "45";
      const compPctB = predB.completeness?.completeness_pct ? predB.completeness.completeness_pct.toFixed(0) : "45";

      kpiContainer.innerHTML = `
        <div class="comparison-kpi-card">
          <span class="comp-kpi-label">Pre-Build Risk</span>
          <div class="comp-kpi-vals">
            <span>${probA}% &rarr; ${probB}%</span>
            <span class="comp-delta-badge ${Number(deltaProb) > 0 ? 'badge-unhealthy' : (Number(deltaProb) < 0 ? 'badge-healthy' : 'badge-neutral')}">${Number(deltaProb) > 0 ? '+' : ''}${deltaProb}%</span>
          </div>
        </div>
        <div class="comparison-kpi-card">
          <span class="comp-kpi-label">Gate Verdict</span>
          <div class="comp-kpi-vals">
            <span class="text-xs">${Utils.escapeHtml(predA.verdict || "GATE")} &rarr; ${Utils.escapeHtml(predB.verdict || "GATE")}</span>
          </div>
        </div>
        <div class="comparison-kpi-card">
          <span class="comp-kpi-label">Source Churn</span>
          <div class="comp-kpi-vals">
            <span>${churnA} &rarr; ${churnB}</span>
            <span class="comp-delta-badge badge-neutral">${churnB - churnA >= 0 ? '+' : ''}${churnB - churnA}</span>
          </div>
        </div>
        <div class="comparison-kpi-card">
          <span class="comp-kpi-label">Files Changed</span>
          <div class="comp-kpi-vals">
            <span>${filesA} &rarr; ${filesB}</span>
            <span class="comp-delta-badge badge-neutral">${filesB - filesA >= 0 ? '+' : ''}${filesB - filesA}</span>
          </div>
        </div>
        <div class="comparison-kpi-card">
          <span class="comp-kpi-label">Feature Completeness</span>
          <div class="comp-kpi-vals">
            <span>${compPctA}% &rarr; ${compPctB}%</span>
          </div>
        </div>
      `;
    }

    // Full 38-feature delta table
    const allFeatures = Object.keys({ ...featA, ...featB });
    allFeatures.sort();

    let html = `
      <tr class="comparison-header-row font-semibold" style="background: var(--bg-tertiary);">
        <td>Failure Probability</td>
        <td class="font-mono text-accent">${probA}%</td>
        <td class="font-mono text-accent">${probB}%</td>
        <td class="font-mono font-bold ${(Number(deltaProb) > 0 ? "text-danger" : (Number(deltaProb) < 0 ? "text-success" : "text-muted"))}">${Number(deltaProb) > 0 ? "+" : ""}${deltaProb}%</td>
      </tr>
      <tr class="comparison-header-row font-semibold" style="background: var(--bg-tertiary);">
        <td>Gatekeeper Verdict</td>
        <td><span class="status-pill badge-neutral">${predA.verdict || "GATE"}</span></td>
        <td><span class="status-pill badge-neutral">${predB.verdict || "GATE"}</span></td>
        <td class="text-sm text-muted">Comparison</td>
      </tr>
    `;

    allFeatures.forEach(feat => {
      const vA = featA[feat] !== undefined ? featA[feat] : 0;
      const vB = featB[feat] !== undefined ? featB[feat] : 0;
      const delta = (typeof vA === "number" && typeof vB === "number") ? vB - vA : 0;
      const deltaStr = typeof delta === "number" ? ((delta > 0 ? "+" : "") + (Number.isInteger(delta) ? delta : delta.toFixed(2))) : "--";
      const deltaClass = delta === 0 ? "text-muted" : (delta > 0 ? "text-warning" : "text-success");

      html += `
        <tr>
          <td class="font-mono">${Utils.escapeHtml(feat)}</td>
          <td class="font-mono">${typeof vA === "number" ? (Number.isInteger(vA) ? vA : vA.toFixed(2)) : String(vA)}</td>
          <td class="font-mono">${typeof vB === "number" ? (Number.isInteger(vB) ? vB : vB.toFixed(2)) : String(vB)}</td>
          <td class="font-mono ${deltaClass}">${deltaStr}</td>
        </tr>
      `;
    });

    compBody.innerHTML = html;
  }
}

export const metadataIntelController = new MetadataIntelController();

