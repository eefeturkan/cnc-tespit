# CNC Parça Ölçüm Sistemi — Ajan Rehberi

## Proje Özeti
Silindirik CNC parçalarının fotoğraflarından çap ve uzunluk ölçümü yapan web tabanlı görüntü işleme sistemi.

## Teknoloji
- **Backend:** Python, FastAPI, OpenCV, NumPy, SciPy
- **Frontend:** HTML, CSS (vanilla), JavaScript (vanilla)
- **Sunucu:** `uvicorn` (port 8000, --reload)

## Klasör Yapısı
```
backend/     → app.py, image_processing.py, calibration.py, profile_extractor.py, measurement_engine.py
frontend/    → index.html, css/style.css, js/app.js
uploads/     → Yüklenen görüntüler
```

## Kurallar
1. `CHANGELOG.md` her değişiklikten sonra güncellenmelidir
2. Backend FastAPI, frontend vanilla JS — framework kullanılmaz
3. CSS teması: Industrial Dark (JetBrains Mono + DM Sans)
4. Tüm UI metinleri Türkçe
5. Dosya yapısı: `backend/` ve `frontend/` ayrımına uy
6. Sunucu başlatma: `cd backend && python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload`

## Mevcut Durum
- **Faz 1** ✅ Görüntü işleme (12 algoritma)
- **Faz 2** ✅ Kalibrasyon + Ölçüm motoru
- **Faz 3** ⬜ Rapor çıktısı (PDF/Excel)
- **Faz 4** ⬜ Polish & Optimizasyon
