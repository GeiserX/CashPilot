---
source_hash: 38029ca1a5d6
---
# टैक्स के लिए आय का export { #income-export-for-taxes }

**Payouts** (भुगतान) खोलें, **Income for taxes** (टैक्स के लिए आय) खोजें, और एक तारीख़ सीमा और मुद्रा चुनें। **This year** (इस साल) आज तक चलता है, और **Last year** (पिछले साल) पिछले कैलेंडर वर्ष को कवर करता है। आज तक का उपलब्ध इतिहास export करने के लिए तारीख़ें खाली छोड़ दें। CashPilot UTC तारीख़ें इस्तेमाल करता है और सीमा के दोनों सिरे शामिल करता है।

CashPilot कमाई की रीडिंग दर्ज होने के 400 दिन बाद हटा देता है। CSV बचे हुए इतिहास का इस्तेमाल करता है, इसलिए किसी पिछले वर्ष में उसकी अर्जित या उपार्जित आय का केवल एक हिस्सा हो सकता है।

## लेखा आधार चुनें { #choose-an-accounting-basis }

- **नकद आधार।** भुगतान वाली पंक्तियाँ इस्तेमाल करें। वे वह पैसा दर्ज करती हैं जो सेवा ने भुगतान किया। CashPilot केवल पुष्ट भुगतान शामिल करता है।
- **उपार्जन आधार।** अर्जित और उपार्जित पंक्तियाँ इस्तेमाल करें। अर्जित पंक्तियाँ वह क्रेडिट दिखाती हैं जिसकी आप सेवा की शर्तों पर निकासी कर सकते हैं। उपार्जित पंक्तियाँ pool का बिना भुगतान वाला क्रेडिट दिखाती हैं, जिसे pool शायद कभी न चुकाए।

एक ही आय के लिए एक ही आधार इस्तेमाल करें। अर्जित और उपार्जित पंक्तियों में भुगतान वाली पंक्तियाँ जोड़ने से एक ही पैसा दो बार गिना जा सकता है। जाँचें कि आपकी फ़ाइलिंग पर कौन-सा आधार लागू होता है।

## CSV कॉलम { #csv-columns }

| कॉलम | अर्थ |
|---|---|
| date | बाद वाली रीडिंग या भुगतान का UTC दिन। भुगतान आपकी डाली गई तारीख़ या वह दिन इस्तेमाल करता है जब CashPilot ने उसे पहचाना। |
| period_start | इस सेवा और स्रोत की पिछली रीडिंग का UTC दिन। भुगतान के लिए खाली। रीडिंग के बीच अंतर का मतलब है कि राशि पूरे अंतराल को कवर करती है। |
| kind | earned (अर्जित), accrued (उपार्जित) या payout (भुगतान)। |
| service | CashPilot सेवा ID। |
| coin | CashPilot के दर्ज किए अनुसार मुद्रा या टोकन कोड। |
| amount | उस मुद्रा या टोकन में राशि। |
| usd_rate | coin की हर इकाई के लिए अमेरिकी डॉलर की संख्या। |
| usd_value | अमेरिकी डॉलर में आँकी गई राशि। |
| local_currency | export के लिए आपकी चुनी गई fiat मुद्रा। |
| local_rate | हर अमेरिकी डॉलर के लिए आपकी चुनी गई मुद्रा की इकाइयाँ। |
| local_value | आपकी चुनी गई मुद्रा में आँकी गई राशि। |
| method | भुगतान का तरीका, अगर दर्ज हो। |

खाली मूल्यांकन का मतलब है कि दर उपलब्ध नहीं थी। मूल राशि फिर भी मौजूद रहती है। CashPilot कमाई की रीडिंग में Grass points जैसे आंतरिक points छोड़ देता है। हर स्रोत की पहली रीडिंग एक शुरुआती बैलेंस देती है। बाद की पंक्तियाँ बढ़ोतरी दर्ज करती हैं, इसलिए CSV चुनी गई सीमा की सबसे पुरानी रीडिंग के बाद शुरू हो सकता है।

अगर एक से ज़्यादा स्रोत एक ही खाता पढ़ते हैं, तो CSV उस आय को एक से ज़्यादा बार गिन सकता है।

