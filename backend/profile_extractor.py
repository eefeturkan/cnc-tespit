"""
CNC Parça Ölçüm Sistemi — Profil Çıkarıcı
Parçanın silüetinden profil verisi (üst/alt kenar, çap profili) çıkarır.
"""

import cv2
import numpy as np
import scipy.ndimage as ndimage
import scipy.signal as signal
from typing import Dict, List, Tuple, Optional


def _subpixel_edge_1d(gray_col: np.ndarray, y: int, search_window: int = 3) -> float:
    """1D gradyan tabanlı parabolik interpolasyon ile alt-piksel (sub-pixel) kenar tespiti."""
    h = len(gray_col)
    if y < search_window + 1 or y >= h - search_window - 2:
        return float(y)
    
    # Arama penceresi içindeki gradyanları hesapla (mutlak değer)
    grads = []
    y_vals = range(y - search_window, y + search_window + 1)
    for i in y_vals:
        # Merkezi fark (Central difference)
        g = abs(float(gray_col[i+1]) - float(gray_col[i-1]))
        grads.append(g)
        
    max_idx = int(np.argmax(grads))
    best_y = y_vals[max_idx]
    
    # Sınırlara çok yakınsa interpolasyon yapma
    if max_idx == 0 or max_idx == len(grads) - 1:
        return float(best_y)
        
    g_minus = grads[max_idx - 1]
    g_zero = grads[max_idx]
    g_plus = grads[max_idx + 1]
    
    denom = g_minus - 2 * g_zero + g_plus
    if denom == 0:
        return float(best_y)
        
    delta = 0.5 * (g_minus - g_plus) / denom
    delta = max(-1.0, min(1.0, delta))
    
    return float(best_y) + delta


def _subpixel_edge_1d_polarity(
    gray_col: np.ndarray,
    y: int,
    search_window: int = 3,
    edge: str = "any",
) -> float:
    """
    Kenar yönünü dikkate alarak sub-pixel kenar konumu bulur.

    edge:
      - "top": parlak arka plandan daha koyu parçaya geçiş (negatif gradyan)
      - "bottom": koyu parçadan parlak arka plana geçiş (pozitif gradyan)
      - "any": yön farkı gözetmez
    """
    h = len(gray_col)
    if y < search_window + 1 or y >= h - search_window - 2:
        return float(y)

    grads = []
    y_vals = list(range(y - search_window, y + search_window + 1))
    for i in y_vals:
        g = 0.5 * (float(gray_col[i + 1]) - float(gray_col[i - 1]))
        grads.append(g)

    if edge == "top":
        signed = np.array(grads, dtype=float)
        candidate_mask = signed < 0
        if np.any(candidate_mask):
            masked_scores = np.where(candidate_mask, -signed, -np.inf)
            max_idx = int(np.argmax(masked_scores))
        else:
            max_idx = int(np.argmax(np.abs(signed)))
    elif edge == "bottom":
        signed = np.array(grads, dtype=float)
        candidate_mask = signed > 0
        if np.any(candidate_mask):
            masked_scores = np.where(candidate_mask, signed, -np.inf)
            max_idx = int(np.argmax(masked_scores))
        else:
            max_idx = int(np.argmax(np.abs(signed)))
    else:
        signed = np.array(grads, dtype=float)
        max_idx = int(np.argmax(np.abs(signed)))

    best_y = y_vals[max_idx]
    if max_idx == 0 or max_idx == len(grads) - 1:
        return float(best_y)

    g_minus = signed[max_idx - 1]
    g_zero = signed[max_idx]
    g_plus = signed[max_idx + 1]

    denom = g_minus - 2 * g_zero + g_plus
    if denom == 0:
        return float(best_y)

    delta = 0.5 * (g_minus - g_plus) / denom
    delta = max(-1.0, min(1.0, delta))
    return float(best_y) + delta


