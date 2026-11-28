---
source_hash: 5a764f1d0f5a
---
# money4band'den geçiş { #moving-from-money4band }

CashPilot, money4band'in yapılandırmasını okuyabilir ve hizmet oturum bilgilerinizi
taşıyabilir, böylece onları yeniden yazmanız gerekmez. CashPilot kaydetmeden önce her şeyi
siz kontrol edersiniz.

## Başlamadan önce { #before-you-start }

CashPilot sahip hesabına ve money4band'in şu anda çalıştığı makinede ya da başka bir
makinede en az bir CashPilot worker'ına ihtiyacınız var.

Aynı hizmetleri bir makineye CashPilot'tan dağıtmadan önce o makinedeki money4band'i
durdurun. Tek bir bağlantının arkasındaki iki kopya tek bir kopya gibi kazanır ve aynı EarnApp
veya ProxyRack cihaz ID'si iki kez çalışmamalıdır. money4band'in menüsündeki **Stop apps stack**
seçeneğini kullanın
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))
ya da klasöründe `docker compose down` çalıştırın. Ek proxy örnekleri kurduysanız
her birini de durdurun.

## Hangi dosyayı kullanmalı { #which-file-to-use }

money4band klasörünüzdeki `config/user-config.json` dosyasını kullanın. Bu dosyayı
CashPilot'a nasıl ulaştıracağınız money4band sürümünüze bağlıdır.

money4band 4.x'te money4band bu dosyayı **Setup Apps** çalıştırdığınızda yazar ve dosya
tam olarak sizin yazdıklarınızı tutar. Yanındaki `.env` o dosyadan üretilir ve o da çalışır;
money4band 3.x'in elle düzenlenmiş `.env` dosyası da çalışır. İkisi de yalnızca diskinizde
kalır: money4band'in
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
dosyası onları listeler.

