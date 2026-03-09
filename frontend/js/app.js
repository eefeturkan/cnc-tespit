/**
 * CNC Parça Ölçüm Sistemi — Frontend v2.0
 * Algoritmalar + Kalibrasyon + Ölçüm
 */

const state = {
    imageId: null, imageUrl: null, imageName: null,
    algorithms: [], selectedAlgorithm: null, currentParams: {},
    viewMode: 'split',
    // Algorithm result
    processedImageId: null, // Algoritma uygulanmış görüntünün disk ID'si
    // Calibration — Y ekseni (çap)
    calMode: 'auto', // 'auto' or 'manual'
    isCalibrating: false,
    calibrated: false,
    pixelsPerMm: 1.0,
    detectedEdges: null, // {top_y, bottom_y, click_x, pixel_distance}
    // Calibration — X ekseni (uzunluk)
    xCalState: 'idle',    // 'idle' | 'first_click' | 'second_click'
    xCalPoints: { x1: null, x2: null },
    xCalibrated: false,
    pixelsPerMmX: null,
    // Measurement
    lastMeasurementTable: null,
    lastSummary: null,
    measureParams: {
        min_section_width_px: 20, gradient_threshold: 2.0,
        blur_ksize: 5, morph_ksize: 5, min_contour_area: 5000,
    },
};

const DOM = {};

function cacheDom() {
    DOM.uploadZone = document.getElementById('upload-zone');
    DOM.fileInput = document.getElementById('file-input');
    DOM.thumbnailPreview = document.getElementById('thumbnail-preview');
    DOM.thumbnailImg = document.getElementById('thumbnail-img');
    DOM.thumbnailName = document.getElementById('thumbnail-name');
    DOM.btnChangeImage = document.getElementById('btn-change-image');
    DOM.imageInfoBadge = document.getElementById('image-info-badge');
    DOM.imageInfoText = document.getElementById('image-info-text');
    DOM.algorithmList = document.getElementById('algorithm-list');
    DOM.imageWorkspace = document.getElementById('image-workspace');
    DOM.emptyState = document.getElementById('empty-state');
    DOM.originalPanel = document.getElementById('original-panel');
    DOM.processedPanel = document.getElementById('processed-panel');
    DOM.imageDivider = document.getElementById('image-divider');
    DOM.originalImage = document.getElementById('original-image');
    DOM.processedImage = document.getElementById('processed-image');
    DOM.activeAlgoTitle = document.getElementById('active-algo-title');
    DOM.btnSplit = document.getElementById('btn-split');
    DOM.btnSingle = document.getElementById('btn-single');
    DOM.paramPanel = document.getElementById('param-panel');
    DOM.paramsGrid = document.getElementById('params-grid');
    DOM.btnApply = document.getElementById('btn-apply');
    DOM.loadingOverlay = document.getElementById('loading-overlay');
    DOM.toastContainer = document.getElementById('toast-container');
    // Calibration
    DOM.calibrationBadge = document.getElementById('calibration-badge');
    DOM.calibrationStatus = document.getElementById('calibration-status');
    DOM.calModeAuto = document.getElementById('cal-mode-auto');
    DOM.calModeManual = document.getElementById('cal-mode-manual');
    DOM.calAutoSection = document.getElementById('cal-auto-section');
    DOM.calManualSection = document.getElementById('cal-manual-section');
    DOM.calTopEdge = document.getElementById('cal-top-edge');
    DOM.calBottomEdge = document.getElementById('cal-bottom-edge');
    DOM.calDistance = document.getElementById('cal-distance');
    DOM.calReferenceMm = document.getElementById('cal-reference-mm');
    DOM.btnCalibrate = document.getElementById('btn-calibrate');
    DOM.calManualPpmm = document.getElementById('cal-manual-ppmm');
    DOM.btnCalibrateManual = document.getElementById('btn-calibrate-manual');
    DOM.calResult = document.getElementById('cal-result');
    DOM.calResultPpmm = document.getElementById('cal-result-ppmm');
    DOM.calResultPx = document.getElementById('cal-result-px');
    DOM.calResultPpmmX = document.getElementById('cal-result-ppmm-x');
    // Measurement
    DOM.btnProfile = document.getElementById('btn-profile');
    DOM.btnMeasure = document.getElementById('btn-measure');
    DOM.measureTablePanel = document.getElementById('measurement-table-panel');
    DOM.measureTbody = document.getElementById('measurement-tbody');
    DOM.measureSummary = document.getElementById('measure-summary');
    DOM.btnDownloadImage = document.getElementById('btn-download-image');
    DOM.btnDownloadPdf = document.getElementById('btn-download-pdf');
    DOM.btnDownloadExcel = document.getElementById('btn-download-excel');
    // X-Ekseni Kalibrasyon
    DOM.calXSection = document.getElementById('cal-x-section');
    DOM.calX1 = document.getElementById('cal-x1');
    DOM.calX2 = document.getElementById('cal-x2');
    DOM.calXDist = document.getElementById('cal-x-dist');
    DOM.calXReferenceMm = document.getElementById('cal-x-reference-mm');
    DOM.btnCalibrateX = document.getElementById('btn-calibrate-x');
    DOM.calXResult = document.getElementById('cal-x-result');
    DOM.calXResultPpmm = document.getElementById('cal-x-result-ppmm');
    DOM.calXHintText = document.getElementById('cal-x-hint-text');
    DOM.calXStep1 = document.getElementById('cal-x-step-1');
    DOM.calXStep2 = document.getElementById('cal-x-step-2');
    DOM.btnXReset = document.getElementById('btn-x-reset');
    // X-kalibrasyon canvas overlay'leri
    DOM.originalXCalCanvas = document.getElementById('original-xcal-canvas');
    DOM.processedXCalCanvas = document.getElementById('processed-xcal-canvas');
}

