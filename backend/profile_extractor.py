"""
CNC Parça Ölçüm Sistemi — Profil Çıkarıcı
Parçanın silüetinden profil verisi (üst/alt kenar, çap profili) çıkarır.
"""

import cv2
import numpy as np
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
        
    d = 0.5 * (g_minus - g_plus) / denom
    d = max(-1.0, min(1.0, d))
    
    return float(best_y) + d


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
    blur_ksize = params.get("blur_ksize", 5)
    morph_ksize = params.get("morph_ksize", 5)
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

    # Alan filtresi
    valid_contours = [c for c in contours if cv2.contourArea(c) >= min_contour_area]
    if not valid_contours:
        raise ValueError(f"Yeterince büyük kontur bulunamadı (min alan: {min_contour_area} px²)")

    # Parlak yüzeyli metal parçalarda gövde bazen birden çok kontura ayrılabiliyor.
    # Sadece en büyük konturu almak "yarım profil" hatasına yol açtığı için
    # geçerli tüm konturları birleştirip tek maske üzerinde profil çıkarıyoruz.
    main_contour = max(valid_contours, key=cv2.contourArea)
    mask = np.zeros(gray.shape, dtype=np.uint8)
    cv2.drawContours(mask, valid_contours, -1, 255, cv2.FILLED)

    # Birleşik maskeden bbox hesapla
    cols_with_data = np.where(np.any(mask > 0, axis=0))[0]
    rows_with_data = np.where(np.any(mask > 0, axis=1))[0]
    if len(cols_with_data) == 0 or len(rows_with_data) == 0:
        raise ValueError("Parça maskesi oluşturulamadı. Görüntü kalitesini kontrol edin.")

    x_start = int(cols_with_data[0])
    x_end = int(cols_with_data[-1]) + 1  # python range için exclusive üst sınır
    y_start = int(rows_with_data[0])
    y_end = int(rows_with_data[-1]) + 1
    bbox_w = x_end - x_start
    bbox_h = y_end - y_start
    bbox = (x_start, y_start, bbox_w, bbox_h)

    top_edge = []
    bottom_edge = []
    diameter_px = []
    center_y_list = []

    for x in range(x_start, x_end):
        # Kritik: Çapı kalibrasyonla aynı mantıkla ölç.
        # Kalibrasyonda bir kolondaki ilk/son beyaz piksel alınıyor.
        # Ölçümde de aynı yaklaşımı kullanıyoruz; kontur maskesi yalnızca x aralığını
        # belirlemek için kullanılıyor.
        if is_edge_map and 'binary_edges' in locals():
            col = binary_edges[:, x]
        else:
            col = binary[:, x]

        white_pixels = np.where(col > 0)[0]

        # Kaynak kolonda veri yoksa birleşik kontur maskesine fallback.
        if len(white_pixels) == 0:
            white_pixels = np.where(mask[:, x] > 0)[0]

        if len(white_pixels) == 0:
            top_edge.append(None)
            bottom_edge.append(None)
            diameter_px.append(0)
            center_y_list.append(None)
        else:
            top = int(white_pixels[0])
            bottom = int(white_pixels[-1])

            # Alt-piksel hassasiyeti (Sub-pixel refinement)
            top_sub = _subpixel_edge_1d(gray[:, x], top)
            bottom_sub = _subpixel_edge_1d(gray[:, x], bottom)

            top_edge.append(top_sub)
            bottom_edge.append(bottom_sub)
            diameter_px.append(bottom_sub - top_sub)
            center_y_list.append((top_sub + bottom_sub) / 2.0)

    return {
        "top_edge": top_edge,
        "bottom_edge": bottom_edge,
        "diameter_px": diameter_px,
        "center_y": center_y_list,
        "x_start": x_start,
        "x_end": x_end,
        "contour": main_contour,
        "mask": mask,
        "bbox": bbox,
    }


