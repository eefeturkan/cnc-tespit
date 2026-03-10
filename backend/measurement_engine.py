"""
CNC Parça Ölçüm Sistemi — Ölçüm Motoru
Çap profil verisinden bölüm tespiti, çap ve uzunluk hesaplama.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from calibration import CalibrationProfile


def detect_sections(profile: Dict, calibration: CalibrationProfile,
                    min_section_width_px: int = 20,
                    gradient_threshold: float = 2.0) -> List[Dict]:
    """
    Çap profilindeki bölümleri (sabit çap bölgeleri) tespit eder.

    Yöntem:
    1. Çap profilinin türevini al
    2. Türevdeki büyük sıçramalar = bölüm geçişleri
    3. Her düz bölge = bir bölüm
    4. Her bölümün ortalama çapını ve uzunluğunu hesapla

    Args:
        profile: profile_extractor.extract_profile() çıktısı
        calibration: Kalibrasyon profili
        min_section_width_px: Minimum bölüm genişliği (piksel)
        gradient_threshold: Bölüm geçiş eşiği (piksel/kolon)

    Returns:
        Bölüm listesi (her biri dict)
    """
    diameter_px = np.array(profile["diameter_px"], dtype=float)
    top_edge = profile["top_edge"]
    bottom_edge = profile["bottom_edge"]
    x_start = profile["x_start"]

    # None değerleri 0 ile değiştir
    diameter_px = np.nan_to_num(diameter_px, nan=0.0)

    # Kısa bir median filtre ile gürültüyü temizle
    if len(diameter_px) > 5:
        from scipy.ndimage import median_filter
        diameter_smooth = median_filter(diameter_px, size=7)
    else:
        diameter_smooth = diameter_px.copy()

    # Türev hesapla
    gradient = np.gradient(diameter_smooth)

    # Bölüm geçiş noktalarını bul
    transitions = []
    transitions.append(0)  # Başlangıç

    for i in range(1, len(gradient)):
        if abs(gradient[i]) > gradient_threshold:
            # Önceki geçişten yeterli uzaklıkta mı?
            if len(transitions) == 0 or (i - transitions[-1]) > min_section_width_px // 2:
                transitions.append(i)

    transitions.append(len(diameter_px))  # Bitiş

    # Geçişleri temizle — çok yakın olanları birleştir
    clean_transitions = [transitions[0]]
    for t in transitions[1:]:
        if t - clean_transitions[-1] >= min_section_width_px:
            clean_transitions.append(t)
        else:
            clean_transitions[-1] = t  # İleriyi al
    if clean_transitions[-1] != len(diameter_px):
        clean_transitions.append(len(diameter_px))

    # Bölüm bilgilerini hesapla
    sections = []
    section_num = 1

    for i in range(len(clean_transitions) - 1):
        s = clean_transitions[i]
        e = clean_transitions[i + 1]

        if e - s < min_section_width_px:
            continue

        # Bölüm çap değerleri
        seg_diameters = diameter_px[s:e]
        valid_diameters = seg_diameters[seg_diameters > 0]

        if len(valid_diameters) == 0:
            continue

        # İstatistikler
        avg_diameter_px = float(np.median(valid_diameters))
        std_diameter_px = float(np.std(valid_diameters))
        width_px = e - s

        # mm'ye çevir — çap Y-ekseni, uzunluk X-ekseni kalibrasyonu kullanır
        diameter_mm = calibration.pixels_to_mm_y(avg_diameter_px)
        length_mm = calibration.pixels_to_mm_x(width_px)

        # Orta noktadaki üst/alt kenar
        mid_idx = (s + e) // 2
        top_y_at_mid = top_edge[mid_idx] if mid_idx < len(top_edge) and top_edge[mid_idx] is not None else None
        bot_y_at_mid = bottom_edge[mid_idx] if mid_idx < len(bottom_edge) and bottom_edge[mid_idx] is not None else None

        # Merkez y
        center_y_values = [profile["center_y"][j] for j in range(s, e) if j < len(profile["center_y"]) and profile["center_y"][j] is not None]
        center_y = float(np.mean(center_y_values)) if center_y_values else None

        sections.append({
            "section_id": section_num,
            "x_start_rel": s,
            "x_end_rel": e,
            "x_start_abs": x_start + s,
            "x_end_abs": x_start + e,
            "width_px": width_px,
            "avg_diameter_px": round(avg_diameter_px, 2),
            "std_diameter_px": round(std_diameter_px, 2),
            "diameter_mm": round(diameter_mm, 4),
            "length_mm": round(length_mm, 4),
            "top_y_at_mid": top_y_at_mid,
            "bottom_y_at_mid": bot_y_at_mid,
            "center_y": center_y,
        })

        section_num += 1

    return sections


def _pick_change_points(gradient_abs: np.ndarray, k: int, min_distance: int) -> List[int]:
    """
    En yüksek |gradient| noktalarından k adet değişim noktası seç (non-max suppression).
    Dönen indeksler 1..len-2 aralığında olur (0 ve len dahil edilmez).
    """
    if k <= 0:
        return []
    if len(gradient_abs) < 3:
        return []

    # Adayları büyükten küçüğe sırala
    candidates = np.argsort(-gradient_abs)
    picked: List[int] = []
    for idx in candidates:
        i = int(idx)
        if i <= 0 or i >= len(gradient_abs) - 1:
            continue
        if any(abs(i - p) < min_distance for p in picked):
            continue
        picked.append(i)
        if len(picked) >= k:
            break
    return sorted(picked)


def _segments_from_points(n: int, points: List[int]) -> List[Tuple[int, int]]:
    """0..n aralığını (exclusive end) noktalarla segmentlere ayır."""
    pts = [0] + sorted([p for p in points if 0 < p < n]) + [n]
    segs = []
    for a, b in zip(pts[:-1], pts[1:]):
        if b > a:
            segs.append((a, b))
    return segs


def detect_sections_golden(
    profile: Dict,
    calibration: CalibrationProfile,
    layout: Dict,
    min_section_width_px: int = 20,
    gradient_threshold: float = 2.0,
) -> Dict:
    """
    Golden (referans layout) ile sabit sayıda feature üretir.

    MVP yaklaşımı:
    - diameter_px sinyalinden |gradient| tepe noktaları ile K adet sınır seçilir.
    - Bu sınırlar ile K+1 segment oluşturulur.
    - Layout'taki diameter feature sayısı kadar segment üretilir (gerekirse kısaltılır).
    - Length feature'lar segment genişliklerinden (soldan sağa) üretilir.

    Returns:
      {
        "segments": [...],  # internal segment list (abs/rel)
        "matched_features": [...], # layout id'leriyle eşleştirilmiş
      }
    """
    features = (layout or {}).get("features", [])
    if not features:
        raise ValueError("Golden layout boş: features bulunamadı")

    diameter_ids = [f for f in features if f.get("type") == "diameter"]
    length_ids = [f for f in features if f.get("type") == "length"]
    if len(diameter_ids) < 1:
        raise ValueError("Golden layout'ta en az 1 diameter feature olmalı")

    diameter_px = np.array(profile["diameter_px"], dtype=float)
    diameter_px = np.nan_to_num(diameter_px, nan=0.0)
    x_start_abs = int(profile["x_start"])
    top_edge = profile["top_edge"]
    bottom_edge = profile["bottom_edge"]

    # Smooth + gradient
    if len(diameter_px) > 5:
        from scipy.ndimage import median_filter
        diameter_smooth = median_filter(diameter_px, size=7)
    else:
        diameter_smooth = diameter_px.copy()
    grad = np.gradient(diameter_smooth)
    grad_abs = np.abs(grad)

    # Eğer gradient threshold çok küçük/çok büyük ise, yine de tepe noktası seçebilmek için
    # threshold altı değerleri sıfıra yakınlaştır (sadece sıralama için)
    grad_abs = np.where(grad_abs >= float(gradient_threshold), grad_abs, grad_abs * 0.25)

    # K boundary => K+1 segment, burada segment sayısı = diameter feature sayısı hedefleniyor.
    target_segments = len(diameter_ids)
    k = max(0, target_segments - 1)
    min_dist = max(1, int(min_section_width_px))
    change_points = _pick_change_points(grad_abs, k=k, min_distance=min_dist)
    segs_rel = _segments_from_points(len(diameter_px), change_points)

    # Çok az segment çıktıysa (gradient çok zayıf), eşit aralıklı böl.
    if len(segs_rel) < target_segments and len(diameter_px) > target_segments:
        step = len(diameter_px) // target_segments
        pts = [i * step for i in range(1, target_segments)]
        segs_rel = _segments_from_points(len(diameter_px), pts)

    # Fazla segment çıktıysa (nadir), en büyük segmentleri tut (sıra korunur)
    if len(segs_rel) > target_segments:
        # Skor: segment uzunluğu; en büyükleri seç ama sıralı kalsın
        lengths = np.array([b - a for a, b in segs_rel], dtype=int)
        keep_idx = set(np.argsort(-lengths)[:target_segments].tolist())
        segs_rel = [segs_rel[i] for i in range(len(segs_rel)) if i in keep_idx]
        segs_rel = sorted(segs_rel, key=lambda t: t[0])

    # Segment metrikleri
    segments = []
    for (s, e) in segs_rel:
        seg_d = diameter_px[s:e]
        valid_d = seg_d[seg_d > 0]
        avg_d_px = float(np.median(valid_d)) if len(valid_d) else 0.0
        std_d_px = float(np.std(valid_d)) if len(valid_d) else 0.0
        width_px = int(e - s)
        mid_idx = int((s + e) // 2)
        top_y = top_edge[mid_idx] if mid_idx < len(top_edge) and top_edge[mid_idx] is not None else None
        bot_y = bottom_edge[mid_idx] if mid_idx < len(bottom_edge) and bottom_edge[mid_idx] is not None else None
        segments.append({
            "x_start_rel": int(s),
            "x_end_rel": int(e),
            "x_start_abs": int(x_start_abs + s),
            "x_end_abs": int(x_start_abs + e),
            "width_px": width_px,
            "avg_diameter_px": round(avg_d_px, 2),
            "std_diameter_px": round(std_d_px, 2),
            "diameter_mm": round(calibration.pixels_to_mm_y(avg_d_px), 4) if avg_d_px > 0 else 0.0,
            "length_mm": round(calibration.pixels_to_mm_x(width_px), 4) if width_px > 0 else 0.0,
            "top_y_at_mid": top_y,
            "bottom_y_at_mid": bot_y,
        })

    # Layout order'a göre eşleştir (MVP: diameter segmentleri soldan sağa)
    diameter_ids_sorted = sorted(diameter_ids, key=lambda f: int(f.get("order", 0)))
    length_ids_sorted = sorted(length_ids, key=lambda f: int(f.get("order", 0)))

    matched_features = []
    for i, feat in enumerate(diameter_ids_sorted):
        if i >= len(segments):
            matched_features.append({
                "id": feat.get("id"),
                "type": "diameter",
                "found": False,
            })
            continue
        seg = segments[i]
        matched_features.append({
            "id": feat.get("id"),
            "type": "diameter",
            "found": True,
            "x_start_abs": seg["x_start_abs"],
            "x_end_abs": seg["x_end_abs"],
            "mid_x": int((seg["x_start_abs"] + seg["x_end_abs"]) // 2),
            "top_y": seg["top_y_at_mid"],
            "bottom_y": seg["bottom_y_at_mid"],
            "measured_mm": seg["diameter_mm"],
            "measured_px": seg["avg_diameter_px"],
            "std_px": seg["std_diameter_px"],
        })

    # Length feature üretimi (MVP): segment genişlikleri üzerinden
    for j, feat in enumerate(length_ids_sorted):
        if j >= len(segments):
            matched_features.append({
                "id": feat.get("id"),
                "type": "length",
                "found": False,
            })
            continue
        seg = segments[j]
        matched_features.append({
            "id": feat.get("id"),
            "type": "length",
            "found": True,
            "x_start_abs": seg["x_start_abs"],
            "x_end_abs": seg["x_end_abs"],
            "measured_mm": seg["length_mm"],
            "measured_px": seg["width_px"],
        })

    return {"segments": segments, "matched_features": matched_features}


def generate_measurement_table(sections: List[Dict]) -> List[Dict]:
    """
    Bölüm verisinden VICIVISION benzeri ölçüm tablosu oluşturur.

    Returns:
        Tablo satırları listesi
    """
    rows = []
    for sec in sections:
        # Çap satırı
        rows.append({
            "id": f"D{sec['section_id']:02d}",
            "type": "Çap",
            "description": f"Ø Bölüm {sec['section_id']}",
            "nominal_mm": sec["diameter_mm"],
            "measured_mm": sec["diameter_mm"],
            "deviation_mm": 0.0,
            "section_id": sec["section_id"],
        })
        # Uzunluk satırı
        rows.append({
            "id": f"L{sec['section_id']:02d}",
            "type": "Uzunluk",
            "description": f"Boy Bölüm {sec['section_id']}",
            "nominal_mm": sec["length_mm"],
            "measured_mm": sec["length_mm"],
            "deviation_mm": 0.0,
            "section_id": sec["section_id"],
        })

    return rows


def get_measurement_summary(sections: List[Dict]) -> Dict:
    """Genel ölçüm özeti."""
    if not sections:
        return {"total_sections": 0}

    diameters = [s["diameter_mm"] for s in sections]
    lengths = [s["length_mm"] for s in sections]

    return {
        "total_sections": len(sections),
        "min_diameter_mm": round(min(diameters), 4),
        "max_diameter_mm": round(max(diameters), 4),
        "total_length_mm": round(sum(lengths), 4),
        "sections": sections,
    }
