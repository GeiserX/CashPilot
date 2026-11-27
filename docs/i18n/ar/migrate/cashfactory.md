---
source_hash: 7f8476aeb8b6
---
# الانتقال من CashFactory { #moving-from-cashfactory }

يستطيع CashPilot قراءة ملف `.env` الخاص بـ CashFactory ونقل بيانات تسجيل الدخول إلى خدماتك، حتى
لا تكتبها مرة أخرى. وأنت تراجع كل شيء قبل أن يحفظه CashPilot.

## قبل أن تبدأ { #before-you-start }

تحتاج إلى حساب المالك في CashPilot وإلى عامل CashPilot واحد على الأقل.

أوقف CashFactory على الجهاز قبل أن تنشر الخدمات نفسها هناك من
CashPilot. فنسختان خلف اتصال واحد تكسبان كنسخة واحدة، ولا يجوز تشغيل معرّف الجهاز نفسه
في EarnApp مرتين. شغّل `docker compose down` في مجلد CashFactory.
كما يشغّل
[ملف compose](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/docker-compose.yml)
الخاص به ثلاث حاويات تركّب مقبس Docker: Portainer (السطر 31)
وحاويتي Watchtower (السطران 141 و264). تأكّد من أنها أُزيلت أيضًا: يجب ألا يدرج `docker ps`
أيًّا منها.

## أي ملف تستخدم { #which-file-to-use }

استخدم ملف `.env` في مجلد CashFactory الخاص بك، وهو الملف الذي ملأته انطلاقًا من
[النموذج](https://github.com/OlivierGaland/CashFactory/blob/0ff4bd0c3b020d82c91e095db43ba5c9e356ac94/.env).

يقرأ Docker Compose ذلك الملف، ويوسّع الرمز `$` في القيم غير المحاطة
بعلامات اقتباس مفردة. والقيمة من هذا النوع ليست كما يعرضها الملف، لذلك يطلب منك CashPilot
إعادة كتابتها بدلًا من التخمين.

## طريقة الاستيراد { #how-to-import }

1. افتح **Settings** (الإعدادات)، ثم **Import from another tool** (الاستيراد من أداة أخرى) (أو انتقل إلى `/import`).
2. أضف ملف `.env`، أو الصق نصه. اترك الأداة على "Tell from the
   files" (الاستنتاج من الملفات)، أو اختر CashFactory.
3. راجع الجدول. حدّد الخدمات التي تريدها واملأ أي قيمة معلَّمة بأنها
   ناقصة.
4. اضغط **Save the ticked services** (حفظ الخدمات المحدّدة)، ثم انشرها على عمّالك من
   الصفحة نفسها.

## ما الذي يُنقل { #what-comes-over }

| تطبيق CashFactory | المفاتيح المقروءة | خدمة CashPilot | ما الذي يُنقل |
|---|---|---|---|
| `earnapp` | `EARNAPP_DEVICE_ID` | EarnApp | معرّف الجهاز، حتى يستمر جهازك المرتبط في الكسب |
| `honeygain` | `HONEYGAIN_EMAIL`، `HONEYGAIN_PASSWD` | Honeygain | البريد الإلكتروني، كلمة المرور |
| `iproyalpawns` | `IPROYALPAWNS_EMAIL`، `IPROYALPAWNS_PASSWD` | IPRoyal Pawns | البريد الإلكتروني، كلمة المرور |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | الرمز (token) |
| `repocket` | `RP_EMAIL`، `RP_API_KEY` | Repocket | البريد الإلكتروني، مفتاح API |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | معرّف المستخدم |
| `proxyrack` | `PROXYRACK_HOST_UUID` | ProxyRack | UUID الجهاز |
| `earnfm` | `EARNFM_APIKEY` | Earn.fm | مفتاح API |
| `peer2profit` | `PEER2PROFIT_EMAIL` | Peer2Profit | لا شيء: لم تعد متاحة |

القيمة التي لا تزال تعرض العنصر النائب من النموذج (`<email>`، `sdk-node-<md5sum>`)
تُعدّ غير مضبوطة، والخدمة التي لا تحتوي إلا على عناصر نائبة تُستبعد من
الجدول.

## ما الذي لا يُنقل أبدًا { #what-never-comes-over }

- **`DEVICE_NAME`.** يسمّي CashPilot كل جهاز باسم العامل الذي يعمل عليه، لذلك
  لا يبلّغ عاملان أبدًا عن الاسم نفسه. وتبقى أجهزتك القديمة مدرجة على أنها
  غير متصلة في لوحة تحكم كل مزوّد إلى أن تزيلها هناك.
- **Bitping.** يحتفظ CashFactory ببيانات تسجيل الدخول إلى Bitping في وحدة تخزين Docker، لا في
  `.env`، لذلك لا يجد الاستيراد شيئًا ليقرأه ولا يعرض صفًا لـ Bitping. اكتب
  بيانات تسجيل الدخول في نموذج نشر Bitping.
- **Portainer وWatchtower.** يدير CashPilot حاوياته ويحدّثها بنفسه.

## تتبّع الأرباح { #earnings-tracking }

بالنسبة إلى Honeygain وIPRoyal Pawns، تسجيل الدخول في الحاوية هو أيضًا تسجيل الدخول إلى الحساب،
لذلك يملأ CashPilot بيانات اعتماد الأرباح لهما أيضًا، إلا إذا كنت قد ضبطتها
بالفعل في **Settings** (الإعدادات). ولكل خدمة أخرى، أضف بيانات تسجيل الدخول للأرباح في
**Settings > Earnings collection** (الإعدادات > جمع الأرباح).

## الأمان { #safety }

- لا يُشغَّل أي شيء في الملف ولا يُوسَّع، ولا يُجلب أي عنوان فيه.
- يُقرأ الملف مرة واحدة ولا يُحتفظ به. وما تحفظه يُخزَّن مشفّرًا، مثل
  كل بيانات الاعتماد الأخرى في CashPilot.
- لا تُعرض الأسرار في الصفحة إلا بالكلمة "set" (مضبوط).
- تبقى عمليات الاستيراد المحفوظة في صفحة الاستيراد إلى أن تضغط **Forget** (نسيان)، حتى تستطيع
  نشرها على عمّال آخرين لاحقًا.
