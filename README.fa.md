<div dir="rtl">

# روایت کمیک — Revayat Comic

**ترجمهٔ مانگا، مانهوا، مانهوای چینی و کمیک به فارسی — و تحویل یک CBZ یا PDF که دست‌نخوردگیِ هنرِ صفحه در آن اثبات شده باشد.**

یک Agent Skill برای Claude Code، Claude Desktop، Codex، Antigravity، Hermes، OpenCode، Kiro، Cursor، Cline و هر ایجنت کدنویسی دیگری که بتواند یک `SKILL.md` را بخواند. کارهایی را انجام می‌دهد که ترجمهٔ کمیک را واقعاً سخت می‌کنند: پیدا کردن حبابِ گفت‌وگو در حد پیکسل، پاک کردن متن اصلی بدون آسیب زدن به نقاشی، و حروف‌چینیِ فارسیِ راست‌به‌چپی که باید درست باشد، نه تقریباً درست.

<div align="right"><a href="LICENSE">مجوز GPL-3.0</a></div>
<div align="left"><a href="README.md">English</a></div>

---

## دو مرحلهٔ اختیاری

مدلی که این مهارت را اجرا می‌کند خودش می‌خواند و خودش می‌بیند، پس این دو مرحله
**پیش‌فرض خاموش‌اند** و تا وقتی یک provider را با اسم صدا نزنید اجرا نمی‌شوند:

| مرحله | برای چه |
| --- | --- |
| `ocr` | نظر دوم دربارهٔ متنِ مبدأ — وقتی یک موتور تخصصی بهتر از میزبان است (ژاپنیِ عمودی) یا میزبان اصلاً بینایی ندارد |
| `qa visual` | نظر یک مدل دربارهٔ چیزهایی که بررسیِ قطعی نمی‌تواند قضاوت کند؛ فقط مشورتی است و هرگز اجرایی را رد یا تأیید نمی‌کند |

هیچ‌کدام خروجیِ provider را مستقیم روی صفحه نمی‌نویسند: تصویر از همان composite
با ماسک سخت رد می‌شود و متن هرگز روی ناحیه‌ای که قفل شده نوشته نمی‌شود. برای هر
نقش یک fake قطعی هست، پس کل تست‌ها آفلاین و بدون هیچ credential اجرا می‌شوند.

## چه چیزی آن را از یک مترجم مانگای معمولی جدا می‌کند