money4band 5.0, `config/user-config.json` dosyasını diskte şifreler
([güvenlik notları](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption))
ve her başlatmadan sonra `.env` dosyasını siler
([env oluşturucu](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
CashPilot şifrelenmiş dosyayı okuyamaz. money4band klasörünüzde `config edit`
komutunu çalıştırın. Yayımlanan ikili dosya için sisteminize uygun dosyayı kullanın, örneğin `./Money4Band-linux-amd64 config edit` ya da Windows'ta `.\Money4Band-windows-amd64.exe config edit`.
Kaynak koddan çalıştırıyorsanız `python run.py config edit` komutunu çalıştırın.
Bu komut money4band'i uv ile, uv yoksa bir pip ortamıyla çalıştırır ([run.py](https://github.com/MRColorR/money4band/blob/eebbdd410131e4b0fd4c9f9d49f84dc60e6a0e3d/run.py#L48-L69)).
`config edit` komutu, şifresi çözülmüş dosyayı düzenleyicinizde açar ([CLI başvurusu](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
Metnin tamamını kopyalayın, **Import from another tool** (Başka bir araçtan içe aktar) sayfasına yapıştırın, ardından düzenleyiciyi kapatın.

JSON dosyasını tercih edin. Bir `.env` içinde Docker Compose tırnaksız değerlerdeki `$` işaretini
genişletir, bu yüzden içinde `$` bulunan bir parola dosyada göründüğü gibi değildir. CashPilot
tahmin yürütmez: o değeri yeniden yazmanızı ister.

## Nasıl içe aktarılır { #how-to-import }

1. **Settings** (Ayarlar) sayfasını, ardından **Import from another tool** (Başka bir araçtan içe aktar) bölümünü açın (ya da `/import` adresine gidin).
2. `user-config.json` dosyasını ekleyin veya metnini yapıştırın. Aracı "Tell from the
   files" (Dosyalardan anla) seçeneğinde bırakın ya da money4band'i seçin.
3. Tabloyu kontrol edin. İstediğiniz hizmetleri işaretleyin ve eksik olarak işaretlenen
   değerleri doldurun.
4. **Save the ticked services** (İşaretli hizmetleri kaydet) düğmesine basın, ardından
   hizmetleri aynı sayfadan worker'larınıza dağıtın.

## Neler taşınır { #what-comes-over }

Alan adları money4band'in
[user-config şablonundan](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
ve `.env` adları da onun
[üretecinin](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
yazdığı adlardan gelir (`<APP>_<FLAG>`, örneğin `REPOCKET_APIKEY`). money4band 5.0
[uygulama katalogunda](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported)
aynı alan adlarını korur.

| money4band uygulaması | CashPilot hizmeti | Neler taşınır |
|---|---|---|
| `earnapp` | EarnApp | cihaz ID'si (`uuid`), böylece bağlı cihazınız kazanmaya devam eder |
| `honeygain` | Honeygain | e-posta, parola |
| `iproyalpawns` | IPRoyal Pawns | e-posta, parola |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | belirteç |
| `repocket` | Repocket | e-posta, API anahtarı |
| `earnfm` | Earn.fm | API anahtarı |
| `proxyrack` | ProxyRack | API anahtarı, cihaz UUID'si |
| `proxylite` | ProxyLite | kullanıcı ID'si |
| `bitping` | Bitping | e-posta, parola |
| `mystnode` | Mysterium | açılır; aşağıdaki Mysterium notuna bakın |

money4band'de kapattığınız bir uygulama işaretsiz görünür. Kapalı olan ve şablonun yer
tutucuları (`yourHONEYGAINMail`) ile port listelerinden başka bir şey içermeyen bir uygulama
dışarıda bırakılır, bu yüzden hiç dokunulmamış bir `user-config.json` boş bir tablo verir.

Şu uygulamalar listelenir ama taşınmaz:

| money4band uygulaması | Neden |
|---|---|
| `proxybase` | money4band, ProxyBase'in eski istemcisini bir kullanıcı ID'siyle çalıştırır. CashPilot ise proxybase.org'dan alınan Access Token gerektiren güncel istemciyi çalıştırır. |
| `urnetwork` | money4band bir oturum belirteci tutar. CashPilot, URnetwork'te e-postanız ve parolanızla oturum açar. |
| `grass` | Grass bir tarayıcı eklentisi olarak çalışır. CashPilot onu yalnızca Grass panosundaki erişim belirteciyle izler. |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot bunları izler, ancak dağıtılacak bir konteyner yoktur. |
| `packetshare`, `peer2profit`, `speedshare` | Artık mevcut değil. |

Diğer tüm uygulamalar "CashPilot has no such service" (CashPilot'ta böyle bir hizmet yok) olarak listelenir.

## Hiçbir zaman taşınmayanlar { #what-never-comes-over }

- **Cihaz adı.** CashPilot her cihazı çalıştığı worker'ın adıyla adlandırır, böylece iki
  worker hiçbir zaman aynı adı bildirmez. Eski cihazlarınız, siz onları her sağlayıcının
  panosundan kaldırana kadar orada çevrimdışı olarak listelenmeye devam eder.
- **Proxy'ler.** Her birini **Fleet** (Filo) sayfasının **Proxies** (Proxy'ler) bölümünde ekleyin, ardından
  hizmetlerinizin kopyalarını onun üzerinden çalıştırın; bir proxy eklemek tek başına hiçbir şeyi başlatmaz.
  Bir içe aktarmayı kaydetmek de hiçbir şeyi başlatmaz. Bir proxy kopyası, önce aynı hizmetin
  worker'da dağıtılmış olmasını gerektirir ve onu dağıtmak hizmeti worker'ın kendi bağlantısında
  çalıştırır; bu yüzden o bağlantıyı asla kullanmaması gereken bir hizmet işaretsiz kalmalıdır.
  Bkz. [Proxy kopyaları](../proxies.md).
- **Watchtower ve bildirimler.** CashPilot kendi konteynerlerini günceller.
- **money4band'in panosu ve portları.**

## Kazanç takibi { #earnings-tracking }

Honeygain, IPRoyal Pawns ve Bitping için konteyner oturum bilgileri aynı zamanda hesap
oturum bilgileridir, bu yüzden CashPilot, siz onları **Settings** (Ayarlar) içinde zaten ayarlamadıysanız,
bunların kazanç kimlik bilgilerini de doldurur. Diğer tüm hizmetler için kazanç oturum bilgilerini
**Settings > Earnings collection** (Ayarlar > Kazanç toplama) içinde ekleyin.

## Mysterium { #mysterium }

İçe aktarma Mysterium'u açar, ancak CashPilot yeni bir kimlikle yeni bir düğüm başlatır.
Eski düğümün anahtar deposu ve ödenmemiş kazançları money4band'in
`.data/mysterium-node` klasöründe kalır
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). Önce onları tahsil edin ya da kimliği taşımak için
[Mysterium rehberini](../guides/mysterium.md) izleyin.

Bir 3.x `.env` dosyası Mysterium'u çalıştırıp çalıştırmadığınızı söyleyemez: şablonu her zaman
pano portunu listeler. 3.x dosyasından Mysterium içe aktarılmaz, bu yüzden çalıştırdıysanız
onu katalogdan ekleyin.

## Güvenlik { #safety }

- Dosyadaki hiçbir şey çalıştırılmaz veya genişletilmez ve içindeki hiçbir adres çekilmez.
- Dosya bir kez okunur ve saklanmaz. Kaydettikleriniz, CashPilot'taki diğer tüm kimlik
  bilgileri gibi şifrelenmiş olarak saklanır.
- Gizli değerler sayfada yalnızca "set" (ayarlı) olarak gösterilir.
- Kaydedilen içe aktarmalar siz **Forget** (Unut) düğmesine basana kadar içe aktarma sayfasında
  kalır, böylece onları daha sonra başka worker'lara da dağıtabilirsiniz.
