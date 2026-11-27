---
source_hash: d88e40f8d9a6
---
# Saldo pembayaran on-chain { #on-chain-payout-balances }

Buka **Payouts** (Pembayaran) untuk melihat saldo pada alamat pembayaran publik. Bitcoin memakai
[mempool.space](https://mempool.space/docs/api/rest) dan Kaspa memakai
[api.kaspa.org](https://api.kaspa.org/docs). Ethereum, Polygon, dan Solana memakai
node RPC publik. CashPilot dapat membaca alamat-alamat ini tanpa kunci.

| Yang Anda lihat | Artinya |
|---|---|
| Sebuah jumlah | Explorer melaporkan saldo. Nol yang dilaporkan tampil sebagai nol. Arahkan kursor ke jumlah itu untuk melihat sumbernya. |
| **Pending** (Tertunda) | Di Bitcoin, explorer melihat perubahan yang belum dikonfirmasi. Tanda plus berarti dana sedang masuk. Tanda minus berarti dana sedang dibelanjakan. Jumlah yang sudah dikonfirmasi ditampilkan terpisah. |
| **Could not check** (Tidak dapat diperiksa) | Explorer gagal merespons atau mengirim data yang tidak dapat dibaca CashPilot. |
| **Address not valid** (Alamat tidak valid) | Alamat gagal dalam pemeriksaan format. CashPilot melewati permintaan itu. |
| **Private chain** (Chain privat) | Membaca saldo Monero memerlukan private view key Anda. Periksa saldonya di dompet Anda. CashPilot tidak pernah meminta kunci ini dari Anda. |
| Tanda pisah | Tidak ada alamat atau pembaca untuk baris ini, atau pencarian dimatikan. Jika sebuah pengaturan mematikan pencarian, arahkan kursor ke tanda pisah itu untuk melihat pengaturan yang mana. |

Endpoint publik Kaspa melaporkan satu saldo. Endpoint itu tidak menyediakan jumlah
tertunda yang terpisah.

Kolom on-chain menampilkan saldo pada alamat itu saat ini. Saldo ini bisa mencakup
transfer dari sumber lain. Saldo belum dibayar milik pool menunjukkan apa yang masih
ditahan pool untuk Anda. Pembayaran OCEAN melalui Lightning tidak muncul di
saldo on-chain. Saldo itu juga tidak dapat memberi tahu Anda transfer mana yang berasal dari
pool Anda.

## Pilih ke mana pencarian dikirim { #choose-where-the-lookup-goes }

Setiap pencarian membagikan alamat pembayaran publik Anda dan IP server UI kepada
explorer. Explorer dapat mengaitkan alamat-alamat yang Anda periksa dari IP yang sama.

Setel URL dasar di lingkungan kontainer UI jika Anda menjalankan node sendiri.
Biarkan variabel tidak diatur untuk memakai bawaan. Setel ke nilai kosong untuk mematikan
pencarian untuk chain itu.

Misalnya, override Compose untuk layanan UI bisa berisi:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Gunakan URL dasar API Esplora atau Kaspa saat mengonfigurasi Bitcoin atau Kaspa.
Endpoint Bitcoin juga memberikan tingkat kesulitan jaringan dan imbalan blok untuk
[perkiraan penghasilan](fleet.md#running-costs) pool Bitcoin. Pembacaan itu memerlukan
backend mempool (API `/v1/mining`-nya); server Esplora biasa hanya menjawab
pencarian saldo, dan baris pool lalu tidak menampilkan perkiraan jumlah.
Untuk Ethereum, Polygon, dan Solana, setel variabel yang sesuai
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON`, atau
`CASHPILOT_ONCHAIN_URL_SOLANA` ke URL RPC sebuah node. Gunakan URL HTTP atau HTTPS
tanpa kredensial, query string, atau fragmen. Terapkan perubahan dengan
membuat ulang kontainer UI dengan lingkungan yang baru.
