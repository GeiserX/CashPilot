---
source_hash: 38029ca1a5d6
---
# Vergi için gelir dışa aktarımı { #income-export-for-taxes }

**Payouts** (Ödemeler) sayfasını açın, **Income for taxes** (Vergi için gelir) bölümünü bulun ve bir tarih aralığı ile para birimi seçin. **This year** (Bu yıl) bugüne kadar uzanır, **Last year** (Geçen yıl) ise önceki takvim yılını kapsar. Mevcut geçmişi bugüne kadar dışa aktarmak için tarihleri boş bırakın. CashPilot UTC tarihleri kullanır ve aralığın iki ucunu da dahil eder.

CashPilot kazanç okumalarını kaydettikten 400 gün sonra siler. CSV kalan geçmişi kullanır, bu yüzden geçmiş bir yıl, kazanılmış veya tahakkuk etmiş gelirinin yalnızca bir kısmını içerebilir.

## Bir muhasebe esası seçin { #choose-an-accounting-basis }

- **Nakit esası.** Ödeme satırlarını kullanın. Bu satırlar hizmetin ödediği parayı kaydeder. CashPilot yalnızca onaylanmış ödemeleri dahil eder.
- **Tahakkuk esası.** Kazanılmış (earned) ve tahakkuk etmiş (accrued) satırları kullanın. Kazanılmış satırlar, hizmetin koşullarına göre çekebileceğiniz alacağı gösterir. Tahakkuk etmiş satırlar, havuzun hiçbir zaman ödemeyebileceği ödenmemiş havuz alacağını gösterir.

Aynı gelir için tek bir esas kullanın. Ödeme satırlarını kazanılmış ve tahakkuk etmiş satırlara eklemek aynı parayı iki kez sayabilir. Beyannamenize hangi esasın uygulandığını kontrol edin.

## CSV sütunları { #csv-columns }

| Sütun | Anlamı |
|---|---|
| date | Sonraki okumanın veya ödemenin UTC günü. Bir ödeme, girdiğiniz tarihi veya CashPilot'un onu algıladığı günü kullanır. |
| period_start | Bu hizmet ve kaynak için önceki okumanın UTC günü. Ödemelerde boştur. Okumalar arasındaki bir boşluk, tutarın aralığın tamamını kapsadığı anlamına gelir. |
| kind | earned (kazanılmış), accrued (tahakkuk etmiş) veya payout (ödeme). |
| service | CashPilot hizmet kimliği. |
| coin | CashPilot'un kaydettiği para birimi veya token kodu. |
| amount | O para birimi veya token cinsinden tutar. |
| usd_rate | Bir birim coin başına ABD doları sayısı. |
| usd_value | ABD doları cinsinden değerlenmiş tutar. |
| local_currency | Dışa aktarım için seçtiğiniz itibari para birimi. |
| local_rate | Bir ABD doları başına seçtiğiniz para biriminin birim sayısı. |
| local_value | Seçtiğiniz para birimi cinsinden değerlenmiş tutar. |
| method | Kaydedildiyse ödeme yöntemi. |

Boş bir değerleme, kurun mevcut olmadığı anlamına gelir. Yerel tutar yine de vardır. CashPilot, kazanç okumalarındaki Grass puanları gibi dahili puanları atlar. Kaynak başına ilk okuma bir açılış bakiyesi sağlar. Sonraki satırlar artışları kaydeder, bu yüzden CSV seçilen aralıktaki en eski okumadan sonra başlayabilir.

Aynı hesabı birden fazla kaynak okuyorsa CSV o geliri birden fazla kez sayabilir.

USD kuru, sonraki okumadan veya ödeme kaydından gelir. CashPilot bir okumanın fiyatını sonradan doldurduğunda, CoinGecko'nun o gün için 00:00 UTC'deki fiyatını kullanır. CashPilot, USD'yi seçtiğiniz para birimine dönüştürmek için satırın gününde veya ondan önceki en son ECB referans kurunu kullanır. Bu, hafta sonlarını, tatilleri ve ECB'nin kurunu henüz yayımlamadığı günleri kapsar. [Frankfurter günlük kurları](https://frankfurter.dev/v1/)

Frankfurter, dışa aktarım için şu para birimlerini listeler. [Desteklenen para birimleri](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR ve ISK.
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD ve ZAR.

Para biriminiz bu listenin dışındaysa veya Frankfurter kullanılamıyorsa USD'yi seçin.

## Başka bir araca aktarma { #import-into-another-tool }

İçe aktarmadan önce CSV'yi aracın biçimine dönüştürün. Önce muhasebe esasınıza uygun satırları seçin. Aracın zaten senkronize ettiği bir cüzdanın ödeme satırlarını atlayın.

### rotki { #rotki }

Generic Events'i şu başlıklarla kullanın.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Type'ı Income'a, Location'ı external'a ayarlayın. rotki, bir olayı tanımladıklarında Deposit, Withdrawal, Loss, Spend ve Staking türlerini de kabul eder. coin'i Currency'ye, amount'u Amount'a ve service'i Description'a eşleyin. rotki'nin varlık tanımlayıcısı coin kodundan farklıysa onu kullanın. date'i milisaniye cinsinden bir UTC Unix zaman damgasına dönüştürün. İki ücret alanını da boş bırakın. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Universal şablonunun zorunlu sütunlarını kullanın.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Date'i UTC'de YYYY-MM-DD HH:mm:ss biçiminde yazın. Received Amount'u amount'tan, Received Currency'yi coin'den ayarlayın. İki Sent alanını da boş bırakın. Bilinen değerler için local_value ve local_currency'yi isteğe bağlı Net Worth Amount ve Net Worth Currency sütunlarına eşleyin. Uygun olduğunda mining veya reward için Tag sütununu kullanın. Description ve TxHash isteğe bağlıdır. [Koinly Universal şablonu](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

Henüz Koinly hesabınız yok mu? Buradan kaydolabilirsiniz: https://koinly.io/?via=FFF185D5. Bu bir referans bağlantısıdır ve size hiçbir maliyeti yoktur.

### CoinTracking { #cointracking }

Gelir satırlarını CoinTracking'in normal CSV biçimine dönüştürün. Custom Importer her iki tarafta da işlem alanları ister, oysa bir gelir satırının yalnızca alış tarafı vardır. [CoinTracking Custom Importer gereksinimleri](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

Type'ı uygun olduğu şekilde Income veya Mining olarak ayarlayın. amount'u Buy Amount'a, coin'i Buy Currency'ye ve service'i Comment'e eşleyin. Sell alanlarını boş bırakın. Date'i DD.MM.YYYY HH:MM:SS biçiminde yazın. Dışa aktarım UTC gününü verir, bu yüzden saat için 00:00:00 kullanın. Hesabınızın dilindeki tür etiketlerini kullanın. [CoinTracking normal CSV biçimi](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

Henüz CoinTracking hesabınız yok mu? Bu kayıt bağlantısı size her ücretli planda %10 indirim sağlar: https://cointracking.info?ref=G962413. Bu bir referans bağlantısıdır. CoinTracking, ödediğiniz tutarın %20'sini CashPilot projesine öder ve bu size daha fazlasına mal olmaz.
