---
source_hash: e99e2c0c80bb
---
# ऐप स्टोर { #app-stores }

आप कई होम-सर्वर सिस्टम के ऐप स्टोर से CashPilot इंस्टॉल कर सकते हैं।
हर लिस्टिंग डैशबोर्ड (`drumsergio/cashpilot`) और वर्कर
(`drumsergio/cashpilot-worker`) इंस्टॉल करती है, जो सेवा कंटेनरों को शुरू और बंद
करता है। इस रिपॉज़िटरी के केवल CasaOS और Runtipi पैकेज ही
`docker-compose.yml` से Docker socket proxy भी इंस्टॉल करते हैं, इसलिए उनका वर्कर
कभी सीधा Docker socket नहीं रखता। Unraid टेम्पलेट, TrueNAS ऐप और
CasaOS ऐप स्टोर के खुले pull request वाला पैकेज अब भी Docker
socket को सीधे वर्कर में माउंट करते हैं।

आप कोई भी स्टोर इस्तेमाल करें, डैशबोर्ड को अपने LAN या VPN पर ही रखें। यह वर्कर को
आदेश दे सकता है, और वर्कर होस्ट पर Docker चलाता है। जहाँ वर्कर खुद
socket रखता है, वहाँ यह होस्ट पर root के बराबर है।

## आज उपलब्ध { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

Apps टैब में **CashPilot** खोजें और दोनों टेम्पलेट इंस्टॉल करें:
`cashpilot` (डैशबोर्ड) और `cashpilot-worker`। दोनों पर एक ही
`CASHPILOT_API_KEY` सेट करें।

टेम्पलेट https://github.com/GeiserX/docker-templates से आते हैं और
`latest` इमेज टैग का पालन करते हैं, इसलिए Community Applications के उपयोगकर्ताओं को हर रिलीज़
टेम्पलेट बदले बिना मिलती है।

### TrueNAS SCALE { #truenas-scale }

CashPilot TrueNAS की **community** train में है। Apps खोलें, फिर Discover Apps,
और **CashPilot** खोजें।

ऐप की परिभाषा
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot पर रखी जाती है और
एक सटीक इमेज digest पिन करती है। TrueNAS के अपने bots इसे नए रिलीज़ पर ले जाते हैं, इसलिए यह
सबसे नए CashPilot से कुछ रिलीज़ पीछे हो सकती है।

## समीक्षा की प्रतीक्षा में { #waiting-for-review }

### CasaOS { #casaos }

CasaOS ऐप स्टोर में एक pull request खुला है:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

जब तक वह merge नहीं होता, इसे custom app के रूप में इंस्टॉल करें: CasaOS में App Store चुनें,
फिर Custom Install, फिर Import, और इसकी सामग्री पेस्ट करें:
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

इसके लिए CasaOS 0.4.5 या नया चाहिए: उस रिलीज़ से इसका ऐप मैनेजर
Docker Compose 2.23 पर बना है, जो फ़ाइल से socket proxy की policy पढ़ता है।
पुराने संस्करण उसे छोड़ देते हैं, और तब वर्कर Docker तक नहीं पहुँच पाता।

वह फ़ाइल एक सटीक रिलीज़ पिन करती है। उसे import करने से पहले दोनों इमेज टैग
(`drumsergio/cashpilot` और `drumsergio/cashpilot-worker`) को
https://github.com/GeiserX/CashPilot/releases के सबसे नए रिलीज़ पर सेट करें। फ़ाइल में
proxy policy `main` का पालन करती है; अगर वर्कर का स्थिति पेज कहे कि उसकी policy
पुरानी है, तो फ़ाइल फिर से import करें।

## तैयार, अभी जमा नहीं किया गया { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

पैकेज
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
में तैयार है, पर अभी Runtipi ऐप स्टोर में नहीं है। इसे अभी इस्तेमाल करने के लिए, Runtipi docs
के अनुसार इसे अपने नियंत्रण वाले किसी custom app store में जोड़ें:
https://runtipi.io/docs/guides/create-your-own-app-store

## उपलब्ध नहीं { #not-offered }

Umbrel के लिए वर्कर का अलग डिज़ाइन चाहिए, क्योंकि Umbrel ऐप होस्ट socket के बजाय
Docker-in-Docker कंटेनर के ज़रिए Docker तक पहुँचते हैं। हमने इसका परीक्षण नहीं
किया है, इसलिए अभी कोई Umbrel पैकेज नहीं है।

किसी भी दूसरे सिस्टम के लिए रिपॉज़िटरी की `docker-compose.yml` इस्तेमाल करें, जैसा
[शुरुआत करें](getting-started.md) में बताया गया है।
