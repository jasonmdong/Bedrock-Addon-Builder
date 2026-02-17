// =====================
// SIDEBAR RESIZER
// =====================
function initResizer() {
  const sidebar = document.getElementById("sidebar");
  const resizer = document.getElementById("resizer");
  let isResizing = false;

  resizer.addEventListener("mousedown", (e) => {
    isResizing = true;
    document.body.classList.add("resizing");
  });

  window.addEventListener("mousemove", (e) => {
    if (!isResizing) return;
    const newWidth = e.clientX;
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
    
    // Fetch and display geometry from bedrock-samples
    await fetchAndDisplayGeometry(templateId, safeName);  // Pass mob name for texture
    
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
