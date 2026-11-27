---
source_hash: 7f8476aeb8b6
---
# Pindah dari CashFactory { #moving-from-cashfactory }

CashPilot dapat membaca `.env` milik CashFactory dan membawa login layanan Anda, sehingga
Anda tidak perlu mengetiknya lagi. Anda memeriksa semuanya sebelum CashPilot menyimpannya.

## Sebelum Anda mulai { #before-you-start }

Anda memerlukan akun pemilik CashPilot dan setidaknya satu worker CashPilot.

Hentikan CashFactory di sebuah mesin sebelum Anda menerapkan layanan yang sama di sana dari
CashPilot. Dua salinan di balik satu koneksi menghasilkan sebagai satu, dan id perangkat EarnApp
yang sama tidak boleh berjalan dua kali. Jalankan `docker compose down` di folder
CashFactory.
[File compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)-nya
juga menjalankan tiga kontainer yang memasang socket Docker: Portainer (baris 31)
dan dua kontainer Watchtower (baris 141 dan 264). Pastikan semuanya juga sudah hilang: `docker ps` seharusnya
tidak menampilkan satu pun.

## File mana yang dipakai { #which-file-to-use }

Gunakan file `.env` di folder CashFactory Anda, yang Anda isi berdasarkan
[contohnya](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

Docker Compose membaca file itu, dan mengekspansi `$` dalam nilai yang tidak berada di dalam
tanda kutip tunggal. Nilai seperti itu tidak sama dengan yang tampak di file, sehingga CashPilot meminta
Anda mengetik ulang alih-alih menebak.

## Cara mengimpor { #how-to-import }

1. Buka **Settings** (Pengaturan), lalu **Import from another tool** (Impor dari alat lain) (atau buka `/import`).
2. Tambahkan file `.env`, atau tempelkan teksnya. Biarkan pilihan alat pada "Tell from the
   files" (Tentukan dari file), atau pilih CashFactory.
3. Periksa tabelnya. Centang layanan yang Anda inginkan dan isi setiap nilai yang ditandai
   tidak ada.
4. Tekan **Save the ticked services** (Simpan layanan yang dicentang), lalu terapkan ke worker Anda dari
   halaman yang sama.

## Apa yang terbawa { #what-comes-over }

| Aplikasi CashFactory | Kunci yang dibaca | Layanan CashPilot | Apa yang terbawa |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | id perangkat, sehingga perangkat yang sudah Anda tautkan tetap menghasilkan |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | email, kata sandi |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | email, kata sandi |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | token |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | email, kunci API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | id pengguna |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID perangkat |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | kunci API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | tidak ada: tidak tersedia lagi |

Nilai yang masih menampilkan placeholder dari contoh (`<email>`, `sdk-node-<md5sum>`)
dianggap belum disetel, dan layanan yang hanya berisi placeholder tidak disertakan dalam
tabel.

## Apa yang tidak pernah terbawa { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot menamai setiap perangkat sesuai worker tempatnya berjalan, sehingga
  dua worker tidak pernah melaporkan nama yang sama. Perangkat lama Anda tetap tercantum sebagai
  offline di dasbor setiap penyedia sampai Anda menghapusnya di sana.
- **Bitping.** CashFactory menyimpan login Bitping di volume Docker, bukan di
  `.env`, sehingga impor tidak punya apa pun untuk dibaca dan tidak menampilkan baris Bitping. Ketik
  login itu di formulir penerapan Bitping.
- **Portainer dan Watchtower.** CashPilot mengelola dan memperbarui kontainernya
  sendiri.

## Pelacakan penghasilan { #earnings-tracking }

Untuk Honeygain dan IPRoyal Pawns, login kontainer juga merupakan login akun,
sehingga CashPilot juga mengisi kredensial penghasilannya, kecuali Anda sudah menyetelnya
di **Settings** (Pengaturan). Untuk setiap layanan lain, tambahkan login penghasilan di
**Settings > Earnings collection** (Pengaturan > Pengumpulan penghasilan).

## Keamanan { #safety }

- Tidak ada isi file yang dijalankan atau diekspansi, dan tidak ada alamat di dalamnya yang diambil.
- File dibaca sekali dan tidak disimpan. Apa yang Anda simpan disimpan dalam keadaan terenkripsi, seperti
  setiap kredensial lain di CashPilot.
- Rahasia hanya ditampilkan sebagai "set" (disetel) di halaman.
- Impor yang tersimpan tetap ada di halaman impor sampai Anda menekan **Forget** (Lupakan), sehingga Anda dapat
  menerapkannya ke lebih banyak worker nanti.
