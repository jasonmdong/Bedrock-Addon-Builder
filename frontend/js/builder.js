// =====================
// BUILD & DOWNLOAD FUNCTIONS
// =====================

const resourceInput = document.getElementById("resource");
const behaviorInput = document.getElementById("behavior");
const buildModeSelect = document.getElementById("build-mode");
const buildBundleBtn = document.getElementById("build-bundle");
const sidebarStatusEl = document.getElementById("sidebar-status");
const templateSelect = document.getElementById("template-select");

// Template storage - now database mob names instead of vanilla templates
let databaseTemplateMobs = [];

// Load template mob names from database
async function loadTemplates() {
  try {
    const res = await fetch("/api/template/mobs");
    const data = await res.json();
    databaseTemplateMobs = data.mobs || [];
    
    // Convert dropdown to datalist-based search input
    const searchContainer = templateSelect.parentElement;
    
    // Create search input if not exists
    let searchInput = document.getElementById("template-search-input");
    if (!searchInput) {
      searchInput = document.createElement("input");
      searchInput.id = "template-search-input";
      searchInput.type = "text";
      searchInput.placeholder = "Search mob templates...";
      searchInput.style.padding = "8px";
      searchInput.style.fontSize = "14px";
      searchInput.style.width = "100%";
      searchInput.style.boxSizing = "border-box";
      
      // Create datalist for autocomplete
      let datalist = document.getElementById("template-mobs-datalist");
      if (!datalist) {
        datalist = document.createElement("datalist");
        datalist.id = "template-mobs-datalist";
        document.body.appendChild(datalist);
      }
      searchInput.setAttribute("list", "template-mobs-datalist");
      
      // Replace the select dropdown with the search input
      searchContainer.replaceChild(searchInput, templateSelect);
      
      // Setup event listener for the search input (after it's created)
      setupTemplateSearchInput(searchInput);
    }
    
    // Populate datalist with mob names
    const datalist = document.getElementById("template-mobs-datalist");
    datalist.innerHTML = "";
    databaseTemplateMobs.forEach(mobName => {
      const option = document.createElement("option");
      option.value = mobName;
      datalist.appendChild(option);
    });
    
    console.log(`[TEMPLATES] Loaded ${databaseTemplateMobs.length} template mobs from database`);
  } catch (err) {
    console.error("Failed to load templates", err);
  }
}

// Setup event listener for template search input
function setupTemplateSearchInput(searchInput) {
  // Handle Enter key to create mob from selected template
  searchInput.addEventListener("keypress", async (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    
    const selectedMobName = searchInput.value.trim();
    if (!selectedMobName) return;
    
    // Validate selected mob exists in database
    if (!databaseTemplateMobs.includes(selectedMobName)) {
      alert(`"${selectedMobName}" is not available in the database.`);
      return;
    }
    
    const user = getCurrentUser();
    if (!user) {
      alert("Please select or create a user first.");
      searchInput.value = "";
      return;
    }
    
    // Open modal to confirm custom name for new mob
    const loadTemplateModalOverlay = document.getElementById("load-template-modal-overlay");
    const templateModalTitle = document.getElementById("template-modal-title");
    const templateMobInput = document.getElementById("template-mob-input");
    
    templateModalTitle.textContent = `Create mob from template: "${selectedMobName}"`;
    templateMobInput.value = `${selectedMobName}_custom`;
    templateMobInput.placeholder = `Enter a custom name for your new mob...`;
    templateMobInput.dataset.templateMob = selectedMobName; // Store template name
    
    // Load database mob names in case user wants to switch template
    if (window.loadTemplateMobNamesFromDB) {
      window.loadTemplateMobNamesFromDB();
    }
    
    loadTemplateModalOverlay?.classList.remove("hidden");
    templateMobInput?.focus();
    templateMobInput?.select();
    
    // Reset search input
    searchInput.value = "";
  });
}

let selectedTemplateId = null;

// Fetch default texture for a vanilla template from Mojang's bedrock-samples repo.
// Exported globally for use in modals.js
async function fetchTemplateTexture(templateId) {
  if (!templateId) return null;
  const base = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/textures/entity";
  const url = `${base}/${encodeURIComponent(templateId)}/${encodeURIComponent(templateId)}.png`;
  try {
    const res = await fetch(url);
    if (!res.ok) {
      console.warn(`[TEMPLATE] No texture found for ${templateId} (status ${res.status}) at ${url}`);
      return null;
    }
    const blob = await res.blob();
    return await new Promise((resolve) => {
      const reader = new FileReader();
      reader.onloadend = () => resolve(reader.result);
      reader.onerror = () => resolve(null);
      reader.readAsDataURL(blob);
    });
  } catch (err) {
    console.warn(`[TEMPLATE] Failed to fetch texture for ${templateId}:`, err);
    return null;
  }
}
// Make available globally for other scripts
window.fetchTemplateTexture = fetchTemplateTexture;

