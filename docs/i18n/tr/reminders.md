---
source_hash: b4ae1a3ae496
---
# Bekleyen para: kazancınızı kaybetmeden önce hatırlatmalar { #money-waiting-reminders-before-you-lose-earnings }

Bazı sağlayıcılar çok uzun süre bekleyen parayı geri alır. Bir bakiyenin süresi aylarca
etkinlik olmadığında dolabilir. Bir talep penceresi kapanabilir. Bir sağlayıcı, bakiyeniz
hâlâ oradayken bir hesabı yasaklayabilir, ödemeyi durdurabilir veya kapanabilir.
CashPilot, bunları önceden görmek için gerekenlerin çoğunu zaten okur. Panodaki
**Money waiting** (Bekleyen para) paneli ne yapmanız gerektiğini ve son tarihi gösterir;
bildirim kanallarınız da her son tarihten önce bir anlık bildirim alır.

CashPilot sizin adınıza hiçbir zaman talep veya para çekme işlemi yapmaz. Her hatırlatma
sağlayıcının kendi sayfasına bağlantı verir ve işlemi orada siz yaparsınız.

## Neleri hatırlatır { #what-it-reminds-you-about }

**Sağlayıcının kendi koşullarından gelen kurallar.** Her kural, sağlayıcının koşullarını
veya yardım sayfasını ve birinin onu en son okuduğu tarihi belirtir. Satırın **More** (Daha fazla)
menüsündeki **Source** (Kaynak) bağlantısı o sayfayı açar.

| Hizmet | Hatırlatma | Ne zaman |
|---|---|---|
| Grass | Stage 2 USDC'nizi talep edin | 22 Ocak 2027'ye kadar. Grass, talep edilmeyeni kendine alır. |
| MystNodes | Geçen ayın ödüllerini talep edin | Her aylık dağıtımdan sonraki 30 gün içinde |
| Honeygain | Bakiyenizi çekin | Bakiye ilk kez $20'a ulaştıktan 24 ay sonra |
| Honeygain | Bir cihazı paylaşımda tutun veya bir ödeme alın | Son etkinlikten veya ödemeden 6 ay sonra |
| Repocket | Bir cihazı paylaşımda tutun veya para çekin | Son etkinlikten veya ödemeden 12 ay sonra |
| Bitping | Bakiyenizi çekin | Son para çekme işleminden 12 ay sonra |
| Salad | Biraz Reward Points kazanın veya bakiyenizi harcayın | Bakiyenin en son arttığı tarihten 12 ay sonra. Bir kısmını harcamak bu süreyi sıfırlamaz. |

**Para çekme.** CashPilot, bir bakiye sağlayıcının minimum ödeme tutarına ulaştığında size
haber verir. Bu, kendiliğinden ödeme yapan hizmetler dışında, CashPilot'un kazanç topladığı her
hizmet için geçerlidir. Bakiyenin ayrıca en az $5 değerinde olması gerekir; böylece minimumu
5 sent olan bir sağlayıcı ilk sentte sizi rahatsız etmez. Sağlayıcının minimumu daha yüksekse
sağlayıcının minimumu geçerlidir. CashPilot minimumu veya bakiyeyi dönüştüremediğinde hiçbir şey
göstermez. Para çekebileceğinizi asla tahmin etmez.

**Kimlik bilgisinin süresinin dolması.** Kaydedilmiş bir belirtecin veya çerezin süresi dolmadan
önce bir anlık bildirim alırsınız. CashPilot, kimlik bilgisinin kendisinin belirttiği son kullanma
tarihini kullanır. Kimlik bilgisi bir tarih belirtmiyorsa CashPilot, o tür kimlik bilgisinin olağan
ömrünü kaydettiğiniz günden itibaren sayar. Sahipler bunu zaten **Needs attention** (Dikkat gerekiyor)
altında bir **Renew** (Yenile) düğmesiyle görür, bu yüzden panel bunu tekrarlamaz. API'den kimlik
bilgisi hatırlatmalarını yalnızca sahipler alır; kimlik bilgisi sağlık kontrolünde olduğu gibi.
Sağlayıcının reddettiği bir kimlik bilgisi zaten zil simgesindedir ve bildirimi zaten gönderilmiştir,
bu yüzden yeniden bildirim gönderilmez.

## Hangi hizmetleri kapsar { #which-services-it-covers }

Hatırlatma, kullandığınız bir hizmet için geçerlidir: dağıtılmış bir hizmet, **Settings** (Ayarlar)
içinde harici olarak ayarladığınız bir hizmet veya bir telefonun bildirdiği bir uygulama. Kaldırdığınız
bir hizmet, bakiyesi olduğu sürece sayılmaya devam eder, çünkü etkinliksizlik sayaçları hizmet
durduğunda başlar. Özel hizmetler ve sonlandırılmış hizmetler hatırlatma almaz.

## Tarihler ve "veya daha erken" { #dates-and-or-earlier }

Etkinlik sayaçları CashPilot'un kaydettiği şeylerden saymaya başlar:

- bakiyenin en son arttığı zaman,
- son ödeme,
- ya da minimuma eşit veya minimumun üzerindeki ilk okuma.

