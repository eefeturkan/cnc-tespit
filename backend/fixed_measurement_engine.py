"""
Sabit Ölçüm Noktaları Motoru v2.0 — Bölüm Tabanlı (Section-Based)

Teknik çizimdeki sabit ölçüm noktalarını, otomatik tespit edilen profil bölümlerine
eşleyerek ölçüm yapar. x_position_mm yerine section_index kullanır.

Çap ölçümleri: Bölümün merkez bölgesindeki medyan çap
Uzunluk ölçümleri: Bölüm sınırları arası piksel mesafeden X kalibrasyonu ile mm

Bu yaklaşım kamera pozisyonu, zoom ve ROI değişikliklerine dayanıklıdır.
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict


@dataclass
class MeasurementResult:
    """Ölçüm sonucu veri yapısı"""
    code: str
    measurement_type: str  # 'diameter', 'length'
    method: str            # ölçüm yöntemi
    nominal_mm: float
    measured_mm: float
    deviation_mm: float
    lower_tol_mm: float
    upper_tol_mm: float
    min_limit_mm: float
    max_limit_mm: float
    status: str  # "PASS" veya "FAIL"
    description: str
    unit: str
    section_info: str  # hangi bölümden ölçüldüğünü açıklar
    x_pixel_start: Optional[int] = None  # overlay çizimi için
    x_pixel_end: Optional[int] = None
    top_y: Optional[float] = None
    bottom_y: Optional[float] = None
    x_abs: Optional[int] = None  # İnce ayar için ham değer
    x_mode: Optional[str] = None
    x_used_abs: Optional[int] = None
    x_used_rel: Optional[int] = None
    snap_offset_px: Optional[int] = None
    raw_diameter_px: Optional[float] = None
    raw_length_px: Optional[float] = None
    section_index: Optional[int] = None


class FixedMeasurementEngine:
    """
    Bölüm tabanlı sabit ölçüm motoru.
    
    Parça profilinden bölüm tespiti yapılır, ardından her ölçüm noktası
    template'deki section_index ile ilgili bölüme eşlenir.
    """
    
    def __init__(self, template_path: Optional[str] = None):
        self.template = None
        self.measurement_points = []
        
        if template_path:
            self.load_template(template_path)
    
    def load_template(self, template_path: str) -> bool:
        """JSON şablon dosyasını yükler."""
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                self.template = json.load(f)
            self.measurement_points = self.template.get('measurement_points', [])
            return True
        except Exception as e:
            print(f"Şablon yükleme hatası: {e}")
            return False

    @staticmethod
    def _find_runs(mask: np.ndarray, start: int, end: int) -> List[Tuple[int, int]]:
        """[start, end) aralığındaki True segmentlerini döndür."""
        runs: List[Tuple[int, int]] = []
        run_start: Optional[int] = None
        for idx in range(start, end):
            if mask[idx]:
                if run_start is None:
                    run_start = idx
            elif run_start is not None:
                runs.append((run_start, idx))
                run_start = None
        if run_start is not None:
            runs.append((run_start, end))
        return runs

    def _pick_stable_diameter_band(
        self,
        diameter_px_arr: np.ndarray,
        x_rel: int,
        sample_width_px: int,
        search_radius_px: int,
    ) -> Tuple[int, int, int]:
        """
        Beklenen X civarında en stabil düz çap bandını seç.

        Returns:
            (band_start_rel, band_end_rel, used_x_rel)
        """
        if len(diameter_px_arr) == 0:
            return 0, 0, 0

        # Gerçek "sabit nokta" ölçümünde kullanıcı verilen X çevresindeki küçük
        # pencerenin ölçülmesini bekliyor. search_radius=0 ise band arama yapma;
        # yalnızca istenen X ± sample_width aralığını kullan.
        if search_radius_px <= 0:
            band_start = max(0, x_rel - sample_width_px)
            band_end = min(len(diameter_px_arr), x_rel + sample_width_px + 1)
            if band_end <= band_start:
                band_end = min(len(diameter_px_arr), band_start + 1)
            return band_start, band_end, int(np.clip(x_rel, band_start, max(band_start, band_end - 1)))

        valid_mask = diameter_px_arr > 0
        start = max(0, x_rel - search_radius_px)
        end = min(len(diameter_px_arr), x_rel + search_radius_px + 1)
        if end <= start:
            return x_rel, min(len(diameter_px_arr), x_rel + 1), x_rel

        from scipy.ndimage import median_filter

        smooth = median_filter(diameter_px_arr.astype(float), size=3)
        grad_abs = np.abs(np.gradient(smooth))

        local_grad = grad_abs[start:end][valid_mask[start:end]]
        base_grad = float(np.median(local_grad)) if len(local_grad) else 0.0
        stability_threshold = max(0.35, base_grad * 2.5)

        stable_mask = valid_mask & (grad_abs <= stability_threshold)
        all_runs = self._find_runs(stable_mask, 0, len(diameter_px_arr))
        runs = [run for run in all_runs if run[1] > start and run[0] < end]

        if not runs:
            band_start = max(0, x_rel - sample_width_px)
            band_end = min(len(diameter_px_arr), x_rel + sample_width_px + 1)
            return band_start, band_end, int(np.clip(x_rel, band_start, max(band_start, band_end - 1)))

        scored_runs = []
        for run_start, run_end in runs:
            safe_start = run_start
            safe_end = run_end

            if (safe_end - safe_start) > (2 * sample_width_px + 1):
                safe_start += sample_width_px
                safe_end -= sample_width_px

            if safe_end <= safe_start:
                safe_start, safe_end = run_start, run_end

            clamped_x = int(np.clip(x_rel, safe_start, max(safe_start, safe_end - 1)))
            contains = safe_start <= x_rel < safe_end
            distance = abs(clamped_x - x_rel)
            span = safe_end - safe_start
            score = (distance * 2.0) - min(span, 40)
            scored_runs.append((contains, score, distance, -span, safe_start, safe_end, clamped_x))

        containing_runs = [r for r in scored_runs if r[0]]
        if containing_runs:
            _, _, _, _, band_start, band_end, used_x = min(containing_runs, key=lambda r: (r[2], r[3]))
        else:
            _, _, _, _, band_start, band_end, used_x = min(scored_runs, key=lambda r: (r[1], r[2], r[3]))
        return band_start, band_end, used_x

    @staticmethod
    def _evaluate_measurement(
        measured: float,
        nominal: float,
        lower_tol: float,
        upper_tol: float,
    ) -> Tuple[str, float, float, float]:
        deviation = measured - nominal
        min_limit = nominal + lower_tol
        max_limit = nominal + upper_tol
        status = "PASS" if min_limit <= measured <= max_limit else "FAIL"
        return status, deviation, min_limit, max_limit

    def _apply_local_y_correction(
        self,
        results: List[MeasurementResult],
        y_calibration: float,
    ) -> None:
        """
        Referans sabit çap noktalarından yerel px/mm eğrisi kur.

        Bu yaklaşım sentetik/master referans görsele göre ayarlanmış sabit
        noktaların, görüntü boyunca tek global Y kalibrasyondan kaynaklanan
        sistematik sapmasını azaltır.
        """
        if y_calibration <= 0:
            return

        anchors = []
        for result in results:
            if result.measurement_type != "diameter" or result.method != "fixed_x":
                continue
            if result.x_used_abs is None or result.nominal_mm <= 0:
                continue
            raw_diameter_px = result.raw_diameter_px
            if raw_diameter_px is None or raw_diameter_px <= 0:
                continue
            local_ppmm = raw_diameter_px / result.nominal_mm
            anchors.append((result.x_used_abs, local_ppmm))

        if len(anchors) < 2:
            return

        anchors.sort(key=lambda item: item[0])
        xs = np.array([item[0] for item in anchors], dtype=float)
        ppmm = np.array([item[1] for item in anchors], dtype=float)

        for result in results:
            if result.measurement_type != "diameter" or result.method != "fixed_x":
                continue
            if result.x_used_abs is None or result.raw_diameter_px is None or result.raw_diameter_px <= 0:
                continue

            local_ppmm = float(np.interp(result.x_used_abs, xs, ppmm))
            corrected_mm = result.raw_diameter_px / local_ppmm

            result.measured_mm = corrected_mm
            (
                result.status,
                result.deviation_mm,
                result.min_limit_mm,
                result.max_limit_mm,
            ) = self._evaluate_measurement(
                corrected_mm,
                result.nominal_mm,
                result.lower_tol_mm,
                result.upper_tol_mm,
            )

            if "local-y" not in result.section_info:
                result.section_info += f" | local-y={local_ppmm:.4f} px/mm"

    def _template_local_y_ppmm_for_x(self, x_abs: Optional[int]) -> Optional[float]:
        """Şablondaki yerel Y kalibrasyon haritasından x konumuna göre px/mm döndür."""
        if x_abs is None:
            return None
        settings = self.template.get('settings', {}) if self.template else {}
        points = settings.get('local_y_ppmm_points', [])
        try:
            anchors = sorted(
                (
                    float(p["x_abs"]),
                    float(p["pixels_per_mm_y"]),
                )
                for p in points
                if p.get("x_abs") is not None and p.get("pixels_per_mm_y") not in (None, 0)
            )
        except Exception:
            return None

        if not anchors:
            return None

        xs = np.array([a[0] for a in anchors], dtype=float)
        ys = np.array([a[1] for a in anchors], dtype=float)
        return float(np.interp(float(x_abs), xs, ys))

    def _template_local_x_anchors(self) -> List[Tuple[float, float]]:
        settings = self.template.get('settings', {}) if self.template else {}
        points = settings.get('local_x_ppmm_points', [])
        try:
            anchors = sorted(
                (
                    float(p["x_abs"]),
                    float(p["pixels_per_mm_x"]),
                )
                for p in points
                if p.get("x_abs") is not None and p.get("pixels_per_mm_x") not in (None, 0)
            )
        except Exception:
            return []
        return anchors

    def _template_x_span_to_mm(
        self,
        x_start_abs: Optional[int],
        x_end_abs: Optional[int],
        x_calibration: float,
    ) -> Optional[float]:
        if x_start_abs is None or x_end_abs is None or x_calibration <= 0:
            return None

        start = float(min(x_start_abs, x_end_abs))
        end = float(max(x_start_abs, x_end_abs))
        span_px = end - start
        if span_px <= 0:
            return None

        anchors = self._template_local_x_anchors()
        if not anchors:
            return span_px / x_calibration

        xs = np.array([a[0] for a in anchors], dtype=float)
        ys = np.array([a[1] for a in anchors], dtype=float)
        pixel_left = np.arange(np.floor(start), np.ceil(end), dtype=float)
        widths = np.minimum(pixel_left + 1.0, end) - np.maximum(pixel_left, start)
        valid = widths > 0
        if not np.any(valid):
            return span_px / x_calibration

        centers = pixel_left[valid] + 0.5
        local_ppmm = np.interp(centers, xs, ys)
        if np.any(local_ppmm <= 0):
            return span_px / x_calibration
        return float(np.sum(widths[valid] / local_ppmm))

    def _template_local_x_ppmm_for_span(
        self,
        x_start_abs: Optional[int],
        x_end_abs: Optional[int],
    ) -> Optional[float]:
        if x_start_abs is None or x_end_abs is None:
            return None
        anchors = self._template_local_x_anchors()
        if not anchors:
            return None
        mid_x = (float(x_start_abs) + float(x_end_abs)) / 2.0
        xs = np.array([a[0] for a in anchors], dtype=float)
        ys = np.array([a[1] for a in anchors], dtype=float)
        return float(np.interp(mid_x, xs, ys))

    def _apply_local_x_correction(
        self,
        results: List[MeasurementResult],
        x_calibration: float,
    ) -> None:
        if x_calibration <= 0:
            return

        for result in results:
            if result.measurement_type != "length":
                continue
            if result.x_pixel_start is None or result.x_pixel_end is None:
                continue
            corrected_mm = self._template_x_span_to_mm(
                result.x_pixel_start,
                result.x_pixel_end,
                x_calibration,
            )
            if corrected_mm is None:
                continue

            result.measured_mm = corrected_mm
            (
                result.status,
                result.deviation_mm,
                result.min_limit_mm,
                result.max_limit_mm,
            ) = self._evaluate_measurement(
                corrected_mm,
                result.nominal_mm,
                result.lower_tol_mm,
                result.upper_tol_mm,
            )

            local_ppmm = self._template_local_x_ppmm_for_span(
                result.x_pixel_start,
                result.x_pixel_end,
            )
            if local_ppmm and "local-x" not in result.section_info:
                result.section_info += f" | local-x~{local_ppmm:.4f} px/mm"
    
    # ─── Çap Ölçüm Metotları ───────────────────────────────────────
    
    def measure_diameter_at_section_center(
        self, 
        section: Dict, 
        profile: Dict, 
        y_calibration: float,
        center_ratio: float = 0.7
    ) -> Tuple[Optional[float], Optional[int], Optional[int], Optional[float], Optional[float]]:
        """
        Bölümün merkez bölgesindeki medyan çapı ölçer.
        
        Tek bir piksel yerine bölümün merkez %ratio kısmındaki tüm çap
        değerlerinin medyanını alarak gürültüye dayanıklı ölçüm yapar.
        
        Args:
            section: Bölüm verisi (detect_sections çıktısı)
            profile: Profil verisi
            y_calibration: Y kalibrasyonu (piksel/mm)
            center_ratio: Bölümün yüzde kaçlık merkez kısmından ölçüm yapılacağı
            
        Returns:
            (diameter_mm, x_start_px, x_end_px, top_y, bottom_y)
        """
        diameter_px_arr = np.array(profile.get('diameter_px', []), dtype=float)
        top_edge = profile.get('top_edge', [])
        bottom_edge = profile.get('bottom_edge', [])
        x_start = profile.get('x_start', 0)
        
        # Bölüm sınırları (profil-göreli indeksler)
        s_rel = section['x_start_rel']
        e_rel = section['x_end_rel']
        width = e_rel - s_rel
        
        if width <= 0:
            return None, None, None, None, None
        
        # Merkez bölgeyi hesapla
        margin = int(width * (1 - center_ratio) / 2)
        center_start = s_rel + margin
        center_end = e_rel - margin
        
        if center_end <= center_start:
            center_start = s_rel
            center_end = e_rel
        
        # Merkez bölgedeki geçerli çap değerlerini al
        segment = diameter_px_arr[center_start:center_end]
        valid = segment[segment > 0]
        
        if len(valid) == 0:
            return None, None, None, None, None
        
        # Medyan çap (gürültüye dayanıklı)
        median_diameter_px = float(np.median(valid))
        diameter_mm = median_diameter_px / y_calibration
        
        # Orta noktadaki üst/alt kenar (overlay çizimi için)
        mid_idx = (center_start + center_end) // 2
        top_y = top_edge[mid_idx] if mid_idx < len(top_edge) and top_edge[mid_idx] is not None else None
        bot_y = bottom_edge[mid_idx] if mid_idx < len(bottom_edge) and bottom_edge[mid_idx] is not None else None
        
        # Piksel koordinatları (mutlak)
        x_px_start = x_start + center_start
        x_px_end = x_start + center_end
        
        return diameter_mm, x_px_start, x_px_end, top_y, bot_y
    
    def measure_diameter_at_boundary(
        self,
        sections: List[Dict],
        section_index: int,
        boundary_side: str,
        profile: Dict,
        y_calibration: float,
        sample_width_px: int = 5
    ) -> Tuple[Optional[float], Optional[int], Optional[int], Optional[float], Optional[float]]:
        """
        İki bölüm sınırındaki çapı ölçer.
        
        Args:
            sections: Tüm bölümler
            section_index: Referans bölüm indeksi
            boundary_side: 'left' veya 'right' — bölümün hangi tarafından ölçüleceği
            profile: Profil verisi
            y_calibration: Y kalibrasyonu (piksel/mm)
            sample_width_px: Sınır etrafında kaç pikselik alan örnekleneceği
            
        Returns:
            (diameter_mm, x_start_px, x_end_px, top_y, bottom_y)
        """
        if section_index < 0 or section_index >= len(sections):
            return None, None, None, None, None
        
        section = sections[section_index]
        diameter_px_arr = np.array(profile.get('diameter_px', []), dtype=float)
        top_edge = profile.get('top_edge', [])
        bottom_edge = profile.get('bottom_edge', [])
        x_start = profile.get('x_start', 0)
        
        # Sınır noktası
        if boundary_side == 'right':
            boundary_x_rel = section['x_end_rel']
        else:
            boundary_x_rel = section['x_start_rel']
        
        # Sınır etrafındaki örnekleme aralığı
        sample_start = max(0, boundary_x_rel - sample_width_px)
        sample_end = min(len(diameter_px_arr), boundary_x_rel + sample_width_px)
        
        segment = diameter_px_arr[sample_start:sample_end]
        valid = segment[segment > 0]
        
        if len(valid) == 0:
            return None, None, None, None, None
        
        median_diameter_px = float(np.median(valid))
        diameter_mm = median_diameter_px / y_calibration
        
        # Overlay için
        mid_idx = boundary_x_rel
        top_y = top_edge[mid_idx] if mid_idx < len(top_edge) and top_edge[mid_idx] is not None else None
        bot_y = bottom_edge[mid_idx] if mid_idx < len(bottom_edge) and bottom_edge[mid_idx] is not None else None
        
        x_px_start = x_start + sample_start
        x_px_end = x_start + sample_end
        
        return diameter_mm, x_px_start, x_px_end, top_y, bot_y
    
    def measure_diameter_at_fixed_x(
        self,
        x_abs: int,
        profile: Dict,
        y_calibration: float,
        sample_width_px: int = 3,
        x_mode: str = "relative_to_part_start",
        search_radius_px: int = 24,
    ) -> Tuple[
        Optional[float],
        Optional[int],
        Optional[int],
        Optional[float],
        Optional[float],
        Optional[int],
        Optional[int],
        Optional[int],
    ]:
        """
        Sabit bir X konumunda çapı ölçer.
        
        Args:
            x_abs: Ölçüm konumu (varsayılan olarak parçanın sol ucundan ofset)
            profile: Profil verisi
            y_calibration: Y kalibrasyonu (piksel/mm)
            sample_width_px: Ölçüm yapılacak X etrafındaki örnekleme genişliği
            x_mode: "relative_to_part_start" veya "absolute_image"
            search_radius_px: Stabil plato aramak için beklenen X çevresindeki arama yarıçapı
            
        Returns:
            (diameter_mm, x_start_px, x_end_px, top_y, bottom_y)
        """
        diameter_px_arr = np.array(profile.get('diameter_px', []), dtype=float)
        top_edge = profile.get('top_edge', [])
        bottom_edge = profile.get('bottom_edge', [])
        x_start_parca = profile.get('x_start', 0)

        if x_mode == "absolute_image":
            x_rel = int(x_abs - x_start_parca)
        else:
            x_rel = int(x_abs)
        
        if x_rel < 0 or x_rel >= len(diameter_px_arr):
            return None, None, None, None, None, None, None, None

        band_start, band_end, used_x_rel = self._pick_stable_diameter_band(
            diameter_px_arr,
            x_rel,
            sample_width_px=sample_width_px,
            search_radius_px=search_radius_px,
        )

        segment = diameter_px_arr[band_start:band_end]
        valid = segment[segment > 0]
        
        if len(valid) == 0:
            # Sadece seçilen noktadaki değeri dene
            val = diameter_px_arr[used_x_rel]
            if val > 0:
                valid = [val]
            else:
                return None, None, None, None, None, None, None, None
        
        median_diameter_px = float(np.median(valid))
        diameter_mm = median_diameter_px / y_calibration
        
        # Overlay için (Mutlak görüntü koordinatları)
        mid_idx = used_x_rel
        top_y = top_edge[mid_idx] if mid_idx < len(top_edge) and top_edge[mid_idx] is not None else None
        bot_y = bottom_edge[mid_idx] if mid_idx < len(bottom_edge) and bottom_edge[mid_idx] is not None else None
        
        # Overlay görüntüsü için mutlak X koordinatları
        x_px_start = x_start_parca + band_start
        x_px_end = x_start_parca + max(band_start, band_end - 1)
        x_used_abs = x_start_parca + used_x_rel
        snap_offset_px = used_x_rel - x_rel
        
        return diameter_mm, x_px_start, x_px_end, top_y, bot_y, x_used_abs, used_x_rel, snap_offset_px
    
    # ─── Uzunluk Ölçüm Metotları ──────────────────────────────────
    
    def measure_section_length(
        self,
        section: Dict,
        x_calibration: float
    ) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """
        Tek bölümün uzunluğunu ölçer.
        
        Returns:
            (length_mm, x_start_px, x_end_px)
        """
        width_px = section.get('width_px', 0)
        if width_px <= 0 or x_calibration <= 0:
            return None, None, None
        
        length_mm = width_px / x_calibration
        return length_mm, section['x_start_abs'], section['x_end_abs']
    
    def measure_multi_section_length(
        self,
        sections: List[Dict],
        section_start: int,
        section_end: int,
        x_calibration: float
    ) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """
        Birden fazla bölümün toplam uzunluğunu ölçer.
        section_start'tan section_end'e kadar (dahil) tüm bölümlerin uzunluk toplamı.
        
        Returns:
            (length_mm, x_start_px, x_end_px)
        """
        if section_start < 0 or section_end >= len(sections):
            return None, None, None
        if section_start > section_end:
            return None, None, None
        
        # İlk bölümün başından son bölümün sonuna kadar mesafe
        x_start_px = sections[section_start]['x_start_abs']
        x_end_px = sections[section_end]['x_end_abs']
        total_px = x_end_px - x_start_px
        
        if total_px <= 0 or x_calibration <= 0:
            return None, None, None
        
        length_mm = total_px / x_calibration
        return length_mm, x_start_px, x_end_px

    def measure_fixed_length(
        self,
        x_start_abs: int,
        x_end_abs: int,
        x_calibration: float,
    ) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """
        Görüntü üzerindeki sabit iki X koordinatı arasındaki uzunluğu ölçer.

        Returns:
            (length_mm, x_start_px, x_end_px)
        """
        if x_calibration <= 0:
            return None, None, None

        start_px = int(min(x_start_abs, x_end_abs))
        end_px = int(max(x_start_abs, x_end_abs))
        total_px = end_px - start_px
        if total_px <= 0:
            return None, None, None

        length_mm = total_px / x_calibration
        return length_mm, start_px, end_px
    
    def measure_total_length(
        self,
        profile: Dict,
        x_calibration: float
    ) -> Tuple[Optional[float], Optional[int], Optional[int]]:
        """
        Parçanın toplam uzunluğunu ölçer.
        
        Returns:
            (length_mm, x_start_px, x_end_px)
        """
        diameter_px = profile.get('diameter_px', [])
        x_start = profile.get('x_start', 0)
        
        if not diameter_px or x_calibration <= 0:
            return None, None, None
        
        # Geçerli çap değerlerinin aralığını bul
        valid_indices = [i for i, d in enumerate(diameter_px) if d is not None and d > 0]
        
        if not valid_indices:
            return None, None, None
        
        first_valid = min(valid_indices)
        last_valid = max(valid_indices)
        length_px = (last_valid - first_valid) + 1
        length_mm = length_px / x_calibration
        
        return length_mm, x_start + first_valid, x_start + last_valid
    
    # ─── Pass/Fail Değerlendirmesi ─────────────────────────────────
    
    def evaluate_pass_fail(self, measured: float, nominal: float,
                          lower_tol: float, upper_tol: float) -> Tuple[str, float]:
        """
        Ölçüm değerini toleranslarla karşılaştırır.
        
        Returns:
            (status, deviation) — "PASS" veya "FAIL", sapma değeri
        """
        deviation = measured - nominal
        min_limit = nominal + lower_tol
        max_limit = nominal + upper_tol
        
        if min_limit <= measured <= max_limit:
            return "PASS", deviation
        else:
            return "FAIL", deviation
    
    # ─── Ana Ölçüm Fonksiyonu ─────────────────────────────────────
    
    def perform_measurements(
        self,
        profile: Dict,
        sections: List[Dict],
        y_calibration: float,
        x_calibration: float
    ) -> List[MeasurementResult]:
        """
        Tüm sabit ölçüm noktalarında bölüm-tabanlı ölçüm yapar.
        
        Args:
            profile: Profil verisi (profile_extractor çıktısı)
            sections: Bölüm listesi (detect_sections çıktısı)
            y_calibration: Y kalibrasyonu (piksel/mm)
            x_calibration: X kalibrasyonu (piksel/mm)
            
        Returns:
            Ölçüm sonuçları listesi
        """
        results = []
        num_sections = len(sections)
        
        expected_sections = self.template.get('notes', {}).get('expected_sections', 0)
        if expected_sections > 0 and num_sections != expected_sections:
            print(f"⚠️ Uyarı: Beklenen {expected_sections} bölüm, tespit edilen {num_sections} bölüm")
        
        for point in self.measurement_points:
            code = point['code']
            point_type = point['type']
            method = point.get('method', 'section_center')
            nominal = point['nominal_mm']
            lower_tol = point['lower_tol_mm']
            upper_tol = point['upper_tol_mm']
            description = point['description']
            unit = point.get('unit', 'mm')
            
            measured = None
            section_info = ""
            x_start_px = None
            x_end_px = None
            top_y = None
            bottom_y = None
            x_used_abs = None
            x_used_rel = None
            snap_offset_px = None
            local_ppmm = None
            raw_length_px = None
            
            # ─── Çap Ölçümleri ───
            if point_type == 'diameter' and method == 'section_center':
                section_idx = point.get('section_index', 0)
                center_ratio = point.get('center_ratio', 0.7)
                
                if section_idx < num_sections:
                    section = sections[section_idx]
                    measured, x_start_px, x_end_px, top_y, bottom_y = \
                        self.measure_diameter_at_section_center(
                            section, profile, y_calibration, center_ratio
                        )
                    section_info = f"Bölüm {section_idx + 1} merkezi (ratio={center_ratio})"
                else:
                    section_info = f"Bölüm {section_idx + 1} bulunamadı (toplam: {num_sections})"
            
            elif point_type == 'diameter' and method == 'section_boundary':
                section_idx = point.get('section_index', 0)
                boundary_side = point.get('boundary_side', 'right')
                sample_width = point.get('sample_width_px', 5)
                
                measured, x_start_px, x_end_px, top_y, bottom_y = \
                    self.measure_diameter_at_boundary(
                        sections, section_idx, boundary_side,
                        profile, y_calibration, sample_width
                    )
                section_info = f"Bölüm {section_idx + 1} {boundary_side} sınırı"
                
            elif point_type == 'diameter' and method == 'fixed_x':
                x_abs = point.get('x_abs', 0)
                x_mode = point.get('x_mode', 'relative_to_part_start')
                sample_width = point.get('sample_width_px', 3)
                search_radius = point.get('search_radius_px', 24)
                
                measured, x_start_px, x_end_px, top_y, bottom_y, x_used_abs, x_used_rel, snap_offset_px = \
                    self.measure_diameter_at_fixed_x(
                        x_abs, profile, y_calibration, sample_width, x_mode=x_mode, search_radius_px=search_radius
                    )
                if x_mode == 'absolute_image':
                    section_info = f"Görüntü koordinatı x={x_abs}"
                else:
                    section_info = f"Parça solundan ofset x={x_abs}"
                if x_used_abs is not None and snap_offset_px is not None:
                    section_info += f" | kullanılan x={x_used_abs} (snap {snap_offset_px:+d}px)"
                if measured is not None:
                    raw_diameter_px = measured * y_calibration
                    local_ppmm = self._template_local_y_ppmm_for_x(x_used_abs)
                    if local_ppmm and local_ppmm > 0:
                        measured = raw_diameter_px / local_ppmm
                        section_info += f" | local-y={local_ppmm:.4f} px/mm"
                    else:
                        local_ppmm = None
            
            # ─── Uzunluk Ölçümleri ───
            elif point_type == 'length' and method == 'section_length':
                section_idx = point.get('section_index', 0)
                
                if section_idx < num_sections:
                    section = sections[section_idx]
                    measured, x_start_px, x_end_px = \
                        self.measure_section_length(section, x_calibration)
                    section_info = f"Bölüm {section_idx + 1} uzunluğu"
                else:
                    section_info = f"Bölüm {section_idx + 1} bulunamadı"
            
            elif point_type == 'length' and method == 'multi_section_length':
                s_start = point.get('section_start', 0)
                s_end = point.get('section_end', 0)
                
                measured, x_start_px, x_end_px = \
                    self.measure_multi_section_length(
                        sections, s_start, s_end, x_calibration
                    )
                section_info = f"Bölüm {s_start + 1} → {s_end + 1} arası uzunluk"

            elif point_type == 'length' and method == 'fixed_range':
                range_start = point.get('x_start_abs')
                range_end = point.get('x_end_abs')
                if range_start is None or range_end is None:
                    section_info = "Sabit aralık tanımsız"
                else:
                    measured, x_start_px, x_end_px = self.measure_fixed_length(
                        range_start, range_end, x_calibration
                    )
                    section_info = f"Görüntü aralığı x={range_start} → {range_end}"
            
            elif point_type == 'length' and method == 'total_length':
                measured, x_start_px, x_end_px = \
                    self.measure_total_length(profile, x_calibration)
                section_info = "Toplam parça uzunluğu"
            
            # ─── Değerlendirme ───
            if measured is not None:
                if point_type == 'length' and x_start_px is not None and x_end_px is not None:
                    raw_length_px = float(abs(x_end_px - x_start_px))
                status, deviation, min_limit, max_limit = self._evaluate_measurement(
                    measured, nominal, lower_tol, upper_tol
                )
            else:
                status = "FAIL"
                deviation = 0.0
                min_limit = nominal + lower_tol
                max_limit = nominal + upper_tol
                measured = 0.0
                section_info += " — ölçüm alınamadı"
            
            result = MeasurementResult(
                code=code,
                measurement_type=point_type,
                method=method,
                nominal_mm=nominal,
                measured_mm=measured,
                deviation_mm=deviation,
                lower_tol_mm=lower_tol,
                upper_tol_mm=upper_tol,
                min_limit_mm=min_limit,
                max_limit_mm=max_limit,
                status=status,
                description=description,
                unit=unit,
                section_info=section_info,
                x_pixel_start=x_start_px,
                x_pixel_end=x_end_px,
                top_y=top_y,
                bottom_y=bottom_y,
                x_abs=point.get('x_abs') if method == 'fixed_x' else None,
                x_mode=point.get('x_mode', 'relative_to_part_start') if method == 'fixed_x' else None,
                x_used_abs=x_used_abs if method == 'fixed_x' else None,
                x_used_rel=x_used_rel if method == 'fixed_x' else None,
                snap_offset_px=snap_offset_px if method == 'fixed_x' else None,
                raw_diameter_px=(measured * (local_ppmm if ('local_ppmm' in locals() and local_ppmm) else y_calibration)) if (method == 'fixed_x' and point_type == 'diameter' and measured is not None) else None,
                raw_length_px=raw_length_px,
                section_index=point.get('section_index') if method in ['section_center', 'section_boundary', 'section_length'] else None,
            )
            
            results.append(result)

        if self.template.get('settings', {}).get('use_local_y_correction', False):
            self._apply_local_y_correction(results, y_calibration)
        if self.template.get('settings', {}).get('use_local_x_correction', False):
            self._apply_local_x_correction(results, x_calibration)

        return results
    
    def generate_report_data(self, results: List[MeasurementResult]) -> Dict:
        """
        Ölçüm sonuçlarından rapor verisi oluşturur.
        """
        report = {
            'template_id': self.template.get('template_id', 'UNKNOWN'),
            'description': self.template.get('description', ''),
            'measurements': [],
            'summary': {
                'total': len(results),
                'pass': sum(1 for r in results if r.status == 'PASS'),
                'fail': sum(1 for r in results if r.status == 'FAIL'),
                'pass_rate': 0.0
            }
        }
        
        if results:
            report['summary']['pass_rate'] = (
                report['summary']['pass'] / len(results) * 100
            )
        
        for result in results:
            m_data = {
                'code': result.code,
                'type': result.measurement_type,
                'method': result.method,
                'description': result.description,
                'nominal': f"{result.nominal_mm:.4f}",
                'measured': f"{result.measured_mm:.4f}",
                'deviation': f"{result.deviation_mm:.4f}",
                'lower_tol': f"{result.lower_tol_mm:.4f}",
                'upper_tol': f"{result.upper_tol_mm:.4f}",
                'min_limit': f"{result.min_limit_mm:.4f}",
                'max_limit': f"{result.max_limit_mm:.4f}",
                'status': result.status,
                'unit': result.unit,
                'section_info': result.section_info,
                'x_pixel_start': result.x_pixel_start,
                'x_pixel_end': result.x_pixel_end,
                'top_y': result.top_y,
                'bottom_y': result.bottom_y,
            }
            
            # Add raw parameters for fine-tuning UI
            if result.x_abs is not None:
                m_data['x_abs'] = result.x_abs
            if result.x_mode is not None:
                m_data['x_mode'] = result.x_mode
            if result.x_used_abs is not None:
                m_data['x_used_abs'] = result.x_used_abs
            if result.x_used_rel is not None:
                m_data['x_used_rel'] = result.x_used_rel
            if result.snap_offset_px is not None:
                m_data['snap_offset_px'] = result.snap_offset_px
            if result.section_index is not None:
                m_data['section_index'] = result.section_index
            
            m_data['raw_lower_tol'] = result.lower_tol_mm
            m_data['raw_upper_tol'] = result.upper_tol_mm

            report['measurements'].append(m_data)
        
        return report


def load_default_template() -> FixedMeasurementEngine:
    """Varsayılan şablonu yükler."""
    template_path = Path(__file__).parent / 'fixed_measurement_template.json'
    engine = FixedMeasurementEngine(str(template_path))
    return engine


# Test için
if __name__ == "__main__":
    engine = load_default_template()
    print(f"Şablon yüklendi: {engine.template.get('template_id')}")
    print(f"Versiyon: {engine.template.get('version')}")
    print(f"Ölçüm noktası sayısı: {len(engine.measurement_points)}")
    for point in engine.measurement_points:
        method = point.get('method', '?')
        section = point.get('section_index', '-')
        print(f"  {point['code']}: {point['description']} "
              f"(method={method}, section={section}, nominal={point['nominal_mm']} mm)")