def draw_profile_overlay(image: np.ndarray, profile: Dict, calibration_ppmm: float = 1.0,
                          sections: Optional[List] = None,
                          matched_features: Optional[List[Dict]] = None) -> np.ndarray:
    """
    Profil verilerini ve ölçüm çizgilerini görüntü üzerine çizer.

    Args:
        image: Orijinal görüntü
        profile: extract_profile() çıktısı
        calibration_ppmm: Piksel/mm oranı
        sections: Bölüm bilgileri (measurement_engine çıktısı)
        matched_features: Golden mod eşleşmiş feature listesi (opsiyonel)
    """
    overlay = image.copy()
    x_start = profile["x_start"]
    top_edge = profile["top_edge"]
    bottom_edge = profile["bottom_edge"]

    # Üst ve alt kenar çizgileri (yeşil)
    for i in range(len(top_edge) - 1):
        if top_edge[i] is not None and top_edge[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(top_edge[i])),
                     (x_start + i + 1, int(top_edge[i + 1])),
                     (0, 255, 0), 1)
        if bottom_edge[i] is not None and bottom_edge[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(bottom_edge[i])),
                     (x_start + i + 1, int(bottom_edge[i + 1])),
                     (0, 255, 0), 1)

    # Merkez çizgisi (mavi, kesikli)
    center_y = profile["center_y"]
    for i in range(0, len(center_y) - 1, 4):
        if center_y[i] is not None and center_y[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, int(center_y[i])),
                     (x_start + i + 1, int(center_y[i + 1])),
                     (255, 165, 0), 1)

    # Bölüm ölçüm çizgileri
    if sections:
        for sec in sections:
            sx = sec["x_start_abs"]
            ex = sec["x_end_abs"]
            mid_x = (sx + ex) // 2

            # Çap ölçüm çizgisi (kırmızı dikey)
            top_y = sec.get("top_y_at_mid")
            bot_y = sec.get("bottom_y_at_mid")
            if top_y is not None and bot_y is not None:
                ity = int(top_y)
                iby = int(bot_y)
                cv2.line(overlay, (mid_x, ity), (mid_x, iby), (0, 0, 255), 2)
                # Çap ok uçları
                cv2.arrowedLine(overlay, (mid_x, int((ity + iby)/2)), (mid_x, ity), (0, 0, 255), 2, tipLength=0.05)
                cv2.arrowedLine(overlay, (mid_x, int((ity + iby)/2)), (mid_x, iby), (0, 0, 255), 2, tipLength=0.05)

            # Çap ve Uzunluk etiketlerini merkeze yaz (Mockup'taki gibi sarı ve ortalı)
            diameter_mm = sec.get("diameter_mm", 0)
            length_mm = sec.get("length_mm", 0)
            
            if top_y is not None and bot_y is not None:
                mid_y = (ity + iby) // 2
                
                # Etiket metinleri
                d_label = f"cap: {diameter_mm:.2f}"
                l_label = f"uzunluk: {length_mm:.2f}"
                
                font = cv2.FONT_HERSHEY_SIMPLEX
                font_scale = 0.5
                thickness = 2
                color = (0, 255, 255)  # Sarı
                
                # Çap etiketini ortala
                d_size, _ = cv2.getTextSize(d_label, font, font_scale, thickness)
                d_x = mid_x - d_size[0] // 2
                d_y = mid_y - 5  # Merkezin biraz üstü
                
                # Uzunluk etiketini ortala
                l_size, _ = cv2.getTextSize(l_label, font, font_scale, thickness)
                l_x = mid_x - l_size[0] // 2
                l_y = mid_y + 15 # Merkezin biraz altı
                
                # Arka plan için hafif gölge (okunabilirlik için)
                cv2.putText(overlay, d_label, (d_x + 1, d_y + 1), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
                cv2.putText(overlay, l_label, (l_x + 1, l_y + 1), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
                
                # Ana metinler
                cv2.putText(overlay, d_label, (d_x, d_y), font, font_scale, color, thickness, cv2.LINE_AA)
                cv2.putText(overlay, l_label, (l_x, l_y), font, font_scale, color, thickness, cv2.LINE_AA)

            # Bölüm ayraç çizgileri (beyaz dikey kesikli)
            for draw_x in [sx, ex]:
                for y in range(0, overlay.shape[0], 8):
                    cv2.line(overlay, (draw_x, y), (draw_x, min(y + 4, overlay.shape[0])), (100, 100, 100), 1)

    # Golden feature etiketleri (opsiyonel)
    if matched_features:
        for f in matched_features:
            if not f or not f.get("found"):
                continue
            fid = str(f.get("id"))
            ftype = f.get("type")
            xs = f.get("x_start_abs")
            xe = f.get("x_end_abs")
            if xs is None or xe is None:
                continue

            mid_x = int(f.get("mid_x") or ((int(xs) + int(xe)) // 2))
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
                    (mid_x - d_size[0] // 2, max(0, int(top_y) - 15)),
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

    return overlay
