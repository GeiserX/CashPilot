---
source_hash: 915470497dbc
---
# Tanya jawab { #faq }

**Apakah berbagi bandwidth aman?**

Layanan berbagi bandwidth umumnya merutekan lalu lintas yang sah (riset pasar, verifikasi iklan, perbandingan harga, pengiriman konten) melalui koneksi Anda. Meski begitu, Anda membagikan alamat IP Anda, jadi tinjau dengan cermat ketentuan layanan dan kebijakan privasi setiap layanan sebelum mendaftar. Menjalankannya di VPS alih-alih IP residensial adalah salah satu pilihan untuk sebagian layanan. **Ini bukan nasihat hukum -- tanyakan langsung kepada layanan yang ingin Anda pakai dan, jika perlu, mintalah nasihat hukum independen mengenai yurisdiksi Anda.**

**Berapa banyak yang bisa saya hasilkan?**

Penghasilan sangat bervariasi tergantung lokasi, ISP, jumlah perangkat, dan layanan mana yang Anda jalankan. Dasbor melacak penghasilan Anda yang sebenarnya dari waktu ke waktu sehingga Anda bisa mengoptimalkan penyiapan Anda. Sebagai gambaran kasar, dan bukan janji, satu server rumah yang menjalankan 10 sampai 15 layanan menghasilkan sekitar $30 sampai $100 sebulan, dan bisa menghasilkan lebih sedikit, sampai nol. Lebih banyak server, atau komputasi GPU, menambah jumlah itu.

**Bisakah saya menjalankannya di VPS atau server cloud?**

Sebagian layanan memerlukan IP residensial dan tidak akan membayar (atau akan memblokir) IP VPS/pusat data. Katalog mencantumkan "IP residensial" di bawah apa yang dibutuhkan layanan. Layanan yang berfungsi di VPS adalah cara yang baik untuk berkembang tanpa perangkat keras tambahan di rumah.

**Bagaimana kredensial disimpan?**

Semua kredensial layanan dienkripsi saat diam di database SQLite menggunakan kunci Fernet yang disimpan di `/data/.fernet_key`, yang dibuat otomatis saat pertama kali dijalankan. File database berada di volume Docker yang dipasang (`cashpilot_data:/data`). Kredensial tidak pernah dikirim ke mana pun kecuali ke kontainer layanan itu sendiri.

Perhatikan bahwa kunci ini berbeda dari `CASHPILOT_SECRET_KEY`, yang hanya menandatangani sesi login.

### Mencadangkan kunci enkripsi { #backing-up-the-encryption-key }

Kredensial Anda hanya bisa dipulihkan selama `/data/.fernet_key` masih ada. Jika Anda kehilangan file itu, Anda harus memasukkan ulang setiap kredensial, karena tidak ada cara untuk mendekripsi nilai yang tersimpan tanpa file itu.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

File itu selalu lebih diutamakan daripada variabel lingkungan, jadi menyetel `CASHPILOT_ENCRYPTION_KEY` pada instans yang sudah punya kunci tidak mengubah apa pun dan aman. Variabel itu hanya dipakai jika belum ada file kunci, dan itulah tepatnya kasus pemulihan.

Jika CashPilot sama sekali tidak dapat menulis kunci ke disk, karena `/data` tidak dapat ditulis atau tidak dipasang, CashPilot menolak untuk berjalan alih-alih mengenkripsi kredensial Anda dengan kunci yang akan hilang pada restart berikutnya. Setel `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` jika itu memang yang Anda inginkan.

<a id="forgot-password"></a>

### Lupa kata sandi atau nama pengguna { #forgot-password-or-username }

CashPilot tidak punya fitur reset melalui email. Siapa pun yang menjalankan server mereset kata sandi dari konsol kontainer UI CashPilot. Layanan, penghasilan, dan kredensial tersimpan Anda tidak terpengaruh: semuanya dienkripsi dengan `/data/.fernet_key`, bukan dengan kata sandi Anda.

