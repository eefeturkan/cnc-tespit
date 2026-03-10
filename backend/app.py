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
from profile_extractor import extract_profile, draw_profile_overlay
from measurement_engine import (
    detect_sections,
    detect_sections_golden,
    compute_sections_from_boundaries,
    generate_measurement_table,
    get_measurement_summary,
)
from report_generator import generate_pdf_report, generate_excel_report

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


# ---------------------------------------------------------------------------
# Yardımcı
# ---------------------------------------------------------------------------
def _load_image(image_id: str) -> np.ndarray:
    safe_id = Path(image_id).name
    filepath = UPLOAD_DIR / safe_id
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Görüntü bulunamadı: {image_id}")
    img = cv2.imread(str(filepath))
    if img is None:
        raise HTTPException(status_code=400, detail="Görüntü okunamadı")
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
        top_y = int(white_pixels[0])
        bottom_y = int(white_pixels[-1])

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

        top_y = int(white_pixels[0])
        bottom_y = int(white_pixels[-1])

    pixel_distance = bottom_y - top_y

    # Overlay görüntüsü oluştur — kenar çizgilerini göster
    overlay = img.copy()
    # Dikey ölçüm çizgisi (kırmızı)
    cv2.line(overlay, (click_x, top_y), (click_x, bottom_y), (0, 0, 255), 2)
    # Üst/alt kenar işaretleri (yeşil yatay çizgi)
    cv2.line(overlay, (click_x - 20, top_y), (click_x + 20, top_y), (0, 255, 0), 2)
    cv2.line(overlay, (click_x - 20, bottom_y), (click_x + 20, bottom_y), (0, 255, 0), 2)
    # Ok uçları
    cv2.arrowedLine(overlay, (click_x, (top_y + bottom_y) // 2), (click_x, top_y), (0, 0, 255), 2, tipLength=0.03)
    cv2.arrowedLine(overlay, (click_x, (top_y + bottom_y) // 2), (click_x, bottom_y), (0, 0, 255), 2, tipLength=0.03)
    # Piksel mesafesi etiketi
    cv2.putText(overlay, f"{pixel_distance} px", (click_x + 10, (top_y + bottom_y) // 2),
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
# Sunucu
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
