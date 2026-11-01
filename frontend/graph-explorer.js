/**
 * frontend/graph-explorer.js
 * Dedicated Full-Screen Interactive Neo4j Code Graph Explorer
 * Integrates with FastAPI /api/metadata/graph/explorer
 */

(function () {
  "use strict";

  // State
  let cy = null;
  let rawGraphData = null;
  let activeRepo = "msiemens/tinydb";
  let activeMode = "blast_radius"; // 'blast_radius' or 'full'
  let activeChangedFiles = "tinydb/storages.py";
  let activeRunId = null;
  let searchMatches = [];
  let currentSearchIdx = 0;

  // DOM Elements
  const cyCanvas = document.getElementById("cyGraphCanvas");
  const loadingOverlay = document.getElementById("loadingOverlay");
  const loadingMsg = document.getElementById("loadingMsg");
  const loadingSub = document.getElementById("loadingSub");
  const selectRepo = document.getElementById("selectRepo");
  const inputChangedFiles = document.getElementById("inputChangedFiles");
  const btnApplyRepo = document.getElementById("btnApplyRepo");
  const btnModeBlast = document.getElementById("btnModeBlast");
  const btnModeFull = document.getElementById("btnModeFull");
  const headerNodeCount = document.getElementById("headerNodeCount");
  const headerEdgeCount = document.getElementById("headerEdgeCount");

  const graphSearchInput = document.getElementById("graphSearchInput");
  const btnSearchClear = document.getElementById("btnSearchClear");
  const searchMatchCount = document.getElementById("searchMatchCount");
  const btnSearchPrev = document.getElementById("btnSearchPrev");
  const btnSearchNext = document.getElementById("btnSearchNext");

  const selectLayout = document.getElementById("selectLayout");
  const btnFitScreen = document.getElementById("btnFitScreen");
  const btnZoomIn = document.getElementById("btnZoomIn");
  const btnZoomOut = document.getElementById("btnZoomOut");
  const btnResetLayout = document.getElementById("btnResetLayout");
  const floatFit = document.getElementById("floatFit");
  const floatZoomIn = document.getElementById("floatZoomIn");
  const floatZoomOut = document.getElementById("floatZoomOut");
  const floatReset = document.getElementById("floatReset");

  const btnToggleFilters = document.getElementById("btnToggleFilters");
  const filterDrawer = document.getElementById("filterDrawer");
  const chkNodeFile = document.getElementById("chkNodeFile");
  const chkNodeFunction = document.getElementById("chkNodeFunction");
  const chkNodeClass = document.getElementById("chkNodeClass");
  const chkEdgeCalls = document.getElementById("chkEdgeCalls");
  const chkEdgeContains = document.getElementById("chkEdgeContains");
  const chkEdgeImports = document.getElementById("chkEdgeImports");
  const btnResetFilters = document.getElementById("btnResetFilters");

  const sideInspector = document.getElementById("sideInspector");
  const inspectorTitle = document.getElementById("inspectorTitle");
  const inspectorContent = document.getElementById("inspectorContent");
  const btnCloseInspector = document.getElementById("btnCloseInspector");
  const btnToggleInspector = document.getElementById("btnToggleInspector");
  const canvasLegend = document.getElementById("canvasLegend");

  // Read URL query parameters
  function initFromUrlParams() {
    const params = new URLSearchParams(window.location.search);
    if (params.has("repo_id")) activeRepo = params.get("repo_id");
    if (params.has("mode")) activeMode = params.get("mode");
    if (params.has("changed_files")) activeChangedFiles = params.get("changed_files");
    if (params.has("run_id")) activeRunId = params.get("run_id");

    if (selectRepo) selectRepo.value = activeRepo;
    if (inputChangedFiles) inputChangedFiles.value = activeChangedFiles;
    updateModeButtons();
  }

  function updateModeButtons() {
    if (btnModeBlast && btnModeFull) {
      if (activeMode === "blast_radius") {
        btnModeBlast.classList.add("active");
        btnModeFull.classList.remove("active");
      } else {
        btnModeFull.classList.add("active");
        btnModeBlast.classList.remove("active");
      }
    }
  }

  // Sync URL state without page reload
  function syncUrlState() {
    const params = new URLSearchParams();
    if (activeRepo) params.set("repo_id", activeRepo);
    if (activeMode) params.set("mode", activeMode);
    if (activeChangedFiles) params.set("changed_files", activeChangedFiles);
    if (activeRunId) params.set("run_id", activeRunId);
    const newUrl = `${window.location.pathname}?${params.toString()}`;
    window.history.replaceState({}, "", newUrl);
  }

  // Cytoscape Style Definitions
  const cyStyle = [
    // Base Node Styles
    {
      selector: "node",
      style: {
        "label": "data(label)",
        "color": "#f1f5f9",
        "font-family": "Inter, sans-serif",
        "font-size": "11px",
        "font-weight": "500",
        "text-valign": "bottom",
        "text-margin-y": 5,
        "text-outline-color": "#06090e",
        "text-outline-width": 2,
        "transition-property": "opacity, background-color, border-color, border-width, width, height",
        "transition-duration": "0.15s",
      },
    },
    // File Nodes
    {
      selector: "node[type = 'File']",
      style: {
        "shape": "roundrectangle",
        "background-color": "#1e293b",
        "border-color": "#38bdf8",
        "border-width": 2,
        "width": 86,
        "height": 30,
      },
    },
    // Function Nodes
    {
      selector: "node[type = 'Function']",
      style: {
        "shape": "ellipse",
        "background-color": "#0f172a",
        "border-color": "#818cf8",
        "border-width": 2,
        "width": 38,
        "height": 38,
      },
    },
    // Class Nodes
    {
      selector: "node[type = 'Class']",
      style: {
        "shape": "diamond",
        "background-color": "#0f291e",
        "border-color": "#34d399",
        "border-width": 2,
        "width": 42,
        "height": 42,
      },
    },
    // Module Nodes
    {
      selector: "node[type = 'Module']",
      style: {
        "shape": "roundrectangle",
        "background-color": "#2e1065",
        "border-color": "#a78bfa",
        "border-width": 2,
        "width": 90,
        "height": 28,
      },
    },
    // Changed (Origin) Status
    {
      selector: "node[status = 'changed']",
      style: {
        "border-color": "#ef4444",
        "border-width": 3,
        "background-color": "rgba(239, 68, 68, 0.35)",
        "underlay-color": "#ef4444",
        "underlay-padding": 3,
        "underlay-opacity": 0.25,
      },
    },
    // Affected (Blast Radius) Status
    {
      selector: "node[status = 'affected']",
      style: {
        "border-color": "#f59e0b",
        "border-width": 3,
        "background-color": "rgba(245, 158, 11, 0.35)",
        "underlay-color": "#f59e0b",
        "underlay-padding": 3,
        "underlay-opacity": 0.25,
      },
    },
    // Selected Node State
    {
      selector: "node:selected",
      style: {
        "border-color": "#38bdf8",
        "border-width": 4,
        "underlay-color": "#38bdf8",
        "underlay-padding": 6,
        "underlay-opacity": 0.45,
      },
    },
    // Search Matched Nodes
    {
      selector: "node.search-matched",
      style: {
        "border-color": "#38bdf8",
        "border-width": 4,
        "underlay-color": "#38bdf8",
        "underlay-padding": 8,
        "underlay-opacity": 0.6,
      },
    },
    // Dimmed Nodes & Edges (When a node is inspected or search active)
    {
      selector: "node.dimmed",
      style: {
        "opacity": 0.15,
      },
    },
    {
      selector: "edge.dimmed",
      style: {
        "opacity": 0.1,
      },
    },
    // Edge Styles
    {
      selector: "edge",
      style: {
        "curve-style": "bezier",
        "font-family": "JetBrains Mono, monospace",
        "font-size": "8px",
        "color": "#94a3b8",
        "text-rotation": "autorotate",
        "text-background-opacity": 0.7,
        "text-background-color": "#06090e",
        "text-background-padding": 2,
        "transition-property": "opacity, width, line-color",
        "transition-duration": "0.15s",
      },
    },
    // CALLS Relationships
    {
      selector: "edge[type = 'CALLS']",
      style: {
        "width": 2.2,
        "line-color": "#f59e0b",
        "target-arrow-color": "#f59e0b",
        "target-arrow-shape": "triangle",
        "label": "calls",
      },
    },
    // CONTAINS Relationships
    {
      selector: "edge[type = 'CONTAINS']",
      style: {
        "width": 1.4,
        "line-color": "#475569",
        "target-arrow-color": "#475569",
        "target-arrow-shape": "circle",
        "label": "defines",
      },
    },
    // IMPORTS Relationships
    {
      selector: "edge[type = 'IMPORTS']",
      style: {
        "width": 1.4,
        "line-color": "#38bdf8",
        "line-style": "dashed",
        "target-arrow-color": "#38bdf8",
        "target-arrow-shape": "triangle",
        "label": "imports",
      },
    },
    // Edge Highlight
    {
      selector: "edge.highlighted",
      style: {
        "width": 3.5,
        "opacity": 1,
      },
    },
  ];

  // Helper: Get layout config
  function getLayoutOptions(layoutName) {
    switch (layoutName) {
      case "cose":
        return {
          name: "cose",
          animate: true,
          refresh: 20,
          idealEdgeLength: 90,
          nodeOverlap: 25,
          padding: 40,
          randomize: false,
          componentSpacing: 100,
        };
      case "concentric":
        return {
          name: "concentric",
          padding: 40,
          minNodeSpacing: 50,
        };
      case "circle":
        return {
          name: "circle",
          padding: 40,
        };
      case "breadthfirst":
      default:
        return {
          name: "breadthfirst",
          directed: true,
          padding: 40,
          spacingFactor: 1.3,
        };
    }
  }

  // Load and render graph data from API
  async function loadGraphData() {
    showLoading(true, "Querying Neo4j Knowledge Graph...", `Target Repository: ${activeRepo} (${activeMode.toUpperCase()})`);

    const params = new URLSearchParams();
    params.set("repo_id", activeRepo);
    params.set("mode", activeMode);
    if (activeChangedFiles) params.set("changed_files", activeChangedFiles);
    if (activeRunId) params.set("run_id", activeRunId);

    try {
      const resp = await fetch(`/api/metadata/graph/explorer?${params.toString()}`);
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `Server returned ${resp.status}`);
      }

      rawGraphData = await resp.json();
      renderGraph(rawGraphData);
      updateRepoDropdown(rawGraphData.available_repositories || []);
      syncUrlState();
    } catch (exc) {
      showErrorState(`Failed to load graph data: ${exc.message}`);
    } finally {
      showLoading(false);
    }
  }

  // Render elements in Cytoscape canvas
  function renderGraph(data) {
    const elements = data.elements || [];
    const nodeCount = data.nodes_count || 0;
    const edgeCount = data.edges_count || 0;

    if (headerNodeCount) headerNodeCount.textContent = nodeCount;
    if (headerEdgeCount) headerEdgeCount.textContent = edgeCount;

    if (!cy) {
      cy = cytoscape({
        container: cyCanvas,
        elements: elements,
        style: cyStyle,
        layout: getLayoutOptions(selectLayout ? selectLayout.value : "breadthfirst"),
        wheelSensitivity: 0.25,
        minZoom: 0.1,
        maxZoom: 4.0,
      });

      setupCyEventHandlers();
    } else {
      cy.elements().remove();
      cy.add(elements);
      applyFilterVisibility();
      runLayout();
    }

    renderDefaultInspector(data);
  }

  function runLayout() {
    if (!cy) return;
    const layoutName = selectLayout ? selectLayout.value : "breadthfirst";
    const layout = cy.layout(getLayoutOptions(layoutName));
    layout.run();
    cy.fit(undefined, 35);
  }

  // Event Handlers for Cytoscape Canvas & Elements
  function setupCyEventHandlers() {
    if (!cy) return;

    // Node Click -> Inspect Node
    cy.on("tap", "node", function (evt) {
      const node = evt.target;
      inspectNode(node);
    });

    // Background Click -> Deselect and show Default Overview
    cy.on("tap", function (evt) {
      if (evt.target === cy) {
        clearHighlights();
        if (rawGraphData) renderDefaultInspector(rawGraphData);
      }
    });

    // Node Hover effects
    cy.on("mouseover", "node", function (evt) {
      document.body.style.cursor = "pointer";
    });
    cy.on("mouseout", "node", function (evt) {
      document.body.style.cursor = "default";
    });
  }

  // Highlight 1st-degree neighborhood and inspect node
  function inspectNode(node) {
    if (!node || !node.isNode()) return;

    clearHighlights();

    // Dim all elements not in neighborhood
    const neighborhood = node.neighborhood().add(node);
    cy.elements().not(neighborhood).addClass("dimmed");
    neighborhood.edges().addClass("highlighted");

    // Center and select
    node.select();

    // Populate Side Inspector Panel
    renderNodeInspector(node);
  }

  function clearHighlights() {
    if (!cy) return;
    cy.elements().removeClass("dimmed").removeClass("highlighted").removeClass("search-matched");
  }

  // Render Node Metadata in Inspector Panel
  function renderNodeInspector(node) {
    if (!inspectorContent) return;

    const data = node.data();
    const type = data.type || "Unknown";
    const status = data.status || "normal";
    const name = data.name || data.label || node.id();
    const filePath = data.rel_path || data.file_path || "N/A";
    const repo = data.repo_id || activeRepo;

    // Relationships
    const inEdges = node.incomers("edge");
    const outEdges = node.outgoers("edge");

    let statusTagClass = "normal";
    let statusText = "Normal Component";
    if (status === "changed") {
      statusTagClass = "changed";
      statusText = "Changed File / Origin";
    } else if (status === "affected") {
      statusTagClass = "affected";
      statusText = "Blast Radius Affected";
    }

    if (inspectorTitle) inspectorTitle.textContent = `${type}: ${name}`;

    let inHtml = "";
    if (inEdges.length === 0) {
      inHtml = `<p style="font-size:0.72rem; color:var(--text-dim); padding:0.25rem 0;">No incoming relationships.</p>`;
    } else {
      inHtml = inEdges
        .map((edge) => {
          const src = edge.source();
          const relType = edge.data("type") || "CALLS";
          return `
          <div class="rel-item" data-node-id="${src.id()}" title="Click to navigate to ${src.data("name") || src.id()}">
            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:170px;">
              ${src.data("label") || src.data("name") || src.id()}
            </span>
            <span class="rel-badge ${relType.toLowerCase()}">${relType.toLowerCase()}</span>
          </div>`;
        })
        .join("");
    }

    let outHtml = "";
    if (outEdges.length === 0) {
      outHtml = `<p style="font-size:0.72rem; color:var(--text-dim); padding:0.25rem 0;">No outgoing relationships.</p>`;
    } else {
      outHtml = outEdges
        .map((edge) => {
          const tgt = edge.target();
          const relType = edge.data("type") || "CALLS";
          return `
          <div class="rel-item" data-node-id="${tgt.id()}" title="Click to navigate to ${tgt.data("name") || tgt.id()}">
            <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:170px;">
              ${tgt.data("label") || tgt.data("name") || tgt.id()}
            </span>
            <span class="rel-badge ${relType.toLowerCase()}">${relType.toLowerCase()}</span>
          </div>`;
        })
        .join("");
    }

    inspectorContent.innerHTML = `
      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Component Overview</span>
          <span class="badge-tag ${statusTagClass}">${statusText}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Node Type:</span>
          <span class="meta-val">${type}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Name:</span>
          <span class="meta-val">${name}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">File Path:</span>
          <span class="meta-val" title="${filePath}">${filePath}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Repository:</span>
          <span class="meta-val">${repo}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Connectivity:</span>
          <span class="meta-val">${inEdges.length} In / ${outEdges.length} Out</span>
        </div>
      </div>

      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Incoming Invocations (${inEdges.length})</span>
        </div>
        <div class="rel-list">${inHtml}</div>
      </div>

      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Outgoing Calls / Contains (${outEdges.length})</span>
        </div>
        <div class="rel-list">${outHtml}</div>
      </div>
    `;

    // Attach navigation click to connection items
    inspectorContent.querySelectorAll(".rel-item").forEach((el) => {
      el.addEventListener("click", () => {
        const targetId = el.getAttribute("data-node-id");
        if (targetId && cy) {
          const targetNode = cy.getElementById(targetId);
          if (targetNode && targetNode.length > 0) {
            cy.animate({
              center: { eles: targetNode },
              zoom: Math.max(cy.zoom(), 1.2),
              duration: 350,
            });
            inspectNode(targetNode);
          }
        }
      });
    });

    if (sideInspector) sideInspector.classList.remove("collapsed");
  }

  // Render Default Overview in Inspector Panel
  function renderDefaultInspector(data) {
    if (!inspectorContent) return;
    if (inspectorTitle) inspectorTitle.textContent = "Repository Architecture";

    const blast = data.blast_radius_summary || {};
    const stats = data.stats || {};
    const affected = blast.affected_files || [];

    let affectedHtml = "";
    if (affected.length === 0) {
      affectedHtml = `<p style="font-size:0.72rem; color:var(--text-dim); padding:0.25rem 0;">No affected caller modules detected (Isolated changes).</p>`;
    } else {
      affectedHtml = affected
        .slice(0, 10)
        .map(
          (af) => `
        <div class="rel-item" style="cursor:default;">
          <span style="color:#60a5fa; font-weight:600; overflow:hidden; text-overflow:ellipsis; max-width:180px;">${af.file_path || af}</span>
          <span class="rel-badge calls">${af.relationship_type || "CALLS"}</span>
        </div>`
        )
        .join("");
    }

    inspectorContent.innerHTML = `
      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Target Repository</span>
          <span class="badge-tag normal">${data.mode === "full" ? "Full Graph" : "Blast Radius"}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Repository:</span>
          <span class="meta-val">${data.repo_id}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Changed File:</span>
          <span class="meta-val">${Array.isArray(data.changed_files) ? data.changed_files.join(", ") : data.changed_files || "N/A"}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Engine:</span>
          <span class="meta-val">${blast.execution_engine || "Neo4j Knowledge Graph"}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Database:</span>
          <span class="meta-val" style="color:#34d399;">${blast.database_status || "ONLINE (graphdoc)"}</span>
        </div>
      </div>

      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Graph Metrics</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Total Nodes:</span>
          <span class="meta-val">${data.nodes_count || 0}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Files / Functions:</span>
          <span class="meta-val">${stats.files || 0} / ${stats.functions || 0}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Total Edges:</span>
          <span class="meta-val">${data.edges_count || 0}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">Affected Files:</span>
          <span class="meta-val" style="color:#f59e0b; font-weight:600;">${blast.affected_files_count || 0}</span>
        </div>
        <div class="meta-row">
          <span class="meta-label">AST Call Dependencies:</span>
          <span class="meta-val">${blast.ast_calls_count || 0}</span>
        </div>
      </div>

      <div class="inspector-card">
        <div class="card-title-sm">
          <span>Blast Radius Affected Callers</span>
        </div>
        <div class="rel-list">${affectedHtml}</div>
      </div>

      <div style="font-size:0.72rem; color:var(--text-dim); line-height:1.4; padding:0.25rem 0.5rem; background:rgba(30,41,59,0.3); border-radius:6px;">
        💡 <strong>Tip:</strong> Click on any node to inspect caller/callee relationships and navigate through the architecture.
      </div>
    `;
  }

  // Update repository options in dropdown
  function updateRepoDropdown(repos) {
    if (!selectRepo || !repos || repos.length === 0) return;
    const current = selectRepo.value;
    const repoIds = repos.map((r) => (typeof r === "string" ? r : r.repo_id));
    if (!repoIds.includes("msiemens/tinydb")) repoIds.unshift("msiemens/tinydb");
    if (!repoIds.includes("audit_test/repo_a")) repoIds.push("audit_test/repo_a");

    const html = repoIds
      .map((r) => `<option value="${r}" ${r === current ? "selected" : ""}>${r}</option>`)
      .join("");
    selectRepo.innerHTML = html;
  }

  // Search Functionality
  function handleSearch(query) {
    if (!cy) return;
    clearHighlights();

    if (!query || !query.trim()) {
      if (searchMatchCount) searchMatchCount.textContent = "";
      if (btnSearchClear) btnSearchClear.style.display = "none";
      if (btnSearchPrev) btnSearchPrev.style.display = "none";
      if (btnSearchNext) btnSearchNext.style.display = "none";
      searchMatches = [];
      return;
    }

    const q = query.trim().toLowerCase();
    if (btnSearchClear) btnSearchClear.style.display = "block";

    searchMatches = cy.nodes().filter((node) => {
      const data = node.data();
      const label = (data.label || "").toLowerCase();
      const name = (data.name || "").toLowerCase();
      const path = (data.rel_path || data.file_path || "").toLowerCase();
      const type = (data.type || "").toLowerCase();
      return label.includes(q) || name.includes(q) || path.includes(q) || type.includes(q);
    });

    const matchCount = searchMatches.length;
    if (searchMatchCount) {
      searchMatchCount.textContent = matchCount === 1 ? "1 match" : `${matchCount} matches`;
      searchMatchCount.style.color = matchCount > 0 ? "#38bdf8" : "#ef4444";
    }

    if (matchCount > 0) {
      currentSearchIdx = 0;
      cy.nodes().not(searchMatches).addClass("dimmed");
      searchMatches.addClass("search-matched");
      jumpToSearchMatch(currentSearchIdx);

      if (btnSearchPrev) btnSearchPrev.style.display = matchCount > 1 ? "inline-flex" : "none";
      if (btnSearchNext) btnSearchNext.style.display = matchCount > 1 ? "inline-flex" : "none";
    } else {
      if (btnSearchPrev) btnSearchPrev.style.display = "none";
      if (btnSearchNext) btnSearchNext.style.display = "none";
    }
  }

  function jumpToSearchMatch(idx) {
    if (!cy || searchMatches.length === 0) return;
    const target = searchMatches[idx];
    if (target) {
      cy.animate({
        center: { eles: target },
        zoom: Math.max(cy.zoom(), 1.3),
        duration: 300,
      });
      inspectNode(target);
    }
  }

  // Filter Toggle Handling
  function applyFilterVisibility() {
    if (!cy) return;
    const showFiles = chkNodeFile ? chkNodeFile.checked : true;
    const showFuncs = chkNodeFunction ? chkNodeFunction.checked : true;
    const showClasses = chkNodeClass ? chkNodeClass.checked : true;

    const showCalls = chkEdgeCalls ? chkEdgeCalls.checked : true;
    const showContains = chkEdgeContains ? chkEdgeContains.checked : true;
    const showImports = chkEdgeImports ? chkEdgeImports.checked : true;

    cy.batch(() => {
      cy.nodes().forEach((n) => {
        const type = n.data("type");
        if (type === "File") n.style("display", showFiles ? "element" : "none");
        else if (type === "Function") n.style("display", showFuncs ? "element" : "none");
        else if (type === "Class") n.style("display", showClasses ? "element" : "none");
      });

      cy.edges().forEach((e) => {
        const type = e.data("type");
        if (type === "CALLS") e.style("display", showCalls ? "element" : "none");
        else if (type === "CONTAINS") e.style("display", showContains ? "element" : "none");
        else if (type === "IMPORTS") e.style("display", showImports ? "element" : "none");
      });
    });
  }

  function resetFilters() {
    if (chkNodeFile) chkNodeFile.checked = true;
    if (chkNodeFunction) chkNodeFunction.checked = true;
    if (chkNodeClass) chkNodeClass.checked = true;
    if (chkEdgeCalls) chkEdgeCalls.checked = true;
    if (chkEdgeContains) chkEdgeContains.checked = true;
    if (chkEdgeImports) chkEdgeImports.checked = true;
    applyFilterVisibility();
  }

  // Overlays
  function showLoading(show, msg, sub) {
    if (!loadingOverlay) return;
    if (show) {
      loadingOverlay.style.display = "flex";
      if (loadingMsg && msg) loadingMsg.textContent = msg;
      if (loadingSub && sub) loadingSub.textContent = sub;
    } else {
      loadingOverlay.style.display = "none";
    }
  }

  function showErrorState(msg) {
    if (loadingOverlay) {
      loadingOverlay.style.display = "flex";
      if (loadingMsg) loadingMsg.textContent = "Error Loading Graph";
      if (loadingSub) {
        loadingSub.innerHTML = `
          <div style="color:#ef4444; margin-bottom:0.75rem;">${msg}</div>
          <button id="btnRetryGraph" class="btn-ctrl" style="width:auto; padding:0.35rem 0.8rem; font-size:0.75rem;">Retry Request</button>
        `;
        const retry = document.getElementById("btnRetryGraph");
        if (retry) retry.addEventListener("click", loadGraphData);
      }
    }
  }

  // Wire UI DOM Events
  function bindDomEvents() {
    // Mode Switcher
    if (btnModeBlast) {
      btnModeBlast.addEventListener("click", () => {
        if (activeMode !== "blast_radius") {
          activeMode = "blast_radius";
          updateModeButtons();
          loadGraphData();
        }
      });
    }

    if (btnModeFull) {
      btnModeFull.addEventListener("click", () => {
        if (activeMode !== "full") {
          activeMode = "full";
          updateModeButtons();
          loadGraphData();
        }
      });
    }

    // Repository Selection
    if (selectRepo) {
      selectRepo.addEventListener("change", () => {
        activeRepo = selectRepo.value;
        if (activeRepo.includes("demo-order-service") && inputChangedFiles) {
          inputChangedFiles.value = "src/validator.py";
          activeChangedFiles = "src/validator.py";
        } else if (activeRepo.includes("tinydb") && inputChangedFiles) {
          inputChangedFiles.value = "tinydb/storages.py";
          activeChangedFiles = "tinydb/storages.py";
        } else if (activeRepo.includes("repo_a") && inputChangedFiles) {
          inputChangedFiles.value = "src/file_b.py";
          activeChangedFiles = "src/file_b.py";
        }
        loadGraphData();
      });
    }

    if (btnApplyRepo) {
      btnApplyRepo.addEventListener("click", () => {
        activeRepo = selectRepo.value;
        if (inputChangedFiles) activeChangedFiles = inputChangedFiles.value;
        loadGraphData();
      });
    }

    // Search events
    if (graphSearchInput) {
      graphSearchInput.addEventListener("input", (e) => handleSearch(e.target.value));
      graphSearchInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          if (e.shiftKey) {
            if (searchMatches.length > 0) {
              currentSearchIdx = (currentSearchIdx - 1 + searchMatches.length) % searchMatches.length;
              jumpToSearchMatch(currentSearchIdx);
            }
          } else {
            if (searchMatches.length > 0) {
              currentSearchIdx = (currentSearchIdx + 1) % searchMatches.length;
              jumpToSearchMatch(currentSearchIdx);
            }
          }
        } else if (e.key === "Escape") {
          graphSearchInput.value = "";
          handleSearch("");
        }
      });
    }

    if (btnSearchClear) {
      btnSearchClear.addEventListener("click", () => {
        if (graphSearchInput) graphSearchInput.value = "";
        handleSearch("");
      });
    }

    if (btnSearchNext) {
      btnSearchNext.addEventListener("click", () => {
        if (searchMatches.length > 0) {
          currentSearchIdx = (currentSearchIdx + 1) % searchMatches.length;
          jumpToSearchMatch(currentSearchIdx);
        }
      });
    }

    if (btnSearchPrev) {
      btnSearchPrev.addEventListener("click", () => {
        if (searchMatches.length > 0) {
          currentSearchIdx = (currentSearchIdx - 1 + searchMatches.length) % searchMatches.length;
          jumpToSearchMatch(currentSearchIdx);
        }
      });
    }

    // Layout dropdown
    if (selectLayout) {
      selectLayout.addEventListener("change", runLayout);
    }

    // Zoom and Fit Controls
    const fitAction = () => cy && cy.fit(undefined, 35);
    const zoomInAction = () => cy && cy.zoom({ level: cy.zoom() * 1.25, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });
    const zoomOutAction = () => cy && cy.zoom({ level: cy.zoom() * 0.8, renderedPosition: { x: cy.width() / 2, y: cy.height() / 2 } });

    if (btnFitScreen) btnFitScreen.addEventListener("click", fitAction);
    if (floatFit) floatFit.addEventListener("click", fitAction);

    if (btnZoomIn) btnZoomIn.addEventListener("click", zoomInAction);
    if (floatZoomIn) floatZoomIn.addEventListener("click", zoomInAction);

    if (btnZoomOut) btnZoomOut.addEventListener("click", zoomOutAction);
    if (floatZoomOut) floatZoomOut.addEventListener("click", zoomOutAction);

    if (btnResetLayout) btnResetLayout.addEventListener("click", runLayout);
    if (floatReset) floatReset.addEventListener("click", runLayout);

    // Filter Controls
    if (btnToggleFilters && filterDrawer) {
      btnToggleFilters.addEventListener("click", () => {
        const isHidden = filterDrawer.style.display === "none";
        filterDrawer.style.display = isHidden ? "block" : "none";
      });
    }

    [chkNodeFile, chkNodeFunction, chkNodeClass, chkEdgeCalls, chkEdgeContains, chkEdgeImports].forEach((chk) => {
      if (chk) chk.addEventListener("change", applyFilterVisibility);
    });

    if (btnResetFilters) btnResetFilters.addEventListener("click", resetFilters);

    // Inspector Panel Toggle
    if (btnCloseInspector && sideInspector) {
      btnCloseInspector.addEventListener("click", () => {
        sideInspector.classList.add("collapsed");
        if (canvasLegend) canvasLegend.style.right = "1.25rem";
      });
    }

    if (btnToggleInspector && sideInspector) {
      btnToggleInspector.addEventListener("click", () => {
        const isCollapsed = sideInspector.classList.toggle("collapsed");
        if (canvasLegend) {
          canvasLegend.style.right = isCollapsed ? "1.25rem" : "calc(340px + 1.25rem)";
        }
      });
    }

    // Window Resize -> Re-fit Cytoscape
    window.addEventListener("resize", () => {
      if (cy) cy.resize();
    });

    // Keyboard Shortcuts
    window.addEventListener("keydown", (e) => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
      if (e.code === "Space") {
        e.preventDefault();
        fitAction();
      } else if (e.key === "+" || e.key === "=") {
        zoomInAction();
      } else if (e.key === "-" || e.key === "_") {
        zoomOutAction();
      } else if (e.key === "f" || e.key === "F") {
        if (graphSearchInput) graphSearchInput.focus();
      }
    });
  }

  // App Initialization
  function init() {
    initFromUrlParams();
    bindDomEvents();
    loadGraphData();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
