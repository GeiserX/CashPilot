---
source_hash: 1a7f6b462b56
---
# Pindah dari money4band { #moving-from-money4band }

CashPilot dapat membaca konfigurasi money4band dan membawa login layanan Anda, sehingga
Anda tidak perlu mengetiknya lagi. Anda memeriksa semuanya sebelum CashPilot menyimpannya.

## Sebelum Anda mulai { #before-you-start }

Anda memerlukan akun pemilik CashPilot dan setidaknya satu worker CashPilot di
mesin tempat money4band berjalan sekarang, atau di mesin lain.

Hentikan money4band di sebuah mesin sebelum Anda menerapkan layanan yang sama di sana dari
CashPilot. Dua salinan di balik satu koneksi menghasilkan sebagai satu, dan id perangkat EarnApp
atau ProxyRack yang sama tidak boleh berjalan dua kali. Gunakan **Stop apps stack** di
menu money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
atau jalankan `docker compose down` di foldernya. Jika Anda menyiapkan instans proxy
tambahan, hentikan juga masing-masing.

## File mana yang dipakai { #which-file-to-use }

Gunakan `config/user-config.json` di folder money4band Anda. Cara membawanya ke
CashPilot bergantung pada versi money4band Anda.

Di money4band 4.x, money4band menulis file itu
saat Anda menjalankan **Setup Apps**, dan file itu memuat persis apa yang Anda ketik. `.env`
di sampingnya dibuat dari file itu dan juga bisa dipakai, begitu pula
`.env` yang diedit manual dari money4band 3.x. Keduanya hanya ada di disk Anda:
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
milik money4band mencantumkannya.