| | |
| --- | --- |
| **مدل، صفحه را می‌بیند** | به‌جای اینکه یک موتور OCR رشته‌ای بی‌بافت به مترجم بدهد، برای هر صفحه دو تصویر ساخته می‌شود: نمای کل صفحه با شمارهٔ ترتیب خواندنِ هر ناحیه، و برگهٔ برش‌ها بزرگ‌شده و برچسب‌خورده. مدل هر دو را می‌بیند و در یک پاس هم می‌خواند و هم ترجمه می‌کند — با چهرهٔ شخصیت، حبابی که پاسخ می‌دهد و لحن صحنه جلوی چشمش. |
| **سالم ماندن نقاشی، تضمین است نه نیت** | «سعی می‌کنیم به هنر دست نزنیم» کافی نیست. صفحهٔ نهایی با صفحهٔ اصلی مقایسه می‌شود و ثابت می‌شود هر پیکسل بیرونِ ماسکِ مجاز **بایت‌به‌بایت** همان است. `qa check` عدد `artwork_pixels_changed` را گزارش می‌کند و در یک اجرای درست صفر است. |
| **ماسک، شکلِ حباب است نه کادرِ آن** | گوشه‌های یک کادر دور یک بیضی، بیرونِ حباب‌اند. برش به کادر، نقاشیِ آن گوشه‌ها را بازرنگ می‌کند و خطِ دورِ حباب را پاک می‌کند. اینجا ماسک به **درونِ واقعیِ حباب** بریده می‌شود، با یک فرورفتگی که خطِ دور را ساختاراً از دسترس خارج می‌کند. |
| **پاک‌سازیِ پلکانی** | حبابِ تخت با رنگِ خودش پر می‌شود — دقیق، بدون هیچ مدلی. فقط متنی که روی نقاشی نشسته به بازسازی می‌رود. یک پاک‌کنندهٔ بهتر با `--external` وصل می‌شود و باز هم فقط پیکسل‌های ماسک‌شده‌اش استفاده می‌شود. |
| **حروف‌چینی به شکلِ واقعیِ حباب** | حبابِ گرد بالا و پایین باریک است و وسط پهن. هر سطر عرضِ مجاز را در نوارِ عمودیِ خودش می‌پرسد — همان کاری که یک حروف‌چینِ انسانی با دست می‌کند. |
| **راست‌به‌چپِ اصولی** | هیچ رشته‌ای برعکس نمی‌شود. جهت و اتصالِ حروف کارِ HarfBuzz و FriBidi است — یا در ویندوز و مک، `arabic-reshaper` و `python-bidi`. `doctor` می‌گوید کدام مسیر فعال است. |
| **ترتیبِ خواندنِ پنل‌آگاه** | حبابِ بالای پنلِ بعدی بعد از حبابِ پایینِ این پنل خوانده می‌شود، حتی اگر روی کاغذ بالاتر باشد. برای مانگا راست‌به‌چپ، برای وبتون و کمیک غربی چپ‌به‌راست. |
| **کفِ اندازهٔ قلم، واقعاً کف است** | وقتی فارسی در حباب جا نمی‌شود، متن بی‌صدا کوچک نمی‌شود؛ ناحیه به‌عنوان `text-overflow` گزارش می‌شود تا ترجمه کوتاه‌تر شود. |
| **افکت صوتی، هنر است** | افکت‌های صوتی جدا از گفت‌وگو دسته‌بندی می‌شوند و پیش‌فرض `keep` است. پاک کردنِ حروف‌نگاریِ دستی برای گذاشتن یک حدس به‌جایش، بدتر از ترجمه‌نکردن است. |
| **دروازه‌های کیفیِ قطعی** | ناحیهٔ ترجمه‌نشده، بازماندهٔ خطِ مبدأ داخل فارسی، سرریزِ متن، ترتیبِ خواندنِ شکسته، تغییرِ نقاشی، و رانشِ واژه‌نامه. همه بر پایهٔ شمارش و مقایسهٔ پیکسل، نه نظر دوبارهٔ یک مدل. |

## نصب

<div dir="ltr">

```bash
git clone https://github.com/KiaroSama/Revayat-Comic-Skill.git
cd Revayat-Comic-Skill
pip install -r skills/revayat-comic/requirements.txt
```

</div>

سپس اسکیل را در ایجنت‌هایی که استفاده می‌کنید نصب کنید:

<div dir="ltr">

```bash
# macOS / Linux
./install/install.sh

# Windows
powershell -ExecutionPolicy Bypass -File .\install\install.ps1
```

</div>

به‌صورت پیش‌فرض در هر ایجنتی که پیدا کند نصب می‌شود — Claude Code، Kiro، Codex، Cursor، Cline، Hermes، OpenCode و Antigravity. دو مورد آخر یک اشاره‌گر در `AGENTS.md` هم می‌گیرند، چون اینستراکشن‌ها را این‌طور پیدا می‌کنند. با `--agent claude` فقط یکی نصب می‌شود و با `--scope project --path <dir>` فقط در یک پروژه. هر دو نصب‌کننده روی لینوکس، مک و ویندوز رفتار یکسانی دارند.

### به‌عنوان پلاگین Claude Code

<div dir="ltr">

```
/plugin marketplace add KiaroSama/Revayat-Comic-Skill
/plugin install revayat-comic@KiaroSama/Revayat-Comic-Skill
```

</div>

### بررسی نصب

<div dir="ltr">

```bash
python skills/revayat-comic/scripts/revayat-comic.py doctor
```

</div>

اگر `"ready": true` بود، کار تمام است. دو فیلد زیر `persian` تعیین می‌کنند خروجی *درست* است یا فقط *موجود*:

