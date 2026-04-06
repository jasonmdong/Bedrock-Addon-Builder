// =====================
// TEXTURE PAINTER
// =====================

// Painter Elements
const canvas = document.getElementById("pixel-canvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const painterColor = document.getElementById("painter-color");
const painterPencil = document.getElementById("painter-pencil");
const painterEraser = document.getElementById("painter-eraser");
const painterClear = document.getElementById("painter-clear");
const painterLoad = document.getElementById("painter-load");

const painterImport = document.getElementById("painter-import");
const painterWrapper = document.querySelector(".painter-canvas-wrapper");

let isDrawing = false;
let currentTool = "pencil";
let gridWidth = 64;
let gridHeight = 64;
let scaleX = canvas ? canvas.width / gridWidth : 1;
let scaleY = canvas ? canvas.height / gridHeight : 1;

// Painter Logic
function initPainter() {
  // Check if canvas exists
  if (!canvas) {
    console.warn('[Painter] Canvas not found, skipping initialization');
    return;
  }
  
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  painterWrapper?.classList.remove("texture-loaded");

  const draw = (e) => {
    if (!isDrawing) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - rect.left) / (rect.width / gridWidth));
    const y = Math.floor((e.clientY - rect.top) / (rect.height / gridHeight));

    if (currentTool === "pencil") {
      ctx.fillStyle = painterColor.value;
      ctx.fillRect(x * scaleX, y * scaleY, scaleX, scaleY);
    } else {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x * scaleX, y * scaleY, scaleX, scaleY);
    }
  };

  canvas.addEventListener("mousedown", (e) => { isDrawing = true; draw(e); });
  canvas.addEventListener("mousemove", draw);
  canvas.addEventListener("mouseup", () => {
    if (isDrawing) {
      isDrawing = false;
      // Auto-save texture when mouse is released
      console.log('[Painter] Mouse released, triggering auto-save');
      autoSaveTexture();
    }
  });
  
  // Also handle mouse leaving canvas
  canvas.addEventListener("mouseleave", () => {
    if (isDrawing) {
      isDrawing = false;
      autoSaveTexture();
    }
  });

  painterPencil?.onclick && (painterPencil.onclick = () => { currentTool = "pencil"; updateToolUI(); });
  painterEraser?.onclick && (painterEraser.onclick = () => { currentTool = "eraser"; updateToolUI(); });
  painterClear?.onclick && (painterClear.onclick = () => {
    if (confirm("Clear canvas?")) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      painterWrapper?.classList.remove("texture-loaded");
    }
  });

  painterLoad?.onclick && (painterLoad.onclick = () => loadTextureIntoPainter(currentMobName));
  
  // Auto-save texture (used on mouseup after drawing)
  async function autoSaveTexture() {
    // Get current mob name from the global variable or editor
    const mobName = window.currentMobName || getCurrentMobFromEditor();
    if (!mobName) {
      console.log('[Painter] No mob name available for auto-save');
      return;
    }
    
    console.log('[Painter] Auto-saving texture for:', mobName);
    
    // Create a temporary canvas at the actual texture dimensions to export
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = gridWidth;
    tempCanvas.height = gridHeight;
    const tempCtx = tempCanvas.getContext("2d");
    tempCtx.imageSmoothingEnabled = false;
    tempCtx.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, 0, gridWidth, gridHeight);
    
    // Save to localStorage as base64
    const base64Data = tempCanvas.toDataURL("image/png");
    if (saveUserMobTexture(mobName, base64Data)) {
      console.log('[Painter] Texture saved, refreshing 3D view...');
      // Refresh the 3D viewer to show the updated texture
      refresh3DTexture(mobName);
    }
  }
  
  // Helper to get current mob name from editor
  function getCurrentMobFromEditor() {
    // Try to get from URL or editor state
    const urlParams = new URLSearchParams(window.location.search);
    const mobFromUrl = urlParams.get('mob');
    if (mobFromUrl) return mobFromUrl;
    
    // Try to get from current spec
    try {
      const editor = document.getElementById('spec-editor');
      if (editor && editor.value) {
        const spec = JSON.parse(editor.value);
        return spec.short_name || spec.name;
      }
    } catch (e) {}
    
    return null;
  }
  
  // Auto-save is now triggered on mouseup after drawing

  painterImport.onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.onload = () => {
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.imageSmoothingEnabled = false;
        // Scale up to fill the painter while preserving pixel edges (nearest-neighbor).
        const scale = Math.min(canvas.width / img.width, canvas.height / img.height);
        const dw = img.width * scale;
        const dh = img.height * scale;
        const dx = (canvas.width - dw) / 2;
        const dy = (canvas.height - dh) / 2;
        ctx.drawImage(img, 0, 0, img.width, img.height, dx, dy, dw, dh);
        painterWrapper?.classList.add("texture-loaded");
      };
      img.src = event.target.result;
    };
    reader.readAsDataURL(file);
  };

  updateToolUI();
}

