---
source_hash: d88e40f8d9a6
---
# ऑन-चेन भुगतान बैलेंस { #on-chain-payout-balances }

किसी सार्वजनिक भुगतान पते का बैलेंस देखने के लिए **Payouts** (भुगतान) खोलें। Bitcoin
[mempool.space](https://mempool.space/docs/api/rest) का इस्तेमाल करता है और Kaspa
[api.kaspa.org](https://api.kaspa.org/docs) का। Ethereum, Polygon और Solana
सार्वजनिक RPC नोड इस्तेमाल करते हैं। CashPilot इन पतों को बिना किसी कुंजी के पढ़ सकता है।

| आपको क्या दिखता है | इसका मतलब |
|---|---|
| एक राशि | explorer ने एक बैलेंस बताया। बताया गया शून्य शून्य के रूप में दिखता है। स्रोत देखने के लिए राशि पर कर्सर रखें। |
| Pending (लंबित) | Bitcoin पर explorer एक अपुष्ट बदलाव देखता है। प्लस का मतलब है कि पैसा आ रहा है। माइनस का मतलब है कि पैसा ख़र्च हो रहा है। पुष्ट राशि अलग से दिखाई जाती है। |
| Could not check (जाँच नहीं हो सकी) | explorer ने जवाब नहीं दिया या ऐसा डेटा भेजा जिसे CashPilot पढ़ नहीं सका। |
| Address not valid (पता मान्य नहीं) | पता फ़ॉर्मेट की जाँच में विफल रहा। CashPilot ने अनुरोध नहीं भेजा। |
| Private chain (निजी चेन) | Monero का बैलेंस पढ़ने के लिए आपकी निजी view key चाहिए। बैलेंस अपने वॉलेट में देखें। CashPilot आपसे यह कुंजी कभी नहीं माँगता। |
| एक डैश | इस पंक्ति के लिए कोई पता या रीडर नहीं है, या जाँच बंद है। जब कोई सेटिंग जाँच बंद करती है, तो कौन-सी सेटिंग है यह देखने के लिए डैश पर कर्सर रखें। |

Kaspa का सार्वजनिक endpoint एक ही बैलेंस बताता है। वह लंबित राशि अलग से
नहीं देता।

ऑन-चेन कॉलम पते का अभी का बैलेंस दिखाता है। इसमें
दूसरे स्रोतों से आए ट्रांसफ़र भी शामिल हो सकते हैं। pool का बिना भुगतान वाला बैलेंस दिखाता है कि pool
अभी भी आपके लिए कितना रखे हुए है। Lightning से हुआ OCEAN भुगतान
ऑन-चेन बैलेंस में नहीं दिखता। बैलेंस यह भी नहीं बता सकता कि कौन-से ट्रांसफ़र
आपके pool से आए।

## चुनें कि जाँच कहाँ जाती है { #choose-where-the-lookup-goes }

हर जाँच आपका सार्वजनिक भुगतान पता और UI सर्वर का IP
explorer के साथ साझा करती है। explorer उन पतों को आपस में जोड़ सकता है जिन्हें आप एक ही IP से जाँचते हैं।

अगर आप अपना नोड चलाते हैं, तो UI कंटेनर के एनवायरनमेंट में base URL सेट करें।
डिफ़ॉल्ट इस्तेमाल करने के लिए वेरिएबल सेट न करें। उस चेन की जाँच बंद करने के लिए उसे
खाली मान पर सेट करें।

उदाहरण के लिए, UI सेवा के लिए एक Compose override में यह हो सकता है:

```yaml
services:
  cashpilot-ui:
    environment:
      CASHPILOT_ONCHAIN_URL_BITCOIN: "http://mempool.local:3006/api"
      CASHPILOT_ONCHAIN_URL_KASPA: ""
```

Bitcoin या Kaspa कॉन्फ़िगर करते समय Esplora या Kaspa API का base URL इस्तेमाल करें।
Bitcoin endpoint किसी Bitcoin pool की
[अपेक्षित कमाई](fleet.md#running-costs) के लिए नेटवर्क difficulty और ब्लॉक इनाम भी देता है। उस रीडिंग के लिए
mempool backend चाहिए (उसका `/v1/mining` API); सादा Esplora सर्वर केवल
बैलेंस की जाँच का जवाब देता है, और तब pool की पंक्ति में कोई अपेक्षित राशि नहीं दिखती।
Ethereum, Polygon और Solana के लिए संबंधित वेरिएबल
`CASHPILOT_ONCHAIN_URL_ETHEREUM`, `CASHPILOT_ONCHAIN_URL_POLYGON` या
`CASHPILOT_ONCHAIN_URL_SOLANA` को किसी नोड के RPC URL पर सेट करें। HTTP या HTTPS URL
इस्तेमाल करें, जिसमें क्रेडेंशियल, query string या fragment न हो। नए एनवायरनमेंट के साथ
UI कंटेनर को फिर से बनाकर बदलाव लागू करें।