// ═══════════════════════════════════════════════════════════════
// API
// ═══════════════════════════════════════════════════════════════
const API = {
    async getAlgorithms() {
        const r = await fetch('/api/algorithms'); if (!r.ok) throw new Error('Algoritmalar yüklenemedi');
        return (await r.json()).algorithms;
    },
    async uploadImage(file) {
        const fd = new FormData(); fd.append('file', file);
        const r = await fetch('/api/upload', { method: 'POST', body: fd });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Yükleme başarısız'); }
        return r.json();
    },
    async processImage(imageId, algorithm, params) {
        const r = await fetch('/api/process', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ image_id: imageId, algorithm, params }) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'İşleme başarısız'); }
        return r.json();
    },
    async detectEdges(data) {
        const r = await fetch('/api/detect-edges', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Kenar tespiti başarısız'); }
        return r.json();
    },
    async calibrate(data) {
        const r = await fetch('/api/calibrate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Kalibrasyon başarısız'); }
        return r.json();
    },
    async calibrateManual(data) {
        const r = await fetch('/api/calibrate/manual', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Kalibrasyon başarısız'); }
        return r.json();
    },
    async extractProfile(data) {
        const r = await fetch('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Profil çıkarılamadı'); }
        return r.json();
    },
    async measure(data) {
        const r = await fetch('/api/measure', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'Ölçüm başarısız'); }
        return r.json();
    },
    async download(url, data, filename) {
        const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        if (!r.ok) {
            const text = await r.text();
            throw new Error('İndirme başarısız: ' + text);
        }
        const blob = await r.blob();
        const a = document.createElement('a');
        a.href = window.URL.createObjectURL(blob);
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(a.href);
    }
};

// ═══════════════════════════════════════════════════════════════
// UI Helpers
// ═══════════════════════════════════════════════════════════════
function showToast(msg, type = 'info') {
    const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
    const t = document.createElement('div');
    t.className = `toast ${type}`;
    t.innerHTML = `<span class="toast-icon">${icons[type]}</span><span>${msg}</span>`;
    DOM.toastContainer.appendChild(t);
    setTimeout(() => { t.style.animation = 'fadeOut 0.3s forwards'; setTimeout(() => t.remove(), 300); }, 3500);
}

function showLoading(show) { DOM.loadingOverlay.classList.toggle('visible', show); }

function updateViewMode(mode) {
    state.viewMode = mode;
    DOM.btnSplit.classList.toggle('active', mode === 'split');
    DOM.btnSingle.classList.toggle('active', mode === 'single');
    DOM.imageWorkspace.classList.toggle('single-view', mode === 'single');
}

function showImagePanels() {
    DOM.emptyState.classList.add('hidden');
    DOM.originalPanel.classList.remove('hidden');
    DOM.processedPanel.classList.remove('hidden');
    DOM.imageDivider.classList.remove('hidden');
}

// ═══════════════════════════════════════════════════════════════
// Sidebar Tabs
// ═══════════════════════════════════════════════════════════════
function setupTabs() {
    document.querySelectorAll('.sidebar-tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.sidebar-tab').forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.sidebar-tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            document.getElementById(btn.dataset.tab).classList.add('active');

            // Kalibrasyon tabı → calibrating mode aç
            if (btn.dataset.tab === 'tab-calibration' && state.calMode === 'auto') {
                state.isCalibrating = true;
                DOM.originalPanel.classList.add('calibrating');
                DOM.processedPanel.classList.add('calibrating');
                // Algoritma uygulanmışsa işlenmiş görsel üzerinden kalibre et
                // → tek görünüme geç, processed paneli göster
                if (state.processedImageId) {
                    updateViewMode('single');
                    DOM.originalPanel.classList.add('hidden');
                    DOM.processedPanel.classList.remove('hidden');
                }
            } else {
                state.isCalibrating = false;
                DOM.originalPanel.classList.remove('calibrating');
                DOM.processedPanel.classList.remove('calibrating');
            }

            // Overlayleri (ölçüm çizgileri, kenar çizgileri) temizle ve saf haline dön
            resetOverlays(btn.dataset.tab);
        });
    });
}

// Sekme değiştiğinde geçici çizgileri, ölçümleri (overlay) temizler, saf görseli gösterir
function resetOverlays(activeTabId) {
    if (!state.imageId) return;

    // Orijinal her zaman imageUrl'dir.
    DOM.originalImage.src = state.imageUrl;

    // İşlenmiş panel ise, algoritma uygulanmışsa processedUrl'dir.
    // Yoksa aynı imageUrl'dir (henüz algoritma yoksa).
    if (state.processedUrl) {
        DOM.processedImage.src = state.processedUrl;
    } else {
        DOM.processedImage.src = state.imageUrl;
    }

    // X-kalibrasyon canvas'ını temizle (ölçüm/algoritma sekmesine geçince)
    if (activeTabId !== 'tab-calibration') {
        clearXCalCanvas();
    } else if (state.xCalPoints.x1 !== null) {
        // Kalibrasyon sekmesine dönülünce işaretleri yeniden çiz
        setTimeout(drawXCalMarkers, 100);
    }

    // Başlık ve etiketleri tab'a uygun sıfırla
    if (activeTabId === 'tab-algorithms') {
        if (state.selectedAlgorithm) {
            DOM.activeAlgoTitle.innerHTML = `${state.selectedAlgorithm.display_name} <span class="algo-badge">${state.selectedAlgorithm.params.length} parametre</span>`;
        } else {
            DOM.activeAlgoTitle.innerHTML = 'Önizleme';
        }
    } else if (activeTabId === 'tab-calibration') {
        DOM.activeAlgoTitle.innerHTML = 'Kalibrasyon <span class="algo-badge">hazır</span>';
        resetEdgeDisplay(); // Kalibrasyon panelindeki eski tıklama değerlerini sil
    } else if (activeTabId === 'tab-measurement') {
        DOM.activeAlgoTitle.innerHTML = 'Ölçüm <span class="algo-badge">bekliyor</span>';
    }
}

