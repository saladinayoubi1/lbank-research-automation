"""Install this isolated Paper using the native Task Scheduler CLI, without PowerShell."""
import argparse
import csv
import ctypes
from datetime import datetime, timedelta, timezone
import io
import json
import locale
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

NAME = "NEXUS-MR40-LBank-Research-Paper-v1"
NS = "http://schemas.microsoft.com/windows/2004/02/mit/task"


def command(args, check=True):
    result = subprocess.run(args,capture_output=True,timeout=40)
    for field in ("stdout","stderr"):
        raw = getattr(result,field)
        encoding = "utf-16" if raw.startswith((b"\xff\xfe",b"\xfe\xff")) else "utf-8-sig"
        try: text = raw.decode(encoding)
        except UnicodeDecodeError: text = raw.decode(locale.getpreferredencoding(False),errors="replace")
        setattr(result,field,text)
    if check and result.returncode:
        raise RuntimeError("native_command_failed: "+args[0]+": "+result.stderr[-300:])
    return result


def verify_registered(text, args):
    tree = ET.fromstring(text.lstrip("\ufeff"))
    find = lambda path: tree.findtext(path,namespaces={"t":NS})
    # Task Scheduler omits default-valued nodes in its exported XML. Native
    # COM readback on the owner device also verified RunLevel=0, LogonType=3.
    if (find("t:Principals/t:Principal/t:RunLevel") not in (None,"LeastPrivilege")
            or find("t:Principals/t:Principal/t:LogonType") != "InteractiveToken"
            or find("t:Settings/t:Enabled") not in (None,"true")
            or find("t:Actions/t:Exec/t:Arguments") != subprocess.list2cmdline(args)):
        raise ValueError("registered_task_identity_verification_failed")


