---
source_hash: 38029ca1a5d6
---
# Ekspor penghasilan untuk pajak { #income-export-for-taxes }

Buka **Payouts** (Pembayaran), cari **Income for taxes** (Penghasilan untuk pajak), lalu pilih rentang tanggal dan mata uang. **This year** (Tahun ini) mencakup sampai hari ini, dan **Last year** (Tahun lalu) mencakup tahun kalender sebelumnya. Biarkan tanggal kosong untuk mengekspor riwayat yang tersedia sampai hari ini. CashPilot memakai tanggal UTC dan menyertakan kedua ujung rentang.

CashPilot menghapus pembacaan penghasilan 400 hari setelah mencatatnya. CSV memakai riwayat yang tersisa, sehingga tahun yang sudah lewat bisa saja hanya memuat sebagian penghasilan yang diperoleh atau yang masih tertahan.

## Pilih dasar akuntansi { #choose-an-accounting-basis }

- **Basis kas.** Gunakan baris pembayaran. Baris ini mencatat uang yang sudah dibayarkan layanan. CashPilot hanya menyertakan pembayaran yang sudah dikonfirmasi.
- **Basis akrual.** Gunakan baris earned dan accrued. Baris earned menunjukkan kredit yang dapat Anda tarik sesuai ketentuan layanan. Baris accrued menunjukkan kredit pool yang belum dibayar dan mungkin tidak akan pernah dibayar pool.

Gunakan satu basis untuk penghasilan yang sama. Menambahkan baris pembayaran ke baris earned dan accrued bisa menghitung uang yang sama dua kali. Periksa basis mana yang berlaku untuk pelaporan pajak Anda.

## Kolom CSV { #csv-columns }

| Kolom | Arti |
|---|---|
| date | Hari UTC dari pembacaan yang lebih baru atau dari pembayaran. Pembayaran memakai tanggal yang Anda masukkan atau hari CashPilot mendeteksinya. |
| period_start | Hari UTC dari pembacaan sebelumnya untuk layanan dan sumber ini. Kosong untuk pembayaran. Jeda di antara pembacaan berarti jumlahnya mencakup seluruh interval. |
| kind | earned, accrued, atau payout. |
| service | ID layanan CashPilot. |
| coin | Kode mata uang atau token sebagaimana dicatat CashPilot. |
| amount | Jumlah dalam mata uang atau token itu. |
| usd_rate | Jumlah dolar AS per satu unit coin. |
| usd_value | Jumlah yang dinilai dalam dolar AS. |
| local_currency | Mata uang fiat yang Anda pilih untuk ekspor. |
| local_rate | Jumlah unit mata uang pilihan Anda per satu dolar AS. |
| local_value | Jumlah yang dinilai dalam mata uang pilihan Anda. |
| method | Metode pembayaran, jika tercatat. |

Penilaian yang kosong berarti kursnya tidak tersedia. Jumlah aslinya tetap ada. CashPilot melewati poin internal seperti poin Grass dalam pembacaan penghasilan. Pembacaan pertama per sumber memberikan saldo awal. Baris-baris berikutnya mencatat kenaikan, sehingga CSV bisa dimulai setelah pembacaan tertua dalam rentang yang dipilih.

Jika lebih dari satu sumber membaca akun yang sama, CSV bisa menghitung penghasilan itu lebih dari sekali.

Kurs USD berasal dari pembacaan yang lebih baru atau dari catatan pembayaran. Saat CashPilot mengisi harga sebuah pembacaan secara susulan, CashPilot memakai harga CoinGecko pada pukul 00:00 UTC hari itu. CashPilot memakai kurs referensi ECB terbaru pada atau sebelum hari baris itu untuk mengonversi USD ke mata uang pilihan Anda. Ini mencakup akhir pekan, hari libur, dan hari ketika ECB belum memublikasikan kursnya. [Kurs harian Frankfurter](https://frankfurter.dev/v1/)

Frankfurter mencantumkan mata uang berikut untuk ekspor. [Mata uang yang didukung](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR, dan ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD, dan ZAR.

Pilih USD jika mata uang Anda tidak ada di daftar itu atau Frankfurter tidak tersedia.

## Impor ke alat lain { #import-into-another-tool }

Konversikan CSV ke format alat tersebut sebelum mengimpor. Pilih dulu baris untuk dasar akuntansi Anda. Lewati baris pembayaran untuk dompet yang sudah disinkronkan alat itu.

### rotki { #rotki }

Gunakan Generic Events dengan header berikut.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Setel Type ke Income dan Location ke external. rotki juga menerima Deposit, Withdrawal, Loss, Spend, dan Staking jika jenis-jenis itu menggambarkan suatu kejadian. Petakan coin ke Currency, amount ke Amount, dan service ke Description. Gunakan identifier aset rotki jika berbeda dari kode coin. Konversikan date ke timestamp Unix UTC dalam milidetik. Biarkan kedua kolom fee kosong. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Gunakan kolom wajib dari template Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Format Date sebagai YYYY-MM-DD HH:mm:ss dalam UTC. Isi Received Amount dari amount dan Received Currency dari coin. Biarkan kedua kolom Sent kosong. Untuk nilai yang diketahui, petakan local_value dan local_currency ke kolom opsional Net Worth Amount dan Net Worth Currency. Gunakan kolom Tag untuk mining atau reward jika sesuai. Description dan TxHash bersifat opsional. [Template Universal Koinly](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Belum punya akun Koinly? Anda bisa mendaftar di sini: https://koinly.io/?via=FFF185D5. Ini tautan referal, dan tidak membebani Anda biaya apa pun.

### CoinTracking { #cointracking }

Konversikan baris penghasilan ke format CSV reguler CoinTracking. Custom Importer mewajibkan kolom transaksi di kedua sisi, sedangkan baris penghasilan hanya punya sisi beli. [Persyaratan Custom Importer CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Setel Type ke Income atau Mining sesuai kebutuhan. Petakan amount ke Buy Amount, coin ke Buy Currency, dan service ke Comment. Biarkan kolom Sell kosong. Format Date sebagai DD.MM.YYYY HH:MM:SS. Ekspor menyediakan hari UTC, jadi gunakan 00:00:00 untuk jamnya. Gunakan label jenis sesuai bahasa akun Anda. [Format CSV reguler CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Belum punya akun CoinTracking? Tautan pendaftaran ini memberi Anda diskon 10% untuk setiap paket berbayar: https://cointracking.info?ref=G962413. Ini tautan referal. CoinTracking membayar proyek CashPilot 20% dari yang Anda bayar, dan Anda tidak membayar lebih mahal.
