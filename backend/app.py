"""
CNC Parça Ölçüm Sistemi — FastAPI Backend
Görüntü yükleme, işleme ve ölçüm API'si.
Frontend dosyaları ../frontend/ klasöründen serve edilir.
"""

import os
import uuid
import base64
from pathlib import Path
from typing import Optional, List

import cv2
import numpy as np
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from image_processing import get_algorithm_list, apply_algorithm
from calibration import (
    CalibrationProfile, calculate_calibration, calculate_calibration_from_line,
    save_profile, load_profile, list_profiles,
)
from profile_extractor import extract_profile, draw_profile_overlay
from measurement_engine import detect_sections, generate_measurement_table, get_measurement_summary
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


# ---------------------------------------------------------------------------
# Modeller
# ---------------------------------------------------------------------------
class ProcessRequest(BaseModel):
    image_id: str
    algorithm: str
    params: dict = {}


class CalibrateRequest(BaseModel):
    reference_mm: float
    x1: float
    y1: float
    x2: float
    y2: float
    profile_name: Optional[str] = None


class MeasureRequest(BaseModel):
    image_id: str
    min_section_width_px: int = 20
    gradient_threshold: float = 2.0
    blur_ksize: int = 5
    morph_ksize: int = 5
    min_contour_area: int = 5000


class ManualCalibrationRequest(BaseModel):
    pixels_per_mm: float
    profile_name: Optional[str] = None


class EdgeDetectRequest(BaseModel):
    image_id: str
    click_x: float
    click_y: float
    blur_ksize: int = 5
    morph_ksize: int = 5


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

    result_b64 = _image_to_base64(result)
    return {
        "algorithm": request.algorithm,
        "params": request.params,
        "result_image": f"data:image/png;base64,{result_b64}",
        "result_width": result.shape[1],
        "result_height": result.shape[0],
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

    # Blur + Otsu threshold
    bk = request.blur_ksize if request.blur_ksize % 2 == 1 else request.blur_ksize + 1
    blurred = cv2.GaussianBlur(gray, (bk, bk), 0)
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morfolojik temizleme
    mk = request.morph_ksize if request.morph_ksize % 2 == 1 else request.morph_ksize + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (mk, mk))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # Tıklanan x kolonundaki beyaz pikselleri bul
    col = binary[:, click_x]
    white_pixels = np.where(col > 0)[0]

    if len(white_pixels) == 0:
        # Yakın kolonlarda da ara (±20 piksel)
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
        raise HTTPException(status_code=400, detail="Bu noktada parça kenarı tespit edilemedi. Farklı bir nokta deneyin.")

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
    global active_calibration
    try:
        profile = calculate_calibration_from_line(
            request.reference_mm, request.x1, request.y1, request.x2, request.y2
        )
        active_calibration = profile

        if request.profile_name:
            profile.name = request.profile_name
            save_profile(profile, request.profile_name)

        return {
            "pixels_per_mm": round(profile.pixels_per_mm, 4),
            "reference_mm": request.reference_mm,
            "reference_pixels": round(profile.reference_pixels, 2),
            "saved": request.profile_name is not None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/calibrate/manual")
async def calibrate_manual(request: ManualCalibrationRequest):
    """Manuel piksel/mm değerinden kalibrasyon."""
    global active_calibration
    if request.pixels_per_mm <= 0:
        raise HTTPException(status_code=400, detail="Piksel/mm değeri sıfırdan büyük olmalı")

    active_calibration = CalibrationProfile(
        pixels_per_mm=request.pixels_per_mm,
        name=request.profile_name or "manual",
    )

    if request.profile_name:
        save_profile(active_calibration, request.profile_name)

    return {
        "pixels_per_mm": active_calibration.pixels_per_mm,
        "saved": request.profile_name is not None,
    }


@app.get("/api/calibration/current")
async def get_current_calibration():
    """Aktif kalibrasyon durumunu döndür."""
    return active_calibration.to_dict()


@app.get("/api/calibration/profiles")
async def get_calibration_profiles():
    """Kaydedilmiş kalibrasyon profillerini döndür."""
    return {"profiles": list_profiles()}


@app.post("/api/calibration/load/{profile_name}")
async def load_calibration_profile(profile_name: str):
    """Kaydedilmiş profili yükle."""
    global active_calibration
    try:
        active_calibration = load_profile(profile_name)
        return active_calibration.to_dict()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Profil bulunamadı: {profile_name}")


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

    try:
        # 1. Profil çıkar
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        # 2. Bölümleri tespit et
        sections = detect_sections(
            profile, active_calibration,
            min_section_width_px=request.min_section_width_px,
            gradient_threshold=request.gradient_threshold,
        )

        # 3. Overlay çiz
        overlay = draw_profile_overlay(img, profile, active_calibration.pixels_per_mm, sections)

        # 4. Ölçüm tablosu
        table = generate_measurement_table(sections)
        summary = get_measurement_summary(sections)

        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "sections": sections,
            "measurement_table": table,
            "summary": summary,
            "calibration": active_calibration.to_dict(),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ölçüm hatası: {str(e)}")


@app.post("/api/profile")
async def extract_part_profile(request: MeasureRequest):
    """Sadece profil çıkar (bölüm tespiti olmadan) — önizleme için."""
    img = _load_image(request.image_id)

    try:
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })

        overlay = draw_profile_overlay(img, profile, active_calibration.pixels_per_mm)

        # Çap profili verisini seyrelterek gönder (her 5 pikselde bir)
        step = max(1, len(profile["diameter_px"]) // 200)
        diameter_sampled = profile["diameter_px"][::step]

        return {
            "overlay_image": f"data:image/png;base64,{_image_to_base64(overlay)}",
            "diameter_profile": [float(d) for d in diameter_sampled],
            "x_start": profile["x_start"],
            "x_end": profile["x_end"],
            "bbox": list(profile["bbox"]),
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Profil hatası: {str(e)}")


# ---------------------------------------------------------------------------
# Faz 3 Endpoint'ler — Rapor & İndirme
# ---------------------------------------------------------------------------
@app.post("/api/report/pdf")
async def download_pdf_report(request: ReportRequest):
    """PDF ölçüm raporu oluştur ve indir."""
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
                profile, active_calibration,
                min_section_width_px=request.min_section_width_px,
                gradient_threshold=request.gradient_threshold,
            )
            overlay = draw_profile_overlay(img, profile, active_calibration.pixels_per_mm, sections)
            overlay_path = str(REPORTS_DIR / f"overlay_{request.image_id}")
            cv2.imwrite(overlay_path, overlay)
        except Exception:
            overlay_path = None

    cal_info = active_calibration.to_dict()
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
    cal_info = active_calibration.to_dict()
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
    try:
        profile = extract_profile(img, {
            "blur_ksize": request.blur_ksize,
            "morph_ksize": request.morph_ksize,
            "min_contour_area": request.min_contour_area,
        })
        sections = detect_sections(
            profile, active_calibration,
            min_section_width_px=request.min_section_width_px,
            gradient_threshold=request.gradient_threshold,
        )
        overlay = draw_profile_overlay(img, profile, active_calibration.pixels_per_mm, sections)

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
