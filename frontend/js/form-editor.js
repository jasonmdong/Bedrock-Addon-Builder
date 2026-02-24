// =====================
// FORM-BASED MOB EDITOR
// =====================

// Form elements
const formElements = {
  displayName: document.getElementById('form-display-name'),
  shortName: document.getElementById('form-short-name'),
  identifier: document.getElementById('form-identifier'),
  hp: document.getElementById('form-hp'),
  damage: document.getElementById('form-damage'),
  speed: document.getElementById('form-speed'),
  color: document.getElementById('form-color'),
  colorValue: document.getElementById('form-color-value'),
  scale: document.getElementById('form-scale'),
  scaleValue: document.getElementById('form-scale-value'),
  textureHint: document.getElementById('form-texture-hint'),
  eggBase: document.getElementById('form-egg-base'),
  eggBaseValue: document.getElementById('form-egg-base-value'),
  eggOverlay: document.getElementById('form-egg-overlay'),
  eggOverlayValue: document.getElementById('form-egg-overlay-value'),
  geometry: document.getElementById('form-geometry'),
  collisionWidth: document.getElementById('form-collision-width'),
  collisionHeight: document.getElementById('form-collision-height'),
};

// Initialize form editor
function initFormEditor() {
  // Add event listeners for color pickers to show hex values
  formElements.color?.addEventListener('input', (e) => {
    formElements.colorValue.textContent = e.target.value.toUpperCase();
    syncFormToJSON();
  });
  
  formElements.eggBase?.addEventListener('input', (e) => {
    formElements.eggBaseValue.textContent = e.target.value.toUpperCase();
    syncFormToJSON();
  });
  
  formElements.eggOverlay?.addEventListener('input', (e) => {
    formElements.eggOverlayValue.textContent = e.target.value.toUpperCase();
    syncFormToJSON();
  });
  
  // Scale slider
  formElements.scale?.addEventListener('input', (e) => {
    formElements.scaleValue.textContent = e.target.value + 'x';
    syncFormToJSON();
  });
  
  // Add listeners to all form fields
  Object.values(formElements).forEach(el => {
    if (el && !el.id?.includes('-value')) {
      el.addEventListener('change', syncFormToJSON);
      el.addEventListener('input', debounce(syncFormToJSON, 300));
    }
  });
}

// Load spec data into form
function loadSpecIntoForm(spec) {
  if (!spec) return;
  
  formElements.displayName.value = spec.display_name || '';
  formElements.shortName.value = spec.short_name || '';
  formElements.identifier.value = spec.identifier || '';
  formElements.hp.value = spec.hp || 20;
  formElements.damage.value = spec.damage || 4;
  formElements.speed.value = spec.speed || 0.3;
  
  // Color - convert RGB array to hex
  if (spec.color_rgb && Array.isArray(spec.color_rgb)) {
    const hex = rgbToHex(spec.color_rgb[0], spec.color_rgb[1], spec.color_rgb[2]);
    formElements.color.value = hex;
    formElements.colorValue.textContent = hex.toUpperCase();
  }
  
  formElements.scale.value = spec.scale || 1;
  formElements.scaleValue.textContent = (spec.scale || 1) + 'x';
  formElements.textureHint.value = spec.texture_hint || '';
  
  // Egg colors
  if (spec.egg_base) {
    formElements.eggBase.value = spec.egg_base;
    formElements.eggBaseValue.textContent = spec.egg_base.toUpperCase();
  }
  if (spec.egg_overlay) {
    formElements.eggOverlay.value = spec.egg_overlay;
    formElements.eggOverlayValue.textContent = spec.egg_overlay.toUpperCase();
  }
  
  formElements.geometry.value = spec.geometry || 'geometry.cow';
  
  // Collision box
  if (spec.collision_box) {
    formElements.collisionWidth.value = spec.collision_box.width || 0.9;
    formElements.collisionHeight.value = spec.collision_box.height || 1.4;
  }
}

// Sync form data to JSON editor
function syncFormToJSON() {
  const editor = document.getElementById('spec-editor');
  if (!editor) return;
  
  try {
    // Get current spec or create new one
    let spec = {};
    try {
      spec = JSON.parse(editor.value);
    } catch (e) {
      // If invalid JSON, start fresh
    }
    
    // Update spec from form
    spec.display_name = formElements.displayName.value || 'Unnamed Mob';
    spec.short_name = formElements.shortName.value || 'unnamed_mob';
    spec.identifier = formElements.identifier.value || 'custom:unnamed_mob';
    spec.hp = parseInt(formElements.hp.value) || 20;
    spec.damage = parseFloat(formElements.damage.value) || 4;
    spec.speed = parseFloat(formElements.speed.value) || 0.3;
    
    // Color - convert hex to RGB
    const hex = formElements.color.value;
    spec.color_rgb = hexToRgb(hex);
    
    spec.scale = parseFloat(formElements.scale.value) || 1;
    spec.texture_hint = formElements.textureHint.value || 'solid gray';
    spec.egg_base = formElements.eggBase.value;
    spec.egg_overlay = formElements.eggOverlay.value;
    spec.geometry = formElements.geometry.value;
    
    // Collision box
    spec.collision_box = {
      width: parseFloat(formElements.collisionWidth.value) || 0.9,
      height: parseFloat(formElements.collisionHeight.value) || 1.4
    };
    
    // Update editor without triggering focus
    editor.value = JSON.stringify(spec, null, 2);
    
    // Trigger live preview if available
    if (typeof debouncedLivePreview === 'function') {
      debouncedLivePreview();
    }
  } catch (e) {
    console.error('Error syncing form to JSON:', e);
  }
}

// Helper: RGB array to Hex
function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(x => {
    const hex = Math.max(0, Math.min(255, x)).toString(16);
    return hex.length === 1 ? '0' + hex : hex;
  }).join('');
}

// Helper: Hex to RGB array
function hexToRgb(hex) {
  const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
  return result ? [
    parseInt(result[1], 16),
    parseInt(result[2], 16),
    parseInt(result[3], 16)
  ] : [255, 0, 0];
}

// Helper: Debounce function
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', initFormEditor);
