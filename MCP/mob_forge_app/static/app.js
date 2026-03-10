/* ═══════════════════════════════════════════════════════════════════
   Mob Forge — Frontend Application Logic
   Tab routing, API calls, dynamic rendering, and state management
   ═══════════════════════════════════════════════════════════════════ */

// ─── State ──────────────────────────────────────────────────────────
const state = {
    currentTab: 'create',
    difficulty: 'medium',
    gallery: [],
    selectedMobs: new Set(),
    textureSize: 16,
    lastBuildResult: null,
};

// ─── Init ───────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initCreate();
    initTextures();
    initBuild();
    initParticles();
    loadGallery();
});

// ─── Tab Navigation ─────────────────────────────────────────────────
function initTabs() {
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            switchTab(tabName);
        });
    });
}

function switchTab(tabName) {
    state.currentTab = tabName;

    // Update tab buttons
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`.tab[data-tab="${tabName}"]`).classList.add('active');

    // Update content
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.getElementById(`content${capitalize(tabName)}`).classList.add('active');

    // Refresh tab-specific data
    if (tabName === 'gallery') renderGallery();
    if (tabName === 'textures') refreshTextureDropdown();
    if (tabName === 'build') refreshBuildList();
}

function capitalize(s) {
    return s.charAt(0).toUpperCase() + s.slice(1);
}

// ─── Create Mob ─────────────────────────────────────────────────────
function initCreate() {
    // Difficulty buttons
    document.querySelectorAll('.diff-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.diff-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.difficulty = btn.dataset.diff;
        });
    });

    // Generate button
    document.getElementById('btnGenerate').addEventListener('click', generateMob);

    // Quick prompts
    document.querySelectorAll('.quick-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.getElementById('mobDescription').value = btn.dataset.prompt;
            document.getElementById('mobDescription').focus();
        });
    });

    // Enter key
    document.getElementById('mobDescription').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            generateMob();
        }
    });
}

async function generateMob() {
    const description = document.getElementById('mobDescription').value.trim();
    if (!description) {
        showToast('Please describe your mob first!', 'error');
        return;
    }

    const btn = document.getElementById('btnGenerate');
    const loading = document.getElementById('createLoading');

    btn.disabled = true;
    loading.classList.remove('hidden');

    try {
        const res = await fetch('/api/generate-mob', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                description,
                difficulty: state.difficulty,
            }),
        });

        if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || 'Failed to generate mob');
        }

        const mob = await res.json();
        state.gallery.push(mob);
        updateGalleryCount();

        // Show result card
        const results = document.getElementById('createResults');
        results.insertAdjacentHTML('afterbegin', renderMobCard(mob, true));

        // Auto-generate texture
        autoGenerateTexture(mob.id);

        showToast(`Mob "${mob.metadata?.display_name || 'New Mob'}" created!`, 'success');
        document.getElementById('mobDescription').value = '';
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        loading.classList.add('hidden');
    }
}

async function autoGenerateTexture(mobId) {
    try {
        const res = await fetch(`/api/generate-texture/${mobId}`, { method: 'POST' });
        if (res.ok) {
            const data = await res.json();
            // Update gallery item
            const mob = state.gallery.find(m => m.id === mobId);
            if (mob) mob.texture_base64 = data.texture_base64;

            // Update card image if visible
            const img = document.getElementById(`tex-${mobId}`);
            if (img && data.texture_base64) {
                img.src = `data:image/png;base64,${data.texture_base64}`;
                img.style.display = 'block';
            }
        }
    } catch (e) {
        // Texture generation is non-critical
        console.warn('Auto-texture failed:', e);
    }
}

