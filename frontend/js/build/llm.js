// =====================
// LLM INTEGRATION
// =====================

const llmPrompt = document.getElementById("llm-prompt");
const llmButton = document.getElementById("llm-run");
const llmMockHistoryButton = document.getElementById("llm-run-mock");
const llmProvider = document.getElementById("llm-provider");
const llmCategory = document.getElementById("llm-category");
const llmKey = document.getElementById("llm-key");
const llmUsePlan = document.getElementById("llm-use-plan");
const llmHistoryList = document.getElementById("llm-history-list");
const llmSessionCount = document.getElementById("llm-session-count");
const clearLlmHistoryBtn = document.getElementById("clear-llm-history");

const LLM_CATEGORY_KEY = "builder_llm_category";
const LLM_USE_PLAN_KEY = "builder_llm_use_plan";

// Restore Smart Plan toggle state
if (llmUsePlan) {
  llmUsePlan.checked = localStorage.getItem(LLM_USE_PLAN_KEY) === "true";
  llmUsePlan.addEventListener("change", () => {
    localStorage.setItem(LLM_USE_PLAN_KEY, llmUsePlan.checked);
  });
}

function detectCategoryFromSpec(spec) {
  if (!spec || typeof spec !== "object") return "entity_logic_ai";
  if ("minecraft:item" in spec) return "items_weaponry";
  if ("minecraft:block" in spec) return "blocks_furniture";
  if ("pools" in spec || Object.keys(spec).some(k => k.startsWith("minecraft:recipe")))
    return "loot_recipes";
  if ("header" in spec && "modules" in spec) return "scripting_components";
  return "entity_logic_ai";
}

// LLM history stack -> newest first
function llmStackKey(user, mob) {
  if (!user) return null;
  const m = mob || 'global';
  return `llm_stack_${user}_${m}`;
}
const LLM_STACK_MAX = 50;

