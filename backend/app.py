"""
CNC Parça Ölçüm Sistemi — FastAPI Backend
Görüntü yükleme, işleme ve ölçüm API'si.
Frontend dosyaları ../frontend/ klasöründen serve edilir.
"""

import os
import uuid
import base64
from pathlib import Path
from typing import Optional, List, Dict, Literal

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from image_processing import get_algorithm_list, apply_algorithm
from calibration import (
    CalibrationProfile, calculate_calibration, calculate_calibration_from_line,
    calculate_x_calibration,
    save_profile, load_profile, list_profiles,
)
from profile_extractor import (
    extract_profile,
    draw_profile_overlay,
    _subpixel_edge_1d,
    _subpixel_edge_1d_polarity,
)
from measurement_engine import (
    detect_sections,
    detect_sections_golden,
    compute_sections_from_boundaries,
    generate_measurement_table,
    get_measurement_summary,
)
from report_generator import generate_pdf_report, generate_excel_report
from fixed_measurement_engine import FixedMeasurementEngine, load_default_template

# ---------------------------------------------------------------------------
# Yollar
# ---------------------------------------------------------------------------
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"
UPLOAD_DIR = PROJECT_DIR / "uploads"
REPORTS_DIR = PROJECT_DIR / "reports"

UPLOAD_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Uygulama
# ---------------------------------------------------------------------------
app = FastAPI(
    title="CNC Parça Ölçüm Sistemi",
    description="Silindirik CNC parçalarının çap ve uzunluk ölçüm sistemi",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static dosyalar
app.mount("/css", StaticFiles(directory=str(FRONTEND_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(FRONTEND_DIR / "js")), name="js")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Aktif kalibrasyon (session bazlı — bellekte tutulur)
active_calibration: CalibrationProfile = CalibrationProfile(pixels_per_mm=1.0, name="default")
# image_id bazlı kalibrasyon bağlama (global tek profil riskini azaltır)
active_calibration_by_image: Dict[str, CalibrationProfile] = {}

# image_id bazlı golden (referans) layout
active_reference_layout_by_image: Dict[str, dict] = {}

# image_id bazlı ROI (Region of Interest) — (x, y, w, h)
active_roi_by_image: Dict[str, tuple] = {}


# ---------------------------------------------------------------------------
# Modeller
# ---------------------------------------------------------------------------
class ProcessRequest(BaseModel):
    image_id: str
    algorithm: str
    params: dict = Field(default_factory=dict)


class CalibrateRequest(BaseModel):
    image_id: Optional[str] = None
    reference_mm: float
    x1: float
    y1: float
    x2: float
    y2: float
    profile_name: Optional[str] = None


class MeasureRequest(BaseModel):
    image_id: str
    mode: Literal["auto", "golden"] = "auto"
    reference_layout: Optional[dict] = None
    min_section_width_px: int = 20
    gradient_threshold: float = 2.0
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 5000


class ReferenceFeature(BaseModel):
    id: str
    type: Literal["diameter", "length"]
    order: int
    nominal_mm: Optional[float] = None
    tol_minus: Optional[float] = None
    tol_plus: Optional[float] = None
    required: bool = True


class ReferenceLayout(BaseModel):
    image_id: Optional[str] = None
    name: Optional[str] = None
    features: List[ReferenceFeature]


class ReferenceLayoutSetRequest(BaseModel):
    image_id: str
    layout: ReferenceLayout


class ManualCalibrationRequest(BaseModel):
    image_id: Optional[str] = None
    pixels_per_mm: float
    profile_name: Optional[str] = None


class EdgeDetectRequest(BaseModel):
    image_id: str
    click_x: float
    click_y: float
    blur_ksize: int = 5
    morph_ksize: int = 5


class XCalibrateRequest(BaseModel):
    image_id: Optional[str] = None
    reference_length_mm: float
    x1: float
    x2: float
    profile_name: Optional[str] = None


class ManualBoundariesRequest(BaseModel):
    image_id: str
    boundaries: List[int]   # Mutlak x koordinatları (görüntü piksel uzayında)
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 5000


class ManualPointsRequest(BaseModel):
    image_id: str
    points: List[int]   # Mutlak x koordinatları (noktasal ölçüm için)
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 5000


class ReportRequest(BaseModel):
    image_id: str
    measurement_table: List[dict]
    summary: dict
    include_image: bool = True
    min_section_width_px: int = 20
    gradient_threshold: float = 2.0
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 5000


class ROIRequest(BaseModel):
    image_id: str
    x: int
    y: int
    width: int
    height: int


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------
def _load_image(image_id: str, apply_roi: bool = True) -> np.ndarray:
    """Görüntüyü yükle, ROI varsa kırp."""
    safe_id = Path(image_id).name
    filepath = UPLOAD_DIR / safe_id
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Görüntü bulunamadı: {image_id}")
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=400, detail="Görüntü okunamadı")
    if apply_roi:
        roi = _get_roi(image_id)
        if roi:
            x, y, w, h = roi
            ih, iw = img.shape[:2]
            # Sınır kontrolü
            x = max(0, min(x, iw - 1))
            y = max(0, min(y, ih - 1))
            w = min(w, iw - x)
            h = min(h, ih - y)
            if w > 0 and h > 0:
                img = img[y:y+h, x:x+w]
    return img


def _image_to_base64(image: np.ndarray) -> str:
    _, buffer = cv2.imencode(".png", image)
    return base64.b64encode(buffer).decode("utf-8")


def _set_active_calibration(profile: CalibrationProfile, image_id: Optional[str] = None):
    """Kalibrasyonu global + varsa image_id bazlı kaydet."""
    global active_calibration
    active_calibration = profile
    if image_id:
        active_calibration_by_image[Path(image_id).name] = profile


def _get_active_calibration(image_id: Optional[str] = None) -> CalibrationProfile:
    """Varsa image_id'ye bağlı kalibrasyonu, yoksa global aktif kalibrasyonu döndür."""
    if image_id:
        return active_calibration_by_image.get(Path(image_id).name, active_calibration)
    return active_calibration


def _set_active_reference_layout(image_id: str, layout: dict):
    active_reference_layout_by_image[Path(image_id).name] = layout


def _get_active_reference_layout(image_id: Optional[str]) -> Optional[dict]:
    if not image_id:
        return None
    return active_reference_layout_by_image.get(Path(image_id).name)


def _set_roi(image_id: str, x: int, y: int, w: int, h: int):
    """ROI'yi image_id bazlı kaydet."""
    active_roi_by_image[Path(image_id).name] = (x, y, w, h)


def _get_roi(image_id: Optional[str]) -> Optional[tuple]:
    """Varsa image_id'ye bağlı ROI'yi döndür."""
    if not image_id:
        return None
    return active_roi_by_image.get(Path(image_id).name)


def _clear_roi(image_id: str):
    """ROI'yi temizle."""
    active_roi_by_image.pop(Path(image_id).name, None)


# ---------------------------------------------------------------------------
# ROI Endpoint'leri
# ---------------------------------------------------------------------------
@app.post("/api/roi/set")
async def set_roi(request: ROIRequest):
    """Görüntü için ROI (ilgi alanı) ayarla."""
    # Görüntünün var olduğunu kontrol et
    img = _load_image(request.image_id, apply_roi=False)
    ih, iw = img.shape[:2]
    # Sınır doğrulama
    x = max(0, min(request.x, iw - 1))
    y = max(0, min(request.y, ih - 1))
    w = min(request.width, iw - x)
    h = min(request.height, ih - y)
    if w <= 0 or h <= 0:
        raise HTTPException(status_code=400, detail="Geçersiz ROI boyutları")
    _set_roi(request.image_id, x, y, w, h)
    # Kalibrasyon sıfırla (ROI değişince ölçüler geçersiz olur)
    return {
        "ok": True,
        "roi": {"x": x, "y": y, "width": w, "height": h},
        "original_size": {"width": iw, "height": ih},
        "cropped_size": {"width": w, "height": h},
    }


@app.get("/api/roi/get")
async def get_roi(image_id: str):
    """Aktif ROI'yi döndür."""
    roi = _get_roi(image_id)
    if not roi:
        return {"active": False, "roi": None}
    x, y, w, h = roi
    return {"active": True, "roi": {"x": x, "y": y, "width": w, "height": h}}


@app.post("/api/roi/clear")
async def clear_roi(image_id: str):
    """ROI'yi temizle."""
    _clear_roi(image_id)
    return {"ok": True}


@app.get("/api/image/cropped")
async def get_cropped_image(image_id: str):
    """ROI uygulanmış (kırpılmış) görüntüyü base64 döndür."""
    img = _load_image(image_id, apply_roi=True)
    h, w = img.shape[:2]
    b64 = _image_to_base64(img)
    return {
        "image": f"data:image/png;base64,{b64}",
        "width": w,
        "height": h,
    }


# ---------------------------------------------------------------------------
# Faz 1 Endpoint'ler — Görüntü İşleme
# ---------------------------------------------------------------------------
@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/algorithms")
async def list_algorithms():
    return {"algorithms": get_algorithm_list()}


@app.post("/api/upload")
async def upload_image(file: UploadFile = File(...)):
    allowed = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(status_code=400, detail=f"Desteklenmeyen format: {ext}")

    image_id = f"{uuid.uuid4().hex}{ext}"
    filepath = UPLOAD_DIR / image_id

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    img = cv2.imread(str(filepath))
    if img is None:
        filepath.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Görüntü okunamadı")

    h, w = img.shape[:2]
    return {
        "image_id": image_id,
        "filename": file.filename,
        "width": w,
        "height": h,
        "size_kb": round(len(content) / 1024, 1),
        "url": f"/uploads/{image_id}",
    }


@app.post("/api/process")
async def process_image(request: ProcessRequest):
    img = _load_image(request.image_id)
    try:
        result = apply_algorithm(request.algorithm, img, request.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"İşleme hatası: {str(e)}")

    # İşlenmiş görüntüyü diske kaydet (kalibrasyon için kullanılabilir)
    ext = Path(request.image_id).suffix or ".png"
    proc_id = f"proc_{uuid.uuid4().hex}{ext}"
    proc_path = UPLOAD_DIR / proc_id
    cv2.imwrite(str(proc_path), result)

    result_b64 = _image_to_base64(result)
    return {
        "algorithm": request.algorithm,
        "params": request.params,
        "result_image": f"data:image/png;base64,{result_b64}",
        "result_width": result.shape[1],
        "result_height": result.shape[0],
        "processed_image_id": proc_id,
        "processed_url": f"/uploads/{proc_id}",
    }


@app.get("/api/image/{image_id}/info")
async def get_image_info(image_id: str):
    img = _load_image(image_id)
    h, w = img.shape[:2]
    channels = img.shape[2] if len(img.shape) == 3 else 1
    filepath = UPLOAD_DIR / Path(image_id).name
    return {
        "image_id": image_id,
        "width": w,
        "height": h,
        "channels": channels,
        "size_kb": round(filepath.stat().st_size / 1024, 1),
        "url": f"/uploads/{image_id}",
    }


# ---------------------------------------------------------------------------
# Faz 2 Endpoint'ler — Kenar Tespiti + Kalibrasyon
# ---------------------------------------------------------------------------
@app.post("/api/detect-edges")
async def detect_edges(request: EdgeDetectRequest):
    """
    Tıklanan x koordinatında parçanın üst ve alt kenarını otomatik tespit et.
    Kullanıcı tek tıklar → sistem kenarları bulur → kalibrasyon için kullanılır.
    """
    img = _load_image(request.image_id)
    h, w = img.shape[:2]
    click_x = int(round(request.click_x))
    click_y = int(round(request.click_y))

    if click_x < 0 or click_x >= w:
        raise HTTPException(status_code=400, detail=f"x koordinatı görüntü dışında: {click_x}")

    # Gri tonlama
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img.copy()

    # Görüntünün türünü belirle:
    # Kenar haritaları (Canny, Sobel, Laplacian vb.) genellikle çok koyu ortalama değere sahiptir
    # çünkü siyah arka plan üzerinde ince beyaz çizgiler vardır.
    # Normal parça görüntülerinde ise ortalama parlaklık çok daha yüksektir.
    mean_brightness = float(np.mean(gray))
    is_edge_map = mean_brightness < 40  # Kenar haritası heuristic (ortalama < 40/255)

    bk = request.blur_ksize if request.blur_ksize % 2 == 1 else request.blur_ksize + 1

    if is_edge_map:
        # ── Kenar Haritası Modu ──────────────────────────────────────────────
        # Canny/Sobel/Laplacian gibi çıktılar: siyah zemin, beyaz kenarlıklar
        # Beyaz pikselleri doğrudan bul — threshold ters çevirme yapmıyoruz.
        # Hafif dilatasyon ile ince çizgileri biraz kalınlaştır (daha stabil tespit)
        mk = request.morph_ksize if request.morph_ksize % 2 == 1 else request.morph_ksize + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        binary = cv2.dilate(gray, kernel, iterations=1)
        _, binary = cv2.threshold(binary, 20, 255, cv2.THRESH_BINARY)  # düşük eşik: kenarları yakala

        # Tıklanan kolondaki beyaz pikselleri bul → en üstteki ve en alttaki kenar
        col = binary[:, click_x]
        white_pixels = np.where(col > 0)[0]

        if len(white_pixels) == 0:
            for offset in range(1, 30):
                for dx in [click_x - offset, click_x + offset]:
                    if 0 <= dx < w:
                        col = binary[:, dx]
                        white_pixels = np.where(col > 0)[0]
                        if len(white_pixels) > 0:
                            click_x = dx
                            break
                if len(white_pixels) > 0:
                    break

        if len(white_pixels) == 0:
            raise HTTPException(
                status_code=400,
                detail="Bu noktada kenar bulunamadı. Daha az işlenmiş görsel kullanın veya farklı bir nokta deneyin."
            )

        # En üstteki ve en alttaki beyaz piksel = üst ve alt kenar
        top_y_raw = int(white_pixels[0])
        bottom_y_raw = int(white_pixels[-1])
        
        # KRİTİK FIX: Sub-pixel refinement ekle (profile_extractor ile tutarlı)
        # Kenar haritası modunda da orijinal gray üzerinde sub-pixel hesaplama
        top_y = _subpixel_edge_1d_polarity(gray[:, click_x], top_y_raw, search_window=4, edge="top")
        bottom_y = _subpixel_edge_1d_polarity(gray[:, click_x], bottom_y_raw, search_window=4, edge="bottom")

    else:
        # ── Normal Görüntü Modu ──────────────────────────────────────────────
        # Orijinal veya az işlenmiş görüntü: parça gövdesi tespit edilir.
        blurred = cv2.GaussianBlur(gray, (bk, bk), 0)
        _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        mk = request.morph_ksize if request.morph_ksize % 2 == 1 else request.morph_ksize + 1
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
        binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

        col = binary[:, click_x]
        white_pixels = np.where(col > 0)[0]

        if len(white_pixels) == 0:
            for offset in range(1, 21):
                for dx in [click_x - offset, click_x + offset]:
                    if 0 <= dx < w:
                        col = binary[:, dx]
                        white_pixels = np.where(col > 0)[0]
                        if len(white_pixels) > 0:
                            click_x = dx
                            break
                if len(white_pixels) > 0:
                    break

        if len(white_pixels) == 0:
            raise HTTPException(
                status_code=400,
                detail="Bu noktada parça kenarı tespit edilemedi. Farklı bir nokta deneyin."
            )

        top_y_raw = int(white_pixels[0])
        bottom_y_raw = int(white_pixels[-1])
        
        # KRİTİK FIX: Sub-pixel refinement ekle (profile_extractor ile tutarlı)
        top_y = _subpixel_edge_1d_polarity(gray[:, click_x], top_y_raw, search_window=4, edge="top")
        bottom_y = _subpixel_edge_1d_polarity(gray[:, click_x], bottom_y_raw, search_window=4, edge="bottom")

    pixel_distance = bottom_y - top_y

    # Overlay görüntüsü oluştur — kenar çizgilerini göster
    overlay = img.copy()
    # Çizim için integer koordinatlar (cv2.line int bekler)
    top_y_int = int(round(top_y))
    bottom_y_int = int(round(bottom_y))
    mid_y_int = (top_y_int + bottom_y_int) // 2
    
    # Dikey ölçüm çizgisi (kırmızı)
    cv2.line(overlay, (click_x, top_y_int), (click_x, bottom_y_int), (0, 0, 255), 2)
    # Üst/alt kenar işaretleri (yeşil yatay çizgi)
    cv2.line(overlay, (click_x - 20, top_y_int), (click_x + 20, top_y_int), (0, 255, 0), 2)
    cv2.line(overlay, (click_x - 20, bottom_y_int), (click_x + 20, bottom_y_int), (0, 255, 0), 2)
    # Ok uçları
    cv2.arrowedLine(overlay, (click_x, mid_y_int), (click_x, top_y_int), (0, 0, 255), 2, tipLength=0.03)
    cv2.arrowedLine(overlay, (click_x, mid_y_int), (click_x, bottom_y_int), (0, 0, 255), 2, tipLength=0.03)
    # Piksel mesafesi etiketi
    cv2.putText(overlay, f"{pixel_distance:.2f} px", (click_x + 10, mid_y_int),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 255), 2, cv2.LINE_AA)

    return {
        "top_y": top_y,
        "bottom_y": bottom_y,
        "click_x": click_x,
        "pixel_distance": pixel_distance,
        "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
    }

