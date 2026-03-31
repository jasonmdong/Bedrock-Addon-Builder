// =====================
// BLOCKBENCH-STYLE 3D GEOMETRY VIEWER
// =====================
// Enhanced viewer with proper Bedrock coordinate system transformations
// and animation support inspired by Blockbench

let viewer3D = null;
let animationState = null;

// Blockbench-style color palette for bones
const BONE_COLORS = [
  0x4CAF50, 0x2196F3, 0xFFC107, 0xE91E63, 
  0x9C27B0, 0x00BCD4, 0xFF5722, 0x795548,
  0x607D8B, 0x8BC34A, 0x03A9F4, 0xFFEB3B
];

function initializeViewer3D() {
  const container = document.getElementById("viewport-3d");
  if (!container) return null;
  
  // Clear any existing viewer
  container.innerHTML = "";
  
  // Scene setup - Blockbench dark theme
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1e1e1f);
  
  // Camera setup - Y-up like Minecraft/Blockbench
  const width = container.clientWidth;
  const height = container.clientHeight;
  const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 3000);
  camera.position.set(-40, 32, -40);
  camera.up.set(0, 1, 0);
  
  // Renderer setup
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  container.appendChild(renderer.domElement);
  
  // Lighting - Blockbench-style
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.65);
  scene.add(ambientLight);
  
  const sunLight = new THREE.DirectionalLight(0xffffff, 0.85);
  sunLight.position.set(50, 80, 40);
  sunLight.castShadow = true;
  sunLight.shadow.mapSize.width = 2048;
  sunLight.shadow.mapSize.height = 2048;
  sunLight.shadow.camera.near = 0.5;
  sunLight.shadow.camera.far = 500;
  scene.add(sunLight);
  
  // Blockbench-style grid
  const gridHelper = new THREE.GridHelper(256, 16, 0x3e3e42, 0x2d2d30);
  gridHelper.position.y = 0;
  scene.add(gridHelper);
  
  // Axis helper (RGB = XYZ)
  const axisHelper = new THREE.AxesHelper(20);
  axisHelper.position.set(-128, 0, -128);
  scene.add(axisHelper);
  
  // Orbit controls state
  const controls = {
    isRotating: false,
    isPanning: false,
    previousMousePosition: { x: 0, y: 0 },
    target: new THREE.Vector3(0, 16, 0),
    distance: 100,
    theta: Math.PI * 0.75,
    phi: Math.PI * 0.35,
    rotationSpeed: 0.008,
    panSpeed: 0.3,
    zoomSpeed: 8,
    minDistance: 10,
    maxDistance: 500,
    // Keyboard movement state
    keys: {
      w: false, // forward
      a: false, // left
      s: false, // backward
      d: false  // right
    },
    moveSpeed: 1.0
  };
  
  function updateCameraFromOrbit() {
    const sinPhi = Math.sin(controls.phi);
    const cosPhi = Math.cos(controls.phi);
    const sinTheta = Math.sin(controls.theta);
    const cosTheta = Math.cos(controls.theta);
    
    camera.position.x = controls.target.x + controls.distance * sinPhi * sinTheta;
    camera.position.y = controls.target.y + controls.distance * cosPhi;
    camera.position.z = controls.target.z + controls.distance * sinPhi * cosTheta;
    camera.lookAt(controls.target);
  }
  
  updateCameraFromOrbit();
  
  renderer.domElement.addEventListener("mousedown", (e) => {
    controls.previousMousePosition = { x: e.clientX, y: e.clientY };
    const isPaintTool = ['paint', 'erase', 'pick'].includes(editor3DState.tool);
    const isTransformTool = ['move', 'rotate', 'scale'].includes(editor3DState.tool);
    // Don't start orbit rotation when using paint/transform tools and hovering a mesh
    const blockOrbit = (isPaintTool || isTransformTool) && editor3DState.hoverObject;
    if (e.button === 0 && !blockOrbit) {
      controls.isRotating = true;
    }
    if (e.button === 2 || (e.button === 0 && e.shiftKey)) controls.isPanning = true;
    if (controls.isPanning) controls.isRotating = false;
  });
  
  renderer.domElement.addEventListener("mousemove", (e) => {
    const deltaX = e.clientX - controls.previousMousePosition.x;
    const deltaY = e.clientY - controls.previousMousePosition.y;
    
    if (controls.isRotating) {
      controls.theta -= deltaX * controls.rotationSpeed;
      controls.phi = Math.max(0.1, Math.min(Math.PI - 0.1, controls.phi - deltaY * controls.rotationSpeed));
      updateCameraFromOrbit();
    }
    
    if (controls.isPanning) {
      const right = new THREE.Vector3();
      const up = new THREE.Vector3();
      camera.getWorldDirection(up);
      right.crossVectors(camera.up, up).normalize();
      up.crossVectors(right, camera.getWorldDirection(up)).normalize();
      
      controls.target.addScaledVector(right, deltaX * controls.panSpeed);
      controls.target.addScaledVector(up, deltaY * controls.panSpeed);
      updateCameraFromOrbit();
    }
    
    controls.previousMousePosition = { x: e.clientX, y: e.clientY };
  });
  
  renderer.domElement.addEventListener("mouseup", () => {
    controls.isRotating = false;
    controls.isPanning = false;
  });
  
  renderer.domElement.addEventListener("mouseleave", () => {
    controls.isRotating = false;
    controls.isPanning = false;
  });
  
  renderer.domElement.addEventListener("wheel", (e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? 1 : -1;
    
    // If scale tool is active and an object is selected, scale uniformly
    if (editor3DState.tool === 'scale' && editor3DState.selectedObject) {
      const obj = editor3DState.selectedObject;
      const factor = 1 + delta * 0.02;  // Mouse wheel scaling sensitivity
      const clamped = Math.max(0.1, Math.min(5, factor));
      obj.scale.multiplyScalar(clamped);
      refreshSelectionBox();
      console.log('[3D Editor] Scale via wheel:', [obj.scale.x, obj.scale.y, obj.scale.z]);
    } else {
      // Normal camera zoom
      controls.distance = Math.max(
        controls.minDistance,
        Math.min(controls.maxDistance, controls.distance + delta * controls.zoomSpeed)
      );
      updateCameraFromOrbit();
    }
  }, { passive: false });
  
  renderer.domElement.addEventListener("contextmenu", (e) => e.preventDefault());
  
  // WASD keyboard controls for camera movement
  document.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();
    if (key === 'w') { controls.keys.w = true; }
    if (key === 'a') { controls.keys.a = true; }
    if (key === 's') { controls.keys.s = true; }
    if (key === 'd') { controls.keys.d = true; }
  });
  
  document.addEventListener("keyup", (e) => {
    const key = e.key.toLowerCase();
    if (key === 'w') { controls.keys.w = false; }
    if (key === 'a') { controls.keys.a = false; }
    if (key === 's') { controls.keys.s = false; }
    if (key === 'd') { controls.keys.d = false; }
  });
  
  // Handle window resize
  const handleResize = () => {
    const newWidth = container.clientWidth;
    const newHeight = container.clientHeight;
    camera.aspect = newWidth / newHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(newWidth, newHeight);
  };
  
  window.addEventListener("resize", handleResize);
  
  // Animation loop
  let animationFrameId;
  const animate = () => {
    animationFrameId = requestAnimationFrame(animate);
    
    // Handle WASD camera movement
    const moveVec = new THREE.Vector3();
    if (controls.keys.w) moveVec.z += controls.moveSpeed;  // Backward
    if (controls.keys.s) moveVec.z -= controls.moveSpeed;  // Forward
    if (controls.keys.a) moveVec.x += controls.moveSpeed;  // Left (X inverted)
    if (controls.keys.d) moveVec.x -= controls.moveSpeed;  // Right (X inverted)
    
    if (moveVec.length() > 0) {
      // Transform movement from camera-local to world space
      const camDir = new THREE.Vector3();
      camera.getWorldDirection(camDir);
      const camRight = new THREE.Vector3();
      camRight.crossVectors(camera.up, camDir).normalize();
      const camUp = new THREE.Vector3();
      camUp.crossVectors(camDir, camRight).normalize();
      
      // Apply movement relative to camera orientation
      moveVec.x *= controls.moveSpeed;
      moveVec.z *= controls.moveSpeed;
      
      const deltaMove = new THREE.Vector3();
      deltaMove.addScaledVector(camRight, moveVec.x);
      deltaMove.addScaledVector(camUp, moveVec.z);
      
      controls.target.add(deltaMove);
      updateCameraFromOrbit();
    }
    
    // Update animation if playing
    if (animationState && animationState.playing && viewer3D.mesh) {
      updateAnimation();
    }
    
    renderer.render(scene, camera);
  };
  
  animate();
  
  return {
    scene,
    camera,
    renderer,
    mesh: null,
    bones: {},
    animations: [],
    currentAnimation: null,
    controls,
    updateCameraFromOrbit,
    dispose: () => {
      window.removeEventListener("resize", handleResize);
      cancelAnimationFrame(animationFrameId);
      renderer.dispose();
      container.innerHTML = "";
    }
  };
}

