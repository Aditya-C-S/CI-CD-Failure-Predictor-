/**
 * frontend/app.js
 * Main Entry Point for Modern DevOps Dashboard (UI Batches A & B)
 * Initializes Theme Manager, Sidebar Router, Overview, Live Pipeline, Run History,
 * Demo Control, and System Health.
 */

import { themeManager } from "./js/theme.js";
import { navigation } from "./js/navigation.js";
import { overviewController } from "./js/overview.js";
import { demoControlController } from "./js/demo-control.js";
import { healthController } from "./js/health.js";
import { livePipelineController } from "./js/live-pipeline.js";
import { runHistoryController } from "./js/run-history.js";
import { metadataIntelController } from "./js/metadata-intel.js";
import { graphIntelController } from "./js/graph-intel.js";
import { modelComparisonController } from "./js/model-comparison.js";
import { rcaController } from "./js/rca.js";
import { Utils } from "./js/utils.js";

document.addEventListener("DOMContentLoaded", () => {
  console.log("Initializing CI/CD Failure Predictor Modern Dashboard (Complete UI Batches A, B & C)...");

  // 1. Initialize Dark/Light Theme System
  themeManager.init();

  // 2. Initialize Navigation & Collapsible Sidebar
  navigation.init();

  // 3. Initialize Overview Controller
  overviewController.init();

  // 4. Initialize Live Pipeline Controller (UI Batch B)
  livePipelineController.init();

  // 5. Initialize Run History & Inspector Controller (UI Batch B)
  runHistoryController.init();

  // 6. Initialize Pre-Build Metadata Intelligence (UI Batch C)
  metadataIntelController.init();

  // 7. Initialize Neo4j Knowledge Graph & Blast Radius (UI Batch C)
  graphIntelController.init();

  // 8. Initialize Model Comparison & Risk Progression (UI Batch C)
  modelComparisonController.init();

  // 9. Initialize Assisted Root Cause Analysis (UI Batch C)
  rcaController.init();

  // 10. Initialize Demo Control & Scenario Orchestrator
  demoControlController.init();

  // 11. Initialize System Health Diagnostics
  healthController.init();

  console.log("CI/CD Intelligence Dashboard UI Batch C initialized successfully.");
});

// Export modules for debugging in browser console
window.__CICD_DASHBOARD__ = {
  themeManager,
  navigation,
  overviewController,
  livePipelineController,
  runHistoryController,
  metadataIntelController,
  graphIntelController,
  modelComparisonController,
  rcaController,
  demoControlController,
  healthController,
  Utils
};
