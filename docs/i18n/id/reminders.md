---
source_hash: b4ae1a3ae496
---
# Uang yang menunggu: pengingat sebelum Anda kehilangan penghasilan { #money-waiting-reminders-before-you-lose-earnings }

Sebagian penyedia mengambil kembali uang yang terlalu lama mengendap. Saldo bisa kedaluwarsa setelah
berbulan-bulan tanpa aktivitas. Jendela klaim bisa tertutup. Penyedia bisa memblokir
akun, berhenti membayar, atau tutup selagi saldo Anda masih ada di sana.
CashPilot sudah membaca sebagian besar data yang diperlukan untuk melihat hal-hal ini sebelum terjadi. Panel
**Money waiting** (Uang yang menunggu) di dasbor menampilkan apa yang harus dilakukan dan kapan batasnya, dan
saluran notifikasi Anda mendapat push sebelum setiap tenggat.

CashPilot tidak pernah melakukan klaim atau menarik dana apa pun atas nama Anda. Setiap pengingat menautkan ke
halaman milik penyedia itu sendiri, dan Anda bertindak di sana.

## Apa yang diingatkannya { #what-it-reminds-you-about }

**Aturan dari ketentuan penyedia sendiri.** Setiap aturan mengutip ketentuan atau halaman bantuan
penyedia, serta tanggal terakhir seseorang membacanya. Tautan **Source** (Sumber) di
menu **More** (Lainnya) pada baris itu membukanya.

| Layanan | Pengingat | Kapan |
|---|---|---|
| Grass | Klaim USDC Stage 2 Anda | Paling lambat 22 Jan 2027. Grass menyimpan yang tidak diklaim. |
| MystNodes | Klaim imbalan bulan lalu | Dalam 30 hari setelah setiap distribusi bulanan |
| Honeygain | Tarik saldo Anda | 24 bulan setelah saldo pertama kali mencapai $20 |
| Honeygain | Biarkan satu perangkat tetap berbagi, atau lakukan pembayaran | 6 bulan setelah aktivitas atau pembayaran terakhir |
| Repocket | Biarkan satu perangkat tetap berbagi, atau tarik dana | 12 bulan setelah aktivitas atau pembayaran terakhir |
| Bitping | Tarik saldo Anda | 12 bulan setelah penarikan terakhir |
| Salad | Kumpulkan beberapa Reward Points, atau belanjakan saldo Anda | 12 bulan setelah saldo terakhir kali bertambah. Membelanjakan sebagian saldo tidak mengatur ulang hitungan ini. |

**Tarik dana.** CashPilot memberi tahu Anda saat saldo mencapai minimum
penyedia. Ini berlaku untuk setiap layanan yang dikumpulkannya, kecuali layanan yang
membayar sendiri secara otomatis. Saldo juga harus bernilai minimal $5, sehingga penyedia
dengan minimum 5 sen tidak mengganggu sejak sen pertama. Jika minimum penyedia
lebih tinggi, minimum penyedia yang berlaku. Jika CashPilot tidak dapat
mengonversi minimum atau saldonya, CashPilot tidak menampilkan apa pun. CashPilot tidak pernah menebak bahwa
Anda bisa menarik dana.

**Kedaluwarsa kredensial.** Anda mendapat push sebelum token atau cookie yang tersimpan kedaluwarsa.
CashPilot memakai tanggal kedaluwarsa yang dinyatakan oleh kredensial itu sendiri. Jika kredensial
tidak menyatakannya, CashPilot memakai masa berlaku umum untuk jenis kredensial itu, dihitung
dari hari Anda menyimpannya. Pemilik sudah melihatnya di bawah **Needs attention** (Perlu perhatian),
dengan tombol **Renew** (Perbarui), sehingga panel tidak mengulanginya. Hanya pemilik yang mendapat
pengingat kredensial dari API, sama seperti pemeriksaan kesehatan kredensial.
Kredensial yang ditolak penyedia sudah ada di ikon lonceng dan sudah dikirim sebagai push,
sehingga tidak dikirim lagi.

## Layanan mana yang dicakup { #which-services-it-covers }

Pengingat berlaku untuk layanan yang Anda pakai: layanan yang diterapkan, layanan yang Anda atur
sebagai eksternal di **Settings** (Pengaturan), atau aplikasi yang dilaporkan oleh ponsel. Layanan yang sudah Anda hapus
tetap dihitung selama masih menyimpan saldo, karena hitungan waktu ketidakaktifan dimulai
saat layanan itu berhenti. Layanan kustom dan layanan yang dihentikan tidak mendapat pengingat.

## Tanggal dan "atau lebih awal" { #dates-and-or-earlier }

Hitungan waktu aktivitas dimulai dari apa yang dicatat CashPilot:

- terakhir kali saldo bertambah,
- pembayaran terakhir,
- atau pembacaan pertama yang mencapai atau melebihi minimum.