// Parse Bedrock geometry with proper coordinate transformations
// Following Blockbench's approach: X-axis is inverted
function parseBedrock(geometryData) {
  let geometries = [];
  
  if (Array.isArray(geometryData)) {
    geometries = geometryData;
  } else if (geometryData["minecraft:geometry"]) {
    geometries = geometryData["minecraft:geometry"];
  } else if (geometryData.bones) {
    geometries = [geometryData];
  } else {
    const geometryKeys = Object.keys(geometryData).filter(key => key.includes("geometry"));
    if (geometryKeys.length > 0) {
      const geometryObj = geometryData[geometryKeys[0]];
      if (Array.isArray(geometryObj)) {
        geometries = geometryObj;
      } else if (geometryObj && geometryObj.bones) {
        geometries = [geometryObj];
      }
    }
  }
  
  return geometries;
}

// Apply UV coordinates to box geometry based on Bedrock cube UV data
// Maps the cube faces to the correct texture regions
// Reference: https://wiki.bedrock.dev/documentation/uv-mapping.html
// 
// Bedrock box UV layout for a cube with size (w, h, d):
// The UV coord [u, v] points to the top-left corner of the front face
// 
// Texture layout (horizontal strip):
// [right: u-d, v, size d x h] [front: u, v, size w x h] [left: u+w, v, size d x h] [back: u+w+d, v, size w x h]
// [top: u, v-d, size w x d]   [bottom: u+w, v-d, size w x d]
//
// Note: left and back faces are mirrored horizontally
// Note: bottom face is mirrored vertically

function applyPerFaceUV(geometry, uvFaces, size, textureWidth, textureHeight) {
  // Per-face UV format from MCP designModel:
  // { "north": { "uv": [x, y], "uv_size": [w, h] }, ... }
  const toU = (x) => x / textureWidth;
  const toV = (y) => 1 - (y / textureHeight);

  const uvArray = [];

  // Three.js BoxGeometry face order: right(+x), left(-x), top(+y), bottom(-y), front(+z), back(-z)
  // Bedrock per-face names mapped to Three.js face indices:
  // lateral=true for side faces (vertices ordered TL,TR,BL,BR in Three.js)
  const faceOrder = [
    ["east", true], ["west", true], ["up", false], ["down", false], ["south", true], ["north", true]
  ];

  for (const [faceName, lateral] of faceOrder) {
    const face = uvFaces[faceName];
    if (face && face.uv && face.uv_size) {
      const fu = face.uv[0];
      const fv = face.uv[1];
      const fw = face.uv_size[0];
      const fh = face.uv_size[1];

      const u1 = toU(fu);
      const u2 = toU(fu + fw);
      const vBottom = toV(fv + fh);
      const vTop = toV(fv);

      if (lateral) {
        uvArray.push(u1, vTop, u2, vTop, u1, vBottom, u2, vBottom);
      } else {
        uvArray.push(u1, vBottom, u2, vBottom, u1, vTop, u2, vTop);
      }
    } else {
      uvArray.push(0, 0, 0, 0, 0, 0, 0, 0);
    }
  }

  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvArray, 2));
}

function applyBoxUV(geometry, uv, size, textureWidth, textureHeight) {
  // Handle missing or non-array UV data
  if (!uv || !Array.isArray(uv) || uv.length < 2) {
    return;
  }
  
  const u = uv[0];
  const v = uv[1];
  const [w, h, d] = size;
  
  // Helper to convert pixel coords to UV coords
  // Three.js V=0 is bottom, V=1 is top (flipped from image coordinates)
  const toU = (x) => x / textureWidth;
  const toV = (y) => 1 - (y / textureHeight);
  
  const uvArray = [];
  
  // Standard Bedrock box UV layout:
  //      u    u+d   u+d+w  u+2d+w
  //  v   ┌─────┬──────┬──────┬──────┐
  //      │     │ Top  │      │Bottom│
  // v+d  ├─────┼──────┼──────┼──────┤
  //      │Right│Front │ Left │ Back │
  // v+d+h└─────┴──────┴──────┴──────┘
  //
  // Three.js BoxGeometry face order: +X, -X, +Y, -Y, +Z, -Z
  // Bedrock: +X=East/Right, -X=West/Left, +Y=Top, -Y=Bottom,
  //          +Z=South/Back, -Z=North/Front
  // The viewer uses X-inversion for positions, so U-mirroring
  // on the front face is NOT needed (inversion handles it).
  
  // Face definitions: [pixelU, pixelV, pixelW, pixelH, mirrorU, mirrorV, lateral]
  // lateral=true means the face is a side face (vertices ordered TL,TR,BL,BR in Three.js)
  const faces = [
    // +X = East/Right side
    [u,             v + d,   d, h, false, false, true],
    // -X = West/Left side
    [u + d + w,     v + d,   d, h, false, false, true],
    // +Y = Top
    [u + d,         v,       w, d, false, false, false],
    // -Y = Bottom
    [u + d + w,     v,       w, d, false, true, false],
    // +Z = South/Back
    [u + 2*d + w,   v + d,   w, h, true, false, true],
    // -Z = North/Front
    [u + d,         v + d,   w, h, false, false, true]
  ];

  for (const [fu, fv, fw, fh, mirrorU, mirrorV, lateral] of faces) {
    let u1 = toU(fu);
    let u2 = toU(fu + fw);
    let vBottom = toV(fv + fh);
    let vTop = toV(fv);

    if (mirrorU) [u1, u2] = [u2, u1];
    if (mirrorV) [vBottom, vTop] = [vTop, vBottom];

    if (lateral) {
      // Lateral faces: Three.js vertex order is TL, TR, BL, BR
      uvArray.push(u1, vTop, u2, vTop, u1, vBottom, u2, vBottom);
    } else {
      // Top/bottom faces: Three.js vertex order is BL, BR, TL, TR
      uvArray.push(u1, vBottom, u2, vBottom, u1, vTop, u2, vTop);
    }
  }
  
  geometry.setAttribute('uv', new THREE.Float32BufferAttribute(uvArray, 2));
}

// Create cube mesh from Bedrock cube data
// Applies Blockbench coordinate transformations
function createCubeMesh(cube, bonePivot, colorIndex, texture, textureWidth = 64, textureHeight = 64) {
  const origin = cube.origin || [0, 0, 0];
  const size = cube.size || [1, 1, 1];
  const inflate = cube.inflate || 0;
  const cubeRotation = cube.rotation || [0, 0, 0];
  const cubePivot = cube.pivot || null;
  const uv = cube.uv;
  
  // Apply inflation
  const adjustedSize = [
    size[0] + inflate * 2,
    size[1] + inflate * 2,
    size[2] + inflate * 2
  ];
  
  // Create geometry
  const geometry = new THREE.BoxGeometry(adjustedSize[0], adjustedSize[1], adjustedSize[2]);
  
  // Apply UV mapping if texture is available
  if (texture && uv) {
    if (typeof uv === "object" && !Array.isArray(uv)) {
      // Per-face UV format from MCP designModel
      applyPerFaceUV(geometry, uv, size, textureWidth, textureHeight);
    } else {
      // Classic box UV format [x, y]
      applyBoxUV(geometry, uv, size, textureWidth, textureHeight);
    }
  }
  
  // Use texture material if available, otherwise use colored material
  let material;
  if (texture) {
    material = new THREE.MeshLambertMaterial({
      map: texture,
      side: THREE.DoubleSide,
      transparent: true,
      alphaTest: 0.05
    });
  } else {
    // Blockbench-style material with slight random color variation
    const baseColor = BONE_COLORS[colorIndex % BONE_COLORS.length];
    material = new THREE.MeshLambertMaterial({
      color: baseColor,
      side: THREE.DoubleSide
    });
  }
  
  const mesh = new THREE.Mesh(geometry, material);
  
  // Bedrock coordinate transformation (X-axis inverted like Blockbench)
  // Convert origin to center position
  const cubeCenter = [
    -(origin[0] + size[0] / 2),  // X inverted
    origin[1] + size[1] / 2,
    origin[2] + size[2] / 2
  ];
  
  const hasCubeRotation = cubeRotation[0] || cubeRotation[1] || cubeRotation[2];
  
  if (hasCubeRotation && cubePivot) {
    // Create pivot group for rotation around cube's pivot point
    const pivotGroup = new THREE.Group();
    
    // Cube pivot with X inverted
    const adjustedCubePivot = [
      -cubePivot[0],  // X inverted
      cubePivot[1],
      cubePivot[2]
    ];
    
    // Bone pivot with X inverted
    const adjustedBonePivot = [
      -bonePivot[0],
      bonePivot[1],
      bonePivot[2]
    ];
    
    // Position pivot group relative to bone
    pivotGroup.position.set(
      adjustedCubePivot[0] - adjustedBonePivot[0],
      adjustedCubePivot[1] - adjustedBonePivot[1],
      adjustedCubePivot[2] - adjustedBonePivot[2]
    );
    
    // Position mesh relative to cube pivot
    mesh.position.set(
      cubeCenter[0] - adjustedCubePivot[0],
      cubeCenter[1] - adjustedCubePivot[1],
      cubeCenter[2] - adjustedCubePivot[2]
    );
    
    // Apply rotation (inverted for X and Y axes like Blockbench)
    pivotGroup.rotation.order = "ZYX";
    pivotGroup.rotation.x = -cubeRotation[0] * Math.PI / 180;
    pivotGroup.rotation.y = -cubeRotation[1] * Math.PI / 180;
    pivotGroup.rotation.z = cubeRotation[2] * Math.PI / 180;
    
    pivotGroup.add(mesh);
    return pivotGroup;
  } else {
    // Simple case: position relative to bone
    const adjustedBonePivot = [
      -bonePivot[0],
      bonePivot[1],
      bonePivot[2]
    ];
    
    mesh.position.set(
      cubeCenter[0] - adjustedBonePivot[0],
      cubeCenter[1] - adjustedBonePivot[1],
      cubeCenter[2] - adjustedBonePivot[2]
    );
    
    if (hasCubeRotation) {
      mesh.rotation.order = "ZYX";
      mesh.rotation.x = -cubeRotation[0] * Math.PI / 180;
      mesh.rotation.y = -cubeRotation[1] * Math.PI / 180;
      mesh.rotation.z = cubeRotation[2] * Math.PI / 180;
    }
    
    return mesh;
  }
}