def _snap_edge_to_support(
    edge_col: Optional[np.ndarray],
    coarse_y: int,
    search_radius: int = 6,
    prefer: str = "nearest",
) -> int:
    """
    Kaba maske kenarını, gerçek kenar destek haritasındaki en yakın adaya hizalar.

    prefer:
      - "up": coarse_y'nin üstündeki/en yakın adayı tercih et
      - "down": coarse_y'nin altındaki/en yakın adayı tercih et
      - "nearest": mutlak en yakın adayı seç
    """
    if edge_col is None or coarse_y < 0:
        return int(coarse_y)

    edge_idx = np.where(edge_col > 0)[0]
    if len(edge_idx) == 0:
        return int(coarse_y)

    nearby = edge_idx[np.abs(edge_idx - coarse_y) <= search_radius]
    if len(nearby) == 0:
        return int(coarse_y)

    if prefer == "up":
        upward = nearby[nearby <= coarse_y]
        if len(upward) > 0:
            return int(upward[-1])
    elif prefer == "down":
        downward = nearby[nearby >= coarse_y]
        if len(downward) > 0:
            return int(downward[0])

    nearest_idx = int(np.argmin(np.abs(nearby - coarse_y)))
    return int(nearby[nearest_idx])


def _remove_outliers(edge_array: List[Optional[float]], window: int = 11, threshold: float = 2.0) -> List[Optional[float]]:
    """
    Komşu piksellere göre çok sapan (outlier) noktaları temizler.
    Median filtreden farkı: Sadece sapan noktaları değiştirir, diğerlerini korur.
    """
    if not edge_array or len(edge_array) < window:
        return edge_array
        
    result = list(edge_array)
    arr = np.array([x if x is not None else np.nan for x in edge_array], dtype=float)
    
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            continue
            
        # Pencere sınırlarını belirle
        start = max(0, i - window // 2)
        end = min(len(arr), i + window // 2 + 1)
        
        # Komşuların medyanını bul
        neighbor_slice = arr[start:end]
        valid_neighbors = neighbor_slice[~np.isnan(neighbor_slice)]
        
        if len(valid_neighbors) < 3:
            continue
            
        med = np.median(valid_neighbors)
        
        # Eğer noktada büyük sapma varsa medyan ile değiştir (outlier temizliği)
        if abs(arr[i] - med) > threshold:
            result[i] = float(med)
            
    return result


def _savitzky_golay_smooth(edge_array: List[Optional[float]], window: int = 15, polyorder: int = 2) -> List[Optional[float]]:
    """
    Savitzky-Golay filtresi ile kenar profilini yumuşatır.
    Fiziksel geometriyi (köşeleri) Gaussian'dan daha iyi korur.
    """
    if not edge_array or len(edge_array) < window:
        return edge_array
        
    mask = [x is not None for x in edge_array]
    vals = np.array([x if x is not None else 0 for x in edge_array], dtype=float)
    
    # None değerleri civarındaki verilerle doldur (polinom fit için sürekli dizi lazım)
    # Basit bir interpolasyon (pad)
    for i in range(len(vals)):
        if not mask[i]:
            # En yakın geçerli değeri bul
            left = i - 1
            while left >= 0 and not mask[left]: left -= 1
            right = i + 1
            while right < len(vals) and not mask[right]: right += 1
            
            if left >= 0 and right < len(vals):
                vals[i] = (vals[left] + vals[right]) / 2.0
            elif left >= 0:
                vals[i] = vals[left]
            elif right < len(vals):
                vals[i] = vals[right]

    # Savitzky-Golay (hassas geometrik yumuşatma)
    window_choice = int(window)
    if window_choice % 2 == 0: window_choice += 1
    if window_choice >= len(vals): window_choice = len(vals) if len(vals) % 2 == 1 else len(vals) - 1
    
    if window_choice < 5: return edge_array
        
    smoothed = signal.savgol_filter(vals, window_choice, polyorder)
    
    result = []
    for i, exists in enumerate(mask):
        result.append(float(smoothed[i]) if exists else None)
        
    return result


def edge_stabilize(edge_array: List[Optional[float]]) -> List[Optional[float]]:
    """
    Stabilizasyon katmanı: Median + Outlier Temizliği + Savitzky-Golay
    Ani sıçramaları (jitter) ve gürültüyü ciddi oranda azaltır.
    """
    if not edge_array or len(edge_array) < 10:
        return edge_array
        
    # 1. Ham median filtre (kaba gürültü)
    mask = [x is not None for x in edge_array]
    clean_vals = np.array([x if x is not None else 0 for x in edge_array], dtype=float)
    med_smoothed = ndimage.median_filter(clean_vals, size=5)
    
    # None'ları geri koy
    stage1 = [float(med_smoothed[i]) if mask[i] else None for i in range(len(edge_array))]
    
    # 2. Outlier Temizliği (medyandan aşırı sapanları buda)
    stage2 = _remove_outliers(stage1, window=9, threshold=1.25)
    
    # 3. Savitzky-Golay (hassas geometrik yumuşatma)
    stage3 = _savitzky_golay_smooth(stage2, window=9, polyorder=2)
    
    return stage3


def extract_profile(image: np.ndarray, params: Optional[Dict] = None) -> Dict:
    """
    Görüntüdeki silindirik parçanın profilini çıkarır.

    Adımlar:
    1. Gri tonlama + Gaussian blur
    2. Otsu threshold ile binary maske
    3. Morfolojik temizleme
    4. En büyük konturu bul (parça)
    5. Her x koordinatında üst ve alt kenarı bul
    6. Çap profili oluştur

    Returns:
        Dict: {
            "top_edge": [...],      # Her x için üst kenar y değeri
            "bottom_edge": [...],   # Her x için alt kenar y değeri
            "diameter_px": [...],   # Her x için çap (piksel)
            "center_y": [...],      # Her x için merkez y
            "x_start": int,         # Profilin başladığı x
            "x_end": int,           # Profilin bittiği x
            "contour": np.ndarray,  # Ana kontur
            "mask": np.ndarray,     # Binary maske
        }
    """
    params = params or {}
    blur_ksize = params.get("blur_ksize", 7)  # Gürültüye karşı varsayılan blur'u artırdık
    morph_ksize = params.get("morph_ksize", 7) # Sınırların daha iyi birleşmesi için artırıldı
    min_contour_area = params.get("min_contour_area", 5000)

    # 1. Gri tonlama ve parlaklık analizi
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()

    mean_brightness = float(np.mean(gray))
    is_edge_map = mean_brightness < 40  # Kenar haritası tespit eşiği

    if is_edge_map:
        # KENAR HARİTASI MODU (siyah zemin, beyaz çizgiler)
        # KRİTİK FIX: Kalibrasyon (detect_edges) ile AYNI algoritmayı kullanıyoruz
        # Böylece kalibrasyon ve ölçüm tutarlı sonuç verir
        
        # 1. Kernel boyutu - kalibrasyonla AYNI (morph_ksize + 2 YOK!)
        mk = morph_ksize if morph_ksize % 2 == 1 else morph_ksize + 1
        
        # 2. Dilate kullan - kalibrasyonla AYNI (GaussianBlur DEĞİL!)
        # app.py:437 ile tutarlı: cv2.dilate(gray, kernel, iterations=1)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        binary_dilated = cv2.dilate(gray, kernel, iterations=1)
        _, binary_edges = cv2.threshold(binary_dilated, 20, 255, cv2.THRESH_BINARY)
        
        # 3. İçi boş (sadece sınırları olan) haritadan solid maske üret
        h, w = binary_edges.shape
        solid_mask = np.zeros_like(binary_edges)
        for x in range(w):
            col = binary_edges[:, x]
            white_idx = np.where(col > 0)[0]
            if len(white_idx) > 0:
                y1 = white_idx[0]
                y2 = white_idx[-1]
                # En az birkaç piksel kalınlığında bir şekilse içini doldur
                if y2 - y1 > 5:
                    solid_mask[y1:y2+1, x] = 255
                    
        # 4. Morfolojik temizleme - kalibrasyonla tutarlı (daha az agresif)
        # iterations=1 kullan (kalibrasyonda morfoloji yok)
        kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        binary = cv2.morphologyEx(solid_mask, cv2.MORPH_CLOSE, kernel2, iterations=1)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel2, iterations=1)
    else:
        # NORMAL GÖRÜNTÜ MODU (Otsu Threshold ile solid maske)
        # Kernel boyutunu tek sayı yap - kalibrasyonla tutarlı
        blur_k = blur_ksize if blur_ksize % 2 == 1 else blur_ksize + 1
        mk = morph_ksize if morph_ksize % 2 == 1 else morph_ksize + 1
        
        blurred = cv2.GaussianBlur(gray, (blur_k, blur_k), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

        # Parlak/yansımalı yüzeylerde Otsu maskesi üst gövdeyi kaçırabildiği için
        # kenar destek haritası üret: kolon bazında maske çapı bariz kısa kalırsa
        # bu harita ile üst/alt kenarı düzelt.
        edge_blur = cv2.GaussianBlur(gray, (3, 3), 0)
        edge_support = cv2.Canny(edge_blur, 40, 120)
        edge_support = cv2.dilate(
            edge_support,
            cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)),
            iterations=1
        )

    # 4. Kontur bul
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("Parça konturu bulunamadı. Görüntü kalitesini kontrol edin.")

    # Alan filtresini daha agresif yap (gürültüyü önlemek için)
    # Eğer kullanıcı 100 gibi çok küçük bir değer gönderirse bile 
    # en büyük konturun %10'undan küçük olanları gürültü kabul et.
    all_areas = [cv2.contourArea(c) for c in contours]
    max_area = max(all_areas)
    dynamic_min_area = max(min_contour_area, max_area * 0.1)
    
    valid_contours = [c for c in contours if cv2.contourArea(c) >= dynamic_min_area]
    if not valid_contours:
        # Fallback: Sadece en büyüğü al
        valid_contours = [max(contours, key=cv2.contourArea)]

    # Metrologi tarafında ölçüm tek fiziksel parçadan alınmalı.
    # Bu yüzden maskeyi yalnızca ana konturdan üret; ek konturlar
    # ancak false positive riskini artırıyor.
    main_contour = max(valid_contours, key=cv2.contourArea)
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.drawContours(mask, [main_contour], -1, 255, cv2.FILLED)

    # x_start/x_end tespiti için sadece ana konturu kullan
    x_c, y_c, w_c, h_c = cv2.boundingRect(main_contour)
    x_start = x_c
    x_end = x_c + w_c
    bbox = (int(x_c), int(y_c), int(w_c), int(h_c))

    # ROI Band Sınırlaması (Kullanıcı parametresi)
    # Sadece fiziksel parçanın olması gereken y aralığında kenar ara
    roi_y_min = params.get("roi_y_min", 0)
    roi_y_max = params.get("roi_y_max", gray.shape[0])

    top_edge: List[Optional[float]] = []
    bottom_edge: List[Optional[float]] = []
    diameter_px: List[float] = []
    center_y_list: List[Optional[float]] = []

    edge_source = binary_edges if is_edge_map and 'binary_edges' in locals() else locals().get("edge_support")

    for x in range(x_start, x_end):
        # Kritik: Çapı kalibrasyonla aynı mantıkla ölç.
        # Kalibrasyonda bir kolondaki ilk/son beyaz piksel alınıyor.
        # Ölçümde de aynı yaklaşımı kullanıyoruz; kontur maskesi yalnızca x aralığını
        # belirlemek için kullanılıyor.
        col = binary[:, x]

        # ROI kısıtı uygula
        white_pixels = np.where((col > 0) & (np.arange(len(col)) >= roi_y_min) & (np.arange(len(col)) <= roi_y_max))[0]

        # Kaynak kolonda veri yoksa ana kontur maskesine fallback.
        if len(white_pixels) == 0:
            white_pixels = np.where(
                (mask[:, x] > 0)
                & (np.arange(mask.shape[0]) >= roi_y_min)
                & (np.arange(mask.shape[0]) <= roi_y_max)
            )[0]

        if len(white_pixels) == 0:
            top_edge.append(None)
            bottom_edge.append(None)
            diameter_px.append(0)
            center_y_list.append(None)
        else:
            top = int(white_pixels[0])
            bottom = int(white_pixels[-1])

            if edge_source is not None:
                edge_col = edge_source[:, x]
                top = _snap_edge_to_support(edge_col, top, search_radius=6, prefer="up")
                bottom = _snap_edge_to_support(edge_col, bottom, search_radius=6, prefer="down")

            # Alt-piksel hassasiyeti (Sub-pixel refinement)
            top_sub = _subpixel_edge_1d_polarity(gray[:, x], top, search_window=4, edge="top")
            bottom_sub = _subpixel_edge_1d_polarity(gray[:, x], bottom, search_window=4, edge="bottom")

            top_edge.append(top_sub)
            bottom_edge.append(bottom_sub)
            diameter_px.append(bottom_sub - top_sub)
            center_y_list.append((top_sub + bottom_sub) / 2.0)

    # Ölçüm verisi ham/sub-pixel kenar olarak korunur.
    # Overlay için ayrı, hafifçe stabilize edilmiş bir görünüm üret.
    top_edge_display = edge_stabilize(top_edge)
    bottom_edge_display = edge_stabilize(bottom_edge)

    center_y_display = []
    for t, b in zip(top_edge_display, bottom_edge_display):
        if t is not None and b is not None:
            center_y_display.append((t + b) / 2.0)
        else:
            center_y_display.append(None)

    return {
        "top_edge": top_edge,
        "bottom_edge": bottom_edge,
        "diameter_px": diameter_px,
        "center_y": center_y_list,
        "overlay_top_edge": top_edge_display,
        "overlay_bottom_edge": bottom_edge_display,
        "overlay_center_y": center_y_display,
        "x_start": x_start,
        "x_end": x_end,
        "contour": main_contour,
        "mask": mask,
        "bbox": bbox,
    }