@app.post("/api/calibrate")
async def calibrate(request: CalibrateRequest):
    """İki nokta + bilinen ölçüden kalibrasyon hesapla."""
    try:
        profile = calculate_calibration_from_line(
            request.reference_mm, request.x1, request.y1, request.x2, request.y2
        )

        # Mevcut kalibrasyonda kullanıcının bağımsız olarak ayarladığı X değeri
        # varsa yeni profile aktar — böylece Y yeniden kalibre edilseyde X korunur.
        old_cal = _get_active_calibration(request.image_id)
        if old_cal and old_cal.x_is_calibrated:
            profile.set_x_calibration(old_cal.pixels_per_mm_x)

        _set_active_calibration(profile, request.image_id)

        if request.profile_name:
            profile.name = request.profile_name
            save_profile(profile, request.profile_name)

        return {
            "pixels_per_mm": round(profile.pixels_per_mm, 4),
            "pixels_per_mm_x": round(profile.pixels_per_mm_x, 4) if profile.pixels_per_mm_x else None,
            "x_calibrated": profile.x_is_calibrated,
            "reference_mm": request.reference_mm,
            "reference_pixels": round(profile.reference_pixels, 2),
            "saved": request.profile_name is not None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/manual")
async def calibrate_manual(request: ManualCalibrationRequest):
    """Manuel piksel/mm değerinden kalibrasyon."""
    if request.pixels_per_mm <= 0:
        raise HTTPException(status_code=400, detail="Piksel/mm değeri sıfırdan büyük olmalı")

    profile = CalibrationProfile(
        pixels_per_mm=request.pixels_per_mm,
        name=request.profile_name or "manual",
    )
    _set_active_calibration(profile, request.image_id)

    if request.profile_name:
        save_profile(profile, request.profile_name)

    return {
        "pixels_per_mm": profile.pixels_per_mm,
        "saved": request.profile_name is not None,
    }


@app.get("/api/calibration/current")
async def get_current_calibration(image_id: Optional[str] = None):
    """Aktif kalibrasyon durumunu döndür."""
    return _get_active_calibration(image_id).to_dict()


@app.get("/api/calibration/profiles")
async def get_calibration_profiles():
    """Kaydedilmiş kalibrasyon profillerini döndür."""
    return {"profiles": list_profiles()}


# ---------------------------------------------------------------------------
# Golden (Referans) Layout
# ---------------------------------------------------------------------------
@app.post("/api/reference-layout/set")
async def set_reference_layout(request: ReferenceLayoutSetRequest):
    """Verilen image_id için referans (golden) layout kaydet."""
    if not request.image_id:
        raise HTTPException(status_code=400, detail="image_id zorunludur")
    layout_dict = request.layout.model_dump()
    layout_dict["image_id"] = request.image_id
    _set_active_reference_layout(request.image_id, layout_dict)
    return {"ok": True, "image_id": Path(request.image_id).name, "layout": layout_dict}


@app.get("/api/reference-layout/current")
async def get_reference_layout_current(image_id: str):
    """Verilen image_id için aktif referans layout döndür."""
    layout = _get_active_reference_layout(image_id)
    if not layout:
        raise HTTPException(status_code=404, detail="Bu image_id için referans layout yok")
    return {"image_id": Path(image_id).name, "layout": layout}


@app.post("/api/calibration/load/{profile_name}")
async def load_calibration_profile(profile_name: str, image_id: Optional[str] = None):
    """Kaydedilmiş profili yükle."""
    try:
        profile = load_profile(profile_name)
        _set_active_calibration(profile, image_id)
        return profile.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profil bulunamadı: {profile_name}")


@app.post("/api/calibrate/x-axis")
async def calibrate_x_axis(request: XCalibrateRequest):
    """
    X-ekseni (yatay) kalibrasyonu: bilinen uzunluktaki bir bölümün
    iki x koordinatından X-ekseni piksel/mm oranını hesapla.
    Mevcut Y-ekseni kalibrasyonu korunur.
    """
    try:
        profile = _get_active_calibration(request.image_id)
        ppmm_x = calculate_x_calibration(
            request.reference_length_mm, request.x1, request.x2
        )
        profile.set_x_calibration(ppmm_x)
        _set_active_calibration(profile, request.image_id)

        if request.profile_name:
            profile.name = request.profile_name
            save_profile(profile, request.profile_name)

        return {
            "pixels_per_mm_x": round(ppmm_x, 4),
            "pixels_per_mm_y": round(profile.pixels_per_mm_y, 4),
            "reference_length_mm": request.reference_length_mm,
            "pixel_distance": round(abs(request.x2 - request.x1), 2),
            "saved": request.profile_name is not None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Faz 2 Endpoint'ler — Ölçüm
# ---------------------------------------------------------------------------
@app.post("/api/measure")
async def measure_part(request: MeasureRequest):
    """
    Parçanın profilini çıkar, bölümleri tespit et, ölçümleri hesapla.
    Sonucu overlay görüntüsü ve ölçüm tablosu olarak döndür.
    """
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)

    try:
        # 1. Profil çıkar
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        sections = None
        matched_features = None

        # 2. Bölümleri tespit et
        if request.mode == "golden":
            layout = request.reference_layout or _get_active_reference_layout(request.image_id)
            if not layout:
                raise HTTPException(status_code=400, detail="Golden ölçüm için reference_layout gerekli (veya image_id için set edilmeli)")
            golden = detect_sections_golden(
                profile, calibration, layout,
                min_section_width_px=request.min_section_width_px,
                gradient_threshold=request.gradient_threshold,
            )
            matched_features = golden.get("matched_features")
            # Overlay çizimi için minimal section benzeri veri türet
            sections = []
            for f in matched_features or []:
                if not f.get("found"):
                    continue
                if f.get("type") == "diameter":
                    sections.append({
                        "x_start_abs": f.get("x_start_abs"),
                        "x_end_abs": f.get("x_end_abs"),
                        "top_y_at_mid": f.get("top_y"),
                        "bottom_y_at_mid": f.get("bottom_y"),
                        "diameter_mm": f.get("measured_mm", 0),
                        "length_mm": 0,
                    })
        else:
            sections = detect_sections(
                profile, calibration,
                min_section_width_px=request.min_section_width_px,
                gradient_threshold=request.gradient_threshold,
            )

        # 3. Overlay çiz
        overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm, sections, matched_features=matched_features)

        # 4. Ölçüm tablosu
        if request.mode == "golden":
            # matched_features -> tablo satırları
            table = []
            for f in (matched_features or []):
                if not f.get("found"):
                    continue
                row_type = "Çap" if f.get("type") == "diameter" else "Uzunluk"
                prefix = "D" if f.get("type") == "diameter" else "L"
                table.append({
                    "id": f"{prefix}{str(f.get('id')).zfill(2)}",
                    "type": row_type,
                    "description": f"{prefix}{str(f.get('id')).zfill(2)}",
                    "nominal_mm": f.get("nominal_mm", f.get("measured_mm", 0)),
                    "measured_mm": float(f.get("measured_mm", 0)),
                    "deviation_mm": 0.0,
                    "feature_id": f.get("id"),
                })
            summary = {
                "total_sections": len(table),
                "mode": "golden",
            }
        else:
            table = generate_measurement_table(sections)
            summary = get_measurement_summary(sections)

        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "sections": sections,
            "measurement_table": table,
            "summary": summary,
            "calibration": calibration.to_dict(),
            "x_calibrated": calibration.x_is_calibrated,
            "mode": request.mode,
            "matched_features": matched_features,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ölçüm hatası: {str(e)}")


