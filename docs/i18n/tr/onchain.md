---
source_hash: d88e40f8d9a6
---
# Zincir üstü ödeme bakiyeleri { #on-chain-payout-balances }

Herkese açık bir ödeme adresindeki bakiyeyi görmek için **Payouts** (Ödemeler) sayfasını açın.
Bitcoin [mempool.space](https://mempool.space/docs/api/rest), Kaspa ise
[api.kaspa.org](https://api.kaspa.org/docs) kullanır. Ethereum, Polygon ve Solana herkese açık
RPC düğümleri kullanır. CashPilot bu adresleri bir anahtar olmadan okuyabilir.

| Gördüğünüz | Anlamı |
|---|---|
| Bir tutar | Gezgin bir bakiye bildirdi. Bildirilen sıfır, sıfır olarak görünür. Kaynağı görmek için imleci tutarın üzerine getirin. |
| Bekliyor | Bitcoin'de gezgin onaylanmamış bir değişiklik görüyor. Artı, gelen fon anlamına gelir. Eksi, fonların harcandığı anlamına gelir. Onaylanmış tutar ayrıca gösterilir. |
| Kontrol edilemedi | Gezgin yanıt vermedi veya CashPilot'un okuyamadığı veriler gönderdi. |
| Adres geçerli değil | Adres biçim kontrolünden geçemedi. CashPilot isteği atladı. |
| Gizli zincir | Bir Monero bakiyesini okumak için özel görüntüleme anahtarınız gerekir. Bakiyeyi cüzdanınızda kontrol edin. CashPilot bu anahtarı sizden hiçbir zaman istemez. |
| Bir tire | Bu satır için bir adres veya okuyucu yok ya da sorgu kapalı. Sorguyu bir ayar kapattığında, hangisi olduğunu görmek için imleci tirenin üzerine getirin. |

Kaspa'nın herkese açık uç noktası tek bir bakiye bildirir. Ayrı bir bekleyen
tutar sağlamaz.

Zincir üstü sütunu, adresteki bakiyeyi şu anki haliyle gösterir. Başka kaynaklardan
gelen transferleri de içerebilir. Havuzun ödenmemiş bakiyesi, havuzun sizin için hâlâ
tuttuğu tutarı gösterir. Lightning üzerinden yapılan bir OCEAN ödemesi zincir üstü
bakiyede görünmez. Bakiye ayrıca hangi transferlerin havuzunuzdan geldiğini söyleyemez.

## Sorgunun nereye gideceğini seçin { #choose-where-the-lookup-goes }

Her sorgu, herkese açık ödeme adresinizi ve arayüz sunucusunun IP'sini gezginle paylaşır.
Gezgin, aynı IP'den kontrol ettiğiniz adresleri birbirine bağlayabilir.

Kendi düğümünüzü çalıştırıyorsanız temel URL'yi arayüz konteynerinin ortamında ayarlayın.
Varsayılanı kullanmak için değişkeni ayarlamadan bırakın. O zincir için sorguyu kapatmak
için değişkeni boş bir değere ayarlayın.

Örneğin, arayüz hizmeti için bir Compose geçersiz kılma dosyası şunu içerebilir:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Bitcoin veya Kaspa'yı yapılandırırken Esplora veya Kaspa API temel URL'sini kullanın.
Bitcoin uç noktası, bir Bitcoin havuzunun [beklenen kazancı](fleet.md#running-costs)
için ağ zorluğunu ve blok ödüllerini de verir. Bu okuma bir mempool arka ucu
(onun `/v1/mining` API'si) gerektirir; yalın bir Esplora sunucusu yalnızca bakiye
sorgusunu yanıtlar ve havuzun satırı bu durumda beklenen bir tutar göstermez.
Ethereum, Polygon ve Solana için ilgili değişkenleri,
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` veya
`CASHPILOT_ONCHAIN_URL_SOLANA` değerini bir düğümün RPC URL'sine ayarlayın. Kimlik bilgisi,
sorgu dizesi veya parça içermeyen bir HTTP ya da HTTPS URL'si kullanın. Değişikliği,
arayüz konteynerini yeni ortamla yeniden oluşturarak uygulayın.
