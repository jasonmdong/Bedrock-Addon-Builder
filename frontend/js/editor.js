// =====================
// SPEC EDITOR & VALIDATION
// =====================

const editor = document.getElementById("spec-editor");
const statusEl = document.getElementById("status");
const schemaView = document.getElementById("schema-view");
const validationBadge = document.getElementById("validation-badge");
const fileTreeEl = document.getElementById("file-tree");
const diffContent = document.getElementById("llm-diff-content");
const mobListEl = document.getElementById("mob-list");

async function loadMobList() {
  const user = getCurrentUser();
  if (!user) {
    mobListEl.innerHTML = '<li style="color: var(--muted); padding: 1rem;">Please select a user first.</li>';
    return;
  }
  
  const mobs = getCurrentUserMobs();
  const mobNames = Object.keys(mobs);
  
  mobListEl.innerHTML = "";
  mobNames.forEach(name => {
    const li = document.createElement("li");
    li.className = "mob-item" + (name === currentMobName ? " active" : "");
    
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = true; // Default to selected
    cb.onclick = (e) => e.stopPropagation();
    li.appendChild(cb);
    
    const span = document.createElement("span");
    span.className = "mob-name";
    span.textContent = name;
    li.appendChild(span);
    
    const del = document.createElement("button");
    del.className = "delete-btn";
    del.textContent = "🗑";
    del.onclick = (e) => deleteMob(e, name);
    li.appendChild(del);
    
    li.onclick = () => selectMob(name);
    mobListEl.appendChild(li);
  });
  
  // If current mob is gone, pick another
  if (mobNames.length > 0 && !mobNames.includes(currentMobName)) {
    selectMob(mobNames[0]);
  }
}

async function selectMob(name) {
  currentMobName = name;
  setStatus(`Loading ${name}...`);
  
  const spec = getUserMob(name);
  if (!spec) {
    setStatus(`Failed to load ${name}`, true);
    return;
  }
  
  editor.value = JSON.stringify(spec, null, 2);
  
  // Load schema from server (it's static)
  try {
    const res = await fetch("/api/spec");
    const data = await res.json();
    schemaView.textContent = JSON.stringify(data.schema || {}, null, 2);
  } catch (e) {
    console.log("Could not load schema", e);
  }
  
  setStatus(`Loaded ${name} at ` + new Date().toLocaleTimeString());
  
  // Update UI active state
  document.querySelectorAll(".mob-item").forEach(el => {
    el.classList.toggle("active", el.querySelector(".mob-name").textContent === name);
  });

  // Load texture into painter automatically
  loadTextureIntoPainter(name);
  
  // Update file tree preview
  updateFileTree(spec);
}

async function loadSpec() {
  const user = getCurrentUser();
  if (!user) {
    setStatus("Please select or create a user to get started.");
    return;
  }
  
  await loadMobList();
  
  const mobs = Object.keys(getCurrentUserMobs());
  
  if (mobs.length === 0) {
    // If no mobs exist, create a default one from server template
    currentMobName = "my_first_mob";
    setStatus("Creating your first mob...");
    try {
      const res = await fetch("/api/spec");
      const data = await res.json();
      const spec = data.spec;
      spec.short_name = "my_first_mob";
      spec.display_name = "My First Mob";
      spec.identifier = "custom:my_first_mob";
      
      saveUserMob(currentMobName, spec);
      editor.value = JSON.stringify(spec, null, 2);
      schemaView.textContent = JSON.stringify(data.schema || {}, null, 2);
      await loadMobList();
      setStatus("Created your first mob! Edit it and click Save.");
    } catch (e) {
      setStatus("Could not load default spec from server.", true);
    }
  } else {
    // Select existing currentMobName or first in list
    if (mobs.includes(currentMobName)) {
      await selectMob(currentMobName);
    } else {
      await selectMob(mobs[0]);
    }
  }
}

async function saveSpec() {
  let spec;
  try {
    spec = JSON.parse(editor.value);
  } catch (err) {
    setStatus("JSON parse error: " + err.message, true);
    showValidationBadge(false, "Invalid JSON");
    return null;
  }
  
  const user = getCurrentUser();
  if (!user) {
    setStatus("No user logged in.", true);
    return null;
  }
  
  // Validate spec against schema via server
  setStatus("Validating spec...");
  showValidationBadge(null, "Validating...");
  try {
    const res = await fetch("/api/spec/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(spec)
    });
    const result = await res.json();
    
    if (!result.valid) {
      const errorMsg = result.error || "Validation failed";
      const field = result.field ? ` (field: ${result.field})` : "";
      setStatus(`❌ Validation error: ${errorMsg}${field}`, true);
      showValidationBadge(false, `Error in ${result.field || 'spec'}`);
      return null;
    }
    
    // Use the validated spec from server (fills defaults)
    spec = result.spec;
    showValidationBadge(true, "Valid");
  } catch (err) {
    console.error("Validation failed", err);
    setStatus("⚠️ Could not validate spec: " + err.message, true);
    showValidationBadge(null, "Offline");
    // Continue anyway for offline mode
  }
  
  // If short_name changed, we treat it as a rename/move
  const targetName = spec.short_name || currentMobName;
  
  // If renaming, delete old mob
  if (targetName !== currentMobName && currentMobName) {
    deleteUserMob(currentMobName);
  }
  
  saveUserMob(targetName, spec);
  currentMobName = targetName;
  setStatus(`✅ Saved ${currentMobName} locally.`);
  await loadMobList();
  
  // Refresh painter in case color changed in JSON
  loadTextureIntoPainter(currentMobName);
  
  // Update file tree preview
  updateFileTree(spec);
  
  return spec;
}