// Fetch mob geometry JSON from server endpoint
// textureMobName is the actual mob name for loading textures (e.g., "orange_cow")
// geometryMobName is the vanilla mob name for fetching geometry (e.g., "cow")
async function fetchAndDisplayGeometry(geometryMobName, textureMobName = null) {
  if (!geometryMobName) return;
  
  // Use textureMobName if provided, otherwise fall back to geometryMobName
  const mobNameForTexture = textureMobName || geometryMobName;
  
  const geometryContainer = document.getElementById("geometry-container");
  const geometryViewer = document.getElementById("geometry-viewer");
  const geometryUrl = document.getElementById("geometry-url");
  const geometryCopy = document.getElementById("geometry-copy");
  
  if (!geometryContainer || !geometryViewer) return;
  
  try {
    // Call our backend endpoint that fetches from bedrock-samples
    const res = await fetch(`/api/geometry/${encodeURIComponent(geometryMobName)}`);
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      console.warn(`[GEOMETRY] Failed to fetch geometry for ${geometryMobName}:`, error.detail || res.statusText);
      // Show container with placeholder instead of hiding it (to maintain layout)
      geometryViewer.textContent = `// No geometry available for "${geometryMobName}"\n// The mob may be using a custom or undefined geometry.`;
      geometryUrl.href = "#";
      geometryUrl.textContent = "No source available";
      geometryContainer.style.display = "block";
      // Clear any previous 3D model
      if (viewer3D && viewer3D.mesh) {
        viewer3D.scene.remove(viewer3D.mesh);
        viewer3D.mesh = null;
      }
      return;
    }
    
    const data = await res.json();
    const geometryData = data.geometry;
    const url = data.url;
    
    // Format JSON with indentation
    const formattedJson = JSON.stringify(geometryData, null, 2);
    
    // Display the geometry
    geometryViewer.textContent = formattedJson;
    geometryUrl.href = url;
    geometryUrl.textContent = `View on GitHub: ${geometryMobName}.geo.json`;
    geometryContainer.style.display = "block";
    
    // Store formatted JSON for copy functionality
    geometryCopy.dataset.json = formattedJson;
    
    // Render the 3D model with texture (use mobNameForTexture to load the correct texture)
    render3DGeometry(geometryData, mobNameForTexture);
    
    console.log(`[GEOMETRY] Successfully loaded geometry for ${geometryMobName}`);
  } catch (err) {
    console.warn(`[GEOMETRY] Error fetching geometry for ${geometryMobName}:`, err);
    // Show container with placeholder instead of hiding it (to maintain layout)
    geometryViewer.textContent = `// Error loading geometry for "${geometryMobName}"\n// ${err.message || 'Unknown error'}`;
    geometryUrl.href = "#";
    geometryUrl.textContent = "No source available";
    geometryContainer.style.display = "block";
    // Clear any previous 3D model
    if (viewer3D && viewer3D.mesh) {
      viewer3D.scene.remove(viewer3D.mesh);
      viewer3D.mesh = null;
    }
  }
}

async function buildArtifact() {
  const selectedMobNames = Array.from(mobListEl.querySelectorAll(".mob-item"))
    .filter(item => item.querySelector("input[type='checkbox']").checked)
    .map(item => item.querySelector(".mob-name").textContent);

  if (selectedMobNames.length === 0) {
    setStatus("No mobs selected for bundle.", true);
    return;
  }

  // Get the actual specs from localStorage
  const selectedSpecs = selectedMobNames.map(name => getUserMob(name)).filter(Boolean);
  
  if (selectedSpecs.length === 0) {
    setStatus("No valid mob specs found.", true);
    return;
  }

  // Get textures from localStorage
  const textures = {};
  selectedMobNames.forEach(name => {
    const tex = getUserMobTexture(name);
    if (tex) textures[name] = tex;
  });

  const choice = buildModeSelect ? buildModeSelect.value : "bundle";
  const msg = `Building bundle with ${selectedSpecs.length} mobs (${choice})...`;
  setStatus(msg);
  if (sidebarStatusEl) {
    sidebarStatusEl.textContent = msg;
    sidebarStatusEl.style.display = "block";
    sidebarStatusEl.style.color = "var(--muted)";
  }
  
  const formData = new FormData();
  if (resourceInput.files[0]) formData.append("resource", resourceInput.files[0]);
  if (behaviorInput.files[0]) formData.append("behavior", behaviorInput.files[0]);
  formData.append("build_mode", choice);
  // Send the actual specs as JSON so server can build them
  formData.append("specs_json", JSON.stringify(selectedSpecs));
  // Send textures as JSON (base64 encoded)
  formData.append("textures_json", JSON.stringify(textures));

  const res = await fetch("/api/build", { method: "POST", body: formData });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || payload.error || res.statusText;
    setStatus("Build failed: " + detail, true);
    if (sidebarStatusEl) {
      sidebarStatusEl.textContent = "Build failed: " + detail;
      sidebarStatusEl.style.color = "var(--danger)";
    }
    return;
  }
  const link = document.createElement("a");
  link.href = payload.artifact || payload.bundle_zip;
  link.textContent = payload.kind === "mcworld" ? "Download .mcworld" : "Download bundle";
  link.target = "_blank";
  link.rel = "noopener";
  link.style.color = "var(--primary)";
  link.style.fontWeight = "bold";

  const successMsg = `${payload.kind === "mcworld" ? "World" : "Bundle"} ready. `;
  statusEl.innerHTML = successMsg;
  statusEl.appendChild(link);

  if (sidebarStatusEl) {
    sidebarStatusEl.innerHTML = successMsg;
    sidebarStatusEl.appendChild(link.cloneNode(true));
    sidebarStatusEl.style.color = "var(--text)";
  }
}

