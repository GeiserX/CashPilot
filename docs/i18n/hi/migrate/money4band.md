---
source_hash: 05d0f97e7d36
---
# money4band से आना { #moving-from-money4band }

CashPilot money4band का config पढ़ सकता है और आपकी सेवाओं के लॉगिन ले आ सकता है, ताकि
आपको उन्हें फिर से टाइप न करना पड़े। CashPilot के सहेजने से पहले आप सब कुछ जाँचते हैं।

## शुरू करने से पहले { #before-you-start }

आपको CashPilot का स्वामी खाता चाहिए और कम से कम एक CashPilot वर्कर, उस
मशीन पर जहाँ अभी money4band चलता है, या किसी दूसरी मशीन पर।

किसी मशीन पर CashPilot से वही सेवाएँ डिप्लॉय करने से पहले वहाँ money4band बंद करें।
एक ही कनेक्शन के पीछे की दो कॉपियाँ एक जितना ही कमाती हैं, और एक ही EarnApp
या ProxyRack डिवाइस id दो बार नहीं चलनी चाहिए। money4band के मेनू में **Stop apps stack**
इस्तेमाल करें
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json)),
या उसके फ़ोल्डर में `docker compose down` चलाएँ। अगर आपने अतिरिक्त प्रॉक्सी
इंस्टेंस सेट किए हैं, तो उनमें से हर एक को भी बंद करें।

## कौन-सी फ़ाइल इस्तेमाल करें { #which-file-to-use }

अपने money4band फ़ोल्डर में `config/user-config.json` इस्तेमाल करें। इसे CashPilot तक
कैसे पहुँचाएँ, यह आपके money4band संस्करण पर निर्भर करता है।

money4band 4.x में, जब आप **Setup Apps** चलाते हैं, तो money4band यह फ़ाइल लिखता है, और
इसमें ठीक वही होता है जो आपने टाइप किया। इसके बगल की `.env` उसी फ़ाइल से बनती है और वह
भी काम करती है, और money4band 3.x की हाथ से बदली गई `.env` भी। दोनों केवल आपकी डिस्क पर
रहती हैं: money4band की
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
उन्हें सूचीबद्ध करती है।

money4band 5.0 डिस्क पर `config/user-config.json` को एन्क्रिप्ट करता है
([सुरक्षा नोट्स](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption)),
और हर शुरुआत के बाद अपनी `.env` मिटा देता है
([env builder](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11))।
CashPilot एन्क्रिप्ट की गई फ़ाइल नहीं पढ़ सकता। अपने money4band फ़ोल्डर में उसका
`config edit` कमांड चलाएँ: release binary के लिए `./Money4Band-<os>-<arch> config edit`,
या source से चलाने पर `python main.py config edit`। यह डिक्रिप्ट की गई फ़ाइल को आपके
editor में खोलता है
([CLI reference](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit))।
उसका पूरा टेक्स्ट कॉपी करें, उसे **Import from another tool** (किसी दूसरे टूल से import करें) पेज पर पेस्ट करें, फिर editor बंद करें।

JSON फ़ाइल को प्राथमिकता दें। `.env` में Docker Compose बिना quotes वाले मानों में `$` को
expand करता है, इसलिए जिस पासवर्ड में `$` है, वह वैसा नहीं होता जैसा फ़ाइल दिखाती है। CashPilot
अंदाज़ा नहीं लगाता: वह आपसे वह मान फिर से टाइप करने को कहता है।

## import कैसे करें { #how-to-import }

1. **Settings** (सेटिंग्स) खोलें, फिर **Import from another tool** (किसी दूसरे टूल से import करें) (या `/import` पर जाएँ)।
2. `user-config.json` जोड़ें, या उसका टेक्स्ट पेस्ट करें। टूल को "Tell from the
   files" (फ़ाइलों से पहचानें) पर रहने दें, या money4band चुनें।
3. तालिका जाँचें। जो सेवाएँ आप चाहते हैं उन पर टिक करें और missing चिह्नित हर मान
   भरें।
4. **Save the ticked services** (टिक की गई सेवाएँ सहेजें) दबाएँ, फिर उसी पेज से उन्हें अपने वर्करों पर
   डिप्लॉय करें।

## क्या आता है { #what-comes-over }

