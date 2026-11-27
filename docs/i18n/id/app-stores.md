---
source_hash: e99e2c0c80bb
---
# Toko aplikasi { #app-stores }

Anda dapat memasang CashPilot dari toko aplikasi beberapa sistem server rumahan.
Setiap listing memasang dasbor (`drumsergio/cashpilot`) dan worker
(`drumsergio/cashpilot-worker`), yang menjalankan dan menghentikan kontainer
layanan. Hanya paket CasaOS dan Runtipi di repositori ini yang juga
memasang socket proxy Docker dari `docker-compose.yml`, sehingga worker-nya
tidak pernah memegang socket Docker mentah. Template Unraid, aplikasi TrueNAS, dan
paket di pull request toko aplikasi CasaOS yang masih terbuka tetap memasang socket
Docker langsung di worker.

Toko mana pun yang Anda pakai, simpan dasbor di LAN atau VPN Anda. Dasbor dapat memberi perintah
ke worker, dan worker mengendalikan Docker di host. Jika worker memegang
socket itu sendiri, itu setara dengan root di host.

## Sudah tersedia { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Cari **CashPilot** di tab Apps dan pasang kedua template:
`cashpilot` (dasbor) dan `cashpilot-worker`. Setel
`CASHPILOT_API_KEY` yang sama pada keduanya.

Template berasal dari https://github.com/GeiserX/docker-templates dan mengikuti
tag image `latest`, sehingga pengguna Community Applications mendapat setiap rilis
tanpa perubahan template.

### TrueNAS SCALE { #truenas-scale }

CashPilot ada di train **community** TrueNAS. Buka Apps, lalu Discover Apps,
dan cari **CashPilot**.

Definisi aplikasinya dikelola di
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot dan mengunci
digest image yang persis. Bot milik TrueNAS sendiri yang memindahkannya ke rilis baru, jadi versinya bisa
tertinggal beberapa rilis dari CashPilot terbaru.

## Menunggu tinjauan { #waiting-for-review }

### CasaOS { #casaos }

Pull request ke toko aplikasi CasaOS sudah dibuka:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Sampai pull request itu digabungkan, pasang sebagai aplikasi kustom: di CasaOS pilih App Store,
lalu Custom Install, lalu Import, dan tempelkan isi
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

Diperlukan CasaOS 0.4.5 atau yang lebih baru: sejak rilis itu pengelola aplikasinya dibangun di atas
Docker Compose 2.23, yang membaca kebijakan socket proxy dari file tersebut.
Versi yang lebih lama membuangnya, dan worker lalu tidak dapat menjangkau Docker.

File itu mengunci satu rilis yang persis. Sebelum Anda mengimpornya, setel kedua tag image
(`drumsergio/cashpilot` dan `drumsergio/cashpilot-worker`) ke rilis
terbaru dari https://github.com/GeiserX/CashPilot/releases. Kebijakan proxy
di file itu mengikuti `main`; jika halaman status worker mengatakan kebijakannya
sudah usang, impor file itu lagi.

## Sudah disiapkan, belum diajukan { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

Paketnya sudah siap di
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
tetapi belum ada di toko aplikasi Runtipi. Untuk memakainya sekarang, tambahkan ke toko aplikasi
kustom yang Anda kendalikan, dengan mengikuti dokumentasi Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## Tidak ditawarkan { #not-offered }

Umbrel memerlukan desain worker yang berbeda, karena aplikasi Umbrel menjangkau Docker
melalui kontainer Docker-in-Docker, bukan socket host. Kami belum
mengujinya, jadi belum ada paket Umbrel.

Untuk sistem lain apa pun, gunakan `docker-compose.yml` dari repositori, seperti di
[Memulai](getting-started.md).
