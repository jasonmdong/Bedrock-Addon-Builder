// =====================
// MAIN APP INITIALIZATION
// =====================
console.log("[App] Script loaded");

// Global constants
const THEME_KEY = "builder_theme_preference";
const LLM_PROVIDER_KEY = "builder_llm_provider";
const LLM_API_KEY_STORAGE = "builder_llm_api_key";
const BUILD_MODE_KEY = "builder_build_mode";

// Shared state — restore last selected mob across page reloads
let currentMobName = localStorage.getItem("builder_current_mob") || "current";

// Theme management
const themeToggle = document.getElementById("theme-toggle");
const addMobBtn = document.getElementById("add-mob");

// ---------------------
// Sidebar collapse logic
// ---------------------
// Keep this separate from the rest of init so it still works even if some
// other module throws during startup.
function initSidebarCollapse() {
  const sidebarToggle = document.getElementById("sidebar-toggle");
  const sidebar = document.getElementById("sidebar");
  const resizer = document.getElementById("resizer");

  console.log("[Sidebar] Toggle button:", sidebarToggle);
  console.log("[Sidebar] Sidebar element:", sidebar);

  if (!sidebarToggle || !sidebar) {
    console.warn("[Sidebar] Toggle button or sidebar not found");
    return;
  }

  function setCollapsed(collapsed) {
    sidebar.classList.toggle("collapsed", collapsed);
    localStorage.setItem("sidebar-collapsed", String(collapsed));

    // When collapsing, clear any inline width set by the resizer.
    // When expanding, restore the saved width if present.
    if (collapsed) {
      sidebar.style.width = "";
      sidebarToggle.innerHTML = "▶";
      if (resizer) resizer.style.pointerEvents = "none";
    } else {
      sidebarToggle.innerHTML = "◀";
      if (resizer) resizer.style.pointerEvents = "auto";
      const savedWidth = localStorage.getItem("sidebar_width");
      if (savedWidth) sidebar.style.width = savedWidth;
    }
  }

  // Restore collapsed state on load
  const isCollapsed = localStorage.getItem("sidebar-collapsed") === "true";
  console.log("[Sidebar] Restored collapsed state:", isCollapsed);
  setCollapsed(isCollapsed);

  sidebarToggle.addEventListener("click", (e) => {
    console.log("[Sidebar] Toggle clicked");
    e.preventDefault();
    e.stopPropagation();
    setCollapsed(!sidebar.classList.contains("collapsed"));
  });
}

function applyTheme(theme) {
  document.body.classList.toggle("theme-dark", theme === "dark");
  if (themeToggle) {
    themeToggle.textContent = theme === "dark" ? "☀ Light Mode" : "🌙 Dark Mode";
  }
}

function initTheme() {
  const stored = localStorage.getItem(THEME_KEY);
  const theme = stored === "dark" ? "dark" : "light";
  applyTheme(theme);
}

function loadLlmPrefs() {
  const storedProvider = localStorage.getItem(LLM_PROVIDER_KEY);
  const storedKey = localStorage.getItem(LLM_API_KEY_STORAGE);
  // Use typeof guards so this file doesn't crash if llm.js fails to load.
  if (storedProvider && typeof llmProvider !== "undefined" && llmProvider) {
    llmProvider.value = storedProvider;
  }
  if (storedKey && typeof llmKey !== "undefined" && llmKey) {
    llmKey.value = storedKey;
  }
}

function loadBuildMode() {
  const storedMode = localStorage.getItem(BUILD_MODE_KEY);
  // Use typeof guards so this file doesn't crash if builder.js fails to load.
  if (storedMode && typeof buildModeSelect !== "undefined" && buildModeSelect) {
    buildModeSelect.value = storedMode;
  }
}

function setStatus(message, isError=false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#fecdd3" : "#94a3b8";
}