// Update file upload button labels when files are selected
function initFileUploadLabels() {
  const resourceFileName = document.getElementById('resource-file-name');
  const behaviorFileName = document.getElementById('behavior-file-name');

  resourceInput?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file && resourceFileName) {
      resourceFileName.textContent = file.name;
      resourceFileName.style.color = 'var(--primary)';
      resourceFileName.style.fontWeight = 'bold';
    }
  });

  behaviorInput?.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file && behaviorFileName) {
      behaviorFileName.textContent = file.name;
      behaviorFileName.style.color = 'var(--primary)';
      behaviorFileName.style.fontWeight = 'bold';
    }
  });
}

function initTemplateSelect() {
  // Event listeners are now set up in loadTemplates() via setupTemplateSearchInput()
  // This function kept for compatibility with app.js initialization sequence
}


function initBuildHandlers() {
  buildBundleBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    // Ensure current spec is saved before building
    if (currentMobName) {
      const saved = await saveSpec();
      if (saved === null) return; // Stop if current spec has errors
    }
    await buildArtifact();
  });

  buildModeSelect?.addEventListener("change", () => {
    localStorage.setItem(BUILD_MODE_KEY, buildModeSelect.value);
  });

  // --- Publish to Database ---
  initPublishHandler();

  // --- One-Click Play (Test in Game) ---
  initTestInGame();
}

// ---------------------------------------------------------------------------
// Test in Game (One-Click Play)
// ---------------------------------------------------------------------------
const testInGameBtn = document.getElementById("test-in-game");
const testSessionBar = document.getElementById("test-session-bar");
const testSessionStatus = document.getElementById("test-session-status");
const testSessionLog = document.getElementById("test-session-log");
const testStopBtn = document.getElementById("test-stop-btn");
let _testPollTimer = null;

function _setTestStatus(text, color) {
  if (testSessionStatus) {
    testSessionStatus.textContent = text;
    testSessionStatus.style.color = color || "var(--text)";
  }
}

function _startTestPolling() {
  if (_testPollTimer) return;
  testSessionBar.style.display = "block";
  _testPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/launch-test/status");
      const data = await res.json();
      const statusMap = {
        idle: ["Idle", "var(--hint)"],
        starting: ["Starting server...", "#f59e0b"],
        ready: ["Server ready! Minecraft launching...", "#10b981"],
        error: ["Error: " + (data.error || "unknown"), "var(--danger)"],
        stopped: ["Stopped", "var(--hint)"],
      };
      const [label, color] = statusMap[data.status] || ["Unknown", "var(--hint)"];
      _setTestStatus(label, color);
      if (testSessionLog && data.recent_logs) {
        testSessionLog.textContent = data.recent_logs.join("\n");
        testSessionLog.scrollTop = testSessionLog.scrollHeight;
      }
      if (!data.running && data.status !== "starting") {
        _stopTestPolling();
        testInGameBtn.disabled = false;
        testInGameBtn.textContent = "🎮 Test in Game";
      }
    } catch (e) {
      _setTestStatus("Poll error", "var(--danger)");
    }
  }, 1500);
}

function _stopTestPolling() {
  if (_testPollTimer) {
    clearInterval(_testPollTimer);
    _testPollTimer = null;
  }
}

