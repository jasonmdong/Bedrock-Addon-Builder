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
    maxDistance: 500
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
    if (e.button === 0) controls.isRotating = true;
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
    controls.distance = Math.max(
      controls.minDistance,
      Math.min(controls.maxDistance, controls.distance + delta * controls.zoomSpeed)
    );
    updateCameraFromOrbit();
  }, { passive: false });
  
  renderer.domElement.addEventListener("contextmenu", (e) => e.preventDefault());
  
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

function applyBoxUV(geometry, uv, size, textureWidth, textureHeight) {
  // Handle missing UV data
  if (!uv || uv.length < 2) {
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
  
  // Three.js BoxGeometry face order: right(+x), left(-x), top(+y), bottom(-y), front(+z), back(-z)
  // Each face: 4 vertices × 2 coords = 8 values
  // Vertex order: bottom-left, bottom-right, top-left, top-right
  
  // Face definitions: [u, v, width, height, mirrorU, mirrorV]
  const faces = [
    // Right face - to the left of front (negative U direction)
    [u - d, v, d, h, true, false],
    // Left face - to the right of front
    [u + w, v, d, h, false, false],
    // Top face - above front (negative V direction)
    [u, v - d, w, d, false, false],
    // Bottom face - below front area, mirrored V
    [u + w, v - d, w, d, false, true],
    // Front face - the anchor point
    [u, v, w, h, false, false],
    // Back face - further right, mirrored U
    [u + w + d, v, w, h, true, false]
  ];
  
  for (const [fu, fv, fw, fh, mirrorU, mirrorV] of faces) {
    let u1 = toU(fu);
    let u2 = toU(fu + fw);
    let v1 = toV(fv + fh); // bottom (after Y-flip)
    let v2 = toV(fv);      // top (after Y-flip)
    
    if (mirrorU) [u1, u2] = [u2, u1];
    if (mirrorV) [v1, v2] = [v2, v1];
    
    // 4 vertices: BL, BR, TL, TR
    uvArray.push(u1, v1, u2, v1, u1, v2, u2, v2);
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
  const uv = cube.uv || [0, 0];
  
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
    applyBoxUV(geometry, uv, size, textureWidth, textureHeight);
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

function render3DGeometry(geometryData, mobName) {
  console.log("[3D] Rendering geometry with Blockbench-style transformations");
  
  if (!viewer3D) {
    viewer3D = initializeViewer3D();
    // Initialize editor features after viewer is created
    setupRaycasting();
  }
  
  if (!viewer3D) return;
  
  // Clear previous mesh
  if (viewer3D.mesh) {
    viewer3D.scene.remove(viewer3D.mesh);
    viewer3D.bones = {};
  }
  
  // Get the texture for this mob
  const textureData = mobName ? getUserMobTexture(mobName) : null;
  let texture = null;
  let textureWidth = 64;
  let textureHeight = 64;
  
  if (textureData) {
    // Create texture from base64 data
    const img = new Image();
    img.src = textureData;
    texture = new THREE.Texture(img);
    texture.magFilter = THREE.NearestFilter;
    texture.minFilter = THREE.NearestFilter;
    texture.wrapS = THREE.ClampToEdgeWrapping;
    texture.wrapT = THREE.ClampToEdgeWrapping;
    img.onload = function() {
      texture.needsUpdate = true;
      textureWidth = img.width;
      textureHeight = img.height;
      console.log(`[3D] Texture loaded: ${textureWidth}x${textureHeight}`);
    };
    img.onerror = function() {
      console.warn('[3D] Failed to load texture');
    };
  }
  
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
      case 'g': 
        e.preventDefault();
        toggleGrid();
        gridBtn?.classList.toggle('active', editor3DState.gridVisible);
        break;
      case 'z':
        if (!e.ctrlKey && !e.metaKey) {
          e.preventDefault();
          toggleWireframe();
          wireBtn?.classList.toggle('active', editor3DState.showWireframe);
        }
        break;
      case 'delete':
      case 'backspace':
        deleteSelected();
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

// Refresh the 3D model texture when the painter saves a new texture
function refresh3DTexture(mobName) {
  if (!viewer3D || !viewer3D.mesh) return;
  
  // Get the new texture
  const textureData = getUserMobTexture(mobName);
  if (!textureData) return;
  
  // Create new texture
  const img = new Image();
  img.src = textureData;
  const newTexture = new THREE.Texture(img);
  newTexture.magFilter = THREE.NearestFilter;
  newTexture.minFilter = THREE.NearestFilter;
  newTexture.wrapS = THREE.ClampToEdgeWrapping;
  newTexture.wrapT = THREE.ClampToEdgeWrapping;
  
  img.onload = function() {
    newTexture.needsUpdate = true;
    
    // Update all mesh materials with the new texture
    viewer3D.mesh.traverse(child => {
      if (child.isMesh && child.material) {
        // Create new material with texture
        child.material = new THREE.MeshLambertMaterial({
          map: newTexture,
          side: THREE.DoubleSide,
          transparent: true,
          alphaTest: 0.05
        });
      }
    });
    
    console.log(`[3D] Texture refreshed for ${mobName}`);
  };
  
  img.onerror = function() {
    console.warn('[3D] Failed to refresh texture');
  };
}

// =====================
// BLOCKBENCH-STYLE 3D EDITOR FEATURES
// =====================

// Editor state
const editor3DState = {
  mode: 'object', // 'object', 'face', 'edge', 'vertex'
  tool: 'select', // 'select', 'move', 'scale', 'rotate', 'paint', 'erase'
  gridVisible: true,
  backgroundColor: 0x1e1e1f,
  selectedObject: null,
  selectedFace: null,
  hoverObject: null,
  hoverFace: null,
  paintColor: '#ff0000',
  showWireframe: false,
  snapToGrid: false,
  gridSize: 16
};

// Toggle grid visibility
function toggleGrid() {
  if (!viewer3D) return;
  editor3DState.gridVisible = !editor3DState.gridVisible;
  
  viewer3D.scene.traverse(child => {
    if (child.type === 'GridHelper') {
      child.visible = editor3DState.gridVisible;
    }
  });
  
  console.log(`[3D Editor] Grid ${editor3DState.gridVisible ? 'shown' : 'hidden'}`);
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
  
  console.log(`[3D Editor] Wireframe ${editor3DState.showWireframe ? 'on' : 'off'}`);
}

// Set editor mode (object, face, edge, vertex)
function setEditorMode(mode) {
  editor3DState.mode = mode;
  console.log(`[3D Editor] Mode set to: ${mode}`);
  
  // Update UI
  document.querySelectorAll('.editor-mode-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.mode === mode);
  });
}

// Set editor tool (select, move, scale, rotate, paint)
function setEditorTool(tool) {
  editor3DState.tool = tool;
  console.log(`[3D Editor] Tool set to: ${tool}`);
  
  // Update UI
  document.querySelectorAll('.editor-tool-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tool === tool);
  });
  
  // Update cursor
  const canvas = document.getElementById('viewport-3d');
  if (canvas) {
    canvas.style.cursor = tool === 'paint' ? 'crosshair' : 'default';
  }
}

// Paint a face with a color
function paintFace(mesh, faceIndex, color) {
  if (!mesh || !mesh.isMesh) return;
  
  console.log(`[3D Editor] Painting mesh ${mesh.name || 'unnamed'}, face ${faceIndex}`);
  
  // For BoxGeometry, each face is made of 2 triangles (6 vertices)
  // faceIndex from raycaster corresponds to the triangle index
  // We need to convert to face index (0-5 for box faces)
  const boxFaceIndex = Math.floor(faceIndex / 2);
  
  // Get the geometry
  const geometry = mesh.geometry;
  if (!geometry) return;
  
  // Check if we have vertex colors attribute
  let colors = geometry.getAttribute('color');
  if (!colors) {
    // Initialize vertex colors (white by default)
    const count = geometry.attributes.position.count;
    colors = new THREE.Float32BufferAttribute(new Array(count * 3).fill(1), 3);
    geometry.setAttribute('color', colors);
    
    // Enable vertex colors on material
    if (mesh.material) {
      mesh.material.vertexColors = true;
      mesh.material.needsUpdate = true;
    }
  }
  
  // Convert hex color to RGB
  const threeColor = new THREE.Color(color);
  const r = threeColor.r;
  const g = threeColor.g;
  const b = threeColor.b;
  
  // BoxGeometry face vertex mapping (each face has 4 vertices, but we need to handle indexed geometry)
  // For a standard BoxGeometry, vertices are arranged in groups of 4 per face
  const verticesPerFace = 4;
  const startVertex = boxFaceIndex * verticesPerFace;
  
  // Paint the 4 vertices of this face
  for (let i = 0; i < verticesPerFace; i++) {
    const vertexIndex = startVertex + i;
    if (vertexIndex * 3 + 2 < colors.array.length) {
      colors.array[vertexIndex * 3] = r;
      colors.array[vertexIndex * 3 + 1] = g;
      colors.array[vertexIndex * 3 + 2] = b;
    }
  }
  
  colors.needsUpdate = true;
  
  console.log(`[3D Editor] Painted face ${boxFaceIndex} (triangle ${faceIndex}) with color ${color}`);
}

// Raycasting for mouse interaction
function setupRaycasting() {
  if (!viewer3D) {
    console.warn('[3D Editor] Cannot setup raycasting - viewer3D not initialized');
    return;
  }
  
  const raycaster = new THREE.Raycaster();
  const mouse = new THREE.Vector2();
  const canvas = document.getElementById('viewport-3d');
  
  if (!canvas) {
    console.warn('[3D Editor] Cannot setup raycasting - canvas not found');
    return;
  }
  
  console.log('[3D Editor] Setting up raycasting...');
  
  // Track mouse position for raycasting
  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    
    raycaster.setFromCamera(mouse, viewer3D.camera);
    
    // Get all meshes from the scene
    const meshes = [];
    viewer3D.scene.traverse(child => {
      if (child.isMesh && child.visible) {
        meshes.push(child);
      }
    });
    
    if (meshes.length > 0) {
      const intersects = raycaster.intersectObjects(meshes, false);
      
      if (intersects.length > 0) {
        const intersect = intersects[0];
        editor3DState.hoverObject = intersect.object;
        editor3DState.hoverFace = intersect.face;
        
        // Highlight hover effect
        if (editor3DState.tool === 'paint') {
          canvas.style.cursor = 'crosshair';
        }
      } else {
        editor3DState.hoverObject = null;
        editor3DState.hoverFace = null;
        canvas.style.cursor = editor3DState.tool === 'select' ? 'default' : 'crosshair';
      }
    }
  });
  
  canvas.addEventListener('mousedown', (e) => {
    // Only handle left click
    if (e.button !== 0) return;
    
    // Don't paint if we're rotating the view (orbit controls handle this)
    if (!editor3DState.hoverObject) return;
    
    const mesh = editor3DState.hoverObject;
    
    switch (editor3DState.tool) {
      case 'select':
        editor3DState.selectedObject = mesh;
        console.log('[3D Editor] Selected:', mesh.name || 'unnamed');
        break;
        
      case 'paint':
        if (editor3DState.hoverFace) {
          console.log(`[3D Editor] Painting face ${editor3DState.hoverFace.materialIndex} with color ${editor3DState.paintColor}`);
          paintFace(mesh, editor3DState.hoverFace.materialIndex, editor3DState.paintColor);
        }
        break;
        
      case 'erase':
        // Hide the mesh (don't delete to allow undo)
        mesh.visible = false;
        console.log('[3D Editor] Hidden:', mesh.name || 'unnamed');
        break;
    }
  });
  
  console.log('[3D Editor] Raycasting setup complete');
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
  
  viewer3D.scene.remove(editor3DState.selectedObject);
  editor3DState.selectedObject = null;
  
  console.log('[3D Editor] Deleted selected object');
}