USD दर बाद वाली रीडिंग से या भुगतान के रिकॉर्ड से आती है। जब CashPilot किसी रीडिंग की कीमत बाद में भरता है, तो वह उस दिन 00:00 UTC पर CoinGecko की कीमत इस्तेमाल करता है। USD को आपकी चुनी गई मुद्रा में बदलने के लिए CashPilot पंक्ति के दिन या उससे पहले की सबसे नई ECB संदर्भ दर इस्तेमाल करता है। इसमें सप्ताहांत, छुट्टियाँ और वे दिन आते हैं जब ECB ने अभी अपनी दर प्रकाशित नहीं की है। [Frankfurter की दैनिक दरें](https://frankfurter.dev/v1/)

Frankfurter export के लिए ये मुद्राएँ सूचीबद्ध करता है। [समर्थित मुद्राएँ](https://api.frankfurter.dev/v1/currencies)

- AUD, BRL, CAD, CHF, CNY, CZK, DKK, EUR, GBP, HKD, HUF, IDR, ILS, INR और ISK।
- JPY, KRW, MXN, MYR, NOK, NZD, PHP, PLN, RON, SEK, SGD, THB, TRY, USD और ZAR।

अगर आपकी मुद्रा उस सूची में नहीं है या Frankfurter उपलब्ध नहीं है, तो USD चुनें।

## किसी दूसरे टूल में import करें { #import-into-another-tool }

import करने से पहले CSV को टूल के फ़ॉर्मेट में बदलें। पहले अपने लेखा आधार की पंक्तियाँ चुनें। उस वॉलेट की भुगतान वाली पंक्तियाँ छोड़ दें जिसे टूल पहले से sync करता है।

### rotki { #rotki }

इन headers के साथ Generic Events इस्तेमाल करें।

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

Type को Income और Location को external पर सेट करें। जब ये प्रकार किसी घटना का वर्णन करते हों, तो rotki Deposit, Withdrawal, Loss, Spend और Staking भी स्वीकार करता है। coin को Currency से, amount को Amount से और service को Description से मिलाएँ। जहाँ rotki का asset identifier coin कोड से अलग हो, वहाँ उसे इस्तेमाल करें। date को मिलीसेकंड में UTC Unix timestamp में बदलें। दोनों fee फ़ील्ड खाली छोड़ दें। [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

Universal template के ज़रूरी कॉलम इस्तेमाल करें।

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

Date को UTC में YYYY-MM-DD HH:mm:ss फ़ॉर्मेट में लिखें। Received Amount को amount से और Received Currency को coin से सेट करें। दोनों Sent फ़ील्ड खाली छोड़ दें। ज्ञात मानों के लिए local_value और local_currency को वैकल्पिक Net Worth Amount और Net Worth Currency से मिलाएँ। जहाँ उचित हो, mining या reward के लिए Tag कॉलम इस्तेमाल करें। Description और TxHash वैकल्पिक हैं। [Koinly Universal template](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

अभी तक Koinly खाता नहीं है? आप यहाँ साइन अप कर सकते हैं: https://koinly.io/?via=FFF185D5। यह एक रेफ़रल लिंक है, और इससे आपको कोई ख़र्च नहीं होता।

### CoinTracking { #cointracking }

आय की पंक्तियों को CoinTracking के सामान्य CSV फ़ॉर्मेट में बदलें। Custom Importer को दोनों तरफ़ trade फ़ील्ड चाहिए, और आय की पंक्ति में केवल buy वाली तरफ़ होती है। [CoinTracking Custom Importer की ज़रूरतें](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

जैसा उचित हो, Type को Income या Mining पर सेट करें। amount को Buy Amount से, coin को Buy Currency से और service को Comment से मिलाएँ। Sell फ़ील्ड खाली छोड़ दें। Date को DD.MM.YYYY HH:MM:SS फ़ॉर्मेट में लिखें। export UTC दिन देता है, इसलिए समय के लिए 00:00:00 इस्तेमाल करें। अपने खाते की भाषा के type लेबल इस्तेमाल करें। [CoinTracking का सामान्य CSV फ़ॉर्मेट](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

अभी तक CoinTracking खाता नहीं है? यह साइन अप लिंक आपको हर paid plan पर 10% छूट देता है: https://cointracking.info?ref=G962413। यह एक रेफ़रल लिंक है। आप जो भुगतान करते हैं, उसका 20% CoinTracking CashPilot प्रोजेक्ट को देता है, और इससे आपको ज़्यादा ख़र्च नहीं होता।