/** Fire-and-forget: persist an LLM version to the DB (mob_versions table). */
async function _pushVersionToDb(mobName, prompt, spec, llm_provider, llm_model) {
  const token = typeof getSessionToken === 'function' ? getSessionToken() : null;
  if (!token) return;
  try {
    await fetch(`/api/user/mobs/${encodeURIComponent(mobName || 'global')}/versions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
      body: JSON.stringify({ prompt, spec, llm_provider: llm_provider || null, llm_model: llm_model || null }),
    });
  } catch (e) {
    console.warn('[DB] pushVersionToDb failed:', e);
  }
}

function readLlmStack(user, mob) {
  const key = llmStackKey(user, mob);
  if (!key) return [];
  const raw = localStorage.getItem(key);
  return raw ? JSON.parse(raw) : [];
}

function pushLlmStack(user, mob, entry) {
  const key = llmStackKey(user, mob);
  if (!key) return;
  const arr = readLlmStack(user, mob);
  arr.unshift(entry);
  arr.splice(LLM_STACK_MAX);
  localStorage.setItem(key, JSON.stringify(arr));
}

function popToLlmIndex(user, mob, index) {
  const key = llmStackKey(user, mob);
  if (!key) return [];
  const arr = readLlmStack(user, mob);
  if (index < 0 || index >= arr.length) return arr;
  const newArr = arr.slice(index);
  localStorage.setItem(key, JSON.stringify(newArr));
  return newArr;
}

function computeMiniDiff(beforeSpec, afterSpec) {
  function sortKeys(obj) {
    if (obj === null || typeof obj !== 'object') return obj;
    if (Array.isArray(obj)) return obj.map(sortKeys);
    const out = {};
    Object.keys(obj).sort().forEach(k => { out[k] = sortKeys(obj[k]); });
    return out;
  }
  const DiffLib = (typeof Diff !== 'undefined') ? Diff : ((typeof diff !== 'undefined') ? diff : null);
  const diffLines = DiffLib && DiffLib.diffLines ? DiffLib.diffLines : null;
  const beforeStr = beforeSpec ? JSON.stringify(sortKeys(beforeSpec), null, 2) : '';
  const afterStr = afterSpec ? JSON.stringify(sortKeys(afterSpec), null, 2) : '';
  let raw = null;
  if (diffLines) {
    try { raw = diffLines(beforeStr, afterStr); } catch (e) { raw = null; }
  }
  if (!raw) {
    const b = afterStr.split('\n');
    raw = b.map(l => ({ value: l + '\n' }));
  }

  const out = [];
  for (const chunk of raw) {
    const lines = (chunk.value || '').split('\n');
    if (lines.length && lines[lines.length-1] === '') lines.pop();
    for (const l of lines) {
      out.push({ text: l, added: !!chunk.added, removed: !!chunk.removed });
    }
  }
  return out;
}

function escapeHtmlMini(text) {
  const d = document.createElement('div');
  d.textContent = String(text);
  return d.innerHTML;
}

function renderMiniDiffEl(beforeSpec, afterSpec) {
  const container = document.createElement('div');
  container.className = 'diff-mini';

  const gutter = document.createElement('pre');
  gutter.className = 'gutter';

  const content = document.createElement('pre');
  content.className = 'diff-content';

  try {
    function sortKeys(obj) {
      if (obj === null || typeof obj !== 'object') return obj;
      if (Array.isArray(obj)) return obj.map(sortKeys);
      const out = {};
      Object.keys(obj).sort().forEach(k => { out[k] = sortKeys(obj[k]); });
      return out;
    }
    const DiffLib = (typeof Diff !== 'undefined') ? Diff : ((typeof diff !== 'undefined') ? diff : null);
    const diffLines = DiffLib && DiffLib.diffLines ? DiffLib.diffLines : null;
    const beforeStr = beforeSpec ? JSON.stringify(sortKeys(beforeSpec), null, 2) : '';
    const afterStr = afterSpec ? JSON.stringify(sortKeys(afterSpec), null, 2) : '';
    let raw = null;
    if (diffLines) {
      try { raw = diffLines(beforeStr, afterStr); } catch (e) { raw = null; }
    }
    // lcs-dp fallback for diff testing since diff library !working properly
    if (!raw) {
      function lcsMatrix(a, b) {
        const n = a.length, m = b.length;
        const dp = Array(n+1).fill(null).map(() => Array(m+1).fill(0));
        for (let i = n-1; i >= 0; --i) {
          for (let j = m-1; j >= 0; --j) {
            if (a[i] === b[j]) dp[i][j] = dp[i+1][j+1] + 1;
            else dp[i][j] = Math.max(dp[i+1][j], dp[i][j+1]);
          }
        }
        return dp;
      }
      function buildChunks(a, b) {
        const dp = lcsMatrix(a, b);
        const chunks = [];
        let i = 0, j = 0;
        while (i < a.length || j < b.length) {
          if (i < a.length && j < b.length && a[i] === b[j]) {
            let val = a[i] + '\n';
            i++; j++;
            while (i < a.length && j < b.length && a[i] === b[j]) { val += a[i] + '\n'; i++; j++; }
            chunks.push({ value: val });
          } else if (j < b.length && (i === a.length || dp[i][j+1] >= dp[i+1][j])) {
            let val = b[j] + '\n';
            j++;
            while (j < b.length && (i === a.length || dp[i][j+1] >= dp[i+1][j])) { val += b[j] + '\n'; j++; }
            chunks.push({ value: val, added: true });
          } else if (i < a.length) {
            let val = a[i] + '\n';
            i++;
            while (i < a.length && (j === b.length || dp[i][j+1] < dp[i+1][j])) { val += a[i] + '\n'; i++; }
            chunks.push({ value: val, removed: true });
          }
        }
        return chunks;
      }
      const a = beforeStr ? beforeStr.split('\n') : [];
      const b = afterStr ? afterStr.split('\n') : [];
      raw = buildChunks(a, b);
    }
    gutter.style.whiteSpace = 'pre';
    gutter.style.textAlign = 'right';

    let oldLine = 1, newLine = 1;
    const contentParts = [];
    const gutterParts = [];
    let addedCount = 0, removedCount = 0;
    raw.forEach(chunk => {
      const lines = (chunk.value || '').split('\n');
      if (lines.length && lines[lines.length-1] === '') lines.pop();
      lines.forEach(l => {
        if (chunk.added) {
          addedCount++;
          contentParts.push(`<div class="diff-line added">+ ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line added">→ ${newLine}</div>`);
          newLine++;
        } else if (chunk.removed) {
          removedCount++;
          contentParts.push(`<div class="diff-line removed">- ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line removed">${oldLine} →</div>`);
          oldLine++;
        } else {
          contentParts.push(`<div class="diff-line context">  ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line context">${oldLine} | ${newLine}</div>`);
          oldLine++; newLine++;
        }
      });
    });
    gutter.innerHTML = gutterParts.join('');
    content.innerHTML = contentParts.join('');
    if (addedCount && removedCount) {
      try {
        console.groupCollapsed('[mini-diff] added+removed detected');
        console.log('beforeStr:', beforeStr);
        console.log('afterStr:', afterStr);
        console.log('raw:', raw);
        console.groupEnd();
      } catch (e) { console.warn('mini-diff debug log failed', e); }
    }
  } catch (e) {
    gutter.textContent = '';
    content.textContent = '(diff error)';
  }
  container.appendChild(gutter);
  container.appendChild(content);
  return container;
}

