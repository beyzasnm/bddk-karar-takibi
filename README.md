# BDDK Karar Takibi

GitHub Actions, iki resm� BDDK karar listesini her saat 17. dakikada kontrol eder. SQLite dosyasi karar kayitlarini ve indirilen PDF'leri saklar. Dashboard HTML dosyasi veriyi kendi i�inde tasir ve tarayicida tek basina a�ilir.

## GitHub kurulumu

1. GitHub'da yeni bir depo olustur ve ZIP'in i�erigini depo k�k�ne y�kle. Dosyalarin arasinda .github/workflows/bddk.yml de yer almali. GitHub web aray�z� bu klas�r� atladiysa **Add file  Create new file** ile ayni yolu olusturup dosyanin i�erigini yapistir.
2. **Actions  BDDK kararlarini g�ncelle  Run workflow** ile ilk taramayi baslat. Arsiv i�in depo ayarlari GitHub Actions'a varsayilan dala yazma izni vermeli.
3. �alistirma sayfasindaki **bddk-dashboard** �iktisini indir ve **index.html** dosyasini a�. Kaynaklarin son basarili kontrol�n� ve PDF durumlarini incele. Ilk �alistirma basarisiz g�r�nse bile tarama hatasi durumunda bu �ikti tani i�in kullanilabilir.

S�rekli a�ilabilen bir baglanti i�in deponun plani ve g�r�n�rl�g� GitHub Pages'i destekliyorsa **Settings  Pages  Source  GitHub Actions** se�. Ardindan **Settings  Secrets and variables  Actions  Variables** altinda ENABLE_PAGES degerini true yap ve g�revi tekrar �alistir. Pages g�r�n�rl�g�n� depo hesabinin planina g�re kontrol et. SQLite dosyasi Pages �iktisina dahil edilmez. Depo herkese a�iksa SQLite dosyasi ve arsivlenmis PDF'ler depo �zerinden g�r�lebilir.

## Takip kapsami

Ilk taramada kaynak basina en g�ncel 10 karar panele alinir. Daha eski kayitlarin numaralari baslangi� referansi olarak tutulur. Sonraki taramalarda listede ilk kez g�r�len kararlar eklenir. Ayni kaynakta ayni karar numarasi tekrar kayit olusturmaz. Basarisiz PDF indirmeleri sonraki �alistirmalarda tekrar denenir. PDF arsivi SQLite i�indedir ve panel resm� belgeye baglanti verir.

BDDK listelerindeki tarih karar tarihidir. Ilk s�r�m ayri bir yayin tarihi kaynagindan dogrulama yapmadigi i�in bu s�tun bos kalir. Ilk g�r�lme ve son basarili kontrol saatleri Istanbul saatine �evrilir. GitHub zamanlayicisi gecikebilir.