// Create bone group with proper transformations
function createBoneGroup(bone, colorIndex) {
  const group = new THREE.Group();
  group.name = bone.name;
  group.userData.boneName = bone.name;
  group.userData.originalRotation = bone.rotation ? [...bone.rotation] : [0, 0, 0];
  group.userData.originalPivot = bone.pivot ? [...bone.pivot] : [0, 0, 0];
  
  const pivot = bone.pivot || [0, 0, 0];
  const rotation = bone.rotation || [0, 0, 0];
  const bindPose = bone.bind_pose_rotation || [0, 0, 0];
  
  // Apply X-inversion to pivot (Blockbench coordinate system)
  group.position.set(-pivot[0], pivot[1], pivot[2]);
  
  // Combine rotation and bind pose
  const totalRotation = [
    (rotation[0] || 0) + (bindPose[0] || 0),
    (rotation[1] || 0) + (bindPose[1] || 0),
    (rotation[2] || 0) + (bindPose[2] || 0)
  ];
  
  if (totalRotation[0] || totalRotation[1] || totalRotation[2]) {
    group.rotation.order = "ZYX";
    // Invert X and Y rotations (Blockbench coordinate transformation)
    group.rotation.x = -totalRotation[0] * Math.PI / 180;
    group.rotation.y = -totalRotation[1] * Math.PI / 180;
    group.rotation.z = totalRotation[2] * Math.PI / 180;
  }
  
  // Apply scale if present
  const scale = bone.scale;
  if (scale) {
    if (Array.isArray(scale)) {
      group.scale.set(scale[0], scale[1], scale[2]);
    } else {
      group.scale.set(scale, scale, scale);
    }
  }
  
  return group;
}

function render3DGeometry(geometryData, mobName, mobScale) {
  console.log("[3D] Rendering geometry with Blockbench-style transformations");
  
  if (!viewer3D) {
    viewer3D = initializeViewer3D();
    window.viewer3D = viewer3D;
    // Initialize editor features after viewer is created
    setupRaycasting();
  }
  
  if (!viewer3D) return;
  
  // Clear previous mesh
  if (viewer3D.mesh) {
    viewer3D.scene.remove(viewer3D.mesh);
    viewer3D.bones = {};
  }
  
  // Resolve mob scale from parameter, spec, or default
  if (!mobScale && mobName) {
    try {
      const spec = typeof getUserMob === 'function' ? getUserMob(mobName) : null;
      if (spec && spec.scale) mobScale = parseFloat(spec.scale);
    } catch (e) { /* ignore */ }
  }
  mobScale = mobScale || 1.0;
  
  // Get the texture for this mob
  const textureData = mobName ? getUserMobTexture(mobName) : null;
  let texture = null;
  let textureWidth = 64;
  let textureHeight = 64;
  
  // Create a canvas-backed texture so we can paint on it directly
  const texCanvas = document.createElement('canvas');
  texCanvas.width = textureWidth;
  texCanvas.height = textureHeight;
  const texCtx = texCanvas.getContext('2d', { willReadFrequently: true });
  texCtx.fillStyle = '#ffffff';
  texCtx.fillRect(0, 0, texCanvas.width, texCanvas.height);

  if (textureData) {
    const img = new Image();
    img.src = textureData;
    img.onload = function() {
      textureWidth = img.width;
      textureHeight = img.height;
      texCanvas.width = img.width;
      texCanvas.height = img.height;
      texCtx.drawImage(img, 0, 0);
      texture.needsUpdate = true;
      // Store dimensions for painting
      viewer3D.texWidth = textureWidth;
      viewer3D.texHeight = textureHeight;
      console.log(`[3D] Texture loaded: ${textureWidth}x${textureHeight}`);
    };
    img.onerror = function() {
      console.warn('[3D] Failed to load texture');
    };
  }

  texture = new THREE.CanvasTexture(texCanvas);
  texture.magFilter = THREE.NearestFilter;
  texture.minFilter = THREE.NearestFilter;
  texture.wrapS = THREE.ClampToEdgeWrapping;
  texture.wrapT = THREE.ClampToEdgeWrapping;

  // Store on viewer3D for painting access
  viewer3D.texCanvas = texCanvas;
  viewer3D.texCtx = texCtx;
  viewer3D.texTexture = texture;
  viewer3D.texWidth = textureWidth;
  viewer3D.texHeight = textureHeight;
  viewer3D.currentMobName = mobName;
  
  const rootGroup = new THREE.Group();
  const geometries = parseBedrock(geometryData);
  
  if (!geometries.length) {
    console.warn("[3D] No geometries found");
    return;
  }
  
  let cubeCount = 0;
  let boneCount = 0;
  
  geometries.forEach((geom, geomIdx) => {
    if (!geom || !geom.bones) return;
    
    // Extract texture dimensions
    const description = geom.description || {};
    const textureWidth = description.texture_width || 64;
    const textureHeight = description.texture_height || 64;
    
    console.log(`[3D] Geometry ${geomIdx}: ${geom.bones.length} bones, texture: ${textureWidth}x${textureHeight}`);
    
    // Create bone lookup maps
    const boneMap = {};
    const boneGroupMap = {};
    
    geom.bones.forEach(bone => {
      boneMap[bone.name] = bone;
    });
    
    // First pass: Create bone groups
    geom.bones.forEach((bone, idx) => {
      if (!bone) return;
      boneCount++;
      
      const boneGroup = createBoneGroup(bone, idx);
      boneGroupMap[bone.name] = boneGroup;
      viewer3D.bones[bone.name] = boneGroup;
    });
    
    // Second pass: Add cubes and build hierarchy
    geom.bones.forEach((bone, idx) => {
      if (!bone || bone.neverRender === true) return;
      
      const boneGroup = boneGroupMap[bone.name];
      const bonePivot = bone.pivot || [0, 0, 0];
      
      // Add cubes
      if (bone.cubes && bone.cubes.length > 0) {
        bone.cubes.forEach((cube, cubeIdx) => {
          if (cube.neverRender === true) return;
          cubeCount++;
          
          const cubeMesh = createCubeMesh(cube, bonePivot, idx, texture, textureWidth, textureHeight);
          boneGroup.add(cubeMesh);
        });
      }
      
      // Build hierarchy
      const parentName = bone.parent;
      if (parentName && boneGroupMap[parentName]) {
        const parentBone = boneMap[parentName];
        const parentPivot = parentBone.pivot || [0, 0, 0];
        const childPivot = bone.pivot || [0, 0, 0];
        
        // Convert to parent-local space with X-inversion
        boneGroup.position.set(
          -childPivot[0] - (-parentPivot[0]),
          childPivot[1] - parentPivot[1],
          childPivot[2] - parentPivot[2]
        );
        
        boneGroupMap[parentName].add(boneGroup);
      } else {
        rootGroup.add(boneGroup);
      }
    });
  });
  
  if (cubeCount === 0) {
    console.warn("[3D] No cubes found in geometry");
    return;
  }
  
  console.log(`[3D] Rendered ${cubeCount} cubes in ${boneCount} bones`);
  
  // Apply mob scale (elephants = 2.0+, mice = 0.5, etc.)
  if (mobScale && mobScale !== 1.0) {
    rootGroup.scale.set(mobScale, mobScale, mobScale);
    console.log(`[3D] Applied mob scale: ${mobScale}x`);
  }
  
  // Center and frame the model
  const box = new THREE.Box3().setFromObject(rootGroup);
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3());
  
  // Position model at origin (feet at y=0)
  rootGroup.position.set(-center.x, -box.min.y, -center.z);
  
  // Adjust camera to fit model
  const maxDim = Math.max(size.x, size.y, size.z);
  viewer3D.controls.distance = maxDim * 2;
  viewer3D.controls.target.set(0, size.y / 2, 0);
  viewer3D.updateCameraFromOrbit();
  
  viewer3D.scene.add(rootGroup);
  viewer3D.mesh = rootGroup;
  
  console.log("[3D] Model rendered successfully");
}

