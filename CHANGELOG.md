# CNC Parça Ölçüm Sistemi — Değişiklik Günlüğü

> Bu dosya her değişiklik sonrası güncellenir.

---

## [v4.10] — 2026-03-09

### scipy Eksikliği + X Kalibrasyon Görsel Geri Bildirim

- **Sorun 1:** `No module named 'scipy'` hatası — ölçüm tamamen duruyordu.
- **Çözüm 1:** `scipy` paketi sanal ortama kuruldu.
- **Sorun 2:** X-ekseni kalibrasyon modunda görüntüye tıklarken kullanıcı nereye bastığını göremiyordu.
- **Çözüm 2:**
  - Her iki görüntü paneline (orijinal + işlenmiş) şeffaf canvas overlay eklendi (`.xcal-overlay-canvas`).
  - 1. tıklamada sarı kesikli dikey çizgi + "X1" etiketi, 2. tıklamada turuncu "X2" çizgisi çiziliyor.
  - İki nokta seçilince arası sarı yarı-saydam bant ve piksel mesafe etiketi gösteriliyor.
  - X-kalibrasyon modu aktifken image panel'leri turuncu outline alıyor ve cursor `col-resize` oluyor.
  - Sekme değişince veya sıfırlanınca canvas temizleniyor; kalibrasyon sekmesine dönünce işaretler yeniden çiziliyor.

---

## [v4.9] — 2026-03-09

### X-Ekseni (Uzunluk) Gerçek Kalibrasyon UI

- **Sorun:** Uzunluk ölçümleri, Y-ekseni (çap) kalibrasyonundan türetilen sabit bir `ASPECT_CORRECTION_FACTOR = 1.2762` ile hesaplanıyordu. Bu faktör tek bir ölçümden alınmış ve tüm görüntülere uygulanıyordu; farklı kameralar veya farklı kırpma oranlarında yanlış uzunluk sonuçları veriyordu.
- **Çözüm:**
  - Kalibrasyon sekmesine **X-Ekseni Uzunluk Kalibrasyonu** bölümü eklendi.
  - Y-ekseni kalibrasyonu tamamlandıktan sonra bu bölüm otomatik açılır.
  - Kullanıcı görüntü üzerindeki bilinen uzunlukta bir bölümün **sol kenarına** (1. tık), ardından **sağ kenarına** (2. tık) tıklar.
  - Gerçek uzunluk mm olarak girilip "X-Eksenini Kalibre Et" butonuna basılır.
  - Adım adım görsel durum göstergesi (1 → 2 tık akışı) ve ↺ sıfırlama butonu eklendi.
- **Backend:** `CalibrationProfile`'a `_x_user_calibrated` flag'i eklendi; `set_x_calibration()` çağrıldığında X kullanıcı kalibrasyonu olarak işaretlenir, `set_y_calibration()` artık kullanıcı kalibre etmişse X değerini ezmez.
- **Uyarı:** Ölçüm yapılırken X ekseni kalibre edilmemişse "X-ekseni kalibre edilmedi — uzunluk ölçümleri yaklaşık olacak" uyarısı gösterilir.
- **API:** `/api/measure` yanıtına `x_calibrated: bool` alanı eklendi.

---

## [v4.8] — 2026-03-06

### PDF CMM Tasarımı ve Türkçe Font (UTF-8) Modülü 
- **Sorun:** PDF çıktılarında `ı, ş, ğ` harfleri bozuk görünüyordu ve rapor düz metin hissi veriyordu.
- **Çözüm:** 
  - Proje kaynak koduna `Roboto` TrueType (TTF) fontu çekilerek `ReportLab` eklentisine kurumsal font gömüldü.
  - Endüstriyel Kalite Kontrol (CMM / Zeiss) makine formlarında profesyonel bir PDF Header / Footer çizildi. 
  - Ölçüm tablosundaki PASS/FAIL değerlerine kırmızı/yeşil Arkaplanlı rozet (Badge) tasarımı giydirilerek metin renkleri beyaza çekildi. Böylece daha okunabilir profesyonel bir PDF çıktısı sağlandı.
  - Her PDF sayfasına `NEXORA®` marka ismi ve "Sayfa 1 / 1" numerikleri işlendi.

---

## [v4.7] — 2026-03-05

### Tolerans Yönetimi ve Referans Parça Uygunluğu (Pass/Fail)
- **Sorun:** Ölçülen CNC parçasının, üretilmesi istenen asıl değerde (nominal) olup olmadığı bilinmiyordu.
- **Çözüm:** Ölçüm tablosuna dinamik olarak **Hedef (mm)**, **Tolerans (±)** ve **Durum (PASS/FAIL)** sütunları eklendi.
- **Yetenek:** 
  - Gelen ölçümlere tolerans değeri girilerek (Örn: 0.05 mm) parça sapmasının tolerans içinde olup olmadığı anında **Yeşil (PASS)** veya **Kırmızı (FAIL)** metinlerle tespit edilebiliyor.
  - "🎯 Referans Ayarla" butonuyla ekrandaki güncel ölçümler tek tuşla tüm bölümler için **Golden Part (Sıfır Hatalı Parça)** referansı olarak kaydediliyor. Ardından yüklenen tüm parçaların bu Altın parçadan ne kadar saptığı otomatik ölçülüyor.
