# BDDK Veri Arşivi

İlk aşama BDDK Haftalık Bülteni’nin sektör tablolarını ve erişilebilir geçmişini kapsar. BDDK’nın gelişmiş raporundaki TL ve USD gösterimleri ayrı seri olarak tutulur. Kaynaktaki boşluklar korunur. Yayın tarihi doğrulanmamış geçmiş veriler için gözlem tarihi kullanılır.

[Son çalıştırmayı aç](https://github.com/beyzasnm/bddk-karar-takibi/actions/workflows/weekly.yml). **bddk-veri-arsivi** çıktısını indir ve ZIP içindeki `index.html` dosyasını aç. Panel tarih aralığı, kategori, seri, para ayrımı ve gösterim birimine göre filtrelenir. Excel’de tablolar ayrı sekmelerde veya gözlem tarihine hizalanmış tek sekmede alınabilir.

Kontrol saatlik çalışır. Yeni bir gözlem geldiğinde son dönemler yeniden çekilir. Tüm geçmişi yeniden doğrulamak için **Run workflow** ekranında ilgili seçeneği işaretle.