// Animation system
function initAnimationState() {
  animationState = {
    playing: false,
    time: 0,
    duration: 0,
    loop: true,
    speed: 1,
    lastFrameTime: 0,
    keyframes: {},
    animationData: null
  };
}

function loadAnimation(animationData) {
  if (!animationState) initAnimationState();
  
  animationState.animationData = animationData;
  animationState.duration = animationData.animation_length || 1;
  animationState.loop = animationData.loop === true || animationData.loop === "loop";
  animationState.keyframes = {};
  
  // Parse bone animations
  if (animationData.bones) {
    for (const boneName in animationData.bones) {
      const boneAnim = animationData.bones[boneName];
      animationState.keyframes[boneName] = {
        rotation: parseKeyframes(boneAnim.rotation),
        position: parseKeyframes(boneAnim.position),
        scale: parseKeyframes(boneAnim.scale)
      };
    }
  }
  
  console.log(`[Animation] Loaded animation: duration=${animationState.duration}s, loop=${animationState.loop}`);
  updateTimelineUI();
}

function parseKeyframes(data) {
  if (!data) return null;
  
  // Handle simple array value (constant)
  if (Array.isArray(data)) {
    return [{ time: 0, value: data }];
  }
  
  // Handle keyframe object
  const keyframes = [];
  for (const time in data) {
    const value = data[time];
    if (Array.isArray(value)) {
      keyframes.push({ time: parseFloat(time), value: value });
    } else if (typeof value === "object") {
      // Handle pre/post values for interpolation
      keyframes.push({ 
        time: parseFloat(time), 
        value: value.post || value.pre || [0, 0, 0],
        lerp_mode: value.lerp_mode || "linear"
      });
    }
  }
  
  keyframes.sort((a, b) => a.time - b.time);
  return keyframes;
}

function updateAnimation() {
  if (!animationState || !animationState.animationData) return;
  
  const now = performance.now();
  const delta = (now - animationState.lastFrameTime) / 1000;
  animationState.lastFrameTime = now;
  
  if (animationState.playing) {
    animationState.time += delta * animationState.speed;
    
    if (animationState.time >= animationState.duration) {
      if (animationState.loop) {
        animationState.time = animationState.time % animationState.duration;
      } else {
        animationState.time = animationState.duration;
        animationState.playing = false;
      }
    }
    
    applyAnimationFrame(animationState.time);
    updateTimelineUI();
  }
}

function applyAnimationFrame(time) {
  if (!viewer3D || !viewer3D.bones) return;
  
  for (const boneName in animationState.keyframes) {
    const bone = viewer3D.bones[boneName];
    if (!bone) continue;
    
    const boneKeyframes = animationState.keyframes[boneName];
    
    // Apply rotation
    if (boneKeyframes.rotation) {
      const rot = interpolateKeyframes(boneKeyframes.rotation, time);
      if (rot) {
        bone.rotation.x = -rot[0] * Math.PI / 180;
        bone.rotation.y = -rot[1] * Math.PI / 180;
        bone.rotation.z = rot[2] * Math.PI / 180;
      }
    }
    
    // Apply position offset
    if (boneKeyframes.position) {
      const pos = interpolateKeyframes(boneKeyframes.position, time);
      if (pos) {
        const originalPivot = bone.userData.originalPivot || [0, 0, 0];
        bone.position.set(
          -originalPivot[0] - pos[0],
          originalPivot[1] + pos[1],
          originalPivot[2] + pos[2]
        );
      }
    }
    
    // Apply scale
    if (boneKeyframes.scale) {
      const scl = interpolateKeyframes(boneKeyframes.scale, time);
      if (scl) {
        bone.scale.set(scl[0], scl[1], scl[2]);
      }
    }
  }
}

function interpolateKeyframes(keyframes, time) {
  if (!keyframes || keyframes.length === 0) return null;
  
  // Before first keyframe
  if (time <= keyframes[0].time) {
    return keyframes[0].value;
  }
  
  // After last keyframe
  if (time >= keyframes[keyframes.length - 1].time) {
    return keyframes[keyframes.length - 1].value;
  }
  
  // Find surrounding keyframes
  let kf1, kf2;
  for (let i = 0; i < keyframes.length - 1; i++) {
    if (time >= keyframes[i].time && time < keyframes[i + 1].time) {
      kf1 = keyframes[i];
      kf2 = keyframes[i + 1];
      break;
    }
  }
  
  if (!kf1 || !kf2) return keyframes[0].value;
  
  // Linear interpolation
  const t = (time - kf1.time) / (kf2.time - kf1.time);
  return [
    kf1.value[0] + (kf2.value[0] - kf1.value[0]) * t,
    kf1.value[1] + (kf2.value[1] - kf1.value[1]) * t,
    kf1.value[2] + (kf2.value[2] - kf1.value[2]) * t
  ];
}

// Timeline UI functions
function updateTimelineUI() {
  const timeDisplay = document.getElementById("anim-time");
  const slider = document.getElementById("anim-slider");
  const playBtn = document.getElementById("anim-play");
  
  if (timeDisplay && animationState) {
    timeDisplay.textContent = `${animationState.time.toFixed(2)}s / ${animationState.duration.toFixed(2)}s`;
  }
  
  if (slider && animationState && animationState.duration > 0) {
    slider.value = (animationState.time / animationState.duration) * 100;
  }
  
  if (playBtn && animationState) {
    playBtn.textContent = animationState.playing ? "Pause" : "Play";
  }
}

function togglePlayback() {
  if (!animationState) initAnimationState();
  animationState.playing = !animationState.playing;
  animationState.lastFrameTime = performance.now();
  updateTimelineUI();
}

function seekAnimation(percent) {
  if (!animationState) return;
  animationState.time = (percent / 100) * animationState.duration;
  applyAnimationFrame(animationState.time);
  updateTimelineUI();
}

function resetAnimation() {
  if (!animationState) return;
  animationState.time = 0;
  animationState.playing = false;
  applyAnimationFrame(0);
  updateTimelineUI();
}

// Viewport controls
function initViewportControls() {
  const resetViewBtn = document.getElementById("viewport-reset");
  const wireframeBtn = document.getElementById("viewport-wireframe");

  resetViewBtn?.addEventListener("click", () => {
    if (viewer3D && viewer3D.mesh) {
      // Reset camera orbit
      viewer3D.controls.theta = Math.PI * 0.75;
      viewer3D.controls.phi = Math.PI * 0.35;
      viewer3D.controls.distance = 100;
      
      // Recenter on model
      const box = new THREE.Box3().setFromObject(viewer3D.mesh);
      const size = box.getSize(new THREE.Vector3());
      viewer3D.controls.target.set(0, size.y / 2, 0);
      viewer3D.controls.distance = Math.max(size.x, size.y, size.z) * 2;
      viewer3D.updateCameraFromOrbit();
    }
  });

  wireframeBtn?.addEventListener("click", () => {
    if (viewer3D && viewer3D.mesh) {
      let isWireframe = false;
      viewer3D.mesh.traverse(child => {
        if (child.isMesh) {
          child.material.wireframe = !child.material.wireframe;
          isWireframe = child.material.wireframe;
        }
      });
      wireframeBtn.style.opacity = isWireframe ? "1" : "0.6";
    }
  });
  
  // Animation controls
  const playBtn = document.getElementById("anim-play");
  const resetBtn = document.getElementById("anim-reset");
  const slider = document.getElementById("anim-slider");
  
  playBtn?.addEventListener("click", togglePlayback);
  resetBtn?.addEventListener("click", resetAnimation);
  slider?.addEventListener("input", (e) => seekAnimation(parseFloat(e.target.value)));
  
  // 3D Editor controls
  init3DEditorControls();
}

