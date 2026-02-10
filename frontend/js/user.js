// =====================
// USER MANAGEMENT SYSTEM
// =====================

const APP_USERS_KEY = "app_users";
const CURRENT_USER_KEY = "current_user";
const USER_DATA_PREFIX = "user_";
const USER_DATA_SUFFIX = "_data";

// User Modal Elements
const userModalOverlay = document.getElementById("user-modal-overlay");
const userListEl = document.getElementById("user-list");
const newUserInput = document.getElementById("new-user-input");
const createUserBtn = document.getElementById("create-user-btn");
const currentUserDisplay = document.getElementById("current-user-display");
const switchUserBtn = document.getElementById("switch-user-btn");
const backupBtn = document.getElementById("backup-btn");
const restoreBtn = document.getElementById("restore-btn");
const restoreFileInput = document.getElementById("restore-file-input");

// Get list of all users
function getAppUsers() {
  const stored = localStorage.getItem(APP_USERS_KEY);
  return stored ? JSON.parse(stored) : [];
}

// Save list of users
function saveAppUsers(users) {
  localStorage.setItem(APP_USERS_KEY, JSON.stringify(users));
}

// Get current logged-in user
function getCurrentUser() {
  return localStorage.getItem(CURRENT_USER_KEY) || null;
}

// Set current user
function setCurrentUser(username) {
  localStorage.setItem(CURRENT_USER_KEY, username);
}

// Get user data key
function getUserDataKey(username) {
  return USER_DATA_PREFIX + username + USER_DATA_SUFFIX;
}

// Get user's workspace data
function getUserData(username) {
  const key = getUserDataKey(username);
  const stored = localStorage.getItem(key);
  return stored ? JSON.parse(stored) : { mobs: {}, settings: {} };
}

// Save user's workspace data
function saveUserData(username, data) {
  const key = getUserDataKey(username);
  localStorage.setItem(key, JSON.stringify(data));
}

// Get current user's mobs
function getCurrentUserMobs() {
  const user = getCurrentUser();
  if (!user) return {};
  const data = getUserData(user);
  return data.mobs || {};
}

// Save a mob to current user's workspace
function saveUserMob(mobName, spec) {
  const user = getCurrentUser();
  if (!user) return false;
  const data = getUserData(user);
  data.mobs = data.mobs || {};
  data.mobs[mobName] = spec;
  saveUserData(user, data);
  return true;
}

// Delete a mob from current user's workspace
function deleteUserMob(mobName) {
  const user = getCurrentUser();
  if (!user) return false;
  const data = getUserData(user);
  if (data.mobs && data.mobs[mobName]) {
    delete data.mobs[mobName];
    saveUserData(user, data);
    return true;
  }
  return false;
}

// Get a specific mob from current user's workspace
function getUserMob(mobName) {
  const mobs = getCurrentUserMobs();
  return mobs[mobName] || null;
}

// Save a mob's texture as base64 to localStorage
function saveUserMobTexture(mobName, base64Data) {
  const user = getCurrentUser();
  if (!user) return false;
  const data = getUserData(user);
  data.textures = data.textures || {};
  data.textures[mobName] = base64Data;
  saveUserData(user, data);
  return true;
}

// Get a mob's texture from localStorage
function getUserMobTexture(mobName) {
  const user = getCurrentUser();
  if (!user) return null;
  const data = getUserData(user);
  return (data.textures && data.textures[mobName]) || null;
}

// Delete a mob's texture from localStorage
function deleteUserMobTexture(mobName) {
  const user = getCurrentUser();
  if (!user) return false;
  const data = getUserData(user);
  if (data.textures && data.textures[mobName]) {
    delete data.textures[mobName];
    saveUserData(user, data);
    return true;
  }
  return false;
}

// Create a new user
function createUser(username) {
  const users = getAppUsers();
  if (users.includes(username)) {
    alert("User already exists!");
    return false;
  }
  users.push(username);
  saveAppUsers(users);
  // Initialize empty workspace for user
  saveUserData(username, { mobs: {}, settings: {} });
  return true;
}

// Delete a user
function deleteUser(username) {
  const users = getAppUsers();
  const index = users.indexOf(username);
  if (index > -1) {
    users.splice(index, 1);
    saveAppUsers(users);
    // Remove user data
    localStorage.removeItem(getUserDataKey(username));
    return true;
  }
  return false;
}