def install(source, state_root, python, source_sha, manifest_sha, resume_finalization=False):
    if os.name != "nt": raise ValueError("Windows installer only")
    existing = command(["schtasks.exe","/Query","/TN",NAME,"/XML"],check=False).returncode == 0
    if existing and not resume_finalization:
        raise ValueError("research_task_already_exists_no_replacement")
    identity = next(csv.reader(io.StringIO(command(["whoami.exe","/user","/fo","csv","/nh"]).stdout)))
    sid = identity[-1].strip()
    if not sid.startswith("S-1-") or sid in ("S-1-5-18","S-1-5-19","S-1-5-20"):
        raise ValueError("interactive_owner_identity_required")
    runner = source/"research/nexus_mr40_lbank_isolated_paper_v1.py"
    args = [str(runner),"--source",str(source),"--state-root",str(state_root),
            "--source-sha",source_sha,"--manifest-sha",manifest_sha]
    if not existing:
        first = command([str(python),*args])
        print(first.stdout.strip(),flush=True)
    state = json.loads((state_root/"state.json").read_bytes())
    if (state["source_sha"] != source_sha or state["manifest_sha256"] != manifest_sha
            or state["policy"]["live_enabled"] is not False or state["policy"]["initial_cash_usdt"] != "500"):
        raise ValueError("activated_paper_identity_mismatch")
    windowless = python.with_name("pythonw.exe")
    if not windowless.is_file(): raise ValueError("windowless_python_missing")
    ET.register_namespace("",NS)
    task = ET.Element("{"+NS+"}Task",version="1.2")
    def child(parent,name,text=None,**attrs):
        value = ET.SubElement(parent,"{"+NS+"}"+name,attrs)
        if text is not None: value.text=str(text)
        return value
    registration = child(task,"RegistrationInfo")
    child(registration,"Author","NEXUS Research Paper")
    child(registration,"Description","Owner-requested isolated MR40 LBank research Paper, 500 virtual USDT; zero exchange orders.")
    expiry = datetime.fromtimestamp((state["trial_end_ms"]+120000)/1000,timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    triggers = child(task,"Triggers")
    timer = child(triggers,"TimeTrigger")
    repetition = child(timer,"Repetition")
    child(repetition,"Interval","PT1M"); child(repetition,"Duration","P31D")
    child(repetition,"StopAtDurationEnd","false")
    child(timer,"StartBoundary",(datetime.now(timezone.utc)+timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    child(timer,"EndBoundary",expiry); child(timer,"Enabled","true")
    logon = child(triggers,"LogonTrigger")
    child(logon,"EndBoundary",expiry); child(logon,"Enabled","true"); child(logon,"UserId",sid)
    principals=child(task,"Principals"); principal=child(principals,"Principal",id="Author")
    child(principal,"UserId",sid); child(principal,"LogonType","InteractiveToken"); child(principal,"RunLevel","LeastPrivilege")
    settings=child(task,"Settings")
    for key,value in {"MultipleInstancesPolicy":"IgnoreNew","DisallowStartIfOnBatteries":"false",
        "StopIfGoingOnBatteries":"false","AllowHardTerminate":"true","StartWhenAvailable":"true",
        "RunOnlyIfNetworkAvailable":"false","AllowStartOnDemand":"true","Enabled":"true",
        "Hidden":"false","RunOnlyIfIdle":"false","WakeToRun":"false",
        "ExecutionTimeLimit":"PT1M","Priority":"7"}.items(): child(settings,key,value)
    actions=child(task,"Actions",Context="Author"); execution=child(actions,"Exec")
    child(execution,"Command",str(windowless)); child(execution,"Arguments",subprocess.list2cmdline(args))
    child(execution,"WorkingDirectory",str(source))
    xml_path = state_root.parent/"paper_task.xml"
    xml_path.write_bytes(ET.tostring(task,encoding="utf-16",xml_declaration=True))
    if not existing:
        command(["schtasks.exe","/Create","/TN",NAME,"/XML",str(xml_path)])
    registered = command(["schtasks.exe","/Query","/TN",NAME,"/XML"])
    verify_registered(registered.stdout,args)
    desktop_buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None,0x10,None,0,desktop_buffer) != 0:
        raise OSError("desktop_path_unavailable")
    shortcut = Path(desktop_buffer.value)/"NEXUS MR40 LBank Paper.url"
    shortcut.write_text("[InternetShortcut]\nURL="+(state_root/"dashboard.html").as_uri()+"\n",encoding="utf-8")
    (state_root/"STOP_PAPER.cmd").write_text('@echo off\necho owner_request>"'+str(state_root/"STOP")+'"\nschtasks /Change /TN "'+NAME+'" /DISABLE\n',encoding="ascii")
    command(["schtasks.exe","/Run","/TN",NAME])
    opened = True
    try: os.startfile(state_root/"dashboard.html")
    except OSError: opened = False
    receipt = {"Installed":True,"TaskName":NAME,"TaskEnabled":True,"TaskRunLevel":"LeastPrivilege",
        "TimerInterval":"PT1M","LogonResume":True,"DesktopShortcutCreated":shortcut.is_file(),
        "DashboardOpened":opened,"PaperInitialCash":"500","SourceSha":source_sha,
        "ManifestSha256":manifest_sha,"FirstExecutionBarMs":state["first_execution_bar_ms"],
        "TrialEndMs":state["trial_end_ms"],"LiveEnabled":False,"ExchangeOrders":0,
        "Installer":"Python + native schtasks.exe XML; no PowerShell execution-policy changes"}
    (state_root.parent/"install_receipt.json").write_text(json.dumps(receipt),encoding="utf-8")
    print(json.dumps(receipt),flush=True)
    return receipt


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    for name in ("source","state-root","python"): parser.add_argument("--"+name,type=Path,required=True)
    for name in ("source-sha","manifest-sha"): parser.add_argument("--"+name,required=True)
    parser.add_argument("--resume-finalization",action="store_true")
    install(**vars(parser.parse_args()))
