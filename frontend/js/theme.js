/**
 * frontend/js/theme.js
 * Dark and light theme switcher with localStorage persistence.
 */

export class ThemeManager {
  static STORAGE_KEY = "cicd_intelligence_theme";
  static DARK = "dark";
  static LIGHT = "light";

  constructor() {
    this.currentTheme = ThemeManager.DARK;
  }

  init() {
    // 1. Check URL param, saved preference or fallback to dark mode default
    const urlParams = new URLSearchParams(window.location.search);
    const paramTheme = urlParams.get("theme");
    const saved = localStorage.getItem(ThemeManager.STORAGE_KEY);

    if (paramTheme === ThemeManager.LIGHT || paramTheme === ThemeManager.DARK) {
      this.currentTheme = paramTheme;
    } else if (saved === ThemeManager.LIGHT || saved === ThemeManager.DARK) {
      this.currentTheme = saved;
    } else {
      this.currentTheme = ThemeManager.DARK;
    }

    this.applyTheme(this.currentTheme);
    this.bindEvents();
  }

  applyTheme(theme) {
    this.currentTheme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    document.body.classList.remove("dark-theme", "light-theme");
    document.body.classList.add(`${theme}-theme`);

    localStorage.setItem(ThemeManager.STORAGE_KEY, theme);

    // Update toggle icons/labels in header
    const toggleBtn = document.getElementById("theme-toggle-btn");
    if (toggleBtn) {
      const isDark = theme === ThemeManager.DARK;
      toggleBtn.setAttribute("aria-label", isDark ? "Switch to light theme" : "Switch to dark theme");
      toggleBtn.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
      toggleBtn.innerHTML = isDark
        ? `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`
        : `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
    }

    // Dispatch event for any chart re-rendering
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  toggle() {
    const nextTheme = this.currentTheme === ThemeManager.DARK ? ThemeManager.LIGHT : ThemeManager.DARK;
    this.applyTheme(nextTheme);
  }

  bindEvents() {
    const toggleBtn = document.getElementById("theme-toggle-btn");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", () => this.toggle());
    }
  }
}

export const themeManager = new ThemeManager();