function initTestInGame() {
  testInGameBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    // Save current spec first
    if (currentMobName) {
      const saved = await saveSpec();
      if (saved === null) return;
    }

    // Use only the currently active mob (the one being edited)
    if (!currentMobName) {
      setStatus("No mob selected. Click a mob in the sidebar first.", true);
      return;
    }
    const activeMobSpec = getUserMob(currentMobName);
    if (!activeMobSpec) {
      setStatus("Could not load spec for " + currentMobName, true);
      return;
    }
    const selectedSpecs = [activeMobSpec];

    // Determine category from the spec (entity by default)
    const category = "entity_logic_ai";

    testInGameBtn.disabled = true;
    testInGameBtn.textContent = "Launching...";
    _setTestStatus("Sending to server...", "#f59e0b");
    testSessionBar.style.display = "block";
    if (testSessionLog) testSessionLog.textContent = "";

    try {
      const res = await fetch("/api/launch-test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ specs: selectedSpecs, category }),
      });
      const data = await res.json();
      if (!res.ok) {
        _setTestStatus("Error: " + (data.detail || res.statusText), "var(--danger)");
        testInGameBtn.disabled = false;
        testInGameBtn.textContent = "🎮 Test in Game";
        return;
      }
      _setTestStatus("Starting...", "#f59e0b");
      _startTestPolling();
    } catch (err) {
      _setTestStatus("Network error: " + err.message, "var(--danger)");
      testInGameBtn.disabled = false;
      testInGameBtn.textContent = "🎮 Test in Game";
    }
  });

  testStopBtn?.addEventListener("click", async () => {
    _setTestStatus("Stopping...", "#f59e0b");
    try {
      await fetch("/api/launch-test/stop", { method: "POST" });
    } catch (e) { /* ignore */ }
    _stopTestPolling();
    testInGameBtn.disabled = false;
    testInGameBtn.textContent = "🎮 Test in Game";
    setTimeout(() => _setTestStatus("Stopped", "var(--hint)"), 500);
  });
}

// ---------------------------------------------------------------------------
// Publish to Database
// ---------------------------------------------------------------------------
const publishMobBtn = document.getElementById("publish-mob-btn");

function initPublishHandler() {
  publishMobBtn?.addEventListener("click", async (e) => {
    e.preventDefault();
    
    const user = getCurrentUser();
    if (!user) {
      alert("Please select or create a user first.");
      return;
    }
    
    if (!currentMobName || currentMobName === "current") {
      alert("Please create and save a mob first before publishing.");
      return;
    }
    
    // Ensure current spec is saved
    const saved = await saveSpec();
    if (saved === null) return;
    
    // Get the current mob spec
    const spec = getUserMob(currentMobName);
    if (!spec) {
      alert("Could not find mob spec to publish.");
      return;
    }
    
    // Get geometry from the spec
    const geometry = spec.geometry || {};
    if (!geometry || Object.keys(geometry).length === 0) {
      const proceed = confirm("This mob has no custom geometry. Publish anyway?");
      if (!proceed) return;
    }
    
    // Get prompts from LLM history
    let prompts = [];
    try {
      const llmStackKey = `llm_stack_${user}`;
      const rawHistory = localStorage.getItem(llmStackKey);
      if (rawHistory) {
        const history = JSON.parse(rawHistory);
        prompts = history.map(entry => entry.prompt).filter(p => p);
      }
    } catch (e) {
      console.warn("Could not read LLM history:", e);
    }
    
    if (prompts.length === 0) {
      const proceed = confirm("No LLM prompts found for this mob. The AI won't have context about how this mob was created. Publish anyway?");
      if (!proceed) return;
    }
    
    // Show confirmation dialog
    const confirmMsg = `Publish "${currentMobName}" to the database?\n\nThis mob will be saved with ${prompts.length} prompt(s) for AI learning.\n\nUsername: ${user}`;
    if (!confirm(confirmMsg)) return;
    
    // Disable button and show loading state
    publishMobBtn.disabled = true;
    const originalText = publishMobBtn.textContent;
    publishMobBtn.textContent = "📤 Publishing...";
    
    try {
      const response = await fetch("/api/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mob_name: currentMobName,
          username: user,
          prompts: prompts,
          geometry: geometry
        })
      });
      
      const result = await response.json();
      
      if (!response.ok) {
        throw new Error(result.detail || result.error || "Failed to publish");
      }
      
      // Success
      alert(`✓ Published successfully!\n\nMob: ${result.mob_name}\nDescription: ${result.description}\nKeywords: ${result.keywords?.join(", ")}`);
      
      if (sidebarStatusEl) {
        sidebarStatusEl.style.display = "block";
        sidebarStatusEl.style.background = "rgba(16, 185, 129, 0.1)";
        sidebarStatusEl.style.color = "#10b981";
        sidebarStatusEl.textContent = `Published: ${result.mob_name}`;
        setTimeout(() => {
          sidebarStatusEl.style.display = "none";
        }, 5000);
      }
      
    } catch (err) {
      console.error("Publish error:", err);
      alert(`✗ Failed to publish: ${err.message}`);
    } finally {
      publishMobBtn.disabled = false;
      publishMobBtn.textContent = originalText;
    }
  });
}