def draw_profile_overlay(image: np.ndarray, profile: Dict, calibration_ppmm: float = 1.0,
                          sections: Optional[List] = None,
                          matched_features: Optional[List[Dict]] = None,
                          point_measurements: Optional[List[Dict]] = None) -> np.ndarray:
    """
    Profil verilerini ve ölçüm çizgilerini görüntü üzerine çizer.

    Args:
        image: Orijinal görüntü
        profile: extract_profile() çıktısı
        calibration_ppmm: Piksel/mm oranı
        sections: Bölüm bilgileri (measurement_engine çıktısı)
        matched_features: Golden mod eşleşmiş feature listesi (opsiyonel)
        point_measurements: Noktasal ölçüm listesi (opsiyonel)
    """
    overlay = image.copy()
    x_start = profile["x_start"]
    top_edge = profile.get("overlay_top_edge", profile["top_edge"])
    bottom_edge = profile.get("overlay_bottom_edge", profile["bottom_edge"])

    # Üst ve alt kenar çizgileri (yeşil)
    for i in range(len(top_edge) - 1):
        if top_edge[i] is not None and top_edge[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(round(top_edge[i]))),
                     (x_start + i + 1, int(round(top_edge[i + 1]))),
                     (0, 255, 0), 1, cv2.LINE_AA)
        if bottom_edge[i] is not None and bottom_edge[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(round(bottom_edge[i]))),
                     (x_start + i + 1, int(round(bottom_edge[i + 1]))),
                     (0, 255, 0), 1, cv2.LINE_AA)

    # Merkez çizgisi (mavi, kesikli)
    center_y = profile.get("overlay_center_y", profile["center_y"])
    for i in range(0, len(center_y) - 1, 4):
        if center_y[i] is not None and center_y[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(round(center_y[i]))),
                     (x_start + i + 1, int(round(center_y[i + 1]))),
                     (255, 165, 0), 1, cv2.LINE_AA)

    # Bölüm ayraç çizgileri (kesikli gri dikey çizgiler) ve bölüm çapları
    if sections is not None:
        for sec in sections:
            sx = sec["x_start_abs"]
            ex = sec["x_end_abs"]
            for draw_x in [sx, ex]:
                for y in range(0, overlay.shape[0], 8):
                    cv2.line(overlay, (draw_x, y), (draw_x, min(y + 4, overlay.shape[0])), (100, 100, 100), 1)

            top_y = sec.get("top_y_at_mid")
            bottom_y = sec.get("bottom_y_at_mid")
            if top_y is None or bottom_y is None:
                continue

            mid_x = int(round((sx + ex) / 2.0))
            ity = int(round(top_y))
            iby = int(round(bottom_y))
            color = (0, 255, 0)

            cv2.line(overlay, (mid_x, ity), (mid_x, iby), color, 2, cv2.LINE_AA)
            cv2.arrowedLine(overlay, (mid_x, (ity + iby) // 2), (mid_x, ity), color, 2, tipLength=0.06)
            cv2.arrowedLine(overlay, (mid_x, (ity + iby) // 2), (mid_x, iby), color, 2, tipLength=0.06)

            if sec.get("diameter_mm") is not None:
                label = f"{float(sec['diameter_mm']):.2f}"
                text_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                tx = mid_x - text_size[0] // 2
                ty = max(20, ity - 12)
                cv2.putText(overlay, label, (tx + 1, ty + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(overlay, label, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    # Golden feature etiketleri (opsiyonel)
    if matched_features:
        for f in matched_features:
            if not f or not f.get("found"):
                continue
            fid = str(f.get("id"))
            ftype = f.get("type")
            xs_val = f.get("x_start_abs")
            xe_val = f.get("x_end_abs")
            if xs_val is None or xe_val is None:
                continue

            mid_x = int(f.get("mid_x") or ((int(xs_val) + int(xe_val)) // 2))
            label = f"{'D' if ftype == 'diameter' else 'L'}{fid.zfill(2)}"

            if ftype == "diameter":
                top_y = f.get("top_y")
                bot_y = f.get("bottom_y")
                if top_y is None or bot_y is None:
                    continue
                # Çap etiketi (sarı ve ortalı)
                d_label = f"cap: {f.get('measured_mm', 0):.2f}"
                d_size, _ = cv2.getTextSize(d_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                cv2.putText(
                    overlay, d_label,
                    (mid_x - d_size[0] // 2, max(0, int(round(float(top_y))) - 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 255), 2, cv2.LINE_AA
                )
            else:
                # Uzunluk için segment sınırlarını hafif vurgula + etiket
                y = overlay.shape[0] - 12
                # Uzunluk etiketi (açık yeşil/sarı ve ortalı)
                l_label = f"uzunluk: {f.get('measured_mm', 0):.2f}"
                l_size, _ = cv2.getTextSize(l_label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
                y = overlay.shape[0] - 15
                cv2.putText(
                    overlay, l_label,
                    (mid_x - l_size[0] // 2, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 255), 2, cv2.LINE_AA
                )

    # Noktasal ölçümleri çiz (Mavi dikey oklar)
    if point_measurements:
        for p in point_measurements:
            px = p["x_abs"]
            ty = int(round(p["top_y"]))
            by = int(round(p["bottom_y"]))
            val = p["diameter_mm"]
            
            color = (255, 100, 0) # Mavi tonu
            # Dikey çizgi
            cv2.line(overlay, (px, ty), (px, by), color, 2)
            # Ok uçları
            cv2.arrowedLine(overlay, (px, (ty + by) // 2), (px, ty), color, 2, tipLength=0.1)
            cv2.arrowedLine(overlay, (px, (ty + by) // 2), (px, by), color, 2, tipLength=0.1)
            
            # Etiket
            label = f"P{p['id']}: {val:.2f}"
            cv2.putText(overlay, label, (px + 5, ty - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2, cv2.LINE_AA)

    return overlay