// Initialize 3D Editor control buttons
function init3DEditorControls() {
  console.log('[3D Editor] Initializing controls...');
  
  // Check if buttons exist
  const toolBtns = document.querySelectorAll('.editor-tool-btn');
  const modeBtns = document.querySelectorAll('.editor-mode-btn');
  
  console.log(`[3D Editor] Found ${toolBtns.length} tool buttons, ${modeBtns.length} mode buttons`);
  
  if (toolBtns.length === 0) {
    console.warn('[3D Editor] No tool buttons found - DOM may not be ready');
    return;
  }
  
  // Tool buttons
  toolBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const tool = btn.dataset.tool;
      console.log(`[3D Editor] Tool clicked: ${tool}`);
      setEditorTool(tool);
    });
  });
  
  // Mode buttons
  modeBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      const mode = btn.dataset.mode;
      console.log(`[3D Editor] Mode clicked: ${mode}`);
      setEditorMode(mode);
    });
  });
  
  // Paint color
  const paintColorInput = document.getElementById('editor-paint-color');
  if (paintColorInput) {
    paintColorInput.addEventListener('input', (e) => {
      editor3DState.paintColor = e.target.value;
      console.log(`[3D Editor] Paint color: ${e.target.value}`);
    });
  }
  
  // Background color
  const bgColorInput = document.getElementById('editor-bg-color');
  if (bgColorInput) {
    bgColorInput.addEventListener('input', (e) => {
      console.log(`[3D Editor] Background color: ${e.target.value}`);
      setBackgroundColor(e.target.value);
    });
  }
  
  // Grid toggle
  const gridBtn = document.getElementById('editor-grid');
  if (gridBtn) {
    gridBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('[3D Editor] Grid toggle clicked');
      toggleGrid();
      gridBtn.classList.toggle('active', editor3DState.gridVisible);
    });
  }
  
  // Wireframe toggle
  const wireBtn = document.getElementById('editor-wireframe');
  if (wireBtn) {
    wireBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('[3D Editor] Wireframe toggle clicked');
      toggleWireframe();
      wireBtn.classList.toggle('active', editor3DState.showWireframe);
    });
  }
  
  // Add cube
  const addCubeBtn = document.getElementById('editor-add-cube');
  if (addCubeBtn) {
    addCubeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('[3D Editor] Add cube clicked');
      addCube([0, 8, 0], [8, 8, 8]);
    });
  }
  
  // Duplicate
  const dupBtn = document.getElementById('editor-duplicate');
  if (dupBtn) {
    dupBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('[3D Editor] Duplicate clicked');
      duplicateSelected();
    });
  }
  
  // Delete
  const delBtn = document.getElementById('editor-delete');
  if (delBtn) {
    delBtn.addEventListener('click', (e) => {
      e.preventDefault();
      e.stopPropagation();
      console.log('[3D Editor] Delete clicked');
      deleteSelected();
    });
  }
  
  // Keyboard shortcuts
  document.addEventListener('keydown', (e) => {
    // Only handle if not typing in an input
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
    
    switch(e.key.toLowerCase()) {
      case 'q': setEditorTool('select'); break;
      case 'w': setEditorTool('move'); break;
      case 'e': setEditorTool('rotate'); break;
      case 'r': setEditorTool('scale'); break;
      case 'p': setEditorTool('paint'); break;
      case 'x': setEditorTool('erase'); break;
      case 'i': setEditorTool('pick'); break;
      case 'g': 
        e.preventDefault();
        toggleGrid();
        gridBtn?.classList.toggle('active', editor3DState.gridVisible);
        break;
      case 'z':
        if (e.ctrlKey || e.metaKey) {
          e.preventDefault();
          undo();
        } else {
          e.preventDefault();
          toggleWireframe();
          wireBtn?.classList.toggle('active', editor3DState.showWireframe);
        }
        break;
      case 'delete':
      case 'backspace':
        deleteSelected();
        break;
      case 'escape':
        clearSelection();
        break;
    }
  });
  
  console.log('[3D Editor] Controls initialized');
}

// Copy geometry JSON to clipboard
function initGeometryCopy() {
  const geometryCopy = document.getElementById("geometry-copy");
  geometryCopy?.addEventListener("click", () => {
    const json = geometryCopy.dataset.json;
    if (!json) {
      alert("No geometry loaded yet.");
      return;
    }
    
    navigator.clipboard.writeText(json).then(() => {
      const originalText = geometryCopy.textContent;
      geometryCopy.textContent = "Copied!";
      setTimeout(() => {
        geometryCopy.textContent = originalText;
      }, 2000);
    }).catch(() => {
      alert("Failed to copy to clipboard");
    });
  });
}

// Refresh the 3D model texture when texture data changes
function refresh3DTexture(mobName) {
  if (!viewer3D || !viewer3D.mesh) return;

  const textureData = getUserMobTexture(mobName);
  if (!textureData) return;

  const img = new Image();
  img.src = textureData;
  img.onload = function() {
    // Update the shared canvas-backed texture
    if (viewer3D.texCanvas && viewer3D.texCtx) {
      viewer3D.texCanvas.width = img.width;
      viewer3D.texCanvas.height = img.height;
      viewer3D.texCtx.drawImage(img, 0, 0);
      viewer3D.texWidth = img.width;
      viewer3D.texHeight = img.height;
      if (viewer3D.texTexture) {
        viewer3D.texTexture.needsUpdate = true;
      }
    }
    console.log(`[3D] Texture refreshed for ${mobName}`);
  };
  img.onerror = function() {
    console.warn('[3D] Failed to refresh texture');
  };
}

// =====================
// BLOCKBENCH-STYLE 3D EDITOR FEATURES
// =====================

// =====================
// EDITOR STATE & TOOLS
// =====================

const editor3DState = {
  tool: 'select', // 'select', 'move', 'scale', 'rotate', 'paint', 'erase', 'pick'
  gridVisible: true,
  backgroundColor: 0x1e1e1f,
  selectedObject: null,  // the mesh or group that is selected
  hoverObject: null,
  hoverFace: null,
  paintColor: '#ff0000',
  brushSize: 1,
  showWireframe: false,
  // Transform drag state
  _dragging: false,
  _dragStart: null,       // {x, y} screen coords at drag start
  _dragStartWorld: null,   // THREE.Vector3 world position at drag start
  _origPosition: null,
  _origRotation: null,
  _origScale: null,
  // Undo stack
  _undoStack: [],
};

// Selection outline helper
let selectionBox = null;
let transformGizmo = null;  // The gizmo group (will contain arrow meshes)

// Create rotation rings for rotate mode
function createRotationGizmo() {
  const gizmo = new THREE.Group();
  gizmo.userData._isGizmo = true;
  
  const ringRadius = 10;
  const tubeRadius = 0.4;
  
  // Color codes: Red=X, Green=Y, Blue=Z
  const axes = [
    { name: 'X', color: 0xff0000, rotationAxis: [1, 0, 0] },
    { name: 'Y', color: 0x00ff00, rotationAxis: [0, 1, 0] },
    { name: 'Z', color: 0x0000ff, rotationAxis: [0, 0, 1] }
  ];
  
  axes.forEach(axis => {
    // Create torus ring for rotation
    const ringGeom = new THREE.TorusGeometry(ringRadius, tubeRadius, 16, 128);
    const ringMat = new THREE.MeshPhongMaterial({ 
      color: axis.color, 
      emissive: axis.color, 
      emissiveIntensity: 0.3,
      side: THREE.DoubleSide
    });
    const ring = new THREE.Mesh(ringGeom, ringMat);
    ring.userData.axis = axis.name;
    ring.userData._isGizmoArrow = true;
    ring.userData.color = axis.color;
    
    // Rotate ring to match axis plane
    // TorusGeometry by default is in XY plane (around Z)
    // X axis: rotate to YZ plane = rotate around Z by PI/2
    // Y axis: rotate to XZ plane = rotate around X by PI/2
    // Z axis: keep in XY plane (no rotation)
    if (axis.name === 'X') {
      ring.rotation.z = Math.PI / 2;
    } else if (axis.name === 'Y') {
      ring.rotation.x = Math.PI / 2;
    }
    // Z axis needs no rotation (already in XY plane)
    
    gizmo.add(ring);
  });
  
  return gizmo;
}

