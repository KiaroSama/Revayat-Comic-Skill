<div dir="rtl">

# روایت کمیک — Revayat Comic

**ترجمهٔ مانگا، مانهوا، مانهوا چینی و کمیک به فارسی — و تحویل یک CBZ یا PDF که هنرِ صفحه در آن دست‌نخورده مانده باشد.**

یک Agent Skill برای Claude Code، Claude Desktop، Codex، Antigravity، Hermes، OpenCode، Kiro، Cursor، Cline و هر ایجنت کدنویسی دیگری که بتواند یک `SKILL.md` را بخواند. کارهایی را انجام می‌دهد که ترجمهٔ کمیک را واقعاً سخت می‌کنند: پیدا کردن دقیقِ حبابِ گفت‌وگو، پاک کردن متن اصلی بدون آسیب زدن به نقاشی، و حروف‌چینیِ فارسیِ راست‌به‌چپی که باید درست باشد، نه تقریباً درست.

<div align="right"><a href="LICENSE">مجوز GPL-3.0</a></div>
<div align="left"><a href="README.en.md">English</a></div>

---

## چه چیزی آن را از یک مترجم مانگای معمولی جدا می‌کند

| | |
| --- | --- |
| **مدل، صفحه را می‌بیند** | به‌جای اینکه یک موتور OCR رشته‌ای بی‌بافت بدهد و مترجم کورکورانه ترجمه کند، برای هر صفحه دو تصویر ساخته می‌شود: نمای کل صفحه با شمارهٔ ترتیب خواندنِ هر ناحیه، و برگهٔ برش‌ها با برچسب. مدل هر دو را می‌بیند و هم‌زمان می‌خواند و ترجمه می‌کند — با چهرهٔ شخصیت، حبابِ پاسخ و لحن صحنه جلوی چشمش. |
| **تضمینِ سالم ماندن نقاشی** | «سعی می‌کنیم به هنر دست نزنیم» کافی نیست. صفحهٔ نهایی با صفحهٔ اصلی مقایسه می‌شود و ثابت می‌شود هر پیکسل بیرونِ ماسکِ مجاز **بایت‌به‌بایت** همان است. `qa check` عدد `artwork_pixels_changed` را گزارش می‌کند و در یک اجرای درست صفر است. |
| **ماسک، شکلِ حباب است نه کادرِ آن** | گوشه‌های یک کادر دور یک بیضی، بیرونِ حباب‌اند. برش به کادر، نقاشیِ آن گوشه‌ها را بازرنگ می‌کند و خطِ دور حباب را پاک می‌کند. اینجا ماسک به **درونِ واقعیِ حباب** بریده می‌شود. |
| **پاک‌سازیِ پلکانی** | حبابِ تخت با رنگِ خودش پر می‌شود — دقیق، بدون هیچ مدلی. فقط جایی که متن روی نقاشی نشسته به بازسازی می‌رود. یک پاک‌کنندهٔ بهتر با `--external` وصل می‌شود و باز هم فقط پیکسل‌های ماسک‌شده‌اش استفاده می‌شود. |
| **حروف‌چینی به شکلِ واقعیِ حباب** | حبابِ گرد بالا و پایین باریک است و وسط پهن. هر سطر عرضِ مجاز را در نوارِ عمودیِ خودش می‌پرسد و همان‌جا شکسته می‌شود — همان کاری که یک حروف‌چینِ انسانی می‌کند. |
| **راست‌به‌چپِ اصولی** | هیچ رشته‌ای برعکس نمی‌شود. جهت و اتصالِ حروف کارِ HarfBuzz و FriBidi است (یا در ویندوز و مک، `arabic-reshaper` و `python-bidi`). `doctor` می‌گوید کدام مسیر فعال است. |
| **ترتیبِ خواندنِ پنل‌آگاه** | حبابِ بالای پنلِ بعدی بعد از حبابِ پایینِ این پنل خوانده می‌شود، حتی اگر روی کاغذ بالاتر باشد. برای مانگا راست‌به‌چپ، برای وبتون و کمیک غربی چپ‌به‌راست. |
| **کفِ اندازهٔ قلم، کف است** | وقتی فارسی در حباب جا نمی‌شود، متن بی‌صدا کوچک نمی‌شود؛ ناحیه به‌عنوان `text-overflow` گزارش می‌شود تا ترجمه کوتاه‌تر شود. |
| **افکت صوتی، هنر است** | افکت‌های صوتی جدا از گفت‌وگو دسته‌بندی می‌شوند و پیش‌فرض `keep` است. پاک کردنِ حروف‌نگاریِ دستی برای گذاشتن یک حدس به‌جایش، بدتر از ترجمه‌نکردن است. |
| **دروازه‌های کیفیِ قطعی** | متن ترجمه‌نشده، بازماندهٔ خط ژاپنی داخل فارسی، سرریزِ متن، ترتیبِ خواندنِ شکسته، تغییرِ نقاشی، و رانشِ واژه‌نامه. همه بر پایهٔ شمارش و مقایسهٔ پیکسل، نه نظر دوبارهٔ یک مدل. |

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