@app.post("/api/profile")
async def extract_part_profile(request: MeasureRequest):
    """Sadece profil çıkar — önizleme + önerilen sınırlar için."""
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)

    try:
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm)

        # Çap profili verisini seyrelterek gönder (her 5 pikselde bir)
        step = max(1, len(profile["diameter_px"]) // 200)
        diameter_sampled = profile["diameter_px"][::step]

        # Otomatik tespit edilen bölüm sınırlarını öner (manuel mod başlangıcı için)
        suggested_sections = detect_sections(
            profile, calibration,
            min_section_width_px=request.min_section_width_px,
            gradient_threshold=request.gradient_threshold,
        )
        # Sınır noktaları: her bölümün sol kenarı + son bölümün sağ kenarı
        suggested_boundaries = []
        for sec in suggested_sections:
            suggested_boundaries.append(sec["x_start_abs"])
        if suggested_sections:
            suggested_boundaries.append(suggested_sections[-1]["x_end_abs"])

        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "diameter_profile": [float(d) for d in diameter_sampled],
            "x_start": profile["x_start"],
            "x_end": profile["x_end"],
            "bbox": list(profile["bbox"]),
            "suggested_boundaries": suggested_boundaries,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profil hatası: {str(e)}")


@app.post("/api/measure/manual-boundaries")
async def measure_with_manual_boundaries(request: ManualBoundariesRequest):
    """
    Kullanıcının elle belirlediği x sınır pozisyonlarından ölçüm yap.
    Sınırlar, görüntü koordinatlarındaki mutlak x değerleridir.
    """
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)

    if not request.boundaries:
        raise HTTPException(status_code=400, detail="En az bir sınır noktası gerekli")

    try:
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        sections = compute_sections_from_boundaries(profile, calibration, request.boundaries)

        overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm, sections)
        table = generate_measurement_table(sections)
        summary = get_measurement_summary(sections)

        # Her bölümün piksel ve mm bilgisini debug için sections'a ekle
        sorted_bounds = sorted(request.boundaries)
        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "sections": sections,
            "measurement_table": table,
            "summary": summary,
            "calibration": calibration.to_dict(),
            "x_calibrated": calibration.x_is_calibrated,
            "mode": "manual",
            "boundaries_used": sorted_bounds,
            "pixels_per_mm_x": round(calibration.pixels_per_mm_x, 4) if calibration.pixels_per_mm_x else None,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Manuel ölçüm hatası: {str(e)}")


