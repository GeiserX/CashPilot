---
source_hash: ca9dd25d45ca
---
# الانتقال من InternetIncome { #moving-from-internetincome }

يستطيع CashPilot قراءة ملف `properties.conf` الخاص بـ InternetIncome، والملفات التي
يحتفظ فيها بمعرّفات أجهزتك في EarnApp وProxyRack، ونقلها. وأنت تراجع
كل شيء قبل أن يحفظه CashPilot.

## قبل أن تبدأ { #before-you-start }

تحتاج إلى حساب المالك في CashPilot وإلى عامل CashPilot واحد على الأقل.

أوقف InternetIncome على الجهاز قبل أن تنشر الخدمات نفسها هناك من
CashPilot. فنسختان خلف اتصال واحد تكسبان كنسخة واحدة، ولا يجوز تشغيل معرّف الجهاز نفسه
مرتين. في مجلد InternetIncome، شغّل:

```bash
sudo bash internetIncome.sh --delete
```

يزيل `--delete` الحاويات ويُبقي `earnapp.txt` و`proxyrack.txt` و
مجلد بيانات Mysterium. أما `--deleteBackup` فيزيلها هي أيضًا
([internetIncome.sh، الأسطر من 61 إلى 64](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L61-L64)
و[السطر 1562](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1562))،
لذلك استورد أولًا.

## أي ملفات تستخدم { #which-files-to-use }

من مجلد InternetIncome:

- `properties.conf`، وهو إعداداتك.
- `earnapp.txt`، إذا كنت تشغّل EarnApp. يحتوي كل سطر على رابط جهاز
  ([الأسطر من 1250 إلى 1261](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1250-L1261)).
- `proxyrack.txt`، إذا كنت تشغّل ProxyRack. UUID جهاز واحد في كل سطر
  ([الأسطر من 817 إلى 827](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L817-L827)).

يأخذ CashPilot أول جهاز في كل ملف: الجهاز الذي استخدمته حاويتك الرئيسية
والجهاز الذي ربطته بحسابك. أما الأسطر الأخرى فكانت تخص نسخ
البروكسي، وتخبرك الصفحة بعدد ما استبعده منها.

