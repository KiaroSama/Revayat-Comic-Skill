<div dir="rtl">

<div align="center">

# روایت کمیک (Revayat Comic)

**ترجمهٔ مانگا، مانهوا، مانهوای چینی و کمیک به فارسی، و تحویل CBZ یا PDF بی‌افت با اثبات دست‌نخوردگی نقاشی صفحه.**

[![وضعیت گردش‌کار CI در GitHub Actions](https://img.shields.io/github/actions/workflow/status/KiaroSama/Revayat-Comic-Skill/ci.yml?branch=main&style=flat-square&label=CI&color=16a34a)](.github/workflows/ci.yml)
[![مجوز GPL نسخهٔ ۳ یا بالاتر](https://img.shields.io/github/license/KiaroSama/Revayat-Comic-Skill?style=flat-square&color=2563eb)](LICENSE)
[![آخرین برچسب نسخه در گیت‌هاب](https://img.shields.io/github/v/tag/KiaroSama/Revayat-Comic-Skill?style=flat-square&label=version&color=ea580c)](https://github.com/KiaroSama/Revayat-Comic-Skill/tags)
[![آخرین انتشار گیت‌هاب](https://img.shields.io/github/v/release/KiaroSama/Revayat-Comic-Skill?style=flat-square&label=release&color=dc2626)](https://github.com/KiaroSama/Revayat-Comic-Skill/releases)
[![آزمون‌های خودکار ورک‌اسپیس Cargo](https://img.shields.io/badge/tests-Cargo%20workspace-0d9488?style=flat-square)](#توسعه)
[![نسخهٔ ثابت Rust 1.100.0](https://img.shields.io/badge/Rust-1.100.0-8b5cf6?style=flat-square)](rust-toolchain.toml)
[![پلتفرم‌های پشتیبانی‌شده: لینوکس و ویندوز ۶۴ بیتی](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%28x64%20%7C%20arm64%29-0891b2?style=flat-square)](.github/workflows/ci.yml)
[![نصب از پنج قالب افزونه یا باینری مستقل CLI](https://img.shields.io/badge/install-5%20plugins%20%7C%20CLI%20binary-4f46e5?style=flat-square)](#نصب)
[![مستندات به انگلیسی و فارسی](https://img.shields.io/badge/docs-English%20%7C%20Persian-0284c7?style=flat-square)](README.md)
[![حجم مخزن در گیت‌هاب](https://img.shields.io/github/repo-size/KiaroSama/Revayat-Comic-Skill?style=flat-square&color=ca8a04)](#توسعه)
[![اجرا با Rust خالص بدون هیچ وابستگی پایتونی](https://img.shields.io/badge/runtime-pure%20Rust%20%7C%20zero%20Python-059669?style=flat-square)](#معماری)
[![گردش‌کار شش‌مرحله‌ای چندعاملی و ویرایش تمام‌صفحه](https://img.shields.io/badge/workflow-6%20agents%20%7C%20full--page%20edit-7c3aed?style=flat-square)](skills/revayat-comic/references/multi-agent-workflow.md)
[![راهنماهای لحن Humanizer 4.0 و فارسی همراه بسته](https://img.shields.io/badge/voice-Humanizer%204.0%20%7C%20Persian-b45309?style=flat-square)](skills/revayat-comic/references/voice/index.md)
[![حمایت مالی](https://img.shields.io/badge/Support-donations-d04a9a?style=flat-square)](#donate)

[English](README.md) · [فارسی](README.fa.md) · [مشخصات مهارت](skills/revayat-comic/SKILL.md) · [گردش‌کار شش‌مرحله‌ای](skills/revayat-comic/references/multi-agent-workflow.md) · [ویرایش تمام‌صفحه](skills/revayat-comic/references/fullpage-image-edit.md)

</div>

«روایت کمیک» یک ابزار خط فرمان خالص Rust (`revayat-comic`) همراه با مهارت عامل هوشمند برای ترجمهٔ کمیک و مانگا به فارسی روان است. این ابزار فایل‌های CBZ، CBR، PDF، پوشهٔ تصویر و تک‌صفحه را می‌خواند، پنل‌ها و حباب‌ها را پیدا می‌کند، برش‌های خوانا برای بازبینی متنی می‌سازد، متن اصلی را درون ماسک‌های کنترل‌شده پاک می‌کند، فارسی راست‌به‌چپ را با قلم وزیر حروف‌چینی می‌کند، صفحه را با دروازه‌های پیکسلی و چیدمان می‌سنجد و در پایان خروجی بی‌افت CBZ، PDF، پوشهٔ عکس یا DOCX دوزبانهٔ بازبینی تحویل می‌دهد.

## ویژگی‌های نسخهٔ ۲.۰

- بازنویسی کامل به Rust خالص با نسخهٔ ثابت `1.100.0` (`edition = "2024"` و `#![forbid(unsafe_code)]`) و حذف کامل پایتون، PyMuPDF، OpenCV و ابزارهای بیرونی unrar.
- خواندن، بررسی، رندر و ساخت PDF بی‌افت در Rust خالص با `lopdf`، `pdf-writer` و `hayro` به همراه کنترل بودجهٔ پیکسلی ماسک‌های شابلونی و Form XObject پیش از تخصیص حافظهٔ تصویر.
- پشتیبانی بومی و خالص Rust از آرشیو CBR (`rars`)، CBZ (`zip`) و فایل بازبینی DOCX راست‌به‌چپ (`quick-xml`).
- شکل‌دهی و راست‌به‌چپ‌سازی اصولی فارسی روی همهٔ سیستم‌عامل‌ها با `cosmic-text` (مبتنی بر HarfBuzz و FriBidi) و قلم‌های وزیر همراه مخزن (`Regular`، `Medium` و `Bold`)، با حداقل فاصلهٔ سطر `1.38x`، پاک‌سازی کامل نقطه‌های جا‌مانده درون حباب و محافظ ضدتداخل متن.
- گردش‌کار ویرایش تمام‌صفحه (`fullpage-prompt`) برای جلدها، خطوط سرعت، عنوان فصل‌ها و افکت‌های صوتی روی نقاشی: ابتدا فقط حباب‌های یکنواخت خالی می‌شوند، سپس کل صفحه همراه با متن OCR تاییدشده، مختصات دقیق و معادل فارسی به مدل ویرایش تصویر سپرده می‌شود و در نهایت فقط ناحیه‌های ویرایش‌شده با حاشیهٔ نرم روی اسکن اصلی دست‌نخورده می‌نشینند.
- گردش‌کار شش‌مرحله‌ای چندعاملی با قالب پرامپت آماده برای ترجمهٔ اولیه، صفحه‌آرایی، بازبینی، اعمال ترجمه، چک مجدد فایل و رفع اشکال، و بازبینی نهایی و تحویل، همراه با جست‌وجوی نام‌های رسمی شخصیت‌ها و اصطلاحات مجموعه پیش از شروع ترجمه.

## معماری

ورک‌اسپیس این مخزن چهارده crate زیر پوشهٔ `rust/` دارد:

- هسته‌های پایه: `hotcore-rs`، `pixcore-rs`، `maskcore-rs`، `textcore-rs`، `detectcore-rs`، `qacore-rs`، `cleancore-rs`، `layoutcore-rs` و `packcore-rs`.
- کتابخانه‌های دامنه: `revayat-ir` (وضعیت سند، برگه‌های ترجمه، واژه‌نامه، دسته‌بندی، ژورنال اتمی و لاگ UTF-8 بر پایهٔ UTC)، `revayat-io` (CBZ، CBR، PDF، پوشه و DOCX دوزبانه)، `revayat-vision` (تشخیص، ماسک، پاک‌سازی حباب، حروف‌چینی `cosmic-text`، سازندهٔ پرامپت تمام‌صفحه و QA سخت‌گیرانه) و `revayat-tools` (سرور MCP stdio و HTTP محلی، کلاینت OCR/ترجمهٔ امن با HTTPS Bearer، لینتر و واژه‌نامهٔ فارسی، نصاب تراکنشی و ابزار ارزیابی).
- باینری خط فرمان: `revayat-comic-cli` که در ویندوز در مسیر `bin/revayat-comic.exe` و در لینوکس در مسیر `bin/revayat-comic` ساخته می‌شود.

## پلتفرم‌های پشتیبانی‌شده

باینری‌های آمادهٔ انتشار و ماتریس CI این چهار هدف ۶۴ بیتی را پوشش می‌دهند:

</div>

| OS | Architecture | Target triple |
| --- | --- | --- |
| Linux | x64 | `x86_64-unknown-linux-gnu` |
| Linux | arm64 | `aarch64-unknown-linux-gnu` |
| Windows | x64 | `x86_64-pc-windows-msvc` |
| Windows | arm64 | `aarch64-pc-windows-msvc` |

<div dir="rtl">

هدف‌های ۳۲ بیتی و macOS به‌طور پیش‌فرض ساخته نمی‌شوند.

## نصب

### پیش‌نیازها

- برای استفاده از باینری آماده در [انتشارهای گیت‌هاب](https://github.com/KiaroSama/Revayat-Comic-Skill/releases): فایل فشردهٔ سیستم ۶۴ بیتی لینوکس یا ویندوز را بگیرید و `revayat-comic` یا `revayat-comic.exe` را استخراج کنید.
- برای ساخت از سورس: Rust نسخهٔ `1.100.0` (ثبت‌شده در `rust-toolchain.toml`)، `git` و PowerShell 7 (`pwsh`) روی ویندوز یا Bash روی لینوکس.

### نصب افزونه

مخزن مانیفست‌های همگام نسخهٔ `2.0.0` را برای پنج اکوسیستم افزونه نگه می‌دارد: Agent Plugins (`plugin.json` و `.agents/plugins/marketplace.json`)، Claude Code (`.claude-plugin/`)، Codex (`.codex-plugin/`)، Cursor (`.cursor-plugin/`) و Antigravity (`.antigravity-plugin/`).

در Claude Code:

</div>

```text
/plugin marketplace add KiaroSama/Revayat-Comic-Skill
/plugin install revayat-comic@revayat-comic-skill
```

<div dir="rtl">

### ساخت از سورس

ویندوز (PowerShell 7):

</div>

```powershell
cargo build --release --locked -p revayat-comic-cli
New-Item -ItemType Directory -Force -Path bin | Out-Null
Copy-Item target\release\revayat-comic.exe bin\revayat-comic.exe -Force
.\bin\revayat-comic.exe doctor --json
```

<div dir="rtl">

لینوکس:

</div>

```bash
cargo build --release --locked -p revayat-comic-cli
mkdir -p bin
cp target/release/revayat-comic bin/revayat-comic
./bin/revayat-comic doctor --json
```

<div dir="rtl">

### راهنماهای لحن همراه بسته

سه راهنمای نوشتار محلی در پوشهٔ `skills/revayat-comic/references/voice/` قرار دارند:

- `persian` برای گفت‌وگو، روایت، زیرنویس، افکت صوتی و متن فارسی (`revayat-comic voice lint` و `revayat-comic voice lookup`).
- `humanizer` نسخهٔ `4.0.0` (`revayat-comic:humanizer`) برای ویرایش متن‌های انگلیسی.
- `great-russian` (`revayat-comic:great-russian`) برای متن‌های روسی در صورت نیاز.

برای مجوز و شناسهٔ نسخهٔ بالادستی هرکدام [فهرست راهنماهای لحن](skills/revayat-comic/references/voice/index.md) را ببینید.

## استفاده

### دستورهای خط لوله

هر مرحله روی فایل `doc.json` داخل پوشهٔ کاری کار می‌کند و صفحه‌های اصلی را در `originals/` دست‌نخورده نگه می‌دارد.

ویندوز (PowerShell 7):

</div>

```powershell
.\bin\revayat-comic.exe import chapter.cbz --work .\work --direction rtl
.\bin\revayat-comic.exe detect --doc .\work\doc.json
.\bin\revayat-comic.exe mask --doc .\work\doc.json
.\bin\revayat-comic.exe crops --doc .\work\doc.json
.\bin\revayat-comic.exe worksheet build --doc .\work\doc.json --out .\work\worksheets
```

<div dir="rtl">

پس از پر کردن برگه‌های ترجمه (دستی یا با گردش‌کار شش‌مرحله‌ای):

</div>

```powershell
.\bin\revayat-comic.exe worksheet merge --doc .\work\doc.json --in .\work\worksheets
.\bin\revayat-comic.exe glossary check --doc .\work\doc.json
.\bin\revayat-comic.exe falint check --doc .\work\doc.json
.\bin\revayat-comic.exe clean --doc .\work\doc.json
.\bin\revayat-comic.exe typeset --doc .\work\doc.json
.\bin\revayat-comic.exe qa check --doc .\work\doc.json --strict
.\bin\revayat-comic.exe export --doc .\work\doc.json --format cbz --out .\work\chapter-fa.cbz
.\bin\revayat-comic.exe qa package --doc .\work\doc.json --out .\work\chapter-fa.cbz
```

<div dir="rtl">

سایر دستورها:

- `fullpage-prompt --doc <doc.json> --page <id> --out <manifest.json>`: ساخت مانیفست و پرامپت ویرایش تمام‌صفحه همراه با متن OCR تاییدشده و مختصات دقیق.
- `review-docx --doc <doc.json> --out <review.docx>`: خروجی فایل Word دوزبانهٔ بازبینی با جهت راست‌به‌چپ.
- `watermark --doc <doc.json> ...`: مشخص‌کردن کادر دقیق واترمارک مجاز برای حذف.
- `batch plan|merge|status`: تقسیم فصل‌های بلند به بخش‌های موازی و ادغام امن.
- `voice lint [--check|--fix] [--style]` و `voice lookup <file>`: اجرای لینتر و واژه‌نامهٔ فارسی در Rust خالص.
- `serve --mcp` یا `serve --http 127.0.0.1:0`: ارائهٔ همهٔ مراحل از طریق MCP stdio یا HTTP محلی.
- `ocr` و `translate`: کمک‌ابزار اختیاری مدل‌های میزبانی‌شده (نیازمند نشانی HTTPS و توکن Bearer).
- `install` و `eval`: نصب تراکنشی مهارت و ارزیابی با نمونه‌های ساختگی.

### گردش‌کار شش‌مرحله‌ای چندعاملی

برای ترجمهٔ کامل فصل‌ها، راهنمای [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md) شش نقش مشخص دارد:

۱. ترجمهٔ اولیه: جست‌وجوی نام‌های رسمی شخصیت‌ها و اصطلاحات مجموعه پیش از شروع، و ترجمه به فارسی گفتاری روان.
۲. صفحه‌آرایی: تنظیم سطرشکن، نشانه‌گذاری، مقیاس قلم و ناحیه‌های ویرایش تمام‌صفحه.
۳. بازبینی: تطبیق دقیق با برش‌های اصلی، یکدستی واژه‌نامه و سلامت نگارشی.
۴. اعمال ترجمه: ادغام برگه‌ها، اجرای `clean` و `typeset` و نشاندن دقیق صفحات ویرایش‌شده روی ابعاد اصلی.
۵. چک مجدد فایل و اصلاح مشکلات: بازبینی چشمی همهٔ صفحه‌ها، اجرای `qa check --strict` و رفع یک‌جای همهٔ ایرادها.
۶. بازبینی نهایی و تحویل: ساخت خروجی بی‌افت CBZ و PDF و تایید بسته با `qa package`.

### لاگ‌های اجرا

هر اجرای CLI یک فایل لاگ UTF-8 در پوشهٔ `logs/` کنار باینری یا پروژه با نام `revayat-comic_YYYY-MM-DD_HH-mm-ss_UTC.log` و قالب `[YYYY-MM-DD HH:mm:ss UTC] [LEVEL] [COMPONENT] Message` می‌نویسد. هدرهای احراز هویت، کلیدهای API، گذرواژه‌ها و نشانی‌های دارای اعتبارنامه پیش از ثبت پوشانده می‌شوند. برای جزئیات بیشتر از `--verbose` یا متغیر `REVAYAT_LOG_LEVEL=DEBUG` استفاده کنید و هنگام گزارش خطا آخرین فایل لاگ را پیوست کنید.

## مستندات

- [SKILL.md](skills/revayat-comic/SKILL.md): گردش‌کار کامل عامل و جدول کدهای QA
- [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md): نقش‌های شش‌مرحله‌ای و قالب پرامپت‌ها
- [references/fullpage-image-edit.md](skills/revayat-comic/references/fullpage-image-edit.md): روش ویرایش تمام‌صفحه پس از خالی‌کردن حباب‌ها
- [references/translation-policy.md](skills/revayat-comic/references/translation-policy.md): اصول ترجمه، لحن گفتاری و واژه‌نامه
- [references/persian-typesetting.md](skills/revayat-comic/references/persian-typesetting.md): راست‌به‌چپ، فاصلهٔ سطر و جاسازی در حباب
- [references/detection.md](skills/revayat-comic/references/detection.md): آستانه‌های تشخیص و اصلاح دستی نواحی
- [references/artwork-preservation.md](skills/revayat-comic/references/artwork-preservation.md): ماسک‌ها، سطوح پاک‌سازی و QA پیکسلی
- [references/sound-effects.md](skills/revayat-comic/references/sound-effects.md) و [references/sfx-glossary.md](skills/revayat-comic/references/sfx-glossary.md): مدیریت و واژه‌نامهٔ افکت‌های صوتی
- [references/serving.md](skills/revayat-comic/references/serving.md): سرور MCP و HTTP محلی
- [references/recovery.md](skills/revayat-comic/references/recovery.md): ژورنال اتمی خروجی و بازیابی
- [AGENTS.md](AGENTS.md): راهنمای توسعهٔ مخزن برای عامل‌ها

## توسعه

اجرای مجموعهٔ کامل بررسی‌ها با Rust نسخهٔ `1.100.0`:

</div>

```powershell
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace --locked
```

<div dir="rtl">

هیچ صفحهٔ کمیک دارای حق نشر در مخزن ذخیره نمی‌شود و همهٔ آزمون‌ها نمونه‌های ساختگی تولید می‌کنند. گردش‌کارهای GitHub Actions هر چهار هدف ۶۴ بیتی لینوکس و ویندوز را می‌سازند، نسخهٔ مانیفست‌های افزونه را می‌سنجند و اسکن‌های CodeQL، Gitleaks، Semgrep و بررسی وابستگی‌ها را اجرا می‌کنند.

## سپاس

ساختار کلی خط لوله از پروژه‌های متن‌باز پیشین الهام گرفته است: [manga-image-translator](https://github.com/zyddnys/manga-image-translator)، [BallonsTranslator](https://github.com/dmMaze/BallonsTranslator) و [comic-translate](https://github.com/ogkalu2/comic-translate).

رندر و بسته‌بندی در Rust خالص بر دوش کتابخانه‌های [cosmic-text](https://github.com/pop-os/cosmic-text)، [lopdf](https://github.com/J-F-Liu/lopdf)، [pdf-writer](https://github.com/typst/pdf-writer)، [hayro](https://github.com/LaurenzV/hayro)، [rars](https://github.com/g-vash/rars)، [zip](https://github.com/zip-rs/zip)، [image](https://github.com/image-rs/image) و قلم [Vazirmatn](https://github.com/rastikerdar/vazirmatn) است.

## نویسنده

نویسنده: Kiaro Sama
گیت‌هاب: https://github.com/KiaroSama

## مجوز

حق نشر متعلق به Kiaro Sama. منتشرشده تحت [پروانهٔ عمومی همگانی گنو نسخهٔ ۳ یا بالاتر (GPL-3.0-or-later)](LICENSE).

<a id="donate"></a>

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
