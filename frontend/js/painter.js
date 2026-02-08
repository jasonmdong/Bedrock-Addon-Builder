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
const painterSave = document.getElementById("painter-save");
const painterImport = document.getElementById("painter-import");
const painterWrapper = document.querySelector(".painter-canvas-wrapper");

let isDrawing = false;
let currentTool = "pencil";
const GRID_SIZE = 64;
const SCALE = canvas.width / GRID_SIZE;

// Painter Logic
function initPainter() {
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  painterWrapper?.classList.remove("texture-loaded");

  const draw = (e) => {
    if (!isDrawing) return;
    const rect = canvas.getBoundingClientRect();
    const x = Math.floor((e.clientX - rect.left) / (rect.width / GRID_SIZE));
    const y = Math.floor((e.clientY - rect.top) / (rect.height / GRID_SIZE));

    if (currentTool === "pencil") {
      ctx.fillStyle = painterColor.value;
      ctx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
    } else {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(x * SCALE, y * SCALE, SCALE, SCALE);
    }
  };

  canvas.addEventListener("mousedown", (e) => { isDrawing = true; draw(e); });
  canvas.addEventListener("mousemove", draw);
  window.addEventListener("mouseup", () => { isDrawing = false; });

  painterPencil.onclick = () => { currentTool = "pencil"; updateToolUI(); };
  painterEraser.onclick = () => { currentTool = "eraser"; updateToolUI(); };
  painterClear.onclick = () => {
    if (confirm("Clear canvas?")) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      painterWrapper?.classList.remove("texture-loaded");
    }
  };

  painterLoad.onclick = () => loadTextureIntoPainter(currentMobName);
  
  painterSave.onclick = async () => {
    if (!currentMobName) return;
    setStatus(`Saving texture for ${currentMobName}...`);
    
    // Create a temporary 64x64 canvas to export the actual image
    const tempCanvas = document.createElement("canvas");
    tempCanvas.width = GRID_SIZE;
    tempCanvas.height = GRID_SIZE;
    const tempCtx = tempCanvas.getContext("2d");
    tempCtx.imageSmoothingEnabled = false;
    tempCtx.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, 0, GRID_SIZE, GRID_SIZE);
    
    // Save to localStorage as base64
    const base64Data = tempCanvas.toDataURL("image/png");
    if (saveUserMobTexture(currentMobName, base64Data)) {
      setStatus(`Texture saved for ${currentMobName}.`);
    } else {
      setStatus(`Failed to save texture.`, true);
    }
  };

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
  
  // Fallback: Check if mob spec has a color_rgb defined
  const spec = getUserMob(name);
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
