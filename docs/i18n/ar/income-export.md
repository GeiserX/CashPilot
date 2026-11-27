---
source_hash: 38029ca1a5d6
---
# تصدير الدخل للضرائب { #income-export-for-taxes }

افتح **Payouts** (الدفعات)، وابحث عن **Income for taxes** (الدخل للضرائب)، واختر نطاقًا زمنيًا وعملة. يمتد **This year** (هذا العام) حتى اليوم، ويغطي **Last year** (العام الماضي) السنة التقويمية السابقة. اترك التاريخين فارغين لتصدير السجل المتاح حتى اليوم. يستخدم CashPilot تواريخ UTC ويشمل طرفي النطاق كليهما.

يحذف CashPilot قراءات الأرباح بعد 400 يوم من تسجيلها. ويستخدم ملف CSV السجل المتبقي، لذلك قد لا تحتوي سنة ماضية إلا على جزء من دخلها المكتسب أو المستحق.

## اختر أساسًا محاسبيًا { #choose-an-accounting-basis }

- **الأساس النقدي.** استخدم صفوف الدفعات. فهي تسجّل المال الذي دفعته الخدمة. ولا يتضمن CashPilot إلا الدفعات المؤكَّدة.
- **أساس الاستحقاق.** استخدم الصفوف المكتسبة والمستحقة. تعرض الصفوف المكتسبة رصيدًا يمكنك سحبه وفق شروط الخدمة. وتعرض الصفوف المستحقة رصيدًا غير مدفوع في مجمّع التعدين قد لا يدفعه المجمّع أبدًا.

استخدم أساسًا واحدًا للدخل نفسه. فإضافة صفوف الدفعات إلى الصفوف المكتسبة والمستحقة قد تحتسب المال نفسه مرتين. تحقّق من الأساس الذي ينطبق على إقرارك.

## أعمدة CSV { #csv-columns }

| العمود | المعنى |
|---|---|
| date | يوم UTC للقراءة اللاحقة أو للدفعة. تستخدم الدفعة التاريخ الذي أدخلته أو اليوم الذي اكتشفها فيه CashPilot. |
| period_start | يوم UTC للقراءة السابقة لهذه الخدمة وهذا المصدر. فارغ للدفعات. والفجوة بين القراءات تعني أن المبلغ يغطي الفترة كلها. |
| kind | earned (مكتسب) أو accrued (مستحق) أو payout (دفعة). |
| service | معرّف الخدمة في CashPilot. |
| coin | رمز العملة أو الرمز الرقمي (token) كما سجّله CashPilot. |
| amount | المبلغ بتلك العملة أو ذلك الرمز الرقمي. |
| usd_rate | عدد الدولارات الأمريكية لكل وحدة من coin. |
| usd_value | المبلغ مقيّمًا بالدولار الأمريكي. |
| local_currency | العملة الورقية التي اخترتها للتصدير. |
| local_rate | وحدات عملتك المختارة لكل دولار أمريكي. |
| local_value | المبلغ مقيّمًا بعملتك المختارة. |
| method | طريقة الدفع، إن سُجّلت. |

التقييم الفارغ يعني أن السعر لم يكن متاحًا. ويبقى المبلغ الأصلي موجودًا. يتخطى CashPilot النقاط الداخلية مثل نقاط Grass في قراءات الأرباح. وتوفّر أول قراءة لكل مصدر رصيدًا افتتاحيًا. وتسجّل الصفوف اللاحقة الزيادات، لذلك قد يبدأ ملف CSV بعد أقدم قراءة في النطاق المختار.

إذا قرأ أكثر من مصدر الحساب نفسه، فقد يحتسب ملف CSV ذلك الدخل أكثر من مرة.

