---
source_hash: 098dcc2576d9
---
# الانتقال من money4band { #moving-from-money4band }

يستطيع CashPilot قراءة إعدادات money4band ونقل بيانات تسجيل الدخول إلى خدماتك، حتى
لا تكتبها مرة أخرى. وأنت تراجع كل شيء قبل أن يحفظه CashPilot.

## قبل أن تبدأ { #before-you-start }

تحتاج إلى حساب المالك في CashPilot وإلى عامل CashPilot واحد على الأقل على
الجهاز الذي يعمل عليه money4band الآن، أو على جهاز آخر.

أوقف money4band على الجهاز قبل أن تنشر الخدمات نفسها هناك من
CashPilot. فنسختان خلف اتصال واحد تكسبان كنسخة واحدة، ولا يجوز تشغيل معرّف الجهاز نفسه
في EarnApp أو ProxyRack مرتين. استخدم **Stop apps stack** في
قائمة money4band
([m4b-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/m4b-config.json))،
أو شغّل `docker compose down` في مجلده. وإذا كنت قد أعددت نسخ بروكسي
إضافية، فأوقف كلًّا منها أيضًا.

## أي ملف تستخدم { #which-file-to-use }

استخدم `config/user-config.json` في مجلد money4band الخاص بك. وتعتمد طريقة إيصاله إلى
CashPilot على إصدار money4band لديك.

في money4band 4.x، يكتب money4band الملف عندما تشغّل **Setup Apps**، وهو يحتوي بالضبط
على ما كتبته. أما ملف `.env` بجانبه فمُولَّد من ذلك الملف ويعمل أيضًا، وكذلك ملف `.env`
المعدَّل يدويًا في money4band 3.x. يبقى كلاهما على قرصك فقط: إذ يدرجهما ملف
[.gitignore](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/.gitignore)
الخاص بـ money4band.

