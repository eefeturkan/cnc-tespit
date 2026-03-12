"""
Sabit Ölçüm Noktaları Motoru
Teknik çizimdeki sabit noktalarda ölçüm yapar ve pass/fail değerlendirmesi yapar.
"""

import json
import numpy as np
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class MeasurementResult:
    """Ölçüm sonucu veri yapısı"""
    code: str
    measurement_type: str  # 'diameter', 'length', 'height'
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


class FixedMeasurementEngine:
    """
    Sabit ölçüm noktaları motoru.
    Parça profilinden belirli X konumlarında ölçüm yapar.
    """
    
    def __init__(self, template_path: Optional[str] = None):
        """
        Args:
            template_path: JSON şablon dosyasının yolu
        """
        self.template = None
        self.measurement_points = []
        
        if template_path:
            self.load_template(template_path)
    
    def load_template(self, template_path: str) -> bool:
        """
        JSON şablon dosyasını yükler.
        
        Args:
            template_path: JSON dosya yolu
            
        Returns:
            Başarılı ise True
        """
        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                self.template = json.load(f)
            self.measurement_points = self.template.get('measurement_points', [])
            return True
        except Exception as e:
            print(f"Şablon yükleme hatası: {e}")
            return False
    
    def find_reference_point(self, profile: Dict) -> int:
        """
        Parçanın referans noktasını bulur (sol uç).
        
        Args:
            profile: Profil verisi (profile_extractor çıktısı)
            
        Returns:
            Referans X koordinatı (piksel)
        """
        # Sol uç = profilin başlangıç noktası
        return profile.get('x_start', 0)
    
    def measure_at_position(self, profile: Dict, x_mm: float, 
                           y_calibration: float) -> Optional[float]:
        """
        Belirli X konumunda çap ölçümü yapar.
        
        Args:
            profile: Profil verisi
            x_mm: X konumu (mm)
            y_calibration: Y kalibrasyonu (piksel/mm)
            
        Returns:
            Çap değeri (mm) veya None
        """
        # Referans noktasını bul
        x_ref = self.find_reference_point(profile)
        
        # X konumunu piksele çevir
        x_pixel = int(x_ref + x_mm * y_calibration)  # y_calibration = pixels_per_mm
        
        # Profil verilerini al
        diameter_px = profile.get('diameter_px', [])
        top_edge = profile.get('top_edge', [])
        bottom_edge = profile.get('bottom_edge', [])
        x_start = profile.get('x_start', 0)
        
        if not diameter_px or x_pixel < x_start or x_pixel >= x_start + len(diameter_px):
            return None
        
        # O konumdaki çap değerini al
        idx = x_pixel - x_start
        if idx < 0 or idx >= len(diameter_px):
            return None
        
        diameter_pixel = diameter_px[idx]
        if diameter_pixel is None or diameter_pixel <= 0:
            return None
        
        # Pikselden mm'ye çevir
        diameter_mm = diameter_pixel / y_calibration
        
        return diameter_mm
    
    def measure_total_length(self, profile: Dict, 
                            x_calibration: float) -> Optional[float]:
        """
        Parçanın toplam uzunluğunu ölçer.
        
        Args:
            profile: Profil verisi
            x_calibration: X kalibrasyonu (piksel/mm)
            
        Returns:
            Uzunluk (mm) veya None
        """
        diameter_px = profile.get('diameter_px', [])
        if not diameter_px:
            return None
        
        # Geçerli çap değerlerinin aralığını bul
        valid_indices = [i for i, d in enumerate(diameter_px) 
                        if d is not None and d > 0]
        
        if not valid_indices:
            return None
        
        length_px = max(valid_indices) - min(valid_indices)
        length_mm = length_px / x_calibration
        
        return length_mm
    
    def measure_section_lengths(self, profile: Dict,
                               x_calibration: float) -> List[float]:
        """
        Her bölümün uzunluğunu ölçer.
        
        Args:
            profile: Profil verisi
            x_calibration: X kalibrasyonu (piksel/mm)
            
        Returns:
            Bölüm uzunlukları listesi (mm)
        """
        from measurement_engine import detect_sections
        from calibration import CalibrationProfile
        
        # Geçici kalibrasyon profili oluştur (sadece piksel/mm değerleri için)
        temp_calibration = CalibrationProfile(
            pixels_per_mm=x_calibration,
            pixels_per_mm_x=x_calibration,
            pixels_per_mm_y=x_calibration
        )
        
        # Bölümleri tespit et
        sections = detect_sections(profile, temp_calibration)
        
        lengths_mm = []
        for section in sections:
            x_start = section.get('x_start_abs', 0)
            x_end = section.get('x_end_abs', 0)
            length_px = x_end - x_start
            length_mm = length_px / x_calibration
            lengths_mm.append(length_mm)
        
        return lengths_mm
    
    def evaluate_pass_fail(self, measured: float, nominal: float,
                          lower_tol: float, upper_tol: float) -> Tuple[str, float]:
        """
        Ölçüm değerini toleranslarla karşılaştırır.
        
        Args:
            measured: Ölçülen değer
            nominal: Nominal değer
            lower_tol: Alt tolerans
            upper_tol: Üst tolerans
            
        Returns:
            (status, deviation) - "PASS" veya "FAIL", sapma değeri
        """
        deviation = measured - nominal
        min_limit = nominal + lower_tol
        max_limit = nominal + upper_tol
        
        if min_limit <= measured <= max_limit:
            return "PASS", deviation
        else:
            return "FAIL", deviation
    
    def perform_measurements(self, profile: Dict, 
                            y_calibration: float,
                            x_calibration: float) -> List[MeasurementResult]:
        """
        Tüm sabit ölçüm noktalarında ölçüm yapar.
        
        Args:
            profile: Profil verisi
            y_calibration: Y kalibrasyonu (piksel/mm)
            x_calibration: X kalibrasyonu (piksel/mm)
            
        Returns:
            Ölçüm sonuçları listesi
        """
        results = []
        
        # Bölüm uzunluklarını önceden hesapla
        section_lengths = self.measure_section_lengths(profile, x_calibration)
        
        for point in self.measurement_points:
            code = point['code']
            point_type = point['type']
            axis = point['axis']
            nominal = point['nominal_mm']
            lower_tol = point['lower_tol_mm']
            upper_tol = point['upper_tol_mm']
            description = point['description']
            unit = point['unit']
            
            measured = None
            
            if point_type == 'diameter' and axis == 'Y':
                # Çap ölçümü
                x_mm = point.get('x_position_mm', 0)
                measured = self.measure_at_position(profile, x_mm, y_calibration)
                
            elif point_type == 'height' and axis == 'Y':
                # Yükseklik ölçümü (şimdilik çap gibi)
                x_mm = point.get('x_position_mm', 0)
                measured = self.measure_at_position(profile, x_mm, y_calibration)
                
            elif point_type == 'length' and axis == 'X':
                # Uzunluk ölçümü
                measurement = point.get('measurement', 'total_length')
                
                if measurement == 'total_length':
                    measured = self.measure_total_length(profile, x_calibration)
                elif measurement == 'section_length':
                    section_idx = point.get('section_index', 0)
                    if section_idx < len(section_lengths):
                        measured = section_lengths[section_idx]
                    else:
                        measured = None
            
            # Değerlendirme
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
            
            result = MeasurementResult(
                code=code,
                measurement_type=point_type,
                nominal_mm=nominal,
                measured_mm=measured,
                deviation_mm=deviation,
                lower_tol_mm=lower_tol,
                upper_tol_mm=upper_tol,
                min_limit_mm=min_limit,
                max_limit_mm=max_limit,
                status=status,
                description=description,
                unit=unit
            )
            
            results.append(result)
        
        return results
    
    def generate_report_data(self, results: List[MeasurementResult]) -> Dict:
        """
        Ölçüm sonuçlarından rapor verisi oluşturur.
        
        Args:
            results: Ölçüm sonuçları listesi
            
        Returns:
            Rapor verisi (tablo formatında)
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
                'description': result.description,
                'nominal': f"{result.nominal_mm:.4f}",
                'measured': f"{result.measured_mm:.4f}",
                'deviation': f"{result.deviation_mm:.4f}",
                'lower_tol': f"{result.lower_tol_mm:.4f}",
                'upper_tol': f"{result.upper_tol_mm:.4f}",
                'min_limit': f"{result.min_limit_mm:.4f}",
                'max_limit': f"{result.max_limit_mm:.4f}",
                'status': result.status,
                'unit': result.unit
            })
        
        return report


def load_default_template() -> FixedMeasurementEngine:
    """
    Varsayılan şablonu yükler.
    
    Returns:
        FixedMeasurementEngine instance
    """
    template_path = Path(__file__).parent / 'fixed_measurement_template.json'
    engine = FixedMeasurementEngine(str(template_path))
    return engine


# Test için
if __name__ == "__main__":
    engine = load_default_template()
    print(f"Şablon yüklendi: {engine.template.get('template_id')}")
    print(f"Ölçüm noktası sayısı: {len(engine.measurement_points)}")
    for point in engine.measurement_points:
        print(f"  {point['code']}: {point['description']} ({point['nominal_mm']} mm)")
