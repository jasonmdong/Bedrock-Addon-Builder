// =====================
// 3D GEOMETRY VISUALIZATION
// =====================

let viewer3D = null;

function initializeViewer3D() {
  const container = document.getElementById("viewport-3d");
  if (!container) return null;
  
  // Clear any existing viewer
  container.innerHTML = "";
  
  // Scene setup
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x222222);
  
  // Camera setup
  const width = container.clientWidth;
  const height = container.clientHeight;
  const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000);
  camera.position.set(0, 0, 100);
  
  // Renderer setup
  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(width, height);
  renderer.shadowMap.enabled = true;
  container.appendChild(renderer.domElement);
  
  // Lighting
  const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
  scene.add(ambientLight);
  
  const directionalLight = new THREE.DirectionalLight(0xffffff, 0.8);
  directionalLight.position.set(50, 100, 50);
  directionalLight.castShadow = true;
  directionalLight.shadow.mapSize.width = 2048;
  directionalLight.shadow.mapSize.height = 2048;
  scene.add(directionalLight);
  
  // Grid helper (optional, for reference)
  const gridHelper = new THREE.GridHelper(200, 20, 0x444444, 0x222222);
  scene.add(gridHelper);
  
  // Mouse controls (OrbitControls-like behavior)
  const controls = {
    isRotating: false,
    isPanning: false,
    previousMousePosition: { x: 0, y: 0 },
    rotationSpeed: 0.005,
    panSpeed: 0.5,
    zoomSpeed: 5
  };
  
  renderer.domElement.addEventListener("mousedown", (e) => {
    controls.previousMousePosition = { x: e.clientX, y: e.clientY };
    if (e.button === 0) controls.isRotating = true; // Left click
    if (e.button === 2) controls.isPanning = true;  // Right click
  });
  
  renderer.domElement.addEventListener("mousemove", (e) => {
    const deltaX = e.clientX - controls.previousMousePosition.x;
    const deltaY = e.clientY - controls.previousMousePosition.y;
    
    if (controls.isRotating) {
      // Rotate around Y axis
      const quaternion = new THREE.Quaternion();
      quaternion.setFromAxisAngle(new THREE.Vector3(0, 1, 0), deltaX * controls.rotationSpeed);
      viewer3D.mesh?.quaternion.multiplyQuaternions(quaternion, viewer3D.mesh.quaternion);
      
      // Rotate around X axis (local)
      const quaternionX = new THREE.Quaternion();
      quaternionX.setFromAxisAngle(new THREE.Vector3(1, 0, 0), deltaY * controls.rotationSpeed);
      viewer3D.mesh?.quaternion.multiplyQuaternions(viewer3D.mesh.quaternion, quaternionX);
    }
    
    if (controls.isPanning) {
      camera.position.x -= deltaX * controls.panSpeed;
      camera.position.y += deltaY * controls.panSpeed;
    }
    
    controls.previousMousePosition = { x: e.clientX, y: e.clientY };
  });
  
  renderer.domElement.addEventListener("mouseup", () => {
    controls.isRotating = false;
    controls.isPanning = false;
  });
  
  renderer.domElement.addEventListener("wheel", (e) => {
    e.preventDefault();
    const zoomDirection = e.deltaY > 0 ? 1 : -1;
    const direction = camera.position.clone().normalize();
    camera.position.addScaledVector(direction, zoomDirection * controls.zoomSpeed);
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
  const animate = () => {
    requestAnimationFrame(animate);
    renderer.render(scene, camera);
  };
  
  animate();
  
  return {
    scene,
    camera,
    renderer,
    mesh: null,
    controls,
    dispose: () => {
      window.removeEventListener("resize", handleResize);
      renderer.dispose();
      container.innerHTML = "";
    }
  };
}

function render3DGeometry(geometryData) {
  // Initialize viewer if not already done
  if (!viewer3D) {
    viewer3D = initializeViewer3D();
  }
  
  if (!viewer3D) return;
  
  // Clear previous mesh
  if (viewer3D.mesh) {
    viewer3D.scene.remove(viewer3D.mesh);
  }
  
  // Create root group for all bones
  const rootGroup = new THREE.Group();
  
  try {
    // Debug: Log the structure of the geometry data
    console.log("[3D] Raw geometry data keys:", Object.keys(geometryData));
    
    // Parse Bedrock geometry format
    let geometries = [];
    
    if (Array.isArray(geometryData)) {
      geometries = geometryData;
      console.log("[3D] Parsed as direct array");
    } else if (geometryData["minecraft:geometry"]) {
      geometries = geometryData["minecraft:geometry"];
      console.log("[3D] Parsed minecraft:geometry array");
    } else if (geometryData.bones) {
      geometries = [geometryData];
      console.log("[3D] Parsed as single geometry with bones");
    } else {
      const geometryKeys = Object.keys(geometryData).filter(key => key.includes("geometry"));
      if (geometryKeys.length > 0) {
        const geometryKey = geometryKeys[0];
        const geometryObj = geometryData[geometryKey];
        
        if (Array.isArray(geometryObj)) {
          geometries = geometryObj;
          console.log(`[3D] Parsed ${geometryKey} as array`);
        } else if (geometryObj && geometryObj.bones) {
          geometries = [geometryObj];
          console.log(`[3D] Parsed ${geometryKey} as single geometry with bones`);
        } else {
          console.warn("[3D] Geometry object found but no bones. Keys:", Object.keys(geometryObj || {}));
          return;
        }
      } else {
        console.warn("[3D] Could not parse geometry structure. Available keys:", Object.keys(geometryData));
        return;
      }
    }
    
    console.log("[3D] Found geometries:", geometries.length);
    
    let cubeCount = 0;
    let boneCount = 0;
    
    geometries.forEach((geom, geomIdx) => {
      if (!geom || !geom.bones) return;
      
      console.log(`[3D] Geometry ${geomIdx} has ${geom.bones.length} bones`);
      
      // Create a map of bone names to bone objects for parent lookup
      const boneMap = {};
      geom.bones.forEach(bone => {
        boneMap[bone.name] = bone;
      });
      
      // Create a map of bone names to THREE.Group objects
      const boneGroupMap = {};
      
      // First pass: Create groups for all bones positioned at their pivot
      geom.bones.forEach((bone) => {
        if (!bone) return;
        
        boneCount++;
        
        // Create a group for this bone
        const boneGroup = new THREE.Group();
        
        // Position the bone group at the bone's pivot point
        const pivot = bone.pivot || [0, 0, 0];
        boneGroup.position.set(pivot[0], pivot[1], -pivot[2]); // Z is inverted for Minecraft Y-up
        
        // Apply bone rotation (convert from degrees to radians)
        const rotation = bone.rotation || [0, 0, 0];
        const bindPoseRotation = bone.bind_pose_rotation || [0, 0, 0];
        
        // Combine rotation and bind_pose_rotation
        const totalRotation = [
          (rotation[0] || 0) + (bindPoseRotation[0] || 0),
          (rotation[1] || 0) + (bindPoseRotation[1] || 0),
          (rotation[2] || 0) + (bindPoseRotation[2] || 0)
        ];
        
        if (totalRotation[0] || totalRotation[1] || totalRotation[2]) {
          boneGroup.rotation.order = "ZYX";
          boneGroup.rotation.x = totalRotation[0] * Math.PI / 180;
          boneGroup.rotation.y = totalRotation[1] * Math.PI / 180;
          boneGroup.rotation.z = totalRotation[2] * Math.PI / 180;
          
          if (bindPoseRotation[0] || bindPoseRotation[1] || bindPoseRotation[2]) {
            console.log(`[3D] Applied bind_pose_rotation to bone "${bone.name}": ${JSON.stringify(bindPoseRotation)}`);
          }
        }
        
        // Apply scale if present
        const scale = bone.scale || [1, 1, 1];
        if (scale[0] !== 1 || scale[1] !== 1 || scale[2] !== 1) {
          boneGroup.scale.set(scale[0], scale[1], scale[2]);
        }
        
        boneGroupMap[bone.name] = boneGroup;
      });
      
      // Second pass: Build hierarchy and add cubes
      geom.bones.forEach((bone) => {
        if (!bone) return;
        
        // Skip bones marked as neverRender
        if (bone.neverRender === true) {
          console.log(`[3D] Skipping bone "${bone.name}" (neverRender=true)`);
          return;
        }
        
        const boneGroup = boneGroupMap[bone.name];
        
        // Add cubes to this bone's group
        if (bone.cubes && bone.cubes.length > 0) {
          console.log(`[3D] Bone "${bone.name}" has ${bone.cubes.length} cubes`);
          
          bone.cubes.forEach((cube, cubeIdx) => {
            // Skip cubes marked as neverRender
            if (cube.neverRender === true) {
              console.log(`[3D] Skipping cube ${cubeIdx} in bone "${bone.name}" (neverRender=true)`);
              return;
            }
            
            cubeCount++;
            
            // Get cube properties
            const origin = cube.origin || [0, 0, 0];
            const size = cube.size || [1, 1, 1];
            const cubeRotation = cube.rotation || [0, 0, 0];
            const inflate = cube.inflate || 0;
            
            console.log(`[3D] Cube ${cubeIdx}: origin=${JSON.stringify(origin)}, size=${JSON.stringify(size)}`);
            
            // Adjust size with inflation (inflate expands in all directions)
            const adjustedSize = [
              size[0] + inflate * 2,
              size[1] + inflate * 2,
              size[2] + inflate * 2
            ];
            
            // Create box geometry
            const boxGeom = new THREE.BoxGeometry(...adjustedSize);
            const material = new THREE.MeshPhongMaterial({
              color: Math.random() * 0xffffff,
              emissive: 0x111111,
              side: THREE.DoubleSide,
              wireframe: false
            });
            
            const mesh = new THREE.Mesh(boxGeom, material);
            
            // Get bone pivot for offset calculation
            const pivot = bone.pivot || [0, 0, 0];
            
            // Calculate cube center (Minecraft origin is min corner, Three.js positions at center)
            const cubeCenter = [
              origin[0] + size[0] / 2,
              origin[1] + size[1] / 2,
              origin[2] + size[2] / 2
            ];
            
            // Cube position in local space: cubeCenter - pivot
            const localPos = [
              cubeCenter[0] - pivot[0],
              cubeCenter[1] - pivot[1],
              -(cubeCenter[2] - pivot[2]) // Z is inverted for Minecraft Y-up
            ];
            
            mesh.position.set(localPos[0], localPos[1], localPos[2]);
            
            // Apply cube rotation (convert from degrees to radians)
            if (cubeRotation[0] || cubeRotation[1] || cubeRotation[2]) {
              mesh.rotation.order = "ZYX";
              mesh.rotation.x = (cubeRotation[0] || 0) * Math.PI / 180;
              mesh.rotation.y = (cubeRotation[1] || 0) * Math.PI / 180;
              mesh.rotation.z = (cubeRotation[2] || 0) * Math.PI / 180;
            }
            
            boneGroup.add(mesh);
          });
        }
        
        // Build parent-child hierarchy
        const parentName = bone.parent;
        if (parentName && boneGroupMap[parentName]) {
          // Convert child bone position to parent-local space
          // Child pivot is in world space, parent pivot is in world space
          // When adding as child, position must be relative to parent
          const parentBone = boneMap[parentName];
          const parentPivot = parentBone.pivot || [0, 0, 0];
          const childPivot = bone.pivot || [0, 0, 0];
          
          // Convert child's world-space position to parent-local space
          const childInParentSpace = [
            childPivot[0] - parentPivot[0],
            childPivot[1] - parentPivot[1],
            -(childPivot[2] - parentPivot[2]) // Z is inverted for Minecraft Y-up
          ];
          
          // Update the child bone group's position to parent-local space
          boneGroup.position.set(childInParentSpace[0], childInParentSpace[1], childInParentSpace[2]);
          
          // Add this bone group to its parent
          boneGroupMap[parentName].add(boneGroup);
          console.log(`[3D] Connected bone "${bone.name}" to parent "${parentName}" at local position ${JSON.stringify(childInParentSpace)}`);
        } else if (parentName) {
          console.warn(`[3D] Bone "${bone.name}" references parent "${parentName}" which was not found`);
          // Add to root if parent not found
          rootGroup.add(boneGroup);
        } else {
          // No parent, add to root - keep pivot position as-is
          rootGroup.add(boneGroup);
        }
      });
    });
    
    // Only proceed if we have cubes
    if (cubeCount === 0) {
      console.warn("[3D] No cubes found in geometry data. Bones processed:", boneCount);
      return;
    }
    
    // Center and frame the model
    const box = new THREE.Box3().setFromObject(rootGroup);
    const center = box.getCenter(new THREE.Vector3());
    rootGroup.position.sub(center);
    
    // Adjust camera to view the model
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    const fov = viewer3D.camera.fov * (Math.PI / 180);
    let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
    cameraZ *= 1.5; // Add some distance
    viewer3D.camera.position.z = cameraZ;
    viewer3D.camera.lookAt(0, 0, 0);
    
    viewer3D.scene.add(rootGroup);
    viewer3D.mesh = rootGroup;
    
    console.log(`[3D] Rendered geometry with ${cubeCount} cubes from ${boneCount} bones`);
  } catch (err) {
    console.error(`[3D] Error rendering geometry:`, err);
    console.error("[3D] Error stack:", err.stack);
  }
}

// Viewport controls
function initViewportControls() {
  const resetViewBtn = document.getElementById("viewport-reset");
  const wireframeBtn = document.getElementById("viewport-wireframe");

  resetViewBtn?.addEventListener("click", () => {
    if (viewer3D && viewer3D.mesh) {
      // Reset rotation
      viewer3D.mesh.quaternion.set(0, 0, 0, 1);
      // Reset camera position
      const box = new THREE.Box3().setFromObject(viewer3D.mesh);
      const size = box.getSize(new THREE.Vector3());
      const maxDim = Math.max(size.x, size.y, size.z);
      const fov = viewer3D.camera.fov * (Math.PI / 180);
      let cameraZ = Math.abs(maxDim / 2 / Math.tan(fov / 2));
      cameraZ *= 1.5;
      viewer3D.camera.position.set(0, 0, cameraZ);
      viewer3D.camera.lookAt(0, 0, 0);
    }
  });

  wireframeBtn?.addEventListener("click", () => {
    if (viewer3D && viewer3D.mesh) {
      viewer3D.mesh.traverse(child => {
        if (child.isMesh) {
          child.material.wireframe = !child.material.wireframe;
        }
      });
      wireframeBtn.style.opacity = viewer3D.mesh.children[0]?.material?.wireframe ? "1" : "0.6";
    }
  });
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
      geometryCopy.textContent = "✅ Copied!";
      setTimeout(() => {
        geometryCopy.textContent = originalText;
      }, 2000);
    }).catch(() => {
      alert("Failed to copy to clipboard");
    });
  });
}
