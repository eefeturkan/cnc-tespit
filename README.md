# CNC Parça Ölçüm Sistemi v3.0

Bu proje, silindirik CNC parçaların fotoğrafları üzerinden çap ve uzunluk ölçümü yapabilen web tabanlı bir görüntü işleme ve ölçüm yazılımıdır. Staj projesi kapsamında, mühendislik ekiplerinin bir parçayı hızlı, tekrarlanabilir ve görsel olarak doğrulanabilir şekilde değerlendirebilmesi hedeflenmiştir.

Sistem; görüntü işleme, profil çıkarma, X-Y kalibrasyonu, tam ölçüm, sabit noktalarda ölçüm ve raporlama adımlarını tek arayüz üzerinden sunar.

## Proje Amacı

- Fotoğraf üzerinden CNC parçanın profilini çıkarmak
- Çap ve uzunluk ölçülerini milimetre cinsinden hesaplamak
- Ölçüm sonuçlarını çizgilerle görsel üzerinde göstermek
- PDF ve Excel çıktısı alabilmek
- Teknik çizimdeki kritik noktalara göre sabit ölçüm yapmak

## Temel Yetenekler

### 1. Görüntü İşleme
- 12 farklı görüntü işleme algoritması
- Parametrelerin arayüzden anlık değiştirilmesi
- Parçanın arka plandan ayrıştırılması ve profilinin çıkarılması

### 2. Kalibrasyon
- Y ekseni için kenar bazlı kalibrasyon
- X ekseni için uzunluk bazlı kalibrasyon
- Piksel/mm oranının hesaplanması
- Kalibrasyon verilerinin saklanabilmesi

### 3. Tam Ölçüm
- Parça profili çıkarılır
- Bölümler otomatik tespit edilir
- Her bölüm için çap ve uzunluk hesaplanır
- Sonuçlar görsel üzerinde çizgilerle gösterilir

### 4. Sabit Noktalarda Ölçüm
- Teknik çizimde tanımlı kritik noktalardan ölçüm alınır
- Özellikle belirli çap ve uzunluk noktalarında daha kontrollü sonuç verir
- Sunum ve karşılaştırma için en kullanışlı moddur

### 5. Raporlama
- Ölçüm görselinin dışa aktarılması
- PDF raporu oluşturulması
- Excel çıktısı alınması

## Sabit Ölçüm Hakkında Önemli Not

Bu projede en iyi sonuç, ölçüm aşamasında:

`X ve Y kalibrasyonu yapıldıktan sonra`

`SABİT ÖLÇÜM NOKTALARI`

`Teknik çizimdeki 03, 04, 05, 06, 08, 17, 18, 21, 22, 24 noktaları`

`Sabit Noktalarda Ölç`

akışı kullanıldığında alınmaktadır.

Bu yaklaşım özellikle teknik resimde kritik kabul edilen çap ve uzunlukların doğrudan kontrol edilmesi açısından daha uygundur.

## Sentetik Referans Görsel Notu

Klasörde bulunan `sentetikgorsel.jpeg` dosyası, sabit ölçümde kullanılan çap ve uzunluk çizgilerinin yerlerini belirlemek için referans alınmıştır.

Bu nedenle mevcut sabit ölçüm noktaları, bu referans görsele göre ayarlanmıştır.

### Canlıya Alma ve Farklı Görsel ile Test Notu

Sistem farklı bir kamera, farklı bir açı, farklı bir çözünürlük veya farklı bir test görseli ile kullanılacaksa:

1. X ve Y kalibrasyonu yeniden yapılmalıdır.
2. Sabit çap ve uzunluk noktaları yeniden kontrol edilmelidir.
3. Gerekirse `backend/fixed_measurement_template.json` içindeki sabit piksel koordinatları yeni görsele göre tekrar ayarlanmalıdır.

Özetle:

`sentetikgorsel.jpeg` referansına göre ayarlanan sabit noktalar, farklı görüntü koşullarında doğrudan doğru sonuç vermeyebilir.`

Canlı kullanıma alınmadan önce bu noktaların yeniden doğrulanması gerekir.

## Klasör Yapısı

```text
cnc-tespit/
|-- backend/
|   |-- app.py
|   |-- image_processing.py
|   |-- calibration.py
|   |-- profile_extractor.py
|   |-- measurement_engine.py
|   |-- fixed_measurement_engine.py
|   |-- report_generator.py
|   `-- requirements.txt
|-- frontend/
|   |-- index.html
|   |-- css/
|   `-- js/
|-- calibration_profiles/
|-- reports/
|-- uploads/
|-- tests/
`-- sentetikgorsel.jpeg
```

## Kurulum

### Gereksinimler
- Python 3.9+
- Modern bir web tarayıcısı

### Adımlar

1. Bağımlılıkları yükleyin:

```bash
cd backend
pip install -r requirements.txt
pip install reportlab openpyxl
```

2. Sunucuyu başlatın:

```bash
python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

3. Tarayıcıdan açın:

```text
http://localhost:8000
```

## Kullanım Akışı

### 1. Görüntü Yükleme
Parçanın arka plandan net ayrıldığı, iyi ışıklandırılmış görüntü sisteme yüklenir.

### 2. Kalibrasyon
Ölçümden önce X ve Y kalibrasyonu yapılır. Bu adım, ölçümlerin mm cinsinden doğru hesaplanabilmesi için zorunludur.

### 3. Profil Çıkarma
Parçanın üst ve alt sınırları tespit edilir, profil oluşturulur.

### 4. Ölçüm
İki farklı yaklaşım vardır:

- `Tam Ölçüm`: Sistem tüm bölümleri otomatik tespit eder.
- `Sabit Noktalarda Ölç`: Teknik resimdeki belirli kontrol noktaları üzerinden ölçüm yapar.

Mühendislik değerlendirmesi için önerilen akış:

`Kalibrasyon -> Sabit Noktalarda Ölç -> Sonuçları teknik resimle karşılaştır`

### 5. Raporlama
Sonuçlar görsel, PDF ve Excel olarak dışa aktarılabilir.

## Mühendislik Sunumu İçin Öne Çıkan Noktalar

- Sistem yalnızca görsel işleme yapmaz, aynı zamanda teknik resimdeki kritik ölçülere göre kontrol imkanı sunar.
- Sabit ölçüm yaklaşımı, operatör bağımlılığını azaltır.
- Referans görsele göre ayarlanmış sabit noktalar sayesinde tekrarlanabilir ölçüm akışı oluşturulmuştur.
- Farklı kamera veya görüntü koşullarında yeniden kalibrasyon ve nokta doğrulaması gereklidir.
- Bu yapı, gelecekte gerçek üretim hattına uyarlanabilecek bir temel oluşturur.

## Geliştirme Notu

Bu proje bir staj projesi olarak geliştirilmiştir. Amaç, üretim ve kalite ekiplerinin kullanabileceği optik ölçüm yaklaşımını yazılımsal olarak modellemek ve mühendislik bakış açısıyla uygulanabilir bir prototip ortaya koymaktır.

---

Geliştirme: v3.0 | 2026