function updateToolUI() {
  painterPencil.classList.toggle("primary", currentTool === "pencil");
  painterPencil.classList.toggle("secondary", currentTool !== "pencil");
  painterEraser.classList.toggle("primary", currentTool === "eraser");
  painterEraser.classList.toggle("secondary", currentTool !== "eraser");
}

// Update painter grid dimensions to match the geometry's texture size.
// Called from editor.js when a mob is selected so the painter exports at the
// correct resolution (e.g. 64x32 for chicken instead of always 64x64).
function setPainterDimensions(w, h) {
  if (!canvas) return;
  gridWidth = w || 64;
  gridHeight = h || 64;

  // Resize the canvas element to maintain pixel-perfect aspect ratio.
  // Keep the wider axis at 384px and scale the other proportionally.
  const maxPx = 384;
  if (gridWidth >= gridHeight) {
    canvas.width = maxPx;
    canvas.height = Math.round(maxPx * (gridHeight / gridWidth));
  } else {
    canvas.height = maxPx;
    canvas.width = Math.round(maxPx * (gridWidth / gridHeight));
  }

  scaleX = canvas.width / gridWidth;
  scaleY = canvas.height / gridHeight;

  // Update the hint label
  const hint = document.querySelector(".painter-layout")?.closest(".content-card")?.querySelector(".hint");
  if (hint) hint.textContent = `Paint the ${gridWidth}x${gridHeight} skin for the selected mob.`;

  console.log(`[Painter] Dimensions set to ${gridWidth}x${gridHeight}, canvas ${canvas.width}x${canvas.height}`);
}

async function loadTextureIntoPainter(name) {
  if (!name) return;
  
  // Clear canvas to white first
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  
  // Try to load from localStorage first
  const localTexture = getUserMobTexture(name);
  if (localTexture) {
    const img = new Image();
    img.onload = () => {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.imageSmoothingEnabled = false;
      // Scale up to fill the painter while preserving pixel edges (nearest-neighbor).
      const scale = Math.min(canvas.width / img.width, canvas.height / img.height);
      const dw = img.width * scale;
      const dh = img.height * scale;
      const dx = (canvas.width - dw) / 2;
      const dy = (canvas.height - dh) / 2;
      ctx.drawImage(img, 0, 0, img.width, img.height, dx, dy, dw, dh);
      painterWrapper?.classList.add("texture-loaded");
    };
    img.src = localTexture;
    return;
  }
  
  // Fallback: try to fetch vanilla texture from Mojang repo if mob has a template base
  const spec = getUserMob(name);
  if (spec && typeof fetchTemplateTexture === 'function') {
    const base = spec._template_base || (spec.short_name || name).replace(/_custom$/, '');
    if (base) {
      const remoteTex = await fetchTemplateTexture(base);
      if (remoteTex) {
        saveUserMobTexture(name, remoteTex);
        const img = new Image();
        img.onload = () => {
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(0, 0, canvas.width, canvas.height);
          ctx.imageSmoothingEnabled = false;
          const scale = Math.min(canvas.width / img.width, canvas.height / img.height);
          const dw = img.width * scale;
          const dh = img.height * scale;
          const dx = (canvas.width - dw) / 2;
          const dy = (canvas.height - dh) / 2;
          ctx.drawImage(img, 0, 0, img.width, img.height, dx, dy, dw, dh);
          painterWrapper?.classList.add("texture-loaded");
        };
        img.src = remoteTex;
        return;
      }
    }
  }

  // Fallback: Check if mob spec has a color_rgb defined
  if (spec && spec.color_rgb) {
    const [r, g, b] = spec.color_rgb;
    ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    console.log(`No texture for ${name}, filled with color_rgb: rgb(${r}, ${g}, ${b})`);
    painterWrapper?.classList.remove("texture-loaded");
    return;
  }
  
  // No local texture or color_rgb - canvas stays white
  console.log(`No texture or color for ${name}, using blank canvas`);
  painterWrapper?.classList.remove("texture-loaded");
}
