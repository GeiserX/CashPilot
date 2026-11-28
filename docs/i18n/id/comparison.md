---
source_hash: b48a8fc19aa4
---
# Perbandingan CashPilot { #how-cashpilot-compares }

Halaman ini membandingkan CashPilot dengan proyek terbuka lain yang menjalankan beberapa aplikasi penghasilan pasif di Docker. Kami memeriksa setiap proyek pada 2026-11-04, dan CashPilot sekali lagi pada 2026-11-28. Setiap sel tentang proyek lain menautkan ke file sumbernya, pada commit yang tetap, sehingga Anda dapat memeriksanya sendiri. Jika sebuah sel salah atau sudah usang, silakan [buka issue](https://github.com/GeiserX/CashPilot/issues).

## Proyek yang dibandingkan { #projects-compared }

| Proyek | Yang kami periksa | Bintang pada 2026-11-04 | Lisensi |
|---|---|---|---|
| [money4band][m4b-tree] | Rilis 5.0.0, commit tag `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` di `65e900d` (2026-10-20), ditambah klaim README tentang binary 3.0.0-beta.9-nya | 238 | Proprietary, [lisensi sendiri v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` di `db9338a` (2026-11-03) | 257 | Tidak ada file LICENSE. [README][ii-license] mengizinkan penyalinan versi asli dan melarang distribusi salinan yang dimodifikasi |
| [CashFactory][cf-tree] | `main` di `0ff4bd0` (2025-04-08) | 410 | File [LICENSE][cf-license-file] adalah GPL-3.0, tetapi [README][cf-license] melarang distribusi salinan yang dimodifikasi |
| [home-assistant-passive-income][ha-tree] (add-on HA) | Rilis 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | Rilis v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band punya dua jalur kode. Branch bawaannya `main` (`3bfafb1`) masih memuat kode 4.x, dan perubahan kode terakhirnya di sana terjadi pada 2026-03-03. Rilis 5.0.0 dibangun dari riwayat terpisah. Kami membandingkan 5.0.0 karena itulah yang dirilis pada rilis terbarunya.

UI web, pengelolaan armada, dan binary penginstal IGM bersifat sumber tertutup dan tidak ada di repositorinya. Jika sebuah sel bergantung pada bagian itu, sel tersebut menyebut "klaim README" dan menautkan baris README-nya. Semua hal lain di kolom IGM berasal dari skrip shell dan file compose di repo.

Tidak disertakan: [earning-machine](https://github.com/jf-m/earning-machine) dan [passiveMachine](https://github.com/Xpl0itU/passiveMachine) tidak punya commit sejak 2024. Pencarian di GitHub tidak menemukan proyek lain yang masih dipelihara dan menjalankan lebih dari satu aplikasi, hanya image untuk satu aplikasi.

## Versi singkat { #short-version }

- **InternetIncome, money4band, IGM dan, sejak v1.69.0, CashPilot dapat menghasilkan dari banyak IP melalui proxy.** Tiga yang pertama menjalankan setiap aplikasi sekali per proxy, dan proxy adalah fitur utama InternetIncome. CashPilot menjalankan salinan tambahan dari layanan yang sudah diterapkan di worker, masing-masing melalui proxy SOCKS5, HTTP CONNECT, atau exit node Tailscale ([salinan via proxy](proxies.md)).
- **InternetIncome menjalankan 23 aplikasi, IGM menjalankan 20, dan worker CashPilot menjalankan <!-- n:docker -->21<!-- /n -->.** CashPilot melacak lebih banyak layanan secara total (<!-- n:live -->50<!-- /n -->) karena juga mengikuti layanan ekstensi browser, desktop, dan GPU yang tidak dijalankannya. Sejak v1.64.0, CashPilot juga dapat menjalankan image apa pun yang Anda sebutkan sebagai [layanan kustom](custom-services.md).
- **money4band dan IGM mengklaim imbalan harian untuk Anda, dan menjaga image aplikasi tetap terbaru dengan Watchtower.** CashPilot tidak melakukan keduanya. CashPilot baru menarik image lagi saat Anda menerapkan atau menerapkan ulang.
- **CashPilot satu-satunya di sini yang membaca saldo dari akun penyedia Anda dan menyimpan riwayatnya.** money4band 5.0.0 menampilkan perkiraan dari katalognya sendiri, bukan dari akun Anda. Yang lain menautkan ke dasbor setiap penyedia.
- **CashPilot satu-satunya yang bersumber terbuka di sini dengan satu UI untuk banyak server.** README IGM mengklaim pengelolaan armada, tetapi kode itu ada di binary tertutupnya.
- **Sejak v1.70.0, CashPilot satu-satunya di sini yang secara bawaan menjauhkan kontainer aplikasi penghasil dari LAN Anda, dengan batasan.** Fitur ini aktif untuk instalasi baru dan untuk instalasi yang diperbarui tanpa aplikasi penghasil di bridge bawaan Docker. Instalasi yang diperbarui dan aplikasi penghasilnya sudah berada di bridge itu tetap menempatkannya di sana sampai Anda mengaktifkan isolasi, dan jaringan yang Anda sebutkan di `CASHPILOT_CONTAINER_NETWORK` tidak mendapat pagar dari CashPilot ([isolasi](isolation.md#modes)). Sejak 2.0.7, Mysterium juga berjalan di balik pagar; node yang diterapkan dengan versi sampai 2.0.6 tetap berada di jaringan host, tanpa pagar, sampai Anda menerapkannya ulang ([Mysterium di balik pagar](mysterium-fence.md)).

## Berdampingan { #side-by-side }

Kolom CashPilot menggambarkan v3.0.1. Setiap selnya singkat, dan [catatan di bawah tabel](#cashpilot-notes) memuat detail dan tautan kodenya. Kolom lain menggambarkan commit di tabel di atas.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | Add-on HA |
|---|---|---|---|---|---|---|
| Aplikasi yang dapat dijalankannya (lihat [cara kami menghitung](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> dijalankan oleh worker, ditambah [image kustom](custom-services.md); <!-- n:live -->50<!-- /n --> dilacak secara total | 15 ([katalog][m4b-catalog]). README menyebut 35, yang [mencakup][m4b-readme-35] aplikasi komunitas dan aplikasi yang sudah ditinggalkan | 20 ([apps.json][igm-apps]) | 23 ([skrip][ii-script]) | 11 ([file compose][cf-compose]) | 10 ([folder add-on][ha-tree]) |
| Cara memasangnya | Docker Compose: satu UI, ditambah satu worker di setiap server ([armada](fleet.md)) | CLI Python atau binary siap pakai yang menulis file compose ([rilis][m4b-tree]) | Penginstal `curl \| sh` ([README][igm-install]) yang mengunduh binary tertutup, yang hanya diperiksa terhadap file SHA256SUMS dari rilis yang sama ([penginstal][igm-installer-sums]) | Satu skrip bash sepanjang 1.608 baris yang memanggil `sudo docker run` ([skrip][ii-script]) | File compose statis ditambah `setup.sh` yang dijalankan dengan sudo ([penyiapan][cf-setup]) | Repositori add-on Home Assistant; memerlukan Home Assistant OS atau Supervised |
| Banyak server, satu tampilan | Ya ([armada](fleet.md)) | Tidak, satu stack per perangkat | README mengklaim ya, di binary tertutup ([README][igm-features]) | Tidak | Tidak | Tidak |
| Banyak proxy atau IP | Ya, melalui proxy SOCKS5, HTTP CONNECT, atau exit node Tailscale ([salinan via proxy](proxies.md), [catatan](#cashpilot-notes)) | Ya ([README][m4b-features], [kode][m4b-multiproxy]) | Ya ([README][igm-features], [compose][igm-proxy]) | Ya, fitur utamanya ([README][ii-readme-top]) | Tidak | Tidak |
| Penghasilan | <!-- n:collectors -->20<!-- /n --> kolektor membaca saldo dari akun penyedia Anda dan menyimpan riwayatnya | Perkiraan dari rentang katalog, bukan data akun ([kode][m4b-earnings]) | Tidak ditemukan di skripnya | Tidak ada | Tidak ada | Tidak ada |
| Pembayaran | Mengusulkan pembayaran saat saldo turun, dan mencatatnya setelah Anda mengonfirmasi ([skema][cp-payouts]) | Tidak ada | Tidak ada | Tidak ada | Tidak ada | Tidak ada |
| Klaim imbalan harian | Tidak | Ya, sidecar ([README][m4b-features]) | Ya ([README][igm-features], [compose][igm-sidecars]) | Tidak | Tidak | Tidak |
| Kredensial saat diam | Dienkripsi (Fernet) di database UI ([catatan](#cashpilot-notes)) | Dienkripsi (Fernet); file kuncinya berada di direktori data ([kode][m4b-crypto]) | Dienkripsi (AES-256 dengan openssl); file kuncinya berada di samping vault ([kode][igm-encryptor]) | Teks biasa di `properties.conf`; sebagian kata sandi diteruskan sebagai argumen `docker run` ([skrip][ii-password-arg]) | Teks biasa di `.env` ([file][cf-env]) | Opsi add-on, disimpan oleh Supervisor di `/data/options.json` ([dokumentasi HA][ha-options]) |
| Pengaturan kontainer aplikasi penghasil | Semua kapabilitas dicabut, `no-new-privileges`, batas pids; privileged ditolak ([catatan](#cashpilot-notes)) | `no-new-privileges` pada setiap layanan yang tidak privileged ([kode][m4b-nnp]); kontainer proxy privileged dengan `NET_ADMIN` ([template][m4b-tun]) | Tidak ada yang disetel pada layanan aplikasi; Mysterium mendapat `NET_ADMIN` ([compose][igm-hosting-myst]); kontainer proxy mendapat `NET_ADMIN`, dengan `no-new-privileges` dan batas pids ([compose][igm-proxy]) | Ebesucher berjalan dengan `seccomp=unconfined` ([skrip][ii-seccomp]); kontainer proxy dan Mysterium mendapat `NET_ADMIN` | Tidak ada yang disetel | Tidak ada add-on yang meminta privileged, jaringan host, atau akses API Docker ([contoh konfigurasi][ha-config]) |
| Socket Docker dipasang ke | Socket proxy, baca saja, dan satu kontainer migrasi sekali jalan ([catatan](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, yang baca saja dengan `no-new-privileges` ([compose][igm-watchtower]) | Lima kontainer pembantu restart ([skrip][ii-sock-helper]) dan Watchtower ([skrip][ii-watchtower]) | Portainer, dipublikasikan di port 8000, 9000, dan 9443 pada semua antarmuka ([compose][cf-portainer]), dan dua Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | Tidak ada |
| Tag image | <!-- n:pinned -->9<!-- /n --> dari <!-- n:docker -->21<!-- /n --> image aplikasi penghasil dikunci ke versi atau digest; sisanya mengambang | Ke-15 image aplikasi memakai `:latest` ([contoh][m4b-image]); kontainer proxy dikunci ke v2.6.0, Watchtower ke `:1` | Tanpa tag, jadi Docker memakai `latest` ([compose][igm-hosting]); tag hanya disetel untuk sebagian build ARM | Sebagian besar `:latest` ([contoh][ii-seccomp]); EarnApp `:lite`, Honeygain dikunci ke 0.6.6 saat via proxy di amd64 ([skrip][ii-honeygain]), Traffmonetizer dengan tag per arsitektur di ARM; Watchtower `:nightly` | `:latest` atau tanpa tag, kecuali EarnApp `:lite` ([compose][cf-compose]) | Satu versi per add-on, dinaikkan oleh job CI harian ([workflow][ha-bump], [contoh][ha-dockerfile]) |
| Pembaruan image aplikasi | Ditarik lagi pada setiap penerapan atau penerapan ulang; tidak ada pembaru otomatis | Watchtower ([template][m4b-watchtower]) | Watchtower setiap 4 jam ([compose][igm-watchtower]) | Watchtower sekali sehari, jika Anda mengaktifkannya ([skrip][ii-watchtower]) | Dua Watchtower, masing-masing dibatasi pada satu aplikasi, PacketStream ([compose][cf-watchtower-ps]) dan EarnFM ([compose][cf-watchtower-efm]); 9 aplikasi lainnya tidak diperbarui | Pembaruan add-on Home Assistant |
| Isolasi LAN | Aktif secara bawaan untuk instalasi baru ([isolasi](isolation.md#lan-isolation-by-default), [catatan](#cashpilot-notes)) | Subnet bridge sendiri ([konfigurasi][m4b-subnet]), yang tidak memblokir LAN | Tidak ada yang digabungkan | Tidak ditemukan | Tidak ditemukan | Tidak ditemukan |
| ARM | UI dan worker arm64, dengan pemeriksaan platform sebelum setiap penerapan ([ARM](arm.md)) | Binary arm64 dan armv7 ([rilis][m4b-release]) | README mengklaim amd64 dan arm64, arm32 dengan batasan, dan menyiapkan QEMU ([README][igm-arch]) | Memerlukan emulasi binfmt untuk image yang hanya amd64 ([README][ii-arm]) | README menyatakan tidak berfungsi di Raspberry Pi ([README][cf-raspberry]) | Per add-on; ProxyRack hanya amd64 ([konfigurasi][ha-proxyrack]) |
| UI | UI web, ditambah klien Desktop, Android, MCP, dan Home Assistant | CLI, menu, dan dasbor web lokal yang secara bawaan terikat ke 127.0.0.1 ([kode][m4b-bind]) | CLI, menu, dan menurut README sebuah UI web di port 4747 yang dapat dijangkau di LAN ([README][igm-webui]) | Tidak ada, hanya skrip | Halaman bookmark di port 80 ditambah Portainer ([README][cf-ui]) | Panel add-on Home Assistant |
| Rilis terbaru | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | Tidak ada rilis bernomor versi | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| Panggilan keluar selain aplikasi | Pemeriksaan pembaruan, pencarian IP publik, kurs, dan saldo on-chain; font dan Chart.js dari CDN ([catatan](#cashpilot-notes)) | Rilis GitHub, untuk pemeriksaan pembaruannya ([kode][m4b-updater]); Docker Hub dan ghcr.io, untuk memeriksa tag image ([kode][m4b-registry]); saat Anda menjalankan pemeriksaan IP, `api.ipify.org`, `ifconfig.me` atau `icanhazip.com` untuk IP publik Anda dan `ip-api.com` melalui HTTP biasa untuk skor IP ([kode][m4b-ipscore]) | Rilis GitHub ([kode][igm-version]); `api.ipify.org`, `ifconfig.me` atau `icanhazip.com` untuk IP publik Anda ([kode][igm-ifconfig]); `ip-api.com` melalui HTTP biasa untuk skor IP ([kode][igm-ipscore]). Binary tertutupnya tidak diperiksa | Tidak ditemukan | Tidak ditemukan | Tidak ditemukan |

### Catatan tentang kolom CashPilot { #cashpilot-notes }

- **Banyak proxy atau IP.** Sejak v1.69.0, CashPilot menjalankan salinan tambahan dari layanan yang sudah diterapkan di worker, masing-masing melalui proxy-nya sendiri. SOCKS5 dan HTTP CONNECT hanya membawa TCP: terowongan hanya meloloskan TCP ke port proxy, sehingga relay UDP SOCKS5 dibuang. Exit node Tailscale juga membawa UDP. Aplikasi penghasil berbagi namespace jaringan sebuah kontainer terowongan ([kode][cp-proxy-deploy]). Namespace itu hanya meloloskan loopback, terowongan, dan koneksi terowongan itu sendiri ke proxy: TCP ke alamat dan port-nya, atau paket bertanda milik tailscaled ([firewall terowongan][cp-tunnel-fw]). Jadi proxy yang mati menghentikan aplikasi penghasil, bukan membocorkan lalu lintasnya ([cara kerjanya](proxies.md#how-it-works)). Sebuah layanan tidak dapat berjalan melalui proxy jika memerlukan jaringan host, port yang dipublikasikan, volume, perangkat, GPU, atau `NET_ADMIN`, `NET_RAW` atau `SYS_ADMIN`, atau jika ketentuannya melarang proxy. Jadi <!-- n:noproxy -->10<!-- /n --> dari <!-- n:docker -->21<!-- /n --> hanya menghasilkan dari IP server itu sendiri ([yang tidak bisa](proxies.md#what-cannot-run-through-a-proxy)).
- **Penghasilan.** Sebagian kolektor memerlukan cookie atau token yang disalin dari browser Anda, dan sebagian di antaranya kedaluwarsa. Panduan setiap layanan menyebutkan yang mana.
- **Kredensial saat diam.** UI menyimpan file kunci enkripsi di volume data yang sama dengan database ([kode][cp-fernet]). Kredensial aplikasi penghasil sampai ke setiap worker sebagai variabel lingkungan kontainer, sehingga berupa teks biasa di konfigurasi Docker worker itu (`docker inspect`).
- **Pengaturan kontainer aplikasi penghasil.** Worker mencabut semua kapabilitas, lalu menambahkan kembali yang dicantumkan katalog untuk layanan itu. Worker menyetel `no-new-privileges` dan batas pids, dan menolak kontainer privileged ([kode][cp-hardening], [kode][cp-privileged], [pengaturan keamanan bawaan](security-defaults.md)). Mysterium berjalan di namespace jaringannya sendiri pada bridge berpagar dengan `NET_ADMIN`, `SETUID` dan `SETGID`, pada image yang dikunci dengan digest ([katalog][cp-myst]). Runtime gVisor opsional dapat menambahkan kernel di ruang pengguna ([runtime](security-defaults.md#container-runtimes-gvisor-where-it-works)).
- **Socket Docker.** Sejak v1.71.0, hanya socket proxy yang memasang socket: sockguard 2.4.7, dikunci dengan digest, baca saja ([compose][cp-sock]). Worker mendapat salinan terfilter yang menolak kontainer privileged, bind ke `/` atau ke socket, serta kapabilitas atau perangkat di luar yang ada di katalog ([socket proxy](security-defaults.md#docker-socket-proxy)). Kontainer sekali jalan `cashpilot-migrate` juga memasang socket: kontainer itu memberi label pada apa yang dibuat oleh rilis lama, untuk isolasi pemilik pada proxy, lalu keluar sebelum proxy mulai ([compose][cp-migrate]). Aplikasi penghasil tidak pernah mendapat socket ([kode][cp-mounts]). Proxy itu belum menjadi batas root: jika `CASHPILOT_COMPOSE_DIR` atau `CASHPILOT_PROXY_BIND_MOUNTS` disetel, symlink yang ditanam di folder yang diizinkan dapat mencapai `/` milik host dalam dua penerapan ([detail](security-defaults.md#docker-socket-proxy)). Listing Unraid dan TrueNAS masih memasang socket mentah di worker ([toko aplikasi](app-stores.md)).
- **Isolasi LAN.** Aktif secara bawaan sejak v1.70.0, untuk instalasi baru dan untuk instalasi yang diperbarui tanpa aplikasi penghasil di bridge bawaan Docker. Worker menempatkan aplikasi penghasil di bridge miliknya sendiri dan menulis tabel firewall untuk bridge itu ([kode][cp-fence]). Tabel itu membuang rentang privat, rentang tailnet, metadata cloud, subnet yang terhubung ke host, dan host itu sendiri. Jika deteksi IP publik aktif, tabel itu juga membuang IP publik rumah ([isolasi](isolation.md#lan-isolation-by-default)). Instalasi yang diperbarui dan aplikasi penghasilnya sudah berada di bridge bawaan tetap di sana sampai Anda menekan **Turn on isolation** (Aktifkan isolasi). `CASHPILOT_ISOLATION=off` menonaktifkannya. Jika `CASHPILOT_CONTAINER_NETWORK` disetel, CashPilot tidak menulis pagar untuk jaringan itu, dan aturan firewall menjadi urusan Anda. Di Podman tidak ada pagar, dan halaman armada menyebutkannya ([mode](isolation.md#modes), [kode][cp-fence-mode]). Sejak 2.0.7, Mysterium juga berada di balik pagar. Node yang diterapkan dengan versi sampai 2.0.6 tetap berada di jaringan host sampai Anda menerapkannya ulang ([Mysterium di balik pagar](mysterium-fence.md)). Sebuah pemeriksaan menunjukkan apa yang dapat dijangkau aplikasi penghasil ([pemeriksaan](isolation-check.md)).
- **Panggilan keluar.** Selain aplikasinya sendiri, CashPilot memanggil:
    - Rilis GitHub, sekali sehari, untuk pemeriksaan pembaruannya (`CASHPILOT_UPDATE_CHECK=off` menghentikannya, [kode][cp-update]).
    - `api.ipify.org`, `ifconfig.me` atau `icanhazip.com` sekali per jam dari setiap worker, untuk IP publiknya (`CASHPILOT_EGRESS_DETECT=off` menghentikannya, [kode][cp-egress]).
    - CoinGecko dan Frankfurter, untuk kurs ([kode][cp-rates]).
    - mempool.space, api.kaspa.org, dan node RPC publik Ethereum, Ethereum Classic, Polygon, dan Solana, untuk [saldo on-chain](onchain.md).
    - iptoasn.com, untuk tabel nama jaringannya, paling sering sekali seminggu dan hanya selama ada worker yang mengaktifkan [aktivitas](activity.md#network-names-and-countries) ([kode][cp-ipgeo]).
    - Setiap penyedia, untuk kolektor.

    Browser memuat Google Fonts ([template][cp-cdn]) dan Chart.js dari jsDelivr ([template][cp-chartjs]).

Tidak ada satu pun proyek yang mengirim telemetri penggunaan dalam kode yang kami baca. Binary tertutup IGM tidak dapat dibaca.

Setiap proyek di sini meneruskan kredensial aplikasi ke kontainer sebagai variabel lingkungan, dan InternetIncome juga meneruskan sebagian sebagai argumen perintah, sehingga di host yang menjalankan aplikasi, kredensial itu berupa teks biasa di konfigurasi kontainer Docker (`Env` dan `Args` di `docker inspect`), dapat dibaca siapa pun yang punya akses Docker. Baris "Kredensial saat diam" hanya menggambarkan salinan yang tersimpan.

## Cara kami menghitung { #how-we-counted }

- **CashPilot.** Layanan di katalog dengan status active atau beta dan memiliki image Docker, tidak termasuk komputasi GPU atau pool penambangan. Angka di halaman ini berasal dari `scripts/generate_readme_tables.py`, dan CI gagal jika angkanya menyimpang.
- **money4band 5.0.0.** Satu file JSON per aplikasi di `config/catalog/supported/`: 15. "35 aplikasi" di README juga menghitung katalog komunitas, yang secara bawaan nonaktif ([konfigurasi][m4b-community]), aplikasi tanpa image Docker, dan aplikasi yang sudah ditinggalkan.
- **IGM.** Entri di `apps.json`: 20, semuanya aktif. Kontainer proxy, Watchtower, dan sidecar klaim tidak dihitung.
- **InternetIncome.** Setiap blok komentar `# Starting ... container` di `internetIncome.sh`, selain blok proxy dan Watchtower: 24. Blok Chrome dan Firefox milik Ebesucher adalah satu aplikasi, demikian pula EarnFM dan EarnFM Fleetshare, yang memakai akun EarnFM yang sama. Blok ekstensi Depin menjalankan Grass dan Gradient ([skrip][ii-depin]), dua aplikasi. Total 23. Tabel README mencantumkan 27 aplikasi, sebagian hanya dengan tautan pendaftaran.
- **CashFactory.** Layanan penghasil di `docker-compose.yml`: 11. Portainer, server web, dan dua Watchtower tidak dihitung. Satu layanan dinonaktifkan dengan komentar.
- **Add-on HA.** Folder add-on yang memiliki file konfigurasi: 10.

Kami tidak memeriksa apakah setiap aplikasi di setiap daftar masih membayar.

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
