---
source_hash: b48a8fc19aa4
---
# CashPilot की तुलना { #how-cashpilot-compares }

यह पेज CashPilot की तुलना उन दूसरे खुले प्रोजेक्ट से करता है जो Docker में कई निष्क्रिय आय ऐप चलाते हैं। हमने हर प्रोजेक्ट को 2026-11-04 को जाँचा, और CashPilot को 2026-11-28 को फिर से जाँचा। किसी दूसरे प्रोजेक्ट के बारे में हर सेल उस फ़ाइल से लिंक होता है जिससे वह आया है, एक तय commit पर, ताकि आप खुद जाँच सकें। अगर कोई सेल ग़लत या पुराना है, तो कृपया [एक issue खोलें](https://github.com/GeiserX/CashPilot/issues)।

## तुलना किए गए प्रोजेक्ट { #projects-compared }

| प्रोजेक्ट | हमने क्या जाँचा | 2026-11-04 को Stars | लाइसेंस |
|---|---|---|---|
| [money4band][m4b-tree] | रिलीज़ 5.0.0, tag commit `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` पर `65e900d` (2026-10-20), साथ में इसके 3.0.0-beta.9 binary के बारे में README के दावे | 238 | Proprietary, [अपना लाइसेंस v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` पर `db9338a` (2026-11-03) | 257 | कोई LICENSE फ़ाइल नहीं। [README][ii-license] मूल को कॉपी करने की अनुमति देता है और बदली हुई कॉपियाँ बाँटने से मना करता है |
| [CashFactory][cf-tree] | `main` पर `0ff4bd0` (2025-04-08) | 410 | [LICENSE][cf-license-file] फ़ाइल GPL-3.0 है, पर [README][cf-license] बदली हुई कॉपियाँ बाँटने से मना करता है |
| [home-assistant-passive-income][ha-tree] (HA add-ons) | रिलीज़ 2.0.6, `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | रिलीज़ v3.0.1, `47a07fb` (2026-11-27) | 77 | GPL-3.0 |

money4band की दो कोड लाइनें हैं। इसकी डिफ़ॉल्ट branch `main` (`3bfafb1`) में अब भी 4.x कोड है, और वहाँ इसका आख़िरी कोड बदलाव 2026-03-03 को हुआ था। रिलीज़ 5.0.0 एक अलग इतिहास से बना है। हम 5.0.0 की तुलना करते हैं, क्योंकि इसका सबसे नया रिलीज़ यही देता है।

IGM का वेब UI, फ़्लीट प्रबंधन और installer binary closed source हैं और इसकी रिपॉज़िटरी में नहीं हैं। जहाँ कोई सेल उन पर निर्भर है, वहाँ लिखा है "README claims" और README की लाइन का लिंक है। IGM के कॉलम में बाकी सब कुछ रिपॉज़िटरी की shell scripts और compose फ़ाइलों से आता है।

छोड़े गए: [earning-machine](https://github.com/jf-m/earning-machine) और [passiveMachine](https://github.com/Xpl0itU/passiveMachine) में 2024 के बाद कोई commit नहीं हुआ है। GitHub खोज में ऐसा कुछ और नहीं मिला जिसकी देखभाल होती हो और जो एक से ज़्यादा ऐप चलाता हो, केवल एक-ऐप वाली इमेज मिलीं।

## संक्षेप में { #short-version }

- **InternetIncome, money4band, IGM और, v1.69.0 से, CashPilot प्रॉक्सी के ज़रिए कई IP पर कमा सकते हैं।** पहले तीन हर ऐप को हर प्रॉक्सी के लिए एक बार चलाते हैं, और प्रॉक्सी InternetIncome की मुख्य सुविधा है। CashPilot किसी वर्कर पर पहले से डिप्लॉय की गई सेवा की अतिरिक्त कॉपियाँ चलाता है, हर एक SOCKS5, HTTP CONNECT या Tailscale exit-node प्रॉक्सी के ज़रिए ([प्रॉक्सी कॉपी](proxies.md))।
- **InternetIncome 23 ऐप शुरू करता है, IGM 20 और CashPilot का वर्कर <!-- n:docker -->21<!-- /n -->।** CashPilot कुल मिलाकर ज़्यादा सेवाओं (<!-- n:live -->50<!-- /n -->) पर नज़र रखता है, क्योंकि यह उन browser extension, डेस्कटॉप और GPU सेवाओं को भी देखता है जिन्हें यह नहीं चलाता। v1.64.0 से यह आपकी बताई कोई भी इमेज [कस्टम सेवा](custom-services.md) के रूप में भी चला सकता है।
- **money4band और IGM आपके लिए दैनिक इनाम क्लेम करते हैं, और ऐप इमेज को Watchtower से अपडेट रखते हैं।** CashPilot इनमें से कुछ नहीं करता। यह इमेज केवल तब फिर से खींचता है जब आप डिप्लॉय या फिर से डिप्लॉय करते हैं।
- **यहाँ केवल CashPilot ही आपके प्रदाता खातों से बैलेंस पढ़ता है और इतिहास रखता है।** money4band 5.0.0 अपने कैटलॉग से अनुमान दिखाता है, आपके खातों से नहीं। बाकी हर प्रदाता के डैशबोर्ड से लिंक करते हैं।
- **यहाँ केवल CashPilot ही ऐसा open-source प्रोजेक्ट है जिसमें कई सर्वरों के लिए एक UI है।** IGM का README फ़्लीट प्रबंधन का दावा करता है, पर वह कोड उसके closed binary में है।
- **v1.70.0 से, यहाँ केवल CashPilot ही कमाई ऐप कंटेनरों को डिफ़ॉल्ट रूप से आपके LAN से दूर रखता है, कुछ सीमाओं के साथ।** यह नए इंस्टॉल पर चालू है, और उन अपग्रेड किए गए इंस्टॉल पर भी जिनका कोई कमाई ऐप Docker के डिफ़ॉल्ट bridge पर नहीं है। जिस अपग्रेड किए गए इंस्टॉल के कमाई ऐप पहले से उस bridge पर हैं, वह उन्हें तब तक वहीं रखता है जब तक आप पृथक्करण चालू नहीं करते, और `CASHPILOT_CONTAINER_NETWORK` में आपके बताए नेटवर्क को CashPilot से कोई सुरक्षा घेरा नहीं मिलता ([पृथक्करण](isolation.md#modes))। 2.0.7 से Mysterium भी सुरक्षा घेरे के पीछे चलता है; 2.0.6 तक डिप्लॉय किया गया नोड तब तक होस्ट के नेटवर्क पर, बिना सुरक्षा घेरे के, रहता है जब तक आप उसे फिर से डिप्लॉय नहीं करते ([Mysterium सुरक्षा घेरे के पीछे](mysterium-fence.md))।

## आमने-सामने { #side-by-side }

CashPilot का कॉलम v3.0.1 के बारे में है। इसका हर सेल छोटा है, और विवरण व कोड के लिंक [तालिका के नीचे के नोट्स](#cashpilot-notes) में हैं। बाकी कॉलम ऊपर की तालिका के commits के बारे में हैं।

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | HA add-ons |
|---|---|---|---|---|---|---|
| यह कितने ऐप शुरू कर सकता है (देखें [हमने कैसे गिना](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> वर्कर चलाता है, साथ में [कस्टम इमेज](custom-services.md); कुल <!-- n:live -->50<!-- /n --> पर नज़र | 15 ([कैटलॉग][m4b-catalog])। README 35 कहता है, जिसमें community और हटाए गए ऐप [शामिल हैं][m4b-readme-35] | 20 ([apps.json][igm-apps]) | 23 ([script][ii-script]) | 11 ([compose फ़ाइल][cf-compose]) | 10 ([add-on फ़ोल्डर][ha-tree]) |
| इसे कैसे इंस्टॉल करें | Docker Compose: एक UI, और हर सर्वर पर एक वर्कर ([फ़्लीट](fleet.md)) | Python CLI या पहले से बना binary जो compose फ़ाइल लिखता है ([रिलीज़][m4b-tree]) | `curl \| sh` installer ([README][igm-install]) जो एक closed binary डाउनलोड करता है, जिसे केवल उसी रिलीज़ की SHA256SUMS फ़ाइल से जाँचा जाता है ([installer][igm-installer-sums]) | 1,608 लाइनों की एक bash script जो `sudo docker run` चलाती है ([script][ii-script]) | एक स्थिर compose फ़ाइल और sudo से चलाई जाने वाली `setup.sh` ([setup][cf-setup]) | एक Home Assistant add-on रिपॉज़िटरी; Home Assistant OS या Supervised चाहिए |
| कई सर्वर, एक दृश्य | हाँ ([फ़्लीट](fleet.md)) | नहीं, हर डिवाइस पर एक stack | README हाँ का दावा करता है, closed binary में ([README][igm-features]) | नहीं | नहीं | नहीं |
| कई प्रॉक्सी या IP | हाँ, SOCKS5, HTTP CONNECT या Tailscale exit-node प्रॉक्सी के ज़रिए ([प्रॉक्सी कॉपी](proxies.md), [नोट्स](#cashpilot-notes)) | हाँ ([README][m4b-features], [कोड][m4b-multiproxy]) | हाँ ([README][igm-features], [compose][igm-proxy]) | हाँ, इसकी मुख्य सुविधा ([README][ii-readme-top]) | नहीं | नहीं |
| कमाई | <!-- n:collectors -->20<!-- /n --> कलेक्टर आपके प्रदाता खातों से बैलेंस पढ़ते हैं और इतिहास रखते हैं | कैटलॉग की सीमाओं से अनुमान, खाते का डेटा नहीं ([कोड][m4b-earnings]) | scripts में कुछ नहीं मिला | कुछ नहीं | कुछ नहीं | कुछ नहीं |
| भुगतान | बैलेंस गिरने पर भुगतान का सुझाव देता है, और आपकी पुष्टि के बाद उसे दर्ज करता है ([schema][cp-payouts]) | कुछ नहीं | कुछ नहीं | कुछ नहीं | कुछ नहीं | कुछ नहीं |
| दैनिक इनाम क्लेम करना | नहीं | हाँ, sidecars ([README][m4b-features]) | हाँ ([README][igm-features], [compose][igm-sidecars]) | नहीं | नहीं | नहीं |
| सहेजे गए क्रेडेंशियल | UI के डेटाबेस में एन्क्रिप्टेड (Fernet) ([नोट्स](#cashpilot-notes)) | एन्क्रिप्टेड (Fernet); कुंजी फ़ाइल डेटा डायरेक्टरी में रहती है ([कोड][m4b-crypto]) | एन्क्रिप्टेड (openssl के साथ AES-256); कुंजी फ़ाइल vault के बगल में रहती है ([कोड][igm-encryptor]) | `properties.conf` में सादा टेक्स्ट; कुछ पासवर्ड `docker run` arguments के रूप में दिए जाते हैं ([script][ii-password-arg]) | `.env` में सादा टेक्स्ट ([फ़ाइल][cf-env]) | Add-on विकल्प, जिन्हें Supervisor `/data/options.json` में रखता है ([HA docs][ha-options]) |
| कमाई ऐप कंटेनर की सेटिंग्स | हर capability हटाई जाती है, `no-new-privileges`, pids की सीमा; privileged मना ([नोट्स](#cashpilot-notes)) | हर non-privileged सेवा पर `no-new-privileges` ([कोड][m4b-nnp]); प्रॉक्सी कंटेनर `NET_ADMIN` के साथ privileged है ([template][m4b-tun]) | ऐप सेवाओं पर कुछ सेट नहीं; Mysterium को `NET_ADMIN` मिलता है ([compose][igm-hosting-myst]); प्रॉक्सी कंटेनर को `NET_ADMIN` मिलता है, `no-new-privileges` और pids की सीमा के साथ ([compose][igm-proxy]) | Ebesucher `seccomp=unconfined` के साथ चलता है ([script][ii-seccomp]); प्रॉक्सी कंटेनरों और Mysterium को `NET_ADMIN` मिलता है | कुछ सेट नहीं | कोई add-on privileged, host network या Docker API तक पहुँच नहीं माँगता ([उदाहरण config][ha-config]) |
| Docker socket किसमें माउंट होता है | socket proxy, केवल-पढ़ने के मोड में, और एक बार चलने वाला migration कंटेनर ([नोट्स](#cashpilot-notes)) | Watchtower ([template][m4b-watchtower]) | Watchtower, जो `no-new-privileges` के साथ केवल-पढ़ने के मोड में है ([compose][igm-watchtower]) | पाँच restart सहायक कंटेनर ([script][ii-sock-helper]) और Watchtower ([script][ii-watchtower]) | Portainer, सभी interfaces पर पोर्ट 8000, 9000 और 9443 पर प्रकाशित ([compose][cf-portainer]), और दो Watchtower ([compose][cf-watchtower-ps], [compose][cf-watchtower-efm]) | कुछ नहीं |
| इमेज टैग | <!-- n:docker -->21<!-- /n --> में से <!-- n:pinned -->9<!-- /n --> कमाई ऐप इमेज किसी संस्करण या digest पर पिन हैं; बाकी बदलते रहते हैं | सभी 15 ऐप इमेज `:latest` इस्तेमाल करती हैं ([उदाहरण][m4b-image]); प्रॉक्सी कंटेनर v2.6.0 पर पिन, Watchtower `:1` पर | कोई टैग नहीं, इसलिए Docker `latest` इस्तेमाल करता है ([compose][igm-hosting]); टैग केवल कुछ ARM builds के लिए सेट है | ज़्यादातर `:latest` ([उदाहरण][ii-seccomp]); EarnApp `:lite`, amd64 पर प्रॉक्सी के साथ Honeygain 0.6.6 पर पिन ([script][ii-honeygain]), ARM पर Traffmonetizer के हर arch के टैग; Watchtower `:nightly` | `:latest` या कोई टैग नहीं, EarnApp `:lite` को छोड़कर ([compose][cf-compose]) | हर add-on का एक संस्करण, जिसे एक दैनिक CI job बढ़ाता है ([workflow][ha-bump], [उदाहरण][ha-dockerfile]) |
| ऐप इमेज के अपडेट | हर डिप्लॉय या फिर से डिप्लॉय पर फिर से खींची जाती है; कोई स्वचालित updater नहीं | Watchtower ([template][m4b-watchtower]) | हर 4 घंटे में Watchtower ([compose][igm-watchtower]) | दिन में एक बार Watchtower, अगर आप इसे चालू करें ([script][ii-watchtower]) | दो Watchtower, हर एक एक ही ऐप तक सीमित, PacketStream ([compose][cf-watchtower-ps]) और EarnFM ([compose][cf-watchtower-efm]); बाकी 9 ऐप अपडेट नहीं होते | Home Assistant के add-on अपडेट |
| LAN पृथक्करण | नए इंस्टॉल पर डिफ़ॉल्ट रूप से चालू ([पृथक्करण](isolation.md#lan-isolation-by-default), [नोट्स](#cashpilot-notes)) | अपना bridge subnet ([config][m4b-subnet]), जो LAN को नहीं रोकता | कुछ merge नहीं हुआ | कुछ नहीं मिला | कुछ नहीं मिला | कुछ नहीं मिला |
| ARM | arm64 UI और वर्कर, हर डिप्लॉय से पहले प्लेटफ़ॉर्म की जाँच के साथ ([ARM](arm.md)) | arm64 और armv7 binaries ([रिलीज़][m4b-release]) | README amd64 और arm64, सीमाओं के साथ arm32 का दावा करता है, और QEMU सेट करता है ([README][igm-arch]) | केवल amd64 वाली इमेज के लिए binfmt emulation चाहिए ([README][ii-arm]) | README कहता है कि यह Raspberry Pi पर काम नहीं करता ([README][cf-raspberry]) | हर add-on के हिसाब से; ProxyRack केवल amd64 है ([config][ha-proxyrack]) |
| UI | वेब UI, साथ में Desktop, Android, MCP और Home Assistant clients | CLI, मेनू और एक स्थानीय वेब डैशबोर्ड जो डिफ़ॉल्ट रूप से 127.0.0.1 से बँधा है ([कोड][m4b-bind]) | CLI, मेनू, और README के अनुसार पोर्ट 4747 पर एक वेब UI जो LAN पर पहुँच में है ([README][igm-webui]) | कुछ नहीं, एक script | पोर्ट 80 पर एक bookmarks पेज और Portainer ([README][cf-ui]) | Home Assistant का add-on पैनल |
| सबसे नया रिलीज़ | v3.0.1, 2026-11-27 | 5.0.0, 2026-07-25 | 3.0.0-beta.9, 2026-09-23 | कोई संस्करण वाला रिलीज़ नहीं | v1.10, 2024-07-17 | 2.0.6, 2026-11-03 |
| ऐप के अलावा बाहर जाने वाली कॉल | update जाँच, सार्वजनिक IP की पहचान, विनिमय दरें और ऑन-चेन बैलेंस; CDN से fonts और Chart.js ([नोट्स](#cashpilot-notes)) | अपनी update जाँच के लिए GitHub releases ([कोड][m4b-updater]); इमेज टैग जाँचने के लिए Docker Hub और ghcr.io ([कोड][m4b-registry]); जब आप IP जाँच चलाते हैं, तो आपके सार्वजनिक IP के लिए `api.ipify.org`, `ifconfig.me` या `icanhazip.com` और IP scores के लिए सादे HTTP पर `ip-api.com` ([कोड][m4b-ipscore]) | GitHub releases ([कोड][igm-version]); आपके सार्वजनिक IP के लिए `api.ipify.org`, `ifconfig.me` या `icanhazip.com` ([कोड][igm-ifconfig]); IP scores के लिए सादे HTTP पर `ip-api.com` ([कोड][igm-ipscore])। closed binary की जाँच नहीं हुई | कुछ नहीं मिला | कुछ नहीं मिला | कुछ नहीं मिला |

### CashPilot के कॉलम पर नोट्स { #cashpilot-notes }

- **कई प्रॉक्सी या IP।** v1.69.0 से CashPilot किसी वर्कर पर पहले से डिप्लॉय की गई सेवा की अतिरिक्त कॉपियाँ चलाता है, हर एक अपने प्रॉक्सी के ज़रिए। SOCKS5 और HTTP CONNECT केवल TCP ले जाते हैं: टनल प्रॉक्सी के पोर्ट पर केवल TCP बाहर जाने देता है, इसलिए SOCKS5 UDP relays गिरा दिए जाते हैं। Tailscale exit node UDP भी ले जाता है। कमाई ऐप एक टनल कंटेनर का network namespace साझा करता है ([कोड][cp-proxy-deploy])। वह namespace केवल loopback, टनल और प्रॉक्सी से टनल के अपने कनेक्शन को बाहर जाने देता है: उसके पते और पोर्ट पर TCP, या tailscaled के चिह्नित packets ([टनल firewall][cp-tunnel-fw])। इसलिए बंद पड़ा प्रॉक्सी कमाई ऐप का ट्रैफ़िक लीक होने देने के बजाय उसे रोक देता है ([यह कैसे काम करता है](proxies.md#how-it-works))। कोई सेवा प्रॉक्सी के ज़रिए नहीं चल सकती जब उसे host networking, प्रकाशित पोर्ट, वॉल्यूम, devices, GPU या `NET_ADMIN`, `NET_RAW` या `SYS_ADMIN` चाहिए, या जब उसकी शर्तें प्रॉक्सी को मना करती हैं। इसलिए <!-- n:docker -->21<!-- /n --> में से <!-- n:noproxy -->10<!-- /n --> केवल सर्वर के अपने IP से कमाती हैं ([क्या नहीं चल सकता](proxies.md#what-cannot-run-through-a-proxy))।
- **कमाई।** कुछ कलेक्टरों को आपके ब्राउज़र से कॉपी किया गया cookie या टोकन चाहिए, और उनमें से कुछ की अवधि ख़त्म होती है। हर सेवा की गाइड बताती है कि कौन-से।
- **सहेजे गए क्रेडेंशियल।** UI एन्क्रिप्शन कुंजी फ़ाइल को डेटाबेस वाले उसी डेटा वॉल्यूम में रखता है ([कोड][cp-fernet])। कमाई ऐप के क्रेडेंशियल हर वर्कर तक कंटेनर के एनवायरनमेंट वेरिएबल के रूप में पहुँचते हैं, इसलिए वे उस वर्कर के Docker config (`docker inspect`) में सादे टेक्स्ट में होते हैं।
- **कमाई ऐप कंटेनर की सेटिंग्स।** वर्कर हर capability हटाता है, फिर वही वापस जोड़ता है जो कैटलॉग उस सेवा के लिए बताता है। यह `no-new-privileges` और pids की सीमा सेट करता है, और privileged कंटेनरों को मना करता है ([कोड][cp-hardening], [कोड][cp-privileged], [सुरक्षा डिफ़ॉल्ट](security-defaults.md))। Mysterium सुरक्षा घेरे वाले bridge पर अपने network namespace में `NET_ADMIN`, `SETUID` और `SETGID` के साथ, digest से पिन की गई इमेज पर चलता है ([कैटलॉग][cp-myst])। एक वैकल्पिक gVisor runtime user space में चलने वाला kernel जोड़ सकता है ([runtimes](security-defaults.md#container-runtimes-gvisor-where-it-works))।
- **Docker socket।** v1.71.0 से केवल socket proxy socket को माउंट करता है: sockguard 2.4.7, digest से पिन, केवल-पढ़ने के मोड में ([compose][cp-sock])। वर्कर को एक छनी हुई कॉपी मिलती है जो privileged कंटेनरों, `/` या socket के bind, और कैटलॉग से बाहर की capabilities या devices को मना करती है ([socket proxy](security-defaults.md#docker-socket-proxy))। एक बार चलने वाला `cashpilot-migrate` कंटेनर भी socket माउंट करता है: यह proxy के owner isolation के लिए पुराने रिलीज़ की बनाई चीज़ों पर label लगाता है, और proxy शुरू होने से पहले बंद हो जाता है ([compose][cp-migrate])। किसी कमाई ऐप को socket कभी नहीं मिलता ([कोड][cp-mounts])। proxy अभी root की सीमा नहीं है: `CASHPILOT_COMPOSE_DIR` या `CASHPILOT_PROXY_BIND_MOUNTS` सेट होने पर, किसी अनुमत फ़ोल्डर में रखा गया symlink दो डिप्लॉय में होस्ट के `/` तक पहुँच जाता है ([विवरण](security-defaults.md#docker-socket-proxy))। Unraid और TrueNAS की listings अब भी वर्कर में raw socket माउंट करती हैं ([app stores](app-stores.md))।
- **LAN पृथक्करण।** v1.70.0 से डिफ़ॉल्ट रूप से चालू, नए इंस्टॉल पर और उन अपग्रेड किए गए इंस्टॉल पर जिनका कोई कमाई ऐप Docker के डिफ़ॉल्ट bridge पर नहीं है। वर्कर कमाई ऐप को अपने bridge पर रखता है और उसके लिए एक firewall तालिका लिखता है ([कोड][cp-fence])। तालिका निजी सीमाएँ, tailnet की सीमा, cloud metadata, होस्ट के जुड़े subnets और खुद होस्ट को गिरा देती है। सार्वजनिक IP की पहचान चालू हो तो यह घर का सार्वजनिक IP भी गिरा देती है ([पृथक्करण](isolation.md#lan-isolation-by-default))। जिस अपग्रेड किए गए इंस्टॉल के कमाई ऐप पहले से डिफ़ॉल्ट bridge पर हैं, वह तब तक वहीं रहता है जब तक आप **Turn on isolation** (पृथक्करण चालू करें) नहीं दबाते। `CASHPILOT_ISOLATION=off` इसे बंद करता है। `CASHPILOT_CONTAINER_NETWORK` सेट होने पर CashPilot उस नेटवर्क के लिए कोई सुरक्षा घेरा नहीं लिखता, और firewall नियम आपके हाथ में होते हैं। Podman पर कोई सुरक्षा घेरा नहीं है, और फ़्लीट पेज यह बताता है ([मोड](isolation.md#modes), [कोड][cp-fence-mode])। 2.0.7 से Mysterium भी सुरक्षा घेरे में है। 2.0.6 तक डिप्लॉय किया गया नोड तब तक होस्ट के नेटवर्क पर रहता है जब तक आप उसे फिर से डिप्लॉय नहीं करते ([Mysterium सुरक्षा घेरे के पीछे](mysterium-fence.md))। एक जाँच दिखाती है कि कमाई ऐप कहाँ तक पहुँच सकते हैं ([जाँच](isolation-check.md))।
- **बाहर जाने वाली कॉल।** ऐप के अलावा, CashPilot इन्हें कॉल करता है:
    - GitHub releases, दिन में एक बार, अपनी update जाँच के लिए (`CASHPILOT_UPDATE_CHECK=off` इसे रोकता है, [कोड][cp-update])।
    - `api.ipify.org`, `ifconfig.me` या `icanhazip.com`, हर वर्कर से घंटे में एक बार, उसके सार्वजनिक IP के लिए (`CASHPILOT_EGRESS_DETECT=off` इसे रोकता है, [कोड][cp-egress])।
    - CoinGecko और Frankfurter, विनिमय दरों के लिए ([कोड][cp-rates])।
    - mempool.space, api.kaspa.org और सार्वजनिक Ethereum, Ethereum Classic, Polygon और Solana RPC नोड, [ऑन-चेन बैलेंस](onchain.md) के लिए।
    - iptoasn.com, अपनी नेटवर्क-नाम तालिका के लिए, हफ़्ते में ज़्यादा से ज़्यादा एक बार और केवल तब जब किसी वर्कर पर [गतिविधि](activity.md#network-names-and-countries) चालू हो ([कोड][cp-ipgeo])।
    - हर प्रदाता, कलेक्टरों के लिए।

    ब्राउज़र Google Fonts ([template][cp-cdn]) और jsDelivr से Chart.js ([template][cp-chartjs]) लोड करता है।

हमने जो कोड पढ़ा, उसमें कोई भी प्रोजेक्ट उपयोग की telemetry नहीं भेजता। IGM का closed binary पढ़ा नहीं जा सका।

यहाँ का हर प्रोजेक्ट ऐप के क्रेडेंशियल कंटेनरों को एनवायरनमेंट वेरिएबल के रूप में देता है, और InternetIncome कुछ को कमांड arguments के रूप में भी देता है, इसलिए ऐप चलाने वाले होस्ट पर वे Docker के कंटेनर config (`docker inspect` में `Env` और `Args`) में सादे टेक्स्ट में होते हैं, जिन्हें Docker तक पहुँच वाला कोई भी पढ़ सकता है। "सहेजे गए क्रेडेंशियल" वाली पंक्ति केवल सहेजी गई कॉपी के बारे में है।

## हमने कैसे गिना { #how-we-counted }

- **CashPilot.** कैटलॉग की वे सेवाएँ जिनकी स्थिति active या beta है और जिनकी Docker इमेज है, GPU कंप्यूट या माइनिंग pools को छोड़कर। इस पेज की संख्या `scripts/generate_readme_tables.py` से आती है, और अगर यह अलग हो जाए तो CI विफल होता है।
- **money4band 5.0.0.** `config/catalog/supported/` में हर ऐप की एक JSON फ़ाइल: 15। README के "35 apps" में community कैटलॉग भी गिना गया है, जो डिफ़ॉल्ट रूप से बंद है ([config][m4b-community]), बिना Docker इमेज वाले ऐप भी, और हटाए गए ऐप भी।
- **IGM.** `apps.json` में एंट्रियाँ: 20, सभी चालू। प्रॉक्सी कंटेनर, Watchtower और claim sidecars नहीं गिने गए।
- **InternetIncome.** `internetIncome.sh` में हर `# Starting ... container` comment ब्लॉक, प्रॉक्सी और Watchtower ब्लॉक को छोड़कर: 24। Ebesucher के Chrome और Firefox ब्लॉक एक ही ऐप हैं, और EarnFM और EarnFM Fleetshare भी, जो एक ही EarnFM खाता इस्तेमाल करते हैं। Depin extensions ब्लॉक Grass और Gradient शुरू करता है ([script][ii-depin]), यानी दो ऐप। कुल 23। README की तालिका 27 ऐप सूचीबद्ध करती है, जिनमें से कुछ का केवल साइन अप लिंक है।
- **CashFactory.** `docker-compose.yml` में कमाई वाली सेवाएँ: 11। Portainer, वेब सर्वर और दो Watchtower नहीं गिने गए। एक सेवा comment करके बंद की गई है।
- **HA add-ons.** config फ़ाइल वाले add-on फ़ोल्डर: 10।

हमने यह नहीं जाँचा कि हर सूची का हर ऐप अब भी भुगतान करता है या नहीं।

[m4b-tree]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28
[m4b-release]: https://github.com/MRColorR/money4band/releases/tag/5.0.0
[m4b-catalog]: https://github.com/MRColorR/money4band/tree/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported
[m4b-readme-35]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L114-L116
[m4b-features]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/README.md?plain=1#L98-L102
[m4b-multiproxy]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/multiproxy.py
[m4b-earnings]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/apps/earnings.py#L36-L48
[m4b-crypto]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/core/crypto.py#L20-L22
[m4b-nnp]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/compose_builder.py#L459-L462
[m4b-tun]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L54-L67
[m4b-watchtower]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/template/user-config.json#L78-L97
[m4b-image]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported/HONEYGAIN.json
[m4b-subnet]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L362
[m4b-community]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/m4b-config.json#L375-L381
[m4b-bind]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/api/server.py#L613-L624
[m4b-updater]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/updater.py#L165-L168
[m4b-registry]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/checker.py#L15-L16
[m4b-ipscore]: https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/network/ip_scorer.py#L24-L30

[igm-tree]: https://github.com/XternA/income-generator/tree/65e900dcd4342ba011b7093e9800d300804c2f2e
[igm-license]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/LICENSE
[igm-apps]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/apps.json
[igm-features]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L28-L37
[igm-install]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L49
[igm-webui]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L79
[igm-arch]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/README.md?plain=1#L126-L132
[igm-installer-sums]: https://github.com/XternA/income-generator/blob/662225aa9ca009a991d1c6247a369ef20adc6850/install.sh#L291-L302
[igm-proxy]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.proxy.yml#L1-L20
[igm-sidecars]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.service.yml
[igm-hosting]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml
[igm-hosting-myst]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.hosting.yml#L105-L114
[igm-watchtower]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/compose/compose.yml#L1-L23
[igm-encryptor]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/encryptor.sh#L15-L22
[igm-version]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/version.sh#L8
[igm-ifconfig]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/core/network.sh#L8-L15
[igm-ipscore]: https://github.com/XternA/income-generator/blob/65e900dcd4342ba011b7093e9800d300804c2f2e/scripts/ip/ip-score.sh#L94-L97

[ii-tree]: https://github.com/engageub/InternetIncome/tree/db9338ab5a77539db8420476742af647b6cf82e5
[ii-license]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L139-L142
[ii-readme-top]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L1-L6
[ii-arm]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/README.md?plain=1#L78-L82
[ii-script]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh
[ii-sock-helper]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L477
[ii-seccomp]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L501
[ii-password-arg]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L908
[ii-depin]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L920-L932
[ii-honeygain]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L947-L952
[ii-watchtower]: https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1277-L1283

[cf-tree]: https://github.com/OlivierGaland/CashFactory/tree/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94
[cf-license-file]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/LICENSE
[cf-license]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L50-L53
[cf-raspberry]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L61
[cf-ui]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/README.md?plain=1#L46-L47
[cf-compose]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml
[cf-portainer]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L28-L36
[cf-watchtower-ps]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L131-L145
[cf-watchtower-efm]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml#L254-L268
[cf-env]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env#L9-L12
[cf-setup]: https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/setup.sh#L12

[ha-tree]: https://github.com/bvlinsky/home-assistant-passive-income/tree/bf4b9f4558a06fef28154cde51d2aff087713b0e
[ha-config]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/config.yaml
[ha-proxyrack]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/proxyrack/config.yaml
[ha-dockerfile]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/honeygain/Dockerfile#L1
[ha-bump]: https://github.com/bvlinsky/home-assistant-passive-income/blob/bf4b9f4558a06fef28154cde51d2aff087713b0e/.github/workflows/update-addon-versions.yml#L5
[ha-options]: https://developers.home-assistant.io/docs/add-ons/configuration#options--schema

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L541-L557
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/database.py#L51
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/orchestrator.py#L1534-L1541
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1977-L1978
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L1586-L1631
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/services/bandwidth/mysterium.yml#L25-L27
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L125-L180
[cp-update]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/update_check.py#L46-L56
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/exchange_rates.py#L125-L145
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/worker_api.py#L373-L380
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/templates/base.html#L292
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/proxy_tunnel.py#L1145
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/tunnel/cp-tunnel#L1-L27
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L103-L125
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/lan_fence.py#L29-L52
[cp-ipgeo]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/app/ipgeo.py#L1-L40
[cp-migrate]: https://github.com/GeiserX/CashPilot/blob/47a07fbd3dc1a723fd41c6f22ec6bc9b619699db/docker-compose.yml#L91-L101
