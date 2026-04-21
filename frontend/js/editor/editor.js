// =====================
// SPEC EDITOR & VALIDATION
// =====================

console.log('[editor.js] Loading...');

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
  
  // If current mob is gone, update the variable but don't call selectMob here —
  // loadSpec() handles initial selection and avoids double geometry fetches.
  if (mobNames.length > 0 && !mobNames.includes(currentMobName)) {
    currentMobName = mobNames[0];
  }
  try {
    if (typeof updateTierUsagePanel === "function") updateTierUsagePanel();
  } catch (e) { /* ignore */ }
}

async function selectMob(name) {
  currentMobName = name;
  localStorage.setItem("builder_current_mob", name);
  setStatus(`Loading ${name}...`);
  
  const spec = getUserMob(name);
  if (!spec) {
    setStatus(`Failed to load ${name}`, true);
    return;
  }
  
  editor.value = JSON.stringify(spec, null, 2);
  editor.scrollTop = 0; // Scroll to top after loading
  editor.selectionStart = 0; // Move cursor to beginning
  editor.selectionEnd = 0;
  
  // Load spec into form editor
  if (typeof loadSpecIntoForm === 'function') {
    loadSpecIntoForm(spec);
  }
  
  // Load schema from server (it's static)
  try {
    const res = await fetch("/api/spec");
    const data = await res.json();
    schemaView.textContent = JSON.stringify(data.schema || {}, null, 2);
  } catch (e) {
    console.log("Could not load schema", e);
  }
  
  setStatus(`Loaded ${name} at ` + new Date().toLocaleTimeString());
  
  // Show inspiration mobs if this was AI-generated
  if (spec._inspiration_mobs && spec._inspiration_mobs.length > 0) {
    const inspirationList = spec._inspiration_mobs.slice(0, 3).join(", ");
    const more = spec._inspiration_mobs.length > 3 ? ` +${spec._inspiration_mobs.length - 3} more` : "";
    setStatus(`${name} - inspired by: ${inspirationList}${more}`);
  }
  
  // Update UI active state
  document.querySelectorAll(".mob-item").forEach(el => {
    el.classList.toggle("active", el.querySelector(".mob-name").textContent === name);
  });

  // Extract texture dimensions from geometry and update painter canvas size
  try {
    const geoJson = spec.geometry_json;
    if (geoJson && geoJson["minecraft:geometry"] && geoJson["minecraft:geometry"][0]) {
      const desc = geoJson["minecraft:geometry"][0].description || {};
      const tw = desc.texture_width || 64;
      const th = desc.texture_height || 64;
      setPainterDimensions(tw, th);
    } else {
      setPainterDimensions(64, 64);
    }
  } catch (e) {
    setPainterDimensions(64, 64);
  }

  // Load texture into painter automatically
  loadTextureIntoPainter(name);
  
  // Sync geometry viewer with the mob's base geometry
  // If geometry_json is already embedded, render it directly instead of fetching
  if (spec.geometry_json && spec.geometry_json["minecraft:geometry"]) {
    const geometryContainer = document.getElementById("geometry-container");
    const geometryViewer = document.getElementById("geometry-viewer");
    const geometryCopy = document.getElementById("geometry-copy");
    const geometryUrl = document.getElementById("geometry-url");
    if (geometryContainer && geometryViewer) {
      const formattedJson = JSON.stringify(spec.geometry_json, null, 2);
      geometryViewer.textContent = formattedJson;
      if (geometryCopy) geometryCopy.dataset.json = formattedJson;
      const baseName = spec._template_base || spec.geometry.replace('geometry.', '');
      if (geometryUrl) {
        geometryUrl.href = `https://github.com/Mojang/bedrock-samples/tree/main/resource_pack/models/entity`;
        geometryUrl.textContent = `View on GitHub: ${baseName}.geo.json`;
      }
      geometryContainer.style.display = "block";
      render3DGeometry(spec.geometry_json, name);
    }
  } else {
    // Use _template_base (vanilla mob name) if available, otherwise derive from geometry field
    // For legacy mobs without _template_base, try stripping _custom suffix from short_name
    let geometryName = spec._template_base;
    if (!geometryName) {
      const stripped = (spec.short_name || name).replace(/_custom$/, '');
      geometryName = stripped !== (spec.short_name || name) ? stripped : (spec.geometry ? spec.geometry.replace('geometry.', '') : name);
    }
    await fetchAndDisplayGeometry(geometryName, name);
  }
  
  // Update file tree preview
  updateFileTree(spec);

  // Load animations into the 3D viewer panel
  if (typeof loadAnimationsFromSpec === "function") {
    loadAnimationsFromSpec(spec.animation_json || null);
  }

  // check if a og snapshot exists
  try {
    const user = getCurrentUser();
    const orig = getOriginalSpec(user, name);
    if (!orig) setOriginalSpec(user, name, spec);
  } catch (e) {}
  renderGlobalDiff();
  try { if (typeof renderLlmHistory === 'function') renderLlmHistory(); } catch (e) {}

  // Notify animation panel so it can restore saved animations for this mob
  document.dispatchEvent(new CustomEvent('mob-loaded', { detail: spec }));
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
      await loadMobList();
      // Call selectMob to trigger full UI setup including geometry rendering
      await selectMob(currentMobName);
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
          contentParts.push(`<div class="diff-line added">+ ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div class="gutter-line added">→ ${newLine}</div>`);
          newLine++;
        } else if (chunk.removed) {
          contentParts.push(`<div class="diff-line removed">- ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div class="gutter-line removed">${oldLine} →</div>`);
          oldLine++;
        } else {
          contentParts.push(`<div class="diff-line context">  ${escapeHtml(l)}</div>`);
          gutterParts.push(`<div class="gutter-line context">${oldLine} | ${newLine}</div>`);
          oldLine++; newLine++;
        }
      });
    });
    specPre.innerHTML = contentParts.join('');
    lineGutter.innerHTML = gutterParts.join('');
    try { forceRepaintDiff(); } catch (e) {}
    try {
      if (specPre && lineGutter) {
        lineGutter.scrollTop = specPre.scrollTop;
        if (!specPre._gutterSyncAttached) {
          specPre.addEventListener('scroll', () => { lineGutter.scrollTop = specPre.scrollTop; });
          specPre._gutterSyncAttached = true;
        }
        const firstChange = specPre.querySelector('.diff-line.added, .diff-line.removed');
        if (firstChange && typeof firstChange.scrollIntoView === 'function') {
          firstChange.scrollIntoView({ block: 'nearest' });
        }
      }
    } catch (e) {}
  } catch (e) {
    specPre.innerHTML = '<div style="color: var(--muted); padding:8px;">Could not compute diff</div>';
    lineGutter.textContent = '';
  }
}

