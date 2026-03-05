# CNC Parça Ölçüm Sistemi v3.0

Silindirik CNC açılmış parçaların (örneğin tahrik milleri, bobinler) fotoğrafları üzerinden yüksek hassasiyetle **çap (D)** ve **uzunluk (L)** ölçümleri yapabilen web tabanlı bir görüntü işleme ve ölçüm yazılımıdır. 

Proje, VICIVISION benzeri optik ölçüm cihazlarının yazılımsal yeteneklerini standart kameralarla çekilmiş, yüksek çözünürlüklü ve iyi ışıklandırılmış görüntüler üzerinde uygulamayı hedefler.

## Özellikler

### 1. Görüntü İşleme Motoru (Faz 1)
- 12 farklı görüntü işleme algoritması (Canlı Önizleme ile)
- *Grayscale, Gaussian Blur, Canny Edge, Sobel Edge, Laplacian Edge, Adaptive Threshold, Otsu Threshold, Morphology, Contour Detection, Hough Lines, CLAHE, Bilateral Filter*
- Seçilen algoritmanın parametrelerini dinamik değiştirme ve sonucu anında görme (Yan Yana / Tekli Görünüm)

### 2. Optik Kalibrasyon (Faz 2)
- İki farklı kalibrasyon yöntemi:
  - **Dinamik Kenar Tespiti:** Görüntü üzerinde bir noktaya tıklandığında, sistem parçanın üst ve alt kenarlarını (Otsu + Morfolojik işlemler ile) milisaniyeler içinde tespit eder ve piksel cinsinden çapı bulur. Gerçek milimetre değeri girildiğinde `Piksel/mm` oranını hesaplar.
  - **Manuel Giriş:** Bilinen `Piksel/mm` oranı doğrudan girilebilir.
- Kalibrasyon profilleri (`.json`) disk üzerinde saklanır ve daha sonra tekrar yüklenebilir.

### 3. Otomatik Ölçüm Motoru (Faz 2)
- Parçanın silüetini (profilini) çıkararak üst ve alt kenarları tam boyutlu olarak dizilere haritalar.
- Profilin birinci türevi (gradient) alınarak parçadaki keskin çap değişimleri (basamaklar/bölümler) tespit edilir.
- Her bölüm için ayrı ayrı ortalama çap ve toplam uzunluk hesaplanır.
- Sonuçlar, CNC raporlama standartlarına uygun olarak `D01, L01, D02, L02...` formatında tabloya dökülür.

### 4. Raporlama ve Dışa Aktarım (Faz 3)
- Ölçüm tamamlandıktan sonra işlenmiş parçanın üzerinde boyutların çizili olduğu görsel PNG olarak indirilebilir.
- Ölçüm tablosu, kalibrasyon bilgileri ve tolerans dışı durumları (gelecek vizyonu) içeren profesyonel **PDF Raporu** oluşturulur.
- Diğer sistemlerle entegrasyon veya manuel arşivleme için sonuçlar **Excel (.xlsx)** formatında tek tıkla dışa aktarılabilir.

## Klasör Yapısı

```
cnc-tespit/
├── backend/
│   ├── app.py                 # FastAPI ana uygulama (Giriş noktası)
│   ├── image_processing.py    # Görüntü işleme (12 algoritma)
│   ├── calibration.py         # Kalibrasyon hesaplama ve profil yönetimi
│   ├── profile_extractor.py   # Parça silüetini ve kenarları çıkaran motor
│   ├── measurement_engine.py  # Bölümleri bölen ve çap/boy hesaplayan analiz motoru
│   ├── report_generator.py    # PDF ve Excel rapor oluşturucu
│   └── requirements.txt       # Python bağımlılıkları
├── frontend/
│   ├── index.html             # Ana UI çerçevesi
│   ├── css/
│   │   └── style.css          # Industrial Dark Tema
│   └── js/
│       └── app.js             # İstemci tarafı mantık ve API istekleri
├── uploads/                   # Yüklenen ham görüntüler (geçici)
├── reports/                   # Geçici rapor dosyaları klasörü
└── calibration_profiles/      # .json formatındaki kalibrasyon kayıtları
```

## Kurulum ve Çalıştırma

### Gereksinimler
- Python 3.9+
- Modern bir web tarayıcısı (Chrome, Edge, Firefox, Safari)

### Adımlar

1. **Python kütüphanelerini yükleyin:**
   ```bash
   cd backend
   pip install -r requirements.txt
   pip install reportlab openpyxl  # Raporlama için
   ```

2. **Sunucuyu başlatın:**
   Backend klasörü içerisindeyken `uvicorn` ile FastAPI sunucusunu çalıştırın:
   ```bash
   python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
   ```

3. **Arayüze erişin:**
   Tarayıcınızda `http://localhost:8000` adresine gidin.

## Kullanım Rehberi

1. **Görüntü Yükleme:** Sol alt kısımdaki alana test edilecek CNC parçasının, iyi ışıklandırılmış ve arka plandan net ayrışan bir fotoğrafını yükleyin.
2. **Kalibrasyon:** Sol menüden *Kalibrasyon* sekmesine geçin. Parçanın bilinen bir çapı varsa, *Otomatik Kenar* modunda o çap hizasında görüntüye bir kez tıklayın. Sistem kenarları çizecektir. İlgili gerçek mm değerini kutuya girip *Kalibre Et* butonuna basın.
3. **Ölçüm:** Sol menüden *Ölçüm* sekmesine geçin. Algoritma hassasiyeti (bölüm minimum genişliği, geçiş toleransı vb.) için parametreleri ayarlayın. *Tam Ölçüm* butonuna tıklayın.
4. **Raporlama:** Sağ altta beliren ölçüm sonuç tablosundan *Görsel*, *PDF* veya *Excel* ikonlarına tıklayarak raporlarınızı indirebilirsiniz.

## Arayüz Tasarımı (Industrial Dark)
Arayüz, endüstriyel yazılımların karanlık temalarından ilham alınarak, uzun süreli kullanımlarda göz yormayan, kontrastlı (`#0a0e14`, `#111820`), JetBrains Mono ve DM Sans font ailelerinin birleşimiyle kodlanmıştır.

---
*Geliştirme: v3.0 | 2026*
