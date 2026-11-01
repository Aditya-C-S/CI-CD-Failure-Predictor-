/**
 * frontend/js/api.js
 * Centralized API client for CI/CD Intelligence FastAPI Backend.
 */

export class ApiClient {
  constructor(baseUrl = "") {
    this.baseUrl = baseUrl.replace(/\/$/, "");
  }

  /**
   * Safe fetch with timeout and standard JSON error extraction.
   */
  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const controller = new AbortController();
    const timeoutMs = options.timeout || 12000;
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = {
      "Accept": "application/json",
      ...(options.headers || {})
    };

    if (options.body && typeof options.body === "object" && !(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(options.body);
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (!response.ok) {
        let errorDetail = `HTTP ${response.status}: ${response.statusText}`;
        try {
          const errJson = await response.json();
          if (errJson.detail) {
            errorDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
          } else if (errJson.message) {
            errorDetail = errJson.message;
          }
        } catch {
          // Response body was not JSON
        }
        const error = new Error(errorDetail);
        error.status = response.status;
        throw error;
      }

      return await response.json();
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === "AbortError") {
        throw new Error(`Request timed out after ${timeoutMs / 1000}s`);
      }
      throw err;
    }
  }

  // --- Diagnostics & Health ---

  async getSystemHealth() {
    return this.request("/api/health/system");
  }

  // --- Scenario Management ---

  async getScenarios() {
    return this.request("/api/scenarios");
  }

  async dispatchScenario({ scenario_id, repo_id = "Aditya-C-S/demo-order-service", runtime_model = "bilstm2", dry_run = false }) {
    return this.request("/api/scenarios/dispatch", {
      method: "POST",
      body: { scenario_id, repo_id, runtime_model, dry_run }
    });
  }

  async getScenarioStatus(runId) {
    return this.request(`/api/scenarios/runs/${encodeURIComponent(runId)}/status`);
  }

  // --- Run Intelligence & Summaries ---

  async getRecentRuns(limit = 15) {
    return this.request(`/api/demo/runs?limit=${limit}`);
  }

  async getRecentSummaries(limit = 10) {
    return this.request(`/api/summaries?limit=${limit}`);
  }

  async getRunDetails(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}`);
  }

  async getRunSummary(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/summary`);
  }

  async getRunPredictionHistory(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/prediction-history`);
  }

  async getRunRiskProgression(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/risk-progression`);
  }

  async getRunModelComparison(runId, depth = null) {
    const q = depth ? `?depth=${depth}` : "";
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/model-comparison${q}`);
  }

  async getRunWarnings(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/warnings`);
  }

  async getRunRcaEvidence(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/rca/evidence`);
  }

  async replaySampleStream(runId, sampleId = "F2/run_0005.log", chunkLines = 40) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/replay`, {
      method: "POST",
      body: { sample_id: sampleId, chunk_lines: chunkLines }
    });
  }

  async getRecentWarnings(limit = 10) {
    return this.request(`/api/warnings/recent?limit=${limit}`);
  }

  async getMetadataScorecard() {
    return this.request("/api/metadata/scorecard");
  }

  async getMetadataModelInfo() {
    return this.request("/api/metadata/model-info");
  }

  async getCanonicalProvenance() {
    return this.request("/api/metadata/canonical-provenance");
  }

  async predictMetadata(payload) {
    return this.request("/api/metadata/predict", {
      method: "POST",
      body: payload
    });
  }

  async getGraphStatus() {
    return this.request("/api/metadata/graph/status");
  }

  async analyzeBlastRadius(payload) {
    return this.request("/api/metadata/graph/blast-radius", {
      method: "POST",
      body: payload
    });
  }

  async calculateGraphImpact(payload) {
    return this.request("/api/metadata/graph/impact", {
      method: "POST",
      body: payload
    });
  }

  async getGraphRepositories() {
    return this.request("/api/metadata/graph/repositories");
  }

  async getGraphExplorer(params = {}) {
    const qs = new URLSearchParams(params).toString();
    return this.request(`/api/metadata/graph/explorer${qs ? "?" + qs : ""}`);
  }

  async compareModels(logText, depth = 100) {
    return this.request("/api/demo/compare-models", {
      method: "POST",
      body: { log_text: logText, depth }
    });
  }

  async getRunRca(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/rca`);
  }

  async triggerRunRca(runId, body = {}) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/rca`, {
      method: "POST",
      body
    });
  }

  async getRunRcaFindings(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/rca/findings`);
  }

  async getRunRcaRemediation(runId) {
    return this.request(`/api/demo/runs/${encodeURIComponent(runId)}/rca/remediation`);
  }
}

export const api = new ApiClient();

