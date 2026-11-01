/**
 * frontend/js/navigation.js
 * Sidebar router, mobile drawer, and view switcher for UI Batch A.
 */

export class NavigationManager {
  constructor() {
    this.currentRoute = "overview";
    this.routeTitles = {
      "overview": "DevOps Overview",
      "live-pipeline": "Live CI/CD Pipeline",
      "run-history": "Pipeline Run History",
      "metadata-intel": "Metadata Intelligence",
      "graph-intel": "Neo4j Knowledge Graph",
      "model-comparison": "Model Comparison",
      "rca": "Root Cause Analysis",
      "demo-control": "Demo Control",
      "system-health": "System Health"
    };
  }

  init() {
    this.bindEvents();
    // Check URL hash if present (e.g. #demo-control, #system-health)
    const hash = window.location.hash.replace(/^#/, "");
    if (hash && this.routeTitles[hash]) {
      this.navigate(hash, false);
    } else {
      this.navigate("overview", false);
    }
  }

  navigate(routeId, updateHash = true) {
    if (!this.routeTitles[routeId]) {
      routeId = "overview";
    }
    this.currentRoute = routeId;

    // 1. Update navigation active state
    document.querySelectorAll(".nav-link[data-route], .sidebar-nav-item[data-route]").forEach((item) => {
      const match = item.getAttribute("data-route") === routeId;
      item.classList.toggle("active", match);
      if (match) {
        item.setAttribute("aria-current", "page");
      } else {
        item.removeAttribute("aria-current");
      }
    });

    // 2. Hide all views and show target view
    document.querySelectorAll(".view-container, .view-panel").forEach((view) => {
      view.style.display = "none";
      view.classList.remove("active");
    });

    const targetView = document.getElementById(`view-${routeId}`);
    if (targetView) {
      targetView.style.display = "flex";
      targetView.classList.add("active");
    }

    // 3. Update breadcrumbs and titles
    const breadcrumbCurrent = document.getElementById("breadcrumb-current");
    const headerTitle = document.getElementById("header-page-title");
    const titleText = this.routeTitles[routeId] || "DevOps Overview";

    if (breadcrumbCurrent) breadcrumbCurrent.textContent = titleText;
    if (headerTitle) headerTitle.textContent = titleText;

    // 4. Update browser URL hash
    if (updateHash) {
      history.pushState(null, "", `#${routeId}`);
    }

    // 5. Close mobile drawer if open
    document.body.classList.remove("mobile-nav-open");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (sidebar) sidebar.classList.remove("mobile-open");
    if (backdrop) backdrop.classList.remove("active");

    // 6. Dispatch custom route change event so active view controller can trigger refresh
    window.dispatchEvent(new CustomEvent("routechange", { detail: { route: routeId } }));
  }

  bindEvents() {
    // Sidebar navigation clicks
    document.querySelectorAll(".nav-link[data-route], .sidebar-nav-item[data-route]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const route = btn.getAttribute("data-route");
        if (route) {
          this.navigate(route);
        }
      });
    });

    // Sidebar collapse toggle for desktop
    const collapseBtn = document.getElementById("sidebar-toggle-btn") || document.getElementById("sidebar-collapse-btn");
    const sidebar = document.getElementById("sidebar");

    if (collapseBtn && sidebar) {
      collapseBtn.addEventListener("click", () => {
        sidebar.classList.toggle("collapsed");
        document.body.classList.toggle("sidebar-collapsed");
        const isCollapsed = sidebar.classList.contains("collapsed");
        localStorage.setItem("cicd_sidebar_collapsed", isCollapsed ? "1" : "0");
      });

      // Restore collapsed preference
      if (localStorage.getItem("cicd_sidebar_collapsed") === "1") {
        sidebar.classList.add("collapsed");
        document.body.classList.add("sidebar-collapsed");
      }
    }

    // Mobile menu toggle
    const mobileBtn = document.getElementById("mobile-sidebar-toggle") || document.getElementById("mobile-menu-btn");
    const backdrop = document.getElementById("sidebar-backdrop");

    if (mobileBtn && sidebar) {
      mobileBtn.addEventListener("click", () => {
        sidebar.classList.toggle("mobile-open");
        if (backdrop) backdrop.classList.toggle("active");
      });
    }

    if (backdrop && sidebar) {
      backdrop.addEventListener("click", () => {
        sidebar.classList.remove("mobile-open");
        backdrop.classList.remove("active");
      });
    }

    // Handle browser back/forward buttons
    window.addEventListener("popstate", () => {
      const hash = window.location.hash.replace(/^#/, "");
      if (hash && this.routeTitles[hash]) {
        this.navigate(hash, false);
      } else {
        this.navigate("overview", false);
      }
    });
  }
}

export const navigation = new NavigationManager();

