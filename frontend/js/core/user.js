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
const currentUserTierBadge = document.getElementById("current-user-tier-badge");
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
  let toStore = spec;
  try {
    if (
      spec &&
      spec.animation_json &&
      spec.geometry_json &&
      Array.isArray(spec.geometry_json["minecraft:geometry"]) &&
      spec.geometry_json["minecraft:geometry"].length &&
      typeof window !== "undefined" &&
      typeof window.mergeProceduralPreviewClipsLocal === "function"
    ) {
      const mergedAnim = window.mergeProceduralPreviewClipsLocal(
        spec.geometry_json,
        spec.animation_json,
        spec.short_name || mobName
      );
      toStore = { ...spec, animation_json: mergedAnim };
    }
  } catch (e) {
    toStore = spec;
  }
  data.mobs[mobName] = toStore;
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

// Get tier for a user
function getUserTier(username) {
  return localStorage.getItem(`user_${username}_tier`) || "free";
}

const VALID_SIGNUP_TIERS = new Set(["free", "creator", "pro"]);

// Create a new user (tier = POC plan selection; no payment)
function createUser(username, tier = "free") {
  const users = getAppUsers();
  if (users.includes(username)) {
    alert("User already exists!");
    return false;
  }
  if (!VALID_SIGNUP_TIERS.has(tier)) {
    tier = "free";
  }
  users.push(username);
  saveAppUsers(users);
  saveUserData(username, { mobs: {}, settings: {} });
  localStorage.setItem(`user_${username}_tier`, tier);
  syncUserToBackend(username, tier);
  return true;
}

// Sync user to Neon DB (fire-and-forget)
async function syncUserToBackend(username, tier) {
  try {
    await fetch("/api/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, subscription_tier: tier }),
    });
  } catch (e) {
    console.warn("User sync failed (offline?):", e);
  }
}

// Fetch and cache tier from backend
async function refreshUserTierFromBackend(username) {
  try {
    const res = await fetch(`/api/users/${encodeURIComponent(username)}`);
    if (res.ok) {
      const data = await res.json();
      localStorage.setItem(`user_${username}_tier`, data.subscription_tier || "free");
    }
  } catch (e) {
    console.warn("Tier fetch failed:", e);
  }
}

const TIER_LIMITS = {
  free:    { mobs: 5,  history: 3,  ai_daily: 20 },
  creator: { mobs: 50, history: 20, ai_daily: 200 },
  pro:     { mobs: -1, history: -1, ai_daily: -1 },
};

/** Max LLM history entries stored per mob (-1 = use practical cap in llm.js). */
function getTierHistoryLimit() {
  const user = getCurrentUser();
  const tier = user ? getUserTier(user) : "free";
  const lim = TIER_LIMITS[tier]?.history ?? 3;
  if (lim === -1) return 50;
  return Math.min(lim, 50);
}

function _aiUsageDateKey() {
  return new Date().toISOString().slice(0, 10);
}

function _aiUsageStorageKey(username) {
  return `user_${username}_ai_actions_${_aiUsageDateKey()}`;
}

function getAiUsageCountToday(username) {
  if (!username) return 0;
  const raw = localStorage.getItem(_aiUsageStorageKey(username));
  return raw ? parseInt(raw, 10) || 0 : 0;
}

/** Increment after a successful AI call (LLM assistant or full mob generation). */
function recordAiAction(username) {
  if (!username) return;
  const key = _aiUsageStorageKey(username);
  const n = getAiUsageCountToday(username) + 1;
  localStorage.setItem(key, String(n));
  updateAiUsageDisplay();
}

/**
 * Whether the user may run another AI action today (POC quota; no payment).
 * @returns {{ ok: boolean, reason?: string, used?: number, cap?: number, remaining?: number }}
 */
function canRunAiAction() {
  const user = getCurrentUser();
  if (!user) return { ok: false, reason: "no_user" };
  const tier = getUserTier(user);
  const cap = TIER_LIMITS[tier]?.ai_daily ?? 20;
  if (cap === -1) return { ok: true, remaining: -1, cap: -1 };
  const used = getAiUsageCountToday(user);
  if (used >= cap) return { ok: false, reason: "daily_cap", used, cap, remaining: 0 };
  return { ok: true, used, cap, remaining: cap - used };
}

/** Must match llm.js llmStackKey() for localStorage. */
function _llmStackStorageKey(user, mob) {
  if (!user) return null;
  const m = mob || "global";
  return `llm_stack_${user}_${m}`;
}

function getCurrentMobHistoryCount() {
  const user = getCurrentUser();
  if (!user) return 0;
  let mob = null;
  try {
    if (typeof currentMobName !== "undefined" && currentMobName) mob = currentMobName;
  } catch (e) {
    /* ignore */
  }
  if (!mob) {
    try {
      mob = localStorage.getItem("builder_current_mob") || null;
    } catch (e) {
      /* ignore */
    }
  }
  const key = _llmStackStorageKey(user, mob);
  if (!key) return 0;
  const raw = localStorage.getItem(key);
  let arr = raw ? JSON.parse(raw) : [];
  if (!Array.isArray(arr)) arr = [];
  return arr.length;
}