// Kalibrasyon hint metnini güncelle
function updateCalibrationHint() {
    const hint = document.getElementById('cal-hint-text');
    if (!hint) return;
    if (state.processedImageId) {
        hint.innerHTML = '⚠️ Algoritma uygulandı. <strong>Kalibrasyon işlenmiş görsel</strong> üzerinden yapılacak. Her iki görsele de tıklayabilirsiniz.';
        hint.style.color = 'var(--accent-secondary)';
    } else {
        hint.innerHTML = 'Parçanın üzerine tıklayın — üst ve alt kenarlar otomatik tespit edilir. Sonra gerçek çap değerini mm olarak girin.';
        hint.style.color = '';
    }
}

// ═══════════════════════════════════════════════════════════════
// Algorithm List
// ═══════════════════════════════════════════════════════════════
function renderAlgorithmList(algs) {
    DOM.algorithmList.innerHTML = '';
    algs.forEach((a, i) => {
        const item = document.createElement('div');
        item.className = 'algo-item'; item.dataset.name = a.name;
        item.innerHTML = `<span class="algo-number">${String(i + 1).padStart(2, '0')}</span><div class="algo-info"><div class="algo-name">${a.display_name}</div><div class="algo-desc">${a.description}</div></div>`;
        item.addEventListener('click', () => selectAlgorithm(a));
        DOM.algorithmList.appendChild(item);
    });
}

function selectAlgorithm(algo) {
    state.selectedAlgorithm = algo;
    document.querySelectorAll('.algo-item').forEach(el => el.classList.toggle('active', el.dataset.name === algo.name));
    DOM.activeAlgoTitle.innerHTML = `${algo.display_name} <span class="algo-badge">${algo.params.length} parametre</span>`;
    renderParams(algo.params);
    DOM.measureTablePanel.classList.add('hidden');
    DOM.measureTablePanel.classList.remove('visible');
    if (state.imageId) applyAlgorithm();
}

// ═══════════════════════════════════════════════════════════════
// Parameters
// ═══════════════════════════════════════════════════════════════
function renderParams(params) {
    if (!params || !params.length) { DOM.paramPanel.classList.remove('visible'); state.currentParams = {}; return; }
    DOM.paramPanel.classList.add('visible');
    DOM.paramsGrid.innerHTML = '';
    state.currentParams = {};
    params.forEach(p => {
        state.currentParams[p.name] = p.default;
        const g = document.createElement('div'); g.className = 'param-group';
        if (p.type === 'select') {
            g.innerHTML = `<label class="param-label">${p.display_name}</label><select class="param-select" data-param="${p.name}">${p.options.map(o => `<option value="${o}" ${o === p.default ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
        } else {
            g.innerHTML = `<label class="param-label">${p.display_name}<span class="param-value-display" id="val-${p.name}">${p.default}</span></label><input type="range" data-param="${p.name}" min="${p.min}" max="${p.max}" value="${p.default}" step="${p.step}">`;
        }
        DOM.paramsGrid.appendChild(g);
        const inp = g.querySelector(`[data-param="${p.name}"]`);
        inp.addEventListener('input', e => {
            const v = p.type === 'float' ? parseFloat(e.target.value) : (p.type === 'select' ? e.target.value : parseInt(e.target.value));
            state.currentParams[p.name] = v;
            const d = document.getElementById(`val-${p.name}`); if (d) d.textContent = v;
        });
    });
}

// ═══════════════════════════════════════════════════════════════
// Upload
// ═══════════════════════════════════════════════════════════════
function setupUpload() {
    DOM.uploadZone.addEventListener('click', () => DOM.fileInput.click());
    DOM.btnChangeImage.addEventListener('click', e => { e.stopPropagation(); DOM.fileInput.click(); });
    DOM.fileInput.addEventListener('change', e => { if (e.target.files.length) handleFile(e.target.files[0]); });
    DOM.uploadZone.addEventListener('dragover', e => { e.preventDefault(); DOM.uploadZone.classList.add('drag-over'); });
    DOM.uploadZone.addEventListener('dragleave', () => DOM.uploadZone.classList.remove('drag-over'));
    DOM.uploadZone.addEventListener('drop', e => { e.preventDefault(); DOM.uploadZone.classList.remove('drag-over'); if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]); });
}