// ─── Mob Card Rendering ─────────────────────────────────────────────
function renderMobCard(mob, showActions = true) {
    const meta = mob.metadata || {};
    const name = meta.display_name || 'Unknown Mob';
    const desc = meta.description || mob.prompt || '';
    const hp = meta.hp || '?';
    const atk = meta.attack || '?';
    const spd = meta.speed || '?';
    const abilities = meta.abilities || [];
    const diff = mob.difficulty || 'medium';
    const texB64 = mob.texture_base64;

    const identifier = mob.entity?.['minecraft:entity']?.description?.identifier || 'custom:mob';

    return `
    <div class="mob-card" id="card-${mob.id}">
        <div class="mob-card-header">
            <div>
                <div class="mob-card-title">${escapeHtml(name)}</div>
                <div class="mob-card-id">${escapeHtml(identifier)}</div>
            </div>
            <div style="display:flex; align-items:center; gap:12px;">
                <img id="tex-${mob.id}" class="mob-card-texture"
                     src="${texB64 ? `data:image/png;base64,${texB64}` : ''}"
                     style="${texB64 ? '' : 'display:none'}"
                     alt="Mob texture">
                <span class="mob-card-difficulty ${diff}">${diff}</span>
            </div>
        </div>
        <p class="mob-card-desc">${escapeHtml(desc)}</p>
        <div class="mob-stats">
            <div class="stat-pill">
                <span class="stat-icon">❤️</span>
                <span class="stat-name">HP</span>
                <span class="stat-val">${hp}</span>
            </div>
            <div class="stat-pill">
                <span class="stat-icon">⚔️</span>
                <span class="stat-name">ATK</span>
                <span class="stat-val">${atk}</span>
            </div>
            <div class="stat-pill">
                <span class="stat-icon">💨</span>
                <span class="stat-name">SPD</span>
                <span class="stat-val">${spd}</span>
            </div>
        </div>
        ${abilities.length > 0 ? `
        <div class="mob-abilities">
            ${abilities.map(a => `<span class="ability-tag">${escapeHtml(a)}</span>`).join('')}
        </div>
        ` : ''}
        ${showActions ? `
        <div class="mob-card-actions">
            <button class="btn btn-download btn-sm" onclick="downloadMcworld('${mob.id}')">🌍 Download .mcworld</button>
            <button class="btn btn-ghost btn-sm" onclick="downloadSingleMob('${mob.id}')">📦 Download .mcpack</button>
            <button class="btn btn-ghost btn-sm" onclick="viewMobDetails('${mob.id}')">🔍 Details</button>
            <button class="btn btn-ghost btn-sm" onclick="regenerateTexture('${mob.id}')">🎨 New Texture</button>
            <button class="btn btn-danger btn-sm" onclick="deleteMob('${mob.id}')">🗑️ Delete</button>
        </div>
        ` : ''}
    </div>
    `;
}