@app.post("/api/measure/points")
async def measure_at_points(request: ManualPointsRequest):
    """
    Kullanıcının tıkladığı spesifik x koordinatlarında ölçüm yap.
    """
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)

    if not request.points:
        raise HTTPException(status_code=400, detail="En az bir ölçüm noktası gerekli")

    try:
        # 1. Profil çıkar
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        x_start = profile["x_start"]
        x_end = profile["x_end"]
        top_edge = profile["top_edge"]
        bottom_edge = profile["bottom_edge"]
        
        point_measurements = []
        table = []
        
        for i, px in enumerate(request.points):
            # Koordinat parça sınırları içindeyse ölçüm yap
            if x_start <= px < x_end:
                idx = px - x_start
                ty = top_edge[idx]
                by = bottom_edge[idx]
                if ty is not None and by is not None:
                    diameter_px = by - ty
                    diameter_mm = calibration.pixels_to_mm_y(diameter_px)
                    
                    point_measurements.append({
                        "id": i + 1,
                        "x_abs": px,
                        "top_y": ty,
                        "bottom_y": by,
                        "diameter_mm": round(diameter_mm, 4)
                    })
                    
                    table.append({
                        "id": f"P{i+1:02d}",
                        "type": "Noktasal Çap",
                        "description": f"X={px} noktasındaki çap",
                        "nominal_mm": round(diameter_mm, 4),
                        "measured_mm": round(diameter_mm, 4) ,
                        "deviation_mm": 0.0,
                        "x_abs": px
                    })

        # Section formatına benzeterek çizdir (opsiyonel)
        # Veya draw_profile_overlay'e point_measurements desteği ekle
        overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm, point_measurements=point_measurements)
        
        summary = {
            "total_points": len(table),
            "mode": "points"
        }

        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "point_measurements": point_measurements,
            "measurement_table": table,
            "summary": summary,
            "calibration": calibration.to_dict(),
            "mode": "points"
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Noktasal ölçüm hatası: {str(e)}")