Kadang hitungan waktu sudah dimulai sebelum pembacaan pertama CashPilot. Maka tenggat
sebenarnya mungkin lebih awal daripada yang bisa dilihat CashPilot, dan barisnya bertuliskan
"paling lambat 3 Okt 2027 atau lebih awal".

CashPilot menghapus riwayat penghasilan setelah 400 hari, sedangkan hitungan waktu Honeygain
berjalan selama 730 hari. Jadi CashPilot menyimpan awal setiap hitungan waktu saat pertama kali
melihatnya, dan tetap menyimpannya setelah riwayat di baliknya hilang. Pembayaran mengatur ulang
hitungan waktu, kecuali jika penyedia hanya menghitung perolehan. Salad salah satunya:
pembayaran yang masih menyisakan saldo tidak mengatur ulang 12 bulannya.

Tanggal tetap hilang dari daftar sehari setelah lewat, karena uangnya sudah hilang.
Hitungan waktu yang sudah lewat tetap ada dan menyatakan bahwa penyedia mungkin sudah menghapus
uang itu. Pengingat itu tetap ada sampai Anda menandainya selesai atau membisukannya, atau sampai pembayaran
mengatur ulang hitungannya.

## Apa yang bisa Anda lakukan dengan pengingat { #what-you-can-do-with-a-reminder }

Pemilik dan editor melihat tombol-tombolnya. Penonton hanya melihat pengingatnya. Hanya pemilik
yang dapat menindaklanjuti pengingat kredensial.

- **Done** (Selesai), atau **Requested** (Sudah diminta) untuk penarikan, menyembunyikan pengingat ini. Jendela
  bulanan muncul lagi bulan berikutnya. Penarikan muncul lagi sekali setelah 14 hari jika
  saldonya masih ada, dan menanyakan apakah pembayaran sudah tiba. Itu masih
  di dalam jendela sengketa 60 hari yang diberikan sebagian besar penyedia.
- **Snooze** (Tunda) menyembunyikannya selama sehari atau seminggu dan menahan push-nya. Penundaan tidak pernah
  melewati peringatan terakhir sebelum tenggat.
- **Not for me** (Bukan untuk saya), di menu **More** (Lainnya), membisukan satu pengingat, atau semua pengingat
  dari satu layanan. Satu contoh: Honeygain dalam mode JumpTask, di mana saldo yang tidak bertambah
  adalah hal normal. Pengingat yang dibisukan tercantum di bagian bawah panel, dengan
  **Unmute** (Bunyikan lagi).

Satu rumah tangga berbagi pilihan-pilihan ini. Jika satu orang menandai pengingat selesai, pengingat itu
selesai untuk semua orang. Setiap pilihan dicatat di log audit dengan nama
orang yang membuatnya.

## Push { #pushes }

Pengingat dikirim ke saluran yang Anda atur untuk peringatan: ntfy, webhook, atau Telegram
([konfigurasi](configuration.md)). Tanpa saluran yang diatur, panel adalah satu-satunya
tempat pengingat muncul.

- Satu push per peringatan. Misalnya, Grass mengirim push 60, 30, 7, dan 1 hari sebelum
  tanggalnya. Pengingat yang pertama kali terlihat 5 hari sebelum tanggalnya mengirim push sekali, dengan sisa 5
  hari.
- Push hanya dikirim antara pukul 09:00 dan 21:00. CashPilot memakai zona waktu
  pemilik pertama dari **Settings** (Pengaturan), lalu `TZ` milik kontainer, lalu UTC. Peringatan
  yang jatuh pada malam hari dikirim pada pemeriksaan pertama setelah 09:00.
- Jika lebih dari 3 push jatuh tempo sekaligus, Anda mendapat satu ringkasan saja. Ini
  terjadi pada hari Anda memperbarui versi, saat setiap saldo yang melebihi minimumnya muncul
  bersamaan.
- Push memuat layanan, apa yang harus dilakukan, apa yang akan hilang, tanggal, dan
  tautan penyedia. Push tidak pernah memuat saldo, alamat, id perangkat, atau
  nama worker. Topik ntfy bisa bersifat publik.
- Payload webhook memuat `kind: "obligation"`, sehingga Home Assistant dan alat
  serupa dapat merutekannya.

## Untuk kontributor katalog { #for-catalog-contributors }

Aturan berada di file YAML setiap layanan, di bawah `obligations:`.
`services/_schema.yml` mendokumentasikan kolom-kolomnya. Tambahkan aturan hanya jika
ketentuan atau dokumentasi penyedia sendiri menyatakannya, dan jika CashPilot dapat melihat sinyal yang
menjadi dasarnya. Tautan sebuah aturan harus berada di domain milik layanan itu sendiri, karena situs klaim
palsu memang ada untuk layanan-layanan ini. CI gagal pada aturan yang tidak valid, dan
pada aturan bertanggal yang sudah lewat lebih dari 30 hari.
