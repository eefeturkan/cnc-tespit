# CNC Parça Ölçüm Sistemi - Geliştirme Yol Haritası (TODOs)

Bu belge, projenin yeteneklerini bir prototipten endüstri standardı bir **CMM (Coordinate Measuring Machine) / Optik Ölçüm Cihazı** seviyesine taşımak için yapılabilecek eksiklikleri ve potansiyel geliştirmeleri içermektedir.

---

## 🔴 Kritik ve Yüksek Öncelikli (Core Features)

### 1. Tolerans Yönetimi ve Referans Parça Karşılaştırması (Pass/Fail) ✅ **[TAMAMLANDI v4.7]**
- **Sorun:** Sistem ölçüyor ancak ölçülen çapın/uzunluğun CNC programında istenen değere uygun olup olmadığını bilmiyor.
- **Çözüm (GD&T):** 
  - Sisteme bir "Referans (Golden)" parça tanımlama yeteneği eklendi.
  - Her bölüm (D1, D2, L1...) için `±0.05 mm` gibi alt/üst tolerans sınırları girilebiliyor.
  - Ölçüm sonucunda tablonun tolerans içindekileri **Yeşil (Pass)**, dışındakileri **Kırmızı (Fail - Iskarta)** olarak renklendiriyor. Ayrıca bu renkler Excel ve PDF raporlarında da çıkıyor.

### 2. Kamera Lens Distorsiyonu (Bozulma) Düzeltmesi
- **Sorun:** Kameraların veya alınan lenslerin fiziksel eğriliğinden (fıçı / yastık distorsiyonu) dolayı parçanın merkezindeki piksel genişliği ile köşesindeki genişlik aynı değildir. (Şu anki x_scale düzeltmeniz buna sadece bant aid yapıyor).
- **Çözüm:** 
  - OpenCV'nin Satranç Tahtası (Checkerboard) Camera Calibration fonksiyonelliğinin bir sekmeye eklenmesi. Kamera matrisi (Intrinsic) ve bozulma katsayılarının bulunarak sisteme entegre edilmesi ve fotoğraf yüklenir yüklenmez ilk olarak görselin `cv2.undistort` ile **düzeltilmiş gerçeğe (rectified)** dönüştürülmesi.

### 3. Sub-Pixel (Piksel Altı) Hassasiyet ve Algoritma Kalitesi
- **Sorun:** Canny vb. klasik filtreler tam sayı (integer) tabanlı kenar bulur. Yani yanılma payı kameranın 1 piksel ölçüsü kadardır `(Örn: 1px = 0.04mm durumu)`.
- **Çözüm:** 
  - Kenarlardaki gri tonlama geçişlerini (gradient profile) bir Gaussian eğrisine (veya kübik spline'a) oturtarak interpolasyonla **0.1 piksel** hassasiyetinde kenar tespiti eklemek. Çözünürlüğü artırmadan doğruluğu yazılımla 10 katına katlar.

---

## 🟡 Orta Öncelikli (Advanced Analysis & UX)

### 4. Kusur ve Yüzey Hatası Tespiti (Surface Defect Detection)
- **Sorun:** Form (ebat) kontrolü olsa da parçadaki fiziksel hatalar yakalanmıyor.
- **Çözüm:** 
  - Sadece kenar bulmaktan çıkarak, parça yüzeyindeki vuruk, talaş çiziği, pas bandı veya chatter mark (titreşim izi) gibi hataları yakalamak için **Derin Öğrenme / CNN (Örn: YOLO v8, TensorFlow)** entegrasyonu sağlama alanı açıp, modelin bulduğu çizikleri ana resimde farklı renk kutular (BBox) ile çizme.

### 5. Geçmiş Ölçümlerin Kaydı ve SPC (İstatistiksel Proses Kontrol)
- **Sorun:** Rapor indirilebilse de veriler izole ve merkezi değil.
- **Çözüm:** 
  - Arkaya bir Veritabanı (SQLite / PostgreSQL) ekleyip parçaların ölçüm kayıtlarını tarih, vardiya ve Barkod numarası ile kaydetmek.
  - Elmas kesicinin ne kadar aşındığını görebilmek için son 100 parçanın çap büyüme-küçülme trendini (X-Bar ve R SPC grafikleri) izlenebilen bir **Dashboard sayfası** yapmak.

### 6. İnteraktif Ölçüm Haritası (Manuel Müdahale)
- **Sorun:** Algoritma geçişleri (`gradient_threshold`) bazen tek bir yüzeyi 2'ye bölebilir veya 2 küçük kertiği 1 bölüm sayabilir, kullanıcı düzeltemiyor.
- **Çözüm:** 
  - Ekranda çizilen dikey noktalı bölme çizgilerini kullanıcının mouse ile sürükleyebilmesi (Drag & Drop), sağ tıklayıp "Bölümleri Birleştir" ya da "Buradan Böl" diyebilmesi, yani **manuel düzeltme modunun** yazılması.

---

## 🟢 Uzun Vadeli (Endüstri 4.0 & Otomasyon)

### 7. Çoklu Parça veya Batch (Otomatik) İşleme
- **Sorun:** Üretim hattında insan gücü gerektiriyor.
- **Çözüm:** 
  - Sistemin bir *Watchdog* modifikasyonuyla, bir klasöre ağ (FTP) üzerinden her yeni kamera fotoğrafı düştüğünde arayüze bile girmeden arka planda analiz yapıp bir PLC'ye "OK/NG" sinyali ateşleyecek headless (API-only) versiyonu.

### 8. Donanım (I/O) ve Robotik Entegrasyonu
- **Sorun:** Sistem dış dünyaya kapalı.
- **Çözüm:** 
  - Modbus TCP, OPC-UA protokollerinin sunucuya (FastAPI) eklenerek, CNC tezgah kapısı açıldığında veya robot kol parça getirdiğinde ölçümün "Remote" tetiklenmesi, yeşil/kırmızı ışıkların veya pinlerin yörülmesi (Raspberry Pi GPIO entegrasyonu destekleri).

### 9. 3D Ekseninde (Salgı/Dairesellik) Kontrolü
- **Sorun:** Kameralar her zaman 2B form ölçer. Parçada ovalleşme (ovality) veya salgı (run-out) olup olmadığını anlamak zordur.
- **Çözüm:** 
  - Sisteme bir döner V-yatağı (fikstür) entegrasyonu eklenerek; parçanın belli aralıklarla dönüp X sayıda karesinin alınması ve bu açılardan elde edilen Y çaplarının matematiksel farkından *Salgı Toleransı* (Concentricity/Runout) çıkarılması.