Perintah `python -m app.users` memerlukan CashPilot 2.3 atau yang lebih baru. Pada 2.2 atau yang lebih lama, perintah itu gagal dengan `No module named app.users`. Perbarui dulu: dengan Docker Compose, ubah tag `drumsergio/cashpilot` dan `drumsergio/cashpilot-worker` ke `2.3` atau yang lebih baru (penguncian seperti `2.2` atau `2.2.9` tetap berada di rilis itu), lalu jalankan `docker compose up -d` ([Memperbarui CashPilot](getting-started.md#updating-cashpilot)). Di Unraid, perbarui kontainernya.

1. Tampilkan daftar akun. Ini juga menampilkan nama pengguna yang Anda lupa. Nama pengguna peka huruf besar-kecil.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Setel kata sandi acak baru untuk akun itu. Ganti `alice` dengan nama pengguna dari langkah 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    Jika hanya ada tepat satu pemilik, Anda boleh tidak menyebutkan nama pengguna, dan perintah itu mereset pemilik tersebut. Jika nama pengguna diawali `-`, letakkan `--` di depannya: `reset-password -- -alice`.

    Perintah itu mencetak kata sandi baru satu kali.

3. Jika orang lain mungkin pernah punya akses ke akun itu, restart kontainer UI sekarang (`docker restart cashpilot-ui`). Browser yang masih login sebagai pengguna itu baru dikeluarkan setelah restart. Jika Anda hanya lupa kata sandi, restart bersifat opsional.
4. Login dengan kata sandi baru, lalu ubah dari menu avatar (kanan atas), **Change password** (Ubah kata sandi).

Nama kontainer tergantung cara Anda memasang CashPilot:

| Instalasi | Kontainer UI |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | nama yang dibuat otomatis; `docker ps` menampilkannya |

Portainer, Unraid, dan CasaOS juga punya tombol konsol untuk kontainer. Perintah ini tidak memerlukan input terminal, jadi juga berfungsi di sana.

Untuk mengubah nama pengguna:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

Nama baru mengikuti aturan pendaftaran: 3 sampai 32 huruf, angka, `_` atau `-`. Logout lalu login lagi untuk melihatnya.

**Setelah dugaan pembobolan**, misalnya cadangan hilang yang memuat `/data/.secret_key`, reset kata sandi saja tidak cukup. Siapa pun yang memiliki kunci itu dapat menandatangani cookie login yang valid, dan reset tidak menghentikannya. Ganti kuncinya, lalu restart kontainer UI. `&&` hanya me-restart kontainer jika kunci baru sudah terpasang; jika perintah itu mencetak galat, perbaiki dulu galat itu:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

Setelah restart, setiap browser dikeluarkan, dan semua orang login lagi dengan kata sandinya. Kredensial tersimpan tidak terpengaruh. Jika Anda sendiri yang menyetel `CASHPILOT_SECRET_KEY`, perintah itu menolak: masukkan nilai acak baru ke variabel itu dan buat ulang kontainernya sebagai gantinya. `docker run` dari image tidak melihat variabel itu dan tidak bisa menolak, jadi gunakan `docker exec` pada kontainer UI.

Kunci baru mengakhiri cookie palsu, tetapi tidak membatalkan apa yang dilakukan penyerang selama berada di dalam. Ada dua langkah lagi:

1. Jalankan `docker exec cashpilot-ui python -m app.users list`. Hapus dari dasbor setiap akun yang tidak Anda kenali.
2. Jika salinan yang hilang memuat seluruh `/data`, ubah kata sandi akun-akun penyedia Anda. `.fernet_key` dan `cashpilot.db` bersama-sama dapat mendekripsi setiap kredensial tersimpan.

Jika nanti Anda memulihkan cadangan yang dibuat sebelum rotasi, jangan sertakan `.secret_key`-nya ([Mencadangkan dan memulihkan](backup-restore.md#restore)), atau lakukan rotasi dan restart lagi. Jika tidak, kunci lama akan kembali. Database yang dipulihkan juga mengembalikan akun dan kata sandi yang dimuatnya, jadi ulangi pemeriksaan akun dan reset kata sandi yang diperlukan.

**Jika kontainer UI tidak mau berjalan**, jalankan perintah itu dari image yang sama terhadap data yang sama. Pertama, temukan folder host yang menyimpan `/data` milik UI. Cara ini berfungsi untuk kontainer yang berhenti, dan untuk volume bernama maupun bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Lalu pasang folder itu dan gunakan tag image yang Anda jalankan:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Periksa bahwa daftar itu menampilkan akun-akun Anda, lalu jalankan baris yang sama dengan `reset-password alice` sebagai pengganti `list`.

Path tanpa database memberikan galat "no database", dan perintah itu tidak membuat maupun mengubah apa pun di sana. Docker mungkin tetap meninggalkan folder atau volume kosong dengan nama itu; hapuslah.

**Jangan** hapus volume data: itu menghapus `/data/.fernet_key` dan bersamanya setiap kredensial tersimpan. **Jangan** juga menghapus baris dari tabel `users`.

**Bagaimana cara menghapus CashPilot sepenuhnya?**

`docker compose down -v` hanya menghapus kontainer milik CashPilot sendiri. Layanan yang diterapkannya tetap berjalan, dan datanya, jaringan berpagar, serta satu tabel firewall tetap ada. [Menghapus CashPilot sepenuhnya](uninstall.md) menghapus semuanya, menjelaskan apa yang hilang selamanya, dan menunjukkan cara memeriksa bahwa tidak ada yang tersisa.

**Bagaimana dengan keamanan?**

Setiap layanan yang diterapkan CashPilot berjalan di kontainernya sendiri dengan semua kapabilitas Linux dicabut (beberapa layanan hanya menambahkan kembali kapabilitas yang mereka deklarasikan) dan `--security-opt no-new-privileges` disetel, sehingga proses di dalamnya tidak dapat memperoleh hak istimewa. Kontainer tidak dapat melihat sistem file host Anda di luar volume yang dideklarasikan layanan. Pada instalasi baru, worker juga memagari kontainer dari LAN Anda, host, tailnet Anda, dan metadata cloud, sehingga kontainer menjangkau internet dan tidak ada yang lokal ([Isolasi jaringan](isolation.md)). Di Podman, pagar tidak tersedia: aplikasi penghasil berjalan di jaringan bawaan Podman, yang dapat menjangkau LAN Anda, dan halaman **Fleet** (Armada) menyatakannya ([Isolasi jaringan](isolation.md) mencantumkan pilihannya). Instalasi yang diperbarui dari rilis sebelum 1.70 tetap menempatkan aplikasi penghasilnya di bridge bawaan Docker, yang dapat menjangkau LAN Anda, sampai Anda mengeklik **Turn on isolation** (Aktifkan isolasi) di halaman **Fleet** (Armada). Sejak 2.0.7, Mysterium juga berjalan di balik pagar; node yang diterapkan dengan versi sampai 2.0.6 tetap berada di jaringan host sampai Anda menerapkannya ulang ([Memindahkan node Mysterium Anda ke balik pagar](mysterium-fence.md)). [Melindungi jaringan rumah Anda](home-network-security.md) membahas cara memasang firewall pada bridge Anda sendiri sebagai gantinya. Kredensial layanan dienkripsi saat diam dengan enkripsi simetris Fernet. UI tidak punya akses Docker. Dengan file compose yang dirilis, worker tidak pernah diberi socket Docker mentah: worker menjangkau Docker melalui `cashpilot-socket-proxy`, yang menolak kontainer privileged dan bind ke `/` atau ke socket (kecuali Anda memasukkan salah satunya, atau folder di atas socket, ke `CASHPILOT_PROXY_BIND_MOUNTS` atau `CASHPILOT_COMPOSE_DIR`: proxy menerimanya apa adanya), dan membatasi worker pada kontainer, volume, dan jaringan yang membawa label pemiliknya ([pengaturan keamanan bawaan](security-defaults.md)). Template Unraid dan aplikasi TrueNAS masih memasang socket mentah di worker, yang setara dengan root di host ([toko aplikasi](app-stores.md)).

Meski begitu, tidak ada penyiapan yang kebal. Anda tetap menjalankan perangkat lunak pihak ketiga yang merutekan lalu lintas eksternal melalui jaringan Anda. Isolasi Docker sangat mengurangi permukaan serangan dibandingkan menjalankan layanan ini langsung di host Anda, tetapi tidak menghilangkan semua risiko. Kami menyarankan menjalankan CashPilot di mesin atau VLAN khusus, selalu memperbarui Docker dan OS host Anda, dan meninjau kode sumber terbuka setiap layanan sebelum menerapkannya.

**Apa yang terjadi jika kontainer layanan crash?**

CashPilot terus memantau kesehatan kontainer. Jika kontainer layanan keluar secara tak terduga, kontainer itu otomatis di-restart. Dasbor menampilkan waktu aktif dan status kesehatan untuk setiap layanan yang berjalan.

**Node Mysterium saya tidak mau berjalan setelah diterapkan ulang. Mengapa?**

Penyebab paling umum adalah port dalam rentang UDP-nya yang sudah dipakai program lain di host. Docker harus memesan setiap port dalam rentang itu, jadi satu port yang terpakai menggagalkan start. [Memilih rentang port UDP](mysterium-fence.md#choosing-the-udp-port-range) menjelaskan cara memilih rentang yang tetap bebas.

**Salinan via proxy saya berjalan tetapi tidak menghasilkan apa pun. Mengapa?**

Proxy mungkin menolak terhubung ke server aplikasi penghasil itu, atau hanya mengizinkan port 80 dan 443. **Test** (Uji) di CashPilot hanya memeriksa bahwa proxy menjangkau internet. [Uji server aplikasi penghasil melalui proxy](proxies.md#probe-an-earners-servers-through-the-proxy) menunjukkan cara memeriksa host dan port milik aplikasi penghasil itu sendiri.

**Layanan mana yang berat, dan di mana sebaiknya dijalankan?**

Node penyimpanan, relay dan exit VPN, serta pekerjaan GPU paling banyak memakai sumber daya. [Menganggarkan mesin kecil](fleet.md#budgeting-a-small-box) mencantumkannya dan menunjukkan cara mengukur setiap kontainer sebelum Anda memutuskan.

<a id="worker-lost-docker"></a>

### Worker kehilangan Docker setelah pembaruan Docker { #the-worker-lost-docker-after-a-docker-update }

**Yang Anda lihat.** Worker tetap online di halaman **Fleet** (Armada), tetapi CashPilot tidak dapat menjalankan, menghentikan, atau memperbarui kontainernya. Halaman **Fleet** (Armada) menampilkan **Docker unreachable** (Docker tidak terjangkau) di samping worker. Setelah 10 menit, healthcheck worker gagal (`docker ps` menampilkan worker sebagai `unhealthy`). Setelah 30 menit, ikon lonceng dan notifikasi Anda menyatakan bahwa worker tidak dapat menjangkau Docker. `docker logs cashpilot-socket-proxy` menampilkan `upstream Docker socket unreachable`, dan dengan file compose terbaru, `docker ps` menampilkan proxy sebagai `unhealthy` dalam sekitar 3 menit. Aplikasi penghasil Anda tetap berjalan.

**Penyebab.** File compose yang dirilis melakukan bind file socket `/var/run/docker.sock` ke `cashpilot-socket-proxy`. Bind file memegang satu file itu. Pembaruan Docker (misalnya `unattended-upgrades` memasang `docker-ce` baru) me-restart Docker, dan Docker membuat file socket baru di path yang sama. Dengan live-restore Docker aktif, proxy tetap berjalan melewati restart itu dan tetap memegang file lama. Tidak ada yang menjawab di file lama itu.

**Perbaikan cepat.** Di mesin itu, restart proxy:

```bash
docker restart cashpilot-socket-proxy
```

Restart itu melakukan bind ke socket baru, dan worker menemukan Docker lagi pada sinyal aktif berikutnya. Anda tidak perlu me-restart worker. Di Unraid dan TrueNAS, worker memegang socket itu sendiri, jadi restart worker.

**Perbaikan permanen.** Lakukan bind ke folder socket, bukan ke file socket. Bind folder langsung menampilkan socket yang diganti. Di layanan `cashpilot-socket-proxy` pada file compose Anda, ganti baris `- /var/run/docker.sock:/var/run/docker.sock:ro` dengan bind di bawah, dan tambahkan baris `SOCKGUARD_UPSTREAM_SOCKET` ke `environment`-nya:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Lalu jalankan `docker compose up -d`. Perubahan yang sama berfungsi di `docker-compose.worker.yml` dan `docker-compose.fleet.yml`. Compose hanya membaca file-file itu jika Anda menyebutkannya, jadi jalankan `docker compose -f docker-compose.worker.yml up -d` atau `docker compose -f docker-compose.fleet.yml up -d`, kecuali `COMPOSE_FILE` sudah menyebutkan file itu.

- `recursive: disabled` wajib ada. `/var/run` memuat mount lain, misalnya namespace jaringan Docker di bawah `/run/docker/netns` dan `/run/user/...`. Bind rekursif membawa semuanya ke dalam proxy. Bind non-rekursif hanya menampilkan folder itu sendiri.
- `SOCKGUARD_UPSTREAM_SOCKET` mengarahkan proxy ke path baru. Blok kebijakan dan fingerprint-nya tetap seperti semula, karena variabel lingkungan itu menimpa `upstream.socket` di kebijakan. Tanpa variabel itu, proxy tidak mau berjalan (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` boleh tetap memakai bind file. Kontainer itu berjalan lagi pada setiap `docker compose up`, jadi selalu mendapat socket terbaru. Jika Anda memberinya bind folder yang sama, tambahkan `DOCKER_HOST=unix:///host-run/docker.sock` ke `environment`-nya. Worker 2.8.4 dan yang lebih baru membaca variabel itu. Jangan pernah mengarahkannya ke socket proxy: migrator memerlukan socket milik host sendiri.
- Bind folder memberi proxy setiap socket di `/var/run`, bukan hanya socket Docker. Pada server pada umumnya, itu mencakup socket milik systemd sendiri, D-Bus, dan socket alat seperti Tailscale atau snapd. `read_only` tidak mencegah program terhubung ke socket, dan proxy berjalan sebagai root. Akses ke socket Docker sudah memberi root di host, jadi proxy yang dibobol hanya mendapat sedikit hal yang sebelumnya tidak dimilikinya. Jika Anda ingin proxy hanya memegang socket Docker, pertahankan bind file dan restart proxy setelah pembaruan Docker: peringatan di atas memberi tahu Anda kapan.
- Diperlukan Docker Compose 2.30.0 atau yang lebih baru. Rilis yang lebih lama menolak seluruh file dengan `Additional property recursive is not allowed`. Jalankan `docker compose version` untuk memeriksa. Debian 13 menyertakan paket Compose 2.26.1, jadi di Debian pasang Compose dari repositori milik Docker sendiri. Pembaruan dari dalam aplikasi memakai Compose 2.33 miliknya sendiri, jadi dapat membaca file yang diubah.
- Ini hanya berfungsi di Linux. Docker Desktop di macOS dan Windows hanya memetakan `/var/run/docker.sock` ke dalam mesin virtualnya. Di sana, `/var/run` adalah folder di Mac atau PC Anda, tanpa socket Docker di dalamnya.
- Dengan Docker rootless, socket berada di `/run/user/<your uid>`, yang merupakan mount terpisah. Gunakan folder itu sebagai `source`.
- Di Podman, pertahankan bind file. Kami belum menguji bind folder di sana.

File yang dirilis tetap memakai bind file, karena bind folder memerlukan Compose 2.30 dan Linux, sedangkan CashPilot juga mendukung rilis Compose yang lebih lama dan Docker Desktop. File compose lebih baru yang Anda unduh tidak memuat perubahan Anda, jadi lakukan perubahan itu lagi setelah Anda mengganti file.