async function requestLlm() {
  if (!llmPrompt) return;
  const instruction = llmPrompt.value.trim();
  if (!instruction) {
    setStatus("Enter instructions for the LLM assistant.", true);
    return;
  }
  const provider = llmProvider ? llmProvider.value : "openai";
  const category = llmCategory ? llmCategory.value : "entity_logic_ai";
  const apiKey = llmKey ? llmKey.value.trim() : "";

  // Animated progress steps while waiting for the backend
  const _steps = _buildProgressSteps(provider, category);
  let _stepIdx = 0;
  setStatus(_steps[0]);
  const _progressTimer = setInterval(() => {
    _stepIdx++;
    if (_stepIdx < _steps.length) {
      setStatus(_steps[_stepIdx]);
    }
  }, 3000);
  
  let currentSpec;
  try {
    currentSpec = JSON.parse(editor.value);
  } catch (err) {
    setStatus("Invalid JSON in editor. Fix it before using the LLM.", true);
    return;
  }

  // Warn if the spec structure doesn't match the selected category
  const detected = detectCategoryFromSpec(currentSpec);
  if (detected !== category) {
    const labelMap = {
      entity_logic_ai: "Entity / Mob",
      items_weaponry: "Items & Weaponry",
      blocks_furniture: "Blocks & Furniture",
      loot_recipes: "Loot Tables & Recipes",
      scripting_components: "Scripting & Manifests",
    };
    const detectedLabel = labelMap[detected] || detected;
    const selectedLabel = labelMap[category] || category;
    console.warn(`[LLM] Category mismatch: dropdown=${category}, detected=${detected}`);
    setStatus(`Note: Spec looks like "${detectedLabel}" but you selected "${selectedLabel}". Treating as a conversion request.`);
    await new Promise(r => setTimeout(r, 2000));
  }
  
  const beforeSpec = JSON.parse(JSON.stringify(currentSpec));
  
  const requestBody = { 
    prompt: instruction, 
    provider: provider,
    category: category,
    current_spec: currentSpec 
  };
  if (apiKey) {
    requestBody.api_key = apiKey;
  }
  if (llmUsePlan && llmUsePlan.checked) {
    requestBody.use_plan = true;
  }
  // mock uses dedicated mock route for dev
  let endpoint = "/api/spec/llm";
  if (provider === "mock") endpoint = "/api/spec/llm_mock";

  let res;
  try {
    res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody)
    });
  } catch (err) {
    clearInterval(_progressTimer);
    console.error("LLM fetch failed", err);
    setStatus("LLM request failed (network): " + err.message, true);
    return;
  }
  clearInterval(_progressTimer);
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = payload.detail || payload.error || res.statusText;
    setStatus("LLM request failed: " + detail, true);
    return;
  }
  console.log("LLM response", payload);
  
  // Show the diff before applying changes
  showDiff(beforeSpec, payload.spec);
  
  editor.value = JSON.stringify(payload.spec, null, 2);
  
  // Save to localStorage
  if (currentMobName) {
    // If short_name changed, rename the mob in localStorage (same logic as saveSpec)
    const newShortName = payload.spec.short_name || currentMobName;
    if (newShortName !== currentMobName) {
      const oldTexture = typeof getUserMobTexture === "function" ? getUserMobTexture(currentMobName) : null;
      if (typeof deleteUserMob === "function") deleteUserMob(currentMobName);
      currentMobName = newShortName;
      localStorage.setItem("builder_current_mob", currentMobName);
      // Migrate texture to new name
      if (oldTexture && typeof saveUserMobTexture === "function") {
        saveUserMobTexture(currentMobName, oldTexture);
      }
      console.log(`[LLM] Mob renamed: → ${currentMobName}`);
      if (typeof loadMobList === "function") loadMobList();
    }
    saveUserMob(currentMobName, payload.spec);

    // Detect if the mob type changed (by display_name or identifier)
    const oldDisplay = (beforeSpec.display_name || "").toLowerCase();
    const newDisplay = (payload.spec.display_name || "").toLowerCase();
    const oldIdent = (beforeSpec.identifier || "").toLowerCase();
    const newIdent = (payload.spec.identifier || "").toLowerCase();
    const mobTypeChanged = (oldDisplay && newDisplay && oldDisplay !== newDisplay)
                        || (oldIdent && newIdent && oldIdent !== newIdent);

    if (payload.texture_b64 && typeof saveUserMobTexture === "function") {
      saveUserMobTexture(currentMobName, payload.texture_b64);
      console.log("[LLM] MCP texture received, saved to localStorage");
    } else if (mobTypeChanged) {
      if (typeof deleteUserMobTexture === "function") {
        deleteUserMobTexture(currentMobName);
      }
      delete payload.spec._template_base;
      editor.value = JSON.stringify(payload.spec, null, 2);
      console.log(`[LLM] Mob identity changed (${oldDisplay} → ${newDisplay}), cleared old texture + template`);
    }

    loadTextureIntoPainter(currentMobName);
    updateFileTree(payload.spec);

    // Always re-render 3D model after LLM response to pick up new
    // textures, scale changes, and geometry updates.
    const hasNewGeometryJson = payload.spec.geometry_json
                            && payload.spec.geometry_json["minecraft:geometry"];
    const oldGeo = beforeSpec.geometry || "";
    const newGeo = payload.spec.geometry || "";
    const textureChanged = !!payload.texture_b64;
    const scaleChanged = (beforeSpec.scale || 1) !== (payload.spec.scale || 1);

    if (hasNewGeometryJson) {
      if (typeof render3DGeometry === "function") {
        render3DGeometry(payload.spec.geometry_json, currentMobName);
      }
    } else if (newGeo && newGeo !== oldGeo) {
      const geoName = newGeo.replace("geometry.", "");
      if (typeof fetchAndDisplayGeometry === "function") {
        fetchAndDisplayGeometry(geoName, currentMobName);
      }
    } else if (textureChanged || scaleChanged) {
      // Texture or scale changed but geometry didn't — re-render with current geometry
      const currentGeoJson = payload.spec.geometry_json || beforeSpec.geometry_json;
      if (currentGeoJson && currentGeoJson["minecraft:geometry"] && typeof render3DGeometry === "function") {
        render3DGeometry(currentGeoJson, currentMobName);
      }
    }
  }

  // Refresh animation buttons if animation_json changed
  if (typeof loadAnimationsFromSpec === "function") {
    loadAnimationsFromSpec(payload.spec.animation_json || null);
  }
  
  // Build status message with MCP + orchestrator info
  let statusMsg = `${provider} updated the spec at ${new Date().toLocaleTimeString()}.`;
  const mcpInfo = _formatMcpStatus(payload.mcp);
  if (mcpInfo) statusMsg += " " + mcpInfo;
  const orchInfo = _formatOrchestratorStatus(payload.orchestrator);
  if (orchInfo) statusMsg += " " + orchInfo;
  const pipelineInfo = _formatPipelineStatus(payload.pipeline);
  if (pipelineInfo) statusMsg += " " + pipelineInfo;
  setStatus(statusMsg);

  // Show MCP detail badge if available
  _renderMcpBadge(payload.mcp, payload.pipeline);

  try {
    const user = getCurrentUser();
    const mob = currentMobName || null;
    if (user) {
      const entry = { ts: new Date().toISOString(), prompt: instruction, spec: payload.spec };
      pushLlmStack(user, mob, entry);
      _pushVersionToDb(mob, instruction, payload.spec, provider, payload.model || null).catch(() => {});
      renderLlmHistory();
    }
  } catch (e) {
    console.warn('Failed to write llm history', e);
  }
}

