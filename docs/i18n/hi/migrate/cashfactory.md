---
source_hash: 7f8476aeb8b6
---
# CashFactory से आना { #moving-from-cashfactory }

CashPilot CashFactory की `.env` पढ़ सकता है और आपकी सेवाओं के लॉगिन ले आ सकता है, ताकि
आपको उन्हें फिर से टाइप न करना पड़े। CashPilot के सहेजने से पहले आप सब कुछ जाँचते हैं।

## शुरू करने से पहले { #before-you-start }

आपको CashPilot का स्वामी खाता और कम से कम एक CashPilot वर्कर चाहिए।

किसी मशीन पर CashPilot से वही सेवाएँ डिप्लॉय करने से पहले वहाँ CashFactory बंद करें।
एक ही कनेक्शन के पीछे की दो कॉपियाँ एक जितना ही कमाती हैं, और एक ही EarnApp
डिवाइस id दो बार नहीं चलनी चाहिए। CashFactory फ़ोल्डर में `docker compose down` चलाएँ।
इसकी
[compose फ़ाइल](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
तीन ऐसे कंटेनर भी शुरू करती है जो Docker socket माउंट करते हैं: Portainer (लाइन 31)
और दो Watchtower कंटेनर (लाइन 141 और 264)। पक्का करें कि वे भी हट गए हैं: `docker ps` में
उनमें से कोई नहीं दिखना चाहिए।

## कौन-सी फ़ाइल इस्तेमाल करें { #which-file-to-use }

अपने CashFactory फ़ोल्डर की `.env` फ़ाइल इस्तेमाल करें, वही जिसे आपने
[नमूने](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env) से भरा था।

Docker Compose वह फ़ाइल पढ़ता है, और जो मान single quotes में नहीं हैं उनमें `$` को
expand करता है। ऐसा मान वैसा नहीं होता जैसा फ़ाइल दिखाती है, इसलिए CashPilot अंदाज़ा लगाने के बजाय
आपसे उसे फिर से टाइप करने को कहता है।

## import कैसे करें { #how-to-import }

1. **Settings** (सेटिंग्स) खोलें, फिर **Import from another tool** (किसी दूसरे टूल से import करें) (या `/import` पर जाएँ)।
2. `.env` फ़ाइल जोड़ें, या उसका टेक्स्ट पेस्ट करें। टूल को "Tell from the
   files" (फ़ाइलों से पहचानें) पर रहने दें, या CashFactory चुनें।
3. तालिका जाँचें। जो सेवाएँ आप चाहते हैं उन पर टिक करें और missing चिह्नित हर मान
   भरें।
4. **Save the ticked services** (टिक की गई सेवाएँ सहेजें) दबाएँ, फिर उसी पेज से उन्हें अपने वर्करों पर
   डिप्लॉय करें।

## क्या आता है { #what-comes-over }

| CashFactory ऐप | पढ़ी गई keys | CashPilot सेवा | क्या आता है |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | डिवाइस id, ताकि आपका जुड़ा हुआ डिवाइस कमाता रहे |
| `honeygain` | `HONEYGAIN_EMAIL`, `HONEYGAIN_PASSWD` | Honeygain | ईमेल, पासवर्ड |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`, `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | ईमेल, पासवर्ड |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | टोकन |
| `repocket` | `RP_EMAIL`, `RP_API_KEY` | Repocket | ईमेल, API कुंजी |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | user id |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | डिवाइस UUID |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | API कुंजी |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | कुछ नहीं: अब उपलब्ध नहीं |

जो मान अब भी नमूने का placeholder (`<email>`, `sdk-node-<md5sum>`) दिखाता है,
उसे सेट नहीं माना जाता, और जिस सेवा में placeholders के अलावा कुछ नहीं है, उसे
तालिका से छोड़ दिया जाता है।

## क्या कभी नहीं आता { #what-never-comes-over }

- **`DEVICE_NAME`.** CashPilot हर डिवाइस का नाम उस वर्कर के नाम पर रखता है जिस पर वह चलता है, ताकि
  दो वर्कर कभी एक ही नाम न बताएँ। आपके पुराने डिवाइस हर प्रदाता के डैशबोर्ड में तब तक
  offline के रूप में सूचीबद्ध रहते हैं जब तक आप उन्हें वहाँ से नहीं हटाते।
- **Bitping.** CashFactory Bitping का लॉगिन `.env` में नहीं, एक Docker वॉल्यूम में रखता है,
  इसलिए import के पास पढ़ने को कुछ नहीं होता और कोई Bitping पंक्ति नहीं दिखती।
  लॉगिन Bitping के डिप्लॉय फ़ॉर्म में टाइप करें।
- **Portainer और Watchtower.** CashPilot अपने कंटेनर खुद संभालता और
  अपडेट करता है।

## कमाई पर नज़र { #earnings-tracking }

Honeygain और IPRoyal Pawns के लिए कंटेनर का लॉगिन ही खाते का लॉगिन है,
इसलिए CashPilot उनके कमाई वाले क्रेडेंशियल भी भर देता है, जब तक आपने उन्हें
सेटिंग्स में पहले से सेट न किया हो। हर दूसरी सेवा के लिए कमाई का लॉगिन
**Settings > Earnings collection** (सेटिंग्स > कमाई का संग्रह) में जोड़ें।

## सुरक्षा { #safety }

- फ़ाइल में कुछ भी चलाया या expand नहीं किया जाता, और उसमें दिया कोई पता खोला नहीं जाता।
- फ़ाइल एक बार पढ़ी जाती है और रखी नहीं जाती। आप जो सहेजते हैं, वह एन्क्रिप्ट करके रखा जाता है,
  CashPilot के हर दूसरे क्रेडेंशियल की तरह।
- पेज पर सीक्रेट केवल "set" के रूप में दिखते हैं।
- सहेजे गए import तब तक import पेज पर रहते हैं जब तक आप **Forget** (भूल जाएँ) नहीं दबाते, ताकि आप
  बाद में उन्हें और वर्करों पर डिप्लॉय कर सकें।
