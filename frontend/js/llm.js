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
function llmStackKey(user, mob) {
  if (!user) return null;
  const m = mob || 'global';
  return `llm_stack_${user}_${m}`;
}
const LLM_STACK_MAX = 50;

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
  container.style.display = 'flex';
  container.style.flexDirection = 'row';
  container.style.alignItems = 'flex-start';
  container.style.background = 'transparent';
  container.style.borderRadius = '6px';
  container.style.padding = '2px';

  const gutter = document.createElement('pre');
  gutter.style.margin = '0';
  gutter.style.padding = '4px 6px';
  gutter.style.width = '64px';
  gutter.style.fontFamily = 'monospace';
  gutter.style.fontSize = '0.72rem';
  gutter.style.lineHeight = '1.1';
  gutter.style.color = 'var(--muted)';
  gutter.style.overflow = 'hidden';
  gutter.style.whiteSpace = 'nowrap';
  gutter.style.boxSizing = 'border-box';

  const content = document.createElement('pre');
  content.style.margin = '0';
  content.style.padding = '4px 6px';
  content.style.flex = '1';
  content.style.fontFamily = 'monospace';
  content.style.fontSize = '0.72rem';
  content.style.lineHeight = '1.1';
  content.style.overflow = 'auto';
  content.style.whiteSpace = 'pre';

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
          contentParts.push(`<div class="diff-line added" style="white-space:pre; padding:2px 6px; background:rgba(16,185,129,0.06); color:#10b981;">+ ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line added" style="padding:2px 6px; color:#a7f3d0;">→ ${newLine}</div>`);
          newLine++;
        } else if (chunk.removed) {
          removedCount++;
          contentParts.push(`<div class="diff-line removed" style="white-space:pre; padding:2px 6px; background:rgba(239,68,68,0.06); color:#ef4444;">- ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line removed" style="padding:2px 6px; color:#fecaca;">${oldLine} →</div>`);
          oldLine++;
        } else {
          contentParts.push(`<div class="diff-line context" style="white-space:pre; padding:2px 6px; color:var(--muted);">  ${escapeHtmlMini(l)}</div>`);
          gutterParts.push(`<div class="gutter-line context" style="padding:2px 6px; color:var(--muted);">${oldLine} | ${newLine}</div>`);
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
    const mob = currentMobName || null;
    if (user) {
      const entry = { ts: new Date().toISOString(), prompt: instruction, spec: payload.spec };
      pushLlmStack(user, mob, entry);
      renderLlmHistory();
    }
  } catch (e) {
    console.warn('Failed to write llm history', e);
  }
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

  llmProvider?.addEventListener("change", () => {
    localStorage.setItem(LLM_PROVIDER_KEY, llmProvider.value);
  });

  llmKey?.addEventListener("input", () => {
    localStorage.setItem(LLM_API_KEY_STORAGE, llmKey.value.trim());
  });
}