يمرّر InternetIncome كل قيمة عبر الصدفة (shell)
([السطر 1375](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/internetIncome.sh#L1375)).
والقيمة المحاطة بعلامات اقتباس مفردة تؤخذ كما كُتبت، كما تنصح التعليقات في
[properties.conf](https://github.com/engageub/InternetIncome/blob/db9338ab5a77539db8420476742af647b6cf82e5/properties.conf).
أما القيمة غير المحاطة بعلامات اقتباس مفردة والتي تحتوي على `$`، أو علامة backtick، أو مسافة، أو
حرف آخر قد تغيّره الصدفة، فليست كما يعرضها الملف، لذلك
يطلب منك CashPilot إعادة كتابتها بدلًا من تشغيل صدفة لمعرفة القيمة.

## طريقة الاستيراد { #how-to-import }

1. افتح **Settings** (الإعدادات)، ثم **Import from another tool** (الاستيراد من أداة أخرى) (أو انتقل إلى `/import`).
2. أضف `properties.conf`، إضافةً إلى `earnapp.txt` و`proxyrack.txt` إذا كانا
   لديك. اترك الأداة على "Tell from the files" (الاستنتاج من الملفات)، أو اختر InternetIncome.
3. راجع الجدول. حدّد الخدمات التي تريدها واملأ أي قيمة معلَّمة بأنها
   ناقصة. يحتاج Repocket إلى البريد الإلكتروني لحسابك، الذي لم يطلبه InternetIncome
   قط.
4. اضغط **Save the ticked services** (حفظ الخدمات المحدّدة)، ثم انشرها على عمّالك من
   الصفحة نفسها.

## ما الذي يُنقل { #what-comes-over }

| تطبيق InternetIncome | المفاتيح المقروءة | خدمة CashPilot | ما الذي يُنقل |
|---|---|---|---|
| `repocket` | `REPOCKET_API` | Repocket | مفتاح API (أضف بريدك الإلكتروني) |
| `traffmonetizer` | `TRAFFMONETIZER_TOKEN` | Traffmonetizer | الرمز (token) |
| `proxybase` | `PROXYBASE_ACCOUNT_ID` | ProxyBase | Access Token |
| `proxyrack` | `PROXYRACK_API`، `proxyrack.txt` | ProxyRack | مفتاح API، UUID الجهاز |
| `iproyals` | `IPROYALS_EMAIL`، `IPROYALS_PASSWORD` | IPRoyal Pawns | البريد الإلكتروني، كلمة المرور |
| `honeygain` | `HONEYGAIN_EMAIL`، `HONEYGAIN_PASSWORD` | Honeygain | البريد الإلكتروني، كلمة المرور |
| `packetstream` | `PACKETSTREAM_CID` | PacketStream | CID |
| `proxylite` | `PROXYLITE_USER_ID` | ProxyLite | معرّف المستخدم |
| `earnfm` | `EARN_FM_API` | Earn.fm | مفتاح API |
| `earnapp` | `EARNAPP=true`، `earnapp.txt` | EarnApp | معرّف الجهاز |
| `bitping` | `BITPING_EMAIL`، `BITPING_PASSWORD` | Bitping | البريد الإلكتروني، كلمة المرور |
| `mysterium` | `MYSTERIUM=true` | Mysterium | يُفعَّل؛ راجع ملاحظة Mysterium أدناه |

القيمة الفارغة تعني أن التطبيق كان معطّلًا، ولا يُدرج.

هذه التطبيقات مدرجة لكنها لا تُنقل:

| تطبيق InternetIncome | السبب |
|---|---|
| `urnetwork` | يستخدم InternetIncome رمز جلسة. أما CashPilot فيسجّل الدخول إلى URnetwork ببريدك الإلكتروني وكلمة مرورك. |
| `grass` | يعمل Grass كإضافة متصفح. ولا يفعل CashPilot إلا تتبّعه، برمز الوصول من لوحة تحكم Grass. |
| `titan`، `ebesucher`، `wipter` | يتتبّع CashPilot هذه التطبيقات، لكن لا توجد حاوية لنشرها. |
| `peer2profit` | لم تعد متاحة. |

إعدادات التطبيقات التي لا يملكها CashPilot (antGain وAdnade وغيرهما)
تُدرج بأسمائها على أنها لم تُقرأ.

## ما الذي لا يُنقل أبدًا { #what-never-comes-over }

- **`DEVICE_NAME`.** يسمّي CashPilot كل جهاز باسم العامل الذي يعمل عليه، لذلك
  لا يبلّغ عاملان أبدًا عن الاسم نفسه. وتبقى أجهزتك القديمة مدرجة على أنها
  غير متصلة في لوحة تحكم كل مزوّد إلى أن تزيلها هناك.
- **البروكسيات** (`USE_PROXIES`، `proxies.txt`). أضف كلًّا منها في قسم **Proxies** (البروكسيات)
  في صفحة **Fleet** (الأسطول)، ثم شغّل نسخًا من خدماتك عبره؛ فإضافة
  بروكسي لا تشغّل شيئًا بمفردها. ومع `USE_PROXIES=true` كان InternetIncome يشغّل
  خدماتك عبر البروكسيات فقط. وحفظ الاستيراد لا يشغّل شيئًا أيضًا. تحتاج
  النسخة عبر بروكسي إلى أن تكون الخدمة نفسها منشورة على العامل أولًا، و
  نشرها يشغّلها على اتصال العامل نفسه، لذلك يجب أن تبقى غير محدَّدة الخدمةُ التي يجب
  ألا تستخدم ذلك الاتصال أبدًا. راجع [النسخ عبر
  بروكسي](../proxies.md).
- **`BROWSER_USERNAME` و`BROWSER_PASSWORD`**، وهما بيانات تسجيل الدخول إلى المتصفح الخاص
  بـ InternetIncome.

## تتبّع الأرباح { #earnings-tracking }

بالنسبة إلى Honeygain وIPRoyal Pawns وBitping، تسجيل الدخول في الحاوية هو أيضًا
تسجيل الدخول إلى الحساب، لذلك يملأ CashPilot بيانات اعتماد الأرباح لها أيضًا، إلا إذا كنت
قد ضبطتها بالفعل في **Settings** (الإعدادات). ولكل خدمة أخرى، أضف بيانات تسجيل الدخول للأرباح
في **Settings > Earnings collection** (الإعدادات > جمع الأرباح).

## Mysterium { #mysterium }

يفعّل الاستيراد Mysterium، لكن CashPilot يبدأ عقدة جديدة بهوية
جديدة. ويبقى مخزن المفاتيح الخاص بالعقدة القديمة وأي أرباح غير مسوّاة في مجلد
`mysterium-data` الخاص بـ InternetIncome. سوِّها أولًا، أو اتبع
[دليل Mysterium](../guides/mysterium.md) لنقل الهوية.

## الأمان { #safety }

- لا يُشغَّل أي شيء في الملفات ولا يُوسَّع، ولا يُجلب أي عنوان فيها.
- تُقرأ الملفات مرة واحدة ولا يُحتفظ بها. وما تحفظه يُخزَّن مشفّرًا، مثل
  كل بيانات الاعتماد الأخرى في CashPilot.
- لا تُعرض الأسرار في الصفحة إلا بالكلمة "set" (مضبوط).
- تبقى عمليات الاستيراد المحفوظة في صفحة الاستيراد إلى أن تضغط **Forget** (نسيان)، حتى تستطيع
  نشرها على عمّال آخرين لاحقًا.
