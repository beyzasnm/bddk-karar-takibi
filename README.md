# BDDK Veri ve Karar Takibi

Panel önce BDDK Haftalık Bülteni’ndeki altı bankacılık serisini gösterir. Son dönem, önceki yayımlanan döneme göre değişim ve son bir yıla kadar gözlemler yer alır. Tutarlar milyon TL’dir. YP mevduat TL karşılığıyla gösterilir. Kaynak hatasında son başarılı gözlemler korunur. Kurul kararları panelin altındaki ayrı bölümde açılır.

GitHub Actions, iki resmî BDDK karar listesini her saat 17. dakikada kontrol eder. SQLite dosyası karar kayıtlarını ve indirilen PDF’leri saklar. Dashboard HTML dosyası veriyi kendi içinde taşır ve tarayıcıda tek başına açılır.

## GitHub kurulumu

1. GitHub’da yeni bir depo oluştur ve ZIP’in içeriğini depo köküne yükle. Dosyaların arasında .github/workflows/bddk.yml de yer almalı. GitHub web arayüzü bu klasörü atladıysa **Add file → Create new file** ile aynı yolu oluşturup dosyanın içeriğini yapıştır.
2. **Actions → BDDK verilerini ve kararlarını güncelle → Run workflow** ile ilk taramayı başlat. Arşiv için depo ayarları GitHub Actions’a varsayılan dala yazma izni vermeli.
3. Çalıştırma sayfasındaki **bddk-dashboard** çıktısını indir ve **index.html** dosyasını aç. Kaynakların son başarılı kontrolünü ve PDF durumlarını incele. İlk çalıştırma başarısız görünse bile tarama hatası durumunda bu çıktı tanı için kullanılabilir.

Sürekli açılabilen bir bağlantı için deponun planı ve görünürlüğü GitHub Pages’i destekliyorsa **Settings → Pages → Source → GitHub Actions** seç. Ardından **Settings → Secrets and variables → Actions → Variables** altında ENABLE_PAGES değerini true yap ve görevi tekrar çalıştır. Pages görünürlüğünü depo hesabının planına göre kontrol et. SQLite dosyası Pages çıktısına dahil edilmez. Depo herkese açıksa SQLite dosyası ve arşivlenmiş PDF’ler depo üzerinden görülebilir.

## Takip kapsamı

İlk taramada kaynak başına en güncel 10 karar panele alınır. Daha eski kayıtların numaraları başlangıç referansı olarak tutulur. Sonraki taramalarda listede ilk kez görülen kararlar eklenir. Aynı kaynakta aynı karar numarası tekrar kayıt oluşturmaz. Başarısız PDF indirmeleri sonraki çalıştırmalarda tekrar denenir. PDF arşivi SQLite içindedir ve panel resmî belgeye bağlantı verir.

BDDK listelerindeki tarih karar tarihidir. İlk sürüm ayrı bir yayın tarihi kaynağından doğrulama yapmadığı için bu sütun boş kalır. İlk görülme ve son başarılı kontrol saatleri İstanbul saatine çevrilir. GitHub zamanlayıcısı gecikebilir.
