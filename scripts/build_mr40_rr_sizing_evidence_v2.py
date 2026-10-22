"""Assemble fixed-run evidence and a Persian report; never fetch or trade."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import importlib.util
import io
import json
import lzma
from pathlib import Path
import shutil
import zipfile


def canonical(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def sha(x):return hashlib.sha256(x).hexdigest()


def build(source,run,inputs,bundle):
    if bundle.exists():raise ValueError("refuse_bundle_overwrite")
    r=json.loads((run/"results.json").read_bytes())
    policy=json.loads((source/"research/mr40_rr_sizing_v2.json").read_bytes())
    if sha(canonical({k:v for k,v in r.items() if k!="result_digest"}))!=r["result_digest"]:raise ValueError("result_changed")
    ev=source/"docs/evidence/mr40-rr-sizing-20261022";ev.mkdir(exist_ok=True,parents=True)
    report_path=source/"docs/research/MR40_RR_SIZING_20261022_FA.md"
    def metric(case,window="full",profile="normal",capital=10000):
        return next(x for x in r["results"] if x["case"]==case and x["window"]==window and x["profile"]==profile and x["capital_usdt"]==capital)
    def fmt(v):return "—" if v is None else f"{v:,.2f}"
    names=["baseline_a100","baseline_a50","baseline_a25","confirm_natural_a100","b_rr2_r1","c_rr3_r1","c_trail2_r1","c_partial3_r1"]
    labels=["نسخهٔ اصلی، ورود ۱۰۰٪","نسخهٔ اصلی، ورود ۵۰٪","نسخهٔ اصلی، ورود ۲۵٪","تأیید برگشت، خروج اصلی","ورود اصلی، RR=2، ریسک ۱٪","تأیید برگشت، RR=3، ریسک ۱٪","تأیید برگشت، حد متحرک، ریسک ۱٪","تأیید برگشت، خروج پله‌ای، ریسک ۱٪"]
    summary={"schema":"nexus.mr40-rr-sizing-summary.v2","result_digest":r["result_digest"],"protocol_commit":r["protocol_commit"],"code_commit":r["code_commit"],
        "selection":r["selection"],"evaluation_profit_success":r["evaluation_profit_success"],"evaluation_efficiency_success":r["evaluation_efficiency_success"],
        "main_ledger_replays":r["main_ledger_replays"],"diagnostic_ledger_replays":r["diagnostic_ledger_replays"],"prefix_checks":r["prefix_checks"],
        "baseline_parity_checks":r["baseline_parity_checks"],"data":r["data"],"walk_forward_compounded_pnl_10000":r["walk_forward_compounded_pnl_10000"],
        "full_normal_all_cases":[metric(c["id"]) for c in policy["cases"]],
        "key_comparisons":[metric(n,w,p,cap) for n in names for w in ("evaluation","lbank30") for p in ("normal","stress") for cap in (10000,500)],"authority":r["authority"],"classification":r["classification"]}
    (ev/"summary.json").write_bytes(canonical(summary)+b"\n")
    lines=["# آزمایش جداگانهٔ MR40: آر‌آر، حجم ورود و ترکیب سیستم‌ها","",
        "**نتیجه: در ۲۷ مسیر ازپیش‌ثبت‌شده، هیچ نامزد تازه‌ای معیار بهبود سود یا راندمان را در مرحلهٔ انتخاب پاس نکرد. هر دو انتخاب به نسخهٔ اصلی برگشتند.** کاهش حجم افت را کمتر کرد، اما سود هم کم شد. چند ترکیب کم‌افت‌تر بودند، ولی بخش عمدهٔ بازده یا دوام در سناریوی هزینهٔ بالاتر را از دست دادند.","",
        "این مطالعه دربارهٔ MR40 با ورود Z≤−2، خروج اصلی Z≥0 و فیلتر مومنتوم ۳۰روزه است؛ خرید نقدی BTC/USDT روی کندل چهارساعته، بدون اهرم. سودها خالص و به USDT هستند.","",
        "## مقایسهٔ کل دوره","","از ۱ ژانویهٔ ۲۰۲۳ تا پیش از ۲۰ اکتبر ۲۰۲۶؛ سرمایهٔ مستقل ۱۰٬۰۰۰ تتر. دادهٔ اصلی Bybit با فرض‌های هزینه و محدودیت سفارش البانک؛ این بخش، سابقهٔ بلندمدت خود البانک نیست.","",
        "| سیستم | سود عادی | بیشترین افت بسته‌شدن کندل | سود با هزینهٔ سختگیرانه | رشد سالانهٔ مرکب عادی |","|---|---:|---:|---:|---:|"]
    for n,label in zip(names,labels):
        a=metric(n);b=metric(n,profile="stress")
        lines.append(f"| {label} | {fmt(a['net_pnl_usdt'])} | {fmt(a['max_close_drawdown_pct'])}٪ | {fmt(b['net_pnl_usdt'])} | {fmt(a['cagr_pct'])}٪ |")
    a=metric("baseline_a100");half=metric("baseline_a50");c=metric("c_rr3_r1")
    lines += ["",f"ورود ۵۰٪، افت را از {fmt(a['max_close_drawdown_pct'])}٪ به {fmt(half['max_close_drawdown_pct'])}٪ رساند و سود را از {fmt(a['net_pnl_usdt'])} به {fmt(half['net_pnl_usdt'])} کاهش داد. مدت زیر قله ماندن در سناریوی عادی همچنان حدود {fmt(half['longest_underwater_days'])} روز بود؛ حجم کمتر لزوماً زمان بازیابی را کوتاه نمی‌کند.","",
        f"تأیید برگشت + RR=3 + ریسک ۱٪، در کل دوره {fmt(c['net_pnl_usdt'])} سود و {fmt(c['max_close_drawdown_pct'])}٪ افت داشت، اما در انتخاب آموزشی به حداقل حفظ ۷۵٪ رشد سالانهٔ نسخهٔ اصلی نرسید. این ترکیب صرفاً یک نتیجهٔ اکتشافی است و به‌عنوان برنده انتخاب نشده است.","",
        "![سود، افت و منحنی حساب](../evidence/mr40-rr-sizing-20261022/equity_drawdown.png)","",
        "## بخش ارزیابی و البانک","","ارزیابی: ۱ ژانویهٔ ۲۰۲۵ تا پیش از ۲۰ اکتبر ۲۰۲۶. البانک: ۲۱ سپتامبر تا پیش از ۲۱ اکتبر ۲۰۲۶، فقط دو معامله در نسخه‌های نشان‌داده‌شده. حساب هر پنجره از سرمایهٔ اولیهٔ خودش شروع می‌شود؛ سود پنجره‌ها قابل جمع ساده نیست.","",
        "| سیستم | ارزیابی عادی، ۱۰هزار | ارزیابی سختگیرانه، ۱۰هزار | البانک ۳۰روزه عادی، ۱۰هزار | البانک ۳۰روزه عادی، ۵۰۰ |","|---|---:|---:|---:|---:|"]
    for n,label in zip(names,labels):lines.append(f"| {label} | {fmt(metric(n,'evaluation')['net_pnl_usdt'])} | {fmt(metric(n,'evaluation','stress')['net_pnl_usdt'])} | {fmt(metric(n,'lbank30')['net_pnl_usdt'])} | {fmt(metric(n,'lbank30',capital=500)['net_pnl_usdt'])} |")
    lines += ["","روی البانک، حد ضرر ۲ATR در دو معامله فعال شد؛ بالاتر بردن هدف سود از ۱R به ۳R کمکی نکرد، چون معامله پیش از رسیدن به هدف متوقف شد. سود نسخهٔ اصلی با خروج میانگین، با سود فرضی معاملات دارای حد ضرر یکسان نیست.","",
        "تأیید برگشت با خروج اصلی در بخش ارزیابی بهتر بود، ولی در آموزش و افت کل سابقه برنده نبود. انتخاب آن پس از دیدن این بخش، یک انتخاب پس از مشاهدهٔ نتیجه خواهد بود.","",
        "## اندازهٔ ورود و آر‌آر","",
        "ورود ۲۵٪/۵۰٪/۱۰۰٪ یعنی کسری از نقد موجود. ریسک ۰٫۵٪/۱٪/۲٪ یعنی زیان اسمیِ برآوردشده تا حد ضرر اولیه، با هر دو کارمزد و لغزش، به‌عنوان کسری از حساب. حجم به نقد موجود محدود شده و اهرم ندارد. با تغییر سناریوی هزینه، حجم مدل ریسک ثابت هم دوباره محاسبه می‌شود؛ سناریوهای هزینه لزوماً تعداد BTC یکسانی نمی‌خرند.","",
        "| ورود اصلی، RR=2 | میانهٔ درصد سرمایهٔ درگیر | سود کل عادی | افت کل عادی | سود کل سختگیرانه |","|---|---:|---:|---:|---:|"]
    for n,label in (("b_rr2_r05","ریسک ۰٫۵٪"),("b_rr2_r1","ریسک ۱٪"),("b_rr2_r2","ریسک ۲٪")):
        x=metric(n);lines.append(f"| {label} | {fmt(x['median_entry_allocation_pct'])}٪ | {fmt(x['net_pnl_usdt'])} | {fmt(x['max_close_drawdown_pct'])}٪ | {fmt(metric(n,profile='stress')['net_pnl_usdt'])} |")
    lines += ["","آر‌آر تنظیم‌شده فاصلهٔ قیمتِ هدف نسبت به فاصلهٔ حد ضرر است، نه نسبت سود و زیان خالص تحقق‌یافته. در RR=2 با ریسک ۱٪ و ورود اصلی، میانهٔ RR خالص برنامه‌ریزی‌شده در کل دوره حدود "+fmt(metric("b_rr2_r1")["median_net_planned_rr"])+" بود. نصف خروج در ۱R و نصف در ۳R، پیش از هزینه‌ها تقریباً ۲R پاداش برنامه‌ریزی‌شده می‌دهد. نسبت متوسط برد به باخت تحقق‌یافته جداگانه در JSON ثبت شده است.","",
        f"بیشترین زمان نگهداری نسخهٔ اصلی {fmt(a['max_holding_hours_upper'])} ساعت، یعنی ۹ روز و ۱۲ ساعت بود. برای ورود اصلی با RR=2، این کران به {fmt(metric('b_rr2_r1')['max_holding_hours_upper'])} ساعت، یعنی ۲۳ روز و ۲۰ ساعت رسید. هدف ثابت می‌تواند سرمایه را مدت بیشتری درگیر کند. زمان خروج داخل کندل به‌صورت بازهٔ چهارساعته ثبت می‌شود؛ این اعداد کران بالای زمان هستند.","",
        "## حساسیت به اجرای سفارش","",
        "| سیستم | اجرای داخل کندل: سود / افت | یک کندل تأخیر اضافه: سود / افت | تأیید بسته‌شدن و اجرای بازشدن بعد: سود / افت |","|---|---:|---:|---:|"]
    for n,label in zip(names[4:],labels[4:]):
        values=[metric(n,profile=p) for p in ("normal","extra_4h_delay","close_confirmed")]
        lines.append("| "+label+" | "+" | ".join(fmt(x['net_pnl_usdt'])+" / "+fmt(x['max_close_drawdown_pct'])+"٪" for x in values)+" |")
    lines += ["","در حالت اصلی، حدها می‌توانند داخل کندل فعال شوند؛ گپ نامطلوب در قیمت بازشدن پر می‌شود، گپ مطلوب فقط قیمت هدف را می‌گیرد و اگر حد ضرر و سود در یک کندل لمس شوند، حد ضرر اول است. حد متحرک و سر‌به‌سر فقط از کندل بسته‌شدهٔ پس از ورود استفاده می‌کنند. دادهٔ تیک، عمق بازار، صف سفارش و پرشدن جزئی بازار مدل نشده‌اند؛ بازهٔ OHLC به‌تنهایی ترتیب واقعی قیمت‌ها را مشخص نمی‌کند.","",
        "در این داده‌ها هیچ کندل دوحدی ثبت نشد؛ آزمون حساسیت ترتیب فقط برای انتخاب‌های قفل‌شده و نسخهٔ اصلی انجام شد. این صفر بودن، نبود ابهام یا لغزش در بازار واقعی را اثبات نمی‌کند. با اجرای پس از بسته‌شدن، زیان بعضی معاملات با ریسک اسمی ۱٪ به بیش از ۲٪ حساب رسید. سر‌به‌سر و ریسک ثابت تضمین زیان صفر یا سقف زیان نیستند.","",
        "فرض هزینهٔ هر سمت: عادی کارمزد ۰٫۱۰٪ + لغزش ۰٫۰۵٪؛ سختگیرانه کارمزد ۰٫۲۵٪ + لغزش ۰٫۱۵٪. نرخ حساب شخصی و لغزش تاریخی واقعی در دسترس نیست؛ این‌ها سناریوهای مدل‌اند. حداقل سفارش ۱ USDT و گام ۰٫۰۰۰۰۱ BTC با قواعد فعلی به گذشته تعمیم داده شده‌اند.","",
        "## روش انتخاب و آزمون زمانی","",
        "آموزش: ۲۰۲۳ و ۲۰۲۴. انتخاب سود باید سود عادی حداقل برابر پایه، سود سختگیرانه حداقل ۵٪ بیشتر و افت حداکثر ۱۰٪ بیشتر از پایه داشته باشد. انتخاب راندمان، نسبت رشد سالانهٔ بدترِ دو سناریو به افت بدتر را بیشینه می‌کند؛ حداقل ۷۵٪ رشد سالانهٔ عادی پایه، افت حداکثر برابر پایه و بهبود حداقل ۱۰٪ این نسبت لازم است. کنترل‌های حجم ۲۵٪ و ۵۰٪ از رقابت انتخاب کنار گذاشته شده‌اند. هیچ مسیر جدیدی واجد شرایط نشد.","",
        "شش مرحلهٔ walk-forward با آموزش فقط بر گذشته و حساب مستقل در هر مرحله انجام شد. هزینهٔ بستن حساب هر مرحله محاسبه شده و بازده‌ها هندسی ترکیب شده‌اند؛ این مدل تحویل اجباری مرحله‌ای است، نه یک حساب پیوستهٔ بدون بستن.","",
        "| روش انتخاب | سود مرکب مراحل با شروع ۱۰هزار، عادی | سختگیرانه |","|---|---:|---:|"]
    for method,label in (("baseline","پایهٔ ثابت"),("profit","انتخاب سود از گذشته"),("efficiency","انتخاب راندمان از گذشته")):
        lines.append(f"| {label} | {fmt(r['walk_forward_compounded_pnl_10000']['normal/'+method])} | {fmt(r['walk_forward_compounded_pnl_10000']['stress/'+method])} |")
    lines += ["","انتخاب‌های دو روش در این شش مرحله یکسان شدند: نیمهٔ اول ۲۰۲۴، تأیید برگشت با خروج اصلی؛ پنج مرحلهٔ بعد، نسخهٔ اصلی. انتخاب متغیر از پایهٔ ثابت ضعیف‌تر شد.","",
        "تمام این سابقه در پژوهش‌های قبلی دیده شده بود. این یک جست‌وجوی پارامتر گذشته‌نگر با ۲۷ مسیر ازپیش‌ثبت‌شده است؛ تقسیم زمانی و walk-forward به‌معنای دادهٔ کاملاً دیده‌نشده نیستند. ۱٬۷۳۱ اجرای مدل نیز ۱٬۷۳۱ نمونهٔ مستقل بازار نیست.","",
        "## جدول کامل ۲۷ مسیر","","b یعنی ورود اصلی؛ c یعنی تأیید برگشت حداکثر در سه تصمیم اول مجاز. rr هدف ثابت؛ hybrid زودتر از هدف یا خروج اصلی؛ be سر‌به‌سر پس از بسته‌شدن ۱R؛ trail حد متحرکِ بسته‌شدن−۲ATR؛ partial نصف در ۱R، بقیه در ۳R. a درصد نقد و r درصد ریسک اسمی را نشان می‌دهد. تمام مسیرهای حددار حد ضرر اولیهٔ ۲ATR20 دارند.","",
        "| شناسه | آموزش عادی | آموزش سختگیرانه | ارزیابی عادی | ارزیابی سختگیرانه | کل عادی | افت کل عادی | کل سختگیرانه |","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for case in policy["cases"]:
        n=case["id"];vals=[metric(n,w,p)["net_pnl_usdt"] for w,p in (("training","normal"),("training","stress"),("evaluation","normal"),("evaluation","stress"),("full","normal"))]
        lines.append("| "+n+" | "+" | ".join(fmt(x) for x in vals)+" | "+fmt(metric(n)["max_close_drawdown_pct"])+"٪ | "+fmt(metric(n,profile="stress")["net_pnl_usdt"])+" |")
    lines += ["","## داده، بازتولید و محدودهٔ نتیجه","",
        "۸٬۵۱۴ کندل پیوستهٔ Bybit و ۶۷۲ کندل معتبر البانک شامل گرم‌کردن، با هش ثابت دوباره استفاده شدند. تاریخ پایان همهٔ پنجره‌ها انحصاری و مبنای داده UTC است. سابقهٔ بلند البانک به‌علت سه ناسازگاری OHLC رد شد و در این مطالعه وارد نشد؛ کندلی اصلاح، حذف یا پر نشده است. صحت یک فریم Bybit، برابری اجرای آن با بازار البانک را ثابت نمی‌کند.","",
        "افت گزارش‌شده بر اساس ارزش حساب در بسته‌شدن کندل چهارساعته است؛ می‌تواند افت واقعی داخل کندل را کمتر نشان دهد. سود کل با سود ماهانه یکسان نیست. معیار اصلی، سود بیشتر با ریسک قابل مقایسه بود و محقق نشد؛ کم‌کردن ریسک بدون حفظ بازده، به‌عنوان بهبود واجد شرایط اعلام نشده است.","",
        "کنترل‌ها: ۲۱ آزمون اجرای جدید + ۹ آزمون قبلی، ۱٬۷۲۸ بازسازی دفتر اصلی + ۳ تشخیصی، ۱۰۸ مقایسهٔ برش زمانی و ۱۲ برابری دقیق منحنی پایه با موتور قبلی؛ بیشترین خطای برابری پایه صفر بود. هشت فایل اجرای Paper با هش قبلی برابر ماندند. بازپخش کامل از ZIP استخراج‌شده با Python و بدون شبکه قابل اجراست.","",
        "قواعد پیش از اجرای اولیه در commit پروتکل ثبت شدند و موتور اولیه نیز پیش از محاسبه منتشر شد. پس از اجرای اولیه فقط شاخص پاداش برنامه‌ریزی‌شدهٔ خروج پله‌ای اصلاح شد تا دو خروج را با وزن واقعی جمع کند. این اصلاح هیچ سفارش، سود، افت یا انتخابی را تغییر نداد؛ تطابق دفترها و تمام معیارهای دیگر در بازاجرای نهایی کنترل شد.","",
        f"- پروتکل: `{r['protocol_commit']}`",
        "- موتور اولیه: `a1b26dfb0d5f6330b4b8bd12336d8e9b6380a07a`",
        f"- موتور نهاییِ تصحیح شاخص: `{r['code_commit']}`",
        f"- هش نتیجه: `{r['result_digest']}`",
        f"- هش ردیف‌های Bybit: `{r['data']['Bybit']['rows_sha256']}`",
        f"- هش ردیف‌های البانک: `{r['data']['LBank']['rows_sha256']}`","",
        "فایل summary.json جدول‌های کلیدی را نگه می‌دارد؛ ZIP شامل منبع، ورودی‌های ثابت، تمام معیارها، دفترها، منحنی‌ها و verify_replay.py است. اجرای دمو و سفارش واقعی از این پژوهش تغییری نمی‌گیرد و هیچ نسخه‌ای خودکار ارتقا نمی‌یابد.","",
        "منابع توضیح مدل هزینه و محدودیت OHLC: [LBank](https://www.lbank.com/support/articles/42227167714585)، [مستندات API البانک](https://www.lbank.com/docs/)، [مدل اجرای کندل TradingView](https://www.tradingview.com/pine-script-docs/concepts/strategies/). نتایج عددی از اجرای کد و ورودی‌های بستهٔ پیوست‌اند.",""]
    report_path.write_text("\n".join(lines),encoding="utf-8")
    # Static research figure. All plotted points use the same full-history window.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    curves=json.loads((run/"full_normal_curves.json").read_bytes())
    curves_names=["baseline_a100","baseline_a50","confirm_natural_a100","c_rr3_r1"]
    curve_labels=["Original, 100% cash","Original, 50% cash","Confirm + original exit","Confirm + 3R, 1% risk"]
    colors=["#155e75","#6b7280","#d97706","#7c3aed"]
    times=[datetime.fromtimestamp((metric("baseline_a100")["start_ms"]+(i+1)*14_400_000)/1000,timezone.utc) for i in range(len(curves["baseline_a100"]))]
    fig,(ax,dd,sc)=plt.subplots(3,1,figsize=(12,11),gridspec_kw={"height_ratios":[1.3,.8,1.1]},layout="constrained")
    for name,label,color in zip(curves_names,curve_labels,colors):
        values=np.array(curves[name]);ax.plot(times,values,label=label,color=color,lw=1.25)
        peaks=np.maximum.accumulate(np.r_[10000,values])[1:]
        dd.plot(times,100*(values/peaks-1),color=color,lw=1)
    ax.set(title="MR40: RR and position sizing | retrospective, 2023-01-01 to 2026-10-20",ylabel="Account value (USDT)")
    ax.legend(loc="upper left",ncol=2,fontsize=9);ax.axhline(10000,color="#9ca3af",lw=.6)
    dd.set(ylabel="Close drawdown (%)")
    for axes in (ax,dd):
        axes.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"));axes.grid(alpha=.18)
    for case in policy["cases"]:
        x=metric(case["id"]);sc.scatter(x["max_close_drawdown_pct"],x["net_pnl_usdt"],c="#b8c4ce" if case["entry"]=="baseline" else "#b7a4e4",s=35)
    for name,label,color in zip(curves_names,curve_labels,colors):
        x=metric(name);sc.scatter(x["max_close_drawdown_pct"],x["net_pnl_usdt"],c=color,s=60)
        sc.annotate(label,(x["max_close_drawdown_pct"],x["net_pnl_usdt"]),xytext=(5,6 if name!="confirm_natural_a100" else -18),textcoords="offset points",fontsize=8)
    sc.set(xlabel="Maximum close drawdown (%)",ylabel="Net PnL (USDT)",title="All 27 paths, normal cost scenario | lower drawdown can mean much less profit")
    sc.set_xlim(0,28);sc.grid(alpha=.18);sc.axhline(0,color="#9ca3af",lw=.6)
    image_buffer=io.BytesIO()
    fig.savefig(image_buffer,format="png",dpi=160);plt.close(fig)
    png=image_buffer.getvalue()
    from PIL import Image
    Image.open(io.BytesIO(png)).verify()
    (ev/"equity_drawdown.png").write_bytes(png)
    bundle.mkdir(parents=True)
    manifest=json.loads((source/"docs/evidence/mr40-lbank-paper-activation-20261021/SOURCE_MANIFEST.json").read_bytes())
    paths=list(manifest["files"])+["research/nexus_mr40_isolated_improvement_v1.py","research/mr40_isolated_improvement_v1.json","tests/test_nexus_mr40_isolated_improvement_v1.py","research/nexus_mr40_rr_sizing_v2.py","research/mr40_rr_sizing_v2.json","tests/test_nexus_mr40_rr_sizing_v2.py"]
    for relative in paths:
        target=bundle/"source"/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/relative,target)
    for relative in ("lbank_kline_response.json","source_receipt.json"):
        target=bundle/"source/docs/evidence/lbank-mr40-exact30-20261021"/relative;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/"docs/evidence/lbank-mr40-exact30-20261021"/relative,target)
    for name in ("bybit_prepared_inputs.json","bybit_october_input_extension.json"):
        (bundle/"inputs").mkdir(exist_ok=True);shutil.copyfile(inputs/name,bundle/"inputs"/name)
    (bundle/"recorded").mkdir()
    for name in ("results.json","selection.json","full_normal_curves.json"):shutil.copyfile(run/name,bundle/"recorded"/name)
    objects={};runs={}
    for line in gzip.open(run/"all_runs.jsonl.gz","rb"):
        x=json.loads(line);refs=[]
        for f in x["fills"]:
            key=sha(canonical(f));objects[key]=f;refs.append(key)
        positions=[]
        for p in x["positions"]:
            q={k:v for k,v in p.items() if k not in ("entry","exit")}
            q.update(entry_ref=sha(canonical(p["entry"])),exit_ref=sha(canonical(p["exit"])));positions.append(q)
        if x["key"] in runs:raise ValueError("duplicate_run")
        runs[x["key"]]={"fill_refs":refs,"positions":positions,"equity_sha256_6dp":x["equity_sha256_6dp"]}
    with lzma.open(bundle/"recorded/all_ledgers.json.xz","wb",preset=6) as f:f.write(canonical({"schema":"nexus.mr40-rr-sizing-ledgers.v2","objects":objects,"runs":runs}))
    for relative,target in ((ev/"equity_drawdown.png","equity_drawdown.png"),(ev/"summary.json","summary.json"),(ev/"verify_replay.py","verify_replay.py"),(ev/"metric_correction_receipt.json","metric_correction_receipt.json")):
        shutil.copyfile(relative,bundle/target)
    (bundle/report_path.name).write_text(report_path.read_text().replace("../evidence/mr40-rr-sizing-20261022/equity_drawdown.png","equity_drawdown.png"),encoding="utf-8")
    (bundle/"README.md").write_text("# MR40 RR and sizing evidence\n\nExtract the ZIP, then run `python verify_replay.py` with Python 3.12+. No network or external packages are needed for replay. The full study takes about a minute on the reference machine.\n\n27 retrospective paths; 1,728 primary and 3 diagnostic runs. Selection retained the original system. No Live or Paper changes. Intrabar event timestamps are intervals.\n\nThe Persian report and summary.json describe assumptions and limitations. This bundle contains validated input frames, not all original exchange trade gzip archives; provenance and their hashes remain in the input records.\n",encoding="utf-8")
    files={str(p.relative_to(bundle)):{"bytes":p.stat().st_size,"sha256":sha(p.read_bytes())} for p in sorted(bundle.rglob("*")) if p.is_file()}
    (bundle/"MANIFEST.json").write_bytes(canonical({"schema":"nexus.mr40-rr-sizing-bundle.v2","files":files})+b"\n")
    archive=ev/"NEXUS_MR40_RR_Sizing_20261022.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():z.write(p,p.relative_to(bundle),compress_type=zipfile.ZIP_STORED if p.suffix==".xz" else zipfile.ZIP_DEFLATED)
    receipt={"archive":archive.name,"bytes":archive.stat().st_size,"sha256":sha(archive.read_bytes()),"files":len(files)+1,"result_digest":r["result_digest"],"research_only":True}
    (ev/"bundle_receipt.json").write_bytes(canonical(receipt)+b"\n")
    print(json.dumps(receipt),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("source","run","inputs","bundle"):p.add_argument("--"+key,type=Path,required=True)
    build(**vars(p.parse_args()))