يشفّر money4band 5.0 الملف `config/user-config.json` على القرص
([ملاحظات الأمان](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/security.md#credential-encryption))،
ويحذف ملف `.env` الخاص به بعد كل تشغيل
([مُنشئ env](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/money4band/docker/env_builder.py#L5-L11)).
لا يستطيع CashPilot قراءة الملف المشفّر. شغّل `m4b config edit` في مجلد money4band
الخاص بك: يفتح هذا الأمر الملف بعد فك تشفيره في محرّرك
([مرجع CLI](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/docs/cli-reference.md#config-edit)).
انسخ نصه كله، والصقه في صفحة **Import from another tool** (الاستيراد من أداة أخرى)، ثم أغلق المحرّر.

فضّل ملف JSON. ففي ملف `.env`، يوسّع Docker Compose الرمز `$` في القيم غير المحاطة بعلامات اقتباس،
لذلك فإن كلمة المرور التي تحتوي على `$` ليست كما يعرضها الملف. لا يخمّن CashPilot:
بل يطلب منك إعادة كتابة تلك القيمة.

## طريقة الاستيراد { #how-to-import }

1. افتح **Settings** (الإعدادات)، ثم **Import from another tool** (الاستيراد من أداة أخرى) (أو انتقل إلى `/import`).
2. أضف `user-config.json`، أو الصق نصه. اترك الأداة على "Tell from the
   files" (الاستنتاج من الملفات)، أو اختر money4band.
3. راجع الجدول. حدّد الخدمات التي تريدها واملأ أي قيمة معلَّمة بأنها
   ناقصة.
4. اضغط **Save the ticked services** (حفظ الخدمات المحدّدة)، ثم انشرها على عمّالك من
   الصفحة نفسها.

## ما الذي يُنقل { #what-comes-over }

تأتي أسماء الحقول من
[قالب user-config](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/template/user-config.json)
في money4band، ومن أسماء `.env` التي يكتبها
[المولّد](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/utils/generator.py#L535-L545)
الخاص به (`<APP>_<FLAG>`، مثل `REPOCKET_APIKEY`). ويحتفظ money4band 5.0 بأسماء الحقول
نفسها في
[كتالوج التطبيقات](https://github.com/MRColorR/money4band/blob/af9d903e1908f5e7fc205ab6871bad2e0ca51f28/config/catalog/supported)
الخاص به.

| تطبيق money4band | خدمة CashPilot | ما الذي يُنقل |
|---|---|---|
| `earnapp` | EarnApp | معرّف الجهاز (`uuid`)، حتى يستمر جهازك المرتبط في الكسب |
| `honeygain` | Honeygain | البريد الإلكتروني، كلمة المرور |
| `iproyalpawns` | IPRoyal Pawns | البريد الإلكتروني، كلمة المرور |
| `packetstream` | PacketStream | CID |
| `traffmonetizer` | Traffmonetizer | الرمز (token) |
| `repocket` | Repocket | البريد الإلكتروني، مفتاح API |
| `earnfm` | Earn.fm | مفتاح API |
| `proxyrack` | ProxyRack | مفتاح API، UUID الجهاز |
| `proxylite` | ProxyLite | معرّف المستخدم |
| `bitping` | Bitping | البريد الإلكتروني، كلمة المرور |
| `mystnode` | Mysterium | يُفعَّل؛ راجع ملاحظة Mysterium أدناه |

التطبيق الذي عطّلته في money4band يظهر غير محدَّد. أما التطبيق المعطّل الذي
لا يحتوي إلا على العناصر النائبة في القالب (`yourHONEYGAINMail`) وقوائم المنافذ
فيُستبعد، لذلك فإن ملف `user-config.json` الذي لم يُلمس يعطي جدولًا فارغًا.

هذه التطبيقات مدرجة لكنها لا تُنقل:

| تطبيق money4band | السبب |
|---|---|
| `proxybase` | يشغّل money4band العميل القديم لـ ProxyBase بمعرّف مستخدم. أما CashPilot فيشغّل العميل الحالي، الذي يحتاج إلى Access Token من proxybase.org. |
| `urnetwork` | يحتفظ money4band برمز جلسة. أما CashPilot فيسجّل الدخول إلى URnetwork ببريدك الإلكتروني وكلمة مرورك. |
| `grass` | يعمل Grass كإضافة متصفح. ولا يفعل CashPilot إلا تتبّعه، برمز الوصول من لوحة تحكم Grass. |
| `gradient`، `dawn`، `teneo`، `titan`، `spide`، `wipter` | يتتبّع CashPilot هذه التطبيقات، لكن لا توجد حاوية لنشرها. |
| `packetshare`، `peer2profit`، `speedshare` | لم تعد متاحة. |

وأي تطبيق آخر يُدرج بالعبارة "CashPilot has no such service" (لا توجد لدى CashPilot خدمة كهذه).

## ما الذي لا يُنقل أبدًا { #what-never-comes-over }

- **اسم الجهاز.** يسمّي CashPilot كل جهاز باسم العامل الذي يعمل عليه، لذلك
  لا يبلّغ عاملان أبدًا عن الاسم نفسه. وتبقى أجهزتك القديمة مدرجة على أنها
  غير متصلة في لوحة تحكم كل مزوّد إلى أن تزيلها هناك.
- **البروكسيات.** أضف كلًّا منها في قسم **Proxies** (البروكسيات) في صفحة **Fleet** (الأسطول)، ثم شغّل
  نسخًا من خدماتك عبره؛ فإضافة بروكسي لا تشغّل شيئًا بمفردها.
  وحفظ الاستيراد لا يشغّل شيئًا أيضًا. تحتاج النسخة عبر بروكسي إلى أن تكون الخدمة نفسها
  منشورة على العامل أولًا، ونشرها يشغّلها على اتصال العامل نفسه،
  لذلك يجب أن تبقى غير محدَّدة الخدمةُ التي يجب ألا تستخدم ذلك الاتصال أبدًا. راجع [النسخ عبر بروكسي](../proxies.md).
- **Watchtower والإشعارات.** يحدّث CashPilot حاوياته بنفسه.
- **لوحة تحكم money4band ومنافذها.**

## تتبّع الأرباح { #earnings-tracking }

بالنسبة إلى Honeygain وIPRoyal Pawns وBitping، تسجيل الدخول في الحاوية هو أيضًا
تسجيل الدخول إلى الحساب، لذلك يملأ CashPilot بيانات اعتماد الأرباح لها أيضًا، إلا إذا كنت
قد ضبطتها بالفعل في **Settings** (الإعدادات). ولكل خدمة أخرى، أضف بيانات تسجيل الدخول للأرباح
في **Settings > Earnings collection** (الإعدادات > جمع الأرباح).

## Mysterium { #mysterium }

يفعّل الاستيراد Mysterium، لكن CashPilot يبدأ عقدة جديدة بهوية
جديدة. ويبقى مخزن المفاتيح الخاص بالعقدة القديمة وأي أرباح غير مسوّاة في مجلد
`.data/mysterium-node` الخاص بـ money4band
([app-config.json](https://github.com/MRColorR/money4band/blob/3bfafb1d9a738aac11f2049d6f2c3515ff783bb8/config/app-config.json)). سوِّها أولًا، أو اتبع
[دليل Mysterium](../guides/mysterium.md) لنقل الهوية.

لا يستطيع ملف `.env` من الإصدار 3.x أن يبيّن هل كنت تشغّل Mysterium: فقالبه يدرج
دائمًا منفذ لوحة التحكم. لذلك لا يُستورد Mysterium من ملف 3.x، فأضفه
من الكتالوج إذا كنت تشغّله.

## الأمان { #safety }

- لا يُشغَّل أي شيء في الملف ولا يُوسَّع، ولا يُجلب أي عنوان فيه.
- يُقرأ الملف مرة واحدة ولا يُحتفظ به. وما تحفظه يُخزَّن مشفّرًا، مثل
  كل بيانات الاعتماد الأخرى في CashPilot.
- لا تُعرض الأسرار في الصفحة إلا بالكلمة "set" (مضبوط).
- تبقى عمليات الاستيراد المحفوظة في صفحة الاستيراد إلى أن تضغط **Forget** (نسيان)، حتى تستطيع
  نشرها على عمّال آخرين لاحقًا.