/**
 * Update the demo plan usage panel (included / used / left per tier).
 * Safe to call from llm.js, editor, and after tier changes.
 */
function updateTierUsagePanel() {
  const panel = document.getElementById("tier-usage-panel");
  const sidebarLine = document.getElementById("sidebar-usage-line");
  const nameEl = document.getElementById("tier-usage-name");
  const aiEl = document.getElementById("tier-usage-ai");
  const mobsEl = document.getElementById("tier-usage-mobs");
  const histEl = document.getElementById("tier-usage-history");

  const user = getCurrentUser();
  if (!user) {
    if (nameEl) nameEl.textContent = "—";
    if (aiEl) aiEl.textContent = "Sign in to see limits.";
    if (mobsEl) mobsEl.textContent = "—";
    if (histEl) histEl.textContent = "—";
    if (sidebarLine) sidebarLine.textContent = "";
    return;
  }

  const tier = getUserTier(user);
  const lim = TIER_LIMITS[tier] || TIER_LIMITS.free;
  const tierLabel = tier.charAt(0).toUpperCase() + tier.slice(1);

  if (nameEl) {
    nameEl.textContent = tierLabel;
    nameEl.className = `tier-usage-plan-pill tier-badge-${tier}`;
  }

  const aiCap = lim.ai_daily;
  const aiUsed = getAiUsageCountToday(user);
  if (aiEl) {
    if (aiCap === -1) {
      aiEl.textContent = `Included: unlimited · Used: ${aiUsed} · Left: unlimited`;
    } else {
      const left = Math.max(0, aiCap - aiUsed);
      aiEl.textContent = `Included: ${aiCap}/day · Used: ${aiUsed} · Left: ${left}`;
    }
  }

  const mobCap = lim.mobs;
  const mobUsed = Object.keys(getCurrentUserMobs()).length;
  if (mobsEl) {
    if (mobCap === -1) {
      mobsEl.textContent = `Included: unlimited · Used: ${mobUsed} · Left: unlimited`;
    } else {
      const left = Math.max(0, mobCap - mobUsed);
      mobsEl.textContent = `Included: ${mobCap} · Used: ${mobUsed} · Left: ${left}`;
    }
  }

  const histCap = getTierHistoryLimit();
  const histUsed = getCurrentMobHistoryCount();
  if (histEl) {
    if (lim.history === -1) {
      histEl.textContent = `Included: ${histCap} stored (demo cap) · Used: ${histUsed} · Left: ${Math.max(0, histCap - histUsed)}`;
    } else {
      const left = Math.max(0, histCap - histUsed);
      histEl.textContent = `Included: ${histCap} · Used: ${histUsed} · Left: ${left}`;
    }
  }

  if (sidebarLine) {
    const aiPart =
      aiCap === -1
        ? `AI · ${aiUsed} used`
        : `AI · ${aiUsed}/${aiCap} · ${Math.max(0, aiCap - aiUsed)} left`;
    const mobPart =
      mobCap === -1
        ? `${mobUsed} mobs`
        : `${mobUsed}/${mobCap} mobs · ${Math.max(0, mobCap - mobUsed)} left`;
    sidebarLine.textContent = `${tierLabel}: ${aiPart} · ${mobPart}`;
  }

  const llmInline = document.getElementById("tier-usage-llm-inline");
  if (llmInline) {
    if (!user) {
      llmInline.textContent = "";
    } else if (aiCap === -1) {
      llmInline.textContent = `Demo plan · AI prompts today: ${aiUsed} used (unlimited on Pro)`;
    } else {
      const left = Math.max(0, aiCap - aiUsed);
      llmInline.textContent = `Demo plan · AI prompts: ${aiUsed} used · ${left} left of ${aiCap} today`;
    }
  }

  if (panel) panel.style.display = "";
}

/** @deprecated use updateTierUsagePanel */
function updateAiUsageDisplay() {
  updateTierUsagePanel();
}

/** Change demo tier without creating a new account (POC). */
function setUserTier(username, tier) {
  if (!username || !VALID_SIGNUP_TIERS.has(tier)) return false;
  localStorage.setItem(`user_${username}_tier`, tier);
  syncUserToBackend(username, tier);
  updateAiUsageDisplay();
  updateUserDisplay();
  try {
    document.dispatchEvent(new CustomEvent("user-tier-changed", { detail: { username, tier } }));
  } catch (e) { /* ignore */ }
  return true;
}

function canAddMob() {
  const user = getCurrentUser();
  if (!user) return false;
  const tier = getUserTier(user);
  const limit = TIER_LIMITS[tier]?.mobs ?? 5;
  if (limit === -1) return true;
  const mobs = getCurrentUserMobs();
  return Object.keys(mobs).length < limit;
}

function getTierMobLimit() {
  const user = getCurrentUser();
  if (!user) return 5;
  const tier = getUserTier(user);
  return TIER_LIMITS[tier]?.mobs ?? 5;
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
    localStorage.removeItem(`user_${username}_tier`);
    return true;
  }
  return false;
}