### یک قلم فارسی

هیچ قلمی همراه این مخزن نمی‌آید — یک فایل قلم، باینریِ جداگانه‌ای با مجوز خودش است و جای آن در یک درختِ GPL نیست. اگر روی سیستم قلمِ فارسی ندارید، [وزیرمتن](https://github.com/rastikerdar/vazirmatn/releases) را نصب کنید. `doctor` می‌گوید چه پیدا کرده است.

## استفاده

به ایجنت بگویید:

> این فصل مانگا را به فارسی ترجمه کن: `chapter-01.cbz`

بقیه‌اش را خودش انجام می‌دهد. یازده گام در `SKILL.md` هست و ایجنت آن‌ها را به ترتیب اجرا می‌کند. گامِ پنجم — خواندن صفحه و ترجمه‌اش — کارِ خودِ ایجنت است، نه یک اسکریپت.

اگر خواستید مستقیم اجرا کنید:

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
#  … برگه‌ها را ترجمه کنید …
$PY $SKILL/scripts/revayat-comic.py worksheet merge --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py falint fix --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py clean   --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py typeset --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py qa check --doc work/comic.json
$PY $SKILL/scripts/revayat-comic.py export --doc work/comic.json --out out/chapter-fa.cbz
```

</div>

## چه چیزی وارد و چه چیزی خارج می‌شود

**ورودی:** CBZ، CBR، PDF کمیک، پوشه‌ای از تصویرها، یا یک تصویر.
**خروجی:** CBZ، PDF، یا پوشه‌ای از صفحه‌ها — به‌همراه `ComicInfo.xml` که جهت خواندن را هم ثبت می‌کند تا خواننده‌ها صفحه‌های دوتایی را برعکس جفت نکنند.

**زبان‌های مبدأ:** ژاپنی، کره‌ای، چینی، انگلیسی — و هر زبان دیگری که ایجنت بتواند از روی برش بخواند.
**زبان مقصد:** فارسی.

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

هر مرحله فقط با `comic.json` حرف می‌زند و هرگز با مرحلهٔ دیگر. صفحهٔ اصلی هرگز بازنویسی نمی‌شود؛ هر مرحله فایل تازه‌ای می‌نویسد و هش صفحهٔ اصلی در پایان دوباره بررسی می‌شود.

## توسعه

<div dir="ltr">

```bash
pip install -r skills/revayat-comic/requirements.txt
python -m pytest tests -q
python tests/e2e_pipeline.py
```

</div>

فیکسچرها ساخته می‌شوند، نه کامیت. هیچ صفحهٔ کمیکی در این مخزن نیست: حجم مخزن را بالا می‌برد و محتوایش معمولاً مالِ کسِ دیگری است.

## مجوز

GPL-3.0-or-later. متن کامل در [LICENSE](LICENSE).

قلم‌ها، مدل‌ها و آثار هنری که این ابزار پردازش می‌کند مجوز جداگانهٔ خودشان را دارند و هیچ‌کدام همراه این مخزن توزیع نمی‌شوند.

</div>
