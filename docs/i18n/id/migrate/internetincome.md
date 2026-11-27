---
source_hash: ca9dd25d45ca
---
# Pindah dari InternetIncome { #moving-from-internetincome }

CashPilot dapat membaca `properties.conf` milik InternetIncome, serta file tempat
InternetIncome menyimpan id perangkat EarnApp dan ProxyRack Anda, lalu membawanya. Anda memeriksa
semuanya sebelum CashPilot menyimpannya.

## Sebelum Anda mulai { #before-you-start }

Anda memerlukan akun pemilik CashPilot dan setidaknya satu worker CashPilot.

Hentikan InternetIncome di sebuah mesin sebelum Anda menerapkan layanan yang sama di sana dari
CashPilot. Dua salinan di balik satu koneksi menghasilkan sebagai satu, dan id perangkat yang sama
tidak boleh berjalan dua kali. Di folder InternetIncome, jalankan:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` menghapus kontainer dan mempertahankan `earnapp.txt`, `proxyrack.txt`, serta
folder data Mysterium. `--deleteBackup` juga menghapus semua itu
([internetIncome.sh, baris 61 sampai 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
dan [baris 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
jadi lakukan impor terlebih dahulu.

## File mana yang dipakai { #which-files-to-use }

Dari folder InternetIncome:

- `properties.conf`, pengaturan Anda.
- `earnapp.txt`, jika Anda menjalankan EarnApp. Setiap baris memuat satu tautan perangkat
  ([baris 1250 sampai 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, jika Anda menjalankan ProxyRack. Satu UUID perangkat per baris
  ([baris 817 sampai 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot mengambil perangkat pertama di setiap file: perangkat yang dipakai kontainer utama Anda
dan yang Anda tautkan ke akun Anda. Baris-baris lain milik salinan
via proxy, dan halaman itu memberi tahu Anda berapa banyak yang tidak disertakan.

InternetIncome menjalankan setiap nilai melalui shell
([baris 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Nilai dalam tanda kutip tunggal diambil apa adanya, seperti yang disarankan komentar di
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
Nilai di luar tanda kutip tunggal yang memuat `$`, backtick, spasi, atau
karakter lain yang akan diubah oleh shell tidak sama dengan yang tampak di file, sehingga
CashPilot meminta Anda mengetik ulang alih-alih menjalankan shell untuk mengetahuinya.

## Cara mengimpor { #how-to-import }

1. Buka **Settings** (Pengaturan), lalu **Import from another tool** (Impor dari alat lain) (atau buka `/import`).
2. Tambahkan `properties.conf`, ditambah `earnapp.txt` dan `proxyrack.txt` jika Anda
   memilikinya. Biarkan pilihan alat pada "Tell from the files" (Tentukan dari file), atau pilih InternetIncome.
3. Periksa tabelnya. Centang layanan yang Anda inginkan dan isi setiap nilai yang ditandai
   tidak ada. Repocket memerlukan email akun Anda, yang tidak pernah ditanyakan
   InternetIncome.
4. Tekan **Save the ticked services** (Simpan layanan yang dicentang), lalu terapkan ke worker Anda dari
   halaman yang sama.

## Apa yang terbawa { #what-comes-over }

| Aplikasi InternetIncome | Kunci yang dibaca | Layanan CashPilot | Apa yang terbawa |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | kunci API (tambahkan email Anda) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | kunci API, UUID perangkat |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | email, kata sandi |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | email, kata sandi |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id pengguna |
| `earnfm` | `EARN_FM_API` | Earn.fm | kunci API |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | id perangkat |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | email, kata sandi |
| `mysterium` | `MYSTERIUM=true` | Mysterium | diaktifkan; lihat catatan Mysterium di bawah |

Nilai kosong berarti aplikasi itu mati, dan tidak dicantumkan.

Aplikasi berikut tercantum tetapi tidak dibawa:

| Aplikasi InternetIncome | Alasan |
|---|---|
| `urnetwork` | InternetIncome memakai token sesi. CashPilot memasukkan URnetwork dengan email dan kata sandi Anda. |
| `grass` | Grass berjalan sebagai ekstensi browser. CashPilot hanya melacaknya, dengan access token dari dasbor Grass. |
| `titan`, `ebesucher`, `wipter` | CashPilot melacak aplikasi ini, tetapi tidak ada kontainer untuk diterapkan. |
| `peer2profit` | Tidak tersedia lagi. |

Pengaturan untuk aplikasi yang tidak dimiliki CashPilot (antGain, Adnade, dan lainnya)
dicantumkan berdasarkan nama sebagai tidak dibaca.

## Apa yang tidak pernah terbawa { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot menamai setiap perangkat sesuai worker tempatnya berjalan, sehingga
  dua worker tidak pernah melaporkan nama yang sama. Perangkat lama Anda tetap tercantum sebagai
  offline di dasbor setiap penyedia sampai Anda menghapusnya di sana.
- **Proxy** (`USE_PROXIES`, `proxies.txt`). Tambahkan masing-masing di bagian **Proxies** (Proxy)
  di halaman **Fleet** (Armada), lalu jalankan salinan layanan Anda melaluinya; menambahkan
  proxy tidak menjalankan apa pun dengan sendirinya. Dengan `USE_PROXIES=true`, InternetIncome menjalankan
  layanan Anda hanya melalui proxy. Menyimpan impor juga tidak menjalankan apa pun.
  Salinan via proxy memerlukan layanan yang sama sudah diterapkan di worker terlebih dahulu, dan
  penerapan itu menjalankannya di koneksi milik worker sendiri, sehingga layanan yang
  sama sekali tidak boleh memakai koneksi itu sebaiknya tetap tidak dicentang. Lihat [Salinan via proxy](../proxies.md).
- **`BROWSER_USERNAME` dan `BROWSER_PASSWORD`**, login browser milik
  InternetIncome sendiri.

## Pelacakan penghasilan { #earnings-tracking }

Untuk Honeygain, IPRoyal Pawns, dan Bitping, login kontainer juga merupakan login
akun, sehingga CashPilot juga mengisi kredensial penghasilannya, kecuali Anda
sudah menyetelnya di **Settings** (Pengaturan). Untuk setiap layanan lain, tambahkan login penghasilan
di **Settings > Earnings collection** (Pengaturan > Pengumpulan penghasilan).

## Mysterium { #mysterium }

Impor mengaktifkan Mysterium, tetapi CashPilot memulai node baru dengan
identitas baru. Keystore node lama dan penghasilan yang belum diselesaikan tetap berada di
folder `mysterium-data` milik InternetIncome. Selesaikan dulu penghasilan itu, atau ikuti
[panduan Mysterium](../guides/mysterium.md) untuk membawa identitasnya.

## Keamanan { #safety }

- Tidak ada isi file yang dijalankan atau diekspansi, dan tidak ada alamat di dalamnya yang diambil.
- File dibaca sekali dan tidak disimpan. Apa yang Anda simpan disimpan dalam keadaan terenkripsi, seperti
  setiap kredensial lain di CashPilot.
- Rahasia hanya ditampilkan sebagai "set" (disetel) di halaman.
- Impor yang tersimpan tetap ada di halaman impor sampai Anda menekan **Forget** (Lupakan), sehingga Anda dapat
  menerapkannya ke lebih banyak worker nanti.