/** Push one LLM history entry without calling the API—same quota + AI count as Ask LLM, for testing history and daily limits. */
function mockPushLlmHistoryEntry() {
  if (typeof canRunAiAction === "function") {
    const quota = canRunAiAction();
    if (!quota.ok && quota.reason === "daily_cap") {
      setStatus(
        `Daily AI limit reached (${quota.used}/${quota.cap} on this demo plan). Use "Change demo plan" for Pro (unlimited in POC) or try again tomorrow.`,
        true
      );
      return;
    }
    if (!quota.ok && quota.reason === "no_user") {
      setStatus("Select or create a user first.", true);
      return;
    }
  }
  const user = typeof getCurrentUser === "function" ? getCurrentUser() : null;
  if (!user) {
    setStatus("Select or create a user first.", true);
    return;
  }
  let currentSpec;
  try {
    currentSpec = JSON.parse(editor.value);
  } catch (err) {
    setStatus("Invalid JSON in editor. Fix it before adding a mock history entry.", true);
    return;
  }
  const instruction =
    llmPrompt && llmPrompt.value.trim()
      ? llmPrompt.value.trim()
      : `Mock entry ${new Date().toLocaleTimeString()}`;
  const mob = currentMobName || null;
  const entry = {
    ts: new Date().toISOString(),
    prompt: instruction,
    spec: JSON.parse(JSON.stringify(currentSpec)),
  };
  pushLlmStack(user, mob, entry);
  _pushVersionToDb(mob, instruction, JSON.parse(JSON.stringify(currentSpec)), 'mock', null).catch(() => {});
  renderLlmHistory();
  if (typeof recordAiAction === "function") recordAiAction(user);
  const n = readLlmStack(user, mob).length;
  const histCap = _llmHistoryMax();
  let aiPart = "";
  if (typeof getAiUsageCountToday === "function" && typeof canRunAiAction === "function") {
    const used = getAiUsageCountToday(user);
    const q = canRunAiAction();
    const cap = q.cap;
    if (cap === -1) aiPart = ` AI prompts today: ${used} (unlimited).`;
    else aiPart = ` AI prompts today: ${used}/${cap}.`;
  }
  setStatus(
    `Mock entry added (${n}/${histCap} history kept).${aiPart} No API call.`
  );
}


