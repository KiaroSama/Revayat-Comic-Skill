<div dir="rtl">

<div align="center">

# روایت کمیک (Revayat Comic)

**ترجمهٔ مانگا، مانهوا، مانهوای چینی و کمیک به فارسی، و تحویل CBZ یا PDF بی‌افت با اثبات دست‌نخوردگی نقاشی صفحه.**

[![وضعیت گردش‌کار CI در GitHub Actions](https://github.com/KiaroSama/Revayat-Comic-Skill/actions/workflows/ci.yml/badge.svg?branch=main)](.github/workflows/ci.yml)
[![مجوز GPL نسخهٔ ۳ یا بالاتر](https://img.shields.io/badge/license-GPL--3.0-2563eb?style=flat-square)](LICENSE)
[![آخرین برچسب نسخه در گیت‌هاب](https://img.shields.io/badge/version-v2.0.6-ea580c?style=flat-square)](#releases-and-tags)
[![آخرین انتشار گیت‌هاب](https://img.shields.io/badge/release-v2.0.6-dc2626?style=flat-square)](https://github.com/KiaroSama/Revayat-Comic-Skill/releases)
[![آزمون‌های خودکار ورک‌اسپیس Cargo](https://img.shields.io/badge/tests-Cargo%20workspace-0d9488?style=flat-square)](#توسعه)
[![نسخهٔ ثابت Rust 1.100.0](https://img.shields.io/badge/Rust-1.100.0-8b5cf6?style=flat-square)](rust-toolchain.toml)
[![پلتفرم‌های پشتیبانی‌شده: لینوکس و ویندوز ۶۴ بیتی](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%28x64%20%7C%20arm64%29-0891b2?style=flat-square)](.github/workflows/ci.yml)
[![نصب از پنج قالب افزونه یا باینری مستقل CLI](https://img.shields.io/badge/install-5%20plugins%20%7C%20CLI%20binary-4f46e5?style=flat-square)](#نصب)
[![مستندات به انگلیسی و فارسی](https://img.shields.io/badge/docs-English%20%7C%20Persian-0284c7?style=flat-square)](README.md)
[![حجم مخزن در گیت‌هاب](https://img.shields.io/badge/repo%20size-2.5%20MiB-ca8a04?style=flat-square)](#توسعه)
[![اجرا با Rust خالص بدون هیچ وابستگی پایتونی](https://img.shields.io/badge/runtime-pure%20Rust%20%7C%20zero%20Python-059669?style=flat-square)](#معماری)
[![گردش‌کار شش‌مرحله‌ای چندعاملی و ویرایش برش‌ها](https://img.shields.io/badge/workflow-6%20agents%20%7C%20crop%20edits-7c3aed?style=flat-square)](skills/revayat-comic/references/multi-agent-workflow.md)
[![راهنماهای لحن Humanizer ۴.۰ و فارسی همراه بسته](https://img.shields.io/badge/voice-Humanizer%204.0%20%7C%20Persian-b45309?style=flat-square)](skills/revayat-comic/references/voice/index.md)
[![حمایت مالی](https://img.shields.io/badge/Support-donations-d04a9a?style=flat-square)](#donate)

[English](README.md) · [فارسی](README.fa.md) · [مشخصات مهارت](skills/revayat-comic/SKILL.md) · [گردش‌کار شش‌مرحله‌ای](skills/revayat-comic/references/multi-agent-workflow.md) · [ویرایش نوشته‌های روی تصویر](skills/revayat-comic/references/fullpage-image-edit.md)

</div>

«روایت کمیک» یک ابزار خط فرمان خالص Rust (`revayat-comic`) همراه با مهارت عامل هوشمند برای ترجمهٔ کمیک و مانگا به فارسی روان است. این ابزار فایل‌های CBZ، CBR، PDF، پوشهٔ تصویر و تک‌صفحه را می‌خواند، پنل‌ها و حباب‌ها را پیدا می‌کند، برش‌های خوانا برای بازبینی متنی می‌سازد، متن اصلی را درون ماسک‌های کنترل‌شده پاک می‌کند، فارسی راست‌به‌چپ را با قلم وزیر حروف‌چینی می‌کند، صفحه را با دروازه‌های پیکسلی و چیدمان می‌سنجد و خروجی بی‌افت CBZ، PDF، پوشهٔ عکس یا DOCX دوزبانهٔ بازبینی تحویل می‌دهد.

## ویژگی‌های نسخهٔ ۲.۰

- بازنویسی کامل به Rust خالص با نسخهٔ ثابت `1.100.0` (`edition = "2024"` و `#![forbid(unsafe_code)]`) و حذف کامل پایتون، PyMuPDF، OpenCV و ابزارهای بیرونی unrar.
- خواندن، بررسی، رندر و ساخت PDF بی‌افت در Rust خالص با `lopdf`، `pdf-writer` و `hayro` به همراه کنترل بودجهٔ پیکسلی ماسک‌های شابلونی و Form XObject پیش از تخصیص حافظهٔ تصویر.
- پشتیبانی بومی و خالص Rust از آرشیو CBR (`rars`)، CBZ (`zip`) و فایل بازبینی DOCX راست‌به‌چپ (`quick-xml`).
- شکل‌دهی و راست‌به‌چپ‌سازی اصولی فارسی روی همهٔ سیستم‌عامل‌ها با `cosmic-text` (شکل‌دهی با HarfRust، ترتیب دوسویه با `unicode-bidi` و رندر با Swash) و قلم‌های وزیر همراه مخزن (`Regular`، `Medium` و `Bold`)، با حداقل فاصلهٔ سطر `1.38x`، پاک‌سازی کامل نقطه‌های جا‌مانده درون حباب و محافظ ضدتداخل متن.
- برای ویرایش نوشته‌های روی جلد، عنوان فصل و افکت‌های صوتی (`fullpage-prompt`)، اول حباب‌های گفت‌وگو را خالی کنید. نوشته را با تمام سایه‌ها و دورخط‌هایش ببرید و دور آن `120-240` پیکسل از تصویر را نگه دارید. برش را با متن اصلیِ بررسی‌شده و متن دقیق فارسی به مدل بدهید و نتیجهٔ تأییدشده را سر جای خودش برگردانید.
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

<a id="releases-and-tags"></a>

## انتشارها و برچسب‌ها

در [انتشارهای گیت‌هاب](https://github.com/KiaroSama/Revayat-Comic-Skill/releases) برای هر سیستم ۶۴ بیتی پشتیبانی‌شده یک فایل ZIP هست. برنامهٔ مستقل `revayat-comic` (لینوکس) یا `revayat-comic.exe` (ویندوز) را از آن بیرون بکشید. برای دیدن کد هر نسخه، به [برچسب‌های گیت‌هاب](https://github.com/KiaroSama/Revayat-Comic-Skill/tags) سر بزنید.

## نصب

### پیش‌نیازها

- اگر از افزونه استفاده می‌کنید، برنامه را در `PATH` بگذارید. برای اجرای مثال‌های پایین، آن را در پوشهٔ `bin/` در ریشهٔ مخزن بگذارید.
- برای ساخت از سورس: Rust نسخهٔ `1.100.0` (ثبت‌شده در `rust-toolchain.toml`)، `git` و PowerShell ۷ (`pwsh`) روی ویندوز یا Bash روی لینوکس.

### نصب افزونه

فایل ZIP انتشار، برنامهٔ خط فرمان را در خود دارد. مهارت را از تعریف‌های افزونه در مخزن یا با [نصب‌کنندهٔ مهارت](install/README.md) نصب کنید و `revayat-comic` را در `PATH` نگه دارید.

مخزن برای پنج نوع افزونه فایل تعریف نسخهٔ `2.0.6` دارد: Agent Plugins (`plugin.json` و `.agents/plugins/marketplace.json`)، Claude Code (`.claude-plugin/`)، Codex (`.codex-plugin/`)، Cursor (`.cursor-plugin/`) و Antigravity (`.antigravity-plugin/`).

در Claude Code:

</div>

```text
/plugin marketplace add KiaroSama/Revayat-Comic-Skill
/plugin install revayat-comic@revayat-comic-skill
```

<div dir="rtl">

### ساخت از سورس

ویندوز (PowerShell ۷):

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

دستور `import` فایل `comic.json` را می‌سازد و صفحه‌های اصلی را در پوشهٔ `pages/` می‌گذارد. مرحله‌های بعد فایل‌های جداگانه می‌نویسند و به صفحه‌های اصلی دست نمی‌زنند.

ویندوز (PowerShell ۷):

</div>

```powershell
.\bin\revayat-comic.exe import chapter.cbz --out .\work --direction rtl
.\bin\revayat-comic.exe detect --doc .\work\comic.json
.\bin\revayat-comic.exe mask --doc .\work\comic.json
.\bin\revayat-comic.exe crops --doc .\work\comic.json
.\bin\revayat-comic.exe worksheet build --doc .\work\comic.json --worksheets .\work\worksheets
```

<div dir="rtl">

پس از پر کردن برگه‌های ترجمه (دستی یا با گردش‌کار شش‌مرحله‌ای):

</div>

```powershell
.\bin\revayat-comic.exe worksheet merge --doc .\work\comic.json --worksheets .\work\worksheets
.\bin\revayat-comic.exe glossary check --doc .\work\comic.json
.\bin\revayat-comic.exe falint check --doc .\work\comic.json
.\bin\revayat-comic.exe mask --doc .\work\comic.json
.\bin\revayat-comic.exe clean --doc .\work\comic.json
.\bin\revayat-comic.exe typeset --doc .\work\comic.json
.\bin\revayat-comic.exe qa check --doc .\work\comic.json --strict
.\bin\revayat-comic.exe export --doc .\work\comic.json --out .\work\chapter-fa.cbz
.\bin\revayat-comic.exe qa package --doc .\work\comic.json --package .\work\chapter-fa.cbz
```

<div dir="rtl">

دستور `export` قالب را از مسیر خروجی تشخیص می‌دهد: فایل `.cbz`، فایل `.pdf` یا پوشه.

دستورهای دیگر:

- `fullpage-prompt --doc <comic.json> --page <id>`: اطلاعات صفحه را برای ویرایش برش‌ها در خروجی استاندارد می‌نویسد. مدل پیش‌فرض `antigravity/gemini-3.1-flash-image` است.
- `review-docx --doc <comic.json> --out <review.docx>`: خروجی فایل Word دوزبانهٔ بازبینی با جهت راست‌به‌چپ.
- `watermark --doc <comic.json> ...`: مشخص‌کردن کادر دقیق واترمارک مجاز برای حذف.
- `batch plan|merge|status`: تقسیم فصل‌های بلند به بخش‌های موازی و ادغام امن.
- `voice lint <file> --check --style` نگارش فارسی را بررسی می‌کند و `voice lookup <text>` واژه‌نامه را جست‌وجو می‌کند. `falint` و `voice lint` به‌طور پیش‌فرض ارقام انگلیسی را به کار می‌برند. برای انتخاب ارقام فارسی، `--digits persian` را اضافه کنید.
- `serve --stdio` سرور MCP را راه می‌اندازد. برای HTTP محلی، `REVAYAT_HTTP_TOKEN` را تنظیم کنید و `serve --http 127.0.0.1:8765` را اجرا کنید.
- `ocr` و `translate`: کمک‌ابزار اختیاری مدل‌های میزبانی‌شده (نیازمند نشانی HTTPS و توکن Bearer).
- `install` و `eval`: نصب تراکنشی مهارت و ارزیابی با نمونه‌های ساختگی.

### گردش‌کار شش‌مرحله‌ای چندعاملی

برای ترجمهٔ کامل فصل‌ها، راهنمای [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md) شش نقش مشخص دارد:

۱. ترجمهٔ اولیه: جست‌وجوی نام‌های رسمی شخصیت‌ها و اصطلاحات مجموعه پیش از شروع، و ترجمه به فارسی گفتاری روان.
۲. صفحه‌آرایی: تنظیم سطرشکن، نشانه‌گذاری، مقیاس قلم و ناحیه‌های ویرایش روی تصویر.
۳. بازبینی: تطبیق دقیق با برش‌های اصلی، یکدستی واژه‌نامه و سلامت نگارشی.
۴. اعمال ترجمه: ادغام برگه‌ها، اجرای `clean` و `typeset` و نشاندن برش‌های تأییدشده در جای اصلی خود روی صفحه.
۵. چک مجدد فایل و اصلاح مشکلات: بازبینی چشمی همهٔ صفحه‌ها، اجرای `qa check --strict` و رفع یک‌جای همهٔ ایرادها.
۶. بازبینی نهایی و تحویل: ساخت خروجی بی‌افت CBZ و PDF و تایید بسته با `qa package`.

### لاگ‌های اجرا

دستورهای خط لوله جزئیات اجرا و وضعیت خروج را با کدگذاری UTF-8 در `logs/revayat-comic_YYYY-MM-DD_HH-mm-ss_UTC.log` می‌نویسند. پوشهٔ `logs/` کنار `bin/` قرار می‌گیرد. اگر برنامه در پوشه‌ای با نام دیگری باشد، `logs/` کنار خود برنامه ساخته می‌شود. پیش از پیوست‌کردن گزارش اجرا به گزارش خطا، محتوایش را مرور کنید.

## مستندات

- [SKILL.md](skills/revayat-comic/SKILL.md): گردش‌کار کامل عامل و جدول کدهای QA
- [references/multi-agent-workflow.md](skills/revayat-comic/references/multi-agent-workflow.md): نقش‌های شش‌مرحله‌ای و قالب پرامپت‌ها
- [references/fullpage-image-edit.md](skills/revayat-comic/references/fullpage-image-edit.md): ویرایش برش‌ها و ترمیم لبه‌ها پس از خالی‌کردن حباب‌ها
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

در مخزن صفحه‌ای از کمیک‌های تحت حق نشر نگه نمی‌داریم. آزمون‌ها از نمونه‌های ساختگی استفاده می‌کنند. گردش‌کارهای GitHub Actions هر چهار هدف ۶۴ بیتی لینوکس و ویندوز را می‌سازند، نسخهٔ مانیفست‌های افزونه را می‌سنجند و اسکن‌های CodeQL، Gitleaks، Semgrep و بررسی وابستگی‌ها را اجرا می‌کنند.

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
