/**
 * frontend/js/utils.js
 * Common UI and helper utilities for CI/CD Intelligence Dashboard.
 */

export const Utils = {
  /**
   * Copy exact text to clipboard with modern Clipboard API and legacy fallback.
   * @param {string} text Exact text to copy
   * @returns {Promise<boolean>} Resolves true on success, false on error
   */
  async copyToClipboard(text) {
    if (!text || typeof text !== "string") {
      return false;
    }
    const cleanText = text.trim();

    // 1. Try modern navigator.clipboard
    if (navigator.clipboard && window.isSecureContext) {
      try {
        await navigator.clipboard.writeText(cleanText);
        return true;
      } catch (err) {
        console.warn("navigator.clipboard failed, attempting fallback:", err);
      }
    }

    // 2. Legacy fallback via temporary textarea
    try {
      const textarea = document.createElement("textarea");
      textarea.value = cleanText;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      textarea.style.top = "0";
      document.body.appendChild(textarea);
      textarea.select();
      textarea.setSelectionRange(0, textarea.value.length);
      const successful = document.execCommand("copy");
      document.body.removeChild(textarea);
      return successful;
    } catch (fallbackErr) {
      console.error("Clipboard copy fallback failed:", fallbackErr);
      return false;
    }
  },

  /**
   * Display accessible toast alert.
   * @param {string} message Text message to display
   * @param {'success'|'error'|'warning'|'info'} type Alert severity
   * @param {number} duration Duration in milliseconds
   */
  showToast(message, type = "info", duration = 3000) {
    let container = document.getElementById("toast-container");
    if (!container) {
      container = document.createElement("div");
      container.id = "toast-container";
      container.className = "toast-container";
      document.body.appendChild(container);
    }

    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", "status");
    toast.setAttribute("aria-live", "polite");

    const iconSvg = {
      success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>`,
      error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
      warning: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`,
      info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`
    }[type] || "";

    toast.innerHTML = `
      <span class="toast-icon">${iconSvg}</span>
      <span class="toast-message">${this.escapeHtml(message)}</span>
      <button type="button" class="toast-close" aria-label="Close notification">&times;</button>
    `;

    container.appendChild(toast);

    const closeBtn = toast.querySelector(".toast-close");
    const removeToast = () => {
      toast.classList.add("toast-hiding");
      setTimeout(() => {
        if (toast.parentNode === container) {
          container.removeChild(toast);
        }
      }, 200);
    };

    closeBtn.addEventListener("click", removeToast);
    setTimeout(removeToast, duration);
  },

  /**
   * Escape HTML entities to prevent XSS.
   */
  escapeHtml(str) {
    if (!str && str !== 0) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  },

  /**
   * Format ISO date string into a clean localized string.
   */
  formatDateTime(isoStr) {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return isoStr;
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
    } catch {
      return isoStr;
    }
  },

  /**
   * Format duration in seconds to a human readable label.
   */
  formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return "—";
    const num = Number(seconds);
    if (isNaN(num)) return "—";
    if (num < 1) return `${Math.round(num * 1000)}ms`;
    if (num < 60) return `${num.toFixed(1)}s`;
    const mins = Math.floor(num / 60);
    const remSecs = Math.round(num % 60);
    return `${mins}m ${remSecs}s`;
  },

  /**
   * Format relative time (e.g. "2m ago", "just now").
   */
  formatRelativeTime(isoStr) {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
      if (diffSec < 5) return "just now";
      if (diffSec < 60) return `${diffSec}s ago`;
      if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
      if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
      return `${Math.floor(diffSec / 86400)}d ago`;
    } catch {
      return isoStr;
    }
  },

  /**
   * Render HTML for standard status badge.
   */
  renderBadge(status, customLabel = null) {
    const norm = String(status || "UNKNOWN").toUpperCase();
    const label = customLabel || norm;
    let badgeClass = "badge-muted";

    if (["HEALTHY", "ONLINE", "SUCCESS", "PASSED", "COMPLETED"].includes(norm)) {
      badgeClass = "badge-healthy";
    } else if (["DEGRADED", "WARNING", "MODERATE", "TRIGGERED", "DISPATCHED", "RUNNING"].includes(norm)) {
      badgeClass = "badge-warning";
    } else if (["UNHEALTHY", "OFFLINE", "FAILED", "FAILURE", "CRITICAL"].includes(norm)) {
      badgeClass = "badge-danger";
    }

    return `<span class="status-badge ${badgeClass}"><span class="status-dot"></span>${this.escapeHtml(label)}</span>`;
  },

  /**
   * Universal runtime risk classifier and color provider.
   * Exact calibrated thresholds:
   *  - 0% - 40% inclusive: Green / Low Risk
   *  - > 40% and < 70%: Yellow/Amber / Moderate Risk
   *  - >= 70%: Red / High Risk (or High/Critical Risk)
   *
   * Exact boundary specifications:
   *  - 40.00% = Green / Low Risk
   *  - 40.01% = Yellow / Moderate Risk
   *  - 69.99% = Yellow / Moderate Risk
   *  - 70.00% = Red / High Risk
   *  - 73.67% = Red / High Risk
   *  - 30.00% = Green / Low Risk
   *
   * @param {number|string} riskVal Failure probability (0.0-1.0) or percentage (0-100)
   * @returns {{
   *   percentage: number,
   *   level: 'low' | 'moderate' | 'high' | 'nominal',
   *   label: string,
   *   colorVar: string,
   *   textClass: string,
   *   badgeClass: string,
   *   bgClass: string,
   *   borderClass: string,
   *   hexColor: string
   * }}
   */
  classifyRisk(riskVal) {
    if (riskVal === null || riskVal === undefined || riskVal === "" || riskVal === "-" || riskVal === "—") {
      return {
        percentage: 0,
        level: "nominal",
        label: "NOMINAL",
        colorVar: "var(--status-neutral)",
        textClass: "text-muted",
        badgeClass: "badge-muted",
        bgClass: "text-neutral-bg",
        borderClass: "border-neutral",
        hexColor: "#64748b"
      };
    }
    let num = Number(riskVal);
    if (isNaN(num)) {
      return {
        percentage: 0,
        level: "nominal",
        label: "NOMINAL",
        colorVar: "var(--status-neutral)",
        textClass: "text-muted",
        badgeClass: "badge-muted",
        bgClass: "text-neutral-bg",
        borderClass: "border-neutral",
        hexColor: "#64748b"
      };
    }
    let pct = num;
    if (num <= 1.0 && num > 0) {
      pct = num * 100.0;
    }
    // Round to 2 decimal places for precise boundary checks
    const rounded = Math.round(pct * 100) / 100;

    if (rounded >= 70.0) {
      return {
        percentage: rounded,
        level: "high",
        label: "HIGH RISK",
        colorVar: "var(--status-unhealthy)",
        textClass: "text-danger",
        badgeClass: "badge-unhealthy",
        bgClass: "text-danger-bg",
        borderClass: "border-danger",
        hexColor: "var(--status-unhealthy)"
      };
    } else if (rounded > 40.0) {
      return {
        percentage: rounded,
        level: "moderate",
        label: "MODERATE RISK",
        colorVar: "var(--status-degraded)",
        textClass: "text-warning",
        badgeClass: "badge-degraded",
        bgClass: "text-warning-bg",
        borderClass: "border-warning",
        hexColor: "var(--status-degraded)"
      };
    } else {
      return {
        percentage: rounded,
        level: "low",
        label: "LOW RISK",
        colorVar: "var(--status-healthy)",
        textClass: "text-success",
        badgeClass: "badge-healthy",
        bgClass: "text-success-bg",
        borderClass: "border-healthy",
        hexColor: "var(--status-healthy)"
      };
    }
  }
};

