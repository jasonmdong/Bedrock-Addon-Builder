// =====================
// BUILD & DOWNLOAD FUNCTIONS
// =====================

const resourceInput = document.getElementById("resource");
const behaviorInput = document.getElementById("behavior");
const buildModeSelect = document.getElementById("build-mode");
const buildBundleBtn = document.getElementById("build-bundle");
const sidebarStatusEl = document.getElementById("sidebar-status");
const templateSelect = document.getElementById("template-select");

// Templates storage
let vanillaTemplates = {};

// Load templates from server
async function loadTemplates() {
  try {
    const res = await fetch("/api/templates");
    const data = await res.json();
    vanillaTemplates = data.mobs || {};
    
    // Fill the dropdown
    templateSelect.innerHTML = '<option value="">-- Load Template --</option>';
    Object.keys(vanillaTemplates).sort().forEach(id => {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = vanillaTemplates[id].display_name || id;
      templateSelect.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load templates", err);
  }
}

let selectedTemplateId = null;

// Fetch default texture for a vanilla template from Mojang's bedrock-samples repo.
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

// Fetch mob geometry JSON from server endpoint
async function fetchAndDisplayGeometry(mobName) {
  if (!mobName) return;
  
  const geometryContainer = document.getElementById("geometry-container");
  const geometryViewer = document.getElementById("geometry-viewer");
  const geometryUrl = document.getElementById("geometry-url");
  const geometryCopy = document.getElementById("geometry-copy");
  
  if (!geometryContainer || !geometryViewer) return;
  
  try {
    // Call our backend endpoint that fetches from bedrock-samples
    const res = await fetch(`/api/geometry/${encodeURIComponent(mobName)}`);
    
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      console.warn(`[GEOMETRY] Failed to fetch geometry for ${mobName}:`, error.detail || res.statusText);
      geometryContainer.style.display = "none";
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
    geometryUrl.textContent = `View on GitHub: ${mobName}.geo.json`;
    geometryContainer.style.display = "block";
    
    // Store formatted JSON for copy functionality
    geometryCopy.dataset.json = formattedJson;
    
    // Render the 3D model
    render3DGeometry(geometryData);
    
    console.log(`[GEOMETRY] Successfully loaded geometry for ${mobName}`);
  } catch (err) {
    console.warn(`[GEOMETRY] Error fetching geometry for ${mobName}:`, err);
    geometryContainer.style.display = "none";
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
  templateSelect?.addEventListener("change", async () => {
    const templateId = templateSelect.value;
    if (!templateId) return;
    
    const template = vanillaTemplates[templateId];
    if (!template) return;
    
    const user = getCurrentUser();
    if (!user) {
      alert("Please select or create a user first.");
      templateSelect.value = "";
      return;
    }
    
    // Store the selected template and show modal
    selectedTemplateId = templateId;
    const loadTemplateModalOverlay = document.getElementById("load-template-modal-overlay");
    const templateModalTitle = document.getElementById("template-modal-title");
    const templateMobInput = document.getElementById("template-mob-input");
    
    templateModalTitle.textContent = `Load ${template.display_name}`;
    templateMobInput.value = template.short_name;
    templateMobInput.placeholder = `Enter name for your ${template.display_name}...`;
    loadTemplateModalOverlay?.classList.remove("hidden");
    templateMobInput?.focus();
    templateMobInput?.select();
    
    // Reset dropdown
    templateSelect.value = "";
  });
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
}
