/**
 * frontend/js/graph-intel.js
 * Neo4j Knowledge Graph & Blast Radius Impact Intelligence (Module II).
 * Interactive Cytoscape graph canvas, Graph Impact Score (0-100),
 * Blast Radius analysis, Node Inspector sidebar, and Tree-Sitter AST fallback.
 */

import { api } from "./api.js";
import { Utils } from "./utils.js";

export class GraphIntelController {
  constructor() {
    this.cy = null;
    this.graphStatus = null;
    this.currentRepo = "Aditya-C-S/demo-order-service";
    this.changedFiles = ["src/order_service.py"];
    this.currentMode = "blast_radius"; // "blast_radius" | "full"
    this.currentGraphData = null;
    this.selectedNode = null;
    this.activeFilter = "ALL";
    this.activeLayout = "cose";
    this.recentRuns = [];
    this.activeRunId = null;
  }

  init() {
    this.bindEvents();
    window.addEventListener("routechange", (e) => {
      if (e.detail.route === "graph-intel") {
        this.loadGraphView();
      }
    });
    const hash = window.location.hash.replace(/^#/, "");
    if (hash === "graph-intel") {
      this.loadGraphView();
    }
  }

  bindEvents() {
    // Mode toggles
    const btnBlast = document.getElementById("btn-graph-mode-blast");
    if (btnBlast) {
      btnBlast.addEventListener("click", () => {
        if (this.currentMode !== "blast_radius") {
          this.currentMode = "blast_radius";
          this.updateModeButtons();
          this.runBlastRadiusAnalysis(this.changedFiles);
        }
      });
    }

    const btnFull = document.getElementById("btn-graph-mode-full");
    if (btnFull) {
      btnFull.addEventListener("click", () => {
        if (this.currentMode !== "full") {
          this.loadFullArchitectureGraph();
        }
      });
    }

    // Run selector dropdown
    const runSelect = document.getElementById("graph-run-select");
    if (runSelect) {
      runSelect.addEventListener("change", (e) => {
        const val = e.target.value;
        if (val) {
          const run = this.recentRuns.find(r => r.run_id === val);
          if (run) {
            this.activeRunId = run.run_id;
            this.currentRepo = run.repo_id || "Aditya-C-S/demo-order-service";
            const runFiles = run.changed_files || (run.commit_info && run.commit_info.changed_files);
            if (Array.isArray(runFiles) && runFiles.length > 0) {
              this.changedFiles = runFiles;
            } else {
              this.changedFiles = ["src/order_service.py"];
            }
            const input = document.getElementById("graph-changed-files-input");
            if (input) input.value = this.changedFiles.join(", ");
            if (this.currentMode === "full") {
              this.loadFullArchitectureGraph();
            } else {
              this.runBlastRadiusAnalysis(this.changedFiles);
            }
          }
        }
      });
    }

    const btnAnalyze = document.getElementById("graph-btn-analyze-blast");
    if (btnAnalyze) {
      btnAnalyze.addEventListener("click", () => {
        const input = document.getElementById("graph-changed-files-input");
        const val = input ? input.value.trim() : "";
        const files = val ? val.split(",").map(f => f.trim()).filter(Boolean) : this.changedFiles;
        this.changedFiles = files;
        if (this.currentMode === "full") {
          this.loadFullArchitectureGraph();
        } else {
          this.runBlastRadiusAnalysis(files);
        }
      });
    }

    const searchInput = document.getElementById("graph-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this.searchNodes(e.target.value.trim());
      });
    }

    const layoutSelect = document.getElementById("graph-layout-select");
    if (layoutSelect) {
      layoutSelect.addEventListener("change", (e) => {
        this.activeLayout = e.target.value;
        this.applyLayout(this.activeLayout);
      });
    }

    const filterSelect = document.getElementById("graph-filter-select");
    if (filterSelect) {
      filterSelect.addEventListener("change", (e) => {
        this.activeFilter = e.target.value;
        this.applyFilter(this.activeFilter);
      });
    }

    const btnZoomIn = document.getElementById("graph-btn-zoom-in");
    if (btnZoomIn) {
      btnZoomIn.addEventListener("click", () => {
        if (this.cy) this.cy.zoom(this.cy.zoom() * 1.25);
      });
    }