// Initialize all event listeners
function initEventListeners() {
  console.log("[App] initEventListeners called");
  
  document.getElementById("reset")?.addEventListener("click", (e) => {
    e.preventDefault();
    loadSpec();
  });

  document.getElementById("save")?.addEventListener("click", (e) => {
    e.preventDefault();
    saveSpec();
  });

  addMobBtn?.addEventListener("click", async () => {
    const user = getCurrentUser();
    if (!user) {
      alert("Please select or create a user first.");
      return;
    }
    if (typeof canAddMob === "function" && !canAddMob()) {
      const lim = typeof getTierMobLimit === "function" ? getTierMobLimit() : 5;
      alert(
        `Mob limit reached (${lim === -1 ? "unlimited" : lim + " mobs"} on this demo plan). Delete a mob or change demo plan.`
      );
      return;
    }
    
    // Show the add mob modal
    const addMobModalOverlay = document.getElementById("add-mob-modal-overlay");
    const newMobInput = document.getElementById("new-mob-input");
    addMobModalOverlay?.classList.remove("hidden");
    newMobInput?.focus();
  });

  themeToggle?.addEventListener("click", () => {
    const next = document.body.classList.contains("theme-dark") ? "light" : "dark";
    applyTheme(next);
    localStorage.setItem(THEME_KEY, next);
  });
}

// Main initialization
function initApp() {
  // Initialize sidebar collapse first so it still works even if some other
  // module fails to initialize.
  initSidebarCollapse();

  // Initialize theme first
  initTheme();
  
  // Load preferences
  loadLlmPrefs();
  loadBuildMode();
  
  // Initialize all modules (guard each so one failure doesn't kill the rest)
  const safe = (name, fn) => {
    try {
      if (typeof fn === "function") fn();
      else console.warn(`[App] ${name} not found`);
    } catch (err) {
      console.error(`[App] ${name} failed:`, err);
    }
  };

  safe("initUserSystem", (typeof initUserSystem !== "undefined") ? initUserSystem : null);
  safe("initResizer", (typeof initResizer !== "undefined") ? initResizer : null);
  safe("initAddMobModal", (typeof initAddMobModal !== "undefined") ? initAddMobModal : null);
  safe("initLoadTemplateModal", (typeof initLoadTemplateModal !== "undefined") ? initLoadTemplateModal : null);
  safe("initPainter", (typeof initPainter !== "undefined") ? initPainter : null);
  safe("initViewportControls", (typeof initViewportControls !== "undefined") ? initViewportControls : null);
  safe("initGeometryCopy", (typeof initGeometryCopy !== "undefined") ? initGeometryCopy : null);
  safe("initGeometryGenerator", (typeof initGeometryGenerator !== "undefined") ? initGeometryGenerator : null);
  safe("initLlmHandlers", (typeof initLlmHandlers !== "undefined") ? initLlmHandlers : null);
  safe("initFileUploadLabels", (typeof initFileUploadLabels !== "undefined") ? initFileUploadLabels : null);
  safe("initTemplateSelect", (typeof initTemplateSelect !== "undefined") ? initTemplateSelect : null);
  safe("initBuildHandlers", (typeof initBuildHandlers !== "undefined") ? initBuildHandlers : null);
  safe("initMctools", (typeof initMctools !== "undefined") ? initMctools : null);
  safe("initEventListeners", initEventListeners);
  
  // Initialize 3D Editor controls
  if (typeof init3DEditorControls === 'function') {
    init3DEditorControls();
    // Retry after a short delay to ensure DOM is fully ready
    setTimeout(() => {
      const toolBtns = document.querySelectorAll('.editor-tool-btn');
      if (toolBtns.length > 0) {
        console.log('[App] Delayed 3D editor init - buttons found');
        init3DEditorControls();
      }
    }, 100);
  }
  
  // Load templates and initial data
  safe("loadTemplates", (typeof loadTemplates !== "undefined") ? loadTemplates : null);
  safe("loadSpec", (typeof loadSpec !== "undefined") ? loadSpec : null);
  safe("renderLlmHistory", (typeof renderLlmHistory !== "undefined") ? renderLlmHistory : null);
  safe("updateTierUsagePanel", (typeof updateTierUsagePanel !== "undefined") ? updateTierUsagePanel : null);
}

// Start the app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