Bazen sayaç CashPilot'un ilk okumasından önce başlamıştır. Bu durumda gerçek son tarih
CashPilot'un görebildiğinden daha erken olabilir ve satırda
"3 Eki 2027'ye kadar veya daha erken" yazar.

CashPilot kazanç geçmişini 400 gün sonra siler, Honeygain sayacı ise 730 gün işler.
Bu yüzden CashPilot her sayacın başlangıcını ilk gördüğünde saklar ve arkasındaki geçmiş
silindikten sonra da tutar. Bir ödeme sayacı sıfırlar; sağlayıcının yalnızca kazancı saydığı
durumlar hariç. Salad bunlardan biridir: bakiye bırakan bir ödeme 12 aylık süresini sıfırlamaz.

Sabit bir tarih, geçtiği günün ertesi günü listeden düşer, çünkü para gitmiştir.
Süresi geçmiş bir sayaç listede kalır ve sağlayıcının parayı zaten silmiş olabileceğini söyler.
Siz onu tamamlandı olarak işaretleyene veya sessize alana ya da bir ödeme onu sıfırlayana
kadar kalır.

## Bir hatırlatmayla neler yapabilirsiniz { #what-you-can-do-with-a-reminder }

Düğmeleri sahipler ve düzenleyiciler görür. Görüntüleyiciler yalnızca hatırlatmaları görür.
Bir kimlik bilgisi hatırlatması üzerinde yalnızca sahipler işlem yapabilir.

- **Done** (Tamamlandı) ya da para çekme için **Requested** (İstendi) bu hatırlatmayı gizler.
  Aylık bir pencere sonraki ay geri gelir. Bir para çekme hatırlatması, bakiye hâlâ oradaysa
  14 gün sonra bir kez geri gelir ve ödemenin gelip gelmediğini sorar. Bu, çoğu sağlayıcının
  tanıdığı 60 günlük itiraz süresinin içindedir.
- **Snooze** (Ertele) hatırlatmayı bir gün veya bir hafta gizler ve anlık bildirimlerini bekletir.
  Erteleme hiçbir zaman bir son tarihten önceki son uyarının ötesine geçmez.
- **More** (Daha fazla) menüsündeki **Not for me** (Bana göre değil) tek bir hatırlatmayı ya da bir
  hizmetin tüm hatırlatmalarını sessize alır. Bir örnek: düz bir bakiyenin normal olduğu JumpTask
  modundaki Honeygain. Sessize alınan hatırlatmalar panelin altında **Unmute** (Sesi aç)
  düğmesiyle listelenir.

Hane halkı bu seçimleri paylaşır. Bir kişi bir hatırlatmayı tamamlandı olarak işaretlediğinde,
herkes için tamamlanmış olur. Her seçim, onu yapan kişinin adıyla denetim günlüğüne kaydedilir.

## Anlık bildirimler { #pushes }

Hatırlatmalar, uyarılar için ayarladığınız kanallara gider: ntfy, bir webhook veya Telegram
([yapılandırma](configuration.md)). Hiçbir kanal ayarlı değilse hatırlatmalar yalnızca panelde
görünür.

- Her uyarı için bir anlık bildirim. Örneğin Grass, tarihinden 60, 30, 7 ve 1 gün önce bildirim
  gönderir. Tarihinden 5 gün önce ilk kez görülen bir hatırlatma, 5 gün kala bir kez bildirim
  gönderir.
- Anlık bildirimler yalnızca 09:00 ile 21:00 arasında gönderilir. CashPilot, **Settings** (Ayarlar)
  içindeki ilk sahibin saat dilimini, sonra konteynerin `TZ` değerini, sonra UTC'yi kullanır.
  Gece ulaşılan bir uyarı, 09:00'dan sonraki ilk kontrolde gönderilir.
- Aynı anda 3'ten fazla anlık bildirim gerektiğinde bunun yerine tek bir özet alırsınız. Bu,
  minimumunun üzerindeki her bakiyenin birlikte ortaya çıktığı yükseltme gününde olur.
- Bir anlık bildirim hizmeti, ne yapılacağını, neyi kaybedeceğinizi, tarihi ve sağlayıcının
  bağlantısını taşır. Hiçbir zaman bir bakiye, bir adres, bir cihaz ID'si veya bir worker adı
  taşımaz. ntfy konuları herkese açık olabilir.
- Webhook yükleri `kind: "obligation"` taşır, böylece Home Assistant ve benzeri araçlar
  onları yönlendirebilir.

## Katalog katkıcıları için { #for-catalog-contributors }

Kurallar her hizmetin YAML dosyasında, `obligations:` altında bulunur.
`services/_schema.yml` alanları belgeler. Bir kuralı yalnızca sağlayıcının kendi koşulları
veya belgeleri onu belirtiyorsa ve CashPilot kuralın dayandığı sinyali görebiliyorsa ekleyin.
Bir kuralın bağlantısı hizmetin kendi alan adında olmalıdır, çünkü tam da bu hizmetler için
sahte talep siteleri vardır. CI, geçersiz bir kuralda ve tarihi 30 günden fazla geçmiş tarihli
bir kuralda başarısız olur.