async function handleFile(file) {
    if (file.size > 50 * 1024 * 1024) { showToast('Dosya 50MB\'dan büyük', 'error'); return; }
    showLoading(true);
    try {
        const r = await API.uploadImage(file);
        state.imageId = r.image_id; state.imageUrl = r.url; state.imageName = r.filename;
        state.processedImageId = null; // Yeni görsel yüklenince sıfırla
        state.processedUrl = null; // Görsel atamasını da sıfırla
        DOM.uploadZone.style.display = 'none';
        DOM.thumbnailPreview.classList.add('visible');
        DOM.thumbnailImg.src = r.url; DOM.thumbnailName.textContent = r.filename;
        DOM.imageInfoBadge.classList.add('visible');
        DOM.imageInfoText.textContent = `${r.width}×${r.height} • ${r.size_kb} KB`;
        DOM.originalImage.src = r.url; DOM.processedImage.src = r.url;
        showImagePanels();
        // Reset edges + X-cal canvas
        state.detectedEdges = null;
        resetEdgeDisplay();
        clearXCalCanvas();
        updateCalibrationHint();
        showToast(`${r.filename} yüklendi`, 'success');
        if (state.selectedAlgorithm) await applyAlgorithm();
    } catch (err) { showToast(err.message, 'error'); }
    finally { showLoading(false); }
}

// ═══════════════════════════════════════════════════════════════
// Processing
// ═══════════════════════════════════════════════════════════════
async function applyAlgorithm() {
    if (!state.imageId) { showToast('Önce fotoğraf yükleyin', 'warning'); return; }
    if (!state.selectedAlgorithm) { showToast('Algoritma seçin', 'warning'); return; }
    showLoading(true); DOM.btnApply.disabled = true;
    try {
        const r = await API.processImage(state.imageId, state.selectedAlgorithm.name, state.currentParams);
        DOM.processedImage.src = r.result_image;

        // İşlenmiş görüntü ID'sini ve resim URL'sini sakla (sekmeler arası geçişte lazım)
        state.processedImageId = r.processed_image_id || null;
        state.processedUrl = r.result_image || null;

        updateCalibrationHint();
        showImagePanels();
        showToast(`${state.selectedAlgorithm.display_name} uygulandı`, 'success');
    } catch (err) { showToast(err.message, 'error'); }
    finally { showLoading(false); DOM.btnApply.disabled = false; }
}

