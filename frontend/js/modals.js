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
  
  // Create mob handler - creates a blank spec with just the name, no LLM call
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
    
    // Build a blank spec from the backend default, then apply the name
    try {
      const res = await fetch("/api/spec/default");
      if (!res.ok) throw new Error(`Server error: ${res.status}`);
      const spec = await res.json();

      // Apply the user-provided name
      spec.display_name = name;
      spec.short_name = safeName;
      spec.identifier = `custom:${safeName}`;

      saveUserMob(safeName, spec);
      currentMobName = safeName;
      await loadMobList();
      await selectMob(safeName);

      setStatus(`Created blank mob "${name}" — use the AI prompt below to generate traits.`);

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
    
    const safeName = name.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    
    // Check if mob already exists
    if (getUserMob(safeName)) {
      alert(`A mob named '${safeName}' already exists.`);
      return;
    }

    // Database template path: templateMob stored in dataset by builder.js search input
    const dbTemplateMob = templateMobInput.dataset.templateMob;

    if (dbTemplateMob) {
      // Fetch template mob from database API and convert to a proper spec
      try {
        const res = await fetch(`/api/template/mob/${encodeURIComponent(dbTemplateMob)}`);
        if (!res.ok) throw new Error(`Failed to fetch template: ${res.statusText}`);
        const data = await res.json();
        const dbMob = data.mob || data;

        // Build a proper spec from the database mob fields + defaults
        const defaultRes = await fetch("/api/spec");
        const defaultData = await defaultRes.json();
        const spec = defaultData.spec || {};

        spec.short_name = safeName;
        spec.display_name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
        spec.identifier = `custom:${safeName}`;
        spec._template_base = dbTemplateMob;

        // Fetch the real Mojang geometry so it matches the Mojang texture UV layout.
        // The database mob_geometry is LLM-generated and won't align with the
        // official texture, so we always prefer the bedrock-samples geometry.
        try {
          const geoRes = await fetch(`/api/geometry/${encodeURIComponent(dbTemplateMob)}`);
          if (geoRes.ok) {
            const geoData = await geoRes.json();
            if (geoData.geometry && geoData.geometry["minecraft:geometry"]) {
              spec.geometry_json = geoData.geometry;
              try {
                const geoId = geoData.geometry["minecraft:geometry"][0]["description"]["identifier"];
                if (geoId) spec.geometry = geoId;
              } catch (e) { /* use default geometry */ }
            }
          }
        } catch (e) {
          console.warn(`[TEMPLATE] Could not fetch Mojang geometry for ${dbTemplateMob}:`, e);
        }

        // Try to pull the default texture from the Mojang samples repo
        const remoteTexture = await fetchTemplateTexture(dbTemplateMob);
        if (remoteTexture) {
          saveUserMobTexture(safeName, remoteTexture);
        }

        saveUserMob(safeName, spec);
        currentMobName = safeName;
        await loadMobList();
        await selectMob(safeName);
      } catch (err) {
        alert("Error creating mob from database template: " + err.message);
        return;
      }
    } else if (selectedTemplateId) {
      // Legacy vanilla template path
      const template = vanillaTemplates[selectedTemplateId];
      if (!template) {
        alert("Template not found.");
        return;
      }

      const spec = JSON.parse(JSON.stringify(template));
      spec.short_name = safeName;
      spec.display_name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
      if (spec.identifier.startsWith("minecraft:")) {
        spec.identifier = `custom:${safeName}`;
      }

      const templateId = template.short_name || selectedTemplateId;
      const remoteTexture = await fetchTemplateTexture(templateId);
      if (remoteTexture) {
        saveUserMobTexture(safeName, remoteTexture);
      }

      saveUserMob(safeName, spec);
      currentMobName = safeName;
      await loadMobList();
      await selectMob(safeName);
      await fetchAndDisplayGeometry(templateId, safeName);
    } else {
      alert("No template selected.");
      return;
    }
    
    // Close modal
    loadTemplateModalOverlay.classList.add("hidden");
    templateMobInput.value = "";
    templateMobInput.dataset.templateMob = "";
    selectedTemplateId = null;
  }
  
  templateCreateBtn?.addEventListener("click", createMobFromTemplate);
  
  templateMobInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      createMobFromTemplate();
    }
  });
}
