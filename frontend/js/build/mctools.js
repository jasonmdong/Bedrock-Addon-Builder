// =====================
// MINECRAFT CREATOR TOOLS (MCP) — STATUS ONLY
// MCP context is fetched automatically by the LLM pipeline.
// This module just tracks availability for the status badge.
// =====================

const MCTOOLS_API = "/api/mctools";

let mctoolsAvailable = false;

async function checkMctoolsHealth() {
  try {
    const res = await fetch(`${MCTOOLS_API}/health`);
    if (!res.ok) return false;
    const data = await res.json();
    mctoolsAvailable = data.available;
    updateMctoolsStatusUI(data);
    return data.available;
  } catch (e) {
    mctoolsAvailable = false;
    updateMctoolsStatusUI({ enabled: false, available: false });
    return false;
  }
}

function updateMctoolsStatusUI(data) {
  const badge = document.getElementById("mctools-status-badge");
  if (!badge) return;
  if (data.available) {
    badge.textContent = "MCP";
    badge.style.background = "#10b981";
    badge.style.color = "#fff";
    badge.title = "Minecraft Creator Tools — connected. LLM prompts are augmented with authoritative templates.";
  } else if (data.enabled) {
    badge.textContent = "MCP";
    badge.style.background = "#f59e0b";
    badge.style.color = "#000";
    badge.title = "Minecraft Creator Tools — starting up...";
  } else {
    badge.textContent = "MCP";
    badge.style.background = "#6b7280";
    badge.style.color = "#fff";
    badge.title = "Minecraft Creator Tools — disabled. LLM uses static context only.";
  }
}

function initMctools() {
  checkMctoolsHealth();
  setInterval(checkMctoolsHealth, 30000);
  console.log("[mctools] Health monitor initialized");
}
