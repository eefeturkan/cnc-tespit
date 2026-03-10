"""
CNC Parça Ölçüm Sistemi — Kalibrasyon Modülü
Piksel/mm oranı hesaplama ve kalibrasyon profili yönetimi.
"""

import json
from pathlib import Path
from typing import Optional, Dict, Any


# ---------------------------------------------------------------------------
# Sabit Görüntü Boyutu Düzeltmesi
# ---------------------------------------------------------------------------
# Yüklenen görseller sabit 1920x1080 (Full HD) boyutundadır.
# 1920x1080 standart kare piksel oranına sahiptir (16:9).
# Bu nedenle X ve Y yönlerinde piksel yoğunluğu eşittir ve
# düzeltme faktörü 1.0 olarak ayarlanmıştır.
# Kullanıcı bağımsız X-ekseni kalibrasyonu yaparsa bu değer
# yalnızca fallback olarak kullanılır (set_x_calibration() override eder).
# ---------------------------------------------------------------------------
ASPECT_CORRECTION_FACTOR = 1.0


class CalibrationProfile:
    """Kalibrasyon profili — ayrı X ve Y ekseni piksel/mm oranlarını saklar."""

    def __init__(self, pixels_per_mm: float = 1.0, reference_diameter_mm: float = 0.0,
                 reference_pixels: float = 0.0, name: str = "default",
                 pixels_per_mm_x: float = None, pixels_per_mm_y: float = None,
                 x_user_calibrated: bool = False):
        self.name = name
        self.pixels_per_mm = pixels_per_mm
        self.reference_diameter_mm = reference_diameter_mm
        self.reference_pixels = reference_pixels
        # Y-ekseni (dikey/çap) oranı
        self.pixels_per_mm_y = pixels_per_mm_y if pixels_per_mm_y is not None else pixels_per_mm
        # X-ekseni (yatay/uzunluk) oranı
        if pixels_per_mm_x is not None:
            self.pixels_per_mm_x = pixels_per_mm_x
            self._x_user_calibrated = bool(x_user_calibrated)
        else:
            # Fallback: ASPECT_CORRECTION_FACTOR kullan — kullanıcı henüz kalibre etmedi
            self.pixels_per_mm_x = self.pixels_per_mm_y / ASPECT_CORRECTION_FACTOR
            self._x_user_calibrated = False

    def pixels_to_mm(self, pixels: float) -> float:
        """Piksel değerini mm'ye çevir (geriye uyumluluk — Y ekseni)."""
        if self.pixels_per_mm <= 0:
            return 0.0
        return pixels / self.pixels_per_mm

    def pixels_to_mm_y(self, pixels: float) -> float:
        """Y-ekseni (dikey) piksel değerini mm'ye çevir — çap ölçümü için."""
        if self.pixels_per_mm_y <= 0:
            return 0.0
        return pixels / self.pixels_per_mm_y

    def pixels_to_mm_x(self, pixels: float) -> float:
        """X-ekseni (yatay) piksel değerini mm'ye çevir — uzunluk ölçümü için."""
        if self.pixels_per_mm_x is None or self.pixels_per_mm_x <= 0:
            # X kalibrasyonu yapılmamışsa fallback: Y kalibrasyonunu kullan
            if self.pixels_per_mm_y and self.pixels_per_mm_y > 0:
                return pixels / self.pixels_per_mm_y
            return 0.0
        return pixels / self.pixels_per_mm_x

    @property
    def x_is_calibrated(self) -> bool:
        """X-ekseninin kullanıcı tarafından bağımsız olarak kalibre edilip edilmediğini döndür."""
        return self._x_user_calibrated

    def mm_to_pixels(self, mm: float) -> float:
        """mm değerini piksele çevir."""
        return mm * self.pixels_per_mm

    def set_x_calibration(self, pixels_per_mm_x: float):
        """X-ekseni kalibrasyonunu kullanıcı tarafından ayarla."""
        self.pixels_per_mm_x = pixels_per_mm_x
        self._x_user_calibrated = True

    def set_y_calibration(self, pixels_per_mm_y: float):
        """Y-ekseni kalibrasyonunu ayarla. X-ekseni kullanıcı kalibrasyonu korunur."""
        self.pixels_per_mm_y = pixels_per_mm_y
        self.pixels_per_mm = pixels_per_mm_y  # Geriye uyumluluk
        # X kullanıcı tarafından kalibre edilmemişse fallback'i güncelle
        if not self._x_user_calibrated:
            self.pixels_per_mm_x = pixels_per_mm_y / ASPECT_CORRECTION_FACTOR

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "pixels_per_mm": self.pixels_per_mm,
            "pixels_per_mm_x": self.pixels_per_mm_x,
            "pixels_per_mm_y": self.pixels_per_mm_y,
            "x_user_calibrated": self._x_user_calibrated,
            "reference_diameter_mm": self.reference_diameter_mm,
            "reference_pixels": self.reference_pixels,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CalibrationProfile":
        ppmm = data.get("pixels_per_mm", 1.0)
        ppmm_x = data.get("pixels_per_mm_x", None)
        has_explicit_x_flag = "x_user_calibrated" in data
        # Geriye uyumluluk: eski profilde x flag yoksa ppmm_x varlığına göre çıkarım yap.
        if has_explicit_x_flag:
            x_user_cal = bool(data.get("x_user_calibrated", False))
        else:
            x_user_cal = ppmm_x is not None
        return cls(
            pixels_per_mm=ppmm,
            reference_diameter_mm=data.get("reference_diameter_mm", 0.0),
            reference_pixels=data.get("reference_pixels", 0.0),
            name=data.get("name", "default"),
            pixels_per_mm_x=ppmm_x,
            pixels_per_mm_y=data.get("pixels_per_mm_y", ppmm),
            x_user_calibrated=x_user_cal,
        )