// Duplicate selected object
function duplicateSelected() {
  if (!viewer3D || !editor3DState.selectedObject) return;
  
  const original = editor3DState.selectedObject;
  const clone = original.clone();
  clone.position.x += 10;
  clone.name = `${original.name}_copy`;
  
  viewer3D.scene.add(clone);
  editor3DState.selectedObject = clone;
  
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
window.setEditorMode = setEditorMode;
window.setEditorTool = setEditorTool;
window.addCube = addCube;
window.deleteSelected = deleteSelected;
window.duplicateSelected = duplicateSelected;
window.init3DEditor = init3DEditor;
window.setupRaycasting = setupRaycasting;
window.paintFace = paintFace;

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
      
      // Update the JSON viewer
      const geometryViewer = document.getElementById("geometry-viewer");
      if (geometryViewer) {
        geometryViewer.textContent = JSON.stringify(data.geometry, null, 2);
      }
      
      // Update copy button data
      const geometryCopy = document.getElementById("geometry-copy");
      if (geometryCopy) {
        geometryCopy.dataset.json = JSON.stringify(data.geometry, null, 2);
      }
      
      // Show the geometry container if hidden
      const container = document.getElementById("geometry-container");
      if (container) container.style.display = "block";
      
      console.log("[Geometry] Generated successfully");
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
