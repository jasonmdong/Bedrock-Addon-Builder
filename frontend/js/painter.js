// =====================
// TEXTURE MANAGEMENT + 2D PREVIEW
// =====================
// Painting happens on the 3D viewer (viewer3d.js).
// This file manages texture loading, importing, clearing,
// and a toggleable 2D read-only preview that syncs in real time.

const canvas = document.getElementById("pixel-canvas");
const ctx = canvas ? canvas.getContext("2d", { willReadFrequently: true }) : null;
const painterClear = document.getElementById("painter-clear");
const painterLoad = document.getElementById("painter-load");
const painterImport = document.getElementById("painter-import");

let gridWidth = 64;
let gridHeight = 64;
let scaleX = canvas ? canvas.width / gridWidth : 1;
let scaleY = canvas ? canvas.height / gridHeight : 1;

// 3D/2D toggle state
const tex2dPanel = document.getElementById("tex-2d-panel");
const viewToggle3d = document.getElementById("view-toggle-3d");
const viewToggle2d = document.getElementById("view-toggle-2d");
let is2DView = false;

// Sync interval for 2D preview
let syncIntervalId = null;

function startPreviewSync() {
  if (syncIntervalId) return;
  syncIntervalId = setInterval(sync2DPreview, 100);
}

function stopPreviewSync() {
  if (syncIntervalId) {
    clearInterval(syncIntervalId);
    syncIntervalId = null;
  }
}

function sync2DPreview() {
  if (!is2DView || !canvas || !ctx) return;
  const v = window.viewer3D;
  if (!v || !v.texCanvas) {
    console.log('[2D Sync] No viewer3D.texCanvas available');
    return;
  }

  const src = v.texCanvas;
  // Match 2D canvas to texture aspect ratio
  const maxPx = 512;
  const tw = v.texWidth || src.width || 64;
  const th = v.texHeight || src.height || 64;
  const targetW = tw >= th ? maxPx : Math.round(maxPx * (tw / th));
  const targetH = th >= tw ? maxPx : Math.round(maxPx * (th / tw));
  if (canvas.width !== targetW || canvas.height !== targetH) {
    canvas.width = targetW;
    canvas.height = targetH;
    // Also resize UV overlay to match
    const uvOv = document.getElementById("uv-overlay-canvas");
    if (uvOv) { uvOv.width = targetW; uvOv.height = targetH; }
  }

  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(src, 0, 0, src.width, src.height, 0, 0, canvas.width, canvas.height);
}

// Called from viewer3d.js after each paint stroke ends
function onPaintStrokeEnd() {
  sync2DPreview();
}
window.onPaintStrokeEnd = onPaintStrokeEnd;

function show3DView() {
  is2DView = false;
  const wrapper = document.getElementById("viewport-3d-wrapper");
  if (wrapper) wrapper.style.display = "";
  if (tex2dPanel) tex2dPanel.style.display = "none";
  if (viewToggle3d) { viewToggle3d.classList.add("primary"); viewToggle3d.classList.remove("secondary"); }
  if (viewToggle2d) { viewToggle2d.classList.remove("primary"); viewToggle2d.classList.add("secondary"); }
  stopPreviewSync();
}

function show2DView() {
  is2DView = true;
  const wrapper = document.getElementById("viewport-3d-wrapper");
  if (wrapper) wrapper.style.display = "none";
  if (tex2dPanel) tex2dPanel.style.display = "";
  if (viewToggle3d) { viewToggle3d.classList.remove("primary"); viewToggle3d.classList.add("secondary"); }
  if (viewToggle2d) { viewToggle2d.classList.add("primary"); viewToggle2d.classList.remove("secondary"); }
  sync2DPreview();
  startPreviewSync();
}

function initPainter() {
  // 3D / 2D toggle
  viewToggle3d?.addEventListener("click", show3DView);
  viewToggle2d?.addEventListener("click", show2DView);

  // Clear texture
  painterClear?.addEventListener("click", () => {
    if (!confirm("Clear texture to white?")) return;
    if (window.viewer3D && window.viewer3D.texCtx) {
      const tctx = window.viewer3D.texCtx;
      tctx.fillStyle = "#ffffff";
      tctx.fillRect(0, 0, window.viewer3D.texCanvas.width, window.viewer3D.texCanvas.height);
      window.viewer3D.texTexture.needsUpdate = true;
      if (typeof savePaintedTexture === "function") savePaintedTexture();
      sync2DPreview();
    }
  });

  // Reload texture
  painterLoad?.addEventListener("click", () => {
    const mobName = window.currentMobName;
    if (mobName) loadTextureInto3D(mobName);
  });

  // Import PNG
  painterImport?.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (event) => {
      const img = new Image();
      img.onload = () => {
        if (window.viewer3D && window.viewer3D.texCtx) {
          const tc = window.viewer3D.texCanvas;
          const tctx = window.viewer3D.texCtx;
          tc.width = img.width;
          tc.height = img.height;
          window.viewer3D.texWidth = img.width;
          window.viewer3D.texHeight = img.height;
          tctx.drawImage(img, 0, 0);
          window.viewer3D.texTexture.needsUpdate = true;
          if (typeof savePaintedTexture === "function") savePaintedTexture();
          sync2DPreview();
          console.log(`[Painter] Imported texture ${img.width}x${img.height}`);
        }
      };
      img.src = event.target.result;
    };
    reader.readAsDataURL(file);
  });

  // Brush size slider
  const brushSlider = document.getElementById("editor-brush-size");
  const brushLabel = document.getElementById("brush-size-label");
  if (brushSlider && brushLabel) {
    brushSlider.addEventListener("input", () => {
      brushLabel.textContent = brushSlider.value;
      if (window.editor3DState) window.editor3DState.brushSize = parseInt(brushSlider.value);
    });
  }

  // UV overlay toggle
  initUVOverlay();
}