function forceRepaintDiff() {
  try {
    const nodes = [specDiffContainerEl, specPre, lineGutter].filter(Boolean);
    nodes.forEach(n => {
      n.style.willChange = 'opacity, transform';
      n.style.transform = 'translateZ(0)';
      n.style.backfaceVisibility = 'hidden';
    });
    nodes.forEach(n => void n.offsetHeight);
    window.requestAnimationFrame(() => {
      nodes.forEach(n => n.style.opacity = '0.999');
      window.requestAnimationFrame(() => {
        nodes.forEach(n => {
          n.style.opacity = '';
          n.style.willChange = '';
          n.style.transform = '';
          n.style.backfaceVisibility = '';
        });
      });
    });
  } catch (e) {}
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
const specDiffContainerEl = document.getElementById('spec-diff-overlay');
const diffScroll = document.getElementById('diff-scroll');

editor?.addEventListener && editor.addEventListener('input', () => {
  if (currentSpecView === 'diff') renderGlobalDiff();
  
  // Live preview: update 3D model as user types (with debounce)
  debouncedLivePreview();
});

// Debounced live preview to avoid excessive re-renders
let livePreviewTimeout = null;
function debouncedLivePreview() {
  clearTimeout(livePreviewTimeout);
  livePreviewTimeout = setTimeout(() => {
    try {
      const spec = JSON.parse(editor.value);
      if (spec && spec.geometry) {
        updateLivePreview(spec);
      }
    } catch (e) {
      // Invalid JSON, ignore
    }
  }, 500); // 500ms debounce
}

// Update the 3D preview with current spec changes
function updateLivePreview(spec) {
  // Only update if viewer is initialized
  if (!window.viewer3D || !window.viewer3D.mesh) return;
  
  console.log('[Live Preview] Updating 3D model...');
  
  // Update bone visibility and colors based on spec
  if (spec.geometry && spec.geometry.bones) {
    const bones = spec.geometry.bones;
    window.viewer3D.mesh.traverse(child => {
      if (child.userData && child.userData.boneName) {
        const boneName = child.userData.boneName;
        const boneData = bones.find(b => b.name === boneName);
        
        if (boneData) {
          // Update visibility
          child.visible = boneData.cubes && boneData.cubes.length > 0;
          
          // Update color tint based on bone index for visual feedback
          const boneIndex = bones.indexOf(boneData);
          if (child.isMesh && child.material) {
            const colors = [0x4CAF50, 0x2196F3, 0xFFC107, 0xE91E63, 0x9C27B0, 0x00BCD4];
            const color = colors[boneIndex % colors.length];
            child.material.emissive = new THREE.Color(color);
            child.material.emissiveIntensity = 0.2;
          }
        }
      }
    });
    
    // Reset emissive after a short delay
    setTimeout(() => {
      window.viewer3D.mesh.traverse(child => {
        if (child.isMesh && child.material) {
          child.material.emissiveIntensity = 0;
        }
      });
    }, 300);
  }
  
  // Show live preview indicator
  showLivePreviewIndicator();
}

// Show a brief "Live Preview" indicator
function showLivePreviewIndicator() {
  let indicator = document.getElementById('live-preview-indicator');
  if (!indicator) {
    indicator = document.createElement('div');
    indicator.id = 'live-preview-indicator';
    indicator.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: var(--primary);
      color: white;
      padding: 8px 16px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 600;
      z-index: 1000;
      opacity: 0;
      transition: opacity 0.3s;
      pointer-events: none;
    `;
    indicator.textContent = '⚡ Live Preview';
    document.body.appendChild(indicator);
  }
  
  indicator.style.opacity = '1';
  setTimeout(() => {
    indicator.style.opacity = '0';
  }, 1500);
}

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
  console.log('[setSpecView] Setting view to:', mode);
  console.trace('[setSpecView] Called from:');
  currentSpecView = mode;
  const formContainer = document.getElementById('spec-form-container');
  const editorContainer = document.getElementById('spec-editor-container');
  const specViewFormBtn = document.getElementById('spec-view-form-btn');
  
  console.log('[setSpecView] Elements:', { formContainer, editorContainer, editor, specDiffContainerEl });
  
  if (mode === 'diff') {
    console.log('[setSpecView] Switching to diff view');
    if (formContainer) formContainer.style.display = 'none';
    if (editorContainer) editorContainer.style.display = 'flex';
    if (editor) editor.style.display = 'none';
    if (specDiffContainerEl) { specDiffContainerEl.style.display = 'block'; specDiffContainerEl.setAttribute('aria-visible','true'); }
    moveToggleSlider(specViewDiffBtn);
    try { renderGlobalDiff(); } catch (e) { console.warn('renderGlobalDiff error', e); }
    try { if (diffScroll) diffScroll.scrollTop = 0; } catch (e) {}
    try {
      if (specPre) {
        specPre.style.willChange = 'transform, opacity';
        specPre.style.transform = 'translateZ(0)';
        void specPre.offsetHeight;
        window.requestAnimationFrame(() => {
          specPre.style.willChange = 'auto';
          specPre.style.transform = '';
        });
      }
    } catch (e) {}
  } else if (mode === 'editor' || mode === 'json') {
    console.log('[setSpecView] Switching to JSON view');
    if (formContainer) formContainer.style.display = 'none';
    if (editorContainer) editorContainer.style.display = 'flex';
    if (editor) editor.style.display = 'block';
    if (specDiffContainerEl) { specDiffContainerEl.style.display = 'none'; specDiffContainerEl.setAttribute('aria-visible','false'); }
    moveToggleSlider(specViewEditorBtn);
    // Don't auto-focus to avoid scrolling to bottom on page load
  } else if (mode === 'form') {
    console.log('[setSpecView] Switching to form view');
    if (formContainer) formContainer.style.display = 'block';
    if (editorContainer) editorContainer.style.display = 'none';
    moveToggleSlider(specViewFormBtn);
  }
  
  // Update active states
  if (specViewFormBtn) specViewFormBtn.classList.toggle('active', mode === 'form');
  if (specViewEditorBtn) specViewEditorBtn.classList.toggle('active', mode === 'editor' || mode === 'json'); 
  if (specViewDiffBtn) specViewDiffBtn.classList.toggle('active', mode === 'diff'); 
}

// Initialize view toggle buttons after DOM is ready
function initViewToggle() {
  const specViewFormBtn = document.getElementById('spec-view-form-btn');
  
  console.log('[Editor] Form button:', specViewFormBtn);
  console.log('[Editor] Editor button:', specViewEditorBtn);
  console.log('[Editor] Diff button:', specViewDiffBtn);

  if (specViewFormBtn) {
    specViewFormBtn.addEventListener('click', () => {
      console.log('[Editor] Form button clicked');
      setSpecView('form');
    });
  }
  if (specViewEditorBtn) {
    specViewEditorBtn.addEventListener('click', () => {
      console.log('[Editor] JSON button clicked');
      setSpecView('editor');
    });
  }
  if (specViewDiffBtn) {
    specViewDiffBtn.addEventListener('click', () => {
      console.log('[Editor] Diff button clicked');
      setSpecView('diff');
    });
  }
  
  // Set initial view
  setSpecView('form');
  
  // Handle resize
  window.addEventListener('resize', () => {
    let activeBtn;
    if (currentSpecView === 'form') activeBtn = specViewFormBtn;
    else if (currentSpecView === 'editor' || currentSpecView === 'json') activeBtn = specViewEditorBtn;
    else if (currentSpecView === 'diff') activeBtn = specViewDiffBtn;
    try { moveToggleSlider(activeBtn); } catch (e) {}
  });
}

// Call init when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initViewToggle);
} else {
  initViewToggle();
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// =====================
// ANIMATION GENERATOR
// =====================

(function initAnimationPanel() {
  const generateBtn = document.getElementById('anim-generate-btn');
  const regenBtn = document.getElementById('anim-regen-btn');
  const promptEl = document.getElementById('anim-prompt');
  const statusEl = document.getElementById('anim-status');
  const jsonPreviewEl = document.getElementById('anim-json-preview');
  const clipSelectEl = document.getElementById('anim-clip-select');
  const panelToggleBtn = document.getElementById('anim-panel-toggle');
  const panelBodyEl = document.getElementById('anim-panel-body');
  const animJsonTab = document.getElementById('anim-json-tab');
  const animCtrlTab = document.getElementById('anim-controller-tab');

  // State
  let _animJson = null;
  let _animCtrlJson = null;
  let _activeTab = 'animation';

  function setAnimStatus(msg, isError = false) {
    if (!statusEl) return;
    statusEl.textContent = msg;
    statusEl.style.color = isError ? '#f87171' : 'var(--text-muted)';
  }

  function showJsonPreview() {
    if (!jsonPreviewEl) return;
    const data = _activeTab === 'animation' ? _animJson : _animCtrlJson;
    jsonPreviewEl.textContent = data ? JSON.stringify(data, null, 2) : '(none)';
  }

  function updateClipSelector(animJson) {
    if (!clipSelectEl) return;
    clipSelectEl.innerHTML = '<option value="">— clip —</option>';
    if (!animJson || !animJson.animations) return;
    const keys = Object.keys(animJson.animations);
    const shortName = (fullKey) => (fullKey.split('.').pop() || '').toLowerCase();
    const sortRank = (k) => {
      const s = shortName(k);
      if (s === 'idle') return 0;
      if (s.includes('walk') || s.includes('run')) return 1;
      if (s === 'swim' || s === 'swimming' || s === 'slither' || s === 'moving') return 1.5;
      if (s.includes('attack') || s.includes('breath') || s.includes('fire') || s.includes('shoot')) return 2;
      if (s.includes('fly')) return 3;
      return 50;
    };
    keys.sort((a, b) => {
      const ra = sortRank(a);
      const rb = sortRank(b);
      if (ra !== rb) return ra - rb;
      return a.localeCompare(b);
    });
    keys.forEach(key => {
      const opt = document.createElement('option');
      opt.value = key;
      const label = shortName(key) || key.replace(/^animation\.\w+\./, '');
      opt.textContent = label;
      opt.title = key;
      clipSelectEl.appendChild(opt);
    });

    // Auto-select the first sorted clip (idle) and apply it to the viewer
    if (clipSelectEl.options.length > 1) {
      clipSelectEl.selectedIndex = 1;
      applyAnimationToViewer(animJson, clipSelectEl.value);
    }
  }

  function applyAnimationToViewer(animJson, clipKey) {
    if (!animJson || !animJson.animations) return;
    const clip = animJson.animations[clipKey];
    if (!clip) return;
    if (typeof loadAnimation === 'function') {
      loadAnimation(clip);
      if (typeof window.playAnimationPreview === 'function') {
        window.playAnimationPreview();
      }
      const timeline = document.getElementById('animation-timeline');
      if (timeline) timeline.style.display = '';
    }
  }

  // Save animations back into the current mob spec in localStorage
  function saveAnimationsToSpec(animJson, animCtrlJson) {
    const user = typeof getCurrentUser === 'function' ? getCurrentUser() : null;
    if (!user || !currentMobName) return;
    const mobs = typeof getCurrentUserMobs === 'function' ? getCurrentUserMobs() : {};
    const spec = mobs[currentMobName];
    if (!spec) return;
    if (animJson) spec.animation_json = animJson;
    if (animCtrlJson) {
      spec.animation_controller_json = animCtrlJson;
      spec.animation_controller = `controller.animation.${spec.short_name || currentMobName}`;
    }
    if (typeof saveUserMob === 'function') saveUserMob(currentMobName, spec);
    // Persist to server
    fetch(`/api/mobs/${currentMobName}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ spec }),
    }).catch(() => {});
  }

  async function runAnimationGeneration() {
    const prompt = promptEl ? promptEl.value.trim() : '';
    if (!prompt) { setAnimStatus('Enter an animation prompt first.', true); return; }

    // Get the current spec's geometry and mob info
    const mobs = typeof getCurrentUserMobs === 'function' ? getCurrentUserMobs() : {};
    const spec = currentMobName ? mobs[currentMobName] : null;
    if (!spec) { setAnimStatus('No mob selected.', true); return; }

    const provider = localStorage.getItem(typeof LLM_PROVIDER_KEY !== 'undefined' ? LLM_PROVIDER_KEY : 'builder_llm_provider') || '';
    const apiKey = localStorage.getItem(typeof LLM_API_KEY_STORAGE !== 'undefined' ? LLM_API_KEY_STORAGE : 'builder_llm_api_key') || '';

    setAnimStatus('Generating animations...');
    if (generateBtn) generateBtn.disabled = true;
    if (regenBtn) regenBtn.disabled = true;

    try {
      const res = await fetch('/api/animation/generate-full', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt,
          mob_name: spec.short_name || currentMobName,
          geometry_json: spec.geometry_json || {},
          provider: provider || undefined,
          api_key: apiKey || undefined,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || res.statusText);
      }

      const data = await res.json();
      _animJson = data.animation_json || null;
      _animCtrlJson = data.animation_controller_json || null;

      if (!_animJson && !_animCtrlJson) {
        setAnimStatus('Generation failed — no animations returned. Try a different prompt or provider.', true);
        return;
      }

      const animCount = _animJson ? Object.keys(_animJson.animations || {}).length : 0;
      setAnimStatus(`✓ Generated ${animCount} animation(s)${_animCtrlJson ? ' + controller' : ''}.`);

      showJsonPreview();
      saveAnimationsToSpec(_animJson, _animCtrlJson);

      const mobs = typeof getCurrentUserMobs === 'function' ? getCurrentUserMobs() : {};
      const specAfter = currentMobName ? mobs[currentMobName] : null;
      if (specAfter && typeof syncAnimationPreviewForMob === 'function') {
        specAfter.animation_json = _animJson;
        specAfter.animation_controller_json = _animCtrlJson;
        syncAnimationPreviewForMob(specAfter);
      }
      const forClipList =
        (typeof getEffectiveAnimationJsonForPreview === 'function' && getEffectiveAnimationJsonForPreview()) ||
        _animJson;
      updateClipSelector(forClipList);
      if (!(specAfter && typeof syncAnimationPreviewForMob === 'function')) {
        if (clipSelectEl && clipSelectEl.options.length > 1) {
          clipSelectEl.selectedIndex = 1;
          applyAnimationToViewer(_animJson, clipSelectEl.value);
        }
      }
    } catch (err) {
      setAnimStatus(`Error: ${err.message}`, true);
      console.error('[AnimGen]', err);
    } finally {
      if (generateBtn) generateBtn.disabled = false;
      if (regenBtn) regenBtn.disabled = false;
    }
  }

  // Button listeners
  if (generateBtn) generateBtn.addEventListener('click', runAnimationGeneration);
  if (regenBtn) regenBtn.addEventListener('click', runAnimationGeneration);

  // Clip selector — play the selected animation clip
  if (clipSelectEl) {
    clipSelectEl.addEventListener('change', () => {
      if (!clipSelectEl.value) return;
      const merged =
        (typeof getEffectiveAnimationJsonForPreview === 'function' && getEffectiveAnimationJsonForPreview()) ||
        _animJson;
      applyAnimationToViewer(merged, clipSelectEl.value);
    });
  }

  // Tab switching in JSON preview
  if (animJsonTab) {
    animJsonTab.addEventListener('click', () => {
      _activeTab = 'animation';
      animJsonTab.style.borderBottom = '2px solid var(--accent)';
      animJsonTab.style.opacity = '1';
      if (animCtrlTab) { animCtrlTab.style.borderBottom = 'none'; animCtrlTab.style.opacity = '0.6'; }
      showJsonPreview();
    });
  }
  if (animCtrlTab) {
    animCtrlTab.addEventListener('click', () => {
      _activeTab = 'controller';
      animCtrlTab.style.borderBottom = '2px solid var(--accent)';
      animCtrlTab.style.opacity = '1';
      if (animJsonTab) { animJsonTab.style.borderBottom = 'none'; animJsonTab.style.opacity = '0.6'; }
      showJsonPreview();
    });
  }

  // Panel collapse toggle
  if (panelToggleBtn && panelBodyEl) {
    panelToggleBtn.addEventListener('click', () => {
      const collapsed = panelBodyEl.style.display === 'none';
      panelBodyEl.style.display = collapsed ? '' : 'none';
      panelToggleBtn.textContent = collapsed ? 'Hide' : 'Show';
    });
  }

  // When a mob is loaded, populate clip selector from stored animation_json immediately,
  // then kick off a backend materialize call to merge procedurally-generated clips
  // (walk from leg bones, fly from wing bones) that only exist at build time.
  document.addEventListener('mob-loaded', (e) => {
    const spec = e.detail;
    if (!spec) return;
    _animJson = spec.animation_json || null;
    _animCtrlJson = spec.animation_controller_json || null;
    updateClipSelector(_animJson);
    showJsonPreview();
    // Fire-and-forget: enrich with build-time clips (walk, fly, etc.)
    if (typeof syncAnimationPreviewForMob === 'function') {
      syncAnimationPreviewForMob(spec);
    }
  });

  // When the backend materializer returns, refresh the clip list with enriched animations
  document.addEventListener('animation-preview-ready', (e) => {
    const enriched = e.detail;
    if (!enriched) return;
    _animJson = enriched;
    updateClipSelector(_animJson);
    if (typeof loadAnimationsFromSpec === 'function') {
      loadAnimationsFromSpec(enriched);
    }
  });
})();

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
