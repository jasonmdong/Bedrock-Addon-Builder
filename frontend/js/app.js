// =====================
// MAIN APP INITIALIZATION
// =====================

// Global constants
const THEME_KEY = "builder_theme_preference";
const LLM_PROVIDER_KEY = "builder_llm_provider";
const LLM_API_KEY_STORAGE = "builder_llm_api_key";
const BUILD_MODE_KEY = "builder_build_mode";

// Shared state
let currentMobName = "current";

// Theme management
const themeToggle = document.getElementById("theme-toggle");
const addMobBtn = document.getElementById("add-mob");

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
  if (storedProvider && llmProvider) {
    llmProvider.value = storedProvider;
  }
  if (storedKey && llmKey) {
    llmKey.value = storedKey;
  }
}

function loadBuildMode() {
  const storedMode = localStorage.getItem(BUILD_MODE_KEY);
  if (storedMode && buildModeSelect) {
    buildModeSelect.value = storedMode;
  }
}

function setStatus(message, isError=false) {
  statusEl.textContent = message;
  statusEl.style.color = isError ? "#fecdd3" : "#94a3b8";
}

// Initialize all event listeners
function initEventListeners() {
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
  // Initialize theme first
  initTheme();
  
  // Load preferences
  loadLlmPrefs();
  loadBuildMode();
  
  // Initialize all modules
  initUserSystem();
  initResizer();
  initAddMobModal();
  initLoadTemplateModal();
  initPainter();
  initViewportControls();
  initGeometryCopy();
  initGeometryGenerator();
  initLlmHandlers();
  initFileUploadLabels();
  initTemplateSelect();
  initBuildHandlers();
  initEventListeners();
  
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
  loadTemplates();
  loadSpec();
  renderLlmHistory();
}

// Start the app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