    const btnZoomOut = document.getElementById("graph-btn-zoom-out");
    if (btnZoomOut) {
      btnZoomOut.addEventListener("click", () => {
        if (this.cy) this.cy.zoom(this.cy.zoom() * 0.8);
      });
    }

    const btnFit = document.getElementById("graph-btn-fit");
    if (btnFit) {
      btnFit.addEventListener("click", () => {
        if (this.cy) {
          this.cy.fit();
          this.cy.center();
        }
      });
    }

    // Preset changed file pills
    document.querySelectorAll("[data-graph-preset]").forEach(pill => {
      pill.addEventListener("click", (e) => {
        const file = e.currentTarget.getAttribute("data-graph-preset");
        const input = document.getElementById("graph-changed-files-input");
        if (input) input.value = file;
        this.changedFiles = [file];
        this.currentMode = "blast_radius";
        this.updateModeButtons();
        this.runBlastRadiusAnalysis([file]);
      });
    });
  }

  async loadGraphView() {
    try {
      this.graphStatus = await api.getGraphStatus();
      this.renderConnectionBanner(this.graphStatus);
      await this.loadRecentRunsDropdown();
      this.updateExternalLinks();
      this.updateModeButtons();
      if (this.currentMode === "full") {
        await this.loadFullArchitectureGraph();
      } else {
        await this.runBlastRadiusAnalysis(this.changedFiles);
      }
    } catch (err) {
      console.error("Failed to load graph view:", err);
      this.renderConnectionBanner({ status: "OFFLINE", connected: false, message: err.message });
      await this.runBlastRadiusAnalysis(this.changedFiles);
    }
  }

  async loadRecentRunsDropdown() {
    try {
      this.recentRuns = await api.getRecentRuns(15);
      const sel = document.getElementById("graph-run-select");
      if (!sel) return;

      const opts = ['<option value="">-- Select Run / Commit --</option>'];
      this.recentRuns.forEach(r => {
        const sha = (r.commit_sha || "HEAD").substring(0, 8);
        const label = `${r.run_id.substring(0, 24)}... (${sha} - ${r.actual_outcome || r.status || "run"})`;
        opts.push(`<option value="${r.run_id}">${label}</option>`);
      });
      sel.innerHTML = opts.join("");
    } catch (err) {
      console.warn("Could not load recent runs for graph selector:", err);
    }
  }

  updateExternalLinks() {
    const fullGraphBtn = document.getElementById("btn-open-full-graph");
    const explorerBtn = document.getElementById("btn-open-graph-explorer");
    const filesParam = encodeURIComponent(this.changedFiles.join(","));
    const repoParam = encodeURIComponent(this.currentRepo);

    if (fullGraphBtn) {
      fullGraphBtn.href = `/graph-explorer?repo_id=${repoParam}&mode=full`;
    }
    if (explorerBtn) {
      explorerBtn.href = `/graph-explorer?repo_id=${repoParam}&mode=blast_radius&changed_files=${filesParam}`;
    }
  }

  updateModeButtons() {
    const btnBlast = document.getElementById("btn-graph-mode-blast");
    const btnFull = document.getElementById("btn-graph-mode-full");
    if (btnBlast && btnFull) {
      if (this.currentMode === "full") {
        btnFull.className = "btn btn-sm btn-primary active";
        btnBlast.className = "btn btn-sm btn-secondary";
      } else {
        btnBlast.className = "btn btn-sm btn-primary active";
        btnFull.className = "btn btn-sm btn-secondary";
      }
    }
  }

  renderConnectionBanner(statusData) {
    const banner = document.getElementById("graph-connection-banner");
    if (!banner) return;

    const isOnline = statusData && statusData.connected === true;
    if (isOnline) {
      banner.className = "graph-status-alert alert-online";
      banner.innerHTML = `
        <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span class="status-indicator-dot dot-online"></span>
            <div>
              <span class="font-bold">Neo4j Database Connected</span>
              <span class="text-xs text-muted" style="margin-left: 8px;">(${Utils.escapeHtml(statusData.database || 'graphdoc')} @ ${Utils.escapeHtml(statusData.uri || 'bolt://localhost:7687')})</span>
            </div>
          </div>
          <div style="display: flex; gap: 1rem;" class="text-xs font-mono">
            <span>Nodes: <strong>${statusData.node_count || 0}</strong></span>
            <span>Edges: <strong>${statusData.edge_count || 0}</strong></span>
            <span class="status-pill badge-healthy">ONLINE</span>
          </div>
        </div>
      `;
    } else {
      banner.className = "graph-status-alert alert-degraded";
      banner.innerHTML = `
        <div style="display: flex; align-items: flex-start; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
          <div style="display: flex; align-items: flex-start; gap: 0.75rem;">
            <span class="status-indicator-dot dot-degraded" style="margin-top: 4px;"></span>
            <div>
              <div class="font-bold text-warning">DEGRADED / TREE-SITTER AST FALLBACK ACTIVE</div>
              <p class="text-xs text-muted" style="margin-top: 2px; max-width: 650px;">
                Neo4j service is currently OFFLINE at <code>${Utils.escapeHtml(statusData.uri || 'bolt://localhost:7687')}</code>.
                Falling back to authentic local Tree-Sitter AST parsing for symbol call hierarchies and blast radius calculations.
              </p>
            </div>
          </div>
          <div style="display: flex; align-items: center; gap: 0.75rem;">
            <span class="status-pill badge-degraded">AST FALLBACK</span>
            <span class="text-xs font-mono text-muted">Zero Hallucination</span>
          </div>
        </div>
      `;
    }
  }

  async loadFullArchitectureGraph() {
    this.currentMode = "full";
    this.updateModeButtons();
    const spinner = document.getElementById("graph-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const expResult = await api.getGraphExplorer({ repo_id: this.currentRepo, mode: "full" });
      this.currentGraphData = expResult;
      this.updateExternalLinks();

      const connBanner = document.getElementById("graph-connection-banner");
      if (connBanner) {
        connBanner.className = "graph-status-alert alert-online";
        const nodesCount = expResult.nodes_count || (Array.isArray(expResult.elements) ? expResult.elements.filter(e => !e.data?.source).length : 0);
        const edgesCount = expResult.edges_count || (Array.isArray(expResult.elements) ? expResult.elements.filter(e => e.data?.source).length : 0);
        connBanner.innerHTML = `
          <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.75rem;">
            <div style="display: flex; align-items: center; gap: 0.75rem;">
              <span class="status-indicator-dot dot-online"></span>
              <div>
                <span class="font-bold">Full Repository Architecture</span>
                <span class="text-xs text-muted" style="margin-left: 8px;">(${Utils.escapeHtml(this.currentRepo)} &bull; ${Utils.escapeHtml(expResult.execution_engine || 'AST Architecture Engine')})</span>
              </div>
            </div>
            <div style="display: flex; gap: 1rem;" class="text-xs font-mono">
              <span>Nodes: <strong>${nodesCount}</strong></span>
              <span>Edges: <strong>${edgesCount}</strong></span>
              <span class="status-pill badge-healthy">FULL ARCHITECTURE</span>
            </div>
          </div>
        `;
      }

      // Render summary
      const summaryContainer = document.getElementById("graph-blast-summary-container");
      if (summaryContainer) {
        summaryContainer.innerHTML = `
          <div class="blast-summary-pills">
            <div class="blast-pill blast-changed">
              <span class="blast-pill-count">${expResult.nodes_count || (Array.isArray(expResult.elements) ? expResult.elements.filter(e => !e.data?.source).length : 0)}</span>
              <span class="blast-pill-label">Total Code Entities</span>
            </div>
            <div class="blast-pill blast-affected">
              <span class="blast-pill-count">${expResult.edges_count || (Array.isArray(expResult.elements) ? expResult.elements.filter(e => e.data?.source).length : 0)}</span>
              <span class="blast-pill-label">AST Relationships</span>
            </div>
          </div>
          <div class="callout-note text-xs" style="margin-top: 0.75rem;">
            Displaying full repository dependency architecture. Use search, type filters, and zoom controls to inspect modules, functions, classes, and call hierarchies.
          </div>
        `;
      }

      this.renderGraphImpactScoreCard(expResult.graph_impact_score || expResult.blast_radius_summary?.graph_impact_score);
      this.renderCytoscapeGraph(expResult);
      Utils.showToast("Loaded full repository architecture", "success", 2000);
    } catch (err) {
      console.error("Failed to load full architecture graph:", err);
      Utils.showToast("Failed to load full architecture: " + err.message, "error", 4000);
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  async runBlastRadiusAnalysis(files) {
    this.currentMode = "blast_radius";
    this.updateModeButtons();
    const spinner = document.getElementById("graph-loading-indicator");
    if (spinner) spinner.style.display = "inline-block";

    try {
      const payload = {
        repo_id: this.currentRepo,
        changed_files: files
      };

      const result = await api.analyzeBlastRadius(payload);
      this.currentGraphData = result;
      this.updateExternalLinks();

      this.renderGraphImpactScoreCard(result.graph_impact_score || result.blast_radius_summary?.graph_impact_score);
      this.renderBlastRadiusSummary(result);
      this.renderCytoscapeGraph(result);
      Utils.showToast("Graph dependency analysis updated", "info", 2000);
    } catch (err) {
      console.warn("Blast radius API call degraded:", err);
      // Try explorer fallback
      try {
        const expResult = await api.getGraphExplorer({
          repo_id: this.currentRepo,
          mode: "blast_radius",
          changed_files: files.join(",")
        });
        this.currentGraphData = expResult;
        this.updateExternalLinks();
        this.renderGraphImpactScoreCard(expResult.graph_impact_score || expResult.blast_radius_summary?.graph_impact_score);
        this.renderBlastRadiusSummary(expResult);
        this.renderCytoscapeGraph(expResult);
      } catch (expErr) {
        console.error("All graph endpoints failed:", expErr);
        this.renderFallbackEmptyState(err.message);
      }
    } finally {
      if (spinner) spinner.style.display = "none";
    }
  }

  renderGraphImpactScoreCard(impactScore) {
    const scoreValEl = document.getElementById("gis-score-value");
    const levelBadge = document.getElementById("gis-tier-badge");
    const descEl = document.getElementById("gis-score-desc");
    const callersEl = document.getElementById("gis-callers-count");
    const depthEl = document.getElementById("gis-depth-val");
    const testingEl = document.getElementById("gis-testing-val");
    const barEl = document.getElementById("gis-score-bar");

    const validScore = impactScore && typeof impactScore.score === "number" ? impactScore.score :
      (impactScore && typeof impactScore.total_score === "number" ? impactScore.total_score : null);

    if (validScore === null) {
      if (scoreValEl) {
        scoreValEl.textContent = "N/A";
        scoreValEl.style.color = "var(--text-muted, #94a3b8)";
      }
      if (levelBadge) {
        levelBadge.className = "status-pill badge-neutral";
        levelBadge.textContent = "UNAVAILABLE";
      }
      if (descEl) descEl.textContent = "Insufficient structural AST/graph evidence to compute GIS.";
      if (callersEl) callersEl.textContent = String(this.currentGraphData?.blast_radius_count ?? 0);
      if (depthEl) depthEl.textContent = "—";
      if (testingEl) testingEl.textContent = "—";
      if (barEl) {
        barEl.style.width = "0%";
        barEl.style.backgroundColor = "var(--border-subtle, #334155)";
      }
      return;
    }

    const score = validScore;
    const scoreFormatted = score.toFixed(1);

    let tier = impactScore.impact_level || "LOW";
    if (tier === "UNKNOWN" || !tier) {
      tier = score >= 65 ? "HIGH" : (score >= 35 ? "MODERATE" : "LOW");
    }

    let badgeClass = "badge-healthy";
    let scoreColor = "var(--risk-green, #10b981)";
    if (tier === "HIGH" || tier === "CRITICAL" || score >= 65) {
      badgeClass = "badge-unhealthy";
      scoreColor = "var(--risk-red, #ef4444)";
    } else if (tier === "MODERATE" || score >= 35) {
      badgeClass = "badge-degraded";
      scoreColor = "var(--risk-yellow, #f59e0b)";
    }

    if (scoreValEl) {
      scoreValEl.textContent = scoreFormatted;
      scoreValEl.style.color = scoreColor;
    }
    if (levelBadge) {
      levelBadge.className = `status-pill ${badgeClass}`;
      levelBadge.textContent = `${tier} STRUCTURAL RISK`;
    }
    if (barEl) {
      barEl.style.width = Math.min(100, Math.max(5, score)) + "%";
      barEl.style.backgroundColor = scoreColor;
    }

    const metrics = impactScore.metrics || {};
    if (callersEl) callersEl.textContent = metrics.downstream_callers_count ?? (this.currentGraphData?.blast_radius_count || 0);
    if (depthEl) depthEl.textContent = metrics.max_dependency_depth ?? "1";
    if (testingEl) testingEl.textContent = metrics.affected_test_files_count ?? "0";

    if (descEl) {
      descEl.textContent = `Structural blast radius impact: ${metrics.downstream_callers_count || 0} downstream caller(s), depth ${metrics.max_dependency_depth || 1}.`;
    }
  }

  renderBlastRadiusSummary(data) {
    const container = document.getElementById("graph-blast-summary-container");
    if (!container) return;

    const count = data.blast_radius_count || 0;
    const affected = data.affected_files || [];
    const changed = data.changed_files || [];

    let html = `
      <div class="blast-summary-pills">
        <div class="blast-pill blast-changed">
          <span class="blast-pill-count">${changed.length}</span>
          <span class="blast-pill-label">Directly Modified File(s)</span>
        </div>
        <div class="blast-pill blast-affected">
          <span class="blast-pill-count">${count}</span>
          <span class="blast-pill-label">Transitive Blast Radius</span>
        </div>
      </div>
      <div class="affected-files-list" style="margin-top: 0.75rem;">
        <span class="text-xs text-muted font-semibold uppercase">Impacted Code Entities:</span>
        <ul class="clean-list" style="margin-top: 0.35rem;">
    `;

    if (affected.length === 0) {
      html += `<li class="text-xs text-muted">No external downstream callers or tests affected.</li>`;
    } else {
      affected.slice(0, 8).forEach(item => {
        const filePath = typeof item === "string" ? item : (item.file_path || item.name || "unknown");
        const reason = typeof item === "object" && item.reason ? ` &mdash; <span class="text-secondary">${Utils.escapeHtml(item.reason)}</span>` : "";
        const isTest = filePath.includes("test_") || filePath.includes("/tests/");
        html += `
          <li class="affected-file-item" style="margin-bottom: 4px;">
            <span class="entity-type-badge ${isTest ? 'type-test' : 'type-file'}">${isTest ? 'TEST' : 'FILE'}</span>
            <span class="font-mono text-xs font-semibold">${Utils.escapeHtml(filePath)}</span>
            <span class="text-xs">${reason}</span>
          </li>
        `;
      });
    }

    html += `
        </ul>
      </div>
    `;

    container.innerHTML = html;
  }

  renderCytoscapeGraph(data) {
    const container = document.getElementById("cy-container");
    if (!container) return;

    if (typeof window.cytoscape === "undefined") {
      container.innerHTML = `<div class="empty-state-notice">Cytoscape visualization library loading...</div>`;
      return;
    }

    // Build elements from data.elements or data.graph_elements
    let elements = [];
    if (Array.isArray(data.elements)) {
      elements = data.elements;
    } else if (data.elements && (data.elements.nodes || data.elements.edges)) {
      elements = [
        ...(data.elements.nodes || []),
        ...(data.elements.edges || [])
      ];
    } else if (Array.isArray(data.graph_elements) && data.graph_elements.length > 0) {
      elements = data.graph_elements;
    } else if (data.ast_relationships && data.ast_relationships.length > 0) {
      const cyNodes = {};
      const cyEdges = [];
      data.ast_relationships.forEach((rel, i) => {
        const callerId = `node_${rel.caller}`;
        const targetId = `node_${rel.target}`;
        if (!cyNodes[callerId]) {
          cyNodes[callerId] = { data: { id: callerId, label: rel.caller, type: "FUNCTION", file_path: rel.caller_file, state: "AFFECTED" } };
        }
        if (!cyNodes[targetId]) {
          cyNodes[targetId] = { data: { id: targetId, label: rel.target, type: "FUNCTION", file_path: rel.target_file, state: "CHANGED" } };
        }
        cyEdges.push({ data: { id: `edge_${i}`, source: callerId, target: targetId, type: rel.relationship || "CALLS" } });
      });
      elements = [...Object.values(cyNodes), ...cyEdges];
    } else {
      // Changed files only
      const changed = data.changed_files || this.changedFiles;
      elements = changed.map((cf, idx) => ({
        data: {
          id: `changed_file_${idx}`,
          label: cf.split("/").pop(),
          name: cf.split("/").pop(),
          type: "FILE",
          file_path: cf,
          state: "CHANGED",
          is_changed: true,
          in_degree: 0,
          out_degree: 0
        }
      }));
    }

    if (this.cy) {
      try {
        this.cy.destroy();
      } catch (e) {
        console.warn("Cytoscape destroy:", e);
      }
    }

    const isDark = document.body.classList.contains("dark-theme");

    this.cy = window.cytoscape({
      container,
      elements,
      boxSelectionEnabled: false,
      autounselectify: false,
      style: [
        {
          selector: 'node',
          style: {
            'content': 'data(label)',
            'font-size': '11px',
            'font-family': 'Inter, sans-serif',
            'text-valign': 'center',
            'text-halign': 'center',
            'color': isDark ? '#f8fafc' : '#0f172a',
            'background-color': '#334155',
            'border-width': 2,
            'border-color': '#64748b',
            'width': 44,
            'height': 44,
            'text-outline-width': 2,
            'text-outline-color': isDark ? '#0f172a' : '#ffffff',
            'transition-property': 'background-color, border-color, width, height',
            'transition-duration': '0.2s'
          }
        },
        {
          selector: 'node[type = "FILE"]',
          style: {
            'shape': 'round-rectangle',
            'width': 64,
            'height': 36,
            'background-color': '#1e293b',
            'border-color': '#38bdf8'
          }
        },
        {
          selector: 'node[type = "FUNCTION"]',
          style: {
            'shape': 'ellipse',
            'background-color': '#0f766e',
            'border-color': '#14b8a6'
          }
        },
        {
          selector: 'node[type = "CLASS"]',
          style: {
            'shape': 'diamond',
            'width': 50,
            'height': 50,
            'background-color': '#4338ca',
            'border-color': '#6366f1'
          }
        },
        {
          selector: 'node[type = "TEST"]',
          style: {
            'shape': 'hexagon',
            'background-color': '#065f46',
            'border-color': '#10b981'
          }
        },
        {
          selector: 'node.changed, node[is_changed = true], node[state = "CHANGED"]',
          style: {
            'border-color': '#ef4444',
            'border-width': 4,
            'background-color': '#7f1d1d',
            'color': '#fee2e2'
          }
        },
        {
          selector: 'node.blast-affected, node[is_affected = true], node[state = "AFFECTED"]',
          style: {
            'border-color': '#f59e0b',
            'border-width': 3,
            'background-color': '#78350f'
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-color': '#6366f1',
            'border-width': 5,
            'shadow-blur': 12,
            'shadow-color': '#6366f1',
            'shadow-opacity': 0.8
          }
        },
        {
          selector: 'edge',
          style: {
            'curve-style': 'bezier',
            'target-arrow-shape': 'triangle',
            'width': 1.5,
            'line-color': isDark ? '#475569' : '#cbd5e1',
            'target-arrow-color': isDark ? '#64748b' : '#94a3b8',
            'arrow-scale': 1.1,
            'opacity': 0.8
          }
        },
        {
          selector: 'edge[type = "CALLS"]',
          style: {
            'line-color': '#38bdf8',
            'target-arrow-color': '#38bdf8',
            'width': 2
          }
        },
        {
          selector: 'edge[type = "CONTAINS"]',
          style: {
            'line-style': 'dashed',
            'line-color': '#64748b',
            'target-arrow-color': '#64748b'
          }
        },
        {
          selector: 'edge[type = "IMPORTS"]',
          style: {
            'line-color': '#a855f7',
            'target-arrow-color': '#a855f7'
          }
        }
      ],
      layout: {
        name: this.activeLayout,
        animate: true,
        animationDuration: 500,
        fit: true,
        padding: 30
      }
    });

    // Node click handler for Node Inspector
    this.cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      this.selectedNode = node;
      this.renderNodeInspector(node);
    });

    // Background tap clears selection
    this.cy.on('tap', (evt) => {
      if (evt.target === this.cy) {
        this.selectedNode = null;
        this.clearNodeInspector();
      }
    });
  }

  renderNodeInspector(node) {
    const inspector = document.getElementById("graph-node-inspector-content");
    if (!inspector) return;

    const d = node.data();
    const isDark = document.body.classList.contains("dark-theme");

    const inEdges = node.incomers('edge');
    const outEdges = node.outgoers('edge');

    inspector.innerHTML = `
      <div class="node-inspector-card">
        <div class="inspector-header-row">
          <span class="status-pill ${d.type === 'TEST' ? 'badge-healthy' : (d.type === 'FILE' ? 'badge-info' : 'badge-neutral')}">${d.type || 'NODE'}</span>
          <span class="font-mono text-xs ${d.state === 'CHANGED' ? 'text-danger' : 'text-accent'}">${d.state || 'NOMINAL'}</span>
        </div>
        <h4 class="font-bold text-base" style="margin: 0.5rem 0 0.25rem 0;">${Utils.escapeHtml(d.name || d.label || d.id)}</h4>
        <div class="font-mono text-xs text-muted" style="word-break: break-all;">${Utils.escapeHtml(d.file_path || 'Repository root')}</div>

        <div class="inspector-metrics-grid" style="margin-top: 1rem;">
          <div class="stat-mini">
            <span class="stat-mini-label">Incoming Callers</span>
            <span class="stat-mini-val font-mono">${inEdges.length}</span>
          </div>
          <div class="stat-mini">
            <span class="stat-mini-label">Outgoing Calls</span>
            <span class="stat-mini-val font-mono">${outEdges.length}</span>
          </div>
          <div class="stat-mini">
            <span class="stat-mini-label">High Fan-In</span>
            <span class="stat-mini-val font-mono">${inEdges.length >= 3 ? 'YES' : 'NO'}</span>
          </div>
        </div>

        <div style="margin-top: 1rem;">
          <button type="button" class="btn btn-secondary btn-sm" id="btn-inspect-subgraph" style="width: 100%;">
            Highlight Neighborhood
          </button>
        </div>
      </div>
    `;

    const btnSub = document.getElementById("btn-inspect-subgraph");
    if (btnSub) {
      btnSub.onclick = () => {
        if (this.cy) {
          const neighborhood = node.neighborhood().add(node);
          this.cy.elements().removeClass('highlighted');
          neighborhood.addClass('highlighted');
          this.cy.fit(neighborhood, 50);
        }
      };
    }
  }

  clearNodeInspector() {
    const inspector = document.getElementById("graph-node-inspector-content");
    if (!inspector) return;
    inspector.innerHTML = `
      <div class="text-xs text-muted text-center" style="padding: 2rem 1rem;">
        Click any node or relationship on the Cytoscape canvas to inspect symbol properties, call hierarchy, and blast radius.
      </div>
    `;
    if (this.cy) {
      this.cy.elements().removeClass('highlighted');
    }
  }

  searchNodes(query) {
    if (!this.cy || !query) {
      if (this.cy) this.cy.elements().removeClass('highlighted');
      return;
    }
    const q = query.toLowerCase();
    const matched = this.cy.nodes().filter(node => {
      const label = (node.data('label') || '').toLowerCase();
      const file = (node.data('file_path') || '').toLowerCase();
      return label.includes(q) || file.includes(q);
    });

    this.cy.elements().removeClass('highlighted');
    if (matched.length > 0) {
      matched.addClass('highlighted');
      this.cy.fit(matched, 80);
    }
  }

  applyFilter(type) {
    if (!this.cy) return;
    if (type === "ALL") {
      this.cy.elements().show();
    } else {
      this.cy.nodes().forEach(node => {
        if (node.data('type') === type) {
          node.show();
        } else {
          node.hide();
        }
      });
      // Show connecting edges where both ends are visible
      this.cy.edges().forEach(edge => {
        if (edge.source().visible() && edge.target().visible()) {
          edge.show();
        } else {
          edge.hide();
        }
      });
    }
  }

  applyLayout(layoutName) {
    if (!this.cy) return;
    const layout = this.cy.layout({
      name: layoutName,
      animate: true,
      animationDuration: 500,
      fit: true,
      padding: 30
    });
    layout.run();
  }

  renderFallbackEmptyState(msg) {
    const container = document.getElementById("cy-container");
    if (container) {
      container.innerHTML = `
        <div class="empty-state-card" style="margin: 2rem auto; max-width: 500px;">
          <h4 class="empty-title">Graph Intelligence Offline</h4>
          <p class="empty-desc text-xs text-muted">${Utils.escapeHtml(msg || 'No graph relationships available.')}</p>
        </div>
      `;
    }
  }
}

export const graphIntelController = new GraphIntelController();