// Show user selection modal
function showUserModal() {
  if (!userModalOverlay || !userListEl) return;
  renderUserList();
  // Always reset tier selection to "free" when the modal opens
  const tierRoot = document.getElementById("tier-select-cards");
  tierRoot?.querySelectorAll(".tier-card").forEach(c => c.classList.remove("selected"));
  tierRoot?.querySelector(".tier-card[data-tier='free']")?.classList.add("selected");
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

    const tier = getUserTier(username);
    const badge = document.createElement("span");
    badge.className = `user-tier-badge tier-badge-${tier}`;
    badge.textContent = tier;
    li.appendChild(badge);
    
    const deleteBtn = document.createElement("button");
    deleteBtn.className = "delete-user-btn";
    deleteBtn.textContent = "Delete";
    deleteBtn.onclick = (e) => {
      e.stopPropagation();
      if (confirm(`Delete user "${username}" and all their data? This cannot be undone.`)) {
        deleteUser(username);
        if (getCurrentUser() === username) {
          localStorage.removeItem(CURRENT_USER_KEY);
          updateUserDisplay();
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
  hideUserModal();
  updateUserDisplay();
  updateAiUsageDisplay();
  // Sync user to backend (upsert) so existing localStorage-only users get persisted
  const tier = getUserTier(username);
  syncUserToBackend(username, tier).then(() => {
    refreshUserTierFromBackend(username).then(() => {
      updateUserDisplay();
      updateAiUsageDisplay();
    });
  });
  loadSpec();
}

// Update UI to show current user and demo tier badge (POC; no payment)
function updateUserDisplay() {
  if (!currentUserDisplay) return;
  const user = getCurrentUser();
  if (user) {
    currentUserDisplay.textContent = user;
    const tier = getUserTier(user);
    if (currentUserTierBadge) {
      currentUserTierBadge.textContent = tier;
      currentUserTierBadge.className = `user-tier-badge tier-badge-${tier}`;
      currentUserTierBadge.classList.remove("hidden");
    }
  } else {
    currentUserDisplay.textContent = "Guest";
    currentUserTierBadge?.classList.add("hidden");
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
    updateUserDisplay();
    updateAiUsageDisplay();
    const u = getCurrentUser();
    if (u) refreshUserTierFromBackend(u).then(() => { updateUserDisplay(); updateAiUsageDisplay(); });
  }
  
  // Event listeners for user management (with null checks)
  switchUserBtn?.addEventListener("click", showUserModal);

  const changePlanOverlay = document.getElementById("change-plan-modal-overlay");
  const changePlanBtn = document.getElementById("change-plan-btn");
  const savePlanBtn = document.getElementById("save-plan-btn");
  const changePlanTierRoot = document.getElementById("change-plan-tier-cards");
  const changePlanTierCards = Array.from(changePlanTierRoot?.querySelectorAll(".tier-card") || []);

  function syncChangePlanSelection(tier) {
    changePlanTierCards.forEach((c) => {
      c.classList.toggle("selected", c.dataset.tier === tier);
    });
  }

  changePlanBtn?.addEventListener("click", () => {
    const u = getCurrentUser();
    if (!u) {
      alert("Select a user first.");
      return;
    }
    syncChangePlanSelection(getUserTier(u));
    changePlanOverlay?.classList.remove("hidden");
  });

  changePlanOverlay?.addEventListener("click", (e) => {
    if (e.target === changePlanOverlay) changePlanOverlay.classList.add("hidden");
  });

  changePlanTierCards.forEach((card) => {
    card.addEventListener("click", () => {
      changePlanTierCards.forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });

  savePlanBtn?.addEventListener("click", () => {
    const u = getCurrentUser();
    if (!u) return;
    const selected = changePlanTierRoot?.querySelector(".tier-card.selected");
    const tier = selected?.dataset.tier || "free";
    if (setUserTier(u, tier)) {
      changePlanOverlay?.classList.add("hidden");
      setStatus?.(`Demo plan set to ${tier}.`);
    }
  });

  document.getElementById("cancel-plan-btn")?.addEventListener("click", () => {
    changePlanOverlay?.classList.add("hidden");
  });
  
  // Tier card selection (signup POC — scoped to modal)
  const tierCardRoot = document.getElementById("tier-select-cards");
  const tierCards = Array.from(tierCardRoot?.querySelectorAll(".tier-card") || []);
  tierCards.forEach((card) => {
    card.addEventListener("click", () => {
      tierCards.forEach((c) => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });
  tierCardRoot?.querySelector(".tier-card[data-tier='free']")?.classList.add("selected");

  createUserBtn?.addEventListener("click", () => {
    const username = newUserInput.value.trim();
    if (!username) {
      alert("Please enter a username.");
      return;
    }
    const selectedCard = tierCardRoot?.querySelector(".tier-card.selected");
    const tier = selectedCard?.dataset.tier || "free";
    if (createUser(username, tier)) {
      newUserInput.value = "";
      tierCards.forEach((c) => c.classList.remove("selected"));
      tierCardRoot?.querySelector(".tier-card[data-tier='free']")?.classList.add("selected");
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