// Show user selection modal
function showUserModal() {
  if (!userModalOverlay || !userListEl) return;
  renderUserList();
  userModalOverlay.classList.remove("hidden");
}

// Hide user selection modal
function hideUserModal() {
  if (!userModalOverlay) return;
  userModalOverlay.classList.add("hidden");
}

// Render user list in modal
function renderUserList() {
  if (!userListEl) return;
  const users = getAppUsers();
  userListEl.innerHTML = "";
  
  if (users.length === 0) {
    userListEl.innerHTML = '<li style="color: var(--muted); text-align: center; padding: 1rem;">No users yet. Create one below.</li>';
    return;
  }
  
  users.forEach(username => {
    const li = document.createElement("li");
    li.className = "user-list-item";
    
    const nameSpan = document.createElement("span");
    nameSpan.className = "user-name";
    nameSpan.textContent = username;
    li.appendChild(nameSpan);
    
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete-user-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.onclick = (e) => {
      e.stopPropagation();
      if (confirm(`Delete user "${username}" and all their data? This cannot be undone.`)) {
        deleteUser(username);
        if (getCurrentUser() === username) {
          localStorage.removeItem(CURRENT_USER_KEY);
        }
        renderUserList();
      }
    };
    li.appendChild(deleteBtn);
    
    li.onclick = () => selectUser(username);
    userListEl.appendChild(li);
  });
}

// Select and login as user
function selectUser(username) {
  setCurrentUser(username);
  if (currentUserDisplay) currentUserDisplay.textContent = username;
  hideUserModal();
  // Reload the app with user's data
  loadSpec();
}

// Update UI to show current user
function updateUserDisplay() {
  if (!currentUserDisplay) return;
  const user = getCurrentUser();
  if (user) {
    currentUserDisplay.textContent = user;
  } else {
    currentUserDisplay.textContent = "Guest";
  }
}

// Export/Backup user data
function backupUserData() {
  const user = getCurrentUser();
  if (!user) {
    alert("No user logged in.");
    return;
  }
  
  const data = getUserData(user);
  const exportData = {
    version: 1,
    username: user,
    exportedAt: new Date().toISOString(),
    workspace: data
  };
  
  const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `bedrock-builder-backup-${user}-${new Date().toISOString().slice(0,10)}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  
  setStatus(`Backup downloaded for user "${user}".`);
}

// Import/Restore user data
function restoreUserData(file) {
  const user = getCurrentUser();
  if (!user) {
    alert("No user logged in. Please select or create a user first.");
    return;
  }
  
  const reader = new FileReader();
  reader.onload = (e) => {
    try {
      const importData = JSON.parse(e.target.result);
      
      if (!importData.workspace) {
        alert("Invalid backup file format.");
        return;
      }
      
      const confirmMsg = `This will overwrite all data for user "${user}" with the backup data` + 
        (importData.username ? ` (originally from "${importData.username}")` : "") + 
        `. Continue?`;
      
      if (!confirm(confirmMsg)) {
        return;
      }
      
      saveUserData(user, importData.workspace);
      setStatus(`Workspace restored for user "${user}".`);
      loadSpec(); // Reload to show restored data
      
    } catch (err) {
      alert("Failed to parse backup file: " + err.message);
    }
  };
  reader.readAsText(file);
}

// Initialize user system on page load
function initUserSystem() {
  const user = getCurrentUser();
  
  if (!user) {
    // No user logged in, show modal
    showUserModal();
  } else {
    // User exists, update display
    updateUserDisplay();
  }
  
  // Event listeners for user management (with null checks)
  switchUserBtn?.addEventListener("click", showUserModal);
  
  createUserBtn?.addEventListener("click", () => {
    const username = newUserInput.value.trim();
    if (!username) {
      alert("Please enter a username.");
      return;
    }
    if (createUser(username)) {
      newUserInput.value = "";
      selectUser(username);
    }
  });
  
  newUserInput?.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      createUserBtn?.click();
    }
  });
  
  backupBtn?.addEventListener("click", backupUserData);
  
  restoreBtn?.addEventListener("click", () => {
    restoreFileInput?.click();
  });
  
  restoreFileInput?.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) {
      restoreUserData(file);
      restoreFileInput.value = ""; // Reset for next use
    }
  });
}