money4band 5.0 mengenkripsi `config/user-config.json` di disk
([catatan keamanan](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
dan menghapus `.env` miliknya setelah setiap kali dijalankan
([env builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot tidak dapat membaca file terenkripsi itu. Jalankan `m4b config edit` di folder
money4band Anda: perintah itu membuka file yang sudah didekripsi di editor Anda
([referensi CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Salin seluruh teksnya, tempelkan di halaman impor, lalu tutup editornya.

Utamakan file JSON. Di `.env`, Docker Compose mengekspansi `$` dalam nilai tanpa tanda kutip,
sehingga kata sandi yang mengandung `$` tidak sama dengan yang tampak di file. CashPilot tidak
menebak: CashPilot meminta Anda mengetik ulang nilai itu.

## Cara mengimpor { #how-to-import }

1. Buka **Settings** (Pengaturan), lalu **Import from another tool** (Impor dari alat lain) (atau buka `/import`).
2. Tambahkan `user-config.json`, atau tempelkan teksnya. Biarkan pilihan alat pada "Tell from the
   files" (Tentukan dari file), atau pilih money4band.
3. Periksa tabelnya. Centang layanan yang Anda inginkan dan isi setiap nilai yang ditandai
   tidak ada.
4. Tekan **Save the ticked services** (Simpan layanan yang dicentang), lalu terapkan ke worker Anda dari
   halaman yang sama.

## Apa yang terbawa { #what-comes-over }

Nama kolom berasal dari
[template user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
milik money4band dan nama `.env` yang ditulis
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)-nya
(`<APP>_<FLAG>`, misalnya `REPOCKET_APIKEY`). money4band 5.0 tetap memakai
nama kolom yang sama di
[katalog aplikasi](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported) miliknya.

| Aplikasi money4band | Layanan CashPilot | Apa yang terbawa |
|---|---|---|
| `earnapp` | EarnApp | id perangkat (`uuid`), sehingga perangkat yang sudah Anda tautkan tetap menghasilkan |
| `honeygain` | Honeygain | email, kata sandi |
| `iproyalpawns` | IPRoyal Pawns | email, kata sandi |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | token |
| `repocket` | Repocket | email, kunci API |
| `earnfm` | Earn.fm | kunci API |
| `proxyrack` | ProxyRack | kunci API, UUID perangkat |
| `proxylite` | ProxyLite | id pengguna |
| `bitping` | Bitping | email, kata sandi |
| `mystnode` | Mysterium | diaktifkan; lihat catatan Mysterium di bawah |

Aplikasi yang Anda matikan di money4band muncul tanpa centang. Aplikasi yang mati dan
hanya memuat placeholder template (`yourHONEYGAINMail`) serta daftar port
tidak disertakan, sehingga `user-config.json` yang belum diubah menghasilkan tabel kosong.

Aplikasi berikut tercantum tetapi tidak dibawa:

| Aplikasi money4band | Alasan |
|---|---|
| `proxybase` | money4band menjalankan klien lama ProxyBase dengan id pengguna. CashPilot menjalankan klien terbaru, yang memerlukan Access Token dari proxybase.org. |
| `urnetwork` | money4band menyimpan token sesi. CashPilot memasukkan URnetwork dengan email dan kata sandi Anda. |
| `grass` | Grass berjalan sebagai ekstensi browser. CashPilot hanya melacaknya, dengan access token dari dasbor Grass. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot melacak aplikasi ini, tetapi tidak ada kontainer untuk diterapkan. |
| `packetshare`, `peer2profit`, `speedshare` | Tidak tersedia lagi. |

Aplikasi lain apa pun tercantum sebagai "CashPilot has no such service" (CashPilot tidak punya layanan seperti itu).

## Apa yang tidak pernah terbawa { #what-never-comes-over }

- **Nama perangkat.** CashPilot menamai setiap perangkat sesuai worker tempatnya berjalan, sehingga
  dua worker tidak pernah melaporkan nama yang sama. Perangkat lama Anda tetap tercantum sebagai
  offline di dasbor setiap penyedia sampai Anda menghapusnya di sana.
- **Proxy.** Tambahkan masing-masing di bagian **Proxies** (Proxy) di halaman **Fleet** (Armada), lalu jalankan
  salinan layanan Anda melaluinya; menambahkan proxy tidak menjalankan apa pun dengan sendirinya.
  Menyimpan impor juga tidak menjalankan apa pun. Salinan via proxy memerlukan layanan yang sama
  sudah diterapkan di worker terlebih dahulu, dan penerapan itu menjalankannya di koneksi milik worker sendiri,
  sehingga layanan yang sama sekali tidak boleh memakai koneksi itu sebaiknya tetap
  tidak dicentang. Lihat [Salinan via proxy](../proxies.md).
- **Watchtower dan notifikasi.** CashPilot memperbarui kontainernya sendiri.
- **Dasbor money4band dan port-nya.**

## Pelacakan penghasilan { #earnings-tracking }

Untuk Honeygain, IPRoyal Pawns, dan Bitping, login kontainer juga merupakan login
akun, sehingga CashPilot juga mengisi kredensial penghasilannya, kecuali Anda
sudah menyetelnya di **Settings** (Pengaturan). Untuk setiap layanan lain, tambahkan login penghasilan
di **Settings > Earnings collection** (Pengaturan > Pengumpulan penghasilan).

## Mysterium { #mysterium }

Impor mengaktifkan Mysterium, tetapi CashPilot memulai node baru dengan
identitas baru. Keystore node lama dan penghasilan yang belum diselesaikan tetap berada di
folder `.data/mysterium-node` milik money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Selesaikan dulu penghasilan itu, atau ikuti
[panduan Mysterium](../guides/mysterium.md) untuk membawa identitasnya.

`.env` versi 3.x tidak dapat menunjukkan apakah Anda menjalankan Mysterium: template-nya selalu
mencantumkan port dasbor. Dari file 3.x, Mysterium tidak diimpor, jadi tambahkan
dari katalog jika Anda menjalankannya.

## Keamanan { #safety }

- Tidak ada isi file yang dijalankan atau diekspansi, dan tidak ada alamat di dalamnya yang diambil.
- File dibaca sekali dan tidak disimpan. Apa yang Anda simpan disimpan dalam keadaan terenkripsi, seperti
  setiap kredensial lain di CashPilot.
- Rahasia hanya ditampilkan sebagai "set" (disetel) di halaman.
- Impor yang tersimpan tetap ada di halaman impor sampai Anda menekan **Forget** (Lupakan), sehingga Anda dapat
  menerapkannya ke lebih banyak worker nanti.
