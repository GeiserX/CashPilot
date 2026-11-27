---
source_hash: 1a93abea95d7
---
# مقارنة CashPilot بغيره { #how-cashpilot-compares }

تقارن هذه الصفحة CashPilot بالمشاريع المفتوحة الأخرى التي تشغّل عدة تطبيقات للدخل السلبي في Docker. فحصنا كل مشروع في 2026-11-04. وكل خلية تتعلق بمشروع آخر ترتبط بالملف الذي جاءت منه، عند commit ثابت، حتى تستطيع التحقق بنفسك. إذا كانت خلية ما خاطئة أو قديمة، فيُرجى [فتح issue](https://github.com/GeiserX/CashPilot/issues).

## المشاريع المقارَنة { #projects-compared }

| المشروع | ما الذي فحصناه | النجوم في 2026-11-04 | الترخيص |
|---|---|---|---|
| [money4band][m4b-tree] | الإصدار 5.0.0، commit الوسم `af9d903` (2026-07-25) | 471 | GPL-3.0 |
| [income-generator][igm-tree] (IGM) | `main` عند `65e900d` (2026-10-20)، إضافةً إلى ادعاءات README بشأن ملفه التنفيذي 3.0.0-beta.9 | 238 | احتكاري، [ترخيصه الخاص v1.4][igm-license] |
| [InternetIncome][ii-tree] | `main` عند `db9338a` (2026-11-03) | 257 | لا يوجد ملف LICENSE. يسمح [README][ii-license] بنسخ الأصل ويمنع توزيع نسخ معدّلة |
| [CashFactory][cf-tree] | `main` عند `0ff4bd0` (2025-04-08) | 410 | الملف [LICENSE][cf-license-file] هو GPL-3.0، لكن [README][cf-license] يمنع توزيع نسخ معدّلة |
| [home-assistant-passive-income][ha-tree] (إضافات HA) | الإصدار 2.0.6، `bf4b9f4` (2026-11-03) | 105 | Unlicense |
| CashPilot | الإصدار v1.64.0، `main` عند `c7a12bd` (2026-11-04) | 77 | GPL-3.0 |

لدى money4band خطّان من الكود. فرعه الافتراضي `main` (`3bfafb1`) لا يزال يحتوي على كود الإصدارات 4.x، وكان آخر تغيير في الكود هناك في 2026-03-03. أما الإصدار 5.0.0 فمبني من سجل منفصل. نقارن 5.0.0 لأنه ما يشحنه أحدث إصدار له.

واجهة الويب في IGM، وإدارة الأسطول، والملف التنفيذي للمثبّت مغلقة المصدر وليست في مستودعه. وحيث تعتمد خلية عليها، تقول "ادعاءات README" وترتبط بسطر README. وكل ما عدا ذلك في عمود IGM يأتي من سكربتات shell وملفات compose في المستودع.

المستبعَدة: لم يشهد [earning-machine](https://github.com/jf-m/earning-machine) و[passiveMachine](https://github.com/Xpl0itU/passiveMachine) أي commits منذ 2024. ولم يجد بحث في GitHub أي مشروع آخر يُصان ويشغّل أكثر من تطبيق واحد، بل صور حاويات لتطبيق واحد فقط.

## النسخة المختصرة { #short-version }

- **يستطيع InternetIncome وmoney4band وIGM، ومنذ الإصدار v1.69.0 CashPilot، الكسب على عناوين IP كثيرة عبر البروكسيات.** تشغّل المشاريع الثلاثة الأولى كل تطبيق مرة لكل بروكسي، والبروكسيات هي الميزة الرئيسية في InternetIncome. أما CashPilot فيشغّل نسخًا إضافية من خدمة منشورة بالفعل على عامل، كل منها عبر بروكسي SOCKS5 أو HTTP CONNECT أو عقدة خروج Tailscale ([النسخ عبر بروكسي](proxies.md)).
- **يشغّل InternetIncome (23) تطبيقات أكثر مما يشغّله عامل CashPilot (<!-- n:docker -->21<!-- /n -->)؛ ويشغّل IGM عشرين.** يتتبّع CashPilot خدمات أكثر إجمالًا (<!-- n:live -->50<!-- /n -->) لأنه يتابع أيضًا خدمات إضافات المتصفح وسطح المكتب وGPU التي لا يشغّلها. ومنذ الإصدار v1.64.0 يستطيع أيضًا تشغيل أي صورة حاوية تسمّيها بوصفها [خدمة مخصصة](custom-services.md).
- **يطالب money4band وIGM بالمكافآت اليومية نيابةً عنك، ويُبقيان صور التطبيقات محدّثة باستخدام Watchtower.** لا يفعل CashPilot أيًّا من ذلك. فهو لا يسحب صورة الحاوية مجددًا إلا عند النشر أو إعادة النشر.
- **CashPilot هو الوحيد هنا الذي يقرأ الأرصدة من حساباتك لدى المزوّدين ويحتفظ بسجل.** يعرض money4band 5.0.0 تقديرات من كتالوجه الخاص، لا من حساباتك. أما البقية فترتبط بلوحة تحكم كل مزوّد.
- **CashPilot هو الوحيد مفتوح المصدر هنا الذي يوفّر واجهة واحدة لخوادم كثيرة.** يدّعي README الخاص بـ IGM إدارة الأسطول، لكن ذلك الكود في ملفه التنفيذي المغلق.
- **منذ الإصدار v1.70.0، CashPilot هو الوحيد هنا الذي يُبقي حاويات تطبيقات الربح بعيدًا عن شبكتك المحلية (LAN) افتراضيًا، مع حدود.** الميزة مفعّلة للتثبيتات الجديدة وللتثبيتات المرقّاة التي لا يوجد فيها تطبيق ربح على الجسر الافتراضي لـ Docker. أما التثبيت المرقّى الذي تقع تطبيقات الربح فيه على ذلك الجسر بالفعل فيُبقيها هناك إلى أن تشغّل العزل، والشبكة التي تسمّيها في `CASHPILOT_CONTAINER_NETWORK` لا تحصل على حاجز من CashPilot ([العزل](isolation.md#modes)). ومنذ الإصدار 2.0.7 يعمل Mysterium خلف الحاجز أيضًا؛ أما العقدة المنشورة حتى الإصدار 2.0.6 فتبقى على شبكة المضيف، بلا حاجز، إلى أن تعيد نشرها ([Mysterium خلف الحاجز](mysterium-fence.md)).

## جنبًا إلى جنب { #side-by-side }

يصف عمود CashPilot الإصدار v1.64.0، باستثناء صفوف البروكسي ومقبس Docker والعزل عن الشبكة المحلية، التي تصف الإصدار v1.71.1 (`0170dee`، 2026-11-06)، وشبكة Mysterium في صفَّي إعدادات الحاوية والعزل عن الشبكة المحلية، التي تصف الإصدار التالي للإصدار 2.0.6 (`01e7310`). ويتضمن صف الاتصالات الصادرة استدعاءات المستكشف الواردة في [دليل الأرصدة على السلسلة الحالي](onchain.md). وتصف الأعمدة الأخرى الـ commits الواردة في الجدول أعلاه.

| | CashPilot | money4band 5.0.0 | IGM | InternetIncome | CashFactory | إضافات HA |
|---|---|---|---|---|---|---|
| التطبيقات التي يستطيع تشغيلها (راجع [كيف أحصينا](#how-we-counted)) | <!-- n:docker -->21<!-- /n --> يشغّلها العامل، إضافةً إلى [صور الحاويات المخصصة](custom-services.md)؛ و<!-- n:live -->50<!-- /n --> متتبَّعة إجمالًا | 15 ([الكتالوج][m4b-catalog]). يقول README إنها 35، وهذا الرقم [يشمل][m4b-readme-35] تطبيقات المجتمع والتطبيقات المُسقطة | 20 ([apps.json][igm-apps]) | 23 ([السكربت][ii-script]) | 11 ([ملف compose][cf-compose]) | 10 ([مجلدات الإضافات][ha-tree]) |
| طريقة التثبيت | Docker Compose: واجهة واحدة إضافةً إلى عامل على كل خادم؛ يشغّل العامل تطبيقات الربح عبر Docker API ([الأسطول](fleet.md)) | واجهة سطر أوامر Python أو ملف تنفيذي جاهز يكتب ملف compose ([الإصدار][m4b-tree]) | مثبّت `curl \| sh` ([README][igm-install]) ينزّل ملفًا تنفيذيًا مغلقًا، ولا يُتحقق منه إلا مقابل ملف SHA256SUMS من الإصدار نفسه ([المثبّت][igm-installer-sums]) | سكربت bash واحد من 1,608 أسطر يستدعي `sudo docker run` ([السكربت][ii-script]) | ملف compose ثابت إضافةً إلى `setup.sh` يُشغَّل بـ sudo ([الإعداد][cf-setup]) | مستودع إضافات Home Assistant؛ يحتاج إلى Home Assistant OS أو Supervised |
| خوادم كثيرة، عرض واحد | نعم ([الأسطول](fleet.md)) | لا، حزمة واحدة لكل جهاز | يدّعي README ذلك، في الملف التنفيذي المغلق ([README][igm-features]) | لا | لا | لا |
| بروكسيات أو عناوين IP كثيرة | نعم، منذ الإصدار v1.69.0: نسخ إضافية من خدمة منشورة، كل منها عبر بروكسي SOCKS5 أو HTTP CONNECT أو عقدة خروج Tailscale. لا ينقل SOCKS5 وHTTP CONNECT إلا TCP (لا يسمح النفق بالخروج إلا لحركة TCP إلى منفذ البروكسي، لذلك تُسقط مرحّلات UDP في SOCKS5)؛ أما عقدة خروج Tailscale فتنقل UDP أيضًا. يتشارك تطبيق الربح نطاق أسماء الشبكة الخاص بحاوية النفق، الذي لا يسمح جدار الحماية فيه بالخروج إلا لواجهة الاسترجاع المحلي والنفق واتصال النفق نفسه بالبروكسي (TCP إلى عنوانه ومنفذه، أو الحزم المعلَّمة من tailscaled)، لذلك يوقفه البروكسي المتعطّل بدلًا من أن يتسرّب ([النسخ عبر بروكسي](proxies.md#how-it-works)، [الكود][cp-proxy-deploy]، [جدار حماية النفق][cp-tunnel-fw]). لا يمكن تشغيل الخدمات التي تحتاج إلى شبكة المضيف أو منافذ منشورة أو وحدات تخزين أو أجهزة أو `NET_ADMIN` أو `NET_RAW` أو `SYS_ADMIN` عبر بروكسي ([النسخ عبر بروكسي](proxies.md#what-cannot-run-through-a-proxy)) | نعم ([README][m4b-features]، [الكود][m4b-multiproxy]) | نعم ([README][igm-features]، [compose][igm-proxy]) | نعم، ميزته الرئيسية ([README][ii-readme-top]) | لا | لا |
| الأرباح | <!-- n:collectors -->20<!-- /n --> مُجمِّعًا تقرأ الأرصدة من حسابات المزوّدين وتحتفظ بسجل. يحتاج بعضها إلى ملف تعريف ارتباط أو رمز منسوخ من متصفحك، وتنتهي صلاحية بعض هذه (راجع دليل كل خدمة) | تقديرات من نطاقات الكتالوج، لا بيانات الحساب ([الكود][m4b-earnings]) | لم نجد شيئًا في السكربتات | لا شيء | لا شيء | لا شيء |
| الدفعات | يقترح دفعة عندما ينخفض الرصيد، ويسجّلها بمجرد أن تؤكّدها ([المخطط][cp-payouts]) | لا شيء | لا شيء | لا شيء | لا شيء | لا شيء |
| المطالبة بالمكافآت اليومية | لا | نعم، بحاويات جانبية (sidecars) ([README][m4b-features]) | نعم ([README][igm-features]، [compose][igm-sidecars]) | لا | لا | لا |
| بيانات الاعتماد في حالة السكون | مشفّرة (Fernet) في قاعدة بيانات الواجهة؛ ويقع ملف المفتاح في وحدة تخزين البيانات نفسها ([الكود][cp-fernet]). تصل بيانات اعتماد تطبيقات الربح إلى كل عامل بوصفها متغيرات بيئة للحاوية، لذلك تكون نصًا عاديًا في إعدادات Docker لذلك العامل (`docker inspect`) | مشفّرة (Fernet)؛ ويقع ملف المفتاح في مجلد البيانات ([الكود][m4b-crypto]) | مشفّرة (AES-256 باستخدام openssl)؛ ويقع ملف المفتاح بجانب الخزنة ([الكود][igm-encryptor]) | نص عادي في `properties.conf`؛ وتُمرَّر بعض كلمات المرور بوصفها وسائط لـ `docker run` ([السكربت][ii-password-arg]) | نص عادي في `.env` ([الملف][cf-env]) | خيارات الإضافة، يخزّنها Supervisor في `/data/options.json` ([وثائق HA][ha-options]) |
| إعدادات حاويات تطبيقات الربح | إسقاط كل الصلاحيات (capabilities)، ثم يعيد الكتالوج ما تحتاج إليه الخدمة؛ و`no-new-privileges`؛ وحد لعدد العمليات (pids)؛ ورفض الوضع المميّز (privileged) ([الكود][cp-hardening]، [الكود][cp-privileged]). يعمل Mysterium في نطاق أسماء الشبكة الخاص به على الجسر المحاط بالحاجز مع `NET_ADMIN` و`SETUID` و`SETGID`، على صورة حاوية مثبّتة ببصمة ([الكتالوج][cp-myst]) | `no-new-privileges` على كل خدمة غير مميّزة ([الكود][m4b-nnp])؛ وحاوية البروكسي مميّزة مع `NET_ADMIN` ([القالب][m4b-tun]) | لا شيء مضبوط على خدمات التطبيقات؛ يحصل Mysterium على `NET_ADMIN` ([compose][igm-hosting-myst])؛ وتحصل حاوية البروكسي على `NET_ADMIN`، مع `no-new-privileges` وحد لعدد العمليات ([compose][igm-proxy]) | يعمل Ebesucher مع `seccomp=unconfined` ([السكربت][ii-seccomp])؛ وتحصل حاويات البروكسي وMysterium على `NET_ADMIN` | لا شيء مضبوط | لا تطلب أي إضافة الوضع المميّز أو شبكة المضيف أو الوصول إلى Docker API ([مثال إعدادات][ha-config]) |
| مقبس Docker مركّب في | منذ الإصدار v1.71.0، وكيل مقبس (sockguard 2.4.5، مثبّت ببصمة)، للقراءة فقط. يحصل العامل على نسخة مفلترة ترفض الحاويات المميّزة، وربط `/` أو المقبس، والصلاحيات أو الأجهزة الخارجة عمّا في الكتالوج ([compose][cp-sock]، [التفاصيل](security-defaults.md))؛ ولا يُركَّب أبدًا في تطبيق ربح ([الكود][cp-mounts]) | Watchtower ([القالب][m4b-watchtower]) | Watchtower، وهو للقراءة فقط مع `no-new-privileges` ([compose][igm-watchtower]) | خمس حاويات مساعدة لإعادة التشغيل ([السكربت][ii-sock-helper]) وWatchtower ([السكربت][ii-watchtower]) | Portainer، منشور على المنافذ 8000 و9000 و9443 على كل واجهات الشبكة ([compose][cf-portainer])، وحاويتا Watchtower ([compose][cf-watchtower-ps]، [compose][cf-watchtower-efm]) | لا شيء |
| وسوم صور الحاويات | 9 من صور تطبيقات الربح الـ <!-- n:docker -->21<!-- /n --> مثبّتة على إصدار أو بصمة؛ والبقية عائمة | كل صور التطبيقات الـ 15 تستخدم `:latest` ([مثال][m4b-image])؛ وحاوية البروكسي مثبّتة على v2.6.0، وWatchtower على `:1` | بلا وسم، لذلك يستخدم Docker القيمة `latest` ([compose][igm-hosting])؛ ولا يُضبط وسم إلا لبعض بنيات ARM | `:latest` في الغالب ([مثال][ii-seccomp])؛ وEarnApp على `:lite`، وHoneygain مثبّت على 0.6.6 عند تشغيله عبر بروكسي على amd64 ([السكربت][ii-honeygain])، وTraffmonetizer بوسوم لكل معمارية على ARM؛ وWatchtower على `:nightly` | `:latest` أو بلا وسم، باستثناء EarnApp على `:lite` ([compose][cf-compose]) | إصدار واحد لكل إضافة، تحدّثه مهمة CI يومية ([سير العمل][ha-bump]، [مثال][ha-dockerfile]) |
| تحديثات صور التطبيقات | تُسحب مجددًا عند كل نشر أو إعادة نشر؛ بلا أداة تحديث تلقائي | Watchtower ([القالب][m4b-watchtower]) | Watchtower كل 4 ساعات ([compose][igm-watchtower]) | Watchtower مرة يوميًا، إذا شغّلته ([السكربت][ii-watchtower]) | حاويتا Watchtower، كل منهما مقصورة على تطبيق واحد، PacketStream ([compose][cf-watchtower-ps]) وEarnFM ([compose][cf-watchtower-efm])؛ أما التطبيقات التسعة الأخرى فلا تُحدَّث | تحديثات الإضافات في Home Assistant |
| العزل عن الشبكة المحلية | مفعّل افتراضيًا منذ الإصدار v1.70.0 للتثبيتات الجديدة وللتثبيتات المرقّاة التي لا يوجد فيها تطبيق ربح على الجسر الافتراضي لـ Docker: يضع العامل تطبيقات الربح على جسره الخاص ويكتب جدول جدار حماية يُسقط النطاقات الخاصة، ونطاق tailnet، والبيانات الوصفية السحابية، والشبكات الفرعية المتصلة بالمضيف، والمضيف نفسه، ومع تفعيل اكتشاف عنوان IP العام، عنوان IP العام للمنزل ([العزل](isolation.md#lan-isolation-by-default)، [الكود][cp-fence]). أما التثبيت المرقّى الذي تقع تطبيقات الربح فيه على الجسر الافتراضي بالفعل فيبقى هناك إلى أن تضغط **Turn on isolation** (تشغيل العزل)؛ ويعطّله `CASHPILOT_ISOLATION=off`؛ ومع ضبط `CASHPILOT_CONTAINER_NETWORK`، لا يكتب CashPilot أي حاجز لتلك الشبكة وتكون قواعد جدار الحماية مسؤوليتك ([العزل](isolation.md#modes)، [الكود][cp-fence-mode]). ومنذ الإصدار 2.0.7 يُحاط Mysterium بالحاجز أيضًا؛ أما العقدة المنشورة حتى الإصدار 2.0.6 فتبقى على شبكة المضيف إلى أن تعيد نشرها ([Mysterium خلف الحاجز](mysterium-fence.md)). ويعرض فحصٌ ما تستطيع تطبيقات الربح الوصول إليه ([الفحص](isolation-check.md)) | شبكة فرعية خاصة لجسره ([الإعدادات][m4b-subnet])، لا تحجب الشبكة المحلية | لا شيء مدموج | لم نجد شيئًا | لم نجد شيئًا | لم نجد شيئًا |
| ARM | واجهة وعامل بمعمارية arm64؛ ويتحقق من منصات كل خدمة قبل النشر ([ARM](arm.md)) | ملفات تنفيذية لـ arm64 وarmv7 ([الإصدار][m4b-release]) | يدّعي README دعم amd64 وarm64، وarm32 مع حدود، ويُعدّ QEMU ([README][igm-arch]) | يحتاج إلى محاكاة binfmt لصور الحاويات الخاصة بـ amd64 فقط ([README][ii-arm]) | يقول README إنه لا يعمل على Raspberry Pi ([README][cf-raspberry]) | حسب الإضافة؛ ProxyRack لـ amd64 فقط ([الإعدادات][ha-proxyrack]) |
| الواجهة | واجهة ويب، إضافةً إلى عملاء Desktop وAndroid وMCP وHome Assistant | واجهة سطر أوامر، وقوائم، ولوحة تحكم ويب محلية مربوطة بـ 127.0.0.1 افتراضيًا ([الكود][m4b-bind]) | واجهة سطر أوامر، وقوائم، وبحسب README واجهة ويب على المنفذ 4747 يمكن الوصول إليها من الشبكة المحلية ([README][igm-webui]) | لا شيء، مجرد سكربت | صفحة إشارات مرجعية على المنفذ 80 إضافةً إلى Portainer ([README][cf-ui]) | لوحة إضافات Home Assistant |
| الـ commits على الفرع الافتراضي، من 2026-08-06 إلى 2026-11-04 | 286 | 6، كلها للوثائق (5.0.0 على سجل منفصل) | 6 | 31 | 0 | 23 |
| أحدث إصدار | v1.64.0، 2026-11-04 | 5.0.0، 2026-07-25 | 3.0.0-beta.9، 2026-09-23 | لا توجد إصدارات مرقّمة | v1.10، 2024-07-17 | 2.0.6، 2026-11-03 |
| الاتصالات الصادرة بخلاف التطبيقات | إصدارات GitHub مرة يوميًا (يوقفه `CASHPILOT_UPDATE_CHECK=off`، [الكود][cp-update])؛ و`api.ipify.org` أو `ifconfig.me` أو `icanhazip.com` مرة كل ساعة من كل عامل، لمعرفة عنوان IP العام الخاص به (يوقفه `CASHPILOT_EGRESS_DETECT=off`، [الكود][cp-egress])؛ وCoinGecko وFrankfurter لأسعار الصرف ([الكود][cp-rates])؛ وmempool.space وapi.kaspa.org وعُقد RPC العامة لـ Ethereum وPolygon وSolana من أجل [الأرصدة على السلسلة](onchain.md)؛ وكل مزوّد، من أجل المُجمِّعات. ويحمّل المتصفح Google Fonts ([القالب][cp-cdn]) وChart.js من jsDelivr ([القالب][cp-chartjs]) | إصدارات GitHub، لفحص التحديثات ([الكود][m4b-updater])؛ وDocker Hub وghcr.io، لفحص وسوم صور الحاويات ([الكود][m4b-registry])؛ وعند تشغيل فحص IP، `api.ipify.org` أو `ifconfig.me` أو `icanhazip.com` لمعرفة عنوان IP العام و`ip-api.com` عبر HTTP العادي لتقييمات IP ([الكود][m4b-ipscore]) | إصدارات GitHub ([الكود][igm-version])؛ و`api.ipify.org` أو `ifconfig.me` أو `icanhazip.com` لمعرفة عنوان IP العام ([الكود][igm-ifconfig])؛ و`ip-api.com` عبر HTTP العادي لتقييمات IP ([الكود][igm-ipscore]). لم يُفحص الملف التنفيذي المغلق | لم نجد شيئًا | لم نجد شيئًا | لم نجد شيئًا |

لا يرسل أي من المشاريع بيانات قياس عن بُعد (telemetry) للاستخدام في الكود الذي قرأناه. ولم يكن ممكنًا قراءة الملف التنفيذي المغلق لـ IGM.

كل مشروع هنا يمرّر بيانات اعتماد التطبيقات إلى الحاويات بوصفها متغيرات بيئة، ويمرّر InternetIncome بعضها بوصفها وسائط أوامر أيضًا، لذلك تكون على المضيف الذي يشغّل التطبيقات نصًا عاديًا في إعدادات الحاوية لدى Docker (`Env` و`Args` في `docker inspect`)، يستطيع قراءتها أي شخص لديه وصول إلى Docker. ولا يصف صف "بيانات الاعتماد في حالة السكون" إلا النسخة المخزّنة.

## كيف أحصينا { #how-we-counted }

- **CashPilot.** الخدمات الموجودة في الكتالوج بالحالة active أو beta ولها صورة حاوية Docker، دون احتساب حوسبة GPU أو مجمّعات التعدين. يأتي الرقم في هذه الصفحة من `scripts/generate_readme_tables.py`، ويفشل CI إذا انحرف.
- **money4band 5.0.0.** ملف JSON واحد لكل تطبيق في `config/catalog/supported/`: 15. أما "35 تطبيقًا" في README فتحتسب أيضًا كتالوج المجتمع، المعطّل افتراضيًا ([الإعدادات][m4b-community])، والتطبيقات التي لا صورة Docker لها، والتطبيقات المُسقطة.
- **IGM.** الإدخالات في `apps.json`: 20، كلها مفعّلة. ولا تُحتسب حاوية البروكسي وWatchtower والحاويات الجانبية للمطالبة.
- **InternetIncome.** كل كتلة تعليق `# Starting ... container` في `internetIncome.sh`، بخلاف كتلتي البروكسي وWatchtower: 24. كتلتا Chrome وFirefox الخاصتان بـ Ebesucher تطبيق واحد، وكذلك EarnFM وEarnFM Fleetshare، اللذان يستخدمان حساب EarnFM نفسه. وتشغّل كتلة إضافات Depin كلًّا من Grass وGradient ([السكربت][ii-depin])، أي تطبيقين. المجموع 23. ويسرد جدول README سبعة وعشرين تطبيقًا، بعضها برابط تسجيل فقط.
- **CashFactory.** خدمات الكسب في `docker-compose.yml`: 11. ولا تُحتسب Portainer وخادم الويب وحاويتا Watchtower. وهناك خدمة واحدة معلَّقة بتعليق.
- **إضافات HA.** مجلدات الإضافات التي فيها ملف إعدادات: 10.

لم نتحقق مما إذا كان كل تطبيق في كل قائمة لا يزال يدفع.

## أين يتأخر CashPilot { #where-cashpilot-is-behind }

- لا يمكن تشغيل الخدمات التي تحتاج إلى شبكة المضيف أو منافذ منشورة أو وحدات تخزين أو أجهزة أو صلاحيات شبكة إضافية عبر بروكسي، لذلك فإن 10 من الـ <!-- n:docker -->21<!-- /n --> (EarnApp وURnetwork وProxyBase Markets وBitping وMysterium وStorj وSia وAnyone Protocol وSRBMiner-Multi وKryptex Pool (Pearl)) لا تكسب إلا من عنوان IP الخاص بالخادم نفسه ([النسخ عبر بروكسي](proxies.md#what-cannot-run-through-a-proxy)).
- عدد التطبيقات التي يشغّلها بنفسه أقل مما في InternetIncome.
- لا مطالبة بالمكافآت اليومية ولا تحديثات تلقائية لصور الحاويات.
- 12 من صور تطبيقات الربح الـ <!-- n:docker -->21<!-- /n --> عائمة على أحدث وسم لدى ناشرها.
- وكيل المقبس ليس بعد حدًّا فاصلًا لصلاحيات root: فالعامل المخترَق لا يزال يستطيع إنشاء حاويات ضمن سياسته، ولا تُرفض عمليات الهروب ذات الخطوتين (الانضمام إلى نطاق أسماء العمليات لحاوية أخرى، أو رابط رمزي في مجلد مسموح به) ([التفاصيل](security-defaults.md)).
- يقع مفتاح تشفير بيانات الاعتماد المخزّنة في وحدة التخزين نفسها التي تقع فيها البيانات، وعلى كل عامل تكون بيانات اعتماد تطبيقات الربح نصًا عاديًا في إعدادات الحاوية لدى Docker.
- يحتاج بعض المُجمِّعات إلى ملف تعريف ارتباط أو رمز منسوخ من المتصفح، وتنتهي صلاحية بعض هذه، لذلك يحتاج تتبّع الأرباح إلى صيانة لتلك الخدمات.
- تحمّل الواجهة الخطوط وChart.js من شبكات CDN تابعة لجهات خارجية.
- يبقى العزل عن الشبكة المحلية معطّلًا في التثبيت المرقّى الذي تقع تطبيقات الربح فيه على الجسر الافتراضي لـ Docker إلى أن تشغّله، ولا يوفّر أي حاجز لشبكة مسمّاة في `CASHPILOT_CONTAINER_NETWORK` ([العزل](isolation.md#modes))، أما عقدة Mysterium المنشورة حتى الإصدار 2.0.6 فتبقى على شبكة المضيف، بلا حاجز، إلى أن تعيد نشرها ([Mysterium خلف الحاجز](mysterium-fence.md)).
- مجتمع أصغر بكثير من مجتمع money4band.
- يصدر إصدارات كثيرة، أحيانًا عدة مرات في اليوم.

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

[cp-payouts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L515-L531
[cp-fernet]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/database.py#L48
[cp-hardening]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/orchestrator.py#L745-L752
[cp-privileged]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L1244
[cp-mounts]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L992-L1040
[cp-myst]: https://github.com/GeiserX/CashPilot/blob/01e7310cf1d923ba35523d8944ebaf2478f39079/services/bandwidth/mysterium.yml#L19-L113
[cp-sock]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/docker-compose.yml#L69-L106
[cp-update]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/update_check.py#L80
[cp-rates]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/exchange_rates.py#L101-L119
[cp-egress]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/worker_api.py#L313
[cp-cdn]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L12-L16
[cp-chartjs]: https://github.com/GeiserX/CashPilot/blob/c7a12bd4a1e5ce06f5be0ad303afc14c28ec17b8/app/templates/base.html#L254
[cp-proxy-deploy]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/proxy_tunnel.py#L336-L350
[cp-tunnel-fw]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/tunnel/cp-tunnel#L48-L99
[cp-fence]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L83-L100
[cp-fence-mode]: https://github.com/GeiserX/CashPilot/blob/0170deec45c1a5fe6e72682b94adc07e5878d2bf/app/lan_fence.py#L630-L646
