"""Package an existing, immutable adaptive-sizing run; no market or order API."""
import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import shutil
import zipfile


def canonical(x):return json.dumps(x,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()
def sha(x):return hashlib.sha256(x).hexdigest()


def build(source,run,inputs,bundle):
    if bundle.exists():raise ValueError("refuse_bundle_overwrite")
    r=json.loads((run/"results.json").read_bytes());policy=json.loads((source/"research/mr40_adaptive_sizing_v3.json").read_bytes())
    if sha(canonical({k:v for k,v in r.items() if k!="result_digest"}))!=r["result_digest"]:raise ValueError("result_changed")
    ev=source/"docs/evidence/mr40-adaptive-sizing-20261022";ev.mkdir(parents=True,exist_ok=True)
    report_path=source/"docs/research/MR40_ADAPTIVE_SIZING_20261022_FA.md"
    def metric(name,window="full",profile="normal",capital=10000):
        return next(x for x in r["results"] if x["case"]==name and x["window"]==window and x["profile"]==profile and x["capital_usdt"]==capital)
    def fmt(x):return "—" if x is None else f"{x:,.2f}"
    base=metric("baseline_a100");candidate=r["selection"]["efficiency"];pick=metric(candidate)
    bn=metric("baseline_a100","evaluation");pn=metric(candidate,"evaluation");bs=metric("baseline_a100","evaluation","stress");ps=metric(candidate,"evaluation","stress")
    keep=pick["net_pnl_usdt"]/base["net_pnl_usdt"]*100
    dd_change=(1-pick["max_close_drawdown_pct"]/base["max_close_drawdown_pct"])*100
    evaluation={"candidate":candidate,"profit_retention_pct":pn["net_pnl_usdt"]/bn["net_pnl_usdt"]*100,
        "normal_dd_reduction_pct":(1-pn["max_close_drawdown_pct"]/bn["max_close_drawdown_pct"])*100,
        "normal_pnl_required_min":.75*bn["net_pnl_usdt"],"normal_dd_required_max":.80*bn["max_close_drawdown_pct"],
        "normal_pnl_retention_pass":pn["net_pnl_usdt"]>=.75*bn["net_pnl_usdt"],"normal_dd_pass":pn["max_close_drawdown_pct"]<=.80*bn["max_close_drawdown_pct"]}
    def score(n):
        a=metric(n,"evaluation");b=metric(n,"evaluation","stress")
        return min(a["cagr_pct"],b["cagr_pct"])/max(a["max_close_drawdown_pct"],b["max_close_drawdown_pct"])
    evaluation.update(candidate_efficiency_score=score(candidate),baseline_efficiency_score=score("baseline_a100"),required_min_efficiency_score=1.10*score("baseline_a100"))
    compact_keys=("case","venue","window","profile","capital_usdt","net_pnl_usdt","max_close_drawdown_pct","cagr_pct","median_entry_allocation_pct","min_entry_allocation_pct","closed_positions","longest_underwater_days","max_holding_hours")
    summary={"schema":"nexus.mr40-adaptive-sizing-summary.v3","protocol_commit":r["protocol_commit"],"code_commit":r["code_commit"],"result_digest":r["result_digest"],
        "selection":r["selection"],"evaluation_profit_success":r["evaluation_profit_success"],"evaluation_efficiency_success":r["evaluation_efficiency_success"],"evaluation_details":evaluation,
        "main_ledger_replays":r["main_ledger_replays"],"prefix_checks":r["prefix_checks"],"control_parity_checks":r["control_parity_checks"],"data":r["data"],
        "walk_forward_compounded_pnl_10000":r["walk_forward_compounded_pnl_10000"],"walk_forward_selections":[{"start":f["start"],"end_exclusive":f["end_exclusive"],"profit":f["selection"]["profit"],"efficiency":f["selection"]["efficiency"]} for f in r["walk_forward"]],
        "metrics":[{k:x[k] for k in compact_keys} for x in r["results"] if x["window"] in ("training","evaluation","full","year2026","lbank30")],"classification":r["classification"],"authority":r["authority"]}
    (ev/"summary.json").write_bytes(canonical(summary)+b"\n")
    names={"baseline_a100":"نسخهٔ اصلی، ورود کامل","baseline_a50":"نسخهٔ اصلی، ورود نصف","confirm_natural_a100":"تأیید برگشت، ورود کامل","b_vol30":"هدف نوسان ۳۰٪","b_vol40":"هدف نوسان ۴۰٪","b_vol50":"هدف نوسان ۵۰٪","c_vol40":"تأیید برگشت + نوسان ۴۰٪","b_dd5_a50":"نصف حجم پس از افت ۵٪","b_dd10_a50":"نصف حجم پس از افت ۱۰٪","b_vol40_dd5":"نوسان ۴۰٪ + افت ۵٪","c_vol40_dd5":"تأیید + نوسان ۴۰٪ + افت ۵٪"}
    lines=["# ادامهٔ پژوهش MR40: حفظ خروج اصلی و حجم ورود متغیر","",
        "**نتیجه: حجم متناسب با نوسان، در کل سابقه مبادلهٔ متعادل‌تری میان سود و افت ایجاد کرد؛ اما بهبود در بخش ارزیابی تکرار نشد. نامزد انتخاب‌شدهٔ آموزشی برای جایگزینی دمو تأیید نشد.**","",
        f"گزینهٔ انتخاب‌شده برای راندمان `{candidate}` است. در کل دوره، {fmt(keep)}٪ سود پایه حفظ شد و افت نسبی {fmt(dd_change)}٪ کمتر شد. انتخاب سود همچنان نسخهٔ اصلی باقی ماند. انتخاب راندمان در ارزیابی: `{r['evaluation_efficiency_success']}`؛ بهبود سود جدید: `{r['evaluation_profit_success']}`.","",
        "۱۱ مسیر پیش از اجرا ثبت شدند: هدف نوسان ۳۰/۴۰/۵۰٪، کاهش حجم هنگام افت ۵/۱۰٪ حساب، ترکیب این دو و تأیید برگشت. تمام مسیرها خروج اصلی MR40 را حفظ می‌کنند؛ هدف سود و حد ضرر تازه‌ای افزوده نشده است. حجم فقط هنگام ورود تعیین می‌شود و در پوزیشن باز تغییر نمی‌کند.","",
        "## مقایسهٔ کل سابقه","","سرمایهٔ مستقل ۱۰٬۰۰۰ USDT؛ ۱ ژانویهٔ ۲۰۲۳ تا پیش از ۲۰ اکتبر ۲۰۲۶؛ دادهٔ Bybit با سناریوهای هزینه و محدودیت سفارش البانک. این بخش، تاریخچهٔ بلندمدت خود البانک نیست. افت‌ها از بسته‌شدن کندل چهارساعته محاسبه شده‌اند.","",
        "| حالت | سود خالص عادی | بیشترین افت | سود سختگیرانه | میانهٔ درصد نقد تخصیص‌یافته |","|---|---:|---:|---:|---:|"]
    for case in policy["cases"]:
        n=case["id"];a=metric(n);b=metric(n,profile="stress")
        lines.append(f"| {names[n]} | {fmt(a['net_pnl_usdt'])} | {fmt(a['max_close_drawdown_pct'])}٪ | {fmt(b['net_pnl_usdt'])} | {fmt(a['median_entry_allocation_pct'])}٪ |")
    lines += ["",f"گزینهٔ نوسان ۴۰٪ سود کل را از {fmt(base['net_pnl_usdt'])} به {fmt(pick['net_pnl_usdt'])} و افت را از {fmt(base['max_close_drawdown_pct'])}٪ به {fmt(pick['max_close_drawdown_pct'])}٪ رساند. این افزایش سود نیست؛ در این سابقه، کاهش حدود {fmt(dd_change)}٪ افت در برابر کاهش حدود {fmt(100-keep)}٪ سود بود.","",
        "![حجم متغیر و منحنی حساب](../evidence/mr40-adaptive-sizing-20261022/equity_drawdown.png)","",
        "## چرا در ارزیابی پذیرفته نشد؟","","بخش ارزیابی: از ۱ ژانویهٔ ۲۰۲۵ تا پیش از ۲۰ اکتبر ۲۰۲۶. انتخاب فقط از آموزش ۲۰۲۳ و ۲۰۲۴ انجام شد و پس از ارزیابی عوض نشد.","",
        "| معیار | نسخهٔ اصلی | نامزد نوسان ۴۰٪ | شرط پذیرش |","|---|---:|---:|---:|",
        f"| سود عادی | {fmt(bn['net_pnl_usdt'])} | {fmt(pn['net_pnl_usdt'])} | حداقل {fmt(evaluation['normal_pnl_required_min'])} |",
        f"| افت عادی | {fmt(bn['max_close_drawdown_pct'])}٪ | {fmt(pn['max_close_drawdown_pct'])}٪ | حداکثر {fmt(evaluation['normal_dd_required_max'])}٪ |",
        f"| سود سختگیرانه | {fmt(bs['net_pnl_usdt'])} | {fmt(ps['net_pnl_usdt'])} | در نسبت راندمان استفاده می‌شود |",
        f"| نسبت راندمان | {score('baseline_a100'):.4f} | {score(candidate):.4f} | حداقل {evaluation['required_min_efficiency_score']:.4f} |","",
        f"شرط حفظ سود پاس شد؛ اما افت در ارزیابی فقط {evaluation['normal_dd_reduction_pct']:.4f}٪ به‌صورت نسبی کمتر شد، در برابر شرط ۲۰٪ کاهش. نسبت راندمان نیز به حد لازم نرسید. افتِ ظاهراً بهتر کل سابقه برای اعلام موفقیت کافی نبود.","",
        "## کاهش حجم پس از افت حساب","",
        "این قاعده پس از مشاهدهٔ افت، فقط ورود بعدی را کوچک می‌کند؛ افتِ پوزیشنی که از قبل باز شده را متوقف نمی‌کند. به همین دلیل، نصف‌کردن ورود پس از افت ۵٪، بیشترین افت کل را کم نکرد و بازیابی را کندتر کرد.","",
        f"در حالت عادی، طولانی‌ترین مدت زیر قله برای پایه {fmt(base['longest_underwater_days'])} روز و برای کاهش حجم پس از افت ۵٪ {fmt(metric('b_dd5_a50')['longest_underwater_days'])} روز شد. برای نامزد نوسان ۴۰٪ نیز {fmt(pick['longest_underwater_days'])} روز باقی ماند. بیشترین زمان نگهداری پایه و نامزد هر دو {fmt(pick['max_holding_hours'])} ساعت بود؛ این تغییر ورود، خروج معامله را جلو نمی‌اندازد.","",
        "## ارزیابی مرحله‌ای و البانک","",
        "شش مرحلهٔ walk-forward، هر بار با آموزش بر گذشتهٔ همان مرحله، حساب مستقل و بستن انتهای مرحله؛ بازده‌ها هندسی ترکیب شده‌اند. این حساب مرحله‌ای با حساب پیوستهٔ کل دوره یکسان نیست.","",
        "| روش | سود مرکب با شروع ۱۰هزار، عادی | سختگیرانه |","|---|---:|---:|"]
    for method,label in (("baseline","پایهٔ ثابت"),("profit","انتخاب سود از گذشته"),("efficiency","انتخاب راندمان از گذشته")):
        lines.append(f"| {label} | {fmt(r['walk_forward_compounded_pnl_10000']['normal/'+method])} | {fmt(r['walk_forward_compounded_pnl_10000']['stress/'+method])} |")
    lines += ["","انتخاب راندمانِ متغیر نیز از پایهٔ ثابت ضعیف‌تر بود. انتخاب‌های شش مرحله در summary.json ثبت شده‌اند.","",
        "البانک: ۲۱ سپتامبر تا پیش از ۲۱ اکتبر ۲۰۲۶؛ فقط دو معامله. در این دو ورود، برآورد نوسان کمتر از سقف ۴۰٪ بود، بنابراین نامزد تمام نقد را تخصیص داد و دقیقاً با نسخهٔ اصلی برابر شد.","",
        "| سرمایه | سود پایه عادی | سود نامزد عادی | سود نامزد سختگیرانه |","|---|---:|---:|---:|"]
    for cap in (10000,500):lines.append(f"| {cap:,} | {fmt(metric('baseline_a100','lbank30',capital=cap)['net_pnl_usdt'])} | {fmt(metric(candidate,'lbank30',capital=cap)['net_pnl_usdt'])} | {fmt(metric(candidate,'lbank30','stress',cap)['net_pnl_usdt'])} |")
    lines += ["","برابری این دو معامله، مزیت روی البانک یا کفایت نمونه برای تصمیم اجرایی را اثبات نمی‌کند.","",
        "## تعریف دقیق حجم و هزینه","",
        "حجم = کمینهٔ سقف نقد، هدف نوسان ÷ نوسان برآوردی، و سقف کاهش حجم در صورت فعال‌شدن شرط افت. هدف نوسان ۴۰٪ یعنی هدف سالانه‌شده در فرمول حجم؛ ورود ثابت ۴۰٪ سرمایه یا تضمین نوسان حساب ۴۰٪ نیست. نوسان از انحراف معیار جمعیتی آخرین ۱۸۰ بازده لگاریتمی بسته‌شده، ضرب در جذر ۲۱۹۱٫۵ به‌دست می‌آید.","",
        "افت مورد استفاده برای حجم از قلهٔ ارزش بسته‌شدهٔ همین حساب تا ارزش بسته‌شدهٔ آن در لحظهٔ تصمیم است. قله با خروج معامله بازنشانی نمی‌شود. در تأخیر دوکندلی نیز فقط مقدار قابل مشاهده در کندل تصمیم استفاده می‌شود، نه افت فعلی هنگام اجرا. پیش از آغاز هر حساب، افت صفر و قله برابر سرمایهٔ اولیه است. در مدت نگهداری بازتخصیص، اهرم، اضافه‌کردن خرید یا میانگین‌کم‌کردن وجود ندارد.","",
        "اجرای عادی و سختگیرانه در بازشدن کندل پس از تصمیم بسته‌شده است؛ تأخیر اضافه یک کندل دیگر صبر می‌کند. هزینهٔ هر سمت عادی: کارمزد ۰٫۱۰٪ و لغزش ۰٫۰۵٪؛ سختگیرانه: ۰٫۲۵٪ و ۰٫۱۵٪. این سناریوها جای نرخ حساب شخصی یا لغزش اندازه‌گیری‌شده را نمی‌گیرند. مقدار BTC به گام ۰٫۰۰۰۰۱ گرد می‌شود و حداقل ارزش سفارش ۱ USDT است. قواعد فعلی به تاریخ تعمیم داده شده‌اند؛ دفتر هزینه/صف واقعی بازار در دسترس نیست.","",
        "## ثبت و اعتبارسنجی","",
        "این ادامه پس از دیدن نتایج دو مطالعهٔ قبلی انتخاب شده و تمام تاریخ قبلاً دیده شده بود؛ پژوهش پارامتر گذشته‌نگر است، نه آزمون روی دادهٔ کاملاً دیده‌نشده. ۵۹۴ اجرای مدل و پنجره‌های هم‌پوشان، نمونه‌های مستقل بازار نیستند. از این مرحله به بعد پارامتری با مشاهدهٔ ارزیابی عوض نشد.","",
        "نامزد سود باید در آموزش سود عادی حداقل برابر پایه، سود سختگیرانه حداقل ۵٪ بیشتر و افت حداکثر ۱۰٪ بیشتر داشته باشد. نامزد راندمان باید حداقل ۷۵٪ رشد سالانهٔ عادی پایه را حفظ کند، افت بیشتر نداشته باشد و نسبت رشد سالانهٔ بدترِ دو سناریو به افت بدتر را حداقل ۱۰٪ بهبود دهد. کنترل ورود نصف در انتخاب شرکت ندارد. نوسان ۴۰٪ تنها نامزد واجد شرایط آموزشی بود؛ شرط ارزیابیِ افت و نسبت راندمان را پاس نکرد.","",
        "۵۹۴ بازسازی مستقل Decimal، ۶۶ برش زمانی و ۳۶ برابری منحنی کنترل با موتور قدیمی انجام شد؛ بیشترین خطای برابری کنترل صفر بود. ۱۲ تست جدید به‌علاوهٔ ۳۰ تست وابستگی قبلی در بسته قرار دارند. منبع، دو فریم ورودی دارای هش، تمام دفترها، منحنی‌ها، معیارها و verify_replay.py داخل ZIP هستند. بازپخش با Python 3.12+ و بدون شبکه یا کتابخانهٔ اضافی انجام می‌شود.","",
        "۸٬۵۱۴ کندل Bybit و ۶۷۲ کندل معتبر البانک شامل گرم‌کردن، از ورودی‌های ثابت قبلی استفاده شدند. سابقهٔ بلند البانک همچنان به‌دلیل ناسازگاری OHLC کنار گذاشته شده و اصلاح/پرکردن/حذف کندل انجام نشده است. تاریخ‌های پایان انحصاری و مبنای کندل UTC است. افت بسته‌شدن کندل می‌تواند افت واقعی داخل کندل را کمتر نشان دهد.","",
        f"- پروتکل پیش از محاسبه: `{r['protocol_commit']}`",
        f"- موتور و تست‌ها پیش از محاسبه: `{r['code_commit']}`",
        f"- هش نتیجه: `{r['result_digest']}`",
        f"- هش فریم Bybit: `{r['data']['Bybit']['rows_sha256']}`",
        f"- هش فریم البانک: `{r['data']['LBank']['rows_sha256']}`","",
        "نسخهٔ دمو تغییر نکرده و هیچ ارتقای خودکار، سفارش واقعی یا استفاده از API خصوصی انجام نشده است. هشت فایل اجرای Paper با هش قبلی برابر مانده‌اند. شش تست CI مرحلهٔ قبلی موفق بودند؛ وضعیت CI این شاخه در PR مستقل قابل مشاهده است.",""]
    report_path.write_text("\n".join(lines),encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np
    from PIL import Image
    curves=json.loads((run/"full_normal_curves.json").read_bytes())
    shown=["baseline_a100","baseline_a50","b_vol40","b_vol40_dd5"]
    labels=["Original, full cash","Original, half cash","Volatility target 40%","Vol 40% + drawdown throttle"]
    colors=["#155e75","#9ca3af","#d97706","#7c3aed"]
    times=[datetime.fromtimestamp((base["start_ms"]+(i+1)*14_400_000)/1000,timezone.utc) for i in range(len(curves[shown[0]]))]
    fig,(ax,dd,sc)=plt.subplots(3,1,figsize=(12,11),gridspec_kw={"height_ratios":[1.2,.8,1]},layout="constrained")
    for n,label,color in zip(shown,labels,colors):
        values=np.array(curves[n]);ax.plot(times,values,color=color,label=label,lw=1.2)
        peaks=np.maximum.accumulate(np.r_[10000,values])[1:];dd.plot(times,100*(values/peaks-1),color=color,lw=1)
    ax.set(title="MR40 adaptive sizing | retrospective 2023-01-01 to 2026-10-20",ylabel="Account value (USDT)");ax.legend(ncol=2,fontsize=9,loc="upper left")
    dd.set(ylabel="Close drawdown (%)")
    for a in (ax,dd):a.grid(alpha=.18);a.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    for case in policy["cases"]:
        m=metric(case["id"]);sc.scatter(m["max_close_drawdown_pct"],m["net_pnl_usdt"],s=35,color="#bcc7d1")
    for n,label,color in zip(shown,labels,colors):
        m=metric(n);sc.scatter(m["max_close_drawdown_pct"],m["net_pnl_usdt"],s=65,color=color)
        sc.annotate(label,(m["max_close_drawdown_pct"],m["net_pnl_usdt"]),xytext=(5,7),textcoords="offset points",fontsize=8)
    sc.set(xlabel="Maximum close drawdown (%)",ylabel="Net PnL (USDT)",title="All 11 paths, normal costs | training-selected efficiency candidate failed evaluation",xlim=(8,27),ylim=(2200,6300));sc.grid(alpha=.18)
    image_buffer=io.BytesIO();fig.savefig(image_buffer,format="png",dpi=160);plt.close(fig)
    png=image_buffer.getvalue();Image.open(io.BytesIO(png)).verify();(ev/"equity_drawdown.png").write_bytes(png)
    bundle.mkdir(parents=True)
    manifest=json.loads((source/"docs/evidence/mr40-lbank-paper-activation-20261021/SOURCE_MANIFEST.json").read_bytes())
    if not all(sha((source/p).read_bytes())==h for p,h in manifest["files"].items()):raise ValueError("frozen_paper_file_changed")
    paths=list(manifest["files"])
    for name in ("isolated_improvement_v1","rr_sizing_v2","adaptive_sizing_v3"):
        paths += [f"research/nexus_mr40_{name}.py",f"research/mr40_{name}.json",f"tests/test_nexus_mr40_{name}.py"]
    for relative in paths:
        target=bundle/"source"/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/relative,target)
    for name in ("lbank_kline_response.json","source_receipt.json"):
        rel=Path("docs/evidence/lbank-mr40-exact30-20261021")/name;target=bundle/"source"/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/rel,target)
    (bundle/"inputs").mkdir();(bundle/"recorded").mkdir()
    for name in ("bybit_prepared_inputs.json","bybit_october_input_extension.json"):shutil.copyfile(inputs/name,bundle/"inputs"/name)
    for name in ("results.json","selection.json","full_normal_curves.json","all_runs.jsonl.gz"):shutil.copyfile(run/name,bundle/"recorded"/name)
    for name in ("equity_drawdown.png","summary.json","verify_replay.py"):shutil.copyfile(ev/name,bundle/name)
    (bundle/report_path.name).write_text(report_path.read_text().replace("../evidence/mr40-adaptive-sizing-20261022/equity_drawdown.png","equity_drawdown.png"),encoding="utf-8")
    (bundle/"README.md").write_text("# MR40 adaptive sizing replay\n\nExtract this ZIP, then run `python verify_replay.py` with Python 3.12+. No network or external packages required. It verifies hashes, 42 tests, all 594 ledgers, 66 prefix checks and 36 original-control parity comparisons.\n\nThe training-selected volatility target did not pass evaluation. No Paper or Live changes. All history was previously observed. Original exchange trade archives are not duplicated; input frames preserve their provenance and hashes.\n",encoding="utf-8")
    files={str(p.relative_to(bundle)):{"bytes":p.stat().st_size,"sha256":sha(p.read_bytes())} for p in sorted(bundle.rglob("*")) if p.is_file()}
    (bundle/"MANIFEST.json").write_bytes(canonical({"schema":"nexus.mr40-adaptive-sizing-bundle.v3","files":files})+b"\n")
    archive=ev/"NEXUS_MR40_Adaptive_Sizing_20261022.zip"
    with zipfile.ZipFile(archive,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():z.write(p,p.relative_to(bundle),compress_type=zipfile.ZIP_STORED if p.suffix==".gz" else zipfile.ZIP_DEFLATED)
    receipt={"archive":archive.name,"bytes":archive.stat().st_size,"sha256":sha(archive.read_bytes()),"files":len(files)+1,"result_digest":r["result_digest"],"research_only":True}
    (ev/"bundle_receipt.json").write_bytes(canonical(receipt)+b"\n");print(json.dumps(receipt),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for key in ("source","run","inputs","bundle"):p.add_argument("--"+key,type=Path,required=True)
    build(**vars(p.parse_args()))
