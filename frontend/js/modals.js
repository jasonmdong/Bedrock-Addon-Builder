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
let allTemplateMobNames = []; // Store all available mob names from database

function initLoadTemplateModal() {
  const loadTemplateModalOverlay = document.getElementById("load-template-modal-overlay");
  const templateMobInput = document.getElementById("template-mob-input");
  const templateCreateBtn = document.getElementById("template-create-btn");
  const datalist = document.getElementById("template-mob-suggestions") || createDatalist();
  
  // Create datalist element if it doesn't exist
  function createDatalist() {
    const dl = document.createElement("datalist");
    dl.id = "template-mob-suggestions";
    document.body.appendChild(dl);
    templateMobInput?.setAttribute("list", "template-mob-suggestions");
    return dl;
  }
  
  // Load all mob names from database when modal opens
  async function loadTemplateMobNames() {
    try {
      const res = await fetch("/api/template/mobs");
      if (res.ok) {
        const data = await res.json();
        allTemplateMobNames = data.mobs || [];
        
        // Populate datalist for autocomplete
        datalist.innerHTML = "";
        allTemplateMobNames.forEach(mobName => {
          const option = document.createElement("option");
          option.value = mobName;
          datalist.appendChild(option);
        });
        
        console.log(`[TEMPLATE] Loaded ${allTemplateMobNames.length} mob names from database`);
      }
    } catch (err) {
      console.warn("[TEMPLATE] Failed to load mob names:", err);
    }
  }
  
  // Show modal and load names
  const originalShowModal = window.showLoadTemplateModal;
  window.showLoadTemplateModal = function() {
    if (originalShowModal) originalShowModal();
    loadTemplateMobNames();
  };
  
  // Close modal when clicking outside
  loadTemplateModalOverlay?.addEventListener("click", (e) => {
    if (e.target === loadTemplateModalOverlay) {
      loadTemplateModalOverlay.classList.add("hidden");
      templateMobInput.value = "";
    }
  });
  
  // Create mob from selected template
  async function createMobFromTemplate() {
    const inputValue = templateMobInput.value.trim();
    if (!inputValue) {
      alert("Please enter a name for your new mob.");
      return;
    }
    
    // The template mob name is stored in a data attribute when modal opens from search
    const templateMobName = templateMobInput.dataset.templateMob || inputValue;
    
    // If no template is explicitly set, validate the input is a valid database mob
    if (!templateMobInput.dataset.templateMob && !allTemplateMobNames.includes(inputValue)) {
      alert(`"${inputValue}" is not available in the database.\nPlease select from the suggestions.`);
      return;
    }
    
    const customName = inputValue;
    const customSafeName = customName.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    
    // Check if mob already exists
    if (getUserMob(customSafeName)) {
      alert(`A mob named '${customSafeName}' already exists.`);
      return;
    }
    
    try {
      // Load the template mob from database
      const dbRes = await fetch(`/api/template/mob/${encodeURIComponent(templateMobName)}`);
      
      if (!dbRes.ok) {
        const errorData = await dbRes.json().catch(() => ({}));
        throw new Error(errorData.detail || 'Failed to load template');
      }
      
      const dbData = await dbRes.json();
      const templateMob = dbData.mob;
      
      // Create a new spec based on the template
      const newSpec = {
        ...templateMob,
        short_name: customSafeName,
        display_name: customName.charAt(0).toUpperCase() + customName.slice(1).replace(/_/g, " "),
        identifier: `custom:${customSafeName}`
      };
      
      // Remember the vanilla template name so geometry can be resolved on reload
      newSpec._template_base = templateMobName;

      // Fetch geometry from bedrock-samples and embed it into the spec
      try {
        const geoRes = await fetch(`/api/geometry/${encodeURIComponent(templateMobName)}`);
        if (geoRes.ok) {
          const geoData = await geoRes.json();
          if (geoData.geometry && geoData.geometry["minecraft:geometry"]) {
            newSpec.geometry_json = geoData.geometry;
          }
        }
      } catch (e) {
        console.warn(`[TEMPLATE] Could not fetch geometry for ${templateMobName}:`, e);
      }

      // Save the custom mob
      saveUserMob(customSafeName, newSpec);
      currentMobName = customSafeName;
      await loadMobList();
      await selectMob(customSafeName);
      
      alert(`✅ Successfully created "${customName}" from "${templateMobName}"!`);
      
      // Close modal
      loadTemplateModalOverlay.classList.add("hidden");
      templateMobInput.value = "";
      templateMobInput.dataset.templateMob = "";
    } catch (err) {
      alert(`❌ Error creating mob: ${err.message}`);
      console.error("[TEMPLATE] Error:", err);
    }
  }
  
  templateCreateBtn?.addEventListener("click", createMobFromTemplate);
  
  templateMobInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      createMobFromTemplate();
    }
  });
  
  // Load names on first modal init
  loadTemplateMobNames();
  
  // Export function to be called from builder.js when opening modal
  window.loadTemplateMobNamesFromDB = loadTemplateMobNames;
}
