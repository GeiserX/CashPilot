---
source_hash: ca9dd25d45ca
---
# InternetIncome'dan geçiş { #moving-from-internetincome }

CashPilot, InternetIncome'un `properties.conf` dosyasını ve EarnApp ile ProxyRack cihaz
ID'lerinizi tuttuğu dosyaları okuyabilir ve bunları taşıyabilir. CashPilot kaydetmeden önce
her şeyi siz kontrol edersiniz.

## Başlamadan önce { #before-you-start }

CashPilot sahip hesabına ve en az bir CashPilot worker'ına ihtiyacınız var.

Aynı hizmetleri bir makineye CashPilot'tan dağıtmadan önce o makinedeki InternetIncome'u
durdurun. Tek bir bağlantının arkasındaki iki kopya tek bir kopya gibi kazanır ve aynı cihaz ID'si
iki kez çalışmamalıdır. InternetIncome klasöründe şunu çalıştırın:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` konteynerleri kaldırır ve `earnapp.txt`, `proxyrack.txt` dosyalarını ve
Mysterium veri klasörünü korur. `--deleteBackup` bunları da kaldırır
([internetIncome.sh, 61 ile 64. satırlar](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
ve [1562. satır](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
bu yüzden önce içe aktarın.

## Hangi dosyaları kullanmalı { #which-files-to-use }

InternetIncome klasöründen:

- `properties.conf`, ayarlarınız.
- `earnapp.txt`, EarnApp çalıştırdıysanız. Her satır bir cihaz bağlantısı tutar
  ([1250 ile 1261. satırlar](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`, ProxyRack çalıştırdıysanız. Satır başına bir cihaz UUID'si
  ([817 ile 827. satırlar](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

CashPilot her dosyadaki ilk cihazı alır: ana konteynerinizin kullandığı ve hesabınıza bağladığınız
cihaz. Diğer satırlar proxy kopyalarına aitti ve sayfa kaç tanesini dışarıda bıraktığını size söyler.

InternetIncome her değeri kabuktan geçirir
([1375. satır](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
Tek tırnak içindeki bir değer,
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
içindeki yorumların önerdiği gibi, yazıldığı haliyle alınır. Tek tırnak dışında olup `$`, ters tırnak,
boşluk veya kabuğun değiştireceği başka bir karakter içeren bir değer dosyada göründüğü gibi
değildir; bu yüzden CashPilot bunu anlamak için bir kabuk çalıştırmak yerine onu yeniden yazmanızı ister.

## Nasıl içe aktarılır { #how-to-import }

1. **Settings** (Ayarlar) sayfasını, ardından **Import from another tool** (Başka bir araçtan içe aktar) bölümünü açın (ya da `/import` adresine gidin).
2. `properties.conf` dosyasını, varsa `earnapp.txt` ve `proxyrack.txt` dosyalarıyla birlikte
   ekleyin. Aracı "Tell from the files" (Dosyalardan anla) seçeneğinde bırakın ya da InternetIncome'u seçin.
3. Tabloyu kontrol edin. İstediğiniz hizmetleri işaretleyin ve eksik olarak işaretlenen
   değerleri doldurun. Repocket, InternetIncome'un hiç sormadığı hesap e-postanızı gerektirir.
4. **Save the ticked services** (İşaretli hizmetleri kaydet) düğmesine basın, ardından
   hizmetleri aynı sayfadan worker'larınıza dağıtın.

## Neler taşınır { #what-comes-over }

| InternetIncome uygulaması | Okunan anahtarlar | CashPilot hizmeti | Neler taşınır |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API anahtarı (e-postanızı ekleyin) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | belirteç |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API anahtarı, cihaz UUID'si |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | e-posta, parola |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | e-posta, parola |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | kullanıcı ID'si |
| `earnfm` | `EARN_FM_API` | Earn.fm | API anahtarı |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | cihaz ID'si |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | e-posta, parola |
| `mysterium` | `MYSTERIUM=true` | Mysterium | açılır; aşağıdaki Mysterium notuna bakın |

Boş bir değer uygulamanın kapalı olduğu anlamına gelir ve uygulama listelenmez.

Şu uygulamalar listelenir ama taşınmaz:

| InternetIncome uygulaması | Neden |
|---|---|
| `urnetwork` | InternetIncome bir oturum belirteci kullanır. CashPilot, URnetwork'te e-postanız ve parolanızla oturum açar. |
| `grass` | Grass bir tarayıcı eklentisi olarak çalışır. CashPilot onu yalnızca Grass panosundaki erişim belirteciyle izler. |
| `titan`, `ebesucher`, `wipter` | CashPilot bunları izler, ancak dağıtılacak bir konteyner yoktur. |
| `peer2profit` | Artık mevcut değil. |

CashPilot'ta olmayan uygulamaların (antGain, Adnade ve diğerleri) ayarları adlarıyla,
okunmadı olarak listelenir.

## Hiçbir zaman taşınmayanlar { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot her cihazı çalıştığı worker'ın adıyla adlandırır, böylece iki
  worker hiçbir zaman aynı adı bildirmez. Eski cihazlarınız, siz onları her sağlayıcının
  panosundan kaldırana kadar orada çevrimdışı olarak listelenmeye devam eder.
- **Proxy'ler** (`USE_PROXIES`, `proxies.txt`). Her birini **Fleet** (Filo) sayfasının **Proxies** (Proxy'ler)
  bölümünde ekleyin, ardından hizmetlerinizin kopyalarını onun üzerinden çalıştırın; bir proxy
  eklemek tek başına hiçbir şeyi başlatmaz. `USE_PROXIES=true` ile InternetIncome hizmetlerinizi
  yalnızca proxy'ler üzerinden çalıştırıyordu. Bir içe aktarmayı kaydetmek de hiçbir şeyi başlatmaz.
  Bir proxy kopyası, önce aynı hizmetin worker'da dağıtılmış olmasını gerektirir ve onu dağıtmak
  hizmeti worker'ın kendi bağlantısında çalıştırır; bu yüzden o bağlantıyı asla kullanmaması
  gereken bir hizmet işaretsiz kalmalıdır. Bkz. [Proxy
  kopyaları](../proxies.md).
- **`BROWSER_USERNAME` ve `BROWSER_PASSWORD`**, InternetIncome'un kendi tarayıcı
  oturum bilgileri.

## Kazanç takibi { #earnings-tracking }

Honeygain, IPRoyal Pawns ve Bitping için konteyner oturum bilgileri aynı zamanda hesap
oturum bilgileridir, bu yüzden CashPilot, siz onları **Settings** (Ayarlar) içinde zaten ayarlamadıysanız,
bunların kazanç kimlik bilgilerini de doldurur. Diğer tüm hizmetler için kazanç oturum bilgilerini
**Settings > Earnings collection** (Ayarlar > Kazanç toplama) içinde ekleyin.

## Mysterium { #mysterium }

İçe aktarma Mysterium'u açar, ancak CashPilot yeni bir kimlikle yeni bir düğüm başlatır.
Eski düğümün anahtar deposu ve ödenmemiş kazançları InternetIncome'un `mysterium-data`
klasöründe kalır. Önce onları tahsil edin ya da kimliği taşımak için
[Mysterium rehberini](../guides/mysterium.md) izleyin.

## Güvenlik { #safety }

- Dosyalardaki hiçbir şey çalıştırılmaz veya genişletilmez ve içlerindeki hiçbir adres çekilmez.
- Dosyalar bir kez okunur ve saklanmaz. Kaydettikleriniz, CashPilot'taki diğer tüm kimlik
  bilgileri gibi şifrelenmiş olarak saklanır.
- Gizli değerler sayfada yalnızca "set" (ayarlı) olarak gösterilir.
- Kaydedilen içe aktarmalar siz **Forget** (Unut) düğmesine basana kadar içe aktarma sayfasında
  kalır, böylece onları daha sonra başka worker'lara da dağıtabilirsiniz.