// ---------------------------------------------------------------------------
// UV Overlay (on the 2D preview canvas)
// ---------------------------------------------------------------------------

const uvOverlayCanvas = document.getElementById("uv-overlay-canvas");
const uvToggleBtn = document.getElementById("painter-uv-toggle");
let uvOverlayVisible = false;

function initUVOverlay() {
  if (!uvToggleBtn) return;
  uvToggleBtn.addEventListener("click", () => {
    uvOverlayVisible = !uvOverlayVisible;
    uvToggleBtn.textContent = uvOverlayVisible ? "Hide UV" : "UV";
    uvToggleBtn.classList.toggle("primary", uvOverlayVisible);
    uvToggleBtn.classList.toggle("secondary", !uvOverlayVisible);
    if (uvOverlayCanvas) {
      uvOverlayCanvas.style.display = uvOverlayVisible ? "block" : "none";
    }
    if (uvOverlayVisible) renderUVOverlay();
  });
}

const _UV_ROLE_KEYWORDS = {
  head: ["head", "skull", "cranium"],
  face: ["jaw", "mouth", "snout", "nose", "beak", "muzzle", "horn"],
  body: ["body", "torso", "chest", "trunk", "abdomen", "spine", "root"],
  leg:  ["leg", "foot", "feet", "hoof", "paw", "thigh", "shin", "calf"],
  arm:  ["arm", "hand", "wing", "fin", "flipper", "claw"],
  tail: ["tail"],
  ear:  ["ear"],
};

const _UV_ROLE_COLORS = {
  head: "rgba(255, 60, 60, 0.35)",  face: "rgba(255, 120, 60, 0.35)",
  body: "rgba(60, 120, 255, 0.35)", leg:  "rgba(60, 200, 60, 0.35)",
  arm:  "rgba(200, 200, 60, 0.35)", tail: "rgba(200, 60, 200, 0.35)",
  ear:  "rgba(60, 200, 200, 0.35)",
};

const _UV_ROLE_BORDERS = {
  head: "rgba(255, 60, 60, 0.8)",  face: "rgba(255, 120, 60, 0.8)",
  body: "rgba(60, 120, 255, 0.8)", leg:  "rgba(60, 200, 60, 0.8)",
  arm:  "rgba(200, 200, 60, 0.8)", tail: "rgba(200, 60, 200, 0.8)",
  ear:  "rgba(60, 200, 200, 0.8)",
};

function _classifyBone(boneName) {
  const name = boneName.toLowerCase().replace(/_/g, " ");
  for (const [role, keywords] of Object.entries(_UV_ROLE_KEYWORDS)) {
    if (keywords.some(kw => name.includes(kw))) return role;
  }
  return "body";
}

function _boxUVFaces(u, v, w, h, d) {
  w = Math.max(w, 0); h = Math.max(h, 0); d = Math.max(d, 0);
  return {
    top: [u+d, v, w, d], bottom: [u+d+w, v, w, d],
    right: [u, v+d, d, h], front: [u+d, v+d, w, h],
    left: [u+d+w, v+d, d, h], back: [u+2*d+w, v+d, w, h],
  };
}

function _perfaceUVRects(uvDict, cubeSize) {
  const [cw, ch, cd] = cubeSize.length >= 3
    ? [Math.round(cubeSize[0]), Math.round(cubeSize[1]), Math.round(cubeSize[2])]
    : [0, 0, 0];
  const defaults = {
    north: [cw, ch], south: [cw, ch], east: [cd, ch], west: [cd, ch],
    up: [cw, cd], down: [cw, cd],
  };
  const faces = {};
  for (const [faceKey, faceData] of Object.entries(uvDict)) {
    if (typeof faceData !== "object" || faceData === null) continue;
    const fuv = faceData.uv || [0, 0];
    const defSize = defaults[faceKey] || [cw, ch];
    const fsize = faceData.uv_size || defSize;
    let fu = Math.round(fuv[0]), fv = Math.round(fuv[1]);
    let fw = Math.abs(Math.round(fsize[0] || 0));
    let fh = Math.abs(Math.round(fsize[1] || 0));
    if (fsize[0] < 0) fu += Math.round(fsize[0]);
    if (fsize[1] < 0) fv += Math.round(fsize[1]);
    faces[faceKey] = [fu, fv, fw, fh];
  }
  return faces;
}