- **Raporlama:** Pass/Fail durum renkleri (kırmızı/yeşil) dahil olmak üzere, Hedef ve Tolerans bilgileri otomatik üretilen PDF ve Excel (.xlsx) raporlarına entegre edildi. Excel hücreleri de PASS ise yeşile, FAIL ise kırmızıya boyandı.

---

## [v4.6] — 2026-03-05

### X Ekseni (Uzunluk) ve Y Ekseni (Çap) Asimetrisi Düzeltmesi (Geri Alındı ve Yeniden Girdi)
- Lens distorsiyonu (bombe) veya kare olmayan piksellerden dolayı oluşan X ve Y eksenleri asimetrisi için API ve `measurement_engine.py` arasına **X-Scale** düzeltici çarpanı katıldı.

---

## [v4.5] — 2026-03-05

### Arayüz Görünümü (Overlay) Temizleme
- Algoritmalar, Kalibrasyon ve Ölçüm sekmeleri arasında geçiş yapıldığında, önceki sekmeden kalan 
  ölçüm çizgileri, kırmızı profil kutuları veya kalibrasyon yeşil okları (overlay görüntüleri) 
  ekranda asılı kalıyordu.
- Artık sekmeler arası geçiş yapıldığında ekran otomatik olarak temizleniyor ve algoritma uygulanmış 
  görüntünün **saf haline** (çizgisiz) geri dönüyor. Başlık etiketleri ve parametreler de ait oldukları
  sekmeye göre sıfırlanıyor.

---

## [v4.4] — 2026-03-05

### Kalibrasyon ve Ölçüm Sapması Düzeltmesi
- Kenar haritaları (Canny vb.) üzerinde yapılan kalibrasyon (örn. 29.7 mm) ile ölçüm sonuçları (örn. 35 mm)
  arasındaki sapma sorunu giderildi.
- Profil çıkarılırken (`extract_profile`), parçanın üst ve alt kenar pikselleri artık morfolojik 
  işlemlerle (dilate/close) şişirilmiş/kalınlaştırılmış maske üzerinden **değil**, orijinal ince 
  ve keskin kenar çizgileri (`binary_edges`) üzerinden hesaplanıyor. Bu sayede kalibrasyon ile 
  ölçüm motoru birebir aynı pikselleri baz alıyor.

---

## [v4.3] — 2026-03-05

### Kenar Haritası (Canny vb.) Profil Çıkarma Düzeltmesi
- Siyah zemin üzerinde beyaz kenar çizgilerinden oluşan görüntülerde (Canny, Sobel vb.) profil çıkarılırken
  parçanın tamamını kaplayan devasa dikdörtgen (boundingBox) çizilmesi hatası düzeltildi.
- Algoritma artık görüntünün parlaklığına bakıp "Kenar Haritası" moduna geçiyor ve sadece dış beyaz çizgilerin içini 
  doldurarak (solid_mask) doğru ve kesin bir parça silüeti çıkarıyor.

---

## [v4.2] — 2026-03-05

### Ölçüm & Profil — İşlenmiş Görsel Üzerinden
- `Profil Çıkar` ve `Tam Ölçüm` butonları artık algoritmalar sekmesinde uygulanan görüntü varsa
  o görsel üzerinden profil silüeti ve ölçüm yapıyor (orijinal değil).
- PDF, Excel ve görsel indirme butonları da aynı şekilde `processedImageId || imageId` mantığıyla çalışıyor.

---

## [v4.1] — 2026-03-05

### Kalibrasyon İyileştirmeleri

**1. Algoritma → Kalibrasyon Entegrasyonu**
- `/api/process` endpoint'i artık işlenmiş görüntüyü diske kaydediyor ve `processed_image_id` döndürüyor.
- Algoritma sekmesinde bir algoritma uygulandıktan sonra kalibrasyon sekmesine geçilince,  
  kalibrasyon artık **orijinal görsel yerine işlenmiş görsel** üzerinden yapılır.
- Kalibrasyon ipucu metni, algoritma uygulanmışsa mavi uyarı rengiyle güncelleniyor.

**2. İşlenmiş Görsel Üzerinde Kalibrasyon Tıklaması**
- Kalibrasyon (`Otomatik Kenar`) modunda hem **orijinal** hem **işlenmiş** görsele tıklanabilir.
- Kalibrasyon sekmesine geçilince algoritma uygulanmışsa otomatik olarak tek görünüme geçip işlenmiş görsel ön plana çıkarılıyor.
- `processedImage`'a tıklama ile de kenar tespiti ve kalibrasyon yapılabiliyor.

---

## [v4.0] — 2026-03-04

### Faz 4: Polish & Dokümantasyon
- Kapsamlı `README.md` dokümantasyonu (özellikler, mimari, kullanım rehberi) oluşturuldu.
- `task.md` üzerindeki tüm Fazlar tamamlandı olarak işaretlendi.
- Projede Frontend ve API bazında var olan `try-catch` mekanizmaları teyit edilerek stabilite güvence altına alındı.

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
