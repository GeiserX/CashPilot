---
source_hash: ca9dd25d45ca
---
# InternetIncome से आना { #moving-from-internetincome }

CashPilot InternetIncome की `properties.conf` पढ़ सकता है, और वे फ़ाइलें भी जिनमें यह
आपके EarnApp और ProxyRack डिवाइस id रखता है, और उन्हें ले आ सकता है। CashPilot के सहेजने से पहले
आप सब कुछ जाँचते हैं।

## शुरू करने से पहले { #before-you-start }

आपको CashPilot का स्वामी खाता और कम से कम एक CashPilot वर्कर चाहिए।

किसी मशीन पर CashPilot से वही सेवाएँ डिप्लॉय करने से पहले वहाँ InternetIncome बंद करें।
एक ही कनेक्शन के पीछे की दो कॉपियाँ एक जितना ही कमाती हैं, और एक ही डिवाइस id
दो बार नहीं चलनी चाहिए। InternetIncome फ़ोल्डर में यह चलाएँ:

```bash
sudo bash internetIncome.sh --delete
```

`--delete` कंटेनर हटाता है और `earnapp.txt`, `proxyrack.txt` और
Mysterium का डेटा फ़ोल्डर रखता है। `--deleteBackup` उन्हें भी हटा देता है
([internetIncome.sh, लाइन 61 से 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
और [लाइन 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562)),
इसलिए पहले import करें।

## कौन-सी फ़ाइलें इस्तेमाल करें { #which-files-to-use }

InternetIncome फ़ोल्डर से:

- `properties.conf`, आपकी सेटिंग्स।
- `earnapp.txt`, अगर आपने EarnApp चलाया था। हर लाइन में एक डिवाइस लिंक होता है
  ([लाइन 1250 से 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261))।
- `proxyrack.txt`, अगर आपने ProxyRack चलाया था। हर लाइन में एक डिवाइस UUID
  ([लाइन 817 से 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827))।

CashPilot हर फ़ाइल का पहला डिवाइस लेता है: वही जिसे आपके मुख्य कंटेनर ने
इस्तेमाल किया और जिसे आपने अपने खाते से जोड़ा। बाकी लाइनें प्रॉक्सी
कॉपियों की थीं, और पेज बताता है कि उसने कितनी छोड़ दीं।

InternetIncome हर मान को shell से गुज़ारता है
([लाइन 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375))।
single quotes में लिखा मान जैसा लिखा है वैसा ही लिया जाता है, जैसा
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf)
की टिप्पणियाँ सलाह देती हैं। single quotes के बाहर का जो मान `$`, backtick, space या
कोई ऐसा दूसरा अक्षर रखता है जिसे shell बदल देगा, वह वैसा नहीं होता जैसा फ़ाइल दिखाती है, इसलिए
CashPilot पता लगाने के लिए shell चलाने के बजाय आपसे उसे फिर से टाइप करने को कहता है।

## import कैसे करें { #how-to-import }

1. **Settings** (सेटिंग्स) खोलें, फिर **Import from another tool** (किसी दूसरे टूल से import करें) (या `/import` पर जाएँ)।
2. `properties.conf` जोड़ें, और अगर आपके पास हों तो `earnapp.txt` और `proxyrack.txt` भी।
   टूल को "Tell from the files" (फ़ाइलों से पहचानें) पर रहने दें, या InternetIncome चुनें।
3. तालिका जाँचें। जो सेवाएँ आप चाहते हैं उन पर टिक करें और missing चिह्नित हर मान
   भरें। Repocket को आपके खाते का ईमेल चाहिए, जो InternetIncome ने कभी नहीं
   माँगा।
4. **Save the ticked services** (टिक की गई सेवाएँ सहेजें) दबाएँ, फिर उसी पेज से उन्हें अपने वर्करों पर
   डिप्लॉय करें।

## क्या आता है { #what-comes-over }

| InternetIncome ऐप | पढ़ी गई keys | CashPilot सेवा | क्या आता है |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | API कुंजी (अपना ईमेल जोड़ें) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | टोकन |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`, `proxyrack.txt` | ProxyRack | API कुंजी, डिवाइस UUID |
| `iproyals` | `IPROYALS_EMAIL`, `IPROYALS_PASSWORD` | IPRoyal Pawns | ईमेल, पासवर्ड |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWORD` | Honeygain | ईमेल, पासवर्ड |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `earnfm` | `EARN_FM_API` | Earn.fm | API कुंजी |
| `earnapp` | `EARNAPP=true`, `earnapp.txt` | EarnApp | डिवाइस id |
| `bitping` | `BITPING_EMAIL`, `BITPING_PASSWORD` | Bitping | ईमेल, पासवर्ड |
| `mysterium` | `MYSTERIUM=true` | Mysterium | चालू किया जाता है; नीचे Mysterium का नोट देखें |

