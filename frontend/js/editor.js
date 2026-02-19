// =====================
// SPEC EDITOR & VALIDATION
// =====================

const editor = document.getElementById("spec-editor");
const statusEl = document.getElementById("status");
const schemaView = document.getElementById("schema-view");
const validationBadge = document.getElementById("validation-badge");
const fileTreeEl = document.getElementById("file-tree");
const lineGutter = document.getElementById('line-gutter');
const specPre = document.getElementById('spec-pre');
const specContentWrapper = document.getElementById('spec-content-wrapper');
const specToggleSlider = document.getElementById('spec-toggle-slider');
const mobListEl = document.getElementById("mob-list");

function originalSpecKey(user, mob) { return `original_spec_${user}_${mob}`; }
function setOriginalSpec(user, mob, spec) {
  try { localStorage.setItem(originalSpecKey(user, mob), JSON.stringify(spec)); } catch (e) {}
}
function getOriginalSpec(user, mob) {
  try { const raw = localStorage.getItem(originalSpecKey(user, mob)); return raw ? JSON.parse(raw) : null; } catch (e) { return null; }
}

async function loadMobList() {
  const user = getCurrentUser();
  if (!user) {
    mobListEl.innerHTML = '<li style="color: var(--muted); padding: 1rem;">Please select a user first.</li>';
    return;
  }
  
  const mobs = getCurrentUserMobs();
  const mobNames = Object.keys(mobs);
  
  // Preserve existing checkbox states before rebuilding
  const prevChecked = {};
  mobListEl.querySelectorAll(".mob-item").forEach(item => {
    const n = item.querySelector(".mob-name")?.textContent;
    const c = item.querySelector("input[type='checkbox']");
    if (n && c) prevChecked[n] = c.checked;
  });

  mobListEl.innerHTML = "";
  mobNames.forEach(name => {
    const li = document.createElement("li");
    li.className = "mob-item" + (name === currentMobName ? " active" : "");
    
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = (name in prevChecked) ? prevChecked[name] : true; // Preserve state, default new mobs to checked
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
  
  // Sync geometry viewer with the mob's base geometry
  const geometryName = spec.geometry ? spec.geometry.replace('geometry.', '') : name;
  await fetchAndDisplayGeometry(geometryName, name);  // Pass mob name for texture loading
  
  // Update file tree preview
  updateFileTree(spec);

  // check if a og snapshot exists
  try {
    const user = getCurrentUser();
    const orig = getOriginalSpec(user, name);
    if (!orig) setOriginalSpec(user, name, spec);
  } catch (e) {}
  renderGlobalDiff();
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
  if (!specPre || !lineGutter) return;
  try {
    const DiffLib = (typeof Diff !== 'undefined') ? Diff : ((typeof diff !== 'undefined') ? diff : null);
    const diffLines = DiffLib && DiffLib.diffLines ? DiffLib.diffLines : null;
    const beforeStr = beforeSpec ? JSON.stringify(beforeSpec, null, 2) : '';
    const afterStr = afterSpec ? JSON.stringify(afterSpec, null, 2) : '';
    let raw = diffLines ? diffLines(beforeStr, afterStr) : null;
    if (!raw) {
      const a = beforeStr.split('\n');
      const b = afterStr.split('\n');
      raw = [];
      let ia = 0, ib = 0;
      while (ia < a.length || ib < b.length) {
        const va = a[ia] || '';
        const vb = b[ib] || '';
        if (va === vb) { 
          raw.push({ value: va + '\n' }); 
          ia++; ib++; 
        } else if (vb && a.slice(ia, ia+3).indexOf(vb) === -1) { 
          raw.push({ value: vb + '\n', added: true }); 
          ib++; 
        } else { 
          raw.push({ value: va + '\n', removed: true }); 
          ia++; 
        }
      }
    }
    let oldLine = 1; let newLine = 1;
    const contentParts = [];
    const gutterParts = [];

    raw.forEach(chunk => {
      const lines = (chunk.value || '').split('\n');
      if (lines.length && lines[lines.length-1] === '') lines.pop();
      lines.forEach(l => {
        if (chunk.added) {
          contentParts.push(`<div style="white-space:pre; padding:2px 6px; background:rgba(16,185,129,0.06); color:#10b981;">+ ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div style="padding:2px 6px; text-align:right; color: #a7f3d0;">→ ${newLine}</div>`);
          newLine++;
        } else if (chunk.removed) {
          contentParts.push(`<div style="white-space:pre; padding:2px 6px; background:rgba(239,68,68,0.06); color:#ef4444;">- ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div style="padding:2px 6px; text-align:right; color: #fecaca;">${oldLine} →</div>`);
          oldLine++;
        } else {
          contentParts.push(`<div style="white-space:pre; padding:2px 6px; color:var(--muted);">  ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div style="padding:2px 6px; text-align:right; color:var(--muted);">${oldLine} | ${newLine}</div>`);
          oldLine++; newLine++;
        }
      });
    });
    specPre.innerHTML = contentParts.join('');
    lineGutter.innerHTML = gutterParts.join('');
  } catch (e) {
    specPre.innerHTML = '<div style="color: var(--muted); padding:8px;">Could not compute diff</div>';
    lineGutter.textContent = '';
  }
}

function renderGlobalDiff() {
  // render diff b/w og & current editor
  try {
    const user = getCurrentUser();
    const mob = currentMobName;
    if (!user || !mob) return;
    const orig = getOriginalSpec(user, mob) || {};
    let curr = {};
    try { curr = JSON.parse(editor.value); } catch (e) { curr = {}; }
    showDiff(orig, curr);
  } catch (e) {
    console.warn('renderGlobalDiff failed', e);
  }
}

let currentSpecView = 'editor';
const specEditorContainerEl = document.getElementById('spec-editor-container');
const specDiffContainerEl = document.getElementById('spec-diff-container');
const diffScroll = document.getElementById('diff-scroll');

editor?.addEventListener && editor.addEventListener('input', () => {
  if (currentSpecView === 'diff') renderGlobalDiff();
});

const specViewEditorBtn = document.getElementById('spec-view-editor-btn');
const specViewDiffBtn = document.getElementById('spec-view-diff-btn');
const specViewToggle = document.getElementById('spec-view-toggle');

function moveToggleSlider(toBtn) {
  if (!specToggleSlider || !specViewToggle || !toBtn) return;
  const parentRect = specViewToggle.getBoundingClientRect();
  const b = toBtn.getBoundingClientRect();
  const left = b.left - parentRect.left + 2;
  specToggleSlider.style.left = left + 'px';
  specToggleSlider.style.width = (b.width - 4) + 'px';
}

function setSpecView(mode) {
  currentSpecView = mode;
  if (mode === 'diff') {
    try { specEditorContainerEl.style.display = 'none'; } catch (e) {}
    try { specDiffContainerEl.style.display = 'flex'; } catch (e) {}
    moveToggleSlider(specViewDiffBtn);
    try { renderGlobalDiff(); } catch (e) { console.warn('renderGlobalDiff error', e); }
    try { if (diffScroll) diffScroll.scrollTop = 0; } catch (e) {}
  } else {
    try { specEditorContainerEl.style.display = 'flex'; } catch (e) {}
    try { specDiffContainerEl.style.display = 'none'; } catch (e) {}
    moveToggleSlider(specViewEditorBtn);
    try { editor.focus(); } catch (e) {}
  }
}

specViewEditorBtn?.addEventListener && specViewEditorBtn.addEventListener('click', () => setSpecView('editor'));
specViewDiffBtn?.addEventListener && specViewDiffBtn.addEventListener('click', () => setSpecView('diff'));
window.requestAnimationFrame(() => setSpecView('editor'));
window.addEventListener && window.addEventListener('resize', () => {
  try { moveToggleSlider(currentSpecView === 'editor' ? specViewEditorBtn : specViewDiffBtn); } catch (e) {}
});

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