// ---------------------------------------------------------------------------
// Progress steps during LLM request
// ---------------------------------------------------------------------------

function _buildProgressSteps(provider, category) {
  const steps = [];
  const usePlan = llmUsePlan && llmUsePlan.checked;
  if (typeof mctoolsAvailable !== "undefined" && mctoolsAvailable) {
    steps.push(`Retrieving MCP context for [${category}]...`);
  }
  if (usePlan) {
    steps.push(`Planning changes with ${provider}...`);
    steps.push(`Applying plan...`);
  } else {
    steps.push(`Sending to ${provider} [${category}]...`);
  }
  steps.push(`Waiting for ${provider} response...`);
  steps.push(`Still waiting for ${provider}...`);
  return steps;
}


// ---------------------------------------------------------------------------
// MCP augmentation status helpers
// ---------------------------------------------------------------------------

function _formatMcpStatus(mcp) {
  if (!mcp || !mcp.augmented) return "";
  const parts = [];
  const sources = (mcp.context_sources || []).join(", ");
  if (sources) parts.push(`MCP context: ${sources}`);
  if (mcp.retrieval_ms) parts.push(`${mcp.retrieval_ms}ms`);
  if (mcp.validation && mcp.validation.ran) {
    parts.push(mcp.validation.valid ? "validated" : "validation warnings");
  }
  return parts.length ? `[${parts.join(" | ")}]` : "";
}