// Create a transformation gizmo with three colored arrows (X, Y, Z) or rotation rings
function createTransformGizmo() {
  // If rotate mode, create rotation rings instead
  if (editor3DState.tool === 'rotate') {
    return createRotationGizmo();
  }
  
  const gizmo = new THREE.Group();
  gizmo.userData._isGizmo = true;
  
  const arrowLength = 12;
  const arrowHeadLength = 3;
  const arrowHeadWidth = 1.5;
  const arrowShaftRadius = 0.3;
  
  // Color codes: Red=X, Green=Y, Blue=Z
  const axes = [
    { name: 'X', color: 0xff0000, direction: [1, 0, 0] },
    { name: 'Y', color: 0x00ff00, direction: [0, 1, 0] },
    { name: 'Z', color: 0x0000ff, direction: [0, 0, 1] }
  ];
  
  axes.forEach(axis => {
    // Create arrow as a group (shaft + head)
    const arrowGroup = new THREE.Group();
    arrowGroup.userData.axis = axis.name;
    arrowGroup.userData._isGizmoArrow = true;
    
    // Shaft (thin cylinder)
    const shaftGeom = new THREE.CylinderGeometry(arrowShaftRadius, arrowShaftRadius, arrowLength - arrowHeadLength, 8);
    const shaftMat = new THREE.MeshPhongMaterial({ color: axis.color, emissive: axis.color, emissiveIntensity: 0.3 });
    const shaft = new THREE.Mesh(shaftGeom, shaftMat);
    shaft.position[axis.direction[0] ? 0 : (axis.direction[1] ? 1 : 2)] = (arrowLength - arrowHeadLength) / 2;
    arrowGroup.add(shaft);
    
    // Arrow head (cone)
    const headGeom = new THREE.ConeGeometry(arrowHeadWidth, arrowHeadLength, 8);
    const headMat = new THREE.MeshPhongMaterial({ color: axis.color, emissive: axis.color, emissiveIntensity: 0.5 });
    const head = new THREE.Mesh(headGeom, headMat);
    const axisIdx = axis.direction[0] ? 0 : (axis.direction[1] ? 1 : 2);
    head.position[axisIdx] = arrowLength - arrowHeadLength / 2;
    arrowGroup.add(head);
    
    // Rotate arrow to align with axis
    if (axis.name === 'X') {
      arrowGroup.rotation.z = Math.PI / 2;
    } else if (axis.name === 'Z') {
      arrowGroup.rotation.x = -Math.PI / 2;
    }
    // Y axis needs no rotation (already points up)
    
    arrowGroup.userData.color = axis.color;
    gizmo.add(arrowGroup);
  });
  
  return gizmo;
}

function showTransformGizmo(target) {
  // Remove old gizmo
  if (transformGizmo && transformGizmo.parent) {
    transformGizmo.parent.remove(transformGizmo);
  }
  
  // Show gizmo for move, rotate, and scale modes
  if (!['move', 'rotate', 'scale'].includes(editor3DState.tool)) {
    transformGizmo = null;
    return;
  }
  
  if (!target) {
    transformGizmo = null;
    return;
  }
  
  // Create and position new gizmo
  transformGizmo = createTransformGizmo();
  
  // Position gizmo in front of the object (towards the camera)
  updateGizmoPosition(target, transformGizmo);
  
  transformGizmo.userData.attachedTo = target;
  
  // Add gizmo to the same parent as the target
  (target.parent || viewer3D.scene).add(transformGizmo);
  
  console.log('[3D Gizmo] Gizmo shown for', target.userData?.boneName || target.name);
}

function updateGizmoPosition(target, gizmo) {
  // Calculate direction from object to camera
  const objPos = target.getWorldPosition(new THREE.Vector3());
  const camPos = viewer3D.camera.position;
  const dirToCamera = new THREE.Vector3().subVectors(camPos, objPos).normalize();
  
  // Get object bounding box to determine offset distance
  const bbox = new THREE.Box3().setFromObject(target);
  const size = bbox.getSize(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z);
  
  // Offset gizmo towards camera by half the object size + a bit extra
  const offsetDistance = maxDim * 0.6;
  const offsetVec = dirToCamera.multiplyScalar(offsetDistance);
  
  // Set gizmo position (in object's local space)
  const localOffset = new THREE.Vector3().copy(offsetVec);
  if (target.parent) {
    target.parent.worldToLocal(localOffset);
  }
  
  gizmo.position.copy(target.position).add(localOffset);
}

function hideTransformGizmo() {
  if (transformGizmo && transformGizmo.parent) {
    transformGizmo.parent.remove(transformGizmo);
  }
  transformGizmo = null;
}

function clearSelection() {
  if (selectionBox && selectionBox.parent) {
    selectionBox.parent.remove(selectionBox);
  }
  if (transformGizmo && transformGizmo.parent) {
    transformGizmo.parent.remove(transformGizmo);
  }
  selectionBox = null;
  transformGizmo = null;
  editor3DState.selectedObject = null;
}

function selectObject(obj) {
  if (!obj || !viewer3D) return;

  // Walk up to find the bone group (THREE.Group with a boneName)
  let target = obj;
  while (target && !target.userData?.boneName && target.parent && target.parent !== viewer3D.scene && target.parent !== viewer3D.mesh) {
    target = target.parent;
  }

  // Remove old outline
  if (selectionBox && selectionBox.parent) {
    selectionBox.parent.remove(selectionBox);
  }

  editor3DState.selectedObject = target;

  // Create wireframe bounding box outline
  const box = new THREE.Box3().setFromObject(target);
  if (box.isEmpty()) return;

  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());

  const geo = new THREE.BoxGeometry(size.x, size.y, size.z);
  const edges = new THREE.EdgesGeometry(geo);
  selectionBox = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({
    color: 0x1e90ff,
    linewidth: 2,
    depthTest: false,
    transparent: true,
  }));
  selectionBox.renderOrder = 999;
  selectionBox.position.copy(center);
  // Convert to target's parent space if target has a parent
  if (target.parent) {
    target.parent.worldToLocal(selectionBox.position);
  }
  selectionBox.userData._isSelectionBox = true;

  (target.parent || viewer3D.scene).add(selectionBox);
  
  // Show transform gizmo for move/rotate modes
  showTransformGizmo(target);
  
  console.log('[3D Editor] Selected:', target.userData?.boneName || target.name || 'object');
}

function refreshSelectionBox() {
  if (!editor3DState.selectedObject) return;
  selectObject(editor3DState.selectedObject);
}

// Toggle grid visibility
function toggleGrid() {
  if (!viewer3D) return;
  editor3DState.gridVisible = !editor3DState.gridVisible;
  viewer3D.scene.traverse(child => {
    if (child.type === 'GridHelper') child.visible = editor3DState.gridVisible;
  });
}

// Set background color
function setBackgroundColor(color) {
  if (!viewer3D) return;
  editor3DState.backgroundColor = color;
  viewer3D.scene.background = new THREE.Color(color);
}

// Toggle wireframe mode
function toggleWireframe() {
  if (!viewer3D || !viewer3D.mesh) return;
  editor3DState.showWireframe = !editor3DState.showWireframe;
  viewer3D.mesh.traverse(child => {
    if (child.isMesh) {
      child.material.wireframe = editor3DState.showWireframe;
    }
  });
}

function setEditorTool(tool) {
  editor3DState.tool = tool;

  // Update UI buttons
  document.querySelectorAll('.editor-tool-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tool === tool);
  });

  // Update cursor
  const el = document.getElementById('viewport-3d');
  if (el) {
    if (['paint', 'erase', 'pick'].includes(tool)) el.style.cursor = 'crosshair';
    else if (['move', 'rotate', 'scale'].includes(tool)) el.style.cursor = 'grab';
    else el.style.cursor = 'default';
  }
  
  // Show/hide gizmo based on tool
  if (['move', 'rotate', 'scale'].includes(tool) && editor3DState.selectedObject) {
    showTransformGizmo(editor3DState.selectedObject);
  } else {
    hideTransformGizmo();
  }
}

// =====================
// UNDO SYSTEM
// =====================

function pushUndo(label) {
  const obj = editor3DState.selectedObject;
  if (!obj) return;
  editor3DState._undoStack.push({
    label,
    object: obj,
    position: obj.position.clone(),
    rotation: obj.rotation.clone(),
    scale: obj.scale.clone(),
  });
  // Keep stack bounded
  if (editor3DState._undoStack.length > 50) editor3DState._undoStack.shift();
}

function undo() {
  const entry = editor3DState._undoStack.pop();
  if (!entry) return;
  entry.object.position.copy(entry.position);
  entry.object.rotation.copy(entry.rotation);
  entry.object.scale.copy(entry.scale);
  refreshSelectionBox();
  console.log('[3D Editor] Undo:', entry.label);
}

// =====================
// TRANSFORM HELPERS
// =====================

// Project a screen-space mouse delta into world-space movement
function screenToWorldDelta(dx, dy, camera, distance) {
  const vFov = camera.fov * Math.PI / 180;
  const el = document.getElementById('viewport-3d');
  const h = el ? el.clientHeight : 500;
  const worldPerPx = (2 * distance * Math.tan(vFov / 2)) / h;

  // Extract camera's local right (+X) and up (+Y) axes from its world matrix
  const m = camera.matrixWorld.elements;
  const right = new THREE.Vector3(m[0], m[1], m[2]).normalize();
  const up = new THREE.Vector3(m[4], m[5], m[6]).normalize();

  const delta = new THREE.Vector3();
  delta.addScaledVector(right, dx * worldPerPx);
  delta.addScaledVector(up, -dy * worldPerPx);
  return delta;
}