खाली मान का मतलब है कि ऐप बंद था, और वह सूचीबद्ध नहीं होता।

ये ऐप सूचीबद्ध होते हैं पर लाए नहीं जाते:

| InternetIncome ऐप | क्यों |
|---|---|
| `urnetwork` | InternetIncome एक session टोकन इस्तेमाल करता है। CashPilot URnetwork में आपके ईमेल और पासवर्ड से साइन इन करता है। |
| `grass` | Grass एक browser extension के रूप में चलता है। CashPilot केवल उस पर नज़र रखता है, Grass डैशबोर्ड के access token से। |
| `titan`, `ebesucher`, `wipter` | CashPilot इन पर नज़र रखता है, पर डिप्लॉय करने के लिए कोई कंटेनर नहीं है। |
| `peer2profit` | अब उपलब्ध नहीं। |

जिन ऐप की सेवा CashPilot में नहीं है (antGain, Adnade और दूसरे), उनकी सेटिंग्स
नाम से "पढ़ी नहीं गईं" के रूप में सूचीबद्ध होती हैं।

## क्या कभी नहीं आता { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot हर डिवाइस का नाम उस वर्कर के नाम पर रखता है जिस पर वह चलता है, ताकि
  दो वर्कर कभी एक ही नाम न बताएँ। आपके पुराने डिवाइस हर प्रदाता के डैशबोर्ड में तब तक
  offline के रूप में सूचीबद्ध रहते हैं जब तक आप उन्हें वहाँ से नहीं हटाते।
- **प्रॉक्सी** (`USE_PROXIES`, `proxies.txt`)। हर प्रॉक्सी को फ़्लीट पेज के प्रॉक्सी
  सेक्शन में जोड़ें, फिर अपनी सेवाओं की कॉपियाँ उसके ज़रिए चलाएँ; प्रॉक्सी जोड़ने से
  अपने आप कुछ शुरू नहीं होता। `USE_PROXIES=true` के साथ InternetIncome
  आपकी सेवाएँ केवल प्रॉक्सी के ज़रिए चलाता था। import सहेजने से भी कुछ शुरू नहीं होता।
  प्रॉक्सी कॉपी के लिए पहले वर्कर पर वही सेवा डिप्लॉय होनी चाहिए, और
  उसे डिप्लॉय करने पर वह वर्कर के अपने कनेक्शन पर चलती है, इसलिए जिस सेवा को
  कभी वह कनेक्शन इस्तेमाल नहीं करना चाहिए, उसे बिना टिक के रहने दें। देखें [प्रॉक्सी
  कॉपी](../proxies.md)।
- **`BROWSER_USERNAME` और `BROWSER_PASSWORD`**, InternetIncome के अपने ब्राउज़र का
  लॉगिन।

## कमाई पर नज़र { #earnings-tracking }

Honeygain, IPRoyal Pawns और Bitping के लिए कंटेनर का लॉगिन ही
खाते का लॉगिन है, इसलिए CashPilot उनके कमाई वाले क्रेडेंशियल भी भर देता है, जब तक आपने
उन्हें सेटिंग्स में पहले से सेट न किया हो। हर दूसरी सेवा के लिए कमाई का लॉगिन
**Settings > Earnings collection** (सेटिंग्स > कमाई का संग्रह) में जोड़ें।

## Mysterium { #mysterium }

import करने से Mysterium चालू हो जाता है, पर CashPilot एक नई
पहचान के साथ एक नया नोड शुरू करता है। पुराने नोड का keystore और कोई भी बिना settle हुई कमाई
InternetIncome के `mysterium-data` फ़ोल्डर में रहती है। पहले उन्हें settle करें, या पहचान साथ लाने के लिए
[Mysterium गाइड](../guides/mysterium.md) का पालन करें।

## सुरक्षा { #safety }

- फ़ाइलों में कुछ भी चलाया या expand नहीं किया जाता, और उनमें दिया कोई पता खोला नहीं जाता।
- फ़ाइलें एक बार पढ़ी जाती हैं और रखी नहीं जातीं। आप जो सहेजते हैं, वह एन्क्रिप्ट करके रखा जाता है,
  CashPilot के हर दूसरे क्रेडेंशियल की तरह।
- पेज पर सीक्रेट केवल "set" के रूप में दिखते हैं।
- सहेजे गए import तब तक import पेज पर रहते हैं जब तक आप **Forget** (भूल जाएँ) नहीं दबाते, ताकि आप
  बाद में उन्हें और वर्करों पर डिप्लॉय कर सकें।