function _formatOrchestratorStatus(orch) {
  if (!orch) return "";
  const parts = [];
  if (orch.applied_directly) {
    parts.push("Plan applied directly (no Phase 2)");
  } else if (orch.fell_back_to_llm) {
    parts.push("Plan-guided rewrite");
  }
  const reasoning = orch.plan && orch.plan.reasoning;
  if (reasoning) {
    const short = reasoning.length > 60
      ? reasoning.slice(0, 57) + "..."
      : reasoning;
    parts.push(short);
  }
  return parts.length ? `[Smart Plan: ${parts.join(" | ")}]` : "";
}

function _formatPipelineStatus(pipeline) {
  if (!pipeline) return "";
  const parts = [];
  const intents = pipeline.intent_profile?.signals || pipeline.stages?.find(s => s.name === "intent_extraction")?.artifacts?.intent_profile?.signals || [];
  if (intents.length) {
    parts.push(`Intent: ${intents.slice(0, 3).map(i => i.name).join(", ")}`);
  }
  const repair = pipeline.repair;
  if (repair?.attempted) {
    parts.push(repair.succeeded ? "repair pass fixed validation issues" : "repair pass attempted");
  }
  return parts.length ? `[${parts.join(" | ")}]` : "";
}


function _renderMcpBadge(mcp, pipeline) {
  let badge = document.getElementById("llm-mcp-badge");
  if (!badge) {
    const statusArea = document.getElementById("status");
    if (!statusArea) return;
    badge = document.createElement("div");
    badge.id = "llm-mcp-badge";
    badge.style.cssText =
      "font-size:0.75rem;color:var(--muted);margin-top:4px;font-style:italic;";
    statusArea.parentNode.insertBefore(badge, statusArea.nextSibling);
  }

  if ((!mcp || !mcp.augmented) && !pipeline) {
    badge.textContent = "";
    badge.style.display = "none";
    return;
  }

  badge.style.display = "block";
  const parts = [];

  if (mcp.context_sources && mcp.context_sources.length) {
    parts.push("Context from: " + mcp.context_sources.join(", "));
  }
  if (mcp.retrieval_ms) {
    parts.push(`retrieved in ${mcp.retrieval_ms}ms`);
  }
  if (mcp.validation && mcp.validation.ran) {
    if (mcp.validation.valid) {
      parts.push("MCP validation passed");
    } else {
      const msgs = (mcp.validation.messages || []).slice(0, 3).join("; ");
      parts.push("MCP validation: " + (msgs || "issues found"));
    }
  }

  const intentSignals = pipeline?.stages?.find(s => s.name === "intent_extraction")?.artifacts?.intent_profile?.signals || [];
  if (intentSignals.length) {
    parts.push("Structured intent: " + intentSignals.slice(0, 4).map(s => s.name).join(", "));
  }
  if (pipeline?.repair?.attempted) {
    parts.push(pipeline.repair.succeeded ? "Repair pass: fixed" : "Repair pass: attempted");
  }

  badge.textContent = parts.join(" | ");
}

