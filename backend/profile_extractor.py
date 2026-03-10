"""
CNC Parça Ölçüm Sistemi — Profil Çıkarıcı
Parçanın silüetinden profil verisi (üst/alt kenar, çap profili) çıkarır.
"""

import cv2
import numpy as np
from typing import Dict, List, Tuple, Optional


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
        # ÖNEMLİ: Kalibrasyon (detect_edges) ile AYNI algoritmayı kullanıyoruz
        # Böylece kalibrasyon ve ölçüm tutarlı sonuç verir
        
        # 1. Kernel boyutu - kalibrasyonla aynı
        mk = morph_ksize if morph_ksize % 2 == 1 else morph_ksize + 1
        
        # 2. Dilate kullan - kalibrasyonla AYNI (blur değil!)
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
            top_edge.append(top)
            bottom_edge.append(bottom)
            diameter_px.append(bottom - top)
            center_y_list.append((top + bottom) / 2.0)

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
                     (x_start + i, top_edge[i]),
                     (x_start + i + 1, top_edge[i + 1]),
                     (0, 255, 0), 1)
        if bottom_edge[i] is not None and bottom_edge[i + 1] is not None:
            cv2.line(overlay,
                     (x_start + i, bottom_edge[i]),
                     (x_start + i + 1, bottom_edge[i + 1]),
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
                cv2.line(overlay, (mid_x, top_y), (mid_x, bot_y), (0, 0, 255), 2)
                # Çap ok uçları
                cv2.arrowedLine(overlay, (mid_x, int((top_y + bot_y)/2)), (mid_x, top_y), (0, 0, 255), 2, tipLength=0.05)
                cv2.arrowedLine(overlay, (mid_x, int((top_y + bot_y)/2)), (mid_x, bot_y), (0, 0, 255), 2, tipLength=0.05)

            # Çap etiketi
            diameter_mm = sec.get("diameter_mm", 0)
            label = f"D{diameter_mm:.2f}"
            label_x = mid_x + 8
            label_y = top_y - 10 if top_y is not None else sec.get("center_y", 0)
            cv2.putText(overlay, label, (label_x, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA)

            # Uzunluk etiketi (alt kısmına yaz)
            length_mm = sec.get("length_mm", 0)
            if length_mm > 0:
                length_label = f"L{length_mm:.2f}"
                ly = bot_y + 20 if bot_y is not None else 0
                cv2.putText(overlay, length_label, (mid_x - 15, ly),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 255, 100), 1, cv2.LINE_AA)

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
                cv2.putText(
                    overlay, label,
                    (mid_x + 8, max(0, int(top_y) - 14)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 220, 255), 2, cv2.LINE_AA
                )
            else:
                # Uzunluk için segment sınırlarını hafif vurgula + etiket
                y = overlay.shape[0] - 12
                cv2.putText(
                    overlay, label,
                    (mid_x - 14, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (180, 255, 180), 2, cv2.LINE_AA
                )

    return overlay
