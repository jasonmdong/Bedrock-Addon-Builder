// =====================
// SIDEBAR RESIZER
// =====================
function initResizer() {
  const sidebar = document.getElementById("sidebar");
  const resizer = document.getElementById("resizer");
  let isResizing = false;

  if (!sidebar || !resizer) {
    console.warn("[Resizer] sidebar or resizer element not found");
    return;
  }

  resizer.addEventListener("mousedown", (e) => {
    // Don't resize while collapsed (it can also eat clicks near the toggle)
    if (sidebar.classList.contains("collapsed")) return;
    isResizing = true;
    document.body.classList.add("resizing");
    e.preventDefault();
  });

  window.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const rect = sidebar.getBoundingClientRect();
    const newWidth = e.clientX - rect.left;
    if (newWidth >= 350 && newWidth <= 600) {
      sidebar.style.width = newWidth + "px";
    }
  });

  window.addEventListener("mouseup", () => {
    if (isResizing) {
      isResizing = false;
      document.body.classList.remove("resizing");
      // Save preference
      localStorage.setItem("sidebar_width", sidebar.style.width);
    }
  });
  
  // Restore preference
  const savedWidth = localStorage.getItem("sidebar_width");
  if (savedWidth) {
    sidebar.style.width = savedWidth;
  }
}

// =====================
// ADD MOB MODAL
// =====================
function initAddMobModal() {
  const addMobModalOverlay = document.getElementById("add-mob-modal-overlay");
  const newMobInput = document.getElementById("new-mob-input");
  const createMobBtn = document.getElementById("create-mob-btn");
  
  // Close modal when clicking outside
  addMobModalOverlay?.addEventListener("click", (e) => {
    if (e.target === addMobModalOverlay) {
      addMobModalOverlay.classList.add("hidden");
      newMobInput.value = "";
    }
  });
  
  // Create mob handler
  async function createNewMob() {
    const name = newMobInput.value.trim();
    if (!name) {
      alert("Please enter a mob name.");
      return;
    }
    
    const safeName = name.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    
    // Check if mob already exists
    if (getUserMob(safeName)) {
      alert(`A mob named '${safeName}' already exists.`);
      return;
    }
    
    // Start with default spec from server
    try {
      const res = await fetch("/api/spec");
      const data = await res.json();
      const spec = data.spec;
      spec.short_name = safeName;
      spec.display_name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
      spec.identifier = `custom:${safeName}`;
      
      saveUserMob(safeName, spec);
      currentMobName = safeName;
      await loadMobList();
      await selectMob(safeName);
      
      // Close modal
      addMobModalOverlay.classList.add("hidden");
      newMobInput.value = "";
    } catch (err) {
      alert("Error creating mob: " + err.message);
    }
  }
  
  createMobBtn?.addEventListener("click", createNewMob);
  
  newMobInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      createNewMob();
    }
  });
}

// =====================
// LOAD TEMPLATE MODAL
// =====================
function initLoadTemplateModal() {
  const loadTemplateModalOverlay = document.getElementById("load-template-modal-overlay");
  const templateMobInput = document.getElementById("template-mob-input");
  const templateCreateBtn = document.getElementById("template-create-btn");
  
  // Close modal when clicking outside
  loadTemplateModalOverlay?.addEventListener("click", (e) => {
    if (e.target === loadTemplateModalOverlay) {
      loadTemplateModalOverlay.classList.add("hidden");
      templateMobInput.value = "";
      selectedTemplateId = null;
    }
  });
  
  // Create mob from template handler
  async function createMobFromTemplate() {
    const name = templateMobInput.value.trim();
    if (!name) {
      alert("Please enter a mob name.");
      return;
    }
    
    if (!selectedTemplateId) {
      alert("No template selected.");
      return;
    }
    
    const template = vanillaTemplates[selectedTemplateId];
    if (!template) {
      alert("Template not found.");
      return;
    }
    
    const safeName = name.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    
    // Check if mob already exists
    if (getUserMob(safeName)) {
      alert(`A mob named '${safeName}' already exists.`);
      return;
    }
    
    // Clone the template and customize
    const spec = JSON.parse(JSON.stringify(template));
    spec.short_name = safeName;
    spec.display_name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
    if (spec.identifier.startsWith("minecraft:")) {
      spec.identifier = `custom:${safeName}`;
    }

    // Try to pull the default texture for this template from the Mojang samples repo.
    const templateId = template.short_name || selectedTemplateId;
    const remoteTexture = await fetchTemplateTexture(templateId);
    if (remoteTexture) {
      saveUserMobTexture(safeName, remoteTexture);
    }
    
    saveUserMob(safeName, spec);
    currentMobName = safeName;
    await loadMobList();
    await selectMob(safeName);
    
    // Try to load template mob from database first, fall back to GitHub
    try {
      const dbRes = await fetch(`/api/template/mob/${encodeURIComponent(templateId)}`);
      if (dbRes.ok) {
        const dbData = await dbRes.json();
        console.log("[TEMPLATE] Loaded template from database:", dbData.mob);
        alert(`✅ Successfully loaded template mob "${dbData.mob.mob_name}" from database!`);
        // Successfully loaded from database
        await fetchAndDisplayGeometry(templateId, safeName);
      } else {
        // Database returned an error
        const errorData = await dbRes.json().catch(() => ({}));
        alert(`⚠️ Could not find template in database: ${errorData.detail || 'Unknown error'}\nFalling back to GitHub...`);
        console.warn("[TEMPLATE] Database template not found, falling back to GitHub");
        await fetchAndDisplayGeometry(templateId, safeName);
      }
    } catch (err) {
      // Network or other error
      alert(`⚠️ Failed to load template from database: ${err.message}\nFalling back to GitHub...`);
      console.warn("[TEMPLATE] Error loading from database, falling back to GitHub:", err);
      // Fall back to GitHub geometry
      await fetchAndDisplayGeometry(templateId, safeName);
    }
    
    // Close modal
    loadTemplateModalOverlay.classList.add("hidden");
    templateMobInput.value = "";
    selectedTemplateId = null;
  }
  
  templateCreateBtn?.addEventListener("click", createMobFromTemplate);
  
  templateMobInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      createMobFromTemplate();
    }
  });
}