function renderLlmHistory() {
  const user = getCurrentUser();
  const mob = currentMobName || null;
  if (!user || !llmHistoryList) {
    try { renderGlobalDiff(); } catch (e) {}
    return;
  }
  try { 
    renderGlobalDiff();
  } catch (e) {}
  const hist = readLlmStack(user, mob);
  if (!hist.length) {
    llmHistoryList.innerHTML = '<div style="color: var(--muted); font-style:italic; text-align:center;">No history yet</div>';
    if (llmSessionCount) llmSessionCount.textContent = '0';
    return;
  }
  llmHistoryList.innerHTML = '';
  hist.forEach((h, idx) => {
    const container = document.createElement('div');
    // two-column layout: card | mini-diff
    container.className = 'llm-history-row';
    const card = document.createElement('div');
    card.className = 'llm-history-card';

    const time = new Date(h.ts).toLocaleTimeString();
    const title = document.createElement('div');
    title.style.fontWeight = '600';
    title.style.fontSize = '0.85rem';
    title.textContent = `${time}`;
    const p = document.createElement('div');
    p.style.fontSize = '0.8rem';
    p.style.color = 'var(--muted)';
    p.textContent = h.prompt.length > 120 ? h.prompt.slice(0,120)+'...' : h.prompt;
    const btnRow = document.createElement('div');
    btnRow.className = 'llm-history-actions';
    const reuse = document.createElement('button');
    reuse.className = 'secondary';
    reuse.textContent = 'Reuse';
    reuse.onclick = () => { llmPrompt.value = h.prompt; };
    const reapply = document.createElement('button');
    reapply.className = 'primary';
    reapply.textContent = 'Apply';
    reapply.onclick = async () => { llmPrompt.value = h.prompt; await requestLlm(); };
    btnRow.appendChild(reuse); btnRow.appendChild(reapply);

    // restore button
    if (typeof idx !== 'undefined' && idx > 0) {
      const restore = document.createElement('button');
      restore.className = 'ghost';
      restore.textContent = 'restore';
      restore.className = 'llm-restore-btn';
      restore.onclick = () => { restoreHistoryEntry(idx, restore); };
      card.appendChild(restore);
    }

    card.appendChild(title); card.appendChild(p); card.appendChild(btnRow);
    let prevSpec = undefined;
    try {
      if (idx < hist.length - 1) {
          prevSpec = hist[idx + 1].spec;
        } else {
          const user = getCurrentUser();
          prevSpec = (typeof getOriginalSpec === 'function' && user && currentMobName) ? (getOriginalSpec(user, currentMobName) || {}) : (getUserMob(currentMobName) || {});
        }
    } catch (e) {
      prevSpec = {};
    }
    container.appendChild(card);
    // try create mini diff element and add
    try {
      const mini = renderMiniDiffEl(prevSpec || {}, h.spec || {});
      mini.classList.add('llm-mini-diff');
      container.appendChild(mini);
      setTimeout(() => {
        try {
          const contentEl = mini.querySelector('pre:nth-child(2)');
          const gutterEl = mini.querySelector('pre:nth-child(1)');
          const firstChange = mini.querySelector('.diff-line.added, .diff-line.removed');
          if (firstChange && typeof firstChange.scrollIntoView === 'function') {
            firstChange.scrollIntoView({ block: 'nearest' });
            if (contentEl && gutterEl) gutterEl.scrollTop = contentEl.scrollTop;
          }
        } catch (e) {}
      }, 0);
      // sync scrolling b/w content and gutter
      setTimeout(() => {
        try {
          const contentEl = mini.querySelector('.diff-content');
          const gutterEl = mini.querySelector('.gutter');
          if (contentEl && gutterEl) {
            contentEl.addEventListener('scroll', () => { gutterEl.scrollTop =contentEl.scrollTop; });
          }
        } catch (e) {}
      }, 50);
    } catch (e) {
      const fallback = document.createElement('div');
      fallback.textContent = '(diff)';
      fallback.style.padding = '6px';
      container.appendChild(fallback);
    }

    llmHistoryList.appendChild(container);
  });
  if (llmSessionCount) llmSessionCount.textContent = String(hist.length);
}