// ─── .mcworld Download ──────────────────────────────────────────────
async function downloadMcworld(mobId) {
    showToast('Building .mcworld...', 'success');

    try {
        const res = await fetch(`/api/download-world/${mobId}`, { method: 'POST' });
        if (!res.ok) throw new Error('World build failed');

        const data = await res.json();
        downloadFile(data.file_base64, data.filename);

        showToast('World downloaded! Double-click the .mcworld file to import into Minecraft.', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// ─── Per-Mob Download ───────────────────────────────────────────────
async function downloadSingleMob(mobId) {
    showToast('Building .mcpack...', 'success');

    try {
        const res = await fetch(`/api/download-mob/${mobId}`, { method: 'POST' });
        if (!res.ok) throw new Error('Pack build failed');

        const data = await res.json();

        // Download both packs
        if (data.behavior_pack) {
            downloadFile(data.behavior_pack.file_base64, data.behavior_pack.filename);
        }
        if (data.resource_pack) {
            downloadFile(data.resource_pack.file_base64, data.resource_pack.filename);
        }

        showToast('Pack downloaded! Open .mcpack files to import into Minecraft.', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

function downloadFile(base64Data, filename) {
    const bytes = atob(base64Data);
    const arr = new Uint8Array(bytes.length);
    for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);

    const blob = new Blob([arr], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ─── Gallery ────────────────────────────────────────────────────────
async function loadGallery() {
    try {
        const res = await fetch('/api/gallery');
        const data = await res.json();
        state.gallery = data.mobs || [];
        updateGalleryCount();
    } catch (e) {
        console.warn('Failed to load gallery:', e);
    }
}

function renderGallery() {
    const grid = document.getElementById('galleryGrid');
    const empty = document.getElementById('galleryEmpty');

    if (state.gallery.length === 0) {
        grid.innerHTML = '';
        grid.appendChild(empty);
        empty.style.display = 'block';
        return;
    }

    grid.innerHTML = state.gallery.map(mob => renderMobCard(mob, true)).join('');
}

function updateGalleryCount() {
    document.getElementById('galleryCount').textContent = state.gallery.length;
}

async function deleteMob(mobId) {
    try {
        await fetch(`/api/gallery/${mobId}`, { method: 'DELETE' });
        state.gallery = state.gallery.filter(m => m.id !== mobId);
        state.selectedMobs.delete(mobId);
        updateGalleryCount();

        // Remove card if visible
        const card = document.getElementById(`card-${mobId}`);
        if (card) {
            card.style.animation = 'fadeSlideIn 0.3s ease reverse';
            setTimeout(() => card.remove(), 300);
        }

        showToast('Mob deleted', 'success');
    } catch (e) {
        showToast('Failed to delete mob', 'error');
    }
}

async function regenerateTexture(mobId) {
    showToast('Generating new texture...', 'success');
    await autoGenerateTexture(mobId);
    showToast('Texture updated!', 'success');
}

function viewMobDetails(mobId) {
    const mob = state.gallery.find(m => m.id === mobId);
    if (!mob) return;

    const modal = document.getElementById('mobModal');
    const body = document.getElementById('modalBody');

    const meta = mob.metadata || {};
    const entityJson = JSON.stringify(mob.entity, null, 2);

    body.innerHTML = `
        <h2 style="margin-bottom: 16px">${escapeHtml(meta.display_name || 'Mob Details')}</h2>
        ${mob.texture_base64 ? `
            <div style="text-align:center; margin-bottom:16px;">
                <img src="data:image/png;base64,${mob.texture_base64}"
                     style="width:128px; height:128px; image-rendering:pixelated; border:2px solid var(--border-subtle); border-radius:8px;"
                     alt="Mob texture">
            </div>
        ` : ''}
        <p style="color: var(--text-secondary); margin-bottom: 16px;">${escapeHtml(meta.description || '')}</p>
        <h3 style="font-size: 14px; color: var(--text-muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: 1px;">Entity JSON</h3>
        <pre class="modal-mob-json">${escapeHtml(entityJson)}</pre>
    `;

    modal.classList.remove('hidden');

    // Close handlers
    document.getElementById('modalClose').onclick = () => modal.classList.add('hidden');
    modal.onclick = (e) => { if (e.target === modal) modal.classList.add('hidden'); };
}

// ─── Textures ───────────────────────────────────────────────────────
function initTextures() {
    document.getElementById('btnGenTexture').addEventListener('click', generateTexture);

    // Size buttons
    document.querySelectorAll('.size-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.size-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.textureSize = parseInt(btn.dataset.size);
        });
    });

    // Add color button
    document.getElementById('btnAddColor').addEventListener('click', () => {
        const palette = document.getElementById('colorPalette');
        const picks = palette.querySelectorAll('.color-pick');
        if (picks.length >= 6) return;

        const input = document.createElement('input');
        input.type = 'color';
        input.className = 'color-pick';
        input.value = randomColor();
        input.dataset.index = picks.length;
        palette.insertBefore(input, document.getElementById('btnAddColor'));
    });
}

function refreshTextureDropdown() {
    const sel = document.getElementById('texMobSelect');
    sel.innerHTML = '<option value="">-- Choose a mob --</option>';
    state.gallery.forEach(mob => {
        const name = mob.metadata?.display_name || mob.entity?.['minecraft:entity']?.description?.identifier || 'Unknown';
        sel.innerHTML += `<option value="${mob.id}">${escapeHtml(name)}</option>`;
    });
}

async function generateTexture() {
    const mobId = document.getElementById('texMobSelect').value;
    const style = document.getElementById('texStyle').value;
    const picks = document.querySelectorAll('#colorPalette .color-pick');
    const colors = Array.from(picks).map(p => p.value);

    let mobName = 'custom_mob';
    let description = '';

    if (mobId) {
        const mob = state.gallery.find(m => m.id === mobId);
        if (mob) {
            mobName = mob.metadata?.display_name || 'mob';
            description = mob.metadata?.description || mob.prompt || '';
        }
    }

    const btn = document.getElementById('btnGenTexture');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Generating...';

    try {
        const res = await fetch('/api/generate-texture', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                mob_name: mobName,
                description,
                style,
                colors,
                size: state.textureSize,
            }),
        });

        if (!res.ok) throw new Error('Texture generation failed');

        const data = await res.json();

        // Render on canvas
        const canvas = document.getElementById('textureCanvas');
        const placeholder = document.getElementById('texPlaceholder');
        const img = new Image();
        img.onload = () => {
            canvas.style.display = 'block';
            placeholder.style.display = 'none';
            const ctx = canvas.getContext('2d');
            ctx.imageSmoothingEnabled = false;
            canvas.width = 256;
            canvas.height = 256;
            ctx.drawImage(img, 0, 0, 256, 256);
        };
        img.src = `data:image/png;base64,${data.texture_base64}`;

        // Update mob in gallery if selected
        if (mobId) {
            const mob = state.gallery.find(m => m.id === mobId);
            if (mob) mob.texture_base64 = data.texture_base64;
        }

        document.getElementById('textureInfo').innerHTML = `
            <p style="color: var(--text-secondary); font-size: 13px;">
                ${data.width}×${data.height} pixels • Style: ${style}
                ${data.ai_generated ? ' • 🤖 AI-designed' : ' • 🧮 Algorithmic'}
            </p>
        `;

        showToast('Texture generated!', 'success');
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">🎨</span> Generate Texture';
    }
}

// ─── Build Pack ─────────────────────────────────────────────────────
function initBuild() {
    document.getElementById('btnBuildPack').addEventListener('click', buildPack);
}

function refreshBuildList() {
    const list = document.getElementById('buildMobList');

    if (state.gallery.length === 0) {
        list.innerHTML = '<div class="gallery-empty"><p>No mobs available. Create some mobs first!</p></div>';
        return;
    }

    list.innerHTML = state.gallery.map(mob => {
        const name = mob.metadata?.display_name || 'Unknown';
        const id = mob.entity?.['minecraft:entity']?.description?.identifier || 'custom:mob';
        const checked = state.selectedMobs.has(mob.id) ? 'checked' : '';
        return `
        <label class="build-mob-item ${checked ? 'selected' : ''}" id="build-item-${mob.id}">
            <input type="checkbox" ${checked} onchange="toggleMobSelection('${mob.id}', this)">
            <div>
                <div class="build-mob-name">${escapeHtml(name)}</div>
                <div class="build-mob-id-text">${escapeHtml(id)}</div>
            </div>
        </label>
        `;
    }).join('');

    updateBuildCount();
}

function toggleMobSelection(mobId, checkbox) {
    if (checkbox.checked) {
        state.selectedMobs.add(mobId);
    } else {
        state.selectedMobs.delete(mobId);
    }

    const item = document.getElementById(`build-item-${mobId}`);
    if (item) item.classList.toggle('selected', checkbox.checked);

    updateBuildCount();
}

function updateBuildCount() {
    document.getElementById('selectedCount').textContent = state.selectedMobs.size;
    document.getElementById('btnBuildPack').disabled = state.selectedMobs.size === 0;
}

async function buildPack() {
    const packName = document.getElementById('packName').value.trim() || 'custom_mobs';
    const mobIds = Array.from(state.selectedMobs);

    const btn = document.getElementById('btnBuildPack');
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-icon">⏳</span> Building...';

    try {
        const res = await fetch('/api/build-pack', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mob_ids: mobIds, pack_name: packName }),
        });

        if (!res.ok) throw new Error('Pack build failed');

        const data = await res.json();
        state.lastBuildResult = data;

        // Show download buttons
        const result = document.getElementById('buildResult');
        result.classList.remove('hidden');

        // Update download buttons for the new .mcpack format
        const downloadArea = document.getElementById('buildDownloads');
        downloadArea.innerHTML = '';

        if (data.behavior_pack) {
            const bpBtn = document.createElement('button');
            bpBtn.className = 'btn btn-download';
            bpBtn.innerHTML = '<span class="btn-icon">⬇️</span> Download Behavior Pack (.mcpack)';
            bpBtn.onclick = () => downloadFile(data.behavior_pack.file_base64, data.behavior_pack.filename);
            downloadArea.appendChild(bpBtn);
        }

        if (data.resource_pack) {
            const rpBtn = document.createElement('button');
            rpBtn.className = 'btn btn-download';
            rpBtn.innerHTML = '<span class="btn-icon">⬇️</span> Download Resource Pack (.mcpack)';
            rpBtn.onclick = () => downloadFile(data.resource_pack.file_base64, data.resource_pack.filename);
            downloadArea.appendChild(rpBtn);
        }

        showToast(`Pack built! ${data.mob_count} mob(s)`, 'success');
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span class="btn-icon">📦</span> Build .mcpack';
    }
}

// ─── Particles ──────────────────────────────────────────────────────
function initParticles() {
    const container = document.getElementById('bgParticles');
    const colors = ['var(--emerald)', 'var(--diamond)', 'var(--gold)'];

    for (let i = 0; i < 20; i++) {
        const p = document.createElement('div');
        p.className = 'particle';
        p.style.left = `${Math.random() * 100}%`;
        p.style.animationDelay = `${Math.random() * 8}s`;
        p.style.animationDuration = `${6 + Math.random() * 6}s`;
        p.style.background = colors[Math.floor(Math.random() * colors.length)];
        container.appendChild(p);
    }
}

// ─── Utilities ──────────────────────────────────────────────────────
function showToast(message, type = 'success') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => toast.remove(), 4000);
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function randomColor() {
    return '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
}

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
}