// ═══════════════════════════════════════════════════════════════
// Calibration — Otomatik Kenar Tespiti
// ═══════════════════════════════════════════════════════════════
function setupCalibration() {
    // Mode toggle — Auto vs Manual
    DOM.calModeAuto.addEventListener('click', () => {
        state.calMode = 'auto'; state.isCalibrating = true;
        DOM.calModeAuto.classList.add('active'); DOM.calModeManual.classList.remove('active');
        DOM.calAutoSection.classList.remove('hidden'); DOM.calManualSection.classList.add('hidden');
        DOM.originalPanel.classList.add('calibrating');
    });
    DOM.calModeManual.addEventListener('click', () => {
        state.calMode = 'manual'; state.isCalibrating = false;
        DOM.calModeManual.classList.add('active'); DOM.calModeAuto.classList.remove('active');
        DOM.calManualSection.classList.remove('hidden'); DOM.calAutoSection.classList.add('hidden');
        DOM.originalPanel.classList.remove('calibrating');
    });

    // Tek tıklama ile kenar tespiti (hem orijinal hem işlenmiş görselde)
    DOM.originalImage.addEventListener('click', handleAutoEdgeClick);
    DOM.processedImage.addEventListener('click', handleAutoEdgeClick);

    // Kalibre Et butonu
    DOM.btnCalibrate.addEventListener('click', async () => {
        const mm = parseFloat(DOM.calReferenceMm.value);
        if (!mm || mm <= 0) { showToast('Geçerli bir mm değeri girin', 'warning'); return; }
        if (!state.detectedEdges) { showToast('Önce parçanın üzerine tıklayın', 'warning'); return; }
        try {
            const edges = state.detectedEdges;
            const r = await API.calibrate({
                reference_mm: mm,
                x1: edges.click_x, y1: edges.top_y,
                x2: edges.click_x, y2: edges.bottom_y,
            });
            setCalibrationResult(r.pixels_per_mm);
            showToast(`Kalibrasyon tamamlandı: ${r.pixels_per_mm.toFixed(2)} px/mm`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
    });

    // Manuel kalibrasyon
    DOM.btnCalibrateManual.addEventListener('click', async () => {
        const ppmm = parseFloat(DOM.calManualPpmm.value);
        if (!ppmm || ppmm <= 0) { showToast('Geçerli bir px/mm değeri girin', 'warning'); return; }
        try {
            const r = await API.calibrateManual({ pixels_per_mm: ppmm });
            setCalibrationResult(r.pixels_per_mm);
            showToast(`Manuel kalibrasyon: ${r.pixels_per_mm.toFixed(2)} px/mm`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
    });

    // X-Ekseni sıfırla (yeniden kalibre)
    DOM.btnXReset.addEventListener('click', () => {
        resetXCalibration();
        showToast('X-kalibrasyon sıfırlandı, sol kenara tıklayın', 'info');
    });

    // X-Ekseni kalibre et butonu
    DOM.btnCalibrateX.addEventListener('click', async () => {
        const mm = parseFloat(DOM.calXReferenceMm.value);
        if (!mm || mm <= 0) { showToast('Geçerli bir uzunluk değeri girin', 'warning'); return; }
        if (state.xCalPoints.x1 === null || state.xCalPoints.x2 === null) {
            showToast('Önce iki nokta seçin', 'warning'); return;
        }
        try {
            const r = await fetch('/api/calibrate/x-axis', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    reference_length_mm: mm,
                    x1: state.xCalPoints.x1,
                    x2: state.xCalPoints.x2,
                }),
            });
            if (!r.ok) { const e = await r.json(); throw new Error(e.detail || 'X-kalibrasyon başarısız'); }
            const data = await r.json();
            setXCalibrationResult(data.pixels_per_mm_x, data.pixels_per_mm_y);
            showToast(`X-Ekseni kalibre: ${data.pixels_per_mm_x.toFixed(2)} px/mm`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
    });
}

async function handleAutoEdgeClick(e) {
    if (!state.imageId) return;

    // Tıklanan görseli belirle: processed veya original
    const isProcessedClick = (e.currentTarget === DOM.processedImage);
    const refImg = isProcessedClick ? DOM.processedImage : DOM.originalImage;
    const rect = refImg.getBoundingClientRect();
    const scaleX = refImg.naturalWidth / rect.width;
    const scaleY = refImg.naturalHeight / rect.height;
    const clickX = Math.round((e.clientX - rect.left) * scaleX);
    const clickY = Math.round((e.clientY - rect.top) * scaleY);

    // X-Ekseni kalibrasyon modu (uzunluk) — sadece X koordinatı alınır
    if (state.xCalState !== 'idle') {
        handleXCalClick(clickX);
        return;
    }

    // Y-Ekseni kalibrasyon modu (çap) — kenar tespiti yapılır
    if (!state.isCalibrating) return;

    // Hangi image_id kullanılacak:
    // Algoritma uygulanmışsa işlenmiş görselin ID'si, aksi halde orijinal
    const calImageId = state.processedImageId || state.imageId;

    showLoading(true);
    try {
        const r = await API.detectEdges({
            image_id: calImageId,
            click_x: clickX,
            click_y: clickY,
        });
        state.detectedEdges = r;

        // Overlay görüntüsünü göster (kenar çizgileri)
        DOM.processedImage.src = r.overlay_image;
        DOM.processedPanel.classList.remove('hidden');
        DOM.activeAlgoTitle.innerHTML = 'Kenar Tespiti <span class="algo-badge">kalibrasyon</span>';
        showImagePanels();

        // Paneli güncelle
        DOM.calTopEdge.textContent = `x=${r.click_x}, y=${r.top_y}`;
        DOM.calBottomEdge.textContent = `x=${r.click_x}, y=${r.bottom_y}`;
        DOM.calDistance.textContent = `${r.pixel_distance} px`;
        DOM.btnCalibrate.disabled = false;

        showToast(`Kenarlar tespit edildi: ${r.pixel_distance} px`, 'success');
    } catch (err) {
        showToast(err.message, 'error');
    } finally {
        showLoading(false);
    }
}

function setXCalActiveStyle(active) {
    DOM.originalPanel.classList.toggle('xcal-active', active);
    DOM.processedPanel.classList.toggle('xcal-active', active);
}

function handleXCalClick(clickX) {
    if (state.xCalState === 'first_click') {
        // 1. nokta alındı
        state.xCalPoints.x1 = clickX;
        state.xCalPoints.x2 = null;
        state.xCalState = 'second_click';

        DOM.calX1.textContent = `${clickX} px`;
        DOM.calX2.textContent = '—';
        DOM.calXDist.textContent = '— px';
        DOM.btnCalibrateX.disabled = true;

        DOM.calXStep1.classList.add('done');
        DOM.calXStep2.classList.add('active');
        DOM.calXHintText.textContent = 'Şimdi sağ kenara tıklayın (2. nokta).';

        drawXCalMarkers();
        showToast(`Sol kenar (X1): x=${clickX} px`, 'info');
    } else if (state.xCalState === 'second_click') {
        // 2. nokta alındı
        state.xCalPoints.x2 = clickX;
        state.xCalState = 'idle'; // Tıklama modunu kapat

        const dist = Math.abs(clickX - state.xCalPoints.x1);
        DOM.calX2.textContent = `${clickX} px`;
        DOM.calXDist.textContent = `${dist} px`;

        DOM.calXStep2.classList.add('done');
        DOM.btnCalibrateX.disabled = false;
        DOM.calXHintText.textContent = 'İki nokta seçildi. Gerçek uzunluğu girin ve kalibre edin.';

        drawXCalMarkers();
        setXCalActiveStyle(false); // 2. nokta alındı, tıklama modu kapandı
        showToast(`Sağ kenar (X2): x=${clickX} px | Mesafe: ${dist} px`, 'success');
    }
}

function resetEdgeDisplay() {
    DOM.calTopEdge.textContent = '—';
    DOM.calBottomEdge.textContent = '—';
    DOM.calDistance.textContent = '— px';
    DOM.btnCalibrate.disabled = true;
}

function setCalibrationResult(ppmm) {
    state.calibrated = true;
    state.pixelsPerMm = ppmm;
    DOM.calResult.classList.remove('hidden');
    DOM.calResultPpmm.textContent = ppmm.toFixed(4);
    // X henüz kalibre edilmediyse "bekliyor" göster, edilmişse güncel değeri göster
    if (state.xCalibrated) {
        DOM.calResultPpmmX.textContent = state.pixelsPerMmX ? state.pixelsPerMmX.toFixed(4) : 'henüz kalibre edilmedi';
    } else {
        DOM.calResultPpmmX.textContent = 'henüz kalibre edilmedi';
    }
    DOM.calResultPx.textContent = `${ppmm.toFixed(2)} px`;
    DOM.calibrationBadge.classList.add('visible', 'calibrated');
    DOM.calibrationStatus.textContent = `Y:${ppmm.toFixed(2)} px/mm`;
    // Y kalibrasyonundan sonra X-kalibrasyon bölümünü göster
    DOM.calXSection.classList.remove('hidden');
    // X-kalibrasyon tıklama modunu etkinleştir
    state.xCalState = 'first_click';
    DOM.calXStep1.classList.remove('done');
    DOM.calXStep2.classList.remove('active', 'done');
    DOM.calXHintText.textContent = 'Bilinen uzunluktaki bir bölümün sol kenarına tıklayın (1. nokta).';
    setXCalActiveStyle(true);
}

function setXCalibrationResult(ppmmX, ppmmY) {
    state.xCalibrated = true;
    state.pixelsPerMmX = ppmmX;
    // Y sonuç kutusundaki X satırını güncelle
    DOM.calResultPpmmX.textContent = ppmmX.toFixed(4);
    // X sonuç kutusunu göster
    DOM.calXResult.classList.remove('hidden');
    DOM.calXResultPpmm.textContent = ppmmX.toFixed(4);
    // Header'daki rozet güncelle
    DOM.calibrationBadge.classList.add('visible', 'calibrated');
    DOM.calibrationStatus.textContent = `Y:${(ppmmY || state.pixelsPerMm).toFixed(2)} X:${ppmmX.toFixed(2)} px/mm`;
    // X-kalibrasyon tıklama modunu kapat
    state.xCalState = 'idle';
    setXCalActiveStyle(false);
    DOM.calXHintText.textContent = 'X-ekseni kalibre edildi. Yeniden kalibre etmek için ↺ butonuna basın.';
    DOM.btnCalibrateX.disabled = true;
}

function resetXCalibration() {
    state.xCalState = 'first_click';
    state.xCalPoints = { x1: null, x2: null };
    DOM.calX1.textContent = '—';
    DOM.calX2.textContent = '—';
    DOM.calXDist.textContent = '— px';
    DOM.btnCalibrateX.disabled = true;
    DOM.calXStep1.classList.remove('done');
    DOM.calXStep2.classList.remove('active', 'done');
    DOM.calXHintText.textContent = 'Bilinen uzunluktaki bir bölümün sol kenarına tıklayın (1. nokta).';
    clearXCalCanvas();
    setXCalActiveStyle(true); // Yeniden tıklama moduna gir
}

// ─── X-Kalibrasyon Canvas Overlay ────────────────────────────────────────────

function clearXCalCanvas() {
    [DOM.originalXCalCanvas, DOM.processedXCalCanvas].forEach(canvas => {
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    });
}

function syncCanvasSize(canvas, img) {
    // Canvas boyutunu img'nin gerçek render boyutuna eşitle
    const rect = img.getBoundingClientRect();
    if (rect.width === 0) return false;
    if (canvas.width !== Math.round(rect.width) || canvas.height !== Math.round(rect.height)) {
        canvas.width = Math.round(rect.width);
        canvas.height = Math.round(rect.height);
    }
    return true;
}

function drawXCalMarkers() {
    const pairs = [
        { canvas: DOM.originalXCalCanvas, img: DOM.originalImage },
        { canvas: DOM.processedXCalCanvas, img: DOM.processedImage },
    ];

    pairs.forEach(({ canvas, img }) => {
        if (!canvas || !img || !img.naturalWidth) return;
        if (!syncCanvasSize(canvas, img)) return;

        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        const scaleX = canvas.width / img.naturalWidth;

        // X1 işareti (sarı dikey çizgi)
        if (state.xCalPoints.x1 !== null) {
            const dx1 = state.xCalPoints.x1 * scaleX;
            ctx.save();
            ctx.strokeStyle = '#f59e0b';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            ctx.moveTo(dx1, 0);
            ctx.lineTo(dx1, canvas.height);
            ctx.stroke();
            // Etiket
            ctx.setLineDash([]);
            ctx.fillStyle = '#f59e0b';
            ctx.font = 'bold 12px JetBrains Mono, monospace';
            ctx.fillText('X1', dx1 + 4, 18);
            ctx.restore();
        }

        // X2 işareti (turuncu dikey çizgi)
        if (state.xCalPoints.x2 !== null) {
            const dx2 = state.xCalPoints.x2 * scaleX;
            ctx.save();
            ctx.strokeStyle = '#fb923c';
            ctx.lineWidth = 2;
            ctx.setLineDash([6, 4]);
            ctx.beginPath();
            ctx.moveTo(dx2, 0);
            ctx.lineTo(dx2, canvas.height);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#fb923c';
            ctx.font = 'bold 12px JetBrains Mono, monospace';
            ctx.fillText('X2', dx2 + 4, 18);
            ctx.restore();

            // X1-X2 arası renkli bant
            if (state.xCalPoints.x1 !== null) {
                const dx1 = state.xCalPoints.x1 * scaleX;
                ctx.save();
                ctx.fillStyle = 'rgba(245, 158, 11, 0.10)';
                ctx.fillRect(
                    Math.min(dx1, dx2), 0,
                    Math.abs(dx2 - dx1), canvas.height
                );
                // Üstte mesafe etiketi
                const midX = (dx1 + dx2) / 2;
                const dist = Math.abs(state.xCalPoints.x2 - state.xCalPoints.x1);
                ctx.fillStyle = '#fcd34d';
                ctx.font = 'bold 11px JetBrains Mono, monospace';
                ctx.textAlign = 'center';
                ctx.fillText(`${dist} px`, midX, 34);
                ctx.restore();
            }
        }
    });
}

// ═══════════════════════════════════════════════════════════════
// Measurement
// ═══════════════════════════════════════════════════════════════
function setupMeasurement() {
    // Slider events
    const sliders = [
        { id: 'measure-min-section', key: 'min_section_width_px', valId: 'val-min-section', type: 'int' },
        { id: 'measure-gradient', key: 'gradient_threshold', valId: 'val-gradient', type: 'float' },
        { id: 'measure-blur', key: 'blur_ksize', valId: 'val-blur', type: 'int' },
        { id: 'measure-morph', key: 'morph_ksize', valId: 'val-morph', type: 'int' },
        { id: 'measure-contour-area', key: 'min_contour_area', valId: 'val-contour', type: 'int' },
    ];

    sliders.forEach(s => {
        const el = document.getElementById(s.id);
        el.addEventListener('input', e => {
            const v = s.type === 'float' ? parseFloat(e.target.value) : parseInt(e.target.value);
            state.measureParams[s.key] = v;
            document.getElementById(s.valId).textContent = v;
        });
    });

    DOM.btnProfile.addEventListener('click', async () => {
        if (!state.imageId) { showToast('Önce fotoğraf yükleyin', 'warning'); return; }
        const activeId = state.processedImageId || state.imageId;
        showLoading(true);
        try {
            const r = await API.extractProfile({ image_id: activeId, ...state.measureParams });
            DOM.processedImage.src = r.overlay_image;
            DOM.activeAlgoTitle.innerHTML = 'Profil Çıkarma <span class="algo-badge">overlay</span>';
            showImagePanels();
            showToast('Profil çıkarıldı', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnMeasure.addEventListener('click', async () => {
        if (!state.imageId) { showToast('Önce fotoğraf yükleyin', 'warning'); return; }
        if (!state.calibrated) { showToast('Önce kalibrasyon yapın', 'warning'); return; }
        if (!state.xCalibrated) {
            showToast('X-ekseni kalibre edilmedi — uzunluk ölçümleri yaklaşık olacak. Kalibrasyon sekmesinde X-eksenini kalibre edin.', 'warning');
        }
        const activeId = state.processedImageId || state.imageId;
        showLoading(true);
        try {
            const r = await API.measure({ image_id: activeId, ...state.measureParams });
            state.lastMeasurementTable = r.measurement_table;
            state.lastSummary = r.summary;
            DOM.processedImage.src = r.overlay_image;
            DOM.activeAlgoTitle.innerHTML = `Ölçüm Sonucu <span class="algo-badge">${r.summary.total_sections} bölüm</span>`;
            showImagePanels();
            renderMeasurementTable(r.measurement_table, r.summary);
            const xNote = r.x_calibrated ? '' : ' (X: yaklaşık)';
            showToast(`Ölçüm tamamlandı: ${r.summary.total_sections} bölüm${xNote}`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnDownloadPdf.addEventListener('click', async () => {
        if (!state.imageId || !state.lastMeasurementTable) return;
        const activeId = state.processedImageId || state.imageId;
        showLoading(true);

        // Tabloyu referans verilerle zenginleştir
        const enrichedTable = state.lastMeasurementTable.map(row => ({
            ...row,
            target: state.referencePart[row.id]?.target || null,
            tol: state.referencePart[row.id]?.tol || 0.05,
            status: row.status || null
        }));

        try {
            await API.download('/api/report/pdf', {
                image_id: activeId,
                measurement_table: enrichedTable,
                summary: state.lastSummary,
                include_image: true,
                ...state.measureParams
            }, 'olcum_raporu.pdf');
            showToast('PDF raporu indirildi', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnDownloadExcel.addEventListener('click', async () => {
        if (!state.imageId || !state.lastMeasurementTable) return;
        showLoading(true);

        // Tabloyu referans verilerle zenginleştir
        const enrichedTable = state.lastMeasurementTable.map(row => ({
            ...row,
            target: state.referencePart[row.id]?.target || null,
            tol: state.referencePart[row.id]?.tol || 0.05,
            status: row.status || null
        }));

        try {
            await API.download('/api/report/excel', {
                image_id: state.processedImageId || state.imageId,
                measurement_table: enrichedTable,
                summary: state.lastSummary,
                include_image: false,
                ...state.measureParams
            }, 'olcum_raporu.xlsx');
            showToast('Excel raporu indirildi', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnDownloadImage.addEventListener('click', async () => {
        if (!state.imageId) return;
        const activeId = state.processedImageId || state.imageId;
        showLoading(true);
        try {
            await API.download('/api/download-image', {
                image_id: activeId,
                ...state.measureParams
            }, 'olcum_gorsel.png');
            showToast('Ölçüm görseli indirildi', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });
}

function renderMeasurementTable(table, summary) {
    DOM.measureTablePanel.classList.remove('hidden');
    DOM.measureTablePanel.classList.add('visible');
    DOM.paramPanel.classList.remove('visible');

    // Referans parçası nesnesi yoksa başlat
    if (!state.referencePart) state.referencePart = {};

    // Summary
    if (summary.total_sections > 0) {
        DOM.measureSummary.textContent = `${summary.total_sections} bölüm | Çap: ${summary.min_diameter_mm.toFixed(2)}—${summary.max_diameter_mm.toFixed(2)} mm | Toplam boy: ${summary.total_length_mm.toFixed(2)} mm`;
    }

    // Table rows
    DOM.measureTbody.innerHTML = '';
    table.forEach(row => {
        const tr = document.createElement('tr');
        const typeClass = row.type === 'Çap' ? 'type-cap' : 'type-length';

        let targetVal = state.referencePart[row.id]?.target || '';
        let tolVal = state.referencePart[row.id]?.tol || 0.05;

        tr.innerHTML = `
            <td>${row.id}</td>
            <td class="${typeClass}">${row.type}</td>
            <td>${row.description}</td>
            <td class="measured-value-cell">${row.measured_mm.toFixed(4)}</td>
            <td><input type="number" class="ref-target" data-id="${row.id}" value="${targetVal}" step="0.01" style="width:70px; background:#1e293b; color:#fff; border:1px solid #334155; border-radius:4px; padding:2px;"></td>
            <td><input type="number" class="ref-tol" data-id="${row.id}" value="${tolVal}" step="0.01" style="width:60px; background:#1e293b; color:#fff; border:1px solid #334155; border-radius:4px; padding:2px;"></td>
            <td class="status-cell" id="status-${row.id}">-</td>
        `;
        DOM.measureTbody.appendChild(tr);

        // Değer değiştiğinde otomatik hesaplama
        const inpTarget = tr.querySelector('.ref-target');
        const inpTol = tr.querySelector('.ref-tol');
        const updateStatus = () => {
            const target = parseFloat(inpTarget.value);
            const tol = parseFloat(inpTol.value);
            const statusCell = tr.querySelector('.status-cell');

            // State'e kaydet (birden fazla parça ölçülünce hatırlasın)
            if (!state.referencePart[row.id]) state.referencePart[row.id] = {};
            state.referencePart[row.id].target = isNaN(target) ? null : target;
            state.referencePart[row.id].tol = isNaN(tol) ? 0.05 : tol;

            if (isNaN(target)) {
                statusCell.textContent = '-';
                statusCell.className = 'status-cell';
                row.status = null;
                return;
            }

            const diff = Math.abs(row.measured_mm - target);
            if (diff <= tol) {
                statusCell.textContent = 'PASS';
                statusCell.className = 'status-cell status-pass';
                statusCell.style.color = '#4ade80';
                statusCell.style.fontWeight = 'bold';
                row.status = 'PASS';
            } else {
                statusCell.textContent = 'FAIL';
                statusCell.className = 'status-cell status-fail';
                statusCell.style.color = '#f87171';
                statusCell.style.fontWeight = 'bold';
                row.status = 'FAIL';
            }
        };

        inpTarget.addEventListener('input', updateStatus);
        inpTol.addEventListener('input', updateStatus);

        // İlk yüklendiğinde statusleri hesaplasın
        if (targetVal) updateStatus();
    });

    // "Referans Ayarla" butonuna basılırsa, o anki ölçülmüş tüm değerleri Hedef olarak kaydet
    const btnSetReference = document.getElementById('btn-set-reference');
    if (btnSetReference) {
        btnSetReference.onclick = () => {
            table.forEach(row => {
                if (!state.referencePart[row.id]) state.referencePart[row.id] = {};
                // Ölçülen değeri doğrudan Yuvarlayarak hedefe at (Örn 14.8099 -> 14.81)
                state.referencePart[row.id].target = parseFloat(row.measured_mm.toFixed(2));
                state.referencePart[row.id].tol = 0.05; // Varsayılan tolerans
            });
            // Tabloyu ekranda güncelle
            renderMeasurementTable(table, summary);
            showToast('Aktif parça kopyalandı ve altın referans olarak ayarlandı', 'success');
        };
    }
}

// ═══════════════════════════════════════════════════════════════
// Events
// ═══════════════════════════════════════════════════════════════
function setupEvents() {
    DOM.btnSplit.addEventListener('click', () => updateViewMode('split'));
    DOM.btnSingle.addEventListener('click', () => updateViewMode('single'));
    DOM.btnApply.addEventListener('click', applyAlgorithm);
    document.addEventListener('keydown', e => {
        if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
        if (e.key === 'Enter' && state.imageId && state.selectedAlgorithm) { e.preventDefault(); applyAlgorithm(); }
        if (e.key >= '1' && e.key <= '9' && !e.ctrlKey && !e.altKey) {
            const idx = parseInt(e.key) - 1;
            if (idx < state.algorithms.length) selectAlgorithm(state.algorithms[idx]);
        }
    });
}

// ═══════════════════════════════════════════════════════════════
// Init
// ═══════════════════════════════════════════════════════════════
async function init() {
    cacheDom();
    setupUpload();
    setupTabs();
    setupCalibration();
    setupMeasurement();
    setupEvents();

    // Resim yüklenince canvas boyutunu eşitle ve X işaretlerini yeniden çiz
    [DOM.originalImage, DOM.processedImage].forEach(img => {
        img.addEventListener('load', () => {
            if (state.xCalPoints.x1 !== null) drawXCalMarkers();
        });
    });
    // Pencere resize'ında da yeniden çiz
    window.addEventListener('resize', () => {
        if (state.xCalPoints.x1 !== null) drawXCalMarkers();
    });

    try {
        state.algorithms = await API.getAlgorithms();
        renderAlgorithmList(state.algorithms);
    } catch (err) { showToast('Algoritmalar yüklenemedi: ' + err.message, 'error'); }
}

document.addEventListener('DOMContentLoaded', init);