يأتي سعر USD من القراءة اللاحقة أو من سجل الدفعة. وعندما يملأ CashPilot لاحقًا سعر قراءة ما، يستخدم سعر CoinGecko عند 00:00 UTC لذلك اليوم. ويستخدم CashPilot أحدث سعر مرجعي من ECB في يوم الصف أو قبله لتحويل USD إلى عملتك المختارة. ويغطي هذا عطلات نهاية الأسبوع والعطلات الرسمية والأيام التي لم ينشر فيها ECB سعره بعد. [أسعار Frankfurter اليومية](https://frankfurter.dev/v1/)

يدرج Frankfurter هذه العملات للتصدير. [العملات المدعومة](https://api.frankfurter.dev/v1/currencies)

- AUD وBRL وCAD وCHF وCNY وCZK وDKK وEUR وGBP وHKD وHUF وIDR وILS وINR وISK.
- JPY وKRW وMXN وMYR وNOK وNZD وPHP وPLN وRON وSEK وSGD وTHB وTRY وUSD وZAR.

اختر USD إذا كانت عملتك خارج تلك القائمة أو كان Frankfurter غير متاح.

## الاستيراد إلى أداة أخرى { #import-into-another-tool }

حوّل ملف CSV إلى تنسيق الأداة قبل الاستيراد. اختر أولًا الصفوف الخاصة بأساسك المحاسبي. وتخطَّ صفوف الدفعات الخاصة بمحفظة تزامنها الأداة بالفعل.

### rotki { #rotki }

استخدم Generic Events مع هذه الترويسات.

```csv
Type,Location,Currency,Amount,Fee,Fee Currency,Description,Timestamp
```

اضبط Type على Income وLocation على external. ويقبل rotki أيضًا Deposit وWithdrawal وLoss وSpend وStaking عندما تصف هذه الأنواع حدثًا ما. اربط coin بـ Currency، وamount بـ Amount، وservice بـ Description. استخدم معرّف الأصل في rotki حيث يختلف عن رمز العملة. حوّل date إلى طابع زمني Unix بتوقيت UTC بالمللي ثانية. واترك حقلي الرسوم كليهما فارغين. [rotki Generic Events](https://docs.rotki.com/usage-guides/history/import-data#rotki-generic-events-import)

### Koinly { #koinly }

استخدم الأعمدة المطلوبة في قالب Universal.

```csv
Date,Sent Amount,Sent Currency,Received Amount,Received Currency
```

نسّق Date بالشكل YYYY-MM-DD HH:mm:ss بتوقيت UTC. اضبط Received Amount من amount وReceived Currency من coin. واترك حقلي Sent كليهما فارغين. للقيم المعروفة، اربط local_value وlocal_currency بالعمودين الاختياريين Net Worth Amount وNet Worth Currency. واستخدم العمود Tag للقيمة mining أو reward حسب الاقتضاء. والعمودان Description وTxHash اختياريان. [قالب Koinly Universal](https://support.koinly.io/en/articles/9489976-how-to-create-a-custom-csv-file-with-your-data)

ألا تملك حسابًا في Koinly بعد؟ يمكنك التسجيل من هنا: https://koinly.io/?via=FFF185D5. إنه رابط إحالة، ولا يكلّفك شيئًا.

### CoinTracking { #cointracking }

حوّل صفوف الدخل إلى تنسيق CSV العادي في CoinTracking. فأداة Custom Importer تتطلب حقول التداول على الجانبين، بينما لا يحتوي صف الدخل إلا على جانب الشراء. [متطلبات CoinTracking Custom Importer](https://cointracking.freshdesk.com/en/support/solutions/articles/29000032507)

```csv
"Type","Buy Amount","Buy Currency","Sell Amount","Sell Currency","Fee","Fee Currency","Exchange","Trade-Group","Comment","Date"
"Income","8","MYST","","","","","","","mysterium","17.11.2025 00:00:00"
```

اضبط Type على Income أو Mining حسب الاقتضاء. اربط amount بـ Buy Amount، وcoin بـ Buy Currency، وservice بـ Comment. واترك حقول Sell فارغة. نسّق Date بالشكل DD.MM.YYYY HH:MM:SS. يوفّر التصدير يوم UTC، لذلك استخدم 00:00:00 للوقت. واستخدم تسميات الأنواع الخاصة بلغة حسابك. [تنسيق CSV العادي في CoinTracking](https://cointracking.freshdesk.com/en/support/solutions/articles/29000038366-how-can-i-import-2gether-csv-data-into-cointracking-)

ألا تملك حسابًا في CoinTracking بعد؟ يمنحك رابط التسجيل هذا خصمًا بنسبة 10% على كل خطة مدفوعة: https://cointracking.info?ref=G962413. إنه رابط إحالة. يدفع CoinTracking لمشروع CashPilot نسبة 20% مما تدفعه، ولا يكلّفك ذلك أكثر.
