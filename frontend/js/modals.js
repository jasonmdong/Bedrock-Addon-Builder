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
  
  // Generate a simple default placeholder texture (64x64 colored gradient)
  function generateDefaultTexture(mobName) {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    
    // Generate a color based on mob name hash
    let hash = 0;
    for (let i = 0; i < mobName.length; i++) {
      hash = mobName.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    
    // Fill with gradient
    const gradient = ctx.createLinearGradient(0, 0, 64, 64);
    gradient.addColorStop(0, `hsl(${hue}, 70%, 50%)`);
    gradient.addColorStop(1, `hsl(${(hue + 30) % 360}, 70%, 40%)`);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
    
    // Add some texture variation
    ctx.fillStyle = `hsla(${hue}, 60%, 60%, 0.3)`;
    for (let y = 0; y < 64; y += 8) {
      for (let x = 0; x < 64; x += 8) {
        if ((x + y) % 16 === 0) {
          ctx.fillRect(x, y, 8, 8);
        }
      }
    }
    
    return canvas.toDataURL('image/png');
  }
  
  // Fetch texture from GitHub bedrock-samples
  async function fetchGitHubTexture(mobName) {
    if (!mobName) return null;
    const base = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/textures/entity";
    const url = `${base}/${encodeURIComponent(mobName)}/${encodeURIComponent(mobName)}.png`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        console.warn(`[TEXTURE] No GitHub texture for ${mobName} (status ${res.status})`);
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
      console.warn(`[TEXTURE] Failed to fetch GitHub texture for ${mobName}:`, err);
      return null;
    }
  }
  
  // Create mob handler - Now uses AI generation!
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
    
    // Get LLM provider/key from localStorage if available
    const provider = localStorage.getItem("builder_llm_provider") || "";
    const apiKey = localStorage.getItem("builder_llm_api_key") || "";
    
    // Show loading state
    const originalBtnText = createMobBtn.textContent;
    createMobBtn.textContent = "🤖 Generating...";
    createMobBtn.disabled = true;
    
    try {
      console.log(`[AI-MOB] Generating complete mob: ${name}`);
      
      // Call the AI generation endpoint
      const res = await fetch("/api/mob/generate-complete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mob_name: name,
          provider: provider || undefined,
          api_key: apiKey || undefined
        })
      });
      
      if (!res.ok) {
        const errorData = await res.json().catch(() => ({}));
        throw new Error(errorData.detail || "AI generation failed");
      }
      
      const data = await res.json();
      const spec = data.mob;
      const geometry = data.geometry;
      const reasoning = data.reasoning;
      const similarMobs = data.similar_mobs || [];
      
      console.log(`[AI-MOB] Generated! Reasoning: ${reasoning}`);
      console.log(`[AI-MOB] Based on similar mobs: ${similarMobs.join(", ")}`);
      
      // Ensure spec has correct naming
      spec.short_name = safeName;
      spec.display_name = name.charAt(0).toUpperCase() + name.slice(1).replace(/_/g, " ");
      spec.identifier = `custom:${safeName}`;
      
      // Store geometry in spec
      if (geometry) {
        spec.geometry_json = geometry;
      }
      
      // Save the mob
      saveUserMob(safeName, spec);
      currentMobName = safeName;
      await loadMobList();
      await selectMob(safeName);
      
      // Step 3: Try to get texture from GitHub (based on mob name, e.g., "dragon" might match)
      console.log(`[TEXTURE] Step 3: Trying GitHub texture for: ${name}`);
      let textureData = await fetchGitHubTexture(name);
      
      // Step 4: If GitHub fails, use default texture
      if (!textureData) {
        console.log(`[TEXTURE] Step 4: GitHub failed, using generated default texture for: ${safeName}`);
        textureData = generateDefaultTexture(safeName);
      } else {
        console.log(`[TEXTURE] Successfully fetched from GitHub: ${name}`);
      }
      
      if (textureData && typeof saveUserMobTexture === "function") {
        saveUserMobTexture(safeName, textureData);
      }
      
      // Display the generated geometry if available
      if (geometry && typeof render3DGeometry === "function") {
        render3DGeometry(geometry, safeName);
      }
      
      // Close modal
      addMobModalOverlay.classList.add("hidden");
      newMobInput.value = "";
      
      // Show success message with details
      const similarInfo = similarMobs.length > 0 
        ? `\n\nBased on: ${similarMobs.slice(0, 3).join(", ")}` 
        : "";
      alert(`✨ AI Generated "${name}"!${similarInfo}`);
      
    } catch (err) {
      console.error("[AI-MOB] Generation failed:", err);
      alert("❌ AI generation failed: " + err.message + "\n\nFalling back to default...");
      
      // Fallback to basic spec
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
        
        addMobModalOverlay.classList.add("hidden");
        newMobInput.value = "";
      } catch (fallbackErr) {
        alert("Error creating mob: " + fallbackErr.message);
      }
    } finally {
      createMobBtn.textContent = originalBtnText;
      createMobBtn.disabled = false;
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
  
  // Fetch texture from GitHub bedrock-samples (inline version for modals.js)
  async function fetchGitHubTexture(mobName) {
    if (!mobName) return null;
    const base = "https://raw.githubusercontent.com/Mojang/bedrock-samples/main/resource_pack/textures/entity";
    const url = `${base}/${encodeURIComponent(mobName)}/${encodeURIComponent(mobName)}.png`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        console.warn(`[TEXTURE] No GitHub texture for ${mobName} (status ${res.status})`);
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
      console.warn(`[TEXTURE] Failed to fetch GitHub texture for ${mobName}:`, err);
      return null;
    }
  }
  
  // Generate a simple default placeholder texture (16x16 colored square)
  function generateDefaultTexture(mobName) {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    
    // Generate a color based on mob name hash
    let hash = 0;
    for (let i = 0; i < mobName.length; i++) {
      hash = mobName.charCodeAt(i) + ((hash << 5) - hash);
    }
    const hue = Math.abs(hash) % 360;
    
    // Fill with gradient
    const gradient = ctx.createLinearGradient(0, 0, 64, 64);
    gradient.addColorStop(0, `hsl(${hue}, 70%, 50%)`);
    gradient.addColorStop(1, `hsl(${(hue + 30) % 360}, 70%, 40%)`);
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
    
    // Add some texture variation
    ctx.fillStyle = `hsla(${hue}, 60%, 60%, 0.3)`;
    for (let y = 0; y < 64; y += 8) {
      for (let x = 0; x < 64; x += 8) {
        if ((x + y) % 16 === 0) {
          ctx.fillRect(x, y, 8, 8);
        }
      }
    }
    
    return canvas.toDataURL('image/png');
  }
  
  // Create mob from selected template or AI generation
  async function createMobFromTemplate() {
    const name = templateMobInput.value.trim();
    if (!name) {
      alert("Please enter a mob name.");
      return;
    }
    
    // The template mob name is stored in a data attribute when modal opens from search
    const templateMobName = templateMobInput.dataset.templateMob || inputValue;
    const customName = inputValue;
    const customSafeName = customName.toLowerCase().replace(/[^a-z0-9_]/g, "_");
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
    
    let newSpec = null;
    let source = "unknown";
    let baseMobForTexture = null;  // The vanilla mob name for texture lookup
    
    try {
      // Step 1: Try to load from database first
      console.log(`[TEMPLATE] Searching database for: ${templateMobName}`);
      const dbRes = await fetch(`/api/template/mob/${encodeURIComponent(templateMobName)}`);
      
      if (dbRes.ok) {
        // Found in database - use as template
        const dbData = await dbRes.json();
        const templateMob = dbData.mob;
        source = "database";
        
        // Extract the base mob name (for texture lookup from GitHub)
        // The mob_name in DB might be "creeper" or "fire_dragon_user123"
        baseMobForTexture = templateMob.mob_name || templateMobName;
        
        // Create a new spec based on the template
        newSpec = {
          ...templateMob,
          short_name: customSafeName,
          display_name: customName.charAt(0).toUpperCase() + customName.slice(1).replace(/_/g, " "),
          identifier: `custom:${customSafeName}`
        };
        console.log(`[TEMPLATE] Loaded from database: ${baseMobForTexture}`);
        
      } else if (dbRes.status === 404) {
        // Step 2: Not in database - use AI generation with similar mobs
        console.log(`[TEMPLATE] Not in database, using complete AI generation for: ${templateMobName}`);
        
        // Get LLM provider/key from localStorage if available
        const provider = localStorage.getItem("builder_llm_provider") || "";
        const apiKey = localStorage.getItem("builder_llm_api_key") || "";
        
        // Show loading indicator
        templateCreateBtn.textContent = "🤖 AI Generating...";
        templateCreateBtn.disabled = true;
        
        const genRes = await fetch("/api/mob/generate-complete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            mob_name: templateMobName,
            provider: provider || undefined,
            api_key: apiKey || undefined
          })
        });
        
        // Reset button
        templateCreateBtn.textContent = "Create";
        templateCreateBtn.disabled = false;
        
        if (!genRes.ok) {
          const errorData = await genRes.json().catch(() => ({}));
          throw new Error(errorData.detail || "AI generation failed");
        }
        
        const genData = await genRes.json();
        newSpec = genData.mob;
        source = "ai_generated";
        
        // Store the generated geometry in the spec
        if (genData.geometry) {
          newSpec.geometry_json = genData.geometry;
        }
        
        const reasoning = genData.reasoning || "";
        const similarMobs = genData.similar_mobs || [];
        
        console.log(`[TEMPLATE] AI generated complete mob!`);
        console.log(`[TEMPLATE] Reasoning: ${reasoning}`);
        console.log(`[TEMPLATE] Based on similar mobs: ${similarMobs.join(", ") || "none"}`);
        
      } else {
        // Other error
        const errorData = await dbRes.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to load template");
      }
      
      // Ensure spec has correct naming
      newSpec.short_name = customSafeName;
      newSpec.display_name = customName.charAt(0).toUpperCase() + customName.slice(1).replace(/_/g, " ");
      newSpec.identifier = `custom:${customSafeName}`;
      
      // Save the mob
      saveUserMob(customSafeName, newSpec);
      currentMobName = customSafeName;
      await loadMobList();
      await selectMob(customSafeName);
      
      // Step 3: Try to get texture from GitHub
      // For DB templates, use the base mob name
      // For AI-generated, try the template name (might match a vanilla mob like "dragon")
      let textureData = null;
      const textureMobName = baseMobForTexture || templateMobName;
      
      console.log(`[TEXTURE] Step 3: Trying GitHub texture for: ${textureMobName}`);
      textureData = await fetchGitHubTexture(textureMobName);
      
      // Step 4: If GitHub fails, use default texture
      if (!textureData) {
        console.log(`[TEXTURE] Step 4: GitHub failed, using generated default texture for: ${customSafeName}`);
        textureData = generateDefaultTexture(customSafeName);
      } else {
        console.log(`[TEXTURE] Successfully fetched from GitHub: ${textureMobName}`);
      }
      
      // Save the texture
      if (textureData && typeof saveUserMobTexture === "function") {
        saveUserMobTexture(customSafeName, textureData);
        console.log(`[TEXTURE] Saved texture for: ${customSafeName}`);
      }
      
      // Display success message
      if (source === "ai_generated") {
        alert(`✨ AI-generated "${customName}" with custom geometry!`);
      } else {
        alert(`✅ Created "${customName}" from template "${baseMobForTexture}"!`);
      }
      
      // Load geometry display
      // Step 1: For database templates, use geometry from the database if available
      // Step 2: For AI-generated, use the generated geometry
      // Fallback: Fetch from GitHub
      if (source === "database" && newSpec.mob_geometry) {
        // Database has geometry stored - use it directly
        console.log(`[GEOMETRY] Step 1: Using geometry from database for: ${customSafeName}`);
        if (typeof render3DGeometry === "function") {
          render3DGeometry(newSpec.mob_geometry, customSafeName);
        }
      } else if (source === "ai_generated" && newSpec.geometry_json && typeof render3DGeometry === "function") {
        // AI generated geometry
        console.log(`[GEOMETRY] Step 2: Rendering AI-generated geometry for: ${customSafeName}`);
        render3DGeometry(newSpec.geometry_json, customSafeName);
      } else {
        // Fallback: Fetch from GitHub
        console.log(`[GEOMETRY] Fallback: Fetching from GitHub for: ${baseMobForTexture || customSafeName}`);
        const geometryMob = baseMobForTexture || customSafeName;
        await fetchAndDisplayGeometry(geometryMob, customSafeName);
      }
      
      // Close modal
      loadTemplateModalOverlay.classList.add("hidden");
      templateMobInput.value = "";
      templateMobInput.dataset.templateMob = "";
      
    } catch (err) {
      alert(`❌ Error creating mob: ${err.message}`);
      console.error("[TEMPLATE] Error:", err);
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
    await fetchAndDisplayGeometry(templateId);
    
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