function showValidationBadge(isValid, text) {
  if (!validationBadge) return;
  if (isValid === null) {
    // Neutral/loading state
    validationBadge.style.display = "inline-block";
    validationBadge.style.background = "var(--muted)";
    validationBadge.style.color = "var(--bg)";
    validationBadge.textContent = text || "⏳ Checking...";
  } else if (isValid) {
    // Valid
    validationBadge.style.display = "inline-block";
    validationBadge.style.background = "#22c55e";
    validationBadge.style.color = "white";
    validationBadge.textContent = "✅ " + (text || "Valid");
  } else {
    // Invalid
    validationBadge.style.display = "inline-block";
    validationBadge.style.background = "var(--danger)";
    validationBadge.style.color = "white";
    validationBadge.textContent = "❌ " + (text || "Invalid");
  }
}

function updateFileTree(spec) {
  if (!fileTreeEl || !spec) return;
  
  const shortName = spec.short_name || "mob";
  const hasCustomGeo = spec.geometry_json && typeof spec.geometry_json === 'object';
  
  let tree = `
<div style="color: var(--muted); margin-bottom: 0.5rem;">┌─ <strong>Resource Pack (RP)</strong></div>
<div style="padding-left: 1rem;">
  ├─ 📄 manifest.json<br>
  ├─ 🖼️ pack_icon.png<br>
  ├─ 📂 entity/<br>
  │&nbsp;&nbsp; └─ ${shortName}.client.entity.json<br>
  ├─ 📂 models/entity/${hasCustomGeo ? '<br>  │&nbsp;&nbsp; └─ ' + shortName + '.geo.json<br>' : '<br>'}
  ├─ 📂 textures/entity/${shortName}/<br>
  │&nbsp;&nbsp; ├─ ${shortName}.png<br>
  │&nbsp;&nbsp; ├─ ${shortName}_mers.tga<br>
  │&nbsp;&nbsp; └─ ${shortName}.texture_set.json<br>
  └─ 📂 texts/<br>
  &nbsp;&nbsp;&nbsp;&nbsp; └─ en_US.lang
</div>
<div style="color: var(--muted); margin-top: 1rem; margin-bottom: 0.5rem;">└─ <strong>Behavior Pack (BP)</strong></div>
<div style="padding-left: 1rem;">
  ├─ 📄 manifest.json<br>
  ├─ 📂 entities/<br>
  │&nbsp;&nbsp; └─ ${shortName}.entity.json<br>
  └─ 📂 texts/<br>
  &nbsp;&nbsp;&nbsp;&nbsp; └─ en_US.lang
</div>
  `.trim();
  
  fileTreeEl.innerHTML = tree;
}

function showDiff(beforeSpec, afterSpec) {
  if (!diffContent) return;
  
  const changes = [];
  const allKeys = new Set([...Object.keys(beforeSpec), ...Object.keys(afterSpec)]);
  
  allKeys.forEach(key => {
    const before = JSON.stringify(beforeSpec[key], null, 2);
    const after = JSON.stringify(afterSpec[key], null, 2);
    
    if (before !== after) {
      changes.push({ key, before: beforeSpec[key], after: afterSpec[key] });
    }
  });
  
  if (changes.length === 0) {
    diffContent.innerHTML = '<div style="color: var(--muted); font-style: italic; padding: 1rem; text-align: center;">No changes detected</div>';
  } else {
    let html = '<div style="display: flex; flex-direction: column; gap: 1rem;">';
    
    changes.forEach(change => {
      const beforeStr = JSON.stringify(change.before, null, 2);
      const afterStr = JSON.stringify(change.after, null, 2);
      
      html += `
        <div style="border: 2px solid var(--border); border-radius: 8px; overflow: hidden;">
          <div style="background: var(--primary); color: white; padding: 0.75rem; font-weight: bold; font-size: 0.9rem;">
            🔑 ${escapeHtml(change.key)}
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0;">
            <div style="background: #3d1a1a; border-right: 1px solid var(--border); padding: 1rem;">
              <div style="color: #ff6b6b; font-weight: bold; margin-bottom: 0.75rem; font-size: 0.85rem;">❌ BEFORE</div>
              <pre style="margin: 0; white-space: pre-wrap; word-break: break-word; color: #ffcccc; font-size: 0.8rem; line-height: 1.4;">${escapeHtml(beforeStr)}</pre>
            </div>
            <div style="background: #1a3d1a; padding: 1rem;">
              <div style="color: #51cf66; font-weight: bold; margin-bottom: 0.75rem; font-size: 0.85rem;">✅ AFTER</div>
              <pre style="margin: 0; white-space: pre-wrap; word-break: break-word; color: #ccffcc; font-size: 0.8rem; line-height: 1.4;">${escapeHtml(afterStr)}</pre>
            </div>
          </div>
        </div>
      `;
    });
    
    html += '</div>';
    diffContent.innerHTML = html;
  }
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

async function deleteMob(event, name) {
  event.stopPropagation();
  if (!confirm(`Delete mob '${name}'?`)) return;
  
  if (deleteUserMob(name)) {
    deleteUserMobTexture(name); // Also delete texture from localStorage
    setStatus(`Deleted ${name}`);
    // If we deleted the active mob, reset currentMobName
    if (currentMobName === name) {
      currentMobName = ""; 
    }
    await loadMobList();
    if (!currentMobName) {
      const first = mobListEl.querySelector(".mob-item .mob-name");
      if (first) selectMob(first.textContent);
      else loadSpec();
    }
  } else {
    setStatus(`Failed to delete ${name}`, true);
  }
}