def calculate_calibration(reference_diameter_mm: float, point1_y: float, point2_y: float) -> CalibrationProfile:
    """
    İki nokta arasındaki piksel mesafesi ve bilinen çap değerinden kalibrasyon hesapla.
    Bu Y-ekseni (dikey) kalibrasyonudur.

    Args:
        reference_diameter_mm: Referans çap değeri (mm)
        point1_y: Birinci nokta y koordinatı (piksel) — üst kenar
        point2_y: İkinci nokta y koordinatı (piksel) — alt kenar

    Returns:
        CalibrationProfile: Hesaplanan kalibrasyon profili
    """
    pixel_distance = abs(point2_y - point1_y)
    if pixel_distance == 0 or reference_diameter_mm <= 0:
        raise ValueError("Geçersiz kalibrasyon değerleri: piksel mesafesi ve çap sıfırdan büyük olmalı")

    pixels_per_mm = pixel_distance / reference_diameter_mm

    return CalibrationProfile(
        pixels_per_mm=pixels_per_mm,
        reference_diameter_mm=reference_diameter_mm,
        reference_pixels=pixel_distance,
        name="custom",
        pixels_per_mm_y=pixels_per_mm,
    )


def calculate_calibration_from_line(reference_length_mm: float, x1: float, y1: float,
                                     x2: float, y2: float) -> CalibrationProfile:
    """
    Herhangi iki nokta arası piksel mesafesi ve bilinen uzunluktan kalibrasyon hesapla.
    Hem yatay hem dikey ölçüm için kullanılabilir.
    """
    import math
    pixel_distance = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
    if pixel_distance == 0 or reference_length_mm <= 0:
        raise ValueError("Geçersiz kalibrasyon değerleri")

    pixels_per_mm = pixel_distance / reference_length_mm
    return CalibrationProfile(
        pixels_per_mm=pixels_per_mm,
        reference_diameter_mm=reference_length_mm,
        reference_pixels=pixel_distance,
        name="custom",
    )


def calculate_x_calibration(reference_length_mm: float, x1: float, x2: float) -> float:
    """
    X-ekseni (yatay) kalibrasyonu: bilinen uzunluktaki bir bölümün
    iki x koordinatından piksel/mm oranı hesapla.

    Args:
        reference_length_mm: Bilinen uzunluk (mm)
        x1: Birinci nokta x koordinatı (piksel)
        x2: İkinci nokta x koordinatı (piksel)

    Returns:
        float: X-ekseni piksel/mm oranı
    """
    pixel_distance = abs(x2 - x1)
    if pixel_distance == 0 or reference_length_mm <= 0:
        raise ValueError("Geçersiz kalibrasyon değerleri: piksel mesafesi ve uzunluk sıfırdan büyük olmalı")

    return pixel_distance / reference_length_mm


# ---------------------------------------------------------------------------
# Profil Kayıt/Yükleme
# ---------------------------------------------------------------------------

PROFILES_DIR = Path(__file__).resolve().parent.parent / "calibration_profiles"


def save_profile(profile: CalibrationProfile, name: Optional[str] = None) -> str:
    """Kalibrasyon profilini JSON dosyası olarak kaydet."""
    PROFILES_DIR.mkdir(exist_ok=True)
    profile_name = name or profile.name
    filepath = PROFILES_DIR / f"{profile_name}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(profile.to_dict(), f, indent=2, ensure_ascii=False)
    return str(filepath)


def load_profile(name: str) -> CalibrationProfile:
    """Kaydedilmiş kalibrasyon profilini yükle."""
    filepath = PROFILES_DIR / f"{name}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Profil bulunamadı: {name}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return CalibrationProfile.from_dict(data)


def list_profiles() -> list:
    """Kaydedilmiş profillerin listesini döndür."""
    PROFILES_DIR.mkdir(exist_ok=True)
    profiles = []
    for fp in PROFILES_DIR.glob("*.json"):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = json.load(f)
            profiles.append(data)
        except Exception:
            continue
    return profiles