function renderUVOverlay() {
  if (!uvOverlayCanvas || !canvas) return;
  const ovCtx = uvOverlayCanvas.getContext("2d");

  uvOverlayCanvas.width = canvas.width;
  uvOverlayCanvas.height = canvas.height;
  ovCtx.clearRect(0, 0, uvOverlayCanvas.width, uvOverlayCanvas.height);

  let geoJson = null;
  try {
    const mobName = window.currentMobName;
    if (mobName && typeof getUserMob === "function") {
      const spec = getUserMob(mobName);
      if (spec) geoJson = spec.geometry_json;
    }
  } catch (e) {}

  if (!geoJson || !geoJson["minecraft:geometry"]) return;

  const geom = geoJson["minecraft:geometry"][0];
  if (!geom) return;
  const desc = geom.description || {};
  const texW = desc.texture_width || 64;
  const texH = desc.texture_height || 64;
  const bones = geom.bones || [];

  const sx = uvOverlayCanvas.width / texW;
  const sy = uvOverlayCanvas.height / texH;

  ovCtx.font = `${Math.max(9, Math.round(sx * 2.5))}px monospace`;
  ovCtx.textBaseline = "top";

  for (const bone of bones) {
    const role = _classifyBone(bone.name || "");
    const fillColor = _UV_ROLE_COLORS[role] || _UV_ROLE_COLORS.body;
    const borderColor = _UV_ROLE_BORDERS[role] || _UV_ROLE_BORDERS.body;

    for (const cube of (bone.cubes || [])) {
      const uv = cube.uv;
      const size = cube.size;
      if (uv == null || !size) continue;

      let faceRects;
      if (typeof uv === "object" && !Array.isArray(uv)) {
        faceRects = _perfaceUVRects(uv, size);
      } else if (Array.isArray(uv) && uv.length >= 2) {
        const iw = Math.round(size[0] || 0), ih = Math.round(size[1] || 0), id = Math.round(size[2] || 0);
        faceRects = _boxUVFaces(Math.round(uv[0]), Math.round(uv[1]), iw, ih, id);
      } else {
        continue;
      }

      let firstRect = true;
      for (const [, [fu, fv, fw, fh]] of Object.entries(faceRects)) {
        if (fw <= 0 || fh <= 0) continue;
        const dx = fu * sx, dy = fv * sy, dw = fw * sx, dh = fh * sy;
        ovCtx.fillStyle = fillColor;
        ovCtx.fillRect(dx, dy, dw, dh);
        ovCtx.strokeStyle = borderColor;
        ovCtx.lineWidth = 1;
        ovCtx.strokeRect(dx + 0.5, dy + 0.5, dw - 1, dh - 1);
        if (firstRect && dw > 15 && dh > 10) {
          ovCtx.fillStyle = borderColor;
          ovCtx.fillText(bone.name, dx + 2, dy + 1);
          firstRect = false;
        }
      }
    }
  }
}

function setPainterDimensions(w, h) {
  gridWidth = w || 64;
  gridHeight = h || 64;

  if (canvas) {
    const maxPx = 512;
    if (gridWidth >= gridHeight) {
      canvas.width = maxPx;
      canvas.height = Math.round(maxPx * (gridHeight / gridWidth));
    } else {
      canvas.height = maxPx;
      canvas.width = Math.round(maxPx * (gridWidth / gridHeight));
    }
    scaleX = canvas.width / gridWidth;
    scaleY = canvas.height / gridHeight;
  }

  console.log(`[Painter] Dimensions set to ${gridWidth}x${gridHeight}`);
  if (uvOverlayVisible) renderUVOverlay();
  sync2DPreview();
}

async function loadTextureInto3D(name) {
  if (!name) return;

  const localTexture = typeof getUserMobTexture === "function" ? getUserMobTexture(name) : null;
  if (localTexture) {
    if (typeof refresh3DTexture === "function") refresh3DTexture(name);
    sync2DPreview();
    return;
  }

  const spec = typeof getUserMob === "function" ? getUserMob(name) : null;
  if (spec && typeof fetchTemplateTexture === "function") {
    const base = spec._template_base || (spec.short_name || name).replace(/_custom$/, "");
    if (base) {
      const remoteTex = await fetchTemplateTexture(base);
      if (remoteTex) {
        saveUserMobTexture(name, remoteTex);
        if (typeof refresh3DTexture === "function") refresh3DTexture(name);
        sync2DPreview();
        return;
      }
    }
  }

  console.log(`[Painter] No texture found for ${name}`);
}

function loadTextureIntoPainter(name) {
  loadTextureInto3D(name);
}