# ---------------------------------------------------------------------------
# Faz 3 Endpoint'ler — Rapor & İndirme
# ---------------------------------------------------------------------------
@app.post("/api/report/pdf")
async def download_pdf_report(request: ReportRequest):
    """PDF ölçüm raporu oluştur ve indir."""
    calibration = _get_active_calibration(request.image_id)
    # Overlay görüntüsü oluştur (rapora eklemek için)
    overlay_path = None
    if request.include_image:
        try:
            img = _load_image(request.image_id)
            profile = extract_profile(img, {
                "blur_ksize": request.blur_ksize,
                "morph_ksize": request.morph_ksize,
                "min_contour_area": request.min_contour_area,
            })
            sections = detect_sections(
                profile, calibration,
                min_section_width_px=request.min_section_width_px,
                gradient_threshold=request.gradient_threshold,
            )
            overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm, sections)
            overlay_path = str(REPORTS_DIR / f"overlay_{request.image_id}")
            cv2.imwrite(overlay_path, overlay)
        except Exception:
            overlay_path = None

    cal_info = calibration.to_dict()
    pdf_bytes = generate_pdf_report(
        measurement_table=request.measurement_table,
        summary=request.summary,
        calibration_info=cal_info,
        image_path=overlay_path,
    )

    # Geçici overlay dosyasını temizle
    if overlay_path and os.path.exists(overlay_path):
        os.remove(overlay_path)

    from fastapi.responses import Response
    from datetime import datetime
    filename = f"olcum_raporu_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/report/excel")