- **`"font"`** و **`"vazir"`** — قلمی که فارسی با آن کشیده می‌شود، و اینکه همان قلمِ خانگی است یا نه. **فارسی در این پروژه با وزیر حروف‌چینی می‌شود**؛ [وزیرمتن](https://github.com/rastikerdar/vazirmatn/releases) نسخهٔ امروزی همین خانواده است و هر وزنی از آن، حتی نسخهٔ variable، کار می‌کند. هیچ قلمی همراه این مخزن نمی‌آید: فایل قلم یک باینریِ با مجوز جداگانه است و جای آن در یک درختِ GPL نیست. تاهوما، نوتو نسخ عربی و Geeza Pro همه فارسیِ درست می‌کشند، پس خروجیِ آن‌ها سالم به نظر می‌رسد و قلمِ خانگی نیست — به همین دلیل `"vazir": false` با یک یادداشت می‌آید و بی‌صدا رد نمی‌شود.
- **`"raqm"`** — اینکه Pillow خودش خط عربی را shape می‌کند یا نه. **این محدودیتِ پلتفرم نیست.** Pillow در wheel هر پلتفرمی libraqm را می‌فرستد؛ آنچه libraqm در زمان اجرا لود می‌کند **FriBiDi** است، و لینوکس معمولاً آن را دارد و ویندوز و مک معمولاً نه. یک `fribidi.dll` — `fribidi-0.dll` یا `libfribidi-0.dll` هم کار می‌کنند — در پوشه‌ای که روی `PATH` است بگذارید (پوشه‌ای در مسیرِ جستجوی DLL؛ کنار `python.exe` کافی نیست) تا `raqm` در ویندوز true شود. در لینوکس و مک، `libfribidi` را نصب کنید. بدون آن، مسیر جایگزین `arabic-reshaper` + `python-bidi` اجرا می‌شود و صفحه‌ها باز هم برای خواندن درست‌اند.

## استفاده

به ایجنت بگویید:

> این فصل مانگا را به فارسی ترجمه کن: `chapter-01.cbz`

بقیه‌اش را خودش انجام می‌دهد. `SKILL.md` یازده گام دارد و ایجنت آن‌ها را به ترتیب اجرا می‌کند. گامِ پنجم — خواندن صفحه و ترجمه‌اش — کارِ خودِ ایجنت است، نه یک اسکریپت.

### یا خودتان مرحله‌به‌مرحله اجرا کنید

<div dir="ltr">

```bash
PY=python   # یا python3
SKILL=skills/revayat-comic

$PY $SKILL/scripts/revayat-comic.py doctor
$PY $SKILL/scripts/revayat-comic.py import chapter-01.cbz --out work/ --source-language ja --direction rtl
$PY $SKILL/scripts/revayat-comic.py detect --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py mask   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py crops  --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py worksheet build --doc work/comic.json
#   … به work/crops/pNNNN/*.png نگاه کنید و برگه‌ها را ترجمه کنید …
$PY $SKILL/scripts/revayat-comic.py worksheet merge --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py glossary scan --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py falint fix --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py clean   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py typeset --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py qa check --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py export --doc work/comic.json --out out/chapter-fa.cbz
```

</div>

**ورودی:** CBZ، CBR، PDF کمیک، پوشه‌ای از تصویرها، یا یک تصویر.
**خروجی:** CBZ، PDF، یا پوشه‌ای از صفحه‌ها — به‌همراه `ComicInfo.xml` که جهت خواندن را ثبت می‌کند تا خواننده‌ها صفحه‌های دوتایی را برعکس جفت نکنند.

**زبان‌های مبدأ:** ژاپنی، کره‌ای، چینی، انگلیسی — و هر زبان دیگری که ایجنت بتواند از روی برش بخواند. **مقصد:** فارسی.

## بدون پوسته

مسیر توصیه‌شده همان CLI است. جایی که میزبان اصلاً نمی‌تواند زیرفرایند اجرا کند،
همان مرحله‌ها از راه MCP یا HTTP روی loopback در دسترس‌اند:

```bash
revayat-comic serve mcp                   # JSON-RPC 2.0 روی stdio
revayat-comic serve http --port 8765      # توکن روی stderr چاپ می‌شود
```

پانزده ابزار — `revayat_doctor` به‌علاوهٔ یکی برای هر مرحله — و هرکدام همان
آرگومان‌هایی را می‌گیرد که CLI می‌گیرد. این یک **لایهٔ انتقال** است، نه پیاده‌سازی
دوم: هر ابزار همان `main` خودِ آن مرحله است، پس هیچ‌چیزی از این راه در دسترس
نیست که CLI نتواند انجام دهد. HTTP فقط به `127.0.0.1` بایند می‌شود و توکن را در
`X-Revayat-Token` می‌خواهد، چون این فراخوانی‌ها فایل می‌نویسند و یک صفحهٔ وب هم
می‌تواند به localhost درخواست POST بفرستد.

گام ۵ همچنان کارِ خودتان است: مدلی که این سرور را می‌راند همان رونویس است و هیچ
ابزاری اینجا جای او را نمی‌گیرد. جزئیات در
[`references/serving.md`](skills/revayat-comic/references/serving.md).

## معماری

<div dir="ltr">

```
import → detect → mask → crops → worksheet ⇄ [ the agent reads and translates ]
                                     ↓
                            merge → glossary → falint
                                     ↓
                              clean → typeset → qa → export
```

</div>

هر مرحله فقط با `comic.json` حرف می‌زند و هرگز با مرحلهٔ دیگر، پس می‌شود detector را عوض کرد یا renderer را از نو نوشت بدون اینکه بقیه متوجه شوند. صفحهٔ اصلی هرگز بازنویسی نمی‌شود؛ هر مرحله فایل تازه‌ای می‌نویسد و SHA-256 صفحهٔ اصلی در پایان دوباره بررسی می‌شود.

| ماژول | نقش |
| --- | --- |
| `pageir.py` | سند صفحه، I/O اتمیک UTF-8، هندسه، ترتیب خواندن، تشخیص خط |
| `readers.py` | CBZ / CBR / PDF / پوشه / تصویر ← صفحه‌های تغییرناپذیر |
| `detect.py` | پنل‌ها، حباب‌ها در هر دو قطبیت، حروف‌نگاری آزاد |
| `masks.py` | شکلِ گلیف‌ها، بریده‌شده به درونِ حباب |
| `crops.py` | نمای کل و برگه‌های برشی که خواننده می‌بیند |
| `worksheet.py` | پروتکل `@@` و هر شکلِ نام‌دارِ خطا در پاسخ |
| `glossary.py` | نام‌ها و اصطلاح‌ها، و بررسی رانش |
| `falint.py` | تایپوگرافی فارسی، مکانیکی |
| `clean.py` | ترمیم پلکانی و ترکیبِ محدود به ماسک |
| `typeset.py` | shaping، جاسازی در شکل حباب، رندر |
| `qa.py` | دروازه، شامل اثباتِ حفظ پیکسل |
| `export.py` | CBZ، PDF، پوشه |

تضمینِ حفظ نقاشی یک خط است، و همین است که وصل‌کردن یک پاک‌کنندهٔ بیرونی را امن می‌کند:

<div dir="ltr">

```
out = original × (1 − alpha) + repaired × alpha        where alpha ≤ mask
```

</div>

چون `alpha` هرجا که ماسک صفر است صفر می‌شود، هر پیکسل بیرون ناحیهٔ مجاز از روی *ساختار* همان بایتِ اصلی است، نه از روی خوش‌رفتاری. به `--external` صفحه‌ای بدهید که یک مدل generative از نو کشیده — باز هم فقط پیکسل‌های ماسک‌شده‌اش استفاده می‌شود.

## آنچه صادقانه باید گفت

- **دو جلد واقعی از آن رد شده‌اند؛ این هنوز پیکره نیست.** فصل‌هایی از *Sekirei* و *Gleipnir* ترجمه، تمیز، حروف‌چینی و خروجی گرفته شدند و هرکدام نقص‌هایی را نشان دادند که fixtureهای ساختگی نمی‌توانستند. دو کتاب برای اثبات پایداری خط لوله کافی است و برای دیدن همهٔ سبک‌های طراحی به‌هیچ‌وجه کافی نیست: بالون‌های بدون خط دور و متن سفید روی سیاهِ کتاب دوم تا نیامدنش نامرئی بودند. انتظار داشته باشید روی یک اسکن تازه knobهای `references/detection.md` را جابه‌جا کنید — دقیقاً به همین دلیل همه‌شان فلگ خط فرمان‌اند.
- **لترینگ آزاد ضعیف‌ترین بخش تشخیص است و بالون‌های ادغام‌شده ضعیف‌ترین ناحیه.** دو بالونِ چسبیده به هم یکی گرفته می‌شوند؛ پنج روش خودکار برای تفکیکشان سنجیده شد و هیچ‌کدام قابل‌عرضه نبود. از روی crop با `drop: yes` و دو بلوک `@@ +name` در چند ثانیه درستش می‌کنید، و مستند است.
- **افکت‌های صوتیِ کشیده‌شده در نقاشی، کشیده‌شده می‌مانند** با سیاست پیش‌فرض. بازکشیدنِ حروف‌نگاری دستی — با همان شیب، ضخامت، حاشیه و پرسپکتیو — یک کارِ حروف‌نگاری است و نسخهٔ نصفه‌نیمه‌اش بدتر از باقی‌گذاشتنِ ژاپنی است.
- **تشخیصِ حروف‌نگاری آزاد نیمهٔ ضعیف است.** افکت‌های آشکار را پیدا می‌کند و دربارهٔ بقیه اشتباه می‌کند؛ برای همین هرچه برمی‌گرداند کم‌اطمینان علامت می‌خورد و به‌شکل برش به شما نشان داده می‌شود.
- **Telea صاف می‌کند، بازنمی‌کشد.** متنِ روی نقاشیِ پرجزئیات بازسازی می‌شود، نه ابداع. `clean` فهرست `inpaint_heavy_pages` را می‌دهد تا بدانید کدام صفحه‌ها را باید ببینید.
- **مسیر جایگزینِ shaping، فرم‌های نمایشی می‌کشد.** در ویندوز و مک متنِ روی صفحه برای خواندن درست است، اما تصویری از فارسی است نه فارسیِ قابل‌جست‌وجو.

## مستندات

- [`SKILL.md`](skills/revayat-comic/SKILL.md) — یازده گام و جدول کدهای QA
- [`references/translation-policy.md`](skills/revayat-comic/references/translation-policy.md) — چه چیزی به ساب‌ایجنتِ مترجم بدهیم
- [`references/persian-typesetting.md`](skills/revayat-comic/references/persian-typesetting.md) — راست‌به‌چپ، shaping، قلم، جاسازی در حباب
- [`references/detection.md`](skills/revayat-comic/references/detection.md) — آستانه‌ها، صفحه‌های دشوار، اصلاح یک ناحیه
- [`references/artwork-preservation.md`](skills/revayat-comic/references/artwork-preservation.md) — ماسک‌ها، لایه‌های پاک‌سازی، و آنچه QA اثبات می‌کند
- [`references/sound-effects.md`](skills/revayat-comic/references/sound-effects.md) — چهار سیاست و انتخاب میانشان
- [`references/ocr.md`](skills/revayat-comic/references/ocr.md) — خواندن با چشم خود، و اینکه کِی یک مدل کمک می‌کند
- [`references/serving.md`](skills/revayat-comic/references/serving.md) — MCP و HTTP روی loopback، برای میزبانی که نمی‌تواند این CLI را اجرا کند
- [`references/troubleshooting.md`](skills/revayat-comic/references/troubleshooting.md) — خطاهایی که بیشتر با آن‌ها روبه‌رو می‌شوید
- [`AGENTS.md`](AGENTS.md) — برای ایجنت‌هایی که *روی* این مخزن کار می‌کنند

## توسعه

<div dir="ltr">

```bash
pip install -r skills/revayat-comic/requirements.txt
python -m pytest tests -q
python tests/e2e_pipeline.py
```

</div>

فایل‌های آزمون ساخته می‌شوند، نه commit. هیچ صفحهٔ کمیکی در این مخزن نیست: حجم مخزن را بالا می‌برد و محتوایش معمولاً مالِ کسِ دیگری است. یک بررسی در CI همین را اجبار می‌کند.

صفحه‌ها عمداً با شکل‌های ساده کشیده می‌شوند نه با ژاپنیِ واقعی — detector هندسه را اندازه می‌گیرد و برایش مهم نیست جوهر از کدام خط آمده، و یک قلم CJK روی رانرِ استاندارد CI نصب نیست.

`tests/e2e_pipeline.py` تمام مراحل را از طریق CLI واقعی روی یک فصل ساختگی اجرا می‌کند، تا شکستگی در dispatcher یا نام یک آرگومان یا یک فیلد گزارش، حتی وقتی تست‌های هر ماژول سبزند، گرفته شود. CI آن را روی لینوکس، مک و ویندوز اجرا می‌کند.

یک لایهٔ دوم هفتگی اجرا می‌شود نه در هر commit — CBR از طریق یک backend واقعی آرشیو، و یک فصل کامل در A4/300dpi — چون flake شدنِ apt یا یک backend شخص‌ثالث نباید یک commit بی‌ربط را متوقف کند.

## سپاس

شکل کلی مسئله — تشخیص، OCR، ترجمه، پاک‌سازی، حروف‌چینی — همان چیزی است که پروژه‌های متن‌بازِ ترجمهٔ مانگا پیش از این درآورده‌اند: [manga-image-translator](https://github.com/zyddnys/manga-image-translator)، [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) و [comic-translate](https://github.com/ogkalu2/comic-translate). این یکی در جایی که خواندن اتفاق می‌افتد فرق دارد، و در اینکه حفظ نقاشی را چیزی می‌داند که باید *اثبات* شود — اما زمینه‌اش مالِ آن‌هاست.

چیدمان متن فارسی بر [HarfBuzz](https://harfbuzz.github.io/) و [FriBidi](https://github.com/fribidi/fribidi) از طریق [Pillow](https://github.com/python-pillow/Pillow) استوار است، و جایی که Pillow راقم ندارد بر [arabic-reshaper](https://github.com/mpcabd/python-arabic-reshaper) و [python-bidi](https://github.com/MeirKriheli/python-bidi). تشخیص، ماسک و inpainting از [OpenCV](https://github.com/opencv/opencv) استفاده می‌کنند؛ ورودی و خروجی PDF از [PyMuPDF](https://github.com/pymupdf/PyMuPDF).

## حمایت مالی

اگر این پروژه به کارتان آمد، حمایت شما مایهٔ قدردانی است.

</div>

| Currency | Network | Address |
| --- | --- | --- |
| Bitcoin (BTC) | Bitcoin | `bc1qmth5m03pu5hujw5xw5jmywam3jj3sqwqupesdt` |
| USDT, BNB, USDC, etc. | BEP20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| USDT, TRX, USDC, etc. | TRC20 | `TWBA3xFTqgZAeAYMxqo85xWnzvty3DcAhw` |
| Ethereum (ETH) | ERC20 | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |
| TON | TON | `UQCN8Umo_OfOWqImZetQsrNStPcmLkMAKajFyiCOhso23NDb` |
| Litecoin (LTC) | LTC | `ltc1qntqnnrunadurnw4cshv3qgspywrueyyeyngwuy` |
| Solana (SOL) | Solana | `7B2wkczUjmkDhETwQuknBL8sUsbuV7nErxc317TmQuwR` |
| Polygon (POL) | Polygon | `0x0Bd0BA443a8B9cf15922bf7f0Bb0a4b495fD06Ef` |

<div dir="rtl">

## نویسنده

نویسنده: Kiaro Sama
گیت‌هاب: https://github.com/KiaroSama

## مجوز

[GNU General Public License v3.0 or later](LICENSE).

این نرم‌افزار آزاد است: می‌توانید بر پایهٔ شرایط «پروانهٔ عمومی همگانی گنو» که
بنیاد نرم‌افزار آزاد منتشر کرده — نسخهٔ ۳ یا هر نسخهٔ بعدی — آن را بازتوزیع یا
دگرگون کنید. این برنامه به امید سودمندبودن منتشر شده، اما **بدون هیچ ضمانتی**؛
حتی بدون ضمانت ضمنی قابلیت فروش یا مناسب‌بودن برای هدفی خاص. برای جزئیات،
متن پروانه را ببینید.

قلم‌ها، مدل‌ها و آثار هنری‌ای که این ابزار پردازش می‌کند مجوز جداگانهٔ خودشان را
دارند و هیچ‌کدام همراه این مخزن توزیع نمی‌شوند.

وابستگی‌ها هم همراه مخزن نمی‌آیند: در `requirements.txt` اعلام شده‌اند و از PyPI
نصب می‌شوند. یکی از آن‌ها ارزش دانستن دارد. **PyMuPDF دو مجوزی است — AGPL-3.0 یا
یک مجوز تجاری از Artifex** — که کپی‌لفتی سخت‌گیرانه‌تر از بقیهٔ پشتهٔ این پروژه
است (Pillow و NumPy و OpenCV اجازه‌محورند). بند ۱۳ از GPLv3 این ترکیب را مجاز
می‌داند، پس انتشار این مخزن مشکلی ندارد؛ آنچه AGPL اضافه می‌کند بندِ شبکه است و
دامنش کسی را می‌گیرد که نسخهٔ تغییریافتهٔ PyMuPDF را به شکل سرویس اجرا کند. این
کتابخانه فقط برای ورودی و خروجیِ PDF لازم است — CBZ و CBR و پوشه و فایل تصویری
هرگز سراغش نمی‌روند، و نبودنش به جای خطا یک پیام می‌شود.

</div>
