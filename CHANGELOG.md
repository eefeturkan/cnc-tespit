# CNC Parça Ölçüm Sistemi — Değişiklik Günlüğü

> Bu dosya her değişiklik sonrası güncellenir.

---

## [v3.0] — 2026-03-04

### Faz 3: Rapor Çıktısı

**Yeni Özellikler:**
- `backend/report_generator.py` eklendi (`reportlab` ile PDF, `openpyxl` ile Excel raporları).
- **Yeni API Endpoint'leri:**
  - `/api/report/pdf` — PDF ölçüm raporu.
  - `/api/report/excel` — Excel ölçüm raporu (tablo ve metadata).
  - `/api/download-image` — İşlenmiş/Overlay ölçüm görüntüsünü PNG olarak indirme.

**Frontend Güncellemeleri:**
- Ölçüm sekmesindeki tablo paneline 3 adet indirme butonu eklendi: 🖼️ Görsel, 📄 PDF, 📊 Excel.
- `app.js` içerisine Javascript Fetch Blob API'si ile dosya indirme fonksiyonları yazıldı.

---

## [v2.0] — 2026-03-04

### Faz 2: Kalibrasyon & Ölçüm Motoru

**Yeni Backend Modülleri:**
- `backend/calibration.py` — Piksel/mm oranı hesaplama, profil kaydet/yükle
- `backend/profile_extractor.py` — Otsu threshold + morfoloji ile parça silüeti çıkarma, üst/alt kenar tespiti
- `backend/measurement_engine.py` — Gradient analizi ile bölüm tespiti, çap/boy ölçüm, VICIVISION-tarzı tablo çıktısı

**Yeni API Endpoint'leri (8 adet):**
| Endpoint | Yöntem | Açıklama |
|---|---|---|
| `/api/detect-edges` | POST | Tek tıklama ile parça kenarlarını otomatik tespit eder |
| `/api/calibrate` | POST | İki nokta + bilinen ölçüden kalibrasyon hesaplar |
| `/api/calibrate/manual` | POST | Manuel piksel/mm oranı ile kalibrasyon |
| `/api/calibration/current` | GET | Aktif kalibrasyonu döner |
| `/api/calibration/profiles` | GET | Kayıtlı kalibrasyon profillerini listeler |
| `/api/calibration/load/{name}` | POST | Kayıtlı profili yükler |
| `/api/measure` | POST | Tam ölçüm: profil + bölüm tespiti + çap/boy tablosu |
| `/api/profile` | POST | Sadece profil çıkarma (overlay önizleme) |

**Frontend Güncellemeleri:**
- 3 sekmeli sidebar: Algoritmalar, Kalibrasyon, Ölçüm
- Kalibrasyon: "Otomatik Kenar" modu — tek tıkla kenar tespit + "Manuel" px/mm girişi
- Ölçüm paneli: 5 parametre slider + Profil Çıkar / Tam Ölçüm butonları
- Ölçüm sonuç tablosu: D01/L01 formatında çap ve uzunluk değerleri

---

## [v1.0] — 2026-03-04

### Faz 1: Temel Altyapı & Görüntü İşleme

**Proje Yapısı:**
```
cnc-tespit/
├── backend/
│   ├── app.py              # FastAPI ana uygulama
│   ├── image_processing.py # 12 görüntü işleme algoritması
│   └── requirements.txt
├── frontend/
│   ├── index.html
│   ├── css/style.css        # Industrial Dark tema
│   └── js/app.js
└── uploads/
```

**Backend:**
- FastAPI + CORS + statik dosya sunumu
- Görüntü yükleme (`/api/upload`)
- Algoritma listeleme (`/api/algorithms`)
- Görüntü işleme (`/api/process`)

**12 Görüntü İşleme Algoritması:**
Grayscale, Gaussian Blur, Canny Edge, Sobel Edge, Laplacian Edge, Adaptive Threshold, Otsu Threshold, Morfolojik İşlemler, Kontur Tespiti, Hough Çizgi, CLAHE, Bilateral Filter

**Frontend:**
- Sürükle-bırak dosya yükleme
- Algoritmalar listesi + dinamik parametre kontrolleri
- Yan yana / tek görünüm modu
- Industrial Dark tema (JetBrains Mono + DM Sans)