// Paint on the texture at a UV coordinate
function paintAtUV(uv, color, brushSize) {
  if (!viewer3D || !viewer3D.texCtx || !uv) return;

  const ctx = viewer3D.texCtx;
  const tw = viewer3D.texWidth;
  const th = viewer3D.texHeight;
  const size = brushSize || editor3DState.brushSize || 1;

  // UV to pixel (UV y is flipped: 0=bottom, 1=top)
  const px = Math.floor(uv.x * tw);
  const py = Math.floor((1 - uv.y) * th);

  ctx.fillStyle = color;

  if (size <= 1) {
    ctx.fillRect(px, py, 1, 1);
  } else {
    const half = Math.floor(size / 2);
    for (let dy = -half; dy < size - half; dy++) {
      for (let dx = -half; dx < size - half; dx++) {
        const tx = px + dx;
        const ty = py + dy;
        if (tx >= 0 && tx < tw && ty >= 0 && ty < th) {
          ctx.fillRect(tx, ty, 1, 1);
        }
      }
    }
  }

  // Update the Three.js texture
  viewer3D.texTexture.needsUpdate = true;
}

// Erase (paint white) at a UV coordinate
function eraseAtUV(uv, brushSize) {
  paintAtUV(uv, '#ffffff', brushSize);
}

// Save the current texture canvas to localStorage and refresh
function savePaintedTexture() {
  if (!viewer3D || !viewer3D.texCanvas || !viewer3D.currentMobName) return;
  const base64 = viewer3D.texCanvas.toDataURL('image/png');
  if (typeof saveUserMobTexture === 'function') {
    saveUserMobTexture(viewer3D.currentMobName, base64);
    console.log('[3D Paint] Texture saved for', viewer3D.currentMobName);
  }
}

// Color picker: sample the texture color at a UV coordinate
function pickColorAtUV(uv) {
  if (!viewer3D || !viewer3D.texCtx || !uv) return null;
  const tw = viewer3D.texWidth;
  const th = viewer3D.texHeight;
  const px = Math.floor(uv.x * tw);
  const py = Math.floor((1 - uv.y) * th);
  const pixel = viewer3D.texCtx.getImageData(px, py, 1, 1).data;
  const hex = '#' + ((1 << 24) + (pixel[0] << 16) + (pixel[1] << 8) + pixel[2]).toString(16).slice(1);
  return hex;
}

// Raycasting for mouse interaction, painting, and transforms
function setupRaycasting() {
  if (!viewer3D) {
    console.warn('[3D Editor] Cannot setup raycasting - viewer3D not initialized');
    return;
  }

  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const container = document.getElementById('viewport-3d');

  if (!container) {
    console.warn('[3D Editor] Cannot setup raycasting - container not found');
    return;
  }

  let isPainting = false;
  let isTransforming = false;
  let gizmoAxis = null;  // Track which gizmo axis is being dragged (X, Y, or Z)

  function getIntersect(e) {
    const rect = container.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, viewer3D.camera);
    const meshes = [];
    viewer3D.scene.traverse(child => {
      if (child.isMesh && child.visible && !child.userData?._isSelectionBox) meshes.push(child);
    });
    const intersects = raycaster.intersectObjects(meshes, false);
    return intersects.length > 0 ? intersects[0] : null;
  }

  function getGizmoIntersect(e) {
    if (!transformGizmo) return null;
    const rect = container.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(mouse, viewer3D.camera);
    const gizmoMeshes = [];
    transformGizmo.traverse(child => {
      if (child.isMesh && child.visible) {
        gizmoMeshes.push(child);
      }
    });
    const intersects = raycaster.intersectObjects(gizmoMeshes, false);
    return intersects.length > 0 ? intersects[0] : null;
  }

  function handlePaintAction(e) {
    const hit = getIntersect(e);
    if (!hit || !hit.uv) return;

    if (editor3DState.tool === 'paint') {
      paintAtUV(hit.uv, editor3DState.paintColor);
    } else if (editor3DState.tool === 'erase') {
      eraseAtUV(hit.uv);
    } else if (editor3DState.tool === 'pick') {
      const color = pickColorAtUV(hit.uv);
      if (color) {
        editor3DState.paintColor = color;
        const colorInput = document.getElementById('editor-paint-color');
        if (colorInput) colorInput.value = color;
      }
    }
  }

  // --- Transform drag handling ---
  function startTransform(e, axis = null) {
    const obj = editor3DState.selectedObject;
    if (!obj) return false;

    pushUndo(editor3DState.tool);
    isTransforming = true;
    gizmoAxis = axis;  // Store which axis is being used (or null for free transform)
    editor3DState._dragging = true;
    editor3DState._dragStart = { x: e.clientX, y: e.clientY };
    editor3DState._origPosition = obj.position.clone();
    editor3DState._origRotation = obj.rotation.clone();
    editor3DState._origScale = obj.scale.clone();
    container.style.cursor = 'grabbing';
    return true;
  }

  function updateTransform(e) {
    const obj = editor3DState.selectedObject;
    if (!obj || !editor3DState._dragging) return;

    const dx = e.clientX - editor3DState._dragStart.x;
    const dy = e.clientY - editor3DState._dragStart.y;
    const dist = viewer3D.controls ? viewer3D.controls.distance : 100;

    if (editor3DState.tool === 'move') {
      if (gizmoAxis) {
        // Axis-constrained movement (from gizmo)
        const axisDelta = dx - dy;  // Diagonal drag gives combined effect
        const sensitivity = 0.2;
        const worldDelta = axisDelta * sensitivity;
        
        obj.position.copy(editor3DState._origPosition);
        if (gizmoAxis === 'X') {
          obj.position.x -= worldDelta;  // X inverted
        } else if (gizmoAxis === 'Y') {
          obj.position.y += worldDelta;  // Y inverted (flipped)
        } else if (gizmoAxis === 'Z') {
          obj.position.z -= worldDelta;  // Z inverted
        }
      } else {
        // Free movement (no gizmo)
        const delta = screenToWorldDelta(dx, dy, viewer3D.camera, dist);
        obj.position.copy(editor3DState._origPosition).add(delta);
      }
      refreshSelectionBox();
    } else if (editor3DState.tool === 'rotate') {
      if (gizmoAxis) {
        // Axis-constrained rotation (from gizmo)
        const axisDelta = dx - dy;  // Diagonal drag for rotation
        const sensitivity = 0.005;
        
        obj.rotation.copy(editor3DState._origRotation);
        if (gizmoAxis === 'X') {
          obj.rotation.x -= axisDelta * sensitivity;  // X inverted
        } else if (gizmoAxis === 'Y') {
          obj.rotation.y -= axisDelta * sensitivity;  // Y inverted
        } else if (gizmoAxis === 'Z') {
          obj.rotation.z += axisDelta * sensitivity;
        }
      } else {
        // Free rotation (no gizmo)
        const sensitivity = 0.5;
        obj.rotation.copy(editor3DState._origRotation);
        obj.rotation.y += dx * sensitivity * Math.PI / 180;
        obj.rotation.x -= dy * sensitivity * Math.PI / 180;
      }
      refreshSelectionBox();
    } else if (editor3DState.tool === 'scale') {
      if (gizmoAxis) {
        // Axis-constrained scaling (from gizmo)
        const axisDelta = dx - dy;  // Diagonal drag for scaling
        const sensitivity = 0.02;  // Increased from 0.005 for more responsive scaling
        const factor = 1 + axisDelta * sensitivity;
        const clamped = Math.max(0.1, Math.min(5, factor));
        
        obj.scale.copy(editor3DState._origScale);
        if (gizmoAxis === 'X') {
          obj.scale.x *= clamped;  // X axis scaling
        } else if (gizmoAxis === 'Y') {
          obj.scale.y *= clamped;  // Y axis scaling
        } else if (gizmoAxis === 'Z') {
          obj.scale.z *= clamped;  // Z axis scaling
        }
      }
      refreshSelectionBox();
    }
  }

  function stopTransform() {
    if (isTransforming) {
      isTransforming = false;
      gizmoAxis = null;
      editor3DState._dragging = false;
      container.style.cursor = ['move', 'rotate', 'scale'].includes(editor3DState.tool) ? 'grab' : 'default';
    }
  }

  // --- Mouse events ---
  container.addEventListener('mousemove', (e) => {
    // Transform dragging takes priority
    if (isTransforming) {
      updateTransform(e);
      // Update gizmo position and offset as object moves
      if (transformGizmo && editor3DState.selectedObject) {
        updateGizmoPosition(editor3DState.selectedObject, transformGizmo);
      }
      return;
    }

    // Check for gizmo hover (highlight hovered arrow)
    if (['move', 'rotate', 'scale'].includes(editor3DState.tool) && transformGizmo) {
      const gizmoHit = getGizmoIntersect(e);
      let hoveredAxis = null;
      
      if (gizmoHit) {
        let arrowGroup = gizmoHit.object;
        while (arrowGroup && !arrowGroup.userData._isGizmoArrow) {
          arrowGroup = arrowGroup.parent;
        }
        if (arrowGroup) {
          hoveredAxis = arrowGroup.userData.axis;
        }
      }
      
      // Update arrow highlight based on hover
      transformGizmo.children.forEach(arrowGroup => {
        arrowGroup.children.forEach(mesh => {
          if (mesh.isMesh) {
            if (arrowGroup.userData.axis === hoveredAxis) {
              mesh.material.emissiveIntensity = 1.0;  // Brightened when hovered
            } else {
              mesh.material.emissiveIntensity = 0.3;  // Normal state
            }
          }
        });
      });
      
      container.style.cursor = hoveredAxis ? 'crosshair' : 'grab';
    }

    // Continuous painting while dragging
    if (isPainting && ['paint', 'erase'].includes(editor3DState.tool)) {
      handlePaintAction(e);
      return;
    }

    // Hover detection
    const hit = getIntersect(e);
    if (hit) {
      editor3DState.hoverObject = hit.object;
      editor3DState.hoverFace = hit.face;
    } else {
      editor3DState.hoverObject = null;
      editor3DState.hoverFace = null;
    }
  });

  container.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;

    const tool = editor3DState.tool;
    const isPaintTool = ['paint', 'erase', 'pick'].includes(tool);
    const isTransformTool = ['move', 'rotate', 'scale'].includes(tool);

    // Check if gizmo was clicked first (gizmo interaction has priority)
    if (isTransformTool && ['move', 'rotate', 'scale'].includes(tool)) {
      const gizmoHit = getGizmoIntersect(e);
      if (gizmoHit) {
        // Find the arrow group (parent) that was hit
        let arrowGroup = gizmoHit.object;
        while (arrowGroup && !arrowGroup.userData._isGizmoArrow) {
          arrowGroup = arrowGroup.parent;
        }
        
        if (arrowGroup && arrowGroup.userData.axis) {
          e.stopPropagation();
          const axis = arrowGroup.userData.axis;
          console.log(`[3D Gizmo] Dragging ${tool} on axis: ${axis}`);
          startTransform(e, axis);
          return;
        }
      }
    }

    // Paint tools
    if (isPaintTool && editor3DState.hoverObject) {
      e.stopPropagation();
      isPainting = true;
      handlePaintAction(e);
      return;
    }

    // Transform tools
    if (isTransformTool) {
      // For move/rotate/scale modes: ONLY transform if gizmo arrow was clicked
      if (['move', 'rotate', 'scale'].includes(tool)) {
        // Gizmo arrow click check was already done above, if we get here it's not a gizmo arrow
        // Don't select a new object - keep current selection
        return;
      }
    }

    // Select tool
    if (tool === 'select') {
      if (editor3DState.hoverObject) {
        selectObject(editor3DState.hoverObject);
      } else {
        clearSelection();
      }
    }
  });

  const stopAll = (e) => {
    if (isPainting) {
      isPainting = false;
      savePaintedTexture();
      if (typeof window.onPaintStrokeEnd === "function") window.onPaintStrokeEnd();
    }
    stopTransform();
  };
  container.addEventListener('mouseup', stopAll);
  container.addEventListener('mouseleave', stopAll);

  console.log('[3D Editor] Raycasting + painting + transforms setup complete');
}