async def download_excel_report(request: ReportRequest):
    """Excel ölçüm raporu oluştur ve indir."""
    cal_info = _get_active_calibration(request.image_id).to_dict()
    excel_bytes = generate_excel_report(
        measurement_table=request.measurement_table,
        summary=request.summary,
        calibration_info=cal_info,
    )

    from fastapi.responses import Response
    from datetime import datetime
    filename = f"olcum_raporu_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.post("/api/download-image")
async def download_processed_image(request: MeasureRequest):
    """İşlenmiş (ölçüm overlay) görüntüyü PNG olarak indir."""
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)
    try:
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })
        sections = detect_sections(
            profile, calibration,
            min_section_width_px=request.min_section_width_px,
            gradient_threshold=request.gradient_threshold,
        )
        overlay = draw_profile_overlay(img, profile, calibration.pixels_per_mm, sections)

        _, png_data = cv2.imencode(".png", overlay)

        from fastapi.responses import Response
        from datetime import datetime
        filename = f"olcum_gorsel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        return Response(
            content=png_data.tobytes(),
            media_type="image/png",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Görüntü indirme hatası: {str(e)}")


# ---------------------------------------------------------------------------
# SABİT ÖLÇÜM NOKTALARI ENDPOINT'LERİ
# ---------------------------------------------------------------------------
class FixedMeasurementRequest(BaseModel):
    """Sabit ölçüm noktaları isteği"""
    image_id: str
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 100
    min_section_width_px: int = 20
    gradient_threshold: Optional[float] = None


