// =====================
// LLM INTEGRATION
// =====================

const llmPrompt = document.getElementById("llm-prompt");
const llmButton = document.getElementById("llm-run");
const llmProvider = document.getElementById("llm-provider");
const llmKey = document.getElementById("llm-key");
const llmHistoryList = document.getElementById("llm-history-list");
const llmSessionCount = document.getElementById("llm-session-count");
const clearLlmHistoryBtn = document.getElementById("clear-llm-history");

// LLM history stack -> newest first
function llmStackKey(user) { return `llm_stack_${user}`; }
const LLM_STACK_MAX = 50;

function readLlmStack(user) {
  const raw = localStorage.getItem(llmStackKey(user));
  return raw ? JSON.parse(raw) : [];
}

function pushLlmStack(user, entry) {
  const key = llmStackKey(user);
  const arr = readLlmStack(user);
  arr.unshift(entry);
  arr.splice(LLM_STACK_MAX);
  localStorage.setItem(key, JSON.stringify(arr));
}

function popToLlmIndex(user, index) {
  const key = llmStackKey(user);
  const arr = readLlmStack(user);
  if (index < 0 || index >= arr.length) return arr;
  const newArr = arr.slice(index);
  localStorage.setItem(key, JSON.stringify(newArr));
  return newArr;
}

async function requestLlm() {
  if (!llmPrompt) return;
  const instruction = llmPrompt.value.trim();
  if (!instruction) {
    setStatus("Enter instructions for the LLM assistant.", true);
    return;
  }
  const provider = llmProvider ? llmProvider.value : "openai";
  setStatus(`Contacting ${provider}...`);
  const apiKey = llmKey ? llmKey.value.trim() : "";
  
  // Get current spec from editor (this is the BEFORE state)
  let currentSpec;
  try {
    currentSpec = JSON.parse(editor.value);
  } catch (err) {
    setStatus("Invalid JSON in editor. Fix it before using the LLM.", true);
    return;
  }
  
  // Store the before state for diff comparison
  const beforeSpec = JSON.parse(JSON.stringify(currentSpec));
  
  const requestBody = { 
    prompt: instruction, 
    provider: provider,
    current_spec: currentSpec 
  };
  if (apiKey) {
    requestBody.api_key = apiKey;
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
    console.error("LLM fetch failed", err);
    setStatus("LLM request failed (network): " + err.message, true);
    return;
  }
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
    saveUserMob(currentMobName, payload.spec);
    // Sync texture painter with potentially new color
    loadTextureIntoPainter(currentMobName);
    // Update file tree
    updateFileTree(payload.spec);
  }
  
  setStatus(`${provider} updated the spec at ${new Date().toLocaleTimeString()}.`);

  try {
    const user = getCurrentUser();
    if (user) {
      const entry = { ts: new Date().toISOString(), prompt: instruction, spec: payload.spec };
      pushLlmStack(user, entry);
      renderLlmHistory();
    }
  } catch (e) {
    console.warn('Failed to write llm history', e);
  }
}

function renderLlmHistory() {
  const user = getCurrentUser();
  if (!user || !llmHistoryList) {
  }
    try { renderGlobalDiff(); } catch (e) {}
  const hist = readLlmStack(user);
  if (!hist.length) {
    llmHistoryList.innerHTML = '<div style="color: var(--muted); font-style:italic; text-align:center;">No history yet</div>';
    if (llmSessionCount) llmSessionCount.textContent = '0';
    return;
  }
  llmHistoryList.innerHTML = '';
  hist.forEach((h, idx) => {
    const container = document.createElement('div');
    container.style.display = 'flex';
    container.style.gap = '0.5rem';
    container.style.alignItems = 'stretch';
    const card = document.createElement('div');
    card.style.display = 'flex';
    card.style.flexDirection = 'column';
    card.style.border = '1px solid var(--border)';
    card.style.padding = '0.6rem 0.8rem';
    card.style.borderRadius = '8px';
    card.style.position = 'relative';
    card.style.flex = '1 1 auto';

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
    btnRow.style.display = 'flex';
    btnRow.style.gap = '0.4rem';
    btnRow.style.marginTop = '0.4rem';
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
      restore.style.position = 'absolute';
      restore.style.right = '8px';
      restore.style.top = '8px';
      restore.style.fontSize = '0.72rem';
      restore.style.padding = '0.2rem 0.45rem';
      restore.style.borderRadius = '999px';
      restore.style.opacity = '0.95';
      restore.style.minWidth = '44px';
      restore.style.textTransform = 'lowercase';
      restore.onclick = () => { restoreHistoryEntry(idx, restore); };
      card.appendChild(restore);
    }

    card.appendChild(title); card.appendChild(p); card.appendChild(btnRow);
    let prevSpec = undefined;
    try {
      if (idx < hist.length - 1) prevSpec = hist[idx + 1].spec;
      else if (typeof currentMobName !== 'undefined' && currentMobName) prevSpec = getUserMob(currentMobName);
      else prevSpec = {};
    } catch (e) {
      prevSpec = {};
    }
    card.addEventListener('click', (e) => {
      e.stopPropagation();
      try { showDiff(prevSpec || {}, h.spec || {}); } catch (er) {}
      try { if (typeof setSpecView === 'function') setSpecView('diff'); } catch (er) {}
    });

    container.appendChild(card);
    llmHistoryList.appendChild(container);
  });
  if (llmSessionCount) llmSessionCount.textContent = String(hist.length);
}

function restoreHistoryEntry(index, btnEl) {
    const user = getCurrentUser();
    if (!user) return;
    const hist = readLlmStack(user);
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
        popToLlmIndex(user, index);
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
    if (!user) return;
    if (!confirm('Clear LLM history for user ' + user + '?')) return;
    localStorage.removeItem(`llm_stack_${user}`);
    renderLlmHistory();
  });

  llmButton?.addEventListener("click", async (e) => {
    e.preventDefault();
    await requestLlm();
  });

  llmProvider?.addEventListener("change", () => {
    localStorage.setItem(LLM_PROVIDER_KEY, llmProvider.value);
  });

  llmKey?.addEventListener("input", () => {
    localStorage.setItem(LLM_API_KEY_STORAGE, llmKey.value.trim());
  });
}