function restoreHistoryEntry(index, btnEl) {
    const user = getCurrentUser();
    if (!user) return;
  const hist = readLlmStack(user, currentMobName || null);
    if (!hist || index < 0 || index >= hist.length) return;
    const entry = hist[index];
    if (!entry || !entry.spec) return;

    if (!confirm(`restore workspace to checkpoint from ${new Date(entry.ts).toLocaleString()}?`)) return;

    let prior = undefined;
    if (hist && index < hist.length - 1) prior = hist[index + 1].spec;
    else {
      try { prior = getUserMob(currentMobName); } catch (e) { prior = {}; }
    }
    const doRestore = () => {
      try {
        editor.value = JSON.stringify(entry.spec, null, 2);
        if (currentMobName) {
          saveUserMob(currentMobName, entry.spec);
          loadTextureIntoPainter(currentMobName);
          updateFileTree(entry.spec);
        }
        setStatus(`restored spec from ${new Date(entry.ts).toLocaleString()}`);
        popToLlmIndex(user, currentMobName || null, index);
        renderLlmHistory();
        try { showDiff(prior || {}, entry.spec || {}); if (typeof setSpecView === 'function') setSpecView('diff'); } catch (er) {}
      } catch (e) {
        console.warn('failed to restore history entry', e);
        setStatus('restore failed', true);
      }
    };

    if (btnEl) {
      btnEl.disabled = true;
      const prevText = btnEl.textContent;
      btnEl.textContent = '...';
      setTimeout(() => {
        doRestore();
        btnEl.textContent = prevText;
        btnEl.disabled = false;
      }, 500);
    } else {
      doRestore();
    }
}

function initLlmHandlers() {
  clearLlmHistoryBtn?.addEventListener('click', () => {
    const user = getCurrentUser();
    const mob = currentMobName || null;
    if (!user) return;
    if (!confirm('Clear LLM history for User: ' + user + (mob ? (' | Mob: ' + mob) : '') + '?')) return;
    const key = llmStackKey(user, mob);
    if (key) localStorage.removeItem(key);
    renderLlmHistory();
  });

  llmButton?.addEventListener("click", async (e) => {
    e.preventDefault();
    await requestLlm();
  });

  llmMockHistoryButton?.addEventListener("click", (e) => {
    e.preventDefault();
    mockPushLlmHistoryEntry();
  });

  llmProvider?.addEventListener("change", () => {
    localStorage.setItem(LLM_PROVIDER_KEY, llmProvider.value);
  });

  llmCategory?.addEventListener("change", () => {
    localStorage.setItem(LLM_CATEGORY_KEY, llmCategory.value);
  });

  llmKey?.addEventListener("input", () => {
    localStorage.setItem(LLM_API_KEY_STORAGE, llmKey.value.trim());
  });

  // Restore saved category
  const savedCategory = localStorage.getItem(LLM_CATEGORY_KEY);
  if (savedCategory && llmCategory) {
    llmCategory.value = savedCategory;
  }
}
