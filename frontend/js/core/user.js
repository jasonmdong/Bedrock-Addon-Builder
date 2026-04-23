// =====================
// USER MANAGEMENT SYSTEM
// =====================

const APP_USERS_KEY = "app_users";
const CURRENT_USER_KEY = "current_user";
const USER_DATA_PREFIX = "user_";
const USER_DATA_SUFFIX = "_data";

// Persistent UI Elements
const currentUserDisplay = document.getElementById("current-user-display");
const currentUserTierBadge = document.getElementById("current-user-tier-badge");
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

// =====================
// SESSION MANAGEMENT
// =====================

function getSessionToken() {
  return localStorage.getItem("auth_session_token");
}

function setSessionToken(token) {
  if (token) localStorage.setItem("auth_session_token", token);
  else localStorage.removeItem("auth_session_token");
}

function clearSession() {
  localStorage.removeItem("auth_session_token");
  localStorage.removeItem(CURRENT_USER_KEY);
}

// =====================
// AUTH API CALLS
// =====================

async function signUp(username, password, tier = "free") {
  try {
    const res = await fetch("/api/auth/signup", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, subscription_tier: tier }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Sign up failed");
    setSessionToken(data.session_token);
    setCurrentUser(data.username);
    localStorage.setItem(`user_${data.username}_tier`, data.subscription_tier || "free");
    if (!getUserData(data.username).mobs) {
      saveUserData(data.username, { mobs: {}, settings: {} });
    }
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function signIn(username, password) {
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Sign in failed");
    setSessionToken(data.session_token);
    setCurrentUser(data.username);
    localStorage.setItem(`user_${data.username}_tier`, data.subscription_tier || "free");
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

async function signOut() {
  const token = getSessionToken();
  if (token) {
    fetch("/api/auth/logout", {
      method: "POST",
      headers: { "Authorization": `Bearer ${token}` },
    }).catch(() => {});
  }
  clearSession();
  updateUserDisplay();
  updateAiUsageDisplay();
  showAuthModal();
}

async function validateSession() {
  const token = getSessionToken();
  if (!token) return null;
  try {
    const res = await fetch("/api/auth/me", {
      headers: { "Authorization": `Bearer ${token}` },
    });
    if (!res.ok) { clearSession(); return null; }
    const data = await res.json();
    setCurrentUser(data.username);
    localStorage.setItem(`user_${data.username}_tier`, data.subscription_tier || "free");
    return data;
  } catch (e) {
    // Offline — keep local session if we have a username
    return getCurrentUser() ? { username: getCurrentUser() } : null;
  }
}

function continueAsGuest() {
  if (!getCurrentUser()) setCurrentUser("guest");
  hideAuthModal();
  updateUserDisplay();
  updateAiUsageDisplay();
  if (typeof loadSpec === "function") loadSpec();
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

// Show auth modal
function showAuthModal() {
  const overlay = document.getElementById("auth-modal-overlay");
  overlay?.classList.remove("hidden");
}

// Hide auth modal
function hideAuthModal() {
  const overlay = document.getElementById("auth-modal-overlay");
  overlay?.classList.add("hidden");
}

// (Legacy aliases — kept for compatibility)
const showUserModal = showAuthModal;
const hideUserModal = hideAuthModal;

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
  // ── Session validation on load ──
  validateSession().then((user) => {
    if (user) {
      hideAuthModal();
      updateUserDisplay();
      updateAiUsageDisplay();
      if (typeof loadSpec === "function") loadSpec();
    } else {
      showAuthModal();
    }
  });

  // ── Tab switching ──
  const tabLoginBtn = document.getElementById("tab-login-btn");
  const tabSignupBtn = document.getElementById("tab-signup-btn");
  const loginPanel = document.getElementById("auth-login-panel");
  const signupPanel = document.getElementById("auth-signup-panel");

  function showLoginTab() {
    loginPanel.style.display = "";
    signupPanel.style.display = "none";
    tabLoginBtn?.classList.add("active");
    tabSignupBtn?.classList.remove("active");
    document.getElementById("login-error").style.display = "none";
  }
  function showSignupTab() {
    loginPanel.style.display = "none";
    signupPanel.style.display = "";
    tabLoginBtn?.classList.remove("active");
    tabSignupBtn?.classList.add("active");
    document.getElementById("signup-error").style.display = "none";
    const tierRoot = document.getElementById("tier-select-cards");
    tierRoot?.querySelectorAll(".tier-card").forEach(c => c.classList.remove("selected"));
    tierRoot?.querySelector(".tier-card[data-tier='free']")?.classList.add("selected");
  }
  tabLoginBtn?.addEventListener("click", showLoginTab);
  tabSignupBtn?.addEventListener("click", showSignupTab);

  // ── Signup tier cards ──
  const tierCardRoot = document.getElementById("tier-select-cards");
  const tierCards = Array.from(tierCardRoot?.querySelectorAll(".tier-card") || []);
  tierCards.forEach(card => {
    card.addEventListener("click", () => {
      tierCards.forEach(c => c.classList.remove("selected"));
      card.classList.add("selected");
    });
  });
  tierCardRoot?.querySelector(".tier-card[data-tier='free']")?.classList.add("selected");

  // ── Login form ──
  const loginBtn = document.getElementById("login-submit-btn");
  const loginUsernameInput = document.getElementById("auth-login-username");
  const loginPasswordInput = document.getElementById("auth-login-password");
  const loginError = document.getElementById("login-error");

  async function doLogin() {
    const username = loginUsernameInput?.value.trim();
    const password = loginPasswordInput?.value;
    if (!username || !password) {
      loginError.textContent = "Please enter username and password.";
      loginError.style.display = "";
      return;
    }
    if (loginBtn) { loginBtn.disabled = true; loginBtn.textContent = "Signing in..."; }
    const result = await signIn(username, password);
    if (loginBtn) { loginBtn.disabled = false; loginBtn.textContent = "Sign In"; }
    if (result.ok) {
      loginPasswordInput.value = "";
      hideAuthModal();
      updateUserDisplay();
      updateAiUsageDisplay();
      if (typeof loadSpec === "function") loadSpec();
    } else {
      loginError.textContent = result.error;
      loginError.style.display = "";
    }
  }
  loginBtn?.addEventListener("click", doLogin);
  loginPasswordInput?.addEventListener("keypress", e => { if (e.key === "Enter") doLogin(); });
  loginUsernameInput?.addEventListener("keypress", e => { if (e.key === "Enter") doLogin(); });

  // ── Signup form ──
  const signupBtn = document.getElementById("signup-submit-btn");
  const signupUsernameInput = document.getElementById("auth-signup-username");
  const signupPasswordInput = document.getElementById("auth-signup-password");
  const signupConfirmInput = document.getElementById("auth-signup-confirm");
  const signupError = document.getElementById("signup-error");

  async function doSignup() {
    const username = signupUsernameInput?.value.trim();
    const password = signupPasswordInput?.value;
    const confirm = signupConfirmInput?.value;
    if (!username || username.length < 2) {
      signupError.textContent = "Username must be at least 2 characters.";
      signupError.style.display = ""; return;
    }
    if (!password || password.length < 6) {
      signupError.textContent = "Password must be at least 6 characters.";
      signupError.style.display = ""; return;
    }
    if (password !== confirm) {
      signupError.textContent = "Passwords do not match.";
      signupError.style.display = ""; return;
    }
    const selectedCard = tierCardRoot?.querySelector(".tier-card.selected");
    const tier = selectedCard?.dataset.tier || "free";
    if (signupBtn) { signupBtn.disabled = true; signupBtn.textContent = "Creating account..."; }
    const result = await signUp(username, password, tier);
    if (signupBtn) { signupBtn.disabled = false; signupBtn.textContent = "Create Account"; }
    if (result.ok) {
      signupPasswordInput.value = "";
      signupConfirmInput.value = "";
      hideAuthModal();
      updateUserDisplay();
      updateAiUsageDisplay();
      if (typeof loadSpec === "function") loadSpec();
    } else {
      signupError.textContent = result.error;
      signupError.style.display = "";
    }
  }
  signupBtn?.addEventListener("click", doSignup);
  signupConfirmInput?.addEventListener("keypress", e => { if (e.key === "Enter") doSignup(); });

  // ── Guest buttons ──
  document.getElementById("login-guest-btn")?.addEventListener("click", continueAsGuest);
  document.getElementById("signup-guest-btn")?.addEventListener("click", continueAsGuest);

  // ── Sign Out ──
  document.getElementById("sign-out-btn")?.addEventListener("click", signOut);

  // ── Change demo plan modal ──
  const changePlanOverlay = document.getElementById("change-plan-modal-overlay");
  const changePlanBtn = document.getElementById("change-plan-btn");
  const savePlanBtn = document.getElementById("save-plan-btn");
  const changePlanTierRoot = document.getElementById("change-plan-tier-cards");
  const changePlanTierCards = Array.from(changePlanTierRoot?.querySelectorAll(".tier-card") || []);

  function syncChangePlanSelection(tier) {
    changePlanTierCards.forEach(c => c.classList.toggle("selected", c.dataset.tier === tier));
  }

  changePlanBtn?.addEventListener("click", () => {
    const u = getCurrentUser();
    if (!u) { showAuthModal(); return; }
    syncChangePlanSelection(getUserTier(u));
    changePlanOverlay?.classList.remove("hidden");
  });
  changePlanOverlay?.addEventListener("click", e => {
    if (e.target === changePlanOverlay) changePlanOverlay.classList.add("hidden");
  });
  changePlanTierCards.forEach(card => {
    card.addEventListener("click", () => {
      changePlanTierCards.forEach(c => c.classList.remove("selected"));
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

  // ── Backup / Restore ──
  backupBtn?.addEventListener("click", backupUserData);
  restoreBtn?.addEventListener("click", () => restoreFileInput?.click());
  restoreFileInput?.addEventListener("change", e => {
    const file = e.target.files[0];
    if (file) { restoreUserData(file); restoreFileInput.value = ""; }
  });
}
