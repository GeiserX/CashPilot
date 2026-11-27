---
source_hash: e99e2c0c80bb
---
# متاجر التطبيقات { #app-stores }

يمكنك تثبيت CashPilot من متجر التطبيقات في عدة أنظمة للخوادم المنزلية.
يثبّت كل إدراج لوحة التحكم (`drumsergio/cashpilot`) والعامل
(`drumsergio/cashpilot-worker`) الذي يشغّل حاويات الخدمات ويوقفها.
حزمتا CasaOS وRuntipi في هذا المستودع هما وحدهما اللتان تثبّتان أيضًا
وكيل مقبس Docker من `docker-compose.yml`، لذلك لا يحمل العامل فيهما
مقبس Docker الخام أبدًا. أما قوالب Unraid وتطبيق TrueNAS والحزمة الموجودة
في طلب السحب المفتوح لمتجر تطبيقات CasaOS فلا تزال تركّب مقبس Docker
في العامل مباشرةً.

أيًّا كان المتجر الذي تستخدمه، أبقِ لوحة التحكم على شبكتك المحلية (LAN) أو شبكة VPN. فهي تستطيع إصدار أوامر
إلى العامل، والعامل يتحكم في Docker على المضيف. وحيث يحمل العامل
المقبس بنفسه، يعني ذلك صلاحيات root على المضيف.

## المُدرَجة حاليًا { #listed-today }

### Unraid Community Applications { #unraid-community-applications }

ابحث عن **CashPilot** في تبويب Apps وثبّت القالبين كليهما:
`cashpilot` (لوحة التحكم) و`cashpilot-worker`. اضبط القيمة نفسها لـ
`CASHPILOT_API_KEY` على كليهما.

تأتي القوالب من https://github.com/GeiserX/docker-templates وتتبع
وسم صورة الحاوية `latest`، لذلك يحصل مستخدمو Community Applications على كل إصدار
دون تغيير في القالب.

### TrueNAS SCALE { #truenas-scale }

يوجد CashPilot في قناة **community** الخاصة بـ TrueNAS. افتح Apps، ثم Discover Apps،
وابحث عن **CashPilot**.

يُحافَظ على تعريف التطبيق في
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot وهو يثبّت
بصمة (digest) دقيقة لصورة الحاوية. تنقله روبوتات TrueNAS نفسها إلى الإصدارات الجديدة، لذلك قد يكون
متأخرًا ببضعة إصدارات عن أحدث إصدار من CashPilot.

## بانتظار المراجعة { #waiting-for-review }

### CasaOS { #casaos }

طلب سحب إلى متجر تطبيقات CasaOS مفتوح حاليًا:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

إلى أن يُدمج، ثبّته كتطبيق مخصّص: في CasaOS اختر App Store،
ثم Custom Install، ثم Import، والصق محتويات
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

يحتاج إلى CasaOS 0.4.5 أو أحدث: فابتداءً من ذلك الإصدار يُبنى مدير التطبيقات فيه على
Docker Compose 2.23، الذي يقرأ سياسة وكيل المقبس من الملف.
أما الإصدارات الأقدم فتُسقطها، وعندها لا يستطيع العامل الوصول إلى Docker.

يثبّت ذلك الملف إصدارًا دقيقًا. قبل أن تستورده، اضبط وسمَي صورتي الحاوية كليهما
(`drumsergio/cashpilot` و`drumsergio/cashpilot-worker`) على أحدث
إصدار من https://github.com/GeiserX/CashPilot/releases. تتبع سياسة الوكيل
في الملف الفرع `main`؛ إذا قالت صفحة حالة العامل إن سياسته
قديمة، فاستورد الملف مرة أخرى.

## جاهزة، ولم تُقدَّم بعد { #prepared-not-yet-submitted }

### Runtipi { #runtipi }

الحزمة جاهزة في
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
لكنها ليست بعد في متجر تطبيقات Runtipi. لاستخدامها الآن، أضفها إلى متجر تطبيقات
مخصّص تتحكم فيه، باتّباع وثائق Runtipi:
https://runtipi.io/docs/guides/create-your-own-app-store

## غير متاحة { #not-offered }

يحتاج Umbrel إلى تصميم مختلف للعامل، لأن تطبيقات Umbrel تصل إلى Docker
عبر حاوية Docker-in-Docker بدلًا من مقبس المضيف. لم نختبر ذلك،
لذلك لا توجد حزمة لـ Umbrel بعد.

لأي نظام آخر، استخدم `docker-compose.yml` من المستودع، كما في
[البدء](getting-started.md).