// Add a new cube to the scene
function addCube(position = [0, 0, 0], size = [8, 8, 8]) {
  if (!viewer3D) return;
  
  const geometry = new THREE.BoxGeometry(size[0], size[1], size[2]);
  const material = new THREE.MeshLambertMaterial({
    color: 0x4CAF50,
    side: THREE.DoubleSide
  });
  
  const cube = new THREE.Mesh(geometry, material);
  cube.position.set(position[0], position[1], position[2]);
  cube.name = `cube_${Date.now()}`;
  
  viewer3D.scene.add(cube);
  
  console.log('[3D Editor] Added cube at:', position);
  return cube;
}

// Delete selected object
function deleteSelected() {
  if (!viewer3D || !editor3DState.selectedObject) return;
  const obj = editor3DState.selectedObject;
  pushUndo('delete');
  if (obj.parent) obj.parent.remove(obj);
  else viewer3D.scene.remove(obj);
  clearSelection();
  console.log('[3D Editor] Deleted selected object');
}

// Duplicate selected object
function duplicateSelected() {
  if (!viewer3D || !editor3DState.selectedObject) return;

  const original = editor3DState.selectedObject;
  const clone = original.clone();
  clone.position.x += 10;
  clone.name = `${original.name || 'object'}_copy`;

  const parent = original.parent || viewer3D.scene;
  parent.add(clone);
  selectObject(clone);

  console.log('[3D Editor] Duplicated:', original.name);
}

// Initialize editor features
function init3DEditor() {
  setupRaycasting();
  console.log('[3D Editor] Initialized');
}

// Export for external use
window.render3DGeometry = render3DGeometry;
window.loadAnimation = loadAnimation;
window.viewer3D = viewer3D;
window.refresh3DTexture = refresh3DTexture;
window.editor3DState = editor3DState;
window.toggleGrid = toggleGrid;
window.setBackgroundColor = setBackgroundColor;
window.toggleWireframe = toggleWireframe;
window.setEditorTool = setEditorTool;
window.selectObject = selectObject;
window.clearSelection = clearSelection;
window.undo = undo;
window.addCube = addCube;
window.deleteSelected = deleteSelected;
window.duplicateSelected = duplicateSelected;
window.init3DEditor = init3DEditor;
window.setupRaycasting = setupRaycasting;
window.paintAtUV = paintAtUV;
window.savePaintedTexture = savePaintedTexture;
window.createTransformGizmo = createTransformGizmo;
window.showTransformGizmo = showTransformGizmo;
window.hideTransformGizmo = hideTransformGizmo;
window.updateGizmoPosition = updateGizmoPosition;

// Geometry generation via LLM
let currentGeometryData = null;

async function generateGeometry(modify = false) {
  const promptEl = document.getElementById("geometry-prompt");
  const prompt = promptEl?.value?.trim();
  
  if (!prompt) {
    alert("Please enter a description for the geometry you want to generate.");
    return;
  }
  
  const provider = document.getElementById("llm-provider")?.value || "openai";
  const apiKey = document.getElementById("llm-key")?.value?.trim() || "";
  
  const generateBtn = document.getElementById("geometry-generate");
  const modifyBtn = document.getElementById("geometry-modify");
  const originalGenText = generateBtn?.textContent;
  const originalModText = modifyBtn?.textContent;
  
  if (generateBtn) generateBtn.disabled = true;
  if (modifyBtn) modifyBtn.disabled = true;
  if (modify && modifyBtn) modifyBtn.textContent = "Generating...";
  else if (generateBtn) generateBtn.textContent = "Generating...";
  
  try {
    const body = {
      prompt: prompt,
      provider: provider
    };

    if (apiKey) body.api_key = apiKey;
    if (modify && currentGeometryData) body.current_geometry = currentGeometryData;

    const mobName = (typeof currentMobName !== "undefined" && currentMobName) ? currentMobName : "custom_mob";
    body.mob_name = mobName;

    const response = await fetch("/api/geometry/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || "Failed to generate geometry");
    }

    if (data.geometry) {
      currentGeometryData = data.geometry;
      render3DGeometry(data.geometry);

      const geometryViewer = document.getElementById("geometry-viewer");
      if (geometryViewer) {
        geometryViewer.textContent = JSON.stringify(data.geometry, null, 2);
      }

      const geometryCopy = document.getElementById("geometry-copy");
      if (geometryCopy) {
        geometryCopy.dataset.json = JSON.stringify(data.geometry, null, 2);
      }

      const container = document.getElementById("geometry-container");
      if (container) container.style.display = "block";

      // If MCP generated a matching texture, load it into the Pixel Painter
      if (data.texture_b64 && typeof saveUserMobTexture === "function" && mobName) {
        saveUserMobTexture(mobName, data.texture_b64);
        if (typeof loadTextureIntoPainter === "function") {
          loadTextureIntoPainter(mobName);
        }
        if (typeof refresh3DTexture === "function") {
          refresh3DTexture(mobName);
        }
        console.log("[Geometry] MCP texture generated and loaded into Pixel Painter");
      }

      console.log("[Geometry] Generated successfully", data.mcp_texture ? "(with MCP texture)" : "");
    }
  } catch (err) {
    console.error("[Geometry] Generation failed:", err);
    alert("Failed to generate geometry: " + err.message);
  } finally {
    if (generateBtn) {
      generateBtn.disabled = false;
      generateBtn.textContent = originalGenText;
    }
    if (modifyBtn) {
      modifyBtn.disabled = false;
      modifyBtn.textContent = originalModText;
    }
  }
}

function initGeometryGenerator() {
  const generateBtn = document.getElementById("geometry-generate");
  const modifyBtn = document.getElementById("geometry-modify");
  
  generateBtn?.addEventListener("click", () => generateGeometry(false));
  modifyBtn?.addEventListener("click", () => generateGeometry(true));
}

// Store current geometry when loaded from API
window.setCurrentGeometry = function(geometry) {
  currentGeometryData = geometry;
};

window.generateGeometry = generateGeometry;
window.initGeometryGenerator = initGeometryGenerator;
