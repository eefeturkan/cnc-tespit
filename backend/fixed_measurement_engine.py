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
        length_px = last_valid - first_valid
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
            
            elif point_type == 'length' and method == 'total_length':
                measured, x_start_px, x_end_px = \
                    self.measure_total_length(profile, x_calibration)
                section_info = "Toplam parça uzunluğu"
            
            # ─── Değerlendirme ───
            if measured is not None:
                status, deviation = self.evaluate_pass_fail(
                    measured, nominal, lower_tol, upper_tol
                )
                min_limit = nominal + lower_tol
                max_limit = nominal + upper_tol
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
            )
            
            results.append(result)
        
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
            report['measurements'].append({
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
            })
        
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
