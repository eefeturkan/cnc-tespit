/**
 * CNC Parça Ölçüm Sistemi — Frontend v2.0
 * Algoritmalar + Kalibrasyon + Ölçüm
 */

const state = {
    imageId: null, imageUrl: null, imageName: null,
    algorithms: [], selectedAlgorithm: null, currentParams: {},
    viewMode: 'split',
    // Calibration
    calMode: 'auto', // 'auto' or 'manual'
    isCalibrating: false,
    calibrated: false,
    pixelsPerMm: 1.0,
    detectedEdges: null, // {top_y, bottom_y, click_x, pixel_distance}
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
    // Measurement
    DOM.btnProfile = document.getElementById('btn-profile');
    DOM.btnMeasure = document.getElementById('btn-measure');
    DOM.measureTablePanel = document.getElementById('measurement-table-panel');
    DOM.measureTbody = document.getElementById('measurement-tbody');
    DOM.measureSummary = document.getElementById('measure-summary');
    DOM.btnDownloadImage = document.getElementById('btn-download-image');
    DOM.btnDownloadPdf = document.getElementById('btn-download-pdf');
    DOM.btnDownloadExcel = document.getElementById('btn-download-excel');
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
            } else {
                state.isCalibrating = false;
                DOM.originalPanel.classList.remove('calibrating');
            }
        });
    });
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
        DOM.uploadZone.style.display = 'none';
        DOM.thumbnailPreview.classList.add('visible');
        DOM.thumbnailImg.src = r.url; DOM.thumbnailName.textContent = r.filename;
        DOM.imageInfoBadge.classList.add('visible');
        DOM.imageInfoText.textContent = `${r.width}×${r.height} • ${r.size_kb} KB`;
        DOM.originalImage.src = r.url; DOM.processedImage.src = r.url;
        showImagePanels();
        // Reset edges
        state.detectedEdges = null;
        resetEdgeDisplay();
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

    // Tek tıklama ile kenar tespiti
    DOM.originalImage.addEventListener('click', handleAutoEdgeClick);

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
}

async function handleAutoEdgeClick(e) {
    if (!state.isCalibrating || !state.imageId) return;

    const img = DOM.originalImage;
    const rect = img.getBoundingClientRect();
    const scaleX = img.naturalWidth / rect.width;
    const scaleY = img.naturalHeight / rect.height;
    const clickX = Math.round((e.clientX - rect.left) * scaleX);
    const clickY = Math.round((e.clientY - rect.top) * scaleY);

    showLoading(true);
    try {
        const r = await API.detectEdges({
            image_id: state.imageId,
            click_x: clickX,
            click_y: clickY,
        });
        state.detectedEdges = r;

        // Overlay görüntüsünü göster (kenar çizgileri)
        DOM.processedImage.src = r.overlay_image;
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
    DOM.calResultPx.textContent = `${ppmm.toFixed(2)} px`;
    DOM.calibrationBadge.classList.add('visible', 'calibrated');
    DOM.calibrationStatus.textContent = `${ppmm.toFixed(2)} px/mm`;
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
        showLoading(true);
        try {
            const r = await API.extractProfile({ image_id: state.imageId, ...state.measureParams });
            DOM.processedImage.src = r.overlay_image;
            DOM.activeAlgoTitle.innerHTML = 'Profil Çıkarma <span class="algo-badge">overlay</span>';
            showImagePanels();
            showToast('Profil çıkarıldı', 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnMeasure.addEventListener('click', async () => {
        if (!state.imageId) { showToast('Önce fotoğraf yükleyin', 'warning'); return; }
        showLoading(true);
        try {
            const r = await API.measure({ image_id: state.imageId, ...state.measureParams });
            state.lastMeasurementTable = r.measurement_table;
            state.lastSummary = r.summary;
            DOM.processedImage.src = r.overlay_image;
            DOM.activeAlgoTitle.innerHTML = `Ölçüm Sonucu <span class="algo-badge">${r.summary.total_sections} bölüm</span>`;
            showImagePanels();
            renderMeasurementTable(r.measurement_table, r.summary);
            showToast(`Ölçüm tamamlandı: ${r.summary.total_sections} bölüm tespit edildi`, 'success');
        } catch (err) { showToast(err.message, 'error'); }
        finally { showLoading(false); }
    });

    DOM.btnDownloadPdf.addEventListener('click', async () => {
        if (!state.imageId || !state.lastMeasurementTable) return;
        showLoading(true);
        try {
            await API.download('/api/report/pdf', {
                image_id: state.imageId,
                measurement_table: state.lastMeasurementTable,
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
        try {
            await API.download('/api/report/excel', {
                image_id: state.imageId,
                measurement_table: state.lastMeasurementTable,
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
        showLoading(true);
        try {
            await API.download('/api/download-image', {
                image_id: state.imageId,
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

    // Summary
    if (summary.total_sections > 0) {
        DOM.measureSummary.textContent = `${summary.total_sections} bölüm | Çap: ${summary.min_diameter_mm.toFixed(2)}—${summary.max_diameter_mm.toFixed(2)} mm | Toplam boy: ${summary.total_length_mm.toFixed(2)} mm`;
    }

    // Table rows
    DOM.measureTbody.innerHTML = '';
    table.forEach(row => {
        const tr = document.createElement('tr');
        const typeClass = row.type === 'Çap' ? 'type-cap' : 'type-length';
        tr.innerHTML = `
            <td>${row.id}</td>
            <td class="${typeClass}">${row.type}</td>
            <td>${row.description}</td>
            <td>${row.measured_mm.toFixed(4)}</td>
        `;
        DOM.measureTbody.appendChild(tr);
    });
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
    try {
        state.algorithms = await API.getAlgorithms();
        renderAlgorithmList(state.algorithms);
    } catch (err) { showToast('Algoritmalar yüklenemedi: ' + err.message, 'error'); }
}

document.addEventListener('DOMContentLoaded', init);