class UpdatePointRequest(BaseModel):
    """Şablondaki bir noktayı güncelleme isteği"""
    point_code: str
    new_x_abs: Optional[int] = None
    new_nominal_mm: Optional[float] = None
    new_lower_tol: Optional[float] = None
    new_upper_tol: Optional[float] = None


@app.post("/api/template/update-point")
async def update_template_point(request: UpdatePointRequest):
    """Şablondaki belirli bir ölçüm noktasının parametrelerini günceller."""
    template_path = PROJECT_DIR / "backend" / "fixed_measurement_template.json"
    
    if not template_path.exists():
        raise HTTPException(status_code=404, detail="Şablon dosyası bulunamadı.")
    
    import json
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        points = data.get('measurement_points', [])
        found = False
        for p in points:
            if p.get('code') == request.point_code:
                if request.new_x_abs is not None:
                    p['x_abs'] = request.new_x_abs
                    # Açıklamayı otomatik güncelle
                    if p.get('x_mode') == 'absolute_image':
                        p['description'] = f"Ölçüm (Görüntü x={request.new_x_abs})"
                    elif "Sol uçtan x=" in p.get('description', ''):
                        p['description'] = f"Ölçüm (Sol uçtan x={request.new_x_abs})"
                
                if request.new_nominal_mm is not None:
                    p['nominal_mm'] = request.new_nominal_mm
                
                if request.new_lower_tol is not None:
                    p['lower_tol_mm'] = request.new_lower_tol
                    
                if request.new_upper_tol is not None:
                    p['upper_tol_mm'] = request.new_upper_tol
                    
                found = True
                break
        
        if not found:
            raise HTTPException(status_code=404, detail=f"Kod: {request.point_code} olan nokta şablonda bulunamadı.")
            
        with open(template_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            
        return {"success": True, "message": f"{request.point_code} güncellendi."}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şablon güncelleme hatası: {str(e)}")


@app.post("/api/measure/fixed")
async def measure_fixed_points(request: FixedMeasurementRequest):
    """
    Teknik çizimdeki sabit ölçüm noktalarında (03, 04, 05, 06, 08, 17, 18, 21, 22, 24)
    bölüm-tabanlı ölçüm yapar ve pass/fail değerlendirmesi yapar.
    
    Yöntem:
    1. Profil çıkar (parça silüeti)
    2. Bölümleri tespit et (otomatik gradient analizi)
    3. Template'deki section_index ile bölümleri eşle
    4. Her nokta için ölçümü ilgili bölümden al
    """
    img = _load_image(request.image_id)
    calibration = _get_active_calibration(request.image_id)
    
    if calibration is None:
        raise HTTPException(
            status_code=400,
            detail="Kalibrasyon yapılmamış. Önce Y ekseni kalibrasyonu yapın."
        )
    
    try:
        y_calibration = calibration.pixels_per_mm if calibration.pixels_per_mm else 10.0
        x_calibration = calibration.pixels_per_mm_x if calibration.pixels_per_mm_x else y_calibration
        
        # 1. Profil çıkar
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })
        
        # 2. Bölümleri tespit et (mevcut detect_sections ile)
        sections = detect_sections(
            profile, calibration,
            min_section_width_px=request.min_section_width_px,
            gradient_threshold=request.gradient_threshold,
        )
        
        print(f"[Sabit Ölçüm] Tespit edilen bölüm sayısı: {len(sections)}")
        for i, sec in enumerate(sections):
            print(f"  Bölüm {i}: x={sec['x_start_abs']}-{sec['x_end_abs']} "
                  f"çap={sec['diameter_mm']:.3f}mm uzunluk={sec['length_mm']:.3f}mm")
        
        # 3. Sabit ölçüm motorunu başlat
        engine = load_default_template()
        
        # 4. Ölçümleri yap — bölüm listesini de gönder
        results = engine.perform_measurements(
            profile, sections, y_calibration, x_calibration
        )
        
        # 5. Rapor verisi oluştur
        report = engine.generate_report_data(results)
        
        # 6. Overlay görüntüsü oluştur
        # Sabit ölçüm modunda tam ölçümdeki bölüm çizgileri görünmemeli;
        # sadece profil ve aşağıda çizilen sabit ölçü işaretleri gösterilir.
        overlay = draw_profile_overlay(img, profile, y_calibration)
        
        # Ölçüm noktalarını overlay üzerine çiz
        for m in report['measurements']:
            color = (0, 255, 0) if m['status'] == 'PASS' else (0, 0, 255)
            x_start_px = m.get('x_pixel_start')
            x_end_px = m.get('x_pixel_end')
            top_y = m.get('top_y')
            bottom_y = m.get('bottom_y')
            
            if m['type'] == 'diameter' and x_start_px is not None and x_end_px is not None:
                # Ölçüm motoru stabil bir banda snap etmiş olabilir; varsa gerçek kullanılan X'i çiz.
                mid_x = int(m.get('x_used_abs') or ((x_start_px + x_end_px) // 2))
                
                # Çap çizgisi (dikey ok)
                if top_y is not None and bottom_y is not None:
                    ity = int(round(top_y))
                    iby = int(round(bottom_y))
                    cv2.line(overlay, (mid_x, ity), (mid_x, iby), color, 2, cv2.LINE_AA)
                    cv2.arrowedLine(overlay, (mid_x, (ity + iby) // 2), (mid_x, ity), color, 2, tipLength=0.06)
                    cv2.arrowedLine(overlay, (mid_x, (ity + iby) // 2), (mid_x, iby), color, 2, tipLength=0.06)
                
                # Etiket
                label_y = max(24, int(round(top_y)) - 20) if top_y is not None else 40
                
                # Arka plan gölgesi
                cv2.putText(overlay, m['code'], (mid_x - 11, label_y + 1),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(overlay, m['code'], (mid_x - 12, label_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
            
            elif m['type'] == 'length' and x_start_px is not None and x_end_px is not None:
                # Uzunluk çizgileri için renk ve yükseklik ayarı (Stacked and color-coded)
                code = m['code']
                h = overlay.shape[0]
                
                # Renk ve Y pozisyonu seçimi
                if code == "21": # Sarı (En alt)
                    l_color = (0, 255, 255)
                    y_line = h - 20
                elif code == "22": # Yeşil (Orta)
                    l_color = (0, 255, 0)
                    y_line = h - 40
                elif code == "24": # Mavi (En üst)
                    l_color = (255, 120, 0)
                    y_line = h - 60
                else:
                    l_color = color # Varsayılan PASS/FAIL rengi
                    y_line = h - 80
                
                # Yatay çizgi
                cv2.line(overlay, (x_start_px, y_line), (x_end_px, y_line), l_color, 2)
                
                # Sınır "tick" işaretleri (dikey kısa çizgiler)
                tick_h = 5
                cv2.line(overlay, (x_start_px, y_line - tick_h), (x_start_px, y_line + tick_h), l_color, 2)
                cv2.line(overlay, (x_end_px, y_line - tick_h), (x_end_px, y_line + tick_h), l_color, 2)
                
                # Ok uçları
                cv2.arrowedLine(overlay, ((x_start_px + x_end_px) // 2 + 10, y_line),
                               (x_start_px, y_line), l_color, 2, tipLength=0.03)
                cv2.arrowedLine(overlay, ((x_start_px + x_end_px) // 2 - 10, y_line),
                               (x_end_px, y_line), l_color, 2, tipLength=0.03)
                
                # Etiket (Siyah arka planlı küçük font)
                l_text = f"{m['code']}: {m['measured']}mm"
                l_size, _ = cv2.getTextSize(l_text, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
                tx = (x_start_px + x_end_px) // 2 - l_size[0] // 2
                ty = y_line - 8
                
                # Arka plan gölgesi
                cv2.putText(overlay, l_text, (tx + 1, ty + 1), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.putText(overlay, l_text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, 0.4, l_color, 1, cv2.LINE_AA)
        
        return {
            "success": True,
            "template_id": report['template_id'],
            "description": report['description'],
            "measurements": report['measurements'],
            "summary": report['summary'],
            "sections_detected": len(sections),
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "calibration": {
                "y_pixels_per_mm": y_calibration,
                "x_pixels_per_mm": x_calibration
            }
        }
        
    except Exception as e:
        import traceback
        print(f"Sabit ölçüm hatası: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Sabit ölçüm hatası: {str(e)}")


@app.get("/api/templates")
async def get_templates():
    """Mevcut ölçüm şablonlarını listeler."""
    try:
        engine = load_default_template()
        return {
            "templates": [
                {
                    "id": engine.template.get('template_id'),
                    "description": engine.template.get('description'),
                    "measurement_count": len(engine.measurement_points),
                    "points": [
                        {
                            "code": p['code'],
                            "description": p['description'],
                            "nominal": p['nominal_mm'],
                            "tolerance": f"{p['lower_tol_mm']:+.4f} / {p['upper_tol_mm']:+.4f}"
                        }
                        for p in engine.measurement_points
                    ]
                }
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Şablon listesi hatası: {str(e)}")


# ---------------------------------------------------------------------------
# Sunucu
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