फ़ील्ड के नाम money4band के
[user-config template](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
से आते हैं, और `.env` के नाम वे हैं जो उसका
[generator](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
लिखता है (`<APP>_<FLAG>`, जैसे `REPOCKET_APIKEY`)। money4band 5.0 अपने
[app catalog](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported)
में वही फ़ील्ड नाम रखता है।

| money4band ऐप | CashPilot सेवा | क्या आता है |
|---|---|---|
| `earnapp` | EarnApp | डिवाइस id (`uuid`), ताकि आपका जुड़ा हुआ डिवाइस कमाता रहे |
| `honeygain` | Honeygain | ईमेल, पासवर्ड |
| `iproyalpawns` | IPRoyal Pawns | ईमेल, पासवर्ड |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | टोकन |
| `repocket` | Repocket | ईमेल, API कुंजी |
| `earnfm` | Earn.fm | API कुंजी |
| `proxyrack` | ProxyRack | API कुंजी, डिवाइस UUID |
| `proxylite` | ProxyLite | user id |
| `bitping` | Bitping | ईमेल, पासवर्ड |
| `mystnode` | Mysterium | चालू किया जाता है; नीचे Mysterium का नोट देखें |

जो ऐप आपने money4band में बंद किया था, वह बिना टिक के दिखता है। जो ऐप बंद है और
जिसमें template के placeholders (`yourHONEYGAINMail`) और पोर्ट की सूचियों के अलावा कुछ नहीं है,
उसे छोड़ दिया जाता है, इसलिए बिना छुई `user-config.json` से खाली तालिका मिलती है।

ये ऐप सूचीबद्ध होते हैं पर लाए नहीं जाते:

| money4band ऐप | क्यों |
|---|---|
| `proxybase` | money4band ProxyBase का पुराना client user id के साथ चलाता है। CashPilot मौजूदा client चलाता है, जिसके लिए proxybase.org का Access Token चाहिए। |
| `urnetwork` | money4band एक session टोकन रखता है। CashPilot URnetwork में आपके ईमेल और पासवर्ड से साइन इन करता है। |
| `grass` | Grass एक browser extension के रूप में चलता है। CashPilot केवल उस पर नज़र रखता है, Grass डैशबोर्ड के access token से। |
| `gradient`, `dawn`, `teneo`, `titan`, `spide`, `wipter` | CashPilot इन पर नज़र रखता है, पर डिप्लॉय करने के लिए कोई कंटेनर नहीं है। |
| `packetshare`, `peer2profit`, `speedshare` | अब उपलब्ध नहीं। |

कोई भी दूसरा ऐप "CashPilot has no such service" (CashPilot में ऐसी कोई सेवा नहीं है) के रूप में सूचीबद्ध होता है।

## क्या कभी नहीं आता { #what-never-comes-over }

- **डिवाइस का नाम।** CashPilot हर डिवाइस का नाम उस वर्कर के नाम पर रखता है जिस पर वह चलता है, ताकि
  दो वर्कर कभी एक ही नाम न बताएँ। आपके पुराने डिवाइस हर प्रदाता के डैशबोर्ड में तब तक
  offline के रूप में सूचीबद्ध रहते हैं जब तक आप उन्हें वहाँ से नहीं हटाते।
- **प्रॉक्सी।** हर प्रॉक्सी को फ़्लीट पेज के प्रॉक्सी सेक्शन में जोड़ें, फिर अपनी सेवाओं की
  कॉपियाँ उसके ज़रिए चलाएँ; प्रॉक्सी जोड़ने से अपने आप कुछ शुरू नहीं होता।
  import सहेजने से भी कुछ शुरू नहीं होता। प्रॉक्सी कॉपी के लिए पहले वर्कर पर वही सेवा
  डिप्लॉय होनी चाहिए, और उसे डिप्लॉय करने पर वह वर्कर के अपने कनेक्शन पर चलती है,
  इसलिए जिस सेवा को कभी वह कनेक्शन इस्तेमाल नहीं करना चाहिए, उसे बिना टिक के रहने दें।
  देखें [प्रॉक्सी कॉपी](../proxies.md)।
- **Watchtower और सूचनाएँ।** CashPilot अपने कंटेनर खुद अपडेट करता है।
- **money4band का डैशबोर्ड और उसके पोर्ट।**

## कमाई पर नज़र { #earnings-tracking }

Honeygain, IPRoyal Pawns और Bitping के लिए कंटेनर का लॉगिन ही
खाते का लॉगिन है, इसलिए CashPilot उनके कमाई वाले क्रेडेंशियल भी भर देता है, जब तक आपने
उन्हें सेटिंग्स में पहले से सेट न किया हो। हर दूसरी सेवा के लिए कमाई का लॉगिन
**Settings > Earnings collection** (सेटिंग्स > कमाई का संग्रह) में जोड़ें।

## Mysterium { #mysterium }

import करने से Mysterium चालू हो जाता है, पर CashPilot एक नई
पहचान के साथ एक नया नोड शुरू करता है। पुराने नोड का keystore और कोई भी बिना settle हुई कमाई
money4band के `.data/mysterium-node` फ़ोल्डर में रहती है
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json))। पहले उन्हें settle करें, या पहचान साथ लाने के लिए
[Mysterium गाइड](../guides/mysterium.md) का पालन करें।

3.x की `.env` से यह पता नहीं चलता कि आपने Mysterium चलाया था या नहीं: उसका template हमेशा
डैशबोर्ड पोर्ट सूचीबद्ध करता है। 3.x फ़ाइल से Mysterium import नहीं होता, इसलिए अगर आपने
उसे चलाया था, तो उसे कैटलॉग से जोड़ें।

## सुरक्षा { #safety }

- फ़ाइल में कुछ भी चलाया या expand नहीं किया जाता, और उसमें दिया कोई पता खोला नहीं जाता।
- फ़ाइल एक बार पढ़ी जाती है और रखी नहीं जाती। आप जो सहेजते हैं, वह एन्क्रिप्ट करके रखा जाता है,
  CashPilot के हर दूसरे क्रेडेंशियल की तरह।
- पेज पर सीक्रेट केवल "set" के रूप में दिखते हैं।
- सहेजे गए import तब तक import पेज पर रहते हैं जब तक आप **Forget** (भूल जाएँ) नहीं दबाते, ताकि आप
  बाद में उन्हें और वर्करों पर डिप्लॉय कर सकें।
