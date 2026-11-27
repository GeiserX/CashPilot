---
source_hash: 7f8476aeb8b6
---
# CashFactory'den geçiş { #moving-from-cashfactory }

CashPilot, CashFactory'nin `.env` dosyasını okuyabilir ve hizmet oturum bilgilerinizi taşıyabilir,
böylece onları yeniden yazmanız gerekmez. CashPilot kaydetmeden önce her şeyi siz kontrol edersiniz.

## Başlamadan önce { #before-you-start }

CashPilot sahip hesabına ve en az bir CashPilot worker'ına ihtiyacınız var.

Aynı hizmetleri bir makineye CashPilot'tan dağıtmadan önce o makinedeki CashFactory'yi
durdurun. Tek bir bağlantının arkasındaki iki kopya tek bir kopya gibi kazanır ve aynı EarnApp
cihaz ID'si iki kez çalışmamalıdır. CashFactory klasöründe `docker compose down` çalıştırın.
CashFactory'nin
[compose dosyası](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
Docker soketini bağlayan üç konteyner daha başlatır: Portainer (31. satır)
ve iki Watchtower konteyneri (141. ve 264. satırlar). Bunların da kaldırıldığından emin olun: `docker ps`
hiçbirini listelememelidir.

## Hangi dosyayı kullanmalı { #which-file-to-use }

CashFactory klasörünüzdeki `.env` dosyasını, yani
[örnekten](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env) doldurduğunuz dosyayı kullanın.

Docker Compose bu dosyayı okur ve tek tırnak içinde olmayan değerlerdeki `$` işaretini genişletir.
Böyle bir değer dosyada göründüğü gibi değildir, bu yüzden CashPilot tahmin yürütmek yerine
onu yeniden yazmanızı ister.

## Nasıl içe aktarılır { #how-to-import }

1. **Settings** (Ayarlar) sayfasını, ardından **Import from another tool** (Başka bir araçtan içe aktar) bölümünü açın (ya da `/import` adresine gidin).
2. `.env` dosyasını ekleyin veya metnini yapıştırın. Aracı "Tell from the
   files" (Dosyalardan anla) seçeneğinde bırakın ya da CashFactory'yi seçin.
3. Tabloyu kontrol edin. İstediğiniz hizmetleri işaretleyin ve eksik olarak işaretlenen
   değerleri doldurun.
4. **Save the ticked services** (İşaretli hizmetleri kaydet) düğmesine basın, ardından
   hizmetleri aynı sayfadan worker'larınıza dağıtın.

## Neler taşınır { #what-comes-over }

| CashFactory uygulaması | Okunan anahtarlar | CashPilot hizmeti | Neler taşınır |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | cihaz ID'si, böylece bağlı cihazınız kazanmaya devam eder |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | e-posta, parola |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | e-posta, parola |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | belirteç |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | e-posta, API anahtarı |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | kullanıcı ID'si |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | cihaz UUID'si |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API anahtarı |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | hiçbir şey: artık mevcut değil |

Hâlâ örneğin yer tutucusunu (`<email>`, `sdk-node-<md5sum>`) gösteren bir değer ayarlanmamış
sayılır ve yer tutuculardan başka bir şeyi olmayan bir hizmet tablonun dışında bırakılır.

## Hiçbir zaman taşınmayanlar { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot her cihazı çalıştığı worker'ın adıyla adlandırır, böylece iki
  worker hiçbir zaman aynı adı bildirmez. Eski cihazlarınız, siz onları her sağlayıcının
  panosundan kaldırana kadar orada çevrimdışı olarak listelenmeye devam eder.
- **Bitping.** CashFactory, Bitping oturum bilgilerini `.env` içinde değil, bir Docker biriminde
  tutar; bu yüzden içe aktarmanın okuyacak bir şeyi yoktur ve Bitping satırı göstermez. Oturum
  bilgilerini Bitping'in dağıtım formuna yazın.
- **Portainer ve Watchtower.** CashPilot kendi konteynerlerini yönetir ve günceller.

## Kazanç takibi { #earnings-tracking }

Honeygain ve IPRoyal Pawns için konteyner oturum bilgileri aynı zamanda hesap oturum bilgileridir,
bu yüzden CashPilot, siz onları **Settings** (Ayarlar) içinde zaten ayarlamadıysanız, bunların kazanç
kimlik bilgilerini de doldurur. Diğer tüm hizmetler için kazanç oturum bilgilerini
**Settings > Earnings collection** (Ayarlar > Kazanç toplama) içinde ekleyin.

## Güvenlik { #safety }

- Dosyadaki hiçbir şey çalıştırılmaz veya genişletilmez ve içindeki hiçbir adres çekilmez.
- Dosya bir kez okunur ve saklanmaz. Kaydettikleriniz, CashPilot'taki diğer tüm kimlik
  bilgileri gibi şifrelenmiş olarak saklanır.
- Gizli değerler sayfada yalnızca "set" (ayarlı) olarak gösterilir.
- Kaydedilen içe aktarmalar siz **Forget** (Unut) düğmesine basana kadar içe aktarma sayfasında
  kalır, böylece onları daha sonra başka worker'lara da dağıtabilirsiniz.
