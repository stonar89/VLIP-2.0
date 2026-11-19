# VLiP 2.0 — Docking, preparation, pose inspection and PLIP
# Based on VLiP Complete Pipeline v0.0.0.22 / VLiP Docking v1.47.
# MD development source is preserved separately; no MD runtime or WSL required.
# Distribution: Windows 10/11 64-bit; scientific tools install into private VLiP runtime.

import base64 as _vlip_b64
import zlib as _vlip_zlib
import types as _vlip_types
import os as _vlip_os
import sys as _vlip_sys


# ---------------------------------------------------------------------------
# Complete-pipeline command audit
# ---------------------------------------------------------------------------
# v0.0.0.3 deliberately uses ONE audit directory per Complete Pipeline session.
# Every child tool inherits the same folder/session through environment variables,
# so PDB acquisition, receptor cleaning/prep, ligand prep, Vina and PLIP all append their timestamped records beside one another.
import subprocess as _vlip_audit_subprocess
import threading as _vlip_audit_threading
import tempfile as _vlip_audit_tempfile
import shlex as _vlip_audit_shlex
import time as _vlip_audit_time
import json as _vlip_audit_json
import functools as _vlip_audit_functools
import urllib.request as _vlip_audit_urllib_request
from datetime import datetime as _vlip_audit_datetime

_VLIP_AUDIT_SESSION_ID = _vlip_os.environ.get(
    "VLIP_COMMAND_AUDIT_SESSION",
    _vlip_audit_datetime.now().strftime("%Y%m%d-%H%M%S"),
)
_VLIP_AUDIT_LOCK = _vlip_audit_threading.RLock()
_VLIP_AUDIT_ROOT = ""
_VLIP_AUDIT_ORIGINAL_POPEN = _vlip_audit_subprocess.Popen
_VLIP_AUDIT_ORIGINAL_OS_SYSTEM = _vlip_os.system
_VLIP_AUDIT_ORIGINAL_URLOPEN = _vlip_audit_urllib_request.urlopen

_VLIP_AUDIT_STAGE_FILES = {
    "00_session": "00_session_and_project_context",
    "01_environment": "01_environment_and_dependencies",
    "02_pdb_download": "02_pdb_download_and_mapping",
    "03_receptor_cleaner": "03_receptor_cleaner",
    "04_receptor_prep": "04_receptor_pdbqt_preparation",
    "05_ligand_prep": "05_ligand_preparation",
    "06_docking": "06_vina_docking",
    "07_plip": "07_plip_analysis",
    "08_pymol": "08_pymol_viewer",
    "99_other": "99_other_commands",
}


def _vlip_command_audit_safe_root(path):
    if not path:
        return ""
    try:
        root = _vlip_os.path.abspath(_vlip_os.path.normpath(str(path)))
        _vlip_os.makedirs(root, exist_ok=True)
        probe = _vlip_os.path.join(root, ".vlip_audit_write_test")
        with open(probe, "a", encoding="utf-8"):
            pass
        try:
            _vlip_os.remove(probe)
        except OSError:
            pass
        return root
    except Exception:
        return ""


def _vlip_default_command_audit_root():
    parent = _vlip_os.environ.get("VLIP_COMMAND_AUDIT_ROOT", "").strip()
    if parent:
        return parent
    try:
        base = _vlip_os.path.dirname(_vlip_os.path.abspath(__file__))
        return _vlip_os.path.join(
            base, "VLiP_Command_Audit", f"commands_{_VLIP_AUDIT_SESSION_ID}"
        )
    except Exception:
        return _vlip_os.path.join(
            _vlip_audit_tempfile.gettempdir(),
            "VLiP_Command_Audit",
            f"commands_{_VLIP_AUDIT_SESSION_ID}",
        )


def _vlip_command_audit_add_root(path):
    """Select the one canonical audit folder for this complete-pipeline session."""
    global _VLIP_AUDIT_ROOT
    root = _vlip_command_audit_safe_root(path)
    if not root:
        return _VLIP_AUDIT_ROOT
    with _VLIP_AUDIT_LOCK:
        if not _VLIP_AUDIT_ROOT:
            _VLIP_AUDIT_ROOT = root
            _vlip_os.environ["VLIP_COMMAND_AUDIT_ROOT"] = root
            _vlip_os.environ["VLIP_COMMAND_AUDIT_SESSION"] = _VLIP_AUDIT_SESSION_ID
        # Once selected, never fan out into extra component/project folders.
        return _VLIP_AUDIT_ROOT


def _vlip_command_audit_root():
    if _VLIP_AUDIT_ROOT:
        return _VLIP_AUDIT_ROOT
    return _vlip_command_audit_add_root(_vlip_default_command_audit_root())


def _vlip_command_audit_set_project_root(project_dir):
    """Record project context without changing the single session audit folder."""
    root = _vlip_command_audit_root()
    if project_dir:
        _vlip_command_audit_write(
            f"VLIP_PROJECT_OUTPUT {str(project_dir)}",
            cwd=project_dir if _vlip_os.path.isdir(str(project_dir)) else None,
            source="VLiP project context",
            stage="00_session",
        )
    return root


def _vlip_command_audit_format_command(args):
    if isinstance(args, (list, tuple)):
        parts = []
        for item in args:
            text = str(item)
            try:
                parts.append(_vlip_audit_shlex.quote(text))
            except Exception:
                parts.append(text)
        return " ".join(parts)
    return str(args)


def _vlip_command_audit_stage(command):
    low = str(command).lower()

    # Explicit internal actions first.
    if "vlip_internal pdb_download" in low or "vlip_internal pdb_mapping" in low:
        return "02_pdb_download"
    if "vlip_internal receptor_clean" in low or "--cleaner-gui" in low or "--cleaner-core" in low:
        return "03_receptor_cleaner"
    if "vlip_internal receptor_prep" in low or "--pdbqt-prep-gui" in low or "--meeko-wrapper" in low:
        return "04_receptor_prep"
    if "vlip_internal ligand_prep" in low or "--ligand-prep-gui" in low or "--ligand-prep-core" in low:
        return "05_ligand_prep"


    if "plip" in low:
        return "07_plip"
    if "vina" in low and ("--receptor" in low or "--ligand" in low or "--config" in low):
        return "06_docking"
    if any(token in low for token in (
        "mk_prepare_receptor", "prepare_receptor", "pdb2pqr", "propka",
        "--pdbqt-prep", "meeko_receptor",
    )):
        return "04_receptor_prep"
    if any(token in low for token in (
        "mk_prepare_ligand", "prepare_ligand", "meeko", "obabel", "openbabel",
        "--ligand-prep", "--vlip-ligand-handoff",
    )):
        return "05_ligand_prep"
    if any(token in low for token in (
        "files.rcsb.org/download", "ebi.ac.uk/pdbe", "pdbe/api/mappings",
        "rest.uniprot.org", "vlip_internal pdb_",
    )):
        return "02_pdb_download"
    if any(token in low for token in (
        "pip install", "conda create", "conda install", "apt-get", "apt install",
        "nvidia-smi", "--version", "dependency", "miniforge", "miniconda",
    )):
        return "01_environment"
    if "vlip_project_output" in low:
        return "00_session"
    return "99_other"


def _vlip_command_audit_write(args, cwd=None, source="subprocess.Popen", stage=None, event="START", extra=None):
    """Append one timestamped audit record to the master and one stage file."""
    try:
        command = _vlip_command_audit_format_command(args)
        stage = stage or _vlip_command_audit_stage(command)
        now = _vlip_audit_datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        try:
            cwd_text = _vlip_os.path.abspath(str(cwd or _vlip_os.getcwd()))
        except Exception:
            cwd_text = str(cwd or "")
        record = (
            f"[{timestamp}] {event}\n"
            f"STAGE: {stage}\n"
            f"SOURCE: {source}\n"
            f"CWD: {cwd_text}\n"
            f"COMMAND:\n{command}\n"
        )
        if extra:
            for key, value in extra.items():
                record += f"{str(key).upper()}: {value}\n"
        record += f"{'-' * 96}\n"

        root = _vlip_command_audit_root()
        if not root:
            return stage
        master_name = f"VLiP_COMPLETE_COMMANDS_{_VLIP_AUDIT_SESSION_ID}.txt"
        stage_base = _VLIP_AUDIT_STAGE_FILES.get(stage, stage)
        stage_name = f"{stage_base}_{_VLIP_AUDIT_SESSION_ID}.txt"
        with _VLIP_AUDIT_LOCK:
            try:
                with open(_vlip_os.path.join(root, master_name), "a", encoding="utf-8", newline="\n") as handle:
                    handle.write(record)
                with open(_vlip_os.path.join(root, stage_name), "a", encoding="utf-8", newline="\n") as handle:
                    handle.write(record)
            except Exception:
                pass
        return stage
    except Exception:
        # Auditing must never be capable of stopping scientific work.
        return stage or "99_other"


def _vlip_command_audit_action(stage, action, details=None, cwd=None, source="VLiP internal"):
    try:
        payload = details or {}
        command = "VLIP_INTERNAL " + str(action)
        if payload:
            command += " " + _vlip_audit_json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
        _vlip_command_audit_write(command, cwd=cwd, source=source, stage=stage, event="ACTION")
    except Exception:
        pass


class _VLiPAuditedPopen(_VLIP_AUDIT_ORIGINAL_POPEN):
    def __init__(self, *popenargs, **kwargs):
        self._vlip_audit_finished = False
        self._vlip_audit_started = _vlip_audit_time.monotonic()
        cmd = popenargs[0] if popenargs else kwargs.get("args", "")
        self._vlip_audit_command = cmd
        self._vlip_audit_cwd = kwargs.get("cwd")
        self._vlip_audit_stage = _vlip_command_audit_stage(_vlip_command_audit_format_command(cmd))

        # Even custom child environments must inherit the one Complete Pipeline
        # audit folder. This is what keeps cleaner/preparer child GUIs together.
        root = _vlip_command_audit_root()
        if kwargs.get("env") is not None:
            child_env = dict(kwargs["env"])
            child_env["VLIP_COMMAND_AUDIT_ROOT"] = root
            child_env["VLIP_COMMAND_AUDIT_SESSION"] = _VLIP_AUDIT_SESSION_ID
            kwargs["env"] = child_env

        _vlip_command_audit_write(
            cmd,
            cwd=self._vlip_audit_cwd,
            source="subprocess.Popen",
            stage=self._vlip_audit_stage,
            event="START",
        )
        super().__init__(*popenargs, **kwargs)

    def _vlip_finish_audit(self):
        if self._vlip_audit_finished or self.returncode is None:
            return
        self._vlip_audit_finished = True
        elapsed = _vlip_audit_time.monotonic() - self._vlip_audit_started
        _vlip_command_audit_write(
            self._vlip_audit_command,
            cwd=self._vlip_audit_cwd,
            source="subprocess.Popen",
            stage=self._vlip_audit_stage,
            event="END",
            extra={"exit_code": self.returncode, "elapsed_seconds": f"{elapsed:.3f}"},
        )

    def wait(self, *args, **kwargs):
        result = super().wait(*args, **kwargs)
        self._vlip_finish_audit()
        return result

    def communicate(self, *args, **kwargs):
        result = super().communicate(*args, **kwargs)
        self._vlip_finish_audit()
        return result

    def __exit__(self, exc_type, value, traceback):
        result = super().__exit__(exc_type, value, traceback)
        self._vlip_finish_audit()
        return result


def _vlip_audited_os_system(command):
    started = _vlip_audit_time.monotonic()
    stage = _vlip_command_audit_stage(command)
    _vlip_command_audit_write(command, source="os.system", stage=stage, event="START")
    result = _VLIP_AUDIT_ORIGINAL_OS_SYSTEM(command)
    _vlip_command_audit_write(
        command,
        source="os.system",
        stage=stage,
        event="END",
        extra={"exit_code": result, "elapsed_seconds": f"{_vlip_audit_time.monotonic() - started:.3f}"},
    )
    return result


def _vlip_audited_urlopen(url, *args, **kwargs):
    try:
        full_url = getattr(url, "full_url", str(url))
        low = full_url.lower()
        stage = "02_pdb_download" if any(token in low for token in (
            "files.rcsb.org", "ebi.ac.uk/pdbe", "pdbe/api/mappings", "rest.uniprot.org"
        )) else "01_environment"
        _vlip_command_audit_write(
            f"HTTP GET {full_url}",
            source="urllib.request.urlopen",
            stage=stage,
            event="START",
        )
    except Exception:
        pass
    return _VLIP_AUDIT_ORIGINAL_URLOPEN(url, *args, **kwargs)


_vlip_audit_subprocess.Popen = _VLiPAuditedPopen
_vlip_os.system = _vlip_audited_os_system
_vlip_audit_urllib_request.urlopen = _vlip_audited_urlopen

# Select and publish the canonical root before any embedded/child tool starts.
if not _vlip_command_audit_add_root(_vlip_default_command_audit_root()):
    _vlip_command_audit_add_root(
        _vlip_os.path.join(
            _vlip_audit_tempfile.gettempdir(),
            "VLiP_Command_Audit",
            f"commands_{_VLIP_AUDIT_SESSION_ID}",
        )
    )
_vlip_command_audit_action(
    "00_session",
    "session_start",
    {
        "session_id": _VLIP_AUDIT_SESSION_ID,
        "audit_folder": _vlip_command_audit_root(),
        "pipeline_version": "2.0.0",
        "executable": _vlip_os.path.abspath(__file__) if "__file__" in globals() else "",
    },
    source="VLiP 2.0",
)


def _vlip_install_embedded_audit_hooks(name, module):
    """Add audit entries for important pure-Python pipeline stages that have no OS command."""
    try:
        def wrap_function(function_name, stage, action, detail_builder):
            original = getattr(module, function_name, None)
            if not callable(original) or getattr(original, "_vlip_audit_wrapped", False):
                return

            @_vlip_audit_functools.wraps(original)
            def wrapped(*args, **kwargs):
                try:
                    details, cwd = detail_builder(args, kwargs)
                    _vlip_command_audit_action(
                        stage, action, details, cwd=cwd,
                        source=f"internal:{name}.{function_name}",
                    )
                except Exception:
                    pass
                return original(*args, **kwargs)

            wrapped._vlip_audit_wrapped = True
            setattr(module, function_name, wrapped)

        if name == "receptor_cleaner_core":
            def download_details(args, kwargs):
                pdb_id = args[0] if args else kwargs.get("pdb_id", "")
                directory = args[1] if len(args) > 1 else kwargs.get("directory", "")
                force = args[2] if len(args) > 2 else kwargs.get("force", False)
                return ({"pdb_id": str(pdb_id), "directory": str(directory), "force": bool(force)}, str(directory) or None)

            def clean_details(args, kwargs):
                entry = args[0] if args else kwargs.get("entry", {})
                root = args[1] if len(args) > 1 else kwargs.get("root", "")
                ns = args[2] if len(args) > 2 else kwargs.get("args")
                ns_dict = dict(vars(ns)) if ns is not None and hasattr(ns, "__dict__") else {}
                payload = {
                    "entry": entry,
                    "root": str(root),
                    "settings": ns_dict,
                }
                return payload, str(root) or None

            wrap_function("download_structure", "02_pdb_download", "PDB_DOWNLOAD", download_details)
            wrap_function("process_entry", "03_receptor_cleaner", "RECEPTOR_CLEAN", clean_details)

        elif name == "receptor_prep_core":
            def receptor_prep_details(args, kwargs):
                input_path = args[0] if args else kwargs.get("input_path", "")
                scan_root = args[1] if len(args) > 1 else kwargs.get("scan_root", "")
                options = args[2] if len(args) > 2 else kwargs.get("options")
                settings = dict(vars(options)) if options is not None and hasattr(options, "__dict__") else {}
                settings = {key: str(value) if hasattr(value, "__fspath__") else value for key, value in settings.items()}
                output_root = settings.get("output_root", "")
                return ({
                    "input": str(input_path),
                    "scan_root": str(scan_root),
                    "settings": settings,
                }, str(output_root or scan_root) or None)

            wrap_function("prepare_receptor", "04_receptor_prep", "RECEPTOR_PREP", receptor_prep_details)

        elif name == "ligand_prep_core":
            def ligand_prep_details(args, kwargs):
                input_paths = args[0] if args else kwargs.get("input_paths", [])
                smiles_text = args[1] if len(args) > 1 else kwargs.get("smiles_text", "")
                options = args[2] if len(args) > 2 else kwargs.get("options")
                settings = dict(vars(options)) if options is not None and hasattr(options, "__dict__") else {}
                settings = {key: str(value) if hasattr(value, "__fspath__") else value for key, value in settings.items()}
                output_root = settings.get("output_root", "")
                return ({
                    "inputs": [str(item) for item in input_paths],
                    "smiles_text": str(smiles_text),
                    "settings": settings,
                }, str(output_root) or None)

            wrap_function("prepare_sources", "05_ligand_prep", "LIGAND_PREP", ligand_prep_details)
    except Exception:
        pass

_EMBEDDED_VLIP_MODULES = {'debug_trace': 'c-qxj{chVh693;%!D<my+S*FG#o-QW9b7hXx4lb~z;%1K$OZx}Q?WMsT9HcPH3Hm2+!NlD+zd&5T5_CjaKPmcM<O{NoEgsihWhTse$KP~c@Xcj_?DzAu}tDO1H&-BvTQ{bOwb@?iy=uv8pI>P?gd!{^g2$s2s|P(>ILyN@so^*B_kR0SSsMf3mJ`BW)B847{+BRBLN47VK8SI6)Z&VDT@~@_EsZ5W6UPxqab%#AQ&e}%!rpnX~+by&0}DlCYcz}cp>N1D@lQEDfDg$x{@f!vLr*T*e&iMVw}@!MuJ!*O39L&Jph5A6{kKZnGjI=78XW0#}>ek#h~OozrIFxsD8ld9PIIy&@dz({BSa7peG}7GD=czqv-|%KT9Iwx_&P5jJd96NoX7=f{GxCxnAQXG1?T2QmoM<5sg9VOs!ggy+jZds+I3Ug1^6mJqCK_SDwVhbHa-!^$&#D5jYg6sp6Ybv8;){fY*Wq{4Kz%QSr`~xd_7YZB_CX%Z$+l*ryx-mC9#y{G56>N}gDy(vWKMC|(W0;}{J|HYDdM8it00!N3bC=i~$}KSK`AfWY5^`C!u^4utEPoQ3|7WJw|%srQh4KO`)c-f_r0Nx~ta+4ZeM!hnlQF0!j3fq38`!y)i$k<lSJ1Jfzy_=h}g&4Y|36H~uh%|$2|R^Y$pgq8qv`l&h11(lICmR7PMdVSYRa`1R&wnT)9cZ2H+^V-u>7-_Ha@+@PqaMQ)yDJ>{>3$(bq?&V83MsQTRmcZ$FY#PHx@1E=v<LhMlvwJd`9eq5VoWR46Uw*R1y)c@D@*KH~AgfWzv1(o5!zmICH&o8Szl_0oihKCl(GC2XDa9S~@hr>Xe6V})zMI_0S8K~o8=JEeNKB@2XJANq37UUw<ia2Q1xGNw@Ua0YB!t+6k(k|uLCnU+FR{^*;mUO8F2RT3Vhl)YPz7^iQblwtX8WQvOs-91Y>@BC>w^QUWA5we#|tu@98WH0=TmZgIypL<Ov!)#^>2diB89t%bQdhVIG@f8>uExK<5;En>R_$wr{KZpB>Jom0Yo?rfuzW0cAVUqmQ8t))ZiuH31%TGOzRPDUuMS+%rv<boa|h9yD+<u^$)kP;>9j(?P$|mX6EYyYe-&_m)jXY*fB2`7{QuXHPA<>^DV3|Qm<V+^s4)bdP@jAI7(@jcu?n(tWF=PX&{FcHMYgtUcUcGvKvg)aGsb4$$14_G0EEA-J+N1JQry$bV^>AX|iYaaS}yX%Q4=`-#(w80Sy)}dyz*emnQ`eAIJJhxfcZE_cY|J*X~EN55OS-OUJiC27IoWFkj;EOK@1fzkZ&5I6v#7E+@D0m`y%ibWr0k&}|IMQQ+3c?u7X?4@H@Iz;{028i*pnqH<Kn6|h{W^~Hqtww|mgYx6a^0({#@vAM)bV_olU06aIY95YLgS`C8D2&ic*0PckQ2=2&y1+WgZmdtE9Ar)2cxTLNZyGKk%Ch{K^RLXJ8*<Cbp9PtzmF8M7-9Oz3V3mO2Qx+s0jIc$3UP>v#^1>zfp9EoXMvnUE6*&8tg=n5YoD%C@_xCsP4VA+_{IScUxO0pl^v#gkiBExFxzhV5kI+t2H7V=H}RwO4=uWI^4Td#xcLM=Z_#Cw1piwV}U-E=UpGzT#tm=NL7zAV+Z0S_Rj5s9n;AFK3dbSbmlm3>luqd-($PHY|@OdqB(Wg)wzvCz7dPAs?^B@E<U<?if!HgU*tl4NjLpp>YPf;7bl&mm=H0f*fKWL+|Bd1wrPJq={DkibG3mW>9OLw6aSb=9Z=0nUW0aleKE5Ik<MXhAwmh!``~=pyhWP8cGXzA7+Z2WWUIw7Lrb;*~hGxis)Q!6fV#MKtAZL7%oC=6q>dJFWG?gtOh&wqa`*R)#go!gijfh`n)BYJ@N-Gn*XRn?}IBp^XN{ExZf)+gP`WAKXV_^Y%SH8&2H?@^#^^+4Rft?8|hbAY@VU>s$OrAz*45=i4Kyb?h$yhlYyI(C4I%w9|}1GM0x+o(?!O6-yS<l=pRIWYlQgs*@~elmf{%^a@gZd^L@|pGSMqXm3IGJ~(@yoW0NXo^M!}&gjim$x&wjnf1u!ra7;St|(OTYE)sPPBQQS7O3L`d9~I%bY36WZ~O;-wbrs8h*22{-J-IOzA}-0GNyjx88Qk+9@bc3X=?sppfn7GoB=~a#l19)tDSNXmS?2H+AQfe10=({rA)e2wPHF3Eb>Z`z9M)Ky27vB9_|*16@e`qJG0Qh+KHww9ezu??MtIO>(!I0%UF?zP6bPdfJcT3R8|`15H?VZo*`m3;8D$^wN^pO96}&0K;iKZU0uVFXplU{i=Rh9CL!NJLq)G6>VU>@E&(t=8VKQRk21#P4P1E#%KKFGjd!`+C88tja8!<F8oV6-60fD|FS0g}Q3-Z58j-a$?gN46E)cQl$QC`!w|JBuWW}yK+$fFkBjv0#%`>>OrrL`aFUaJdcsKD;HhxM&co3_UnIPS=T{or?bKQqcz+S^p_OD40o8>K|t=fCH+FQv`Zc6?D>yp5AEz8be&p~QhHRB-Ya~0lOb=U`MZ|&L<63cDC?p&3K5dVSue>iwvo1r^VEe%6g&SSv=&8<{(joQ}jr<ITZLf(%-^6hD?jES7bW6&z*ZAAqY1t`I1vs0mh+lukGga^N~F_tI+6fV9!s3!3(iLhvntE(KmJjMrE&&+~E4()bdw2?}RY9tlL8&+3>@5fP8vu5?Rqcg1IvdBmrfxZHuCW)*zEUJ;c4<HuFI)a#P#1uqdNe=D3inA6QtccK>&KbmKQ5hKw$d4_G_R?u^g?>VUn(=GP*@pB8Su4iQ;h*t1BJrj3r-Os5_EsRWDn-d*>tJk?aZ0~=<2w8@jK7H9_cMSL-k95Dvx^O-D5tcYlKhHv+3=g}_|%(^FJ+C<n?nK&<}Hb{Dh}H+ilqB%>w8q$vWntP2>J@h)YUhY;)~8DroO8u<i1tF!o?#=X7{frxXZ)CL-Kic^wR`?r!&|fs=75XG?m!h8CA*g4QZP~maI9wC;r{LcUr^uvJWg&d`lL2CchMp*F8;%GKM1oeLFeRfU{bA!<qBA0_T7KcHw1Ms6JhV1yn}mKv%(@^40<h<p1ufqNc(QR}?xAe>^)nCDRGCw`b(|{A2=_sqxv8!Dr_)pq!i@U3`|#e7vFTbYQIjpPi8N_q%<x`9Hm!d1}M8Yva^jw^hx}&z^&UJDVOIPilc%eUZMZR$<uVN9lluaO%uI`boO|)%!Y3<}@Tq7dfIHL4j(ilv)ZK>;FpJSba;;g2wv4GK0P=(9G3dBseyuE?paUdI>RJAG<jKUu*R{U99Hp8Yin_?#iZfr*?BUF%>_}sxGWb=uhg5c9Yy<u4{x6UcU@}&THV^G~1M3-KGsTTBASQ6z!(erc5QSC1u=#cY{G2y;R8Mam><Ct*KT85}LJDmZHLtr5LLVVf+`Ow_Wc', 'receptor_cleaner_core': 'c-q~4+j84Tmf*X-0*#6Zkv2t%^rdXNSv9gmTbh<7k0e)jm5RZDNKitVB-j9HOGWc>K4>HM5B7b&Y0o9^NRX6W-8;P%-4+4l_2kKO$#co?{<J&Kv)$`tvKvo61=IW4Z8~|f6^7yKc`_OV{ZSlE;z5wb{dhV{vtSC3qdXX9={R_Q_&PW~%!6n$2tG`b_gOj%#?f?|Om6b}*4E{19OV5hna+Yi`gt-+qXCr7`nSoanCe1v@aJxKJU%#n6AY74EE+yPxOiO)((752Omf-u&Me)5;#;x@E;_rVw&LL8_|4@-u>bzJ27~2_>11?I1!hrp6VG<0&`O+4;Cr47=5b!z%HnbQ33}~k_xUUujnbPen%*Y;;Bz#KvwXLo?u?Qfm|wm-oaae8f%#{%34V$uv*bD*Byqm`c1yIJW8Zl?!X~2;v@n5Yf>GL!W>6QtPT_N$(dRipIt%)@Fj56XF|e)4e0&Xk)ad2sESX`23Dg-R2;oUGjPn^l_zkph(K)}|J?&iX9`0WT@HrYlA?OWeb8pm5r~ESb6lDpFT>uFHNnnyQKp5R6V<>kTJ*MstMmqrxUMwghL>3I<Q37Lx`9U}NES*9xGaezJ3$5;aHl5Gv!7(mB3}OP<F^#ifnvJP97!3}o7L1cThjHvgGg!|oo<>OqFXuD*3@<(bC`7?Y0)<6203EFARs@xACgXTA18`vrvwK938e-QV?SI6Uu}>IXKb?rS>WJZ6TZBQq-f%vfXK}9=B;#qC!7L^)R$j8LE%`3Hfu+x5`P|Px$)C4Teha{mkH6*VME-_eZ{_bS=KcoJEb5P7*Z>ppNxk9{Q>X<E%CGN@MxdwoPCeY`^5-lWtD()Zs2^WP{g2!l!$UT9nDhZq$AFvB^(d|dCrJ*^X97EF!A1P{c|7UEm&^HdB!)cCMlhawoMix1(a_Q5<@*l4s0AO+Pw1CbIKzhWnJj+Jk2U<9PUDFH{vf`d-}Gq2vSei|fd7yh^z!+59A)=Gl#7Dq+ZvSvl$a&aD9K|irJs6Kfy=<Q)=j{JdfSWdkgOq^sqgBQE`=+q3*Zxf%i~!OaB3Fc&GcvEr6@IvZers*KJpiyw)#SkwXN#b)_1`LAUEuzYo=c@kb}V>mgG1iLejsD`yXkG=IK1^$2)-A$uNOZH_=q=qxx3w-Pz%J=c0Gi+5hS1pdBoz=k5KI{q5HF!RzfB{62q6zk`Ff!NFm0+6fMR2~Lk1@c$-#zc^Lj&ko`BA-opNT)ekFogGq*gP$+>^~GC!e0y?gc5v2#Hae<}w<jOmuV<Ym*ZUd1;IE_O3svS6`Z+jk1_yRC$0r?G1irt8?}rVndeSkQr>gY&=L@sfgHCYzi)`v$=Td#Uz;9UL{ZYqlhlX&_fxo{{iSsj~glr7xGrv6}SX>^dM;a!*JAYqj`cyXEc>>L27x4E;&Gz!=^A)2B&W^C%pY~5IkU-_7Mu?ve&(Gd=PA^=fIC|X(j$Sw6|4%e_h!?>T0QTrD{DuCG4&iSnI67)H@E>?_)Wly+13ga7x`+7ruqlx0z5Pk!jqXdM$f<7(9c-`D6u9!iUqrWo$aJ(1ANHSUoYEs`@T58ovle63(Q9Z8C-}BOZ8z{Ad~8xhtchO_8&70C#yUM5r<jHX{-bL-^LJs5!-K!SKvh7AqhFrb7+aiuLsrrlTry#3O*Y1OTrvu5h*7$@OpMzMEC);)&8_~a?<aCLh&widmk!pzZ|<*Ax<Z8YTU&#881%;J0A#El$Ve3-M%IFl@jZwZAju)^tf7DhvP88-!vHDa428(}ZaPZ(39_$AG`>!5=IK0FvTiU-L5PZx(oY6aHV7h+RMH^oCxhVcb6`iq`#Q=S*rMAJ>^}Lbp3gv7u2k#uDac8csx0EZXTCQiflAg5NHnJg@ioYl7UAdF;C~?Y&9ezTeu_r(82YaiCNFyc&|p(yp2Ta!?<@G!4gS>TMvUeo<itPWOA-kx+Xv}n2(X)B13V--P}S@#*bW{8^s)-HTIJrYendB76{mx1v5=KfGKq7sR<b!DXG<0#047)fr$7buFkx=^=Bo9aCb7)}+tvl}Kjh-c1iF<kX4$=60^tMjqox|qTaE9#a;<96=}dfh(P}ok@P?k6%~tb?Dppm^vDjfi4&?%PX?Iuz@4IM((k)<s0Itv>f@A<NPG<Kl0xtGlWsM0MRc)4U2p)Q~)p*vGBY)aze&6L0GZsmZi*@NIL%A+l`g!HDz;|2~ET$)jZNNHLV28z3d)^XN5l5g>9kjX1b`KEY4&<q9-k)K|Ju&q<P8b^j60u#aN?6-~<OytVBPwv~FrLbG9qG!C+tmP++*n|ptixIvBV%P76*v&~{@zOl+f@^>aQ|`9HR$98enmGP<@aN1oso&#ga;}C8deV!P7pN*F-)>%b!C7}wAD|?Q)&wd1-%|c*YQZd7tQk4)UQ`8x1@H-@3EW-?K0k!HCeiS3Zzk!)4#;=G{ELTzXAn>RJJ?-(e)Z$jO8`}={C&<ySRw2faGTJC_=UJsB^i0`7TIucsEPuAOR0REyb1v^1~N_1UvaO282xdtzd#0WB{W9LLLP-qx2foTUiXd2=e)L4tr%jBh`@FW1UozDjp^L4o2~ChV-7q@;gwTu#~02PEqvESb5E7@w6_d&iVub2XF{<l$ju3lG@6h0+T?PY3$Kks6hHGUckj%S|5n@xa!geJmvTdu(b9gPqP*POkzHga5+dF^!jmLG4|!{{UA$k;t6g`*p8L$qX2Y<BVf9~flom{gojIbx`fAlB0>ex^NRcJ!X5?wIy33vcfo$2Pyqowif^L+J^YCV2<Aa@lYsU+jX}}G^NXS4&#=M>SeTw1U0yE^_zTQ^a<$XwBAvKu;SU4?O<EN~phB5ex1QwGVWqlMO$i{%@hcFV1_%4WL2wqF{q2&OngpnxV(>+ELhbQ637uz5ZU{H7faI>{VZ28Om6($i2pvp86cRE)Wqbef>>UZew3A2>KRv!U`>^d0Tyb~<7!^+jglpAr;El}&vOo`SL~i(8^Ty}MVK(56-#Av(j8X35{X)zH1rHN$R77mVK&-)4<NH=~PmK=+2P}5A*Zs!vcw|CsSYsQKm9}Qdo~4dQ@tA8;sqde+zJJm63XZfB;^@<TInr7if5je!T^ILfL`!gpS1s5`06Q8kZYAo480q%W_LiQ$BK~bv*4<DjYE}?y<-}kO)EwKYXCJPkJSULaUKgmF;jG0*tHbPpk45tlEq^T-fRw6a;kLUdZAl|P0xq_3i^3iTxDMcVwOZ`xY8wlZd|}L(p&@E+cO{Y_7_7PIDywj-A}4B0zpbY)dc!>r8dX(@fmbA`!ozTT!E<W;@MI~4#H;3BO9*-6IL{+VkrXwm5IL&}5eN1%N+4B9zHluid<z^yOdHxm!c+e(O(vB*&0rlXh>2Y9N<*hwC2?hY0-I3dj~tc+!Z5sIeC-AoS|k|+3)!Ar$?fivUcwNu)!z29wcuGS7c`4yu=9hi#;}1(uY%AkT@ge=d89vpH3Rr3c;ufGq!y!iq9#Si(5)^Dvd=387J6(23-P?HhnDmu`GlN5h+#i<&M%J7P641{qyDVk47WajZr<Am-g*fyhv82r$@?8?yV((^hr0_=Zy8h`<LJ>Qvop`*YPj{+{Yz-zbpKt4&V|CGv!k#UgokH`_y@k?pQGkkxZFDIyxIS7a@m81j0&gwSmNLW3jFo>^ziJj7d=>-&iPNB!`_?Yla4CMQqjTLDVBeKPJi}4{0;w{emDtPpnU|ZdvNwnE>p;Sn&oiR9}u>cMlERUNf8)poV>r>u!cMs$fIFQhs!7q_Rz*tVZ}B`uYZg2#C!-83eVJAsDmKD5xYZVT;pWcLXHM6U+h&8g`k9zchAM*0UN>7Z9H@jWJiPx@CE9APG+~Tz;yJF=fY^G04Wu198n)lQR)DJPMh0+6m^hVE7|tdpMPkDyTAVW<;O?A-tFz}{Cd|Ib|1qA3wtm;RG3)30WgGN)n=|vTj8(y<4{z@PqK6v)O(>NYT{SDuSGKwM6w{h7EB|oLz9gvuu92`a52geq|i2u2?!KEm|Fs$uUf#!?{G<3s(|IFR=cpS|E{bm70`Qsk0<TRY!0lLUIp)%`5#XJxBwvTFanV?NBa=1GQA>tp&vo%$#}W9n9>jQ1AXfeB~e%s%3|L4d~mN`k_j_pg@zPr5ERgm3Dj{ktQkWgGb121^-U;uou;FL;Lo(KjeLGItn(Au3-FOf8~nK~n!;c79>!_`Prz#*h|@W7815#`Kqj6<BTzyI@tp<&@(>L!=1B(l;w%ARtI|mFdbkyIk!Um<rG2xB+%Dj(hye*kJOyWZgrN;bX~f^|&4=I3hqT|HPoqiSDj@_8Zj9di`xIz%oXzgl8qo|ue4sU=r69Z66|Iu<PeLk|c<dIIt735(S`3C?t@uF!uI8(hmwaK??XNK(dp-~_J?{l%^p|QGe1x7|3ZgYIF@|jo)f}ERYrx(2`=^}~6k4dUg=#WH?Kv5Qtss1M(0CW>(TD6HfM4F7otqzEm&{^(4^%k$6q}zEvB=^3RrvmC^TqS$#LS*Nd-8oV>>6d+*p3#yNserwC#t=PKteOh0d1w;_Nli32J;Fa0h%IN+6O{cpTr}i4LNGMfU-gSiS^ZpTn$ESC4>^wdp@E7=D~d|Yvmw$`R+fD9|jWG{%e8q?Vvaoy#%-OG0ciUg5Q9PPD~Do+S(|d;jiNwF)2PKXlye1XCL-n`X_(zy7ASMZ#JGid-`p701V(JoxmFIT&HvN#(3R$6$n?9T$t(u_F@?Xv)e44-`u*sI2*10YZ&Q+0Ps(lKCe7Y`fVWHcZh|7B$bR3c}7PrIT8*VE%+~&KbOt7`SsZT^yRm1{NjQ){~-(BX#U6k!vOG4nZ8``<{!P_&yPO5_s{q3{_FkyUevgLa??EV&YWGq#Dd($Kw{8?Wd__PTLq5B(-+UbCx*~`@e}}qzZx%|?S21kAR3Kmol#*NO>ZL*e6OL2Cj_ONXgrRZC)!;P<ofv}ndQRW3o4<eQSd(71cEP)-#jV7nEiv({pMk#M+0gO;?XSf6OD0_r8m)a1X3b{a~1ra0Y`oLO|Uxu=djLa$It)fhYULBc>w{s-sdPA>>who+)|C_PoHfB15|E2Ab2nQ`p6d&QA9cVjpn)X_S-p)b`O+qU`~F60HBRF*5NNdJ#_N@{%Agk2mkUD|K))bPbUALEc%OI-Z%YoKka-Q!Z)A1{QiIZ++RO%?i=9yzrwuFety`zH$?aU`BQ({IV+Kl5BI+b-T!m1@$%Wr|Jlp_bMx?lb6=0{{~Gh|JZ#<q-G@;hgw%hD$#=!^_w8&p?V%ZTo{hu-<0JH@pT*<pESIO-Pio|54yY~PJm>T7>-(8BOpl^`)+0ahmU1e;>PVMrG?b%7Rh$k9ckIeAL}&8gZRau&UgPngg^uFw1^n};Z23x!rM-~9;H4N%dm(--b8$+IvYses9s0|<!Q-G|*rn(wl<ZR2P#uF5dVP>iXO_{lVBv<bLKWfIj-acd$#VdTNqZ4~$m48hAH+{Y8EutW+Ll5R#)U_G1=>>(Zi~NFbOXy`K#EE3m;%|7eUD)^bcWAm>KP2dadxtyz2&!KsU^tggsv?KEd}!Bt_gfZ`#H=M&<5US6*+)fu+5*)#y6jQoTQ&8+tpGd+At*SX_K)`Ob1KHqiCAP172HaNrD}@WUcy>;W968n;h{cv)=4}8n+h;Mq-)RjqHHS>|8>bZE_g{j4L)+1gSWp6oYoX6)K(piCS>U%SumGuZy4FK|$N{)zhn}LKMuMBk|q0T5OI4JX?Yi3bpOIkjb7a|5<N(4+f1QG@m!>&w@v?+zLDsV*@B<_goomoAkHd7^=N${zq$_kK%Y*p@PExNluUFu=wzq-5!VGhY6X|W~quT;|W3^8iGscLm2o#FMamBg66dr1=QGvx?7l+2;-@XqTDxaP^?v_EgELmAuZc2P+ikDKO}7$&>iVbf>=6=#@B<WB}($PZ0t3k0_^Zl71Z`Hbi8hE>+|UVxJiYYvaG+ifV6jm<OWHNoRplo@PV9XafSJppy7igi~F+_=oU@6hNDDt6B>(P!lX4D=kZ)dAH#=Xcqm~jJg_jX>+>zB%+aSP8F2(rI=hXt&$vWr01VIqh|8iQ`;_TYji)~T2)`?AVb94fS7Uv<mwpsxIwEg08{zks3@ksEKEO2@kg>fTTvd>BhsKnHUD*B$uD7h?M}T-G>?gzWQuwjjEik78W!Dd){@>?GPVsduF{rkz{))ldUeF(SRK2tp>gUq7qw<1SSj0BL9*3;e*dUBf6>7Szt+M@g5cM%aPnK*2+(>(2wFx7`Mq%9WFH%}M=itXWKUAvAus|cM@2!;^p9hjBzrz@~U1SLrv?urQ?UF@?HGQyTQ>-2Q06S=JZ}kv9&`Dt*2V#0=knLRzY8jTXNi)n0aK_t6$ZJEPSf7&kGdsVwU##F0w7txwV51q4D&V&miibwAuI+I10E7SnNNyh}&*iP%T?(nKXZ`%To@O_@l3wg8jCU|2-133)GP@^O8uRCPN~d;9u$UDhla^OZk+b0G*D=HL3LKK*rQLsu!+<L8;ubllF(1uB9C&!RWx;z7(AKJj26v)H1s8TEWeftgzvswbDwXT-sI!0AIS-L3TpnMZbOQQ$-g&ow{ulbmPF(c!-PvL1BnVAMypby$y1k90E1=Qsb%;j(o&l&5swd?pZZ%@+S4LZ?OnX6p;L#`Dg#~|kD(#>OZ!0~AtJbr<y>5LFqtUk#&S%4&7kH+g#nVyLkDc{iizM@ja$i*QTZm5ol=;y|kQQCD?*Wo%qqU+nk4Gv{ISSV95x^9z)-4V0@F0&qp~55yItwtcGFs-bVD6)FatC}3om)ZQO2s!xfm*Qq!8|8f&a)xw0lNK!!IvOpcR^m(s+53w7;{4YP10Wr@Z1*d#OT7%iu72JM^gA>xHKa@M5D9xV?3d-hB35XA!jGmFi~mSfuXAfrc0^{4U*)8U-2vi$!8vqlYTl%Cp#EAKc+DG@q9E($i17~oQ6p}8W^5l*p}oAZjYKr$cO^%ZpC33LePLOdo0S{BCaGL<Kt#DBd265!h1NsO1jqj9;{ItYJ%46Mo^jbBz)z{v)7{(J?1RN#$L>=ZrA4h!Q-~kdf9kMBtU{8$GN(HH3rie8><zWv}XV?#U%Kl?FE+|kX6u4KmiyNCJ+4UP6;pcnzK49V&P~d76R@r<zSpp{=ea`6R|O9n!=GD>Ny_Cp4k;>5OD~0&lM|Mh$cYDt70gch~L&KeCMvhCY_JsI|{9${04RUmtYQLC(V;PLnlzB>wq9YDyKmEdxZ8-9g8`o`so;5mC#%aeEGYuTsT2ti{MMa7FfBs-VXff(FgR0g!7eZwlj;E6mdgHI<M$;d%<xa$Rvs56r=r&g)rHPz(&zo28zw?eV+8Aks$R8y#eshjUd1;`L|*&(kqkR%3w`Qn!$t=x=W|ICa1OFa|8=B==EWv+@x6oqO8h4LG*$ME@rG?!bfxjz4Q%&`ySgz4=`rPJQwUJ(5<o-uZZmqbAcSR$uyfOa?67eQ4xia$r<L*O3Obc^lBCrK;ypRpd$GKaf%yV8pIu{__&Qrx(7*gGfDGV($CGl**BT`4Y}<Q0Lu>b{0sykr1tsn3_csn2H$8!@KCzTqr!cerK6mh#E<9-9AbJG`oXbty>RJaD56orbJyA%$e^f%$z0G$7+=;g_#@+x8qw`nkPxiLUaf7}>sCnv;sDUAbCphwn2(yo)t=3KdWFLramXlWg;{YWaTat|4zW}W)u`SxNP_~x5)ZUcx)Keo6G0WCwq*^Pq2s=-g-B2x)`}(@V2O(Et?{3p5JZZ|!fX6lM&Qn4i8U_M7KIclQT!IZv(`)KKK_p=QJWu0;TC(tBVuH6^wAv!57EI8LLr0$_FfJCjeZMoS8>RDo3xIV6$>f=Z#C=B;&Fs7+X%(7f!JFLiH{1{P^Kt}E<ilwPuov8WOsNR5t1E+mrg0}(;`oD7~Yadt;8?qJ43*1i00;$%F@rpGQsZds-6|hppN?Ol%Ydsy$DbeTgD*MD~^i8N7glbu+X8U2Ccsm^jU?8srB&bg|;kXkO$_$1HDjf#irPfBbKRcQjb^KmSsYwV8<CU+(j{hCX~Uze&fyVuG5BsA{u4HPk7BtOApUrn&DQ_5JN$4qPD$nW>JDCVOPxQhaB^c+oUIhX?b-(NUvy2v3KL6pjma*6pz5RRkS)CPcX1&6wjpOCej^fuuB|fRCGWrH?#4L;ac<9xrU(^mNf&*ii=wd9CU3jHo(@B{t?#g1^!#Go7o|ag+(oj-?%%Og)6h|UM(nDA&)x7xCkpx(^0Lpbi0qOCc2)(T9ojv<Y3j-^BNczA7ha8+(U>eO@%^AD<;}e%+v3nQ%U+IhHJ!?+kn&g#wzA^HYfzyGSpL9EhQbRB|wBE^uiW+76=x1`0BWXp&}zXmzKEC-{jc|p6jUKl!_hSQ?nv!>|+{LQUnFl@2l3+t~8h6_|ymDl~0j9>vzOkb=5s1aKBoJD;b6hJ+?nT6?iMU5u;SGa@bkJ(?npl@kF#y+5rP-9DR&6kPs~@ZlqMr43nw_E)0zTshSlXWkra&u~9W6Fsi1aqG~E6s;1(hYK34Zd);bV_R0yMah3zL&A8cs%E{$0+_xQ(MSLz060~oi7<`Q<s}y5P+8Jr)$`r{Vu`WvrWztf{el8@{Jx&qw_j!^DpWxXoyrGEgy31n<aapjaVx9i{e7O*-^lY#U7G-#^Kv!KZD!g(Od>m|7TMdI+Qp-8x{F5#QWCx3ij#cL33$dP02hbQTr|}UdZZ>z<dV$Uni+l0+ckx#*?(=#Rp7-i|{L3I~V$4^qCJd!1hN;e6J&9i!DtSfxRmoq(#_QG0VDi$$F;`r@PCS~}0f)2`0iuSxy5%j-62dWwIiid3aaSp3d3|!!K>D{pCx=6jdd;M<@DB8w=w6iMOd(}CI)$0RI0mrIbcM0DR^^)zkdmQo;z<U#iAN5tUzwM}sE8!6EG31Y--4HMrM3E?urC7l+H}#}<uTM*ZIxb=M}*w$FiV51U}~N2JZMS8eE6uL%?(Hxibpd&iXxiwo1NC9s$Iwg&Qc0AfxgC~W*BcQ-q(Oo&huO6m{QB;qSy+)$tPq2vI2;F7S!5u)brBBSDYgOWpA>Y`3~M{ffjA5go#Rf17wz)YF~FpM`ws^B*W%GI-JE5=}L%)nzQI;m*oV+ygaCAlLtmwR(V&UH68@wbfWVPZE^yJvBj<dgWf$38Y|D8j1vSb-!+kFm}0UKPN-xSdfc#zslzElhgV>E9BkLOwK+mHX%^n@xmk4-6t1XcJSj1RN7aa<!1ILLL34$@R~2fQ?j?i@6g?$7Hh43m$(8!lHIdWJ<>oofB_1aUzsE+VBgO?WA}m~mnIX5CgP0l0L~}e!Dn{sPmeD9{%y*^q5uT=jZh*z<A%%6}9#?6|W#$d@xXq}>V3i(FEl%`7VA3by%mNCKFn9)R7TUe>$Z(YvN0G`&7ReB;ZA~hXF>nY9X)=@Si7Y}fD!np4o-yJ&5e!TjM}>OO1Rm!$_=F4onn-U9teA?-898UKj7MgD{s5fFoZ)Jsf0L#2Y01#(8;%`E92RpKL62Nr<hWXps|2Mfp&VD?a!uzVOM<s^GY=mF%U6n1=~>0X(8}H<HJkE2@Nt7a%wk3#lK-#hL8SCs*Mn6o{BZggyOa62CzFPhb;LOl*Y#tT3Rf8ASTsZPGjLndMk>BWp(##wqSyoH4l*8Hfe4dcSk3C`Ifao0sjf{bRX@N;)ZQIXt5?DOno{>v>i0FJeh(e%fRfkEiiP>BQpUb+)b|Po$;w~id*O<#ZIji_jg!X{_AIigp>Vhd!FizouKlozhDf0ZwO3*KXtolIc-I((3?yRJXbmNl$ukSJbt*Mqee@*n!A`$UM}?YXbW#W_Q1Rb_m-t`R@}3Yz4$ol#(XyJ^lyL$em479|3YA~xgAqzT==Y%5gGO(t@>&sf5(p{-mF7|v!Ex9CFGlo_8BDdr8ZGXEVBJo|E)yaVTL}c?WY){&@L<{CIqik<unY@_V>+zH=#rU%JQ`C)7V>0eKCU$U>Yh%)R#$m<#F@xYop8Yagnf2lmG!o`tcv&~OKsRl{a&F?_(VBT0QLlDL$ZwYI(o@xohJduNv5>9yeD*+EFMzcDgB82K~lovfu>A|`qk%|EKl0UnacjZ!1pRo6-i+5g0d7UP%OogfEcWEMrq5u5aWs&k4-_=nmkCdn*6FZk&I|6q$@BPL&70Tx|Gr=3&l)A=M|xJk0qz`)>N;&{SXg^_HpK_sL<mCUbX!A;+&+c0u>>~3UFEDq}sl*Vk>q0E5}?ouh7f7&TEPt4tkVA4yB3G{%FmVhy-l(X41QkZ+HM@t4B3G<qgh08GL>J@nrCz{#AJkV8UdhkEL)-UfsbjediXl^$k16(8z&WE+_6rkk%{OxH3JfxpBD{>CI4s>7sL=QM&7@(*j{7b96AaqR>MzJvQj#%%u}-o2k`~gS;}qeVpA8xuG8h=~chVsGmIFRQaN11>6_%q2BAES5mJhR7ifyM_JghlgORk3C=K#XMMntWH`(1cp?gf=;;`$@_-`jx>aE9d_~vl7#ivWEx@uXH?Bqp(C9LD$cXX25IEA@GtO+R*qhSe5gzq_T%4V@0()G-x4pDK(|J<>8rQK-H=$LGY8V_wibn;QYl>%QZQ<W8ki`w``26{EJ-$xrQNKR_xC_9GccW>tD=(zjolg=B36_B#(o;s9<gbdtFh*7Ck8Z6g`kt?ckrUnNxTxzIt}mehFB!^U2LL$o3}LOYnb=KfK$l)wxct>pO_ruJVPGbDWkZ<gsQXRuTlywM0<l0u_tF^?K9R)<C75OPfqe5Tgcs7;G#S(4rx;r?f3GPgs4m2@i%(`K5PLdQS5!-i%QSh3x-M@wPiRoTH;pJEeNY;p^{IGrV`M+IPZ-EYBEA02G10ICQ)sT5!E${SkU9E_OBq4+q=%Sh^6<XLNow6N7GmzAzs;*jql+{kZqA^+>*i&Ng=#L3^twza1Zr#C^A@DBw>=pvEvU9p;-Oz9S75+MsSNzBu4sqTv$he#{Hp}wL!2Sca%5>~R4VJ-XxO)kU)8J>FYw;W9ZnisTNAJT^)iR<<PQ-z%%-_jnY>QZr$E^I@ko!gWl54ii_4XX&L_KQG1#_9r~`KNP;HsXk2!3{pbOR!r07F7$R$?XM<B}6`Mt@P2G^u*D1akp;QJhG?(+?d=_^>k=KO`m-{|4S$16ry)wMI-cEy#ESL|&f^160~9$dK1LPOxIZnQx6-ow}Doj0MMSE$Ppo^;EpzNI&Dji;@~i>{9bI|ZA2t>#mwps9yap(jsTPaFRJQGV44nI(BfqD>?k-wGOSy({wH65hKR$@Y=$)vArW(yH;&FsQ5hp`IBpk#g+t5>;1Fr+DO9)P}RFQ*nl&?zd<)8s*np{J+M7hp(+CmfhNLR}~2Xu_$!NQYkD<^Lgt@(|3c456I1b8juSc0}$xxp1-V^F^bq02-t1L1w%1|fT;f9&0@l`hZ6jClp`oagX=ff*Bue4P14wHk}~6RHb0jZ&V*$J4A$Y&^mT0HyMS&yq^3m*3wTUF#o36<??!{)qCQ$kRCnwpf?icQU2A~T-PO?FQZ`=nLiex^$v?cqat=~W$wJT9HYH<3qQ2Zkfu(LNiFzm2Mm_VwR7nkyODjLxL0}skW%`gnwl92@VH$GG1%*qwGYc_@pXr9aHs_Zi*4_##;w+2si+-cLt2ak~o{5WvxCz@GCJQEaq{NAjjh1^HHpCM8$^g+Ec7kRtj|QRoTfZx0V`B7pnS;@Ojd~{OUG5nHL7O&@eCe@lcQMgwb;W2WceAYxD$C^byeeF<bX6pRc~(gLQZR82GqhDu-KtOv^nDAqU|VpvSuIT!?gm@sH(^S(Wg@a+KD6!E)<qF*HZ9sgUFfz)A;+1xZ{*iW=%_xzo6mnA0vaaUiX%Tqw&he;M$5M65-q1F88zF!J3R{?1iC@Xg|Jp+l5O8TXdaJ*cHwF?dn1xE>A5V;E_T;uPXQJ}_gYV0xDDM~C4d_jy87KL@$`A?*;BWKGUu8lpFM3oH||IS+Ok*Qb1DksZ`*TKne-;-c!?j{!S^pX3?&R}j(4{7XwYg{EjUK(VxNXpI+<Y@w%ypu)Up*`Z5z0HB@^W>MMvc95gC2<yfys2q@tu9zSQVUZ$}EwTct2jiFUwgW5NPqSL4_u^3WW#6>INIv+&KAHAfDtb9(sh@FXOWO}63Wk+2404qBb&`zsc@RYcK8VFhvZshg#;y5mG)x>i5LU~gRPsaIKY19+Q`KE*vIO{$iGqXycoK-K<jn)KtmTm<vpQ&S6Uq&AJ(<v#Cx{i8VHm6zmr<Pk9@?<I_~l;4ub73Brd+|%mC|1NkviZDeVoiGh!XdPJa4D;FTi@&$Y&25~|Oji|pA4l0Jfe&@-w&Dz0t1z$EFfuag5g<hfjXroXI86^*z|^YB9w}X;@Qx^^d`;iCeetp3yVY1WEW`_AE<60fV#yY^<Aekb2S4zmlzcV?zbzce^<~i#&jku%l4ndx!J&%|dLq58yKVd%pcXt#4f0TQn!uGqG%SI+fcZt5Q8)B$60KM#o!o1EL|yQ;A{wMxuJ!O{kx6_92@;xqT!~C<tOeHv<Rpx2**80*@$&B(C`(cOF4zgK>vz@Q(IY^<$DqX2@9EXO`RaFi^*g^(a;r!^O!<o|Hh=W4726|uc~=$b&u8gyDC5zXtELkY=?X`vTPxO9ACh8Kc`ji243Hx&f?2jt>JOF{rIw!jlP-h#3LFt)H(`k#)>Ayb5DV{%ugOv7!Z#ACt{ilw9R10uZl#YpVjlYh`O*!dJrK}YAs%UUbd@P9iMV9iH5AW$c}P{4h4M(0whfAq9Vo-!rSL|n#SGRhLnlq7HzFwQXhq?9X#_3RN59SUS>?r^jDBGzfu|WjNaGCCIPKu=Ae4|W82~NB>qN8QI_^hvpuu>i2Rj+Z1#dCy#&sM|RMc&K%gL{Wf*M}G8X6IVp}c;z(LmLNlAh^z-?yyb3~uBFh}oHx_ZT#6v8V7ybStfF$=q_nU&BbMYD9^07?kmXGMXFDr6!4*Yegs}x7J4QZ9o&^yIB^kE{G?fRk7Q(d>}_7{nW!(GIyLA9ck;`%hp1x>hghO-gg#KSzlJfdpdqtRzu6QqJUs{Y|6}RS4PjA(lL1XY%lof<oJDX-Z|*JzdSn+4o*7zr=9aaUCwGKJXW=fvk&J79gJVZlz*0oL1~@K{qwh-ODNB4y?hm10I})73tH<n^@0zl$M4V2u>N*U+}o>h!s^wmOfxz@ecKYv?7Z85|Gsk=U{jsr)8Op%<mXqxo8$9~%Yc-VSMaJ6?4MkooE^L>Y4mje^7yAtaB}>1|Mc);m+q^**nRT>L3Xjbe|mZR`t0zybFuq&NAz<6Fn)LTQ|GW=Hp_FMyvL_7G8`Zb_@ae=>;@XaW_!BVmGkV1dn!i~J@o<I)guSRYr!K6le?SBKUVBRV@qYkOy_w|I3t$^4XJ{PvHDJl+%O}}u8gU*HkE7a!4>QsmbWuTsoKS@77C0@?WIyX)-VJ#KtF9GCYv3%-Bu+}ZT;{hUwS?>Y#aH~m+Hdbnuy3QeB*%oLQ_>=e2bN%$C_&iyOS)=IOO#;RlaJTY^!=b+SY>kOUm2XEa4w5Fs18QzJ~ws_4@<X&Y<aX4tR7SjGKnX969po%#0#)C2(|jh1MVG;TProB*8b7)3j|QvNgFm-#6D&S4HQQLRxprv2DY{0ZLid`nt62WUnYYMo@<TT0yYf{PduJwtq4N<U-iHb*Hqxz<iUS!`w0y+0E91&4ctUbCG!nG>#_8FwUj9h`{dHh*pNrR9T|VjnEM>aA7Sn?=eBkw91+9xzpU17T83OncbRIyA2&q=xIa^7Z(I;KX+;?cfDd=<&Z{qjMG0aoZ2#Y%Trs#6NOZZPDQA!I3L!$U0$!=CK+1;W!YPp)02-Z^@-#f%Y_~V-y2{hX-2cOd3k{7N|nJo++lSs@dCiqIX?>y&fdKT`R4R8==|;SeE;AQ1dcc7XYYzaoNb#k1F!7!U_uOGR&F;OtqMj`%0lp$hk;-fpj}wyibxy6+VE{Cr*U{w&1R%cMJtPa;bjMl0`JuqGdVb1EGbr(a<zFb!sZMyxa63+&hK6rGA@WF+?%nf1R)3%@Z6BicRnGo%|vswSibR6l5Ha1oT}R{vh?Sqk>C@oBAO49*=EOMj(@(2zwpMT@lIVE@aD=EDnS&vsCrsAZUz79#xXmXl@8VRK6AN^iW1=&>&*h|OG=tW-XA<F5@9PI;8j&1pp{wzdv)V&aY9#I6m?rnPKU*+Y!s)T77`fumRabAQHo{5^v=t`xlqU(8#E~S@!BTkYMa|Z;)Yp{R|YRQs|mWoZwh643@a@8N|XdjFSU26xTDS<>b0+#{!&$yU`{hqaV?rY%0vyfN2#GI^sfvgK$m?fdx1WUS7l{4WKgP~;(;Niq;|HM;>y&}l_Y0f%dIMlKKBNcDu{v%b^&tH=TL|d9HD7{R!;N0mFe8aE+JB3sS|X(F)mccr~b0&%+s4hz5a+x3XHG|7sS#K-tw%}meZUPfL#%@tC@4D=|R`zhzvgVAj!1gUVP4GvjM}Lj_8t`c}C}WB#6V?VnE9orwfx^Q&MUedV3+pzkDSpkhd4cR4{f4=h9xNDZwi|AZahe%qXcQf~~#KFr_=H)KybF62Q}&SYOJp+vkgY^!*6x!Y4E7Fb>dj2?L5OWfw)&0<|g}WQFKlr=LApY3&^p+?zV@TzBn|9HtHql5gDbsY0BPELdFuG>oMZHwR&6a06(>fn9*fY!-3|<)K)sq#0$i6-^cHVko~QhQ(JSVKQfH?XlF~-oRI3ZR4d`d*o34OH8TN2RwiswzeY=*=4$~c;a;ooyIb!1KFzQ9NZ_OzVviF*O1tu_(bAGza;O93rb2maRMI}K2Z*bNjCr@!&rPwCId5&U)d&1u+x=z>Db_QSWQHdC!8)wiZo`yvIbQse^CmhK^4*qtQ^%w`2~!U4;z&VEJ9Y+o265oRNm`9Ua7D;xG_kDZrLWITGckXEvz!-1NR5U7)Ps^jI71U@EToz=`8*fLz`{;l2s*c<5dctnj!6kycgv#VLDbtF~mqp5fG1cr1+XAeK8)h%3bcdcv!o}yE|p#!)OSc#Am50>_pX{$iSR_!d%ORJsRu;PU%fHtzx!1jmECPq+&V^|5g>7VBuY?kg2zCk7ziSY>--ci;@(6Rl_RdY(dN}>r$}&KfF^RikEdepCq6N%8<cah~R3kS*qBk<5-r0)s9ablcJ5fOhxT&p<ivjfPpxoYokG7(~hG%>=-nse_+SO)Xfhe#;SkkT40M@i2R9GT=QDzb19gryp_J2E{eiadOcI-7!sd~(SN1@Rmj#QyA?-erq*KKv?;>0WmF%MlhE4^r6F&7G7{9Rt~Qch{n3Y{&tO=g4mLD9ml20_+L!~kW={vRNR8CIDvMfpii4ttRif&IsW^+Nyb;~tb-NciaiKvPmx_1SO;UHoy1KYyTO0N(d3Cc`PG^YS2VULiqNTo{j|V!Rm}wO^xW>^Fo+>YGEJ1O`Ymq}^2UsSi(vUHz9vl}Xt>vmXms+lj@Z4a<O6B)LjKi9=O;Vs=)2El8hx=uDMZOtp3NY-JE>Db(f~c+O98c2m$Xpe}9jR~$jh8fftWnNIHMj^4m9-5>s!M(Sni+xZ)~=O#FDj~Es8Y4l>J-4Xen3ucn6OrCWRr0fDmf!_DHzElYet)nuPKRJG5Y-KQ2}(1d?>SS@~R73k;kG5fPwt5$<$@pstm@ndg~Fg+K40dmzq(`n2Ivrm0jWNG+yfDP$C!$V~5|;!L|w&uix5aw|ZvLT_r+qV&y132VNtDuG03j{=81iTHlIs-o08O|Kl|AauwV>=oWxc2i|@pFx023(gMVQSIXhvEQ4!4fA^2>rd#^uD;B}q)^eS=?`Na$T*ieY1=x0y)3LL&+YKU9@Z@cM#oa^J#kwMyz9Zd;jMoT;1&ayWT1?pPF6*9ae!|0)lV$;>46dX8N4%f%V;oa^pKsHVi2BW60aSCm9ht*{`Dl0?P3BP1ykW!8ZA`(CD;O^PwLtqBQD~@wj>nS@2@3wYYIe=wR|Rq2-{=%t3$)#cd;$0%L>zdCqhf=yBPsOL^6J(G!mYf3XJOBi@||fxX5o(1lzw67Cgb^7ofvUa8@#rJ^CtnZ;N|8LFvDkidsYA0ks6Q02p&$$Gd{^FsZnuSB)quM5@HUjy|5mgYrf5z!JqA#--hUT-WJ#+lbBDprWex4&MCcHajrg>KQT^pXmqAm4-SkSj?3j+!Fq5k_Jd3n<=q41bfWIQ@c6z6d7g`eUA)(me^zyU^5tDwok~#cIgJV(*$1Kt%y-b!elxbqjPM&4PwX_zj^?4|*)0@*ZHgqdUo~xb)D%U3@+{%1V*Pe#Y0*i^5dFPQ?%F$1kE2$|Zjm^l!!A&LA0^0q-%RbQ=FgT@^9`?7s)-5X8o@vkKD?<$T)07(%Ig_w6Po#Utr^WMy!K{z|9aGHNIRFqH=YT!M#HB-iBOxJX=|u!J(OZeK||6+&QuLK480DGsCBEj%xT6+Ra8aZ>pjdGn&b67q7gF~#_3fE3WuFH`yWm&d&g&|>_w<LHjaPn%H;02s_F8)q;}C&`APkt8i7vhj0W9K<h2;ZJto3e?g?JJ;bhF#4j$Tk0y!lD;k?=^F*?XY07XnWEM#F10vQ{H|Fjo$CP%AIFP6do`7Z<G#IXl`w*sn2KwEuQTM|2ET98c7(DJlc&e*%_tsNIE*C51<^9g&eUu~+uX@@m)=&RHMS#(8qJnh0}h~X==I9X7qclVdQyZ;@vNGf~B0#W^5{QbSV=>fT1RPXXzHM+I3i$BdZbE4XLbJ)R%hKet#aNyu(&1tpjwyG!>37UlxW#}RdWMad}VbL%>iTnHtT)E!&ApCg{4m}W$9*Rp}g-`m}BaUD&Gb!}SAVg_v($TQw>uQL`y!VY4W@O?<>gRH+Ozo7-;nEfgIkPEZ7u|e;tg<JR6REszO1T_6gW$Z<)5{UX*w1UBI(EFB*NR%Qha!x8qSjh*t0;0&5aeUMU+^K^6`*l;YH3^LBH9Wu%`2*z)MedD3dl>JUf4DxGBosNX$37#)oSUr?#G%7n^GT3dy?xC#S}`HqDzJ}xRDg-N`I>*Kmm`P>1dvls363^RpOuLcprn|`ZM7N7ijlEX5Hw<97x4R6Ln!Wmrl<B*|OLe?N_G_X4;d%dtTGwApvFP$~&q#<z)@?bcSGfanP9CjtjP=C*B_4V4$B=QK=rD)8k*M4c-H0k9%WSZD9e0cH`+R&3eu!R_tnl?aAd70@8tuwIaB!asnhYrPQ>B`y07&C~w%3{|YS$+;aW&RyHF2O+DkW)R_&(RBX;3l%@6POCD8mx<SA!gaoK^B^+MmuBO|u)fN}Ndu9xdY_3k^HJ=ZM$z5f;{%Mp<dvX=Y;=NrpV<{-n`CvYt<`rl4I4jL$)^3_17Te^MxUFu<LuYsGB`umjOEeyj+YMfA$HQUVCwgQQ+&1W=*+5T`T3=IT4LI={#uu@@TjlIPFo0I63NGqM2LjV$+-LVRDi%zprVqIrF__p9;yOHB$A(j2IKAORBoP!|j0h(_;Tg#1D4U?64u%nYk%yA*NusZ!+=AjLk6c}>GgJedTvWTl3NtfVP7JfN>9P+y*a%E9=!471oJzdeuv#f82u){nvlnOAujt8Y!R^x8=td>nwSu$CUgbu%f)z}`!bGi7kt0-W*;F~~5DLYmi|bN!rEiH#>TQ-|)MRdw#dx$KfLD>8`SdNc{cV2god4WA#4z`h&LRAG{o!qWb_YDx17@~7gJQ&{&O-LJaFUvvlb(#d`REaGG8s(a=Y5Kk1LX?oYD+ugNBVh7<-S_Y_yi1*hPFc~GpGyit-~afDAoeJdOY130F3+c5H-U4SE*LT`U-{LzCSp}zn~TD;O}4@kFPV}Hvnh(b0^C4w4X#XR`L)BvC2g{nqQA%^-3KmsZojyjG}w@0#lve4zGy#I7vTG6jTH~4scE_5|Al_y=Yi)IS|bT7zKu!MdxlhO8OwM%=0)CBS@t8m0}Ahx{5XmgC!qF12`=sz1BgB>FhtTPYo&=yL5@W$ec16#u<*|RWL!%TYeD`H0feD1=45)`#@*f5-$3twL|a>zPU)|N-@3@Qt~}T@@5V#u<0SSv8ImFw(^r3h-G>5ue5uzr2~`78212I!pq~!lMaptV?a5s@-LmA|9W@<<0}r3=KHuUW~GN~AAi*I7#$ocSs0C`w^9AaX8p%OJeoyc{`-G5|NDP`d65jCKu6qI5ki7L^PQ^l@)G+P#Y6{zn^(=Qn^Rhk<Jaq(X+Qh*`pZrIM;S-|Bhb9*h|UWcW54`*UHP#!h93j?|3~<L|GEMHZ&smVI!)5VDBFk0N7u>3d@1I%VywJb%f~74?29@bj<YXxly?jL#iK7b(RBnLr=Pyy<qThd+`!l-G5ou}b046L{dX)k0i%2lO8qDS@Capq%rCo2h>S+Y@`t$Yx~o6wJt}DQhl!As2d{X0kLNkw0g|TZn5YRwXp&m=0jU_2u`L^|1zst!t=`tu#M<&l*-=2dh<H_bCeto%>#BJRg8AK$>L}p8$~<C%(#r^FCGc`sKXK_#di`76pLsJL*r)l16Q^<N&3c!*$|t0zp<De%iTY|Zh84fiJ|5LqSJC$O*a03tB@?<Fi<j>j$RX9mbA3?5c~*hQ9EWzyZ5r8jT_vKJ;Ki6_*#_ig(vfqSG!L>EN?x1}R4qWuJENhP5{KXM&9F<E8AeT|9-3F#&FF@ELQ3ez4zS{^26T~%myA_QbJc6Zs$JV;BgM;slsVO|#M+2mhhlwAlWOs9LdUXYpmLQj<Z(u&lpE{V+gJzPf@^>(^jmI#(#7f`s;vU*Pz{CN>RNMDp&v3w8E*_zlz~e?i-+^k2ow$?$5(qhFZXwT=`NlwLwRWPb*P1@*Aj6-F&a&e4^@V&KV^<P0uDqZKKq)kDpItrQm@+AhOACu`E`={AJkpp)||pVlBYhl<)B<Kx0Q4L;e3^PIsJ9M83^4nrt6dvx`VT&3~^1DUz&+003_0##)#V$Jd8dIeSyMUnGJB_JC*th<F&hG?0`;l3VCKl`!0WZzkk{}5s|~pCai1fHo4HRq-Ba0u+sm~d)A%Iix&lzR|y_yHcloyH(iHu#Iy)8^o?WJM7}uyKeM<NZ)19>E{)SCPYNS3Cu_t~x3k6z8eP6-xRN?xNoNI^dnNH`AQFChf?154W9=ry?Z4tfA^$ag5(=2nL(yufzDYb(*^23un}D6dhf0VV?Iiw8Y3)NFxG*#VM9sk{cD!0Jz`mb<s$))zztW2em#Z25xAo7eQ=M1)7Ld<kf96Mo4PFtOJ68>W!e4=ZJ{cRvO7$qy#nGY_(;Y~R%W|58DzKm3%rVzH#q?&CL7ex2fnW#iUT={0d%dbrvmOlwI25W<33ql<3dTpN8%0k>C263;r;18ipw0;xiK{D{r7}Bo24ppT8;_>#5U;W14Q5DVuVlYDdOo6W<MkX@W)K`+zTasCqT7{|p}0`s5CH3T_$ZY9Nq`HUMIDIj6RR7fNT(ec>4Y`}Qs&!0r_&5JeKwC(C+D#&N3tJwg%%h4VmE}ysy_7@&<>h_cGzrgoDC5yjU2rqQ8umD)B0Y`u;}2R-bHupTnBB<(jDPsB>kSG2^Y8K{^SO*P`HGgM!N?iX(Y>ois&JL9;%^vW%{}~@KIUK5N3+-bB0XYGAKDu3(z=5`Cw7NfeA!6lQf?t{owL%m%%hPtPP>(YIiYQXGhA7+RNsX-t{~g4Ju_xN6geDv{93Zbq%k$(U0Tn`{@`+^<ak%JS2Efl>xv~&obML73IhKqHXe7IxJ*9g$QKb&QKl>R*2*x+;q2{4Cc~SS@e4yf*#Fco?Bi<jnxR3+n~6D$O_ajE8N7}+|m|qgUQNMRDPu!<{(AEc#BsVo=QgUokF3KZD4h4NV_i*0!0DW4$LyaKHrn3M12&>Vv>q2f<;4$WU!zOE)bNpmPXb|)xi}DtwX8KaM(W14NoroiEngH>#pJIoacN6m>ANIbW|@^w>pz!S+4isVsdPpfUZp>!DG?UCj9Kn=w;YsuAFiE$Lmcqz(CObi5JxkG7A8>MQJz7C+{A4j4T-r429uA8GeIp%lkz3TV1)Utequ|l6lEFM3jv1*rXV`Cnb&IfrWyZKC;j!RmEeAvV2PpV&tG_<53EV$5wo8Sw<8@=4mQ#FBj_BE;*m8Q+HF-ln}ovDcY3^>QcpGFc;kJ>NlirZFdR&z+i5TRGi)@Y&Hjb5?C=6VZXPkTZQec^E|`_2+#f!x&`zlC+TOqwy;wcB4gQ(sx!O?3+!iG8^&;!lHId&=dLJY#fo7ul}v6|=B(p_{D9C|;giG5AcpCOVj)IC`2`HgWW~T~iC*~$dVPgQae1oAd3zzcQP%~84-Ar)+d~C5O3Wm!8MvY2J%q9bdOG)G3e0H->UUjaeuPSuHF4DQ32Pby!y!Uo5J`qSCYK$%n6atL>&ioj2Y3p2PbXG6?puZDWZr#4LR?r<j&eT96APGnSuqJo>2pCz0I)*6NA7mLUP(=lDVH@H7EY@h8gkcJZEe6x1c446?AfrH<=V}L`<_8tDwFv)B5k*kL(<Hh`35AP{8mX?;-pMKD6|s6ne?5sS3~Gi=M*}do=8awDmWXZ^KzMOXxXt<6>m$9cii5dvJ@yzxaDqsb$x-#v1*1qEeI`zw~1n0_>RsoL>uzNMm4UciVO4MymKL(0E|N-tAF27&nizrt62>W=d}%vrUXa9Q-DVzQ-Gn3Wl<m;dV?}VRs*D4WXuQY7^DvrGU*tH*t3G)Qr4{G)p~Fd$JT<A0&UK%zDhu{HkMy3`zZ!Q9w4toI;^!v<~jt+?Ggg8y@|@x*xK?<y&k+lz2DF}M1M=|tKb{@A2aN#F{bdGFrx_NPf1Pzq$;=+9SH8F%b#|Kz_Ql~-vB&K`yb<(%p5nIXR}*SzybL{X(ofJJTVv0*;98;;q?}q9)&3l8zH3cmD9>Qv&eMDr(&QzkwT}P8dZT!v#&?MoTCwT@kyCnuqUxhpRBtVI4KRF1b)GbU4=#u<UXSyQjlc%0GbxJ!t!A}!3->ewqA9T89%j+zH5OvLT-x#WD}V39_g1a%kB%6C7e?YCK?6IHR_nB3$LR*e!vOCFq)y?Z93f<0sf52gc`ERY<XD`1Fqg5r8!1{sX?`k-*{dFOCi}lIn4BWh*iCw@Rnh#&jnf4J9i04rigPO*8N|iZ3V>', 'receptor_cleaner_gui': 'c-rkf?Q+{la{u`h6I@jm+$CvIwq#p-yhN60M;BSrNwW8LWfck}h9XWNz~Dm?Po=86A9<1d$U`JQ^CtTw>FyZ-Gr)i!w(nAV7uVK`1ZH|>`fIv-x`)5|hi6$5KO6bsGalZt`68W0;q#VdS%*BiO`|z`_u+_5qL`&q&ORRdXY8Dh`8<Uu2LX3O9`{<UOL&Lv{Dk>o%EQ!;LN^E&%;R$&dORF2x|5i5=7t{25}vTjTWlD!NgT}x^cjuZN>XUz#vTj&QS8Qx9y>}I_xv<ru^hKMhfxDIb3=c^lQikDz|F$(6rduYG0w^lZ`e4BdCL!(%SP___9l)p7(B^F^Eevw1iB?@%-vbSg6IanW%GFy!#HC%9P=P>aS<Jw@qO&40Nrij`n%A{Td*ig=UEDv2|PprAgtA*#W>C+OS70e4)bRS5kQ1dO5l=KOFkPXclpOZB(QGzIZ6bOxtmS_1382<_?kEQw~S{z|57fec(N!yrhGP^_(9P)o#NC1HN^u-1Q#%OD+bOV$rjk%^IgDDhs|IV_lA$62S66QFW;m^@5LN3FFWstiw-;V$7zQh`w9I2bS@a9)!IKhb58c(57~fOMy9f;$;aXO#nI^rw(9qGdVQ<)X8&U793Gv+BSeY~*oG-OPP-TLBns}h-R{lZ7+A1%aC$y;E)LF*&Mud<ZoT<%a(FyEbk6oqhR1os9Cf`Lp5kZEkL`AwJ!95g;LjaC8*$I$p5vwSzC--jLo!+|M+4_v4u6k>fAjb$WXz(5PUz0Kwa2W(%d>8u^<Q>@53@0{Ou^#Bb!qH|2_h260b-GIM*Xc0!Mfvd0?0%_h?*_=STxyVSNM&wNAU+=cq7O6u=&nG|Gj8UFH$##MdFM1r{~IZ8WJD7<J7<7${Tl#42SGo4n!}`UTnYG-7Q<<qvt!%Uv69Zlj{=7E$4G52ckR&S)pO~X;=o6`X2Cd!+|MaLLTWNp#jFw8Tbmd3*&b@Wc~z%J&49`AhZCqn8T|FXq5Ei9G*JOn0fvFcSoCG#t%2Z&1WOxNRGm$8R$HL5PS#18RAN(ZVU}jW<ix9yT<IOgDsfn-}ou(ue0=>4_mK|OFwwi|Kg=@_jh()d=?Lcse2QJK)>#Y)HlrLdp5~%6qayMg`lc|J7&=xa0ckND7%@m521e+!}4eD9M#cUlz#&g++g{CmBkCH(~{pYQ1dCr-3&Le)E)VOpP;S<WtW0zBsmt=BKA+0KQ^p(`^)+K#p}-$_&Tw-|02ZhZ~u0GljZ+a7M~M)`)d<>_g_Ao8CUym|IPls<Mv0-Z?=z3>kj-In1Ce4l!Ic4z?w^8`-;~>M*qdD-Iw}qu>I=A%WeHp|JBac%g;ht5D?XY8Qfq#b^9GQ;;H+buy*6lX72WJxub%ml!d~KOkF>OPWOH~Wo`y$XN*b|(0z2c);96#=<Rbe|Lh-}>~A0T9h%R!$Ai>0s*jl;M>p=s4g64`cP)JG!1nt3b1-%O*V#UIj&^@<#LLC-{L+L5u%Yk4*6$))ttVdn-4{D6F`)D~+1Hru;MmkTN7I>*x^5JL=YmWm#jraMvZM=N9{iabbWhx82LZctW8V#dpU^n~B(5cjhd+JX3_;^@kb#}~cY>UsHbRac{#`N8tDnxcjrchkejVZ3e*XI9FB?B^Hp0&)vh|C{&FPPu;AT_N`h}zC_3+ee{U7ds718?LR{!<R>t8VY{J4F%5q>rht-k@>3^&1z6s?In27~@@20{4e`cnvhziFlMVy}fywNO}(f~Zc)A5z;8B<nD+Ln91M4y-JlbYEHR7Joq7ot<6`<2Z^1%(<H+tyXIsz+ZNTcI?pe!M;DFP^6vS_AaA&0OoAa79A|hdLMaU(sF7?_HPvOYBU-Ant0KpC@%K$_=Gu*4-SLl*a;6N9VViRdkltn?<eDq=(1M?HLozzd6lGb2Lqqi*KEK}V4ybZ{)Rq?>EOR4oAcOi_lf}o=yurv2JEGN8gSbx0;4pXRcRFS#Q&o^f`*rI#yjk-8zj662;+!8bT^N46T2fP;i+8*odxO2^|gv#G(mXkK|5P~foVTJRp0^-CD7`zcq-&$0iMXrNf&eEO2F|&8Ur(YbYuI@4KhA}fdx<u$=X``4)}su8g)HzQOBv(Znrx+@IqQw!<9_|qybJL+^gZpre-*~GFW4o)Doa%VKV1qf8v8ytpn7QhXz$^hyTPd2(tHw$Pd-Q6eyCr)wMX_KBI1ccURXig&JgVA2H~NkqSJ;8S~GEO-D2J0XXnBs~~7?xI_mHWEF|3I{j=MmO#W(Ojt5wsO$;r55VVM4*}|cxW=VRluCa!-%-OF^FEcr4r+7;Qk(*)x3N3pg_870hxfPJT2s(6zGuhL{a~xZ#!-;XLj07Z{`ht=u)>7jTa_N7)i??#{!JEhyWe5=+`pNogMQgEa7Ta?n8=m3P}@2?e8Y|oaS2kQE2yxoOX3hlr!k#EwrkBU=;Y-YMoVy7bc~1Xg=E&6=i$hLFYTm_%@sba_4!vIA;VY9j-;}sJ}O64x|~S*5S{9CCgsR-<*4dPrR}wfZw9pKFq`n%VYhtIW_}0)mCYz_Bwi%#J#8eU{xQC=5j7o#oBM!Two8H&;5y0gE#j7kfejD)TW$Kb80_c_4EiqcfV?&ibr8))(I|RQMk9j+w!cBKwOqm6uYpy3FP#o{UUkIL*}%f1PqcAhSmO9(aHZ`UfTwq72j}<~wzV#PW-~q;!RCqN&p&p-?uf=dh0>&@gk3IReK3vU(RCXI9j3wt1Dyauh;cbX6t_**(l+46jOTudXD$(4LoLh?y5Rh__G+3&z@9|oERnWB(PZj}DN;n&ECt_#1&Q%`RA334xeGSpFss?j?V>f1@R<*D1Oz7>tPw<Gk6AjX;e(5Z%gG)SXD8TC#F9HAe%ui;<L^mk_SngO=is<k0x6ei<WHPG;52q&jPM2!ySoh>2o1PM5g1s%+M$1zWMXZ0h-v7T%Y(|<;!^_l<Y2qT=Zk?2y!fK6%(D16%F-02Usb0#;dZq}No-{b>^s(9Jq=z=qYqEF+B%Zn5PVw>BN1gCP$GoY5%dGh5Mz2A_KIkM$L!-<JMldfF4W6~K)+gdfD0FoRdn!90uK$q6?{><kso@t_3Lw<W^wo%3zI-*BhO_HhO)tIErHqXwz2Cl8M|}d)KxCC*7@EAll>01a6FVr7gekIhDS3_a&3M0DD3Uty$@T56Gu_{U?aI+Zao>^E%JByQvVq>mp=w@)5t5ml4K6!Iw)Ua>)s<{3B3$VvOoj<x|HXb(8I34^_unIl|P43P~GDL)bIoXZ2fuQf;nP+kIJkAoKK_J_>n9YrTewwArX3U-3Bj5?7P6!r8>*^;%hQ8+Bw8tHYbOu<QTCvYhC63T<KbLDfidBn~Ep}j<OL;SS1ixDGHXDWt;uOfRXY+t5!Vg`H36Ao@iG#!ZJ0cmrSF3j{d4`9fg2hKtXAX3`M#PP#}xD<-xsZ(6e$UlO#dc)`F0&imfe>vd&z<Wu+6u(l5#9l9qPRXUw2P=O(j|yM;216fo~5DY@oyMm1Avlj$ig>?&tdVGi|$<c=m+QhaE15a~mM+oujlk19-!Jf}H)%e=kv%My2HnLw27a(OU24N4b!Qkk^sC1^w_6loE*$wL}4)$84dBZ}MHN};O7Ue*br7=tGh>oHF>dt#4DLfMnmq_(Yo|JByR%iXPNiy8QA{vWyh`UUK<U@}x*qv039)@xfoymt<V$HU8^^TW}};pq>+v;zH6=!}C1!!vqUbh~^scSwKNqbyg~wV{yYN@S+Y0_>e(Oqw=<B0!^c4x$@}G6?sWMSpw0!~b8U8JI)LxEAzQ-q-NUXLFJF=3uI#G8asrGY@@}`Hsg&+0D`}dLNNx=>XfIb!2v1ZS3D0-+MMC=+V(N_nbVyC#GpBDSy>1-ABrRD=?Wf4`jXQ)mQ@d(J^<t=spZ0*DL$Ji6Wds+1V786PTDq9^bHInMAl`wjV;00I$q{kXX=Rq51&}zZuRs=DJpUQ3|9q+LrXKnQYD|^8?Sx{3<uO6W9an{?=A5D)T4^oPt%g4O$N>i{ymrb}WDpQ3SRymDARGc7VHmo(?c<+Ey%@Vv0?Q2SHau6I-UxgxG<i`-WykJ5;8lD7uyA|B3u+>swsjYMnrew8Q&b(&Pv4T6H#XfvG#v+>IQ(62Z|lT$;kOWW#P#9?UoFQY;hR*~L_Ie}Urt>>t@1d|@^8QYV{tJOU%*CKj=qhHm*}^Dan-#4;gnJ@S{$H6GY5+CE>|cDHD|t@_^}l04RMTJ&#MTCLy~E$AkDtQB@E9c$4`ClH0y+AGG^;y<q{?xF~dsIc|mh^_;TL-i}mEa8Ka9l0wJD4Ug_`wbXW-22^j+u+n!Lz5@eN$9AM-wPF0i{TxE_F})iI6ZlGaPhHdujn+9d|!|KflEgHiazM1E$=gYpnQFGAWn~*adOwxY2WjT)*wI*MUU&CJwGjh!WRcVa`1Y*TGK-?LHw~e?-1?1{7G}Cb4r9PdWgJ8Q*%Aqi7ZtF9?%b#<f_LvW#mG#gJg8A`#}EHf))Xvq$-E+m;)j@SV44A7a()}E5Q+>|0oMR*xM!JEDe>&U=YUZl%uWE2`tW+v~v_I|0}}F)#F6YrSM$B$2*_jtD0JlIFNsVFyQ_Ttf{CxNd%>UIB5BR{5+&sALLc^5VowlZRMdmILua)>m>vGR)h1^5YS)ZVKv0`^&WZK^E|s$pwQ?^$>_boVWLPct-M_9%dL*Gy8g~qr(6v9DxJz~#iRTSnpF9)&v&<;G$9ZqLhhHuGFVYa?VcowEt=(VR7s~R@$|ag&{@1L`ifw-SZLn0!@#=|FLt*?T~<1t4$ApGnpl>W^<?1AQfF_kaoALLlX1br2t)bZeq&HkQ)6oU2%$L1I0oxgO2`F$0SQ+{B#QAget;!BFeSGp<usWE3YHPHX?cBhdB(++JNiO^$%j-SgYBd!4{;ck$E9h%uWXmO-Xeo6Z*Q4RJNdSp{qq$YD%!8=j+z75&_a>j@~NJxb$e@ADJH{21F2gkrNg?0RU-F?SH`WOGVeD4DB(Z<=|5|G!gv}*33tTE#!<J|z{^ntYJi+zX8+H>w^hvam)LI$W4M1Mnsk>t*9yQcrcwI_tMS#6(GRA4d^<8?@h!USY!dTi%5uj&p(8<cc6G<T=_sh2r17kUCf9H<rOr}=n@?FcMQHjThvz?np9)(H`t}q;V7QSoyLb8fOZFX`WT1M|*d24Md97_z`ZDzpMA@=!(lF+;q%DDcB@C~sj7H;HHY>;3S)mJF=&C>*;}BedK{=ol9SL67PBJdkU|7Mf0_HA(Try0}!mG3urNisY$$Ylv6aZk%;^^A*6C|3qbhIYpbJwU`DziDA^H8s7uFVYNic-foqDgxRHdYKJI5+0#W0*%0yeV2V8`isZ;TOtH8&v1|GUm11bjI-01Q~ek{SSI5d!KUFTYxGVes>Mar0lj<#G!279CfP3f<@@=5|c8E?&5G9bZr!)w=k8Rx9j|f$L3(j*w*FkTmON3Z{Zs}eBG`Ov{?cW&ZWVQQl`1ej>2IpW>g7y#qM0Uq7Yi65v9N-8>$+xzkwYm*NSKIYsD%Q4iT83SZD|Kuv>S%azN$WU#`%byA}Pc2FErvq)dUeJcciBhLG6!8nK`HV3qWkN({Qm+G@y#sM>X6g%uA*nL&Lou4e_7$e6;U(2$y9aFKmTIC~VD^NHP0dCbduD!3=}kA+G_XE_5+GUDL%B*517^cej2jZBf*llOHn#71wvkQXm>^Pqpix?Ks_%4cBp*kv(#3`P)7=pZ-FLYS7HU`1qvUhx<&@aTQBET2$GqIn69o5_G^N=<p*U`h6O&4CgV^BrJ$VjjbxYEHR@;rUX1YlYU1$~H|l-S#?DHs$f4Lz>i6qkfpWsX}pq^H1TYu#)%m^Pm2M9p*ME<^(*O%?^&<!W2LelRlv9I1<XSg4di~9KF4~s8&EHJtJgHGE5j{`D4<!m+>U8o=qc~UW_Hy2`08R9l+a3+YDSp;S!dGF%Kv=jtXjF|CQz2f}0b(P9^n6k>_*xT+}(k=X>ZCi>1Lzu@qWVA2+OK_<%-kn#i(bB=tNBIhH2)A*?6QE|VCej2AjkM+v1-V(vxbTdWv24sZrY;xVqNS|KcZ6AD?F%|<Y9GmKmx0LtYJGU}BcMJ<IWNT%{`S#7~i+@JsaU(XJLpa1;dm<$jBd18e=WIG#&{6XGSlX*T-fy#I>y@c=po4K1z@vmE4pF_(jT?*g52_s~49H2G?v9g~+`@kPjVkqA6ldBLfYT)X9&tubt2fG&s-vF;S0d~3xiTqLM7Bm6%lls8wTv!@O6SK`-KV~zTOM>Q`WH$tjEJ)|PXpcqnMi^)`XtnjTOy1FB?y)bXESZLG-MHamF{!xurfI(Kfw(YPE`>~<$HIRepWs^E0w`w77*L2Ch+DFBS-BF6M|3|z%IA#EQ42=LY@c$UVdX6|h-!>=5zE2QJT+!diW4!=w2F~fo|0)cqBIOcjHd>c0YpzI0Nd*0O*KMOnwpiyNVD%#wkGo(I6D|vqli>Kf0(1jub%40oLqhfV_i#6b}3W_+zndA{#FSn^3)km!BmTRs0RFmUh(*YtUb_krq%3@$_cfWuGUn}a8-$^)|*$V4O-2G21=R`<qOtRezhrGmEW$HKwSnehg64A;#G1*-IS`tE$A5!J;P()_b3a5$k6VXYc&#sxmJ`c)eC<*s~W4-Ju4d*0qdr=R!7#6lt^FIa!DIw6-T{k<xyi|2>LUaNQH@!8bd#o8U^eEhE@xSX(@HZ;bxP_0W+x}#qN)mOqo3BCbtWogb^K^7O@)(Q^&-WbmJ_>j6m_~pR5Wanz91((F~bY+OaaNeBDeMUB#$as2|xaK?kmWoeY=d>6LRdUXVQ})*CUfyz&FVPcX@S?^F1wjiYA7H6d<!Mon$a>XCC}k}z26K#201IV3m+fba<tLYG@2g*+y$(4$kSjQ|ynTk_z_mRSj80U_^vOINkAZ+qk94r{G!OCFcYH{zK%47Ze4c;Acy<XfwK-7##NKt;-LTO%WhuA0Nf?M+j@_rpa~%D1keslBWxGl>SfBITL#S-UwuoCLMn?0WqqbL=YsVP-3(;(cDexiB!mmJ-<pvgj;!@AsIVH%Z9RAJvlLmnQ|olmYG<#imUO!Wx8PcPXCG5w<9>tLDKsoos6mi!G>la;cS^*7I`p9As^Ma)&A&Tr`xOepZHZE%~?@MzeM*D^p50i#JNzIL@ZMNyc*lM75cUht=<uV|?>?d1ADRO1b40-%pf6N>i$|QD>5J$O|elRTdS6%vjt5FCoIPsK^bitJI?WzM_zNNj91I54`}l3m_pDrjc^1n{E_Kp+2aJZP>>HK*qqbYE}AOaEd@=-GpLZ0pBy4BzSZQGbTE~h&>d{b4u>AMK?p8Y`GUhPceUx!B({#wmzWerY>|rP2QtW3TfCL*8hpy2Wl4$)CZRnMo?0IrQuONDU6>)K5n-wsuv%2s2aX4ivIAy@^w}QbYyXAvHX=om=RU4%*F*8cLiF#i{9!-RM<mdSd=>`xXDS1xicsqcwLx}MH`cHH<s2_uVPOqMwiTdtEh6iH2|j7Zs+BwxO3n<b?0H^VolMNaJMG;y$Hhb5<|!;9(rDu9O>me@?~CBRC%n{2-Vyln7|q+lNK{H21A*^J}azTaKZE7h0D|up-x^mg7YzyzZg<%O1#QX^(F?Z7FAaHxNU%2wPy|NB-Bw26*41mju$^;4mY6Un0y2Fn3JXAJ|yB6=tpGUr%!5zuDk(cNPj3wl;E?Pep@ybqq)EKTFpAfY<_<TF;s!!RMb0#vqGiy5979KAm^nM3v5{$$D3I!+I7MvQrD}Bn!K6H&Q@M7tQ5_345Q}*OC+0jwps$}M&1DSc9W(40Oh<cT@lQ~&4QHD4RK`yOPKmgyatm~@FgxlY3!?4;m|haWwUu=%hCspGhkE<Y=oEs&c0*Tr_eIpl(Rzq5I?yKSj2sSO%;hNsa4DT{o2%$*~U7(P_oJ8T17UrSe8)jOWZc9^Q_UW;t7*&q|lNqBs#-dVkR}4NW==5jGo&?6v5B!qK+uUM^xf{1si1WYS)6~aUiX{v2B=#;7pNsUr~hGR;$&m)y+o*7Hr`5qtPh*_FDqi5a`k~a62n5tD#F{%z#v<zyzmyVM`rMHN{kyEy2x&cme-4N>-62-y~5&jOY&f>cv)iHBecJeh=yaP%LxwRc@9tDX(#Av>bY3HMZ7#4TC^Y?=lnC!6OAAO1V0UPWWM3-^mifnQg;M5mnIR1x0{Zz{aCTycH<MQ=6nHi&J!#mXX^OUK7(R>%*(_t|<fgVrl3N>-R;OL!r^=LJ$HD_MK)JgT?B{N!nW;Y@<*%Oj8bjwROENhjcX3UJ;<{zX;n%*mT{O(qS`0(m-b?H%~=8UnO$A8sz_i(nXcZS0i_Eh=i<foQPRo$Ej_i_S%8zO0CQq$P_}`gws+!#qrxZDBc(q9_U!Zs@Gk!mMguHVdMEgS|IGgmS)TWfvTkORC6e?Ivqej=W2Sm;qHlsu(8qyg@eovbyq2OBcTG&Tq-XGF&uL0nQTpGw?)(Z=$6jk2)dzB0*Iy-?KQ?S9O~vrL3)um{-g!+j=l(El&i4K3}B>@<{At$c!JJbf)_+lOj<SMaQ|Kv+Y;}Dv19AVQ9M}f4of}!gZEh$#H45dsyIpvEE%+@m7joHkY3l$jG7HHv#UCs&C^ABoQ4S++7%q-wfVV|ZdPJ?nSYHavY-HD38!rvQva)BAlD>2{@QpsRW;aB4HuMeHo2um42jrKN+BrPHNy0Zd6f8+mn2et)<K7)jq*E0pLLptzhgybdGfvtdY~WWDMLK1F){f}tWmY($|U$zN4E05iDm&cZk{4fI?lq7F24oFtKP#(gCkTo5Wlk}8?V?y3q}+AzamDOnvqRmi29@}P^C7PzX@el;60IYk|lH>N%^x<I*i^7HxPLNYcdd*wGuNp(XE=UBJxXTbMU?6+K*8I5d3V<VSn=<2I9A<ihC|(dZA;rmtWR_={)%e&tx1&{(9B2ZeKrYp;W1g9L{R3H2AB4UJew)?V=KY>SmQV09uWTAXHClx?PE&t`Ml|TUtUF@oa!=LP&i8L2E;IS({bs0J^Z7>z!IB@xoZboJ(Q7P)TrQMGFh`=9Z&{Nx{&soA)zp!+L4ZdO)d<O4jv(nYR8xE`GqH?>-zkZ$2CyA36u8Cl{y3!(RH3TB|^)99vH(GXCrw{feQ`LHP41QNXL&cx0yHgqRGH?&&uRncItBH)JI<Loc1XpPC06xp;V#+n>-g{}H@~KC;A7?IDxDDY>v7;iwr!4XHu(V7QrZhKqbuGZpl~U@%}8xZB_cXWRmyg?1EBhjJh|aF1D_W0Wh9@JMQVJoC_ov-4bUp@!-ZD~V2Ghk{9Aq2;nduyt%&Ly^{+W_MBOK|8XoUEqQ{^?elI(jjhbe{Qsm$FQBE4LJ#1s;yTLc5pu2zZ^Ozr}D-s6x=B3i8ILov%*x~TDoOEKgn$Y4JchiWzM>jG%*M4#`hwhFX!=wxL%Taz|#YDz@xKaV_Pt()V3Fwho>Jd&8?}nfHvrc^txrTQnac%6~<PhY=U=+4f+kJP)Rn>z8UiQ>It1mLOIR~iFyKUs?}E4AD|6Ubc#Tn-q-8}>356u(7CoPgn~8n@W*t<PPUda#`4vHJ`#qg>~?FdLA;0tQJ}Sr9@z3T#76K$Nc9j;wbSz7Q|(>SCtF122SPeAD}c|UP*`_TlC@ZbQtP>axxLbAg+9gvN>Oqu)GNiT@Yj9S6iSmGu4Pmjm5WBbqI|81gq6MEK>5AhvdE#Q>FUi1sYmI{quFA1thh(-5uj9K_4*BDP2{N|<9>=c5=im-v~IyBmX}ZG3}12^W;}&a1LNaW(mvY9115xOi4bb>pgixcZMsWdg-TMi464}tCVuEAQ|?jRem%%SfYzMw1lR#B9`S?DLW=@@Xr!kaLoA(Pw_i&m5SXUWhdv()!fbXUUG>JeVqBS$SgNBvtVn7K#VH$oG`BZ0ILwyA3Ui~$N-4MSY6L@5)3tC+vkgThSy)H0>UdgOgL)_Yp>8_h!wU@-HDj<Tz)-jHD|6`>%;j_aAX@&k4d@DttQejCr+SeN4R%hqAr(jLcm_>5?RS2XQ5l#l&C%*|icp&<RU2`<ikwZdn2NrX8lT>#c6lv{UmzoARS_;F!agcgep;PRpi)eSmPeLqK-VGRy&Gewr;&<&xP*?@X-MhCGsK>nT116yJ=R2<xBExOAI^st=uw(#ZLJ@sbYVgL&W(HAe`sF;wT{*<!|OSm!{H@>93H}lHy_?1SaIXnl#AOrki22ykHs||b)uG<rGDkYiW7@32vd>2yhe~}S(a(VXQ=D^NIEo>-%24A#(qVmbD$(|K%wy~H%;TND2(&2TeWQkeP*zzQ}Od7xN*5Lh`wR0nk#Z;iJxm@BKZvlzg{QR%K+!WyXh{0wU(W-DuaypsW?V5rI6LG$@uEbfsvO6mbOfJGwVgS8x-|PRJj$z*rZ9q#K`Efpq%ArllpO-QM!i$<Bb>VP_b`@nXV(L?&v_bNfR5)@h_K@g3110Ty$}vyJUodrvs9T_^AAZdpVl<nvq|-5}?t}=QBiOVYgRrpJ@0|g8Y_#*?Wxxl9Q;oL_@ivpF)-5ZigaPzD{OA8CTDzP*&a)_dy7%Y_1)urwn7j$tZGTj}9VYyYaP*80V2Wy;(N*bkEU<rh{lsRVOlvo3C?BkMsKsiV=Gn(erEAzxaepQrGBf8xFdPldb$ji;)BFiwb;DU}??QHjwnoT=1%_HJnFlFxC6}5rH$;4@Kk={2BpZt%FYdjT2c(eydCiANSC9^kVnEneIa3^V|GU*wy1vmW)C2(j`Zs(lG7Q1K>cIiQ#7m+WG4qt`hGLkdI{dEx>_~zfM3Y)()vu$HBIaBbBN+oEE>pH3XvC0$=Uc{{mj{wy^', 'receptor_prep_core': 'c-rlKTXWk+(&)Q>1r~WQ8I!OiCw5i|Qy(ocvC6WjrQ~F@`cy2C1SPCVf&oBFvR427^kwcCkd&Q0bskP?*8=C#Gt<-4)6?D46NceomM6h7T_&@1kp$B$58~A%Et5$wTFpKNc`{CxC8RF%WEtminPv+r)m@d@Q8xY<{FW}_XlLi*#sHHp%4C5><Js&!D7a=)1m#VhBtf=J7*KJrvlj(p_(<|kkn$-B&W_$-Q`1>`eN(<D;ze4f1r`2rXFr0htOTgki+C{!Ztf>}cAYHRi=@2G@{a(!Oy{CTaGRDl2yy@HAA=WXgZ|mO?vFb!qaaVO(}^A$l=#O*fPI`NWs+O9-zUk(Obl<HO;)ocSQRjmYykr+A@S_Kyn(_+3EheFNia)Cd7R%zvR&#XK?&j<G4m<=m`rx!B1rC_F~ATYU_OUZMKH~?IRTBwj0}SP;xGfyL9+Oi=GkHnhz*Jii={bMUCyA>J4HFkR)DZ_lH`yaFM?45BP?T>jtR6H0M6TL#5BdhEW0kEoiGe{cBtjyaJnj2c`_UZ>3o^xCG>rfl{{5DJ0fjde3G9xad89Vl|T6pBt(G6coLVf%=vebE#&t+E^p*_R>-gAEG~hp=JI!*$gkpNRi-obYc&EI7$=3QS=_5nB(HdqF0NHVI#+PYJRT>bc>IwEJI-daWK2Voqdm-4K(~1-m?YD9H7h6Sxa7h(mhmhuaONdy3e0ZltX42hli5U7NU(8PTK;ZPmp*5Ugv%`f8GtZZ><n?kRB*q9aj2fbI*La#sD2C`<gfmc7g#GePySpbi*d5Ev-4YTaDLoB4LU)%7wtwb!=1C^v);+^X>WMiec!|M-%irA;0><rfxQ6EXoV*^ki+>!_w=YcI2v}lP~~AKfd9hoNjGf4pTV#6=lqoaoZ+9tKhE*buP3Mc=L7%w1OL1|ro7{mUf5ztCq2qP;Y#m&7x?GwZIAv8`uOL(H^4s^Z~4!FTDkaxe*M-x5s<!tIh)U6`6YMDSvm%qHW<W<al9lXE?`|F?}<xV7}<Edf+a8oOa`lEQ3B1(17seN80Yz09@2aM^G_bjTOP|1|LO6cGad({;*b(g-{UwRcXr-%58u7%1LhC=1H}A8NW~5bi-#eU_$GLhXYm9WB+%0sCj;5;J+agmlEJo%@_v?RZZ%D3Nf8Af79SVc?E(n}1_$#7&~D>=0Rt{z?T=$%Q^9yult4_yILi?c&<+e3R^WXwORj;l!dgs#kHwP-Ft<F3cHW)#e?J{|KV0;W`iJj^7k`}f&J7CSp5w^rAHoF<>XfohX+Hb(-KTHD4}G0?<?R1LP-gV+3I6*gr+;Z~kBK6#>0hF=_Y3-$TKN}!|LasjI*c_!e@W<Hnu5a>{Yyl4n9;vPRHrHZOKqIf_xZ7e^#*_b&NKIoVA#9S>u8VpJ+NEAXAayY<&7Z@_M-h@4s0R?(gRYuy-60pXs5t`5!WMN+66!w!N!z8j@$%cB8zmg!rcV;&x+>qXob`ZL<{wh{V!LeSz6oxF)V>!#n(yjDW0to1P9E%fF1?u1UJ|z??D9+crc!2IOEv@_)&=@FvXpn2ZH-?4%=!;1DON!0#M@&pyF;qU5$1Q`>?Qjrx(LP_vrXo&-&Z&05I`#59f$JfB25b06$;9A_|~SEYPRVSFhAm<InG3Glk&yE>Eod1pFTWBKP))R`7H8wWxc}Kfh-(q3?a3Z3X94eZsu+C)fR#&H=K*y8F9CT=@C&?>Nctd%bu4A*@eeawjMK-@B)WxJaQSuu)>@f*}$w>E(HrHwLgj0Q;sN%>!;K47*4nc{`@f1bMS9E5+#y_SA^B*(%_}7#KI~M3WlegE%dK4v4sLs(<}(3={<XzJR$Lb7cY~8u%ZzA2nbf`J5~|7x^k_iiQVFd+(BaZeV-^^1%TJFFE}L(kzlc_3w0?O%f{`St%z_%Kren1;L`cr(dvb2Cz*fvqq83rp=)JGnV9*@V{a;ou+qyWXz5TcmxH~WuvLe0FAD4z*_h~g{Xr8aJ^^4XO9P*#=U%eU~on%cJ48(>)9Mv!Z4lGbk5gsrNv6WA8niqG#@3)WC06we1E){X57YdGTLAMnGc1qccAv~O8|8RNI6BJ084U5H<yzTKP7nqC1_f3g9nif7CZ=~NLHZ%a*Klb<YQWHQ?MAP%lmB#UMKT;x=q0)3A=7dlBpU(ARA6$k!AUPXBN*#llTB-zerSoNdg&ioHWA!rClNjn@tmLatGYD#O1j?XkABu5<=>F2(nZpKe%#&3%fXg142>Cxvc2|lxWtGF-o}inubSNHmeXZCQ^~ep*lK@P=-Zhl#EkCS=`a4kFb$(F+CRCXu4Rg%3+>m<pB$?m<R_EPwMjKAehcF5W+ga>*za51MG|wLV}`<?)x_&`U!pmf?5Fwp#vHb<RUMltWUFaIYe16Nf$#ri&cwcKp3|<oMctjFY&D4ypKt;9MYyZPbMiIO{?{n`D&32)0}xV(7;ga+@7+;4Td*(dd!9~h+LjB$lL)l!y*~uetUqMGUWe#cXvlk?gFSKo*~EAGaMR75A{?}r;?FsBu1+x5KE(3;i~Br%k!cGIh1jXo9Wx`;5~`CXWhYhFMQPSX##Nb34TM_gEzow_+e2%BXA~xO-Y_`sRMzS#s{ZQf6E_3t0UM8*qVc%m>L9~-ZUX$@4IMsLl45`TM)X65|6jnuoh5=2g!aB>=F@!I92d(fMvG}=;pSZiNJ<mZfy1pc6eY{Ac~3Vsuw`evm}P^m%D)gX|^nuq%nyNt0}#LI=EE0i#o9hOlS!sLlFZe7DzCgeM%b5mIcIEaRwA4bvrQ2n~psvcDA0>&U9*LsioS{yho)uU@B|Zs8h*v2Pzk}QAedYWvh$as8r2#aZ$Vc4Jh@69B5SrVL+*7I<*~&?bMR8uI6XoM{mwo!0~e-{$X3tV>lgZezZ$DqBH(Hp>y-+Y9?u>k~sB*&5u`x)NUD^ckA8LJNkcIbW!uQarA3PSY{x$3}Hn1b)vU4U}>BS=W*CqL70bXs3OANwh%ylm$4X+dBvytA)V@<hOV2q5L<3#yThze4u^%CnoIyyOtPsb7q%l5VUh_E<`A{J4mv=D6UZorpMhu`Ae)XPFe}H%?YaP-=LOq<r8!CNs3DW84vZ5FrR(zuiCD7))uTG$?*8*ZP{Qdtxukh&1?HbCAC=I7nR}#3g;wYikg&)W%WM|sLrEeIGE_kXb_3`6x`N0t(i{pR2TDP_A7*#=T<l3}<QhZ<fPzQ(Awrb(dC)|92x=QxLUk~lpw@Wy#Ez(8+(1$~!6_`0IZD8ZwGP&T<8@FYcf!m=SySvp<*9i(oskJ)NSQia?1FY-*viXQp?}XoZiuffQi_)#hG}VyD8^{KxQX|_f2G9M&}_?_$JK;zXp(~1?7e)G^EMHiEqK~wHizwT@&yc(_dr&riq-GHHgY$0@c-3i1N|Du@J~8MjxOlmTt-{M^TPQrtfMDQ-emNrm)<y|2Em-Uev8wP<v#V~eU3qV#cn56-A}7UcCX<qyRNKFEeH-LKwwnSDOAzmJf&qvsq+<L%pt=t*<lszjy`&@4o_~RY$r4sAsP%f^1YoMJf5z~F)W$ehOIplCmd<wim-&Vaz#+38Kp&rLIfNvngSAY$RXM?8qAsT*kZ$-q##lt-3c>e#FfOcmXz>VHOiLBq7mk!uo=V!6kbebiE&QOa*#fO((vdDhlIQ#H9TB0LWN3WZ+HK@;M)NIG+V(a44d|WkoyAXYaC^R;5DtmbN)?o$6sooxJuITkj^KtlJ81mxUB#a2=_E{)a(gmA&v`;af>pVe*}VT@Q;E-r&f^M!9)+Uk3y1S#(}0n5bXhBR2>mCMEQtXjPNUX9)wXjUxrSV$mkya0}UYA!20Tht8&`@A#4SU<Q4_94yxC<dR8c%n}XD$w&mc5!h9i>dJQG6*)v_r1Brprsxdh-p$MJY9U8@aWzV?f)2#djWbp}|;wx>qYDm#*VC9n(Cwf?nVP7g0M@W-`X`j{^PT>{9Wb+JQ{*q7Mw(d|Lx5b?D@=T|QLYkKjszggeyTbq@bP-rg8kZI=Zq-EaA_&i^_eI$9S4TIC^sebIc_k1GB7AMHe2_-zBD|7IgE*9dEJV<iRQxeCT$K#=z*N?7o={lj2CLIEh-p#0L`{2xidzek^Tmu#;WQz6FHsNhHEA>_c1e?JDcTQIH)(>P7hKQaD?nDLf+P2Y==LTZ-x!oBwQg9-?KyQ28fg#$sfaOwP1Um6h_Lw$RB1E3nm*HBA;Cc3bptP`sI8cq>axJWnO8e((HV~}?~F#2A=3p<$wZk*Kwh6_ysUh76U>FK+F4qK=4{FxYpNTe$i}6DT2ArP_<XtR<h|Stn}#06+P59(7AnH|$06JOP+h^c`e=DCq5E<vYa1Xn0F26JmmRxMr^1C58Y<(guR{4|1<O+8sX+N=1<PXOsX+N=1<P{esX+O%LUYGZFC)#krVoR?U@jXuB>xDdDq9*vZb6bjNW99^h3S=LIATdfui36G>8)**jq{$F{nCEm+820g1p-l6OOtBDSOXTCL}>&6a?)GoxO~NUszou2F05ia!J?Q&4OTIpR#D8N0Xfz7P9a9wsaO>c96fsl|I=^)n*bgsm7m3f_;?J`BCx=1M!pnWpdrEJ1Q!H`9WO{X*T{tN%(Mp(>%*-;h|^FG7@jC;m;#j0AaW|Ya<YIls6On(<5?0fK$160geZ&S#$hsYxnr)Yx8oF)q7pz;dY3Y@WLuU)48dNTDlK`Bq*EIRR;*Z1lp#$BecC!x8H&_A(n$kx4@6G;S5ZF!tT5xQYl%h30iu>MErzA8DGcIbj-gQPyj$Et<@)A?3{by7mn{hvNS0KSu+V34ZVM(^!emMZ0yMr!n9}G5*hMc>JjH(d?Tc@5xrZhZDI*PudQgZ;xMo~q;6|#PjoE5~^b+S~L2hnB9fjI^*zgx9R|a7o-_kb5K6&^#$;Ka1)k7BTA!!7{M`mL<RrP`+QVcFfjlk<!Hfo5W+Ux<5Lljmc!Jx7xU91v=glO(2@))Hg8562Y_p(yUMB3(-7=R|2iM0;&@EmDMbRu5d<60@BS$2z7Jw%B!8;q@7NYM;BqO8k<_TJT|9ui=Q2ow-yQ)V|PDFS|4;E5AtF1edcZitp(ribju{TT)*Q?&AslA4>k!d{PpaZ7YreAk1nR#1?ox<R#D!N)}Ucc3PK-8dTf)szF%Cs*JYZ2f8AvDb5G70qJq<-w~fX>*r0cnOHqWONMQ0?yw4!JY<1*i9Bxu^If_3HDxzRjQ7vLa#f7kvZ^PS1-|wPS!F38Rt4w|8jrtV1K{92mAZ72c{@U?okrJ{=xp5A?&~M03eqtS^w3+{_8dMU;8_N7#0xrULWl5R_3D$Y1e@yrwrD%G5{hOU=0VkdMgtqCs-uZ_Ul&%uYcIw_Uj+iM2b};O;_$#rr>wb5mVW`pgo7OfP}f#aCdM2<#*q|di}%SLrskaNLt7s)c_Zu6$@}JvKLL((d+-E5r5rK1?MMyQ$_0&3g7YWMgM&uOuTeCLtWw+rP(r@-OqvhkpdkVNpRRjp)j5;Z(=wZ=OYk0b6|`~F2Ir7$vB>k)73l*E^f2-EWsT~j;LTREUsj{?Ok*)?B-b^IT7GS_u`I+MEE$Ht>z$v#G?$jxH+RRgEV5##4^?~=W_SToaMXw&&~`h{YSmQ^r~K8$BrXJ5-)cTUjA^^Y*}eP9DMi6N&D{A!S~-?S(?0tmg-u;G1`Dle^|dNp&*wAkeAeIEgHg3EpJO`C6Ctyg3R@<?}L*lIf9+6?P_EK(cHC#&i0qm^lDrvX+V0@@`;cI$)Bri=#!kdN)_;63=AO2;IeQwDQjC6rL@l%5IZ^T6WzI<UX}e;LqN_$mF*e^;-16K<apko7P_)IHC+uJq3#m0ucCM|X}HVWF3;$qf>1+y28Tn#+sf8gR%X-cX}X5hJK~5l`wEP9Q9%iH#~6P^j?grXACVgP4hkzXY1k3U9fd7QVLh>zVNvrIj`Yy9E|q{#TdYP%Gz6YunYJH;-1T;E`n`1YH0tftcK+#@7&HnwJ~AB}N7m-dZd14)c-*6SUOPfk<6ow1Q1t?mWp$RbgIgTIwJ*6GK#GqZE+P&9@q|qyRig;&6FQ-=gTN+KEN5xSwUsa_ZZUFiD*g*}<g9us=;Td~sI9dwsI49Ic&o<V3e0b1H)I2@x_$6F+J%DHzM?4<19VlhSfyluAVL>Pw21v#`>2tSJq_kSs(8KSw1xX96h5Ra4*{oel12TB9w1O)o<zZWuEWEFQf*%IG&ouiybIsY0(JtBIRJN-Ov|9mWS5>5!gD}6e_R9jiyPR^;eYeh_=X)vCkfzS#R?wU%}GHAmD}xj1}B8!C?;15aTsRAljff;mQ51k1j(l)S0fjfg%<Y;1K7z(B6vr6JmJw<lf_q1-HwnSPO%@b-QuZuAulQ+#$mOlc=E#gtiUgE#<KvnQ+34*FyBAwogj(@tlsI-`=b*}Sh278X7jW}mtb{+HBUyXbXMX7knj{Q1gO>GdIcgDl%+1UsS`Z%;5J*$CP9WW)on_bndT$h0~w=K5+;LYITGOdkbRrXW^MLT6Fncz@Mbd1Z4pnCA4P|xYL)a`AlS`F@em}?^+G^Xw|b{(UX<J---*u0H%JvsA1jz#?f{h-F0&$)3ZhH$T%$_#)l%DdvRKXW;xq3s1<A;jEu6Mn8brv99L~G*$zR_D&uFMDk?ueMw%f9$SFw#B$l4tU&ERjYSb!o86m;SGOS+{%d<}l;xcx+-R@p%8J)28Pacv&oHGI8n`McEgxPw=&gH=pnQaeW;K(LJk4@M^*&826MX`^UHL0Ewm4(v<n=AE*f)z)~0JRX<0{1#$0|A<!tl5t5yOiPqj8qu+*4S)-qi+_F45{T?d8ZA69I&1`MXN9v8vXy$~REq%$ImHk*Lge>D?stbYT~<G;H0_mfUGMcx%f+>S@;dv;8mxp8{H%wzQ^gNjPwPf>@I}NWXzL~}OhS?@Su_v;FJt0*A$T^?n3urLnNl)`gDOH`?2CJ(2KjkuLKN%NpT^X|oQp=L7>X=u*VTSkP~xtxMP?o0(GFuC%A^$Z^pn||!&fas^&F9`eq2_MLv^PfMkwt6P_j_>aOJ_O_DI3){MXJEk81v8&t%;-0;*Oe<8cTFgX=T;ca|<1LW-{(mavPm4TBMHvrfWeLx@B@cN)*M3>q^X7pP2WR0Y!JK@bMdMNiF(6nrL%C!`D4r@U!6=)La_-UWaEelIv1^v=42-cj)8kKn<Ix$qb~h^P#YhQZ#deBS>sIP3)vhWy8OS#^1<t?uCBxO)-|dgsSSAA0BT@xK2Xw5=EB^PurmL|aqKy1G*!2vg5$by_H}&iW_EhcM=6=NE(Hvu6mUdK6)J&))TVXV2uQu7u2WhBK0r#GS~^2c<j;Q6l}hNQ}l?S0M7|_Y}*ZjA4#1dV?2-(96RM0ZlR#5^7^5h8i3bZ2^%nr_!BC#lNvuJ}ENc!_uoMETFH*j<`{{EQh)kc~Qdj^Ar{=$7@@ulKv`<PYp9lJ=TJzNdZ;Qo{CbacA(NQLzv2iF4)w{*xeKRbESixGi;?(F8V6Ur>Y9*sogd;$S8WOVffapdE01i-qubtb*ARkk|%RI=u(IhGX|2e#SvZG1cu)YCTi)wpL|NQRWTIz{A;h0-^Aj6PrBf;)*YaYV|)^&O88GRH?1Rd+KBA2O7{&MA*%`~6%HCsISL}>j^5qI3D?SN2Y60si;C;f=YjFWwd?e`!=u^Q1?4dT4Xhbs{rKD*5Gh4Y)vei3UctumzYDSV2oOzlJyxE>OxTXBXhN{;RV**IxRx^MuHVgCE}t+>AI41_X(*_AgR=91aXIZu8w`|hf|+gmC~P=sY!E2FRBL~C|5>g*Y2UHP4D(@SXh-u}NGwZ=i8sgT9Q@T?y$+AqCjfV<8;@O%jJK{F+;X@&8NoUg3#C&IM%aP>o1T#-Ezz))^Ag_rP<@k;a~fiX6-ijLtZ74OR8?jxuzy)LGmPcJeIPkUhUuZGRA#gx)`3wRA-v8Y)rcIUM`;Y_@m)G!!TBkkq^m;cH|zjD5xZ5(eHa7942$$Lp3(NB-Qe568v*BA2Q<g<$kT~9NAaiubEGL|b#cqH8r-v0<(i>=QE>}2>h-lq((9X1w#sqfjrLwE*lh)S`sjue7|6}k+<pbF96VjaIfs<8f~;)D%$2rVG>Bt>PeW>8oVy764m&)1v%k=D(6k-ksdb>*rsc#vxg!^DHQ0lSI%9Ibu7oP}c~dD_k~FVa7$=<Y(!egG>g_pnr$qy}+@oLj;@3X?`V1WR@~Y_vE&Y{nl#-rdr=!+nLVe9zNz_spBCO%M8Rph1Q|#%d1<O0}Pww7$Rb~{hqh`%DL~GBj#_M}INzqkdoY2AtGQ-~uNkuJzS&N`N;}o6xnWAx^9HgNBB=R<o8W*zMB^bpmn&*}RW*h^MsxFaeu4EM~YVl_Y)9^1<@kWNiB|~!R25Be{9B#oE*X&fsXNMIho#260ocL4L<8!y^=VBBTDXOgatrQ~yF1kP-a%8+m!mEa4W*yWzxZ=GL)ibPQ^o>Ns^Iuu!wYp^#G@XXd!>X$WRTB%(R17`HIF1<f@KFQ{B8VFc@6@>88n<Ej+6ubvZ#{9EjKoDmuj^dHP*6PBgChy?@r5zdkL`A7mUjjyE12XEG#*qpqL<UhpxX>Bd-HI$AfI=<OVi*#>%tBg23cRWh=PzTuFD&_z>7cgvH{|<*h;<?dxw3EiW+VzJ*$B5Q?Qq`f7pBqJ)~f-bP`#xnJb9Zb!2H_6`@np#h3yR3Ng`kfamQ`?s=jYzMg6)Ml{V1b*KsVa(BIy&R8_e*Xq+0yAV9v_WJ+45NB)>yig;EgO;HX(TBbSa>dY#rHrwA$UB#ky{P_hbU#!<DJmLfeII(QP^9len_`RqjAHDqZU-*SofQt#NhuoPErI!)$!b|ACKLvSa-Ju`ueOq6;dq!)w23vFnZ5g70>?uc!A<SUdxAK2(fO8`94WjRgOqyhig)*eil|EQC-I+uUWAWYhs_anHi>TR(AVL1sn04;(7wv+8+mGh=v-*ss5_esy}LCx$osVfVsF_nzCDbS)v<y6)TzwHrm+pnY>0|Ri%;<~je~YDV)ARj2O$1)x@_=>xpTUsO=B-7nB({<KqY3o;nh0Gd?}Hx^!Q-60s8Y`)U1H#QMP2yOpq#S1fP#h2K5{xetr*Bt8Oc3R@E{RWh2I{sg4>g(Rsfkm)ND6Sba{ua`i6WLU^#L9JDVFUK$2dR`bISW{wU-^@AU9kFrzuys7&lHFRK7Ti<_oaOJUU3KpTSP(3(1Cvw=sHvaoyk}YkV?Vl0ZyFoW}?&=aES`xU}7g)I@!gjJ{1iiU*)Die8FB?@{r)YQZ#`4i_O$!z3o)6&Ye~S_^IyRBc5aTUijNRgf0-sBHm$!jKB8B#dZsw_I8nmTIZx|Vd8RI#-;pW*9n9tV~8%4v2g07Rqj>ko&AOmlZzDbHP<f|F4c~&9JG5sT3gslPK&K58DtS66Sw3zIOz&{c!#thHUMC_W<bf$WzynfjEfQ-ltSH><8I6IdP)=NMInyU}n?Ni3}eNp1tIsdiYKL1tgN0iMj$LleG7;IUL(~P=;#+*<0ZQ4WSIA!SNSapX4fs~xVID{c@^2SJSbEIriy~KnDt^?&bW=s^km!4E;B2VuCh}GGJxEFQ3!dnp&NFxG?>H20-CK&F!%$Ak+6z1__MaIfcX>#lMhp{cJ<I=M*@@Dv)0ZL2Kjm%ymU*k$v1>fS%M74o<*ztFhKxYGON^{(&`}J~_8`^4(r}`QVlxfefJMyJ!S@H_m(wF#4mA2BH;kq~5Nb|cHhy%Juc^c5}yCc^VM`@B9Q94e9f4T_kWBaGq>bRZR{Ti%N=6?mVDp&!Mtcylc8F|#!sN||qsLS4JxEp%M_gsfcs~~=Jr(wD1a0<SwYg&>dVFVLlo40QW+AWYe;E**3PHo+E6Xnaj=;ilz=e?vs?khwDMs%fUP0%kqawLm}7g*EsguPVO_-%<y`)dh$^0sni9N{EsRF7J$r*=b;ZCDYiyo&o(d$EJG5mMu!bsTi~TW6GTR?=qWm~3OyLNRBEPLtMw)PbdRx%S<(E3<Dpx|rQ?9ZqFrC4#HvV5=JnX44N-;GLbSYSm6vv^TxfTa82~sJC_uCKx9Mob)k~mmHifYn@F!(OE}~Etg2m%BXGRYRA}!wVlQ={HPd?ttVP<*4Tqo;5?yxz-8kJU-{KbsAjP@%}@ksuFi*It{S#NQNAM3ay6qequFf!MT^wN3z0Q`Ic_z!4)|}h6iv;oo#PW8B!Vsxx)v7dSBr5GKh0ZO{KYHzj5HgtRNWW@6oijt{G_G2Y3^l{SN1lTl2yyWsPspdb=VL63!QVj^HF-e%2x8MMKsu!=MIG;;kj)~`|NiZ{wV$RBv+_$y=D$mjr=NS&L)zz{7AL5tzvU4*V(^Hk%<(qG?+EI!lCkl6{J_EH}r^5Bs1+^>7{#MyX1IG9@Y1s*i1rNKdH7Hdctn;G^~s6dFgTz#4*Zi&)u#_7qEGpe=O=<QcwG*XZ@4zAb9)7(V+ip@AN$AzdydX=p6+Q8%4ERU)95t?)lr}(_goMTHQkHJX$Y$gZIa$-IJjI&p!wxdea^c>Rnnl973CPG1PTmb&zw|g@29@q1D6w=|%VOBEUA!gX3RM`)it>h7a-Me;!7Up{0VXTa}x;q6Yu=`26Dd==ih;N$<~2x);6kHJt!*e(XGuqEd8)yu!6p!A6Qxe7VxatEW17F)2Q0p+vb-R()EpY)3HZm4jVX219(+0XXe&I*YGGyv0<;30N01Q2>LJTU?fTL%$S=#(_Z(&^bKq4}U*CJ?j4snB29xuq#70trjZ4n;l!#GCs9xpY&)+p=OMCLq1UmBz?19K2R9-Fh}}eiaNLEYd<pX4d)XUJdt0?E181TQ0Ucpwm{WSI&P={&WHeVwUgM0&M082LffSZg2KWieDO|7ja?ZRb#Esfit=~MX8`!i-kEv`I>KznZ1DK3XXPh(UZ0PI#$isipyTSTbdICHGI}e>h^VMjp(-<K9QRlU`W268s^7OaDY}~Hrk4swM^tkxuA}M%j5kCQtLw?hLl(=jG~)_YA}iP!ZRvhVC^$zelxP5spvBJjHb4<q!NB$f7wp|Fk#$yEljT09vst70Wu4h@eNI1m78<GYIWv9(5nn2ategE5nAk(<L0c{Zb9Q9;pDU~M|4+#F_ZbDtp<X9=l@PW34-Q5j+x#IheGohd?g7%(W8DqH3TB^#)!k^{LF@=t_{W_uL$jq25j%p#ZH-__A{6M>Y*R<!rgvLpcXTrDzPrsT17&nn_$K{nx$8o`4O725>=+4uuCg*wTb+NG^LpDDD8)nk{&+qih3p1|sDRiMf}Nthc_K4d543p0w*?{q9A3yN>8UH>)w<OULN@YDQoguGn*zo+0Qt8KQc-y?jB|8H$Z&PvE*Oj%HQxxAFCIq`UKOkl(S8-ydokh#VyQJ0KO5HDFg1EbWo*&C6c57GJOxwt2u$VbM;_nO1JYj?mSDpj5op9v&BJocv)NFUgj^Z(NkDDP<2(B3>^1QWXT+Vt!cqYB+#Yd&)3I*Q@6#K^z0)K5bo}fMOe!ZmrGW9ldo$>s9=;V2#SafmH4z)3qOg0>ADkcce+jE_^vqd+zCH?2U63Cc>yc1R(_x1M1o@JR;M;2Z&b53+r<I#q{^oIkPz*whTG-yZs^37=%HtSQqQ<^qvDrGx)KhyZ*0@x`@K0l}GdaWajwr6PH4nH{W4@|HE7Ir?^XYr7*&c)78A_Ex)tfegt3lRqF>a2rR_PUMNW{y~WW7@$-LPa^hF6+e+;=Mu&kVeBM;tn1M_e;PH>-)>2z}~;e^7NF4SFF3m|$#0({Yc~yWCSkGHn}e$)vQ7`J?5dwhk-rSaW8iE6so*mROIq$Pi2-(I_T)Wk-J4S<Lb}`qR!9oUCJf8!^f~Z;^FWqAusYNXAd?iIgTC)u2ct9u?x@0O2ERJE_X@w%9ae`GvMX>y-ojL{-ZS8Egd_Zi$CJMJW3eg#tUUeaqB23>miR_-fciEcx_GY9w;lc}Ma1<4`><Lg!eaK~S=sG9sC-&|6$v4?AJ-ZScbnmU56t63G6;#UY6P>X8^*g?KJr+<Fi%H}DHwcA59`6)sswJj-R5I_CGiWEp*F-Y(WBU6n3p=&n5Qg7dfCHa*&9!{s+;e2}X(tk=KnD$BP}OomWiIvw!8qbf`5S2vwn7<Ivln&k#OFq^Cm(csP!@O;53jq25l*><&eNwN%__jFa|>QkG}Kq^nGDt(%Q;hs26k~F`2r@tK!`ls)Erx$h`^awNnG#6iFKRNyAsS%jZMtdvk0#1GPR<u)1q<cxAQrHg8Pd5>K`GR3QHl5`JhaDHB6~?~;(0aVU0XH~$mzFL#E8M?BOXKwH-Ysv%{kO~iin0FP^40?YwbS1HaCCeT9QHq)UYvW@wz$!0uWSz)b7^DwSQY#$MnvV&uc_IUY78pp!bai<B_@0HyzS>0W%zABiv?8s?!EwslF&0a?<UV&b|Rey+5go>nfnsp+PWTO_}&V%Vbr+OYFAo{FC<CY#nL7N)}b&(xvsX`!e4L7f~BTpKj+3wp`6dnDXH_FteKlr)6sQ2%Zj8eeO%d+EyKRECoU^F$a$6S5hrwiO3~%Uw-2}LhUkFuc9QVdy@gl@xpxPL$Z=X~>?w0qU_5^)n^<Sms-<rd++DKPZzTFkJH+DFtDyzy-z}sfaq25pbGN?r%Hs3ryQvROcU5Lb7|oCl72>7DYX4a*w*h=$;d~nqmT+H(!r#@Ki?XtOg|S*gM?#=`0WC+SH8g`t%C$Y5{BNIy&Vxw=T%Jmu*UF{x8oKLMc8Z20@zau5C5IK4Qt<`F2dA1=;8rX4gz-TOGEQapnMJyW;k*UaZnuN;i=+OBivT{ITn8R2i<RNk52-g8Yy~OFa}T5|bzXK388!13q9WkzkBhhc)8JyzJ?vqKF-Ws(tA?%&2hi%=Tf6<q@%v-gHQ{JtZuVlmz<NxCJxRTe0%tmY@@#~TZj0-7f%iY;o`jKH)t!b}mMx2x4%3bSsAk2BamMd*7A>>IQJT%NYhs6SQ6%%x>>eP&UpU#KT0c#I`!Rg+*a_@!cLAwK$teq#hY15C&!**lWVZ2JTC6C<YPu+v7_U!;mld~3@H8ui1^jCKF)8I<CYqGct}HEtHr@*-K{m_FQ!d6$RWF>Zf7VC8T;vN2zxH*X%`f@T3wbIanmmNN&t<I(s;r&`u_7&h&EfnDO#47;*Z4|?QT`Anl|s{ti>p}p$}#x6&t7lw43S0xlp^ful&15Tjrn8|zvU<s+>*vqH4bTL=q(Me>4vlRzaJF5upXu1S1YHX83wO_ef^R5DE~{nwU9&W#2I?qavEX=lwGgyatI}A;Q9Ivr9(qegs4`t+AyM=%WC9eVa!>p@?H?T)KNK^WRx<nPDRY9N~SRpwJ)9Um+tXN?<h3i0VIt}$1==Idl@NlP446xA9thOmhE|nk1bO_Bwnr1?!H%-1p@3W$6sTu(@RBr=H41|G-rk_&f1zxhY&!?WXPzbINc5rdZ%8!gM^V|uaPqdIu?v(8VIL%^YMA-Az<mjD*1=&yFjTDfN<lq*s!pn+Glo*d%cyPYj|YTQ@7>0K0B=j|IuEnMiXocv|XXU#9!twaUDUYF}(^RdMgbb%Vhjgwa#H@C1*G9Q?tBekSNaI9iN@Ss_~T)Q-Q^Vnvk2L##94%XK0cZ$p0si7mlfYq*rG3d)Wqa@YS@mkWSS~h&A^OK=Ep>hnYO_Icnefeo9@*F21B$@)4xUGcniJ0&aTZP8!+jH9kcjmF(hv4pP%c?`ybqhNE-l0RpAs4Z9*(Et0z>-I>MM6M^ye{Dal(qZ4w_?$c_){n7kgKDdT9_U$>A{Z5-U_x_p7J#jlg5k4@wWAG{CKI&8Wr}ajh^H#08623h^qoNPuBpI!)p9+mC@h-1TWz5%+LrrJt^-YNr566?xyhr~f%Up&+9Ew<oLb=!S1eL8mI#QK2?1P|1Gj`TyGlIW-)o#%8#uRYXve17|lyH9qrPx$;WQxDMd7n#EaILFu#flEKBQd{I*(5w_TbvCi8l~l;L6E$Aj?}M6zXFekp40+A@bfzKqxrbbF4QQRz+IlTf@jKmn=93M>dDBwy8mC=S*7-VZ~#8qig4)SkCmf$_3}*hX@p8_`pTN@P9|pTf`T7t5%!lCXM_IPyRNZL9Se(PG8N&78|zFm6{S?WJ)L$o825BZbOhX@FqB0r8$Xa!&4ZyX+qW?MyqZ_0C8G{)aAnd4tlwml4)EUP$Jo;+L|1!x(=n`>2iKnd03O=BJB7raoWLCpUa)}0e?0ke7czBH?)s}v7sWVoC&k*?@CA&H<@oOuZv{1G$d)C-wkjJ(bH}e_(;@Se?e|3>NUtUP<Xq+EMAL2bZ<ardzEy{@V`OpRON)y{r@#oBk>yQi#(Pk1A`FUQqT>~IL$ttdbwX(@7Y{oChC5q{L(1k2;D8^{BFweAHF&5F_z}1kw*F{~_T(ZeNW*p$<+ll}SQs_00IzW-qF$<aA;oG;7b->|!Z}`~7-t1p$kH~3@fs-1^N7(Wj(~h$iG}PemI|3W<~Td(hXA^E@AMhu{7`B)N4_Ih53E9-o3JcIW7Bs_$HWN@UTzA2GB%1oT9A8QHjrvF7^mVIF=c&xgG$%dm9GWuy?nj~bhUg{gsG3$LM*Zhz5aGxMX=gzQgruC8L9E{KO)qkxWi`M?L{k5wO`dccJ=$gT4QAG$en_f@vgN$dPXX*qNkI`&VwxJh+D?ZR=Qp;i}`V|&9y!cR`ilxLpon7-1UVieH-JsV_I!sl!C=4es~?D_v27jMLL2*vFGKYwO6c7Oa70QSXChJCAof{jw4qo%&n1tH?5;D!x}lyiEx`}ZBlLok|!#II7U>vPBIYBP&rUV%5&poolSjhZXD+375#<d1@4csl8U*;6F`^qV3rmYM+YOgR$<2{E4IYK=Akq<of$A*9Ck0apJZc$BZ)3F7-NeUinCE%B*MMgR@h)A*kPyB^sW&a^?0SrAY{TUGbEX1ICQNth5%&Md!m#B$1;kk*2X$wS}^b-6d9!;9Nw#-XsLR~6GSnq$;ZkVY7b2JXx^1Rb5$wd0$Vj?Q+8Wqhb=#k+h)%=@NEC0&wkef(Sc91blE2QYnNG@pZsk9yU5&Q7ygII(PTAW7L9GX<c#*J2BrS)eG`1Z$yM*2I$|hpFL-xP#5jzCV-{CgZps}{ynHdNLXqUGU<U!bz%Y1{-!4}3Q34x#10g4OF+Ri_ynNMl2Jww}AJur`;2AfZ^NU)rNibj_N*Dmf-CGcAzXn2fKwaEO`b>qV9t(=DQ<n&~XLa3qFXbEk*t>jJov-<lLl`dhvDYCjatV@dM4>XVWst9uBdY}La0XG$Nv&36@s<rpl}vUa;>QJ%|6RvLnWWdg<Gu*mF^p&BEE{9tZdmd0s9i?u#14Bw$>br1(7ayANa|rrFlUeau$7qfUlx_@{jh%N0Va#2RDi;kcfcE0Fips4bv>LeEc&6u=2b=TbXlt*zgAQmoLp6ISjGRFstp-Bw5p{GTe^2m56L}2(V;77Rfm=KS1UVsR8LWL2tlV#(cv4isp_a|Fp;c<Md2S8p%dx{15q1SY;DVzM_u-(R=M+fS*ta${T@}FO$zj?zoV*ZCf0XPI3}t}`l^z@j_uDVt68bm9X1|?yyl5+RVqbX(zMdV)uipz8v~!zXxaUg#$%RV!%})NMZ2Yty`1Z6R)^h-PFu<3VRtsu-l^g~8v`K=KLYZ$W?^r;rq+6(hL*JMX`|`sgiC2YHB(Jzsy73bm!BJe*%-d@KqbE7E}vq9S-Z|MV_Jb0fmiTL%G$vXU+Z0>Z{WlL$R2#WTH{gnDT&ZvEviwdX9~On0!gxfqYf|()NNv9F`S<`_=EyWq9qYs*<S8eSZs4+5N~Q)56)XBk_e?-<z5$&c<b<KhEaFaSQ|QMi?&+2h59S!%?dwzvhPF1x8wKj;50N2!pg&$cY*%9aHrPe!+DGLOt}9@o{yp40!5X+Mk?=E8bIjQq6k+mw9wPlY<6$xEG(x=pU(_R*N}ZsKm0>{!{Ow_bZ)5(6U7vOVzt(zKPYXBCXmjtf7+)i7$vg|F`4ocXiWdJ?7F@;!aHqqSLng`yKyumT~jd}!WYWX!=Z6o-0|&F320ZF$K?<J$N-ZlFU|}XsmfLJC;FId;jtkQ**|w2Vfng!QQ7Al*SqcF;;>|ZERf>1TDMslt`Z1amd}{$zhAh1+-u^xRC$4P?rGT_`T}GK^+)|xLs~aBVbL}9KDwgwYHw+euE**dYch^W^~CZ;J~gc`1VbJ*Us~Dqr1@evt^>_i0@A)SHXzUH@y21I1_7R2O+q<UbqU*suDtYB+jPaZEuWLq*v?a$Q%yPUcRTO9r^mna&M$_)9QRI+&Xp1^WD-V_6-*F6ZO33t(fGz+#?FU79nK+eADXU6MlGFS_~+=K(j`WxC@D$;_WHzdziqb~Omi)pPFg+is&x&kuCYN#2(?;rg_w;BWNc}jr3v%bsUc)b#&L|sZJ)Mul6hv*srsB`!?R>+EH1?j{8modJb^xkY=Cwp?}fk?kWQ1L98#DB4xexkWTSsWQF2}8PZhr@E%4C`ls_8cNgay(%r9g$o0a<>hQ?Hs$3PSGrmwN2y@2_BxawnfA;-u(h+fH;ZbS|x+i%T?(G?Bz0)u;bq#Bh$d-Pv@-Te~B``f&DAZ!6fQqwK7t&^;pM0wA_zTY6TqjB+x5r%}C<?N?mRc1+^V#e6%Wb}aJT~yAO;^aV5u!0m(5X$ft<3?2?NiC9FRMK?9u!-^{>a1smQ#Pxt@fqymQ*;D`MDO|J4KCN>2nrN~x8pF<rUN6QKm25R!+w2L-%}K!PL$x|jUyb{Oc*w`TLkIsWa8Kr7Zi7eA=+Dp*{?jiZ9Ir@5bnyOqY*w*LHV$D;WQ)+=n1_a95_RN6y&1MifS%e_N2-H-@v(6IUBS|2r{K1fec!SIC@jGl6OkX)5PPI2~%CKP?ylmFeC=R$Nw!KJlIvqGCqj>t+<(?H8#5~$7Eb4sXeL6<$%NaFzB5}<sI&=4QmV{m@PfoX{Phx?KD#@MildwZ<8pWp9g)-kM45B^AK2u8HL5T2q<D8KnW3-#mHmT;AFTe$B?fguoxu-M}pi3i{8HdRuH4_Mwx4d5L-SVCOlxXg{M-aOS$z8%&r4q@;D9Q(HM=%MFEl+f|+WLofU;4hcj=;pn4|VdPv(Gd`KHE0AL?m&gbmM?T82!@Y11*jfLh`CvsZ!Ov9q=?6+ia^$uMLk|C2t1Vz$k0YfP8nFAp9Ms=eK*4!yFF9({a#(uu}aPn?A=pFXXF8YJv*`Rl(FR*>VbqwP9RFBzxyq?|DQt~i-{>@CWF%2(`7(-X6K&PRqo5YWVtN#P=!}g2', 'receptor_prep_gui': 'c-qxG?Q+{VlK=e_IBuniyp=h&lgT*R(p5Q$GVx8~cx-2`wtOiTB|;X*6saM|*jk^f_95;W?!op+uDbz}00~m^eC*Zvhb57XMx)W+_;4KO>NZXbp0n>ipRz@kv#^Zff=6stCb#VT?d$y_+lP-IuUO9Kd|d#@I_K*!4~sZUeaCV3_7-`zVnMJdi!$dyz~a?9%L^8!X;u)J*xRd~<u}k)@ap%^B1^09nW(<~Qu49}5#?;1XLBy<*J4wDEtWYCqd2{(ALQYj&%*g_{UBa(N#Q(8=VhMrwD2XVqN4PQu$*UEGQH>X5(YV9p$O*LYMpT4hHSqMi)9kesz&GVQ@$uRYoMTd{%MUv4wHJ!g<^3i;Hzq(9w~@LobV_Plk8^1Rxr@;hR?G55i0;*HmH~%AoGE+oL6n#JqCa0r{~iTr)SgP?BwHgM2~)&UR<7jI+H)%@-<H*p3XO?=^~TQ&H<GqRx}STxG0lC{tnmJC|HF8Xbq4$dK}fbg1AN|g@Okaq4Fv4I7`0rK+MB5$g@l#rl0F*7T~~D=XW{C9rTsP3oZ(H=<V(8y+1j7`{~`g;N9tmX>j$|^C_D!=cf;+=fTDF&Gh{0(?y^_oElb*8z2wsXP2MfyqR8J2A5YSSD!DZm+<nz`SgP`V$Oe@T%6(O<qxOl=hL^&BXk?_1&p%b^CFm)X#|rKd`;qYunf~ETPy;U1lMEx|5i`-HA=&mF^vRt;$56ZAe)?tB`_sosv%3VIVl9YTk;eDVh{<CItHI{D&mM!qn|#+=S+4?3Wi9Fd?T^rpL|CQg^^&_Za};Y0?$`GcRe2`BrU}C(HCmT?{R9_ls<rn24BuW9a46drJSC{3+C#5d?T6euQzv&=kxm*Cdl<V?ORQVWwqcc7Wk;~&R)A$$#YT8QO_4;g3|FzL5vn|PBJOREP;-%8!7!lQ$P<zkvH7Gkcf#+RLlk~lcp>yi**SyhEgkd{uO~_CoIb&R8^S1oUbx^6P4>EhI!+no(-aF+;k1Ia4nfEI8Vp$zkUv1U5{R&c~!l{DXRumGZC0BpZNl;W+@n0PXz3hVL*o<s*xNMaje0Ke_-~23ni}~B1k1R-Nrb-YZ!kCjBzz-(&@x*5!R0di5=(y`UQL<%EcnS_mk`no3nobef4QBoh?+|@(mD`37^oUS-zTwg1f*)m&h^*Kww}EF?$#-g7{$+xzNNjSRj09-`ZU$u_O>Bm(n)rCcxEA!I*eCV#9I@7QdFzlOkJzNF~XJt;-pJFLfbRwlu1(z988lvruF>Mp3S~DU2v-gWBWmwI)w=^!I=s=p(DdM1M9YAUdG3KmO`Aijl))j3!rk$wyK*gY1@mdTJP(Bnu-n%{5^T88z^)+!?cuGZ-~+UwJOTq-juw`y-e+IC*g9K?t%)VF4&wzQ8Z8^X#wt&sO`-BKGY4_}RztvrEU*T59Zsrt~S_K1$onSL=#h1_SQmVi}|%bYMKjC+yFl7{zMscqR&8%38ti3l~kLAC;@Ma20b#AVuJLi^-7(JWS^qhCUOgEEfC63KM7$h))7hkXs`i8Dtq^p74}}U!c34C!rARHH3aBybuz)#jSsJt1LZgLI5s5E`q=nJXx4%$1P_F%s|slvX5UHaTDd5M5jjPY3iCR{30&ErYxKXBdU314{A;yomPVzo~<}|NY^<$JU+NTetyt~SfP9U8+Tv5I2f^)uMS|e#(Vx1g>x(;Pya{!e_epx=Qs@QVVhJ4Wac~xs5wB^;ix~wCvE7wOjGnI6ZS4l1UFySF;WjBO=yaoDodlFlnZLQ>$68T*z7J?V0=k48O3vQU?Zly*u$d<UdMnjQc=@uhM9KCJCT&#$kcWPZI%Jffpt5CXRR5IQ}l3O!yKpS*1s%rn2Ddlygf(C6>bMyFKs|y!=&UB=R5yJTLgi-bH0dq5)HIF`S^Nz(QbK{<+otpnr5eI(X=`0XwQmg`Uni@R|f}ep@fVFj3-3tb&J;!lkzZaS~XVMoW?9oHcxAofu&aNw6_^4N2}c}hrEZ9rWK}25R5&o-!<so6GsT5k3t24mS<0E8A1vf2+W;`OZ{zU@W8ceh1bGay_3PAO@xd<Na8o2kuQ6br736*L>CZBU`R3U#K(f&#Yw_ukiMW<1Gu;lP5v*<q0>PPdTJj^2a+_{p?IdsjLJ0p8pcUDOE}o8uuSJmnIEZOC}%QphV%%f;3h{`E<+*+<66`-tm{l^AM=#{y;)`%&=yL}(iTAQm0(hU)sg!9qTvVdj52sg4?04Z-GCj_I((Z!xW}6g5B!cR0-F|tjVR-`!3h^2iSFS6crXbV<zbvk-y;+j^3gQ{1he>G7#1gbfS`9dh9}aSuOUvxc;Zkq5d;g7-2B#sF(wmdmK93}12~KUTf#4a=UGy&AT~)C@lBa?7wEm?@y)WB9JWEh>ojoBYq;lwa4&1PBaL?yG^jy+2xmMoWuNejj7Jz_O&pANSRUWR(Y`*TkR@t$E{eZTK&#(o^IP^)oQ95xYXN!3#C5K2-||HWF7_S#1}+`G7%|{j66xWjXVUE7<Z<M}2q(ZO$vgZ8sq6f9GjZ-5nwZT5`S?P!3QruU#T39WkIsL*_~!iL)A<i43}#=j<t755<*8s{AuAX>k>+Ck{x9q!=eHSyAThoHh?*f`A**0qu&!BfFqtNk4>%>KnaOFNy+N}`ibQT20CUb#knEhTAjSo+8MRg19O7LbLa>(J6ibla;{%P^4SNr5?Bxc3k3B;h3oIW9U8tnGNFFNzdPf#PP|ZLWnX0+dDAuvpLEeyev>SOH1Z{OY)YZ)*Emgyc{?oLvagMi}G~N?AFFi%ub5km(DaPVvKVSi4H0~2K7_;_wXd8d4kJn{UWNBwGuK|<b|M>g=IEZbvLK`KG<(w>gKs{S~J*q|q_T@ku*$yoHr27eHo5=l6JZu70YlnX%6J^)dZnttVqg(+Jox7F?k~DZ0z#biu-vs!f$#bj500~D{gV~_2hP;07c+$&Z6?Wnzd{H>I8EH2)=S1cNpn!1%mgr>{WyPHr=o@yVO_^y%2?V1IVk@z4vehh`W%n)L(BSSk2y-B2vNGz1mIAz;Ojf|dy?K9f@$n;mJ3qO&oH{Mzj8PYmiK#Ir3@z6wdG$&+*}n_dzz!z~PuS1dOl;-X<vLE0T{<2NI0F>zBAXoBW?Re4sww~W_aXkW2yZx3nH+P4_ZtTA{D4OA-4O<kaXQcW3M)wTxHBXzd8~%?-QbW8bdNb-^7*aUqSq3r(dp+;(rMMDA?t{6CQX?{UbB&h`5a5DGijR97n|cXlHVsezs_9hWSBK+Ns}e^{0yna977)-1&}Kg9Kw0j5V<@=ixU_|wzN;D-^jwPQIFNF?miNep`WVky;)qL2(H6dBhBw~x4)H|A2?q#3}BIWSxOn9Q6lJ&Wv?PU$zlH<^L~L#OPtYE$GMCdfkx;gFXAx4g@iaNk^X_HuPYi`g5ASEa3GjJui5+Q)ydUI=B{`VCgPiUwg~66YLRl75eOg3P%dhCg9B>UTeggAP=K0&A^u>2w#cwc6vBHpupY})^_2>+M)rnAmTJv<b?BYaWMvP5beGmb(8tOm27Zfx;c?QgIutpt#(D)`zsCH|)jF<?>_mOS*p@I_XDLh9h*>6mka~f|hl$3TZe;7mS8ZzI^ppZD!*H8=AhpxOpMy=*h^r=Vdl{hETN5UI*$YSwAyI=cHb<!$YF87d;*)QihI5V<WUzHj=g$3t#}67|ked@A3gb6<Rzm#k{OREMyT#G-UD~QG4Myu%;Y$brc4__Y<n+VzZM*&K;NakBr}l47&fZKvSWvv2y;vNFyP&A{Vzdx^OMg0od7dRnuu;-}Nk3;{Zi;)B#~AS78exHpuI;RbDA=HybTHrVh8d<c{#%w7J-F{%xHW01hP;s-)@{|md<dUL?B4qF9$(t94hJzU`&IWe95AG!+va|IX+@6>fj`hp3|Zj{ra}B-xF~YmUXDXg6-XbZI#M}qg}SmF<m|ABQm!poE@Gi~1Na95@@7467g8?gvi2o9gdmE3ti56ROEX5UD&Kjr8#xH6SF*ZfA;bXwClRJrP<NU$0_{#0JswqQW)ut5(T=||I@*=Q0ct+2Ax1Y=2s)Hy08$rAp2C!B;Xv`@T>V4?)R55*2b;Bq5d>ZL@v2-+4i9LB!HQg`D96A9?Jd>#@67^#Md{&jE8nXYZ-xt`w3HHM^IP!X`?PpeHPlL@FTFO_#t3}-)XHdg362z3(b*g4s*Y`eE|$7iVWIZyAYRL=nOabj3uJW;*Q_DLX)KmoqWbRAp|zHR`=h|y^sl+8HMUwAMtw_SHb!kVZ8f+}ZFlAAWs8dj`&vwD86fOm+wKG-Kx+PAPPIqftI>y;g&bH*Jrz4FrI+pkuMsj@db294rk+W5V`M&k3VKnd2&-x13$Kf$(Z`oN#1&1m?O9O+yHid?+`=|Uy<Aqk!tGKunh{&dMz2P+Fa-R|^2izT5ZG3RHJyl0L%S`KtcdDFlg7*5sIMWy657?xpA_C{D4!7EX{E_VPTI-3T}ta-zT0B7UuwRDR;~2~n!c6mdNFdM?V0yOfjbO2)*Lo2t*O=v`T8<GZNJsm?A3BjduMCaiMg{>?w7M}qOBTuJv)wYHhVU*s{ZuV9RCJ)49jYWzRB9ML&-o)Tdw0YY_?p>eYZ9yOBBBwm-SuMR<_z%Y8_3@%Z6w=^B@b`qM=zkzA(13wBi2%NAoa7F~KE`X`W}fTW<kL<yy2FkMI1Jc^m4*V4L2J+M%h9({!zJe7Iw9Qi);jpj#_4it1L|zOl3#ua}cWl7&)y)RNa=gJv<wwzwplj#|p5%JP;fy$zncvR*;ARL5=Y>N2&ZYHfq>){lqk$~FwLYO57}gR0ous_NPr8x>OAbRq1OQ(N0=Wk+!EKarRKwQhUKN4C?qs`xT|0_lxhT_wRFs7*uaywVtnv)dA@>ocRXK3^AuJIf2#fym3LyYh1-X1Is?KhxgEf^*r@+m#wEFwjkAT@4s8nC6yPu$-+^Qu+Z3_(=ytT8$c~9jAoi+SDTFd{Zp5bj%(QgTJO<f!g{0*xry-EgRS1(d=mbOWqGpdwVMA75?aly?FaWTvV`mbQ>4_u$S}rd{e=SdA#2A!+y_KtGI%_!5=o*FS;d`Byfl+Op{AYtd4j<t^w1B$E*lax3c)xoVoL{6i)M{n$YZHtsMl-|2d0Omk?`S9McC|*RpQz5`7$vzVHSJ#26f;y@32O00N@yPWZF17~vkQwAm2J>7ZtK6UOP5L2&73)WFl~EaTu%WOjwR?Xdr1Eucmtum;tq3RRk=wz?0-P{x_IW`BaHl*4rVUN?4VjumQ~;<2@HzEG`+YwT~Igu|nm@NB#bKe1T12xH0=(dN0((DR0dsqe+#vh&`@)nI+6Iqo|If3%XPo$3lNFTgCtNtE-{8X^)@#Bsu1Y;Gc?Xt6>l4-&NKPr?GcEf7mYRlgz6c1^yw#!Y*A8UiZojWQ=Kc(ru|`Bq`|;O&o}r=O|b?>L@io^=*o*MT%1FMv1wTW%?!?AE`U)P(>R&O2ORU=Mf{reTTq*xljl3XcIO&)I{?ht7$V+Cl2QN$;vF5*AJW&o!x0qJM(^yrEO!j7Gkz0;zc0BB`xD?!r8!Wx}&eZ6rmJf*;+z+6)NdpbapcZ9{5P-`$<NmK*4eY%a>mq3-_Kt_knL)F!>#vGhF<D_#F8C-bEhM{b*`TAc9gr>P~FflKCBuPjsAtbFvzDQn|3gNRCoYy9==P@p~15XJJ4ZTE~)b5ILQYW+vPI`(>ttv6OlhQiO@HJ_aunadqJ2HwBMdY)4%gWMtu+BTkGGjS(rgQat;KxJQiEh`;ikO|UC4C4{QlawZYm7GhftgEovl?U8kh4;7{dIf4xXFJ-Sy(-&b$0OEY_Vne*ERW(eM8lz<?UUC<n3@W70y<Tn2Js0%ujWfrbpQl>pBn8*H@tX2PxU|Q+Ky2*rj{y3Azx*wT%xfQtu^wc;29ZQO`~hf@2Iu^R*bv%L>Str4nOZ1`llaEY+jj%25nbTX!AG5tz7b{#W~hjbHKzL^t(Y4o9^u%E=We8`kAQDk(yvSuZ#Y25#QsURVl^$=s+D$Iy#AD+_A#dts=&8Nn7A$F?*KNs6LkHTn9oN<tQoY0f%<+`RwfU?0dSk0_PQEl2pvIVw6+?Q5E67C}*p<aIMh&cX?PLjj8X9#k}>y_LsHgs{Lo^L4Qwe!`u&=gsWK;R=#({){~mG<6iEs4X&%U?J}3$L$-wDT7G^}v9(o9)QrWcaS4s9FnD&sQ3dH%H&)P&nwTD)Zm6g*DQD)|2enfmXvN-~M(&rxrpSqdYvyS**rLu>sA=8G%wp;UW(zXyVvLF748uy#IH@;K4FW3}nk<~pDX#n_=;X)}F$&nm>;V}0xCILgX)SnE7xlnh_c!qR4UURfs%nJ%X@_qt@1OC89UDmNDj&Ol*ZUpScEHegI|1GJVViX^I_?EtI1k4CE03)DZA#SRxPGA~v2T{VT`fFeGmX4_Hfq@26QlHB>SOO~5z1X^^*vcwjbDXD0Ek>2@d6@;BxxB6tL6CPrhCUwks?L4yP}iL4Kv8jB)J&Al|}Z(5d<pE$Xs<J&oq$e*D2#J$$mErY3>->HT>^QHO%N<ZMjP129})vQo;=L=r1gsQ-R1h?}%qs<jKt$r)!sr4CXH~qyHyVNA%;(eZ0F{f<jP|wu7Knw{+-phNZMLy9?vCi&JtV54%rS>%xL?1_9%(xj=*$e@$dh*9WHi#e0kB^@LGa(Zv^xWJIN0391KfBd!p3;I)FAQAI>nHaESrXaGpNf0o5LKuFn$R>mv%%B2HEjs)q8H09gtL%Q~gMlb|+^o0s3IKX~8*&;yI59J4FXm~@#L}FHpD4rPnmL_(9<rafmWMC`*KQiC&V_WCIbY{P8E{vW>p0@=XF3|xp&u)`D)d;r<KE9E&<FS8btv!yz)rvPYhKCy2<2Mh4O!MqpLI9_yJ2GsYKw{j7hW+F3|J@BHhU8ef@9{wI()1jD=~8Gf$iBuJ0Ig_%d%%?PY6%9M9_sZEx#Z!qOD^vy%;laje~?=Aqfe*R#6j+~2T9+3N>8Y{b?RWdSKfx3KHUK~5q3#;Q8kw^#cA=SzpBvODQMjK)DyiU?rTFn5w(0yw#!suc7V(5-8f&At5ule$qSSjS$hV-zvY|9$phJhM~A3`C(2e3g&CIfT-6;K6M-QWR)&F})eU;ij>?R2U!}#MWQwL??d%CV`YyBS?#Goa=(-2{hSGt;PT$T|SAce<h4n6>U2lEqMNQi@WCvr0Hx5<$vLzPXGO!9%BHm_gs-+n#Z+fo+>Pf7e4^O=y2sanguI=VZMY)+R*;Mx%scVh8J$g@Cc_YyV4qNVwv~$(Wjh?v3*0XcCc6MbFsR>QB3!h|Z!IH={8e+j|(UhmjK(z#DrE1$^pe~}s<EJp<5(EDSYWCQ@UQ_O0#Km1>3%dW$=TNotMBchpv1Pa3y8BRuc!H~<wkt>FR!+HyhN)bwinRu9c+uv}uQLTe0w^%JZ-sgLP#a^Xovi6g4W-YS3~$qH8$N2Z^TuC-HgA>P^|n*1?EoS&A+HC;&?mJeEC4_eja>PvHx)DXC%S=Y%;FmeO!#$J6!|{zDo%Oyr5j&~jqukHjACg+##vzw;%AGr>igIIb7Z@F?cj%AuIdDEZAt9Gb06L858(Rk+YAtSb2zK9FY;R76*yAYyqlLUr^nU4>Y{r8B)=)~!i;lz<3?P}L2{6s>h3UoZvlvM_wumsKc70Dh92)D4nl>u@rcg;K01f}`f!xCa7LGk85QUyPu6(L2}mP!T3;JpQ&V}<f4}^6M*7T30s1ZP_*aLS)JY|IlYHg+B&E1kIbuPX-lo}IN~;w_I(-E65QiWv_x@Jefv*jB*LQO;%6$h|9?Pkh=Fx{wjH_w&E+^glZSht>oZuwODm|~SIo{ig@hV$d=?h5ug8*TJK*_({uYI`@5TH))<HD7q;_dw}d%$_&', 'meeko_receptor_wrapper': 'c-nncO^@3+488kTaD7>)8yhpd6bO(4+nqV2=yn23(Mu2ricL?{u_afMCkcxF_mYwmr)k<;VoT)X<Ku_ZG<|Gk(?Dt3PI|Rbjq(TBS=n`HL0Z%63jRlYHgHqCDQ^FEV6nu`8w>w^SQJSTF6nrA@LQwd-{k^IsloMKXVE#3<lt1*W8O(+VPgnT=^CxY3TkUwkUCLq*T~+fO>+RZHP(YRx->7cLG6j0_OkR-*z_KhcaaKnZl$jBMrkBSkG7U2CY3=)?jCU88HeDv(o-f+eM?vceA+5^N>J%9SQ4Po6xeSOn4^QTk<O`FVU<t-kbR{*vE3X_$qP!Z6Q!{@Wj_rSHuxkxg=RUmu_P<(jC}@gV9+Qrb*)N87bG2U&d8idccY6WP17U^f(TLfzPBg@8?hQvQ$oScCCPC1#Tk8kb_Y67K7Uv&#k+@(cj96BY4Pw8=8)$3OQX7+Wp}wZIrH?GvonQDDy%`^-doaFu#pG~WJkT+3>xM9%6Yq<K>jwq`JSlr*%bI<JxhRos)k<}a2=F}5iVHr&myI$VYQCFy23s2JsB3^B)bHh93w@Cf8ZA0&VjmQWIQ>GAr&>i<H31s@At}Qb^7fR@jEg3+AGVIgZGcbnYymWG)A&=cg|{c3L9yYnwOWeqsi-N;_YE16rc%^<u4i|E0<A(7z+2?TJef`++k@dytkG{O*+2*V`2+U;HnA(7DtUiX7G(1zo(NpYV;g1LXl_Ji%Im3MX6)`oYKxqU1ApaPlMl|WKQ4xL;~90dDtKc%$|d^HRVNP)pCCX+!65Cz-&0g1@hy9^U(zUn!{^8VSAdq?98W=)`y%XAr`-Ktl&4sx}LzjEVpM;2A&~{u!{)A@62(r!QzgiDE;Jy)J_r?yk>Nj1+uG~^)w)@Zr78cz2XoA+hH18LeIje(MpRn$GN21T$@%J|AN}^<uo1R-I!=-fHti1VQVZ+b7;{fClh1UlhU-G=Eu8&y+l`SM9i?@-K0w)Mkgjs-;Q#NmAJ6Z%EnFM6;b2ASI;|sy3jrzuF|lfgf}8?sFeF~OylQrMb(aMuSXdP{w5W|4|~2v`fyd*Z&Da=M)8WWQAPV4J^+$-^yzarh|2Zjc@4&b-_9#dHO<DGEHv{C#Ym`VLTK6Y(x21b7QsM>be3H0(C9u%egIp3j70', 'ligand_prep_core': 'c-qZ<?RMKnlIVXu1s1!x24V`99LLEh!^~AIDb_}^bR{`6b7U?KNP-f^Aix1Y+lr!}`$GE&_rBPzkNyN2B;{mgH|NA6`lGtKySlony1M#b|K-`TuAYsv;#pdJ@D_K?ZCQM^<@^5ra+)>i)T`%7o^Q{~Je@4_)LT^PBB_!lD+_N{R^HDi*||3@C-1Z3CfeG%x=p>wZ932Drn>X$CYikVvf9h$i?Tv!dGbq^Lq_Q}P?9RwP%}@rXBj{rmt_MrlZ7`)imf`$XWLC$H(pkFiMPlT_<K$$LQ0cXfDHT_dHa)QndBC3Rr>d3R;4wyGf#@-CY^3kd)2aNvN@nx77YM|*1d~^pR#7)oh{PB`ym;pxtA1E?=(%{ml2M|*4C^l=UyDomd&zC<5+YEiWOx;4c1#*GOfA+Eb3H#PwEd`eVV{<<VjtpwW?oFvkA1UvIgEPOY^C$dz;j^c{Y}xf2+$v{+=hzt^8fq+`<CVptyv7ZWO5$KK1Rg$#V6z951SJlGe3Kxl=!zbiTlOQQt6b>UWh)(lN|0H{IMVa3n?ME1;QVoTmft7$%5+oh@*jl6>G@!rY|AB;DHD`uXtU^7!nHH}w47XeZk7w@&xp93LHCUd8`@$>}(0@yYRz`)>~7^NYjt{fqr8s1nP95sr#c@73kc8&!jO@wYDDo}ZsxTpb?7$8XNxUd5MhkB*N2a(D?4?)|8q&isLgf9Ve_0{Qnjr_VF_H&1K&*?el~FG7FV`t$LdgR?(h#utZ|hZjFXD@VsChi~>zxq&SY{_|g*y}=si7xZWU?O*WEo3|(afbzc#W>DnxzF5x3Y4zaKs^bq_7FAN*q`~gM+uaF6UE}2ZYQq{2FbhO_-br=?WPh#~(P34URdB)Ug+9VPYGDDzq1yjeWGf(GU7qHe3zo}fv25ZBmh~Q!BUQiM^JaOOG%yI?L@zk4DjT2<tQ*hEX}Sl@qr!Py-1=1DeVQ)f92OVwgLqaYH}kXrpujP5D0WpXQ!181M}gv+G;We*Q^N1MTWFqqGP8k~K<<lH{Te7YEwg$Bj8+kb^R1B$a8&y4OUeMY1M^{4c)mj!FfY?`9@l9))j7{!zS!lF{E${3E8xfqlcOZB85K&8fmm%UDQ}w2yaL)w@~lp$0kYK4+x{NtP0y9jlSOF5&_jI~dny{Wr^N$O^8GM^0@)%6qrCi>RzaxhXEO!?Y!PYg9;Xk;88~yDRv%LTK{v&H2CTfFlYGha6#!bQL54J60{<VU-jl`c6Kws7g!Lryb-RmOz?x`E;C*Z1gy<l{jIw$LEWb$uD1gu~1K5uD$034%e|KL*JL_;<yjEC^)8=CeyT%Uf7*N^3NzXLk1{2Dd=~P|PqDQl^m0_2+Xs=zz%52v|qU=_{)Xtdg;*c2q_#@Kf+VOcMD?n9X9%`^?quBMD5`mZ_WwvII1th$Dv97(-<Wn|Z!XBimbz6M-VpW6oU?Lej|8~<>?YiBT0o3ZIX+Cgdzka!KPeJO)JyF#$ykEaGn*=FoSrsOC4y<+zE<Hph&17MuhEe)y0R+CRaj{3R0L%PC8i@TyufgHsww2UkA4B}dF5=|tL*!$OhBLp_vV-Xx5FEL!`WDR%t*^d@tXX$9X0O3+gEoXtimL)n_fY?|i|A!K)ISF;f>K+|P%VEWv4y4DbBz9}v{qTQ2N`8mno%}%$qmN^P})U0DXS^3fFhZ*1VCSPxvVB>jM8l<F)OC&C)zK0+ZB4so>z|lmQHXJeNz^xS%ZZ&C13bf-fe=b(9VNhWg4fr0F8_u>E|M?mwCgTz)4!x8sj+#*`S7Wy71YZB`Poy0ka(=gP5<KA=b2NQFl`0ET-eXH|{KwFRY9NRm2#@??;R#wcyTz7Tg(GK?t}ej&;6t>du{!<P%SBk$>1j!FX^^TrcNZBn5eZy9XS=HHciZFSjYHdRorxM8IQ`l4jRJP_NYZCM}3@Oj~oA0!2e=jM+DLdrFVGCVWRGg$wFWs`z7?-P|@S3s3U$X0ftFv#67m1#ZVvBOkDC<t8g~D^#3OGmOV&F|AjW{Fqdzr9%;rVVi3hKg_1l3_!e1V8O++WC8<!H^dUW@uhjPsF5y!tq}b7^p?C8#vl;hpeZ3M+JxT#CyRmK)uhmPsH*oijG4&W;#aQ^PmeFJF8(UJu(gFUxH5|1J_rn|4umdslb2)I%XPgiAte})vYKQD1h?1T)ms&z1zkky{?qqaqY_C>pd_WO18$D&2-9Vm{XECdf%ggo|3z91yo0o!z;C4Y0qBmP{@3rb0aQILb0e=0a0JCJ8`yi2YMT9$YFzE~-s*>PqrJ4`F9F7#JMj2Z=EA%Rfv7!XbF}@~ZBvrWKNb6op)C)*^MfD$&()uC)2mL>n`Cmwg!pNaE&wC?gKAAuW12CMB<A&K-_|DUb0N#nRlvSovjt0Atx)$;1~y^+l7_GEJkVc~>EA$VL{Z8EHL?^?v;i#ge7og~WdYkXY%F>1J@YQ0{jBo#PfmDj*vJNrQiC61ODaFMLCpMP9y_s>-oqd~=prFQg2XNzQ%(uUjmbDCtzIetMzkEar%+|943)yWxnAgNr>Gp849SAko1q#(Wg4I{TeA4Wy{hFCW&3+f;aXhsk=7xZ)}Brks}VBfx-@F=0>w&Vsp>pqT|&OOg0~DB<E0D*)T%b|w3j!bY$vr#8>?BCHj<3e?nMiAdRDWp*|)5rZeNyByBzx{FPbTG5-~&mcIERVo259#C`)_;O3+^;-N8bjl#8+GIvoxJH9Bcr{$b0#N$_?wO#$C&T1@U@Xb6@|Kvp5##rA|KLAw+XsblBbvI%{XXGrE`SB^g3W|P|h#*~IHG_f$qJtsyMBO?PLszSmLreLGDd>R2+^<5o_eK@KYc?Q^C?~DfB)q_jzCI!I){t9fbMdoPW`LW#1;~1?{%i?`eek}Yj?3sF-`#OQ^;wu}l0I`v*Q{UX?ZLKqh{UMn7lX4Ece7c=yMM}a6Fi~q39(;stPYhL_0V>IdBqO7|7u?I{pR~yK$><?83<sfujGd#vnHvo8gP^}UnWZrvEubm_$_^0V2eflYy=~ylV5h<31tpU)$pFwin`cVs{^mImE|g)qZPHJeT%}RH90%2t>py<K=RbS*?$<wk`R>!s&i1=cyR*^LCx|J4!p=~;ExTsug5|%fpZcOAX35gN7sX=GgmDLR_2wbK$PUSZm@KH-j{xK@(sZ;0j$OfGguS%?@Sp=5aPpqghq>PH`+5&;2Waj`g`b8l3`cSnNZE?VcMYs+RA=`*`fU%XfF{nOBCbTm!{|2sG|kX76NENQoZEnvSTrfw5V;EA-Ga%3_%Um4=_o5g>J0p9?1#7`-@^3gh5(Gm8k1X~FdQsoe?gwi$5ZG8myD`3nFhN%&tG_7diW<Ccw?Ak+sMYaz_>$)(tzMuOiSc<JBkWmHi_BD!9%F~%SU?VaBAV5x`s+?(M0q2)2s^kqaLE!egKjOu-mwNPoIp-Y&xLBIMUo<+~mO=)UWY(0E~2&eHs#ID)ZDMqN<lOO!u)pJeY#khDh`V4wBeSfs3Y~tfSeKrU0AwKlV%msd_x%G!{%5uIyR9tZxH53md8Lib){LAWtX*gJVJo*d_90k_KuB1~iDFQ+P8LhuI|sYF>UYAnA4loU=<3yzPo~;AP3{E+WA7X3+rg0VMkt1@w>(SBPL&E~jbWFPqu+x43t>=xvFk6~NCqXr}T&^}1Ou^7NV;C%B_gt7+f&U%@t#;fZjL)&>tpyoT)rnEGv6kq%J-ox`RKdPW9oj0*tAN{Tyg!j)&Rm(-Cj4L1!c7(zccaX?)imG$cpl|%NoT-56eax0C3iG@1ZalM>OKyQIQn5SX3<^cFt$;Wu1)}&w-^SV954IUwp`CC>9J0%{uY!w#M0gur?aQ%Mn(%oSBu35sHEn`h5QG!~@G!Qhe2L?&qoH)*pjgf=76SUSAsBqf_Bxqc6nhIW1VYj#F_>mRMv<+gx2ZS+BZAj|?fy&hSZVqzS`@jK^75L+N{~)VUG6%8lKJ(AWbjrj9(%rI1KP||bm*05_P9_%zISz|F_+7H$CG#8Trb<6#<+9$0c3=P}d0D4GHDM3qH1Kg0VK&Y4)>~3=ffgB<#hrApo(v2WbYXL=&=erpi^Rb$;$Sb@zo2)wk(iQ?MT$~zIt^4yEwbrsO@anDBw>3_x*c4#mv#0tJ;WxlnY|D*_L+S!XLdzbc;bx0u9<sO$9SWrE@lNt->rQi-juF3?Wn=Y)=imF^z-`%D6~n{u3_}DHMMdl?lj=+>t|2whP-2wo*RBgC=E&LeMP5+f%x1r54l?wjjj=5aZ839Djb<d*M9rl+AP<~GHN-Gs*S47e51bOpxUVI$Tih-^U&I;)pMBb_ncEZ+v_=(_B&_Rt#((}!xQXI1^Zar*T-W<N!RJNZ=7NqMU7OWtU8xAN~$#5PT@Et>ZdiO-!76nJT!)V0}n@|>2kiP12@HjPFj~$6TeUIq##+d<*%&jVc-wY;;;u=KwB*^Y1-1`MdRW1-tKd$=!-^a=>_tPyk%o)*-=bBAfyjjG5RrW&Z}|}`0*Ra(Pk62Y>7gzliDi8mZ%<!d#5c?PIQnGQ5BIk6wxg{^o^_XV;$JamZ4!ll29-NBY@Icmp~qg2DO+yBnPN2Acs`sAE3-cb{1(PLYoa%se_QVkE$8&8Vr!kb3=q9$EEH3LnTDJ5do-CY!Cc@ZCfWgvMTBUh&@*&>k%q<Xg*S9cvPSe6~5jXwFj5ecSq*DfxI42dgy)c?Mkzu7~p$jgp4yA97!d{anXS%BsgRCu$Y{&N&Uf^wU&u!#k6(ILa;JuO~BF|@~YUbvl~ps9i$%mLZ*O}BK?Rx82WBK2n|Ik8W{n*=m2(%3rY~mOlSJIcti)m*xTCWw$*c<H}lay`8GjQuXjs;9MXSYmatRe2@w(>ji_?DoFsKREAuI6B0Qhu-m65m7HSVIs)#8IAQxz?2)LnZ;65XQ13wT<;A@xWNm7(WHc9eWr!h~@CNhaANYrJJuriP?LyPn_Z5+!|Gvs&Oz-psUVFBKtF(_bl7j!TC@O;C0;$zXoyF5KUIlP3`m@nsrW4>&bBH0Rg<_s{?W+*&KF4keKUYvTU8{MQ$VD=_#8LM5Yu<(Z2O!pOB!E8^@R=YK7LC>Yh)Yq~FV&OiGUWEGVLwrwT^kANlbeRS@V6hJn?_+hqUkJ!Ff03DJAg5k!2(+DO_F{OOjW#{(B3Fo^KDMFL*O6dygwkFYI8(${iyUl5X;X&98jWr^_Zf93XXr_XileHWUs5$u+Z<LxQ_hQlXV4*rA*o+BRcg1iAqbBs*-gc=@SP>8w?po;?aC<79x6G+Rh`ivim`H*Afaby$v#}XV?nj+Ykxl24@{B8Jb)8~&3+Y=a+ynO5Gcgt?qH8WWDJ5dUzoN>vN{?xyS38p*yC=iSvgsEXd}m!L|-mfeA9kK2Qn>Ivw|kHMG2QbtcjYg_h1QeZbq1b+%d2Qlwgp_m|CBe%VHX}4?sIy2>CVlNn9N0yO;BL{8u15^WPTrav`p!QQz<$Qwj{8v3XdFxS&Nm$D$)}`|K<1KZ?*jrfU*?SBV}R)<)iII#LuJckvm-W@1s;Rl<p6SykA8TVd0EyV&P3sSPK$*Vdqzmt&_f`}Ke{Y;ZJ9BE6t3wq}n}m!oaK#a3`MO;i0<eh(%FC52$a{fT^cdo4mqb4|R%p}6a|_Zw-+sThR+L#eBecpgV2YstYPp8rN7K}q<x5{lq*`a-3Hvmr0eGg8E8HZKp*RZJuX#xS!z@pV0<Q$HA*q{y1=m(+3e=B7kF4wj-Xnp#J7pG`Y`W|&osDqKBptC`$768p!}??01LpD_(6zIJf*SX!-9r;*=ebae6eQJe_=JU>El;Pa{1joIope`Ax6CGb_mt*CPiA**uk>Dq)~cUNx38&c!%O^JZ)a)MC<NGNtuW7zRQ>32llMCzqMY)QTSgJ5=8dMdZfcif)3$WWGb+BwEBW?U%Aq;Rt-Px|!X&5pfw`m}_|R?fN!h_-)B8zS%IrZ$>NYDiReb3xQph$&ln<)L*`0S@VgXXhq`2D_v0PS@z2s;U|r0=nZU6lFf5xsMs9=ffna#xRvb^q&c^nk<z~-Yn-qh`i+`ZBm#?u`UpV25_4uAMQ}SfYPq|Xs=ySoi2;U!hJ}@0q6&|0+1M|fIBo`yaq1#LIaj}mpr=aswZH8=DQ&ct$mIm$`9J}we9UnFDTfe@8ZQRoxSBIpOHZYGyy7)r+uts+-`VMdli(}9w#**hu66gm~ed}Op-!esZhrm(${GP<<czy?b$mP$#`-)?wTOePXL&1K&^J3HgtJi<q?+54!`k@I49(kqCA6<Pqc1_Oen+&-W_S*=O9pT(ecG`Eo6WSSo#UXsY%wr*fZDgo}7!z`+^~PeE*IwEIx_s2145%QTe`HrFg+3sqU1!jdX+YKjhgWmcHe;F<bkwVoUi}mKbSz!7?HAz^5#V^x?W9?X1G1l}@|0bUTsZAt?9is}lbCAulKI6&Z(}BMrafxdIH8my{0O62bIz=lR;XziAo*L3}&om?p^hHL@Y*lp@;6_L;~xhM-4H_O};4NwXY?VR0Mo-MEC%Q8%e>rT~9vbm{!~{16+S!q(JH$AJ`VAMZ3_-QDLqUAU7frKK>-aZgZ=>lz;P@YTiP{?%dp<}7B9Yv{vHDEuARG!C*~(fGXS@3cDKF~6%RikO$6Dbo9wp|>OBO&9~&XPD#Nr-5Y&^Bic1JRAtfN&|>wrW4-wW*{TJpW;3%*x(SvfMoLpbO1&7%zH-jdV3cGLyX!kY;tX^5K%3<dW@us9;p(%^MGe<|2hI3n$XC)yLi2=U~37EClr##=57+T`Yg5(>hFc<P9UK<do(Evaccs`sT@aVKfF>YfpxP$my9mc=D64|rf19M2(LLeb>NFNi+{omFBqCre0p|b;v#ILtxZC9w;azY)(qhb6WWU?9;RLb`4u+-)fsrJIN;~t?U=w?-Y~-*o_7Qb@#rAM<@5S(T9r3xQQO#ak^SjZ=L>pdo}(DtZ^M>^87~7-7Z%r|75PTd6%QpZB4b$T%9lB=T)Kb7@jxqR8?CjKYwVx6wjQ^p#7z`U0<k17Ltu2d@vKr_)aCQ_Dom}fH&$km&UMJqiVN=IFxjEx>&4<Mp~lD1fx9zn)H2bHUgc?0EEladve{}cw(hB<Brl@cjdey-;uZC6o-W5qYQHo8LNs$P%0F<(LKu0Nd7$=!RS?x^9X_M54QYkkwGJhTk+l-_j$VB;BvtFPE^cF7L_S~=VFznBc6H<(7Nir1!P=HNLODY2fd0B1_JYI!Sd*wN3%9W}zcb`$HG8J-7AShJQFRlVD#|xIo383NrBFv%|AjHfYv0KXhSOMZR3p-t;#O$BJC??2qA3;WO;N)!W=^jM`D2z(L0z3blcEu$-P|ThwHc%BsRB6<DFSv21MNPaPm&1Hd(?Fn->ab-o~B)TZ_{=A>U>#<QH7GV=E<ZPtygRt{C%$x0J;3T_6>i$D3E>>x91ZK+m%hKQpT79o`4?I9n!L`lkHy6oCsBqW3dR0@0q#VQ5)1R8QX12K?*Xv(_~?*QuOH6v&07lg1vQlW5={3F%)}*>EwzX{fzyAcs6emqyM&D!i*kw-Q6cfZHjh<N!)5jxf0O}jLqRn6h2fXY=?u}q$d4JLjY+M1l7~z)0J{gZs|I@Y}6_lpwY<b$n1UTeLHabI9rA{;kgFgFj{#flc7s3auKzr*;E9{yH+p;-j`(RGXSZu1jY`bJ-}*=3kc(vHpUoP^JIIAsdkYMY9#hr(bDb=LEx$sC!MPJz>}_doFjB()eE;8C7kIH;|*QLuxOM_rvX&8!Koff9-ydEA=$kSkK3-ELGSyadv3ePjX|n>ztw_-$ZZOwD^E!BQzRq#&jgE1k(u5*0Y5M!6C#BU#3fg(;1PP}IZPLNep_^c#2|rEAeS!Y>{(AlBy&gRD6H|}Z#f)NRxIk6oTxXf#;9v;DvSK?ZIRS<b^}s8(_N>~vdI3vOnWk6FpotvybW#<7@jqU^Km*Qn;9!IE9^6R;Ak<cp7w+u87Zn%+-7JGS4jSmj#)72ksIxh<cc|2D-vkY;B8Sa(n&VU(&;us)B(6n5{8um8B<a>ft0;+X4A2S&4b`0M9ke2D~oY)MZP>m9kshc>wll<;?hP>3=FU*)H#l&L63r^IT%$B?~_1&3*%D@aZ~oED!7>-ulo)MWK`YkPefqt(nxm`aPzHK<$Ro>0xfCrnK`4Iax-qvW@X*uVLq+l+d5jLT9wD*mW**1k5La)7kLb+OQjjH_3%oJ2#eP~+*u)BiO5K1t_+(b1gf&asP&Sj(ArZ6UD;^>()RRKiASIY5s}J(d_=&E4zGSX`0>M6ftfAtA6=%T1#`sBbQ*g9%iH<%%@O}+7KbUix<xw)0^T)q7S*yyFXlC7ldIuQ^wrmP1i?6)D!!(WLe6-)%$p1(RSe5p2cp*lj0jFC6bZC7?BPH(Jmf!N+qS2hG+kK<)n%PtP`7!^%*(TFe9hq_Or@1ZAt{=-uRIz6{^;#I;wVhmq-d%P%ao)_FY&%Q(D0qHoW&?#n+d|ln*uauseQLdgnf+dYfaD%+40lUqodbJ4WBCX6ZKh+L1<lCZG*$we|S-A77cpUBCQ%m!)${M8X~roETac{KA+8gPO1zPzoCL^^LcCFQATx>LGLY66B`sH=B%-`X55Jg^M&K-&}?%+5<`RX!tTz_j??c;j933y9ATLw3hAhcPK}SVU5AT~n0a;Sf$hV(eb71b$sq;s48m|=4PEHG0qnRL=iHHO{o6qyZ;y`rf5<exT{Vlp+jPBMJ6r$LXGosi3k)7%Xj2hkH8z54jZ<%)6)^T_=0SrO`BEsO2#1Otc(ltBn}yPW#DKjoI93vcLfP{ukPL=Yqwnk8k?8W6!!)T)QSu~v=aD5;+;>?Ht#~?7U}Jz5rfQsPb*DElviEW0mDN>q==Ous<nh$lkA>WU)duZl!0sd#ozp=(4w4W|bmZKr4rJKl)1<GI8$l0EF~bax$Qyx(#Arz>B21&WMAV9**s%w7Vani)W>FQpany6=y&WMK12W<j4Y3}KR&c)m+!&UPf%n3U2S?$9Th&FMu<A*9bKYMWBMZ0cwtGnn^6LC@zaPr&81H(c_#*oqp=tY|EX>IZ?J9|@%Kik`a&N6xtYQa*3t8d^EYN}Spu#T7{>4%<4h(|h7{mIe8rt~wEaRV+Eiw}thTv<@?8y7x``Uc0p<|pql~p{hLYxgRJVG_^An{ZWfxT2|N>3%BBSmPK$SoY0CaB>R&Emu^IrbEkKi923zCombb<N2m+-;mYZ%V`=+WfpG6KZmIXX7>#NnNtp-JQp`+or*_I4F|zsDjz{3?q1qvpj3=Hf^3(EVcP!RijtsqJ&8$qbvLZ(yEu$ESZ384SJ25Y5?N>zyJKd|K$ZBXwB1PH7<gUwRA~}ImrR*dl<Ej$56?T3MR931z;VC?Wcw&7j%VQRgJ`%TlZv?F5FUuO*eNA(yWfWi&7q35g6HT>Kn##ny{x5`SQf#83D5=-LSAD8PJ0L0~kBl;BA~4u=GnJk6~<5c?)gWotfy5)~Kj)*(bsd<2_sG<5NEJP>y4dKD2^bD0HOjCp|a7(f7%b&W`w?w`J&_e{ptp<;&ZIDtg1=n*(>o)!D`6!P$|OvFT)<izf)I{-U>pyfukUJ`+tp6D=t(ZoS?x&S;ucliQ&3gFj_q@Ta~1`1M_le~YB}_4?`d=ucTO!|!+Xum2XxFr>c?Pjyt9K;MgPejdpqV^KEoC^)LbQMx?KD17Se1S6`x45uLn(TbL_=L&>j2EYjX{j0N6bYXgZc(s3Z>WAy%VRTfKPwF8k1b+S1&fZtwj%)$`u2tmQy%#TAMSii1ym-0y^@~wE9$+UDN6S}}eOo0U4!W`Zyak5dk-%H0DlW(N?&y&h0@f_fBqzaF&N!X5Bi67csdsyzkD=$D9f94LrX<e;`}r)Q3w9Rg__-Lj;nTnarQ?@@=y`kYeiL;Xv^hb$QdXdW@fo*No2D9~Qn?|i(KSptnrxpA#h1wyss8V@rhu_CIs!i!#L2A)DJ+-ze+Z87u6`Q4n?4QS)nERbSlR=R{Z^s)>D!a5<CEhzhZYAXc)tx-5sCz@jwCEd{$#EEt|FnIKLKeN)hoU$U@8b|oPFV$ALt}Y8Q>RFgj7vkif%wPSOmM46t3nH1@M|KZR5r!T5d_&a+8jm5~Dha_yERr0cGQ1q1%=msPtM3^Q2td^}A(>h$aKQKy;fCMIbd9BErJ+Zwi@&TOXb&7y+uo#{~kmJmJlFkaz=AxIwmqJ=zg~Nt)0%F<H8B#m(iCB6uivqm#wWbl)SBUi1u*@2~Sbh3=?*zjHue8AM9lA)BVKw={PF@63DVt5k#T6GZYr5Kn;|@w0RYF#lIS`dgV5fdCv?cd-VZohoAzR;|)>!!5M&Fi{BC1_bLw#X!EV0)(+YcU;l?Rqi1$->(|T_jRmyb!Z6M&tMs^&vA0FWge3)>!E+Ne|&Oy;HxHv;_twGB1_yyjk*`G9V584;@ZA7r0uJ5?m22bCNvb^+>De@g?=Cdycxk^?1402AF{oR%wRP9VZS~!kWZ!Fz&x2xCdv19ugPS<(U3;+5v9SFwkYUX7^z3fgljS0qlo699yfSm8W>_JjflP`=&9?}k$E@L`8v_HlduMEpdxsP2~>#Cun&#aabx@CBV(Dk4vky*Kl1e0bS}rxnspi*1{$Z|ai_tu?NPR6A07|HA+rIv<E&=m(GOATdycc@wMJ+<t)J-ECO@WCsx8yX;=J~eqt)~vZ=Mc1Waw>68V$ucn`V06a8-cD(0q%IOZV{l6>L?+Ew5GR?wNn@c)Y^kP2od)uN!@kaSXA$(i6y7g?1o9<3&F)|LstOiZojB3ApB()!cdlkb9##_Yl|j=97Xu&!<MLKi0d&1vu$3V7w8EH{sM{d{o$nB!F);_z-c1#u_BE4MC#d;sA)rTJ&cN!AgKsrgnkicf`$r;F8g{-!!FE(5!gDpo)KQ5WvHpm^yPbAD-PCULFs=5#kzKQiB_b*t#5mTzAM$r#mXLf9hrE^=Ee+&|iclMdn)vMiadOgj}J5n4<AAq~6%S{PN!Eq(mYTi@`3b7;usTabM_R;i#kAisD$kzsaHK>NxJye(1wHV$lP|v&)~3&(A^n=qsu1ZJ<emZi3S-sZy*aP>^x#?)VLW`aAt{D(+$E4-b3uH0o<YX{-DhZsvou{ur_ay@&PA{6oYVyT!eEMkHZa^TsL87P)TXjXzDS4=%!R1^4QsZ_>9vpT<{ruqUiV*M(5U>F4&zsUELXqNm(kPB{+>gZK{q&X#1`Yf5vno7V8OToHSMiEXV~QysrDr@-tRdp8gqj~?1f>f6Zg7o&Sa{5h49b)vMxMUD%1w>35$3=NhzFn6Y*@q1P9Kex1QZstR4XSbEduIMn-JO99b{*xZ~4CGh)@na#Q(etALmW<GphW>%U^_P}>IPku-<+@R5y^h?=zFQC7x;-I3&jVaAx^4@t6jvqdg<av~CNEIYwbc9-WifK?_dwV&&JnHKd+NCqV0y@D=MN!d8#HCVF46J;7-(Ttp7}$QeU6BZi|I6`j@aXby%M%p_#Bff!=)WE+oJZcXJEBAjQ(&Hbv+_%^wC+T^{g=3B#py(PJ}i2(utck{)ri<F7nN?PWThP%Wiu%xSTC`;ySvE+mvQh?Ap>adGT$3#(H3YaP~?aW`YES+sT^4dh?YM_HAF*OS)?!Y?Jr$#@prHe2n*_t($Ig$mAuwj9++a-;fjMQC+!eci?>u^E2?i8Q@)*KMcIx7w|u%?Ly)%q<#gzzy8Xq`0&v2Jr-#9Ne|IRUg-WSY4L`+tGDr03fPB$#KetD0QUD~Mw0R*!M!urckVpCc(&)^6Lu6Gj;v(@uh8LqZu3QT9*C4>oC&X>C-H(e?dZeqxuX8*=98`WzmZXDfY+vJeAHjxIz8jHXF)N{=cB%LC@kk~1f)T|a~UBS*Fhf=+fI&-H(qz5=U@Le@|f`nHJxu|Nxm(kzCg3VeGfu=PouA94<QIMvl-r(qO&RM4xu9+4L7D>+Rwi~oj!!$32NimTrw`eiVF_P2xblV_uf~}Hy)Cie6|^nTJCK~4_-29vJWXe8;?88ciyy|kX!mZxkJf&SyXABp#t#?ACD?(C>{CEML_0WMGUUD<m}y79*aPgaVvzkafe8~jNxFg1_bwk3ok;qR_OnHa(o`2UmTvt;_X-0E3n-fmuGJ;ULB(Q*b2LEU$yx7&B5VcI+Yy)Y!}V_i^GFh#Jt{X3rDLeADvyC?w`c3UhiN0$cT5zb4~qMheyYUCkJ?xrbU}oy*)fRe1-9o58oVK{P<VhXlvu|!gw&4ri<ywcr8d|B5J%=c~&q?md<sQWN|p5DL4EK3bb*8A_606SnAjRp@17BMZ9j&hc*kepNN*U`sys-Iyq3h-fia8COmX?TqUH)n;y2Z(JB-=L1@#*pZ71`_y&7Zz&X6(*-!q~YJ-S6Ql@+8g0(9Cw*s`PD14AWBCsx(8<t9b>Jsgw2AvH|mKTmbgK{kB`n3W<Hv`Sv+Hd4J>uD+&c!BZgPg0ZKC=5FTdIJE|%;)V_e^8_G-xYr6nV+!hEz*7j)WYb|u_Rk0AuJ24=UrOsImp{2iet9J#qf)4;_*LoDJbW|0}4fjH{hydlJdhw^e(deWRBa!fHOaZJp9&rc%s)Bry^le331-XlQ2(;Y?h+g$}lv`2VmVX1X_oB`fxx$WT6iTTJN_Sjcob~sXmG}{5SCUf}AN}XW$*<<oL(^HwR*)+rNTMI6mEfb9{7od1ctK{2C905@{EK+PkLD2ZmdNDNfKUgyt1UWrjZj|BJtFe=*<wV(NYIdhd(Vy)Q0()49WZ5MIOXz6oy`WuS!oX}#dyh|Inxw+zp29(pKyZ7)?3G@9&jnVR{Lg)tCNBAc><?e)h^%h1uzjM2dXEi#O!N!C!%VUl`@ta0&E@=V9zKr?bvW#c7>R<ZYOeScYB|E#V1pEWw*dPxpR7<J<Vg<+?Vl8dy;5H)nQ@T#PEk4={g^w1_A+HQ*O;B1T6U*wfHj6;){2ZQ={NR2m*DI^yjIdNa`vN#`bRQyiF7#Jf8z3QG$yVV1hinrO$F3j$AljXV4Ez_F&(#UP7oaxtG@IDVH{;;<0&}IsKt*Lpbvy;1#)#ymN6Lq*QsfhNWl3XY8zh45envcGTwYLG|7jK5pNd|6q#)>26OmW?q1LIG_qHBEO24sAaR7>C5Sf)Q&MKu?WHc4SAQ_wTMMGSW>2pJ8sAcYC0%;#G#D_T-B7PZ7+UDr^62bRB?Dq*Kdt=DKwi^}wnmBUO%xZ4u32%u+QrWnWzF9UITWx&@@T31U3-Mb?A{Ib}n@ONtyq;c)qp#|Jg&wF(pzO-k)M1>{|i<g<1*BTo<d-lCwrNN~wJ33!^yQk5_n>+kYlrXX4^GY*%Dx6;1Dg+%rJkDuNEhBtzV9f*A#sb{<0sHQQaqFLkvwY#?^Kil$j>`@_{o2})`yD!}vn<Llz6JdS=<N&q$1bws`R(;jZyV3+s%aQ_JuD2yK3wxe<L~T-XSt%Ze5shP)NEE-_2}1@@x-0F7qHIN>UZ^|((zNI_E8XHL+6|z-0+<-Db7HVX^JZjw=9rfFeX<Jn(vLF0=V*BH0vES%WGJ^Sho31RN*l!n<gJ1@mhustJ(Fp*i=H@&^t!Hr$<<{pVTAFT%IwTIC8M#*}dthAs~hid$x0j-&GjIc|ptnPoA&0-Lka&KTs%$#oEy*x<hKf(_jQ5D|D6dGRr|MuWn*`qW~Yc2SSE#`i%Cgn<dJC=aeZuSn)S*Chk(|ECg_n=g%n{)7w7gGdfSiDg5~)J6G462n+^LLBt4h;BRlsH^!0)L*|_aS${f9pi9H+5r&@67xJ;O%Y&n5r)MYl|MO>;r^nB5`=A%dU=9{3@5bSpR+TuiL9=WElruqc^Q_GA{WXeSn$UX~Yue)}^#@XV6%ms}3&I}(pZU~rD0(0*P~t;PZYaXvON76PUaYPtg6(Y^vG|Mus6n6tX&10s-9E+x-G)I>kt*xY08*6O`t|C^SDz=Jtok$@6fQ;%#*1~$+YecP9tv$3T{OPk00upb?W(-{a%FAfv20iE=R2zxKuXfEtKRdMFLqZGv-E)ZyqRZ>qPL=8Xk1@j??^ym1u!3sty@V16n;@`*~I5E8K4$w&}m198%Fd4lWGDRwzhObbO_q6l*pEcbeRFG3ucWGbZ&=~V7@HhjwCwt<tij&DVG;1u^A(i&8E24x3pKCBM|S9j0gyZvSD4u`q_<6ghwO%qpnz##*6Wu72=LN)bpl%Pp~-)upP|J>%<+?4fKS4(=n>dqU;r`7Xas(&Kibq31`}G!Yc~qO!YbNlnL4HhkPjBp?ip(SNqS{QmlHOfk=i94rptX&xBGFv<bq7gQfvi&lqWb(M}5iPJu?o_D~l#*ezOJs=&Q*Sl`v+If0J<(OSzf!<+fIo6DVkVK|_v#{r-gKDF3xu<aGjp{}sjvf`(Ym-C=yn%1^yw+b9?q8&5hE9~<v<BY|Cc5#I&B>6E2U`LQBt=@!X93yjzV-X#gW$Vj3)N~I&Wq832W)mR)e|n*{1O', 'ligand_prep_gui': 'c-pNz?Q+{VlK=e_IBunmnvrSAb{wy&bXA_j*~v~4dt+awuCgf>EJ6~;{2GF^tjoD-AL5?j9&DfFy755*B=q6Q`iDf3=x%hQzXAGB|8`XK^5`zkj#&0UigmTjvy%hQ^FHR;VZ~<4ES}MX+}@Kot5`XwGe+ilNj|@ium7DBT1RokB9g=lnnj02$qHK1D$X-9%S#pjqJx8ZnWrQS=XF(=EDTAU7I|3_nq_$<#`1#$eXm>q0?s5%L@PQ=DCdkfKs<_Pl^*^Z&oh0Ua|u+?YMI1$8sHj!>LI_^tY-QLUvqs~ElWnDI9oI~;<Oo8-3!ivGF(a$`j#3oj}sQfG|3l3k}}Teg5BkhLsG$b2_VH2qIg1-i-z<M2>gAx`1tPa<;`vQ*PE-4LviaGMqU*{HuA>j%TG7&^ix{pX*>&8CCEOk*kdJcN3393#Io5s1aQDFZ_7ntA<ye_#sJ^o;Nalm`Z`oN$&`5GU=)mCsSbp=$$K$hoWx)L^W8)tpTio)SzLvo&sj1bk}}V$2?!&&y&sY#0Oa#|h~l3RUX_T}8%SXMLzn<T-~oQw4@__v0Pwzb3serU*)VZd)RlP5Cm>>8eF3nq0R82wJ&--Htb#FO{e!>ZCyX+F`5nxwyu4@Sq*aXIR$P()Az&8>j9(qr7_XCxOY+Sl<TR+_Dq;TIL!(i$6)UVw<(sh@PX?C)c){|NRpr|E#-sDm<N5KZJ0guU9{)G<|2!HE$*a+5aA40YuPYSP1I0Cg<+`a#VCge0{Rf)VY>L80GYMv^$RCg+;yomB5gJOXCh843aw?Xav3jq9)9#8DWnSf(z_kVNBKoc7m2fk~&&0n1ttLOwJC=|%k61G3Vx5<Ck-`eMD1XZHgwd?Ud0W=3169!)%!rlGgG%XR*oW+~(BqtgzhL?EX?5Xxl+HaT6s;KF0yRGCg3a;_1iqasOZ6mMj73`kj?YfVU7-AdmC|=@7ROtf@UA>~G=H7|wFlV@bO$&5o&y^67LQgn->R{Zhyon_6ce%G=EJ-9mp2dumY}_}Wu9}UY@Vrbz=N(}!n-<7qOgv;{z#ZPodaHfj7Ba;7kQF|(zhv-7f!lCf};!v3^A+BB?Ir#n%<T)WqyMnrV5c{>ixQ;7!hMmqMUJW2mv*EoSuvC_4I6D;|mHpyZ3?jWa>S32m5ewY6w$P_M1Bmo}qP1%)}mrf8J|w!l2kNvl)co#Uc9SwGt<}e)H4cZq+iZVu%@(lnkP6#3G1Q5E~(zxJwv8=RQyJm55UH43iQvL$#=jA@TY|a}kFj3F0)V08yI5suQFL-iZodh2CdK;4v%FyFD<XeZ-M8U?MGYNKW36#?rWx9Lrd_SQBvSaT;^sD~IF*WB0j;`=nYI!1~c_3Aqw*iu3rrrb%3_LCx6go(HIBm?c4826s}Cz)AY>1uI1|uv%c`A!e(<p25Ig2jnfDucuzZ<`t~&s-#82vPHF=jz`C%cJM&z0nI?u%c-~W%orr{j@^nk4s>i(naUR3lOs&!yUVL(7vQu9uqfjQGO(mhGhBvv0gLa0L9JN4SXR^VegI<=pn(vY7xFk#yec*Yo`GYO!0ng$Y6=sOB=8C(KD!5zXPm7xLpa4Vmm#&-v=na|od#EgNs+P$|K`nG(4(vO;^TOT4r)kV-+YE}+Fv|#w%|}Ih}zubs-^25>u?L;4uI;3&Bae*xNm}LMjD^$p>)y|6k{rMhDK2+9;kWaER=@si~AEAF+(@X&`i1%gpIRJMAVv`?n~@7_?EIu0v%4dn+=)YAX2fE(uUv)>I-Y_mr@;H4HZwAC`~;ej|D-r5uw9?*kgf{l+m;WOZQT4W0*_3#~ZZ!Y)D2f?KaRg>Mg=5`R70WmtZ1ZFjVpk9&0b1tRZnsz`cWuyIVsH$Y7$|R9r@QNeO94{%+yQrmsXi9!WO{EWiYSg&Oh(SMp(?+%9Hq9WVEn!sR1P!4XdgdHwo|unLlwJOQlp#nk)LOY!GzbIGzI*zJ;!19ByXZgIsD*Va71HkHc^s~HI<2|;2NV`!ds$`zOGwInP}?VF-W0E|#(V4xZi>l>qZ7)pqZ2Cvn$<y;o%yTy1CSmhp&i?@e2g?V40Vx=Ta43a5Q(rm%}Gb8geQ91*f{M|-163-2U-@tB9hUDcFVUUy)v%YMURH4@#-(qr7L4pKoxIN6RJeP8q*lg{PB_~WZjvxy;AMEfmt&=$&lCd*}cBcL=&s5swp8N5JxdXn}d3u+lYj#QA$&6hO4`rG*^)Ro^vt;dQK2J{V#7xv3eCqG6l_AFj-Q%ppcqcP4nL0{Z-oQ-a9PFOxD-PC%znqe_>;ff$nW&6|TZA$7eqpR2iO6ItNLV2Ii)TdF^TaPzoQBMrAI<U_D=P#?wrok7JpdO&V^jCGGUW8cCO;h(ZYa!9_1GfJ?;+7@5*K@ts(@9~vgBgV@np|Awwxa9Ior#uhROpLzNt|9(=_`Vh6s=MFkh!deV~tVTBn{9mtm{ynXaJQi_yk%<|K5yr&HKVcr~mHo5k}OmRweNqSAtba@}9`riHU<;g8LQZzpN2?stj!^!r5I&VRdrU+(D}wlP4eylSge%<e>!*W~NOt%lkzPJ6byCzHBkrkQ-@q&a?`>RaW$;755~7w+RfzD`#6ZaW7j-xC}^F$h^vJ&UoCg3UiSC*PrQx}&I>7>}G3UjBhV)aNC^?W~kmvt^tuR3^)b+~Zkd+)1@-mzf)9RRtsaF4JmhZZh-JXU8Ci2Y}41*RQlQy=~#w5rVPK=JgB`Qa-PfHj*hDta2fWltLmX_AgYoP3)fZ<Y07M?Y>gGhNsVta>k0%nUQjLvh6{4)YkO*Wp8Uj?vhEVsdlkLf(o~m-u0);>x)m9<o&z9Tzq_U161y?1{<Hhq9?CZMYdXkVt7pjdEBW!K+t7nZnHR6-7&@Qsf{{J2z7y#&J*4*jo?uz9&Ij+&U-%BO-E#>xh^OzIypSrS%95)v_WmTg>zJd-DTJ(Ib5SV>uZ9AaF43pS&b>3hWYrO+&RD`T;|^5N<;v-ka;*>Re8x#P<UNLcfa>qKzd@bgFO}1#%;+&3)i=1-PqJreS=vo!R)-H+{xsvBL2B0q8|e4Z<e}i4kp0Njb`T6XwY(mPh{T~o{V40M}kESgDjqnI;~~RJq~)U1#u>z8)@LP+g3DZF9(f$@X@t)Rig7Rz)dPoj{0~=e6e3HgUbM`Tg`d^Mw)WJQ#SXdA1HvPXco$aAA?<x5~8iPMSv5ZL$a|oWuw@;VJFsVw@qA^`2r~PjKXZ43sl=TdcdilJ9}3G)*0uUJvEDWn@mR(NxtZ{=oA5^(x<vPx5`V@M^#TpP|*YBXcIzryZXd%H@LIbG@iRVYqG;WH4cIVl;5LE!#mi3<aQ7d2LhU=l!~a$Zq!lRw)bqK!F$!ZfXe?%FRX*D)dimVXpZB^+*vr4AF%c$_z53rp2*K*ypzWA6Iu8nnDGbrtR5?`W3Q6LMUphNEg=1&JL>Du5xnlRe1#G9TaH>(ErSeF)fwf?*Ei@L$8TS5zRGR}p8ANh-boMJs`V%_C);uXC)inq-qK0N-h-Tz-sCib0m<?Ti3mO>J*kM>xGUjrMlt9?b@>Wtfv0y`5I02Ix{ou?%F6ecaJ(&8qps#IMpt9?&Ibqwk@+3mv$~Wc!1MY8yU`eD5qlJUMg~bQXOXXwbzEn}k{*{|1oYQ~EqnnOtC%ka8r&EgCJtt7QHrtt#!U}J0g`YbJd=po2<}<A=pFaWJc>);K8LCX4@bdmxY2E72MbpD1Kg3b&)N*Eyj~J;#2*6@R3N?_XH45jp1PA(=c$mS@0`>ikO8CyZSt+@pw<g@W{)7XUSw=fx&@eE#880xp4=^H+w9&g)DF3MlPoD0sP7maj1U|85m~d!JPjdpG4O?LE(~Sk#9^|T$o!_n%OEG{mpWW#*SKOnioSEY1OHfpCDj^CH=z|4(E?pWOJHdO%7U)4q(F1O4nJP~dhzadh{pt2=C$7&sd4rUq>s_!P$M?39mv_^j1?8R6kk}Yf|%jn)-_{gnU|1$<#iH?HOboqy<I~j2AIr97^)glY8yHH5A(p{<iK7+^I4}EEOim{k?9r<g?PN2&Xb%fKP9&S^g|1y*-)2zpoMCFdrjrsX}U{1QcpOZ8}XZlxi^qI9$vBR1mb(fics~fL*0AsccLY38<goLV$-|i{kE$DBxZ|~PvcBUpxgO$%AzGCJ9sfSh_y{UlaxKsBG(1z5NmsAT`=8OYZkL@h_yql{*{wJiJgTs#P(1Nrkh0#?xqjpXv=6u<qgP(tfqW-sRkm7QwSIk;j9qR6vWOrB#vsyoi!iBsK{%v!{oWnbk#+K3lv8Xksy|E!vpsmo;=eF&b)Wd*Z-He0d@FButw^PKF~P9tl4q_oBfz89`sK)SwzI~Ew7(vim2f@QVz;AyC<;%4E~<|J@d$q#DlNkw>-}Lx%cg!t)C|3o7f<G@<hf0w}x`ZOr|X;GF|O;w9GusA`TO{szJvJn@L0niGeyHjkSe1X4ch`rtoO@U{$FiwQggfVrPB0E~4@bO1O**$T6fiHi3h|_$ukyb3R7t)Nt7ASoMw?&dqbw;*6T{JBWD*hV{U@DMcsbtD<DuKTm<Sif7h6nZg~8XI?LL>1Ksu7UF?G6exjhRpJ#bGc5JJkGVdyi6pUQN-F|cChl5hOcq)qFKiEhS_9Ov6+Ei)+&rf}Wgt&|>d^bI3H_q;S2zzR^o`!NMvlg$vW*?Jx82uJIr$HcN3hu8Y#Ap}$*f|ef9ih2p<R(QV<)P_=DjYC4W|G3kN-3E$IuzGJTmSZjTW>Asn%Ux>aC>FVFbjT*E0IP692wjH}$Gj?;3OYI#e1xY&!c+RE6sFOcR>kMO6Ey_Wg(e%Lm^p+K!NLEsj3GhT7CZGt2RWlIZ;@o}2k~Q{sKp*G)udv8k%vS09uEn)cr0@GEgbWhw^@NkpMq&Qxa?i;AiD`Te`=_C=WH6$lprnLV0mf_gbe?T6?WW;%kHn5nVtJ{u3#eG8`dpvhfazLbotO0Z)ms8MoGGBAqS^{Om+U)huHg?#g_enD6G>&2&!_<i%syX))AH{O$;qk>Y&ylC3?R}?%2m}JfD9Ns8d9awse8&RV|ND)QepijhVujtAN9Y>yE2r{&>plhfyqJ9%x^bWA`=1qvui%{<Ogg?W_)!Vn79LD2#8i0n_A3>d&ka4&9E$iNpVkaBlHp6f<#|z(k@n458(!&=KdGYh)#fQm@n{Ja$w!o$J1GxC^j7Vt~&#^Yahn`45e7*k}7-bhZvfn-%7;<rS(tB^7`EA{1y+JV)@8$(jofh0zavh4^5!6Y?{WL|XYXUCb^svH|AQg-G@|iZ&i4N+j-^m&p7SL2odP`;ZW`N4a`YEhRP2ekzBk_ur>}d79sXoi)^xBs34V#}LW`yXc+|C{nVFMBh45a;ZWZx7As-C=#jjQ{r@;&r+5txgFHI&;qlOLl$h)@CG-VbQeE)*{J;)qillY1y_AjcI+Rh{~_hr{;I+Y89o-gs^g+2T?8;buI-J?_GycHf;ywz}FKc+nui$AC=&>e1#5(;6p}Ognn@0{HV%Pl*z%qPfv);;c!+njH&q+yGA*Km`YA%y%KxzR%oyE4%@VV2Bdj6RAatDR+B(4$kMBUYRHPDv*5HrCBc+pjF^WC<BX(7hyp6T9Hh8FD8*6aT??XPbhwC2R=3Ax1X6X2)Xi9dn2(Go#X!2w7XYFVuM-nykE`pzLzJHxstsUsz#?X#b-7LTm+1)QKD?4fbq6lx7_S$^lFKv7$$T5bU>icimtLrEHSctMPsv-VhBzQ`!f0}Y`RI1Cr(G^T2u)?{yNwUAr^V_IMJoHrqPIM%QST8)Od#q#qnMgWOls;{qq!Xmynzar)=|&3vOq>t543;Vlwe5PbW?IGA*i($`zFJeVa!+-sC($eV1=>LQD<CKSXG%OZf}*SO2So;G$gA*l@m<<8YUH$&$i+g;oNIH>ao??R$rZ_?q{j>a!_d54;0)3hsWY-?vw(nZ%)Hhpx>BR1Z^p5nk*7#F<L);Wjwfu+H?pZ=aPwT!dl(KHvhEA}9YvfcUop${MYIN8roj3ud-CMHGSg(z<%uVhnJ`NuC$J#ncG+iSZvBU@8@cLhZv4$A+QO{F26yblj|Y#nQ`1@DPG`s2cts{lT);'}

def _vlip_load_embedded(name):
    packed = _EMBEDDED_VLIP_MODULES[name]
    source = _vlip_zlib.decompress(_vlip_b64.b85decode(packed.encode("ascii"))).decode("utf-8")
    module = _vlip_types.ModuleType(name)
    module.__file__ = _vlip_os.path.abspath(__file__)
    module.__package__ = ""
    _vlip_sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    _vlip_install_embedded_audit_hooks(name, module)
    return module


def _vlip_set_window_dark_titlebar(window, dark):
    """Best-effort dark title bar support for VLiP-owned windows on Windows."""
    if _vlip_os.name != "nt":
        return
    try:
        import ctypes as _vlip_ctypes
        window.update_idletasks()
        hwnd = int(window.winfo_id())
        parent_hwnd = int(_vlip_ctypes.windll.user32.GetParent(hwnd))
        if parent_hwnd:
            hwnd = parent_hwnd
        enabled = _vlip_ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):
            result = _vlip_ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, _vlip_ctypes.byref(enabled), _vlip_ctypes.sizeof(enabled)
            )
            if result == 0:
                break
    except Exception:
        pass


def _vlip_write_run_marker(folder, kind, graphs=None):
    """Write a portable, local run marker. Optional presentation output must not stop a run."""
    import html
    import json
    import warnings
    import uuid
    from pathlib import Path
    from datetime import datetime
    from urllib.parse import quote
    try:
        root = Path(folder)
        if not root.is_dir():
            return
        marker = root / 'VLIP_RUN.html'
        inventory = root / 'VLIP_RUN.json'
        previous = {}
        known = []
        if inventory.is_file():
            try:
                previous = json.loads(inventory.read_text(encoding='utf-8'))
                if not isinstance(previous, dict) or previous.get('format') != 'vlip.run':
                    previous = {}
                known = previous.get('graphs', [])
                if not isinstance(known, list):
                    known = []
            except (ValueError, OSError):
                known = []
        for graph in graphs or []:
            relative = Path(graph).resolve().relative_to(root.resolve()).as_posix()
            if relative not in known:
                known.append(relative)
        valid = []
        for relative in known:
            if not isinstance(relative, str):
                continue
            candidate = (root / relative).resolve()
            if candidate.is_relative_to(root.resolve()) and candidate.is_file():
                valid.append(relative)
        now = datetime.now().astimezone().isoformat(timespec='seconds')
        records = [str(p.relative_to(root).as_posix()) for p in (
            root / 'analysis' / 'analysis_manifest.json', root / 'vlip_prepared.json',
            root / 'vlip_run_settings.json', root / 'VLiP_COMPLETE_SETTINGS_USED.txt',
            root / 'vlip_project.json') if p.is_file()]
        data = dict(format='vlip.run', schema_version=1,
                    run_id=previous.get('run_id') or str(uuid.uuid4()),
                    created_at=previous.get('created_at') or now, updated_at=now,
                    application='VLIP', application_version='2.0.0',
                    run_type='docking',
                    folder_name=root.name, path_base='marker_directory',
                    graphs=valid, records=records,
                    graph_data=[str(Path(p).with_suffix(ext).as_posix()) for p in valid
                                for ext in ('.xvg', '.csv') if (root / Path(p).with_suffix(ext)).is_file()],
                    completion_status='see_run_records')
        temporary = inventory.with_name(inventory.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(data, indent=2), encoding='utf-8')
            temporary.replace(inventory)
        finally:
            if temporary.exists():
                temporary.unlink()
        links = ''.join('<li><a href="' + quote(p, safe='/') + '">' + html.escape(p) + '</a></li>' for p in valid)
        marker.write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8"><title>VLIP run</title>'
            '<style>body{background:#0c1523;color:#edf3fa;font:16px Segoe UI,sans-serif;max-width:900px;margin:48px auto;padding:24px}'
            'a{color:#76beff}li{margin:12px 0}small{color:#a5b4c7}</style>'
            '<h1>VLIP · ' + html.escape(kind) + '</h1><p>Folder: <strong>' + html.escape(root.name) + '</strong></p>'
            '<p>This folder contains VLIP run outputs. This marker does not indicate that the run completed successfully.</p>'
            '<h2>Graphs exported by VLIP</h2>' + ('<ul>' + links + '</ul>' if links else '<p>No graphs have been registered yet.</p>') +
            '<p>Graph links are relative to this folder, so they remain usable when the complete folder is moved.</p>'
            '<small>Marker updated by VLIP v0.0.0.22 · ' + datetime.now().isoformat(timespec='seconds') + '</small></html>',
            encoding='utf-8')
    except Exception as exc:
        warnings.warn('VLIP folder marker could not be updated: ' + str(exc), RuntimeWarning)


def _vlip_set_simple_visibility(items, simple):
    """Hide presentation-only widgets and restore their original geometry/order."""
    for widget, manager, options, siblings in reversed(items):
        if simple:
            if manager == 'pack':
                widget.pack_forget()
            else:
                widget.grid_remove()
        elif manager == 'pack':
            restored = dict(options)
            for sibling in siblings:
                if sibling.winfo_manager() == 'pack':
                    restored['before'] = sibling
                    break
            widget.pack(**restored)
        else:
            widget.grid(**options)


def _vlip_capture_visibility(widgets):
    items = []
    for widget in widgets:
        manager = widget.winfo_manager()
        if manager == 'pack':
            siblings = list(widget.master.pack_slaves())
            items.append((widget, manager, widget.pack_info(), siblings[siblings.index(widget)+1:]))
        elif manager == 'grid':
            items.append((widget, manager, widget.grid_info(), []))
    return items


def _vlip_polish_styles(style, bg, panel, field, fg, accent, select):
    """Shared presentation settings; no changes to application commands or data."""
    style.configure(".", font=("Segoe UI", 9))
    style.configure("TButton", padding=(10, 5), borderwidth=1, relief="flat")
    style.map("TButton", background=[("disabled", panel), ("pressed", select), ("active", accent)],
              foreground=[("disabled", "#8794a5"), ("!disabled", fg)])
    style.configure("TLabelframe", background=bg, bordercolor=panel, relief="solid", borderwidth=1)
    style.configure("TLabelframe.Label", background=bg, foreground=fg, font=("Segoe UI", 10, "bold"))
    style.configure("Section.TLabelframe", padding=8)
    style.configure("TNotebook.Tab", padding=(12, 6))
    style.configure("Treeview", rowheight=27)
    style.configure("Treeview.Heading", padding=(6, 5), font=("Segoe UI", 9, "bold"))
    style.configure("TProgressbar", background=select, troughcolor=field, bordercolor=field,
                    lightcolor=select, darkcolor=select, thickness=16)
    style.configure("TEntry", padding=4, insertcolor=fg)
    style.configure("TCombobox", padding=4, arrowcolor=fg)
    style.configure("TCheckbutton", background=bg, foreground=fg)
    style.map("TCheckbutton", background=[("active", bg)], foreground=[("disabled", "#8794a5")])
    style.configure("TRadiobutton", background=bg, foreground=fg)
    style.map("TRadiobutton", background=[("active", bg)])
    style.configure("Status.TLabel", background=panel, foreground=fg, padding=(10, 6))
    style.configure("Metric.TFrame", background=panel)
    style.configure("Metric.TLabel", background=panel, foreground=fg, padding=(6, 3))
    style.configure("MetricValue.TLabel", background=panel, foreground=fg, font=("Segoe UI", 14, "bold"), padding=(6, 4))
    style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
    style.configure("SubTitle.TLabel", font=("Segoe UI", 10))
    style.configure("Big.TButton", padding=(12, 8))


def _vlip_install_standalone_theme(initial_dark=False, follow_settings=False):
    """Theme separately launched VLiP tools and keep them in sync with the main app."""
    import json as _vlip_json
    import tkinter as _vlip_tk
    from tkinter import ttk as _vlip_ttk

    original_tk_init = _vlip_tk.Tk.__init__
    settings_file = _vlip_os.path.join(
        _vlip_os.path.dirname(_vlip_os.path.abspath(__file__)),
        "vina_batch_settings.json",
    )

    def palette(dark):
        return {
            "background": "#0c1523" if dark else "#f0f0f0",
            "panel": "#172438" if dark else "#f0f0f0",
            "field": "#101c2c" if dark else "#ffffff",
            "foreground": "#edf3fa" if dark else "#111111",
            "accent": "#263e59" if dark else "#d9e7f5",
            "select": "#287fc1" if dark else "#0078d7",
        }

    def recolor(widget, colors):
        bg = colors["background"]
        panel = colors["panel"]
        field = colors["field"]
        fg = colors["foreground"]
        accent = colors["accent"]
        select = colors["select"]
        try:
            if isinstance(widget, (_vlip_tk.Tk, _vlip_tk.Toplevel, _vlip_tk.Frame, _vlip_tk.PanedWindow)):
                widget.configure(bg=bg)
            elif isinstance(widget, _vlip_tk.LabelFrame):
                widget.configure(bg=bg, fg=fg, relief="groove", borderwidth=1, font=("Segoe UI", 9, "bold"))
            elif isinstance(widget, (_vlip_tk.Label, _vlip_tk.Message)):
                widget.configure(bg=bg, fg=fg)
            elif isinstance(widget, _vlip_tk.Button):
                widget.configure(bg=panel, fg=fg, activebackground=accent, activeforeground=fg,
                                 relief="flat", borderwidth=1, padx=8, pady=4,
                                 highlightthickness=1, highlightbackground=accent, highlightcolor=select,
                                 disabledforeground="#8794a5")
            elif isinstance(widget, (_vlip_tk.Checkbutton, _vlip_tk.Radiobutton)):
                widget.configure(
                    bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                    selectcolor=field,
                )
            elif isinstance(widget, (_vlip_tk.Text, _vlip_tk.Entry, _vlip_tk.Listbox, _vlip_tk.Spinbox)):
                widget.configure(
                    bg=field, fg=fg, insertbackground=fg,
                    selectbackground=select, selectforeground="#ffffff",
                )
            elif isinstance(widget, _vlip_tk.Scale):
                widget.configure(
                    bg=bg, fg=fg, activebackground=accent, troughcolor=field,
                    highlightbackground=bg,
                )
            elif isinstance(widget, _vlip_tk.Scrollbar):
                widget.configure(bg=panel, activebackground=accent, troughcolor=bg)
            elif isinstance(widget, _vlip_tk.Canvas):
                widget.configure(bg=bg, highlightbackground=panel)
            elif isinstance(widget, _vlip_tk.Menu):
                widget.configure(bg=panel, fg=fg, activebackground=accent, activeforeground=fg,
                                 relief="flat", borderwidth=1, padx=8, pady=4,
                                 highlightthickness=1, highlightbackground=accent, highlightcolor=select,
                                 disabledforeground="#8794a5")
        except (_vlip_tk.TclError, AttributeError):
            pass
        try:
            for child in widget.winfo_children():
                recolor(child, colors)
        except Exception:
            pass

    def apply(root, dark):
        colors = palette(bool(dark))
        root._vlip_dark_mode = bool(dark)
        for pattern, value in (
            ("*Background", colors["background"]),
            ("*Foreground", colors["foreground"]),
            ("*insertBackground", colors["foreground"]),
            ("*selectBackground", colors["select"]),
            ("*selectForeground", "#ffffff"),
        ):
            try:
                root.option_add(pattern, value, "userDefault")
            except Exception:
                pass

        style = _vlip_ttk.Style(root)
        if not hasattr(root, "_vlip_base_ttk_theme"):
            root._vlip_base_ttk_theme = style.theme_use()
        try:
            target_theme = "clam" if dark else root._vlip_base_ttk_theme
            if target_theme in style.theme_names():
                style.theme_use(target_theme)
        except Exception:
            pass
        bg = colors["background"]
        panel = colors["panel"]
        field = colors["field"]
        fg = colors["foreground"]
        accent = colors["accent"]
        select = colors["select"]
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background=panel, foreground=fg)
        style.map("TButton", background=[("active", accent)])
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)])
        style.configure("Treeview", background=field, fieldbackground=field, foreground=fg)
        style.map("Treeview", background=[("selected", select)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=panel, foreground=fg)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background=panel, foreground=fg)
        style.map("TNotebook.Tab", background=[("selected", accent)])
        style.configure("TProgressbar", background=select, troughcolor=field)
        _vlip_polish_styles(style, bg, panel, field, fg, accent, select)
        recolor(root, colors)
        for child in [root] + list(root.winfo_children()):
            if isinstance(child, (_vlip_tk.Tk, _vlip_tk.Toplevel)):
                _vlip_set_window_dark_titlebar(child, dark)

    def patched_tk_init(root, *args, **kwargs):
        original_tk_init(root, *args, **kwargs)
        root._vlip_dark_mode = bool(initial_dark)

        def mapped(event):
            if isinstance(event.widget, (_vlip_tk.Tk, _vlip_tk.Toplevel)):
                try:
                    event.widget.after_idle(lambda w=event.widget: recolor(w, palette(root._vlip_dark_mode)))
                    event.widget.after_idle(
                        lambda w=event.widget: _vlip_set_window_dark_titlebar(w, root._vlip_dark_mode)
                    )
                except Exception:
                    pass

        root.bind_all("<Map>", mapped, add="+")
        apply(root, initial_dark)
        root.after_idle(lambda: apply(root, root._vlip_dark_mode))

        if follow_settings:
            def poll_theme():
                try:
                    with open(settings_file, "r", encoding="utf-8", errors="replace") as source:
                        dark = bool(_vlip_json.load(source).get("night_mode", False))
                    if dark != root._vlip_dark_mode:
                        apply(root, dark)
                except Exception:
                    pass
                try:
                    root.after(750, poll_theme)
                except Exception:
                    pass

            root.after(750, poll_theme)

    _vlip_tk.Tk.__init__ = patched_tk_init


def _vlip_special_mode_dispatch():
    modes = ("--cleaner-gui", "--cleaner-core", "--pdbqt-prep-gui", "--meeko-wrapper", "--ligand-prep-gui", "--ligand-prep-core", "--single-file-self-test")
    mode = next((item for item in modes if item in _vlip_sys.argv), None)
    if mode is None:
        return False
    while mode in _vlip_sys.argv:
        _vlip_sys.argv.remove(mode)

    initial_dark = "--night-mode" in _vlip_sys.argv
    follow_theme = "--vlip-follow-theme" in _vlip_sys.argv
    while "--night-mode" in _vlip_sys.argv:
        _vlip_sys.argv.remove("--night-mode")
    while "--vlip-follow-theme" in _vlip_sys.argv:
        _vlip_sys.argv.remove("--vlip-follow-theme")
    if mode in ("--cleaner-gui", "--pdbqt-prep-gui", "--ligand-prep-gui") and (initial_dark or follow_theme):
        _vlip_install_standalone_theme(initial_dark=initial_dark, follow_settings=follow_theme)

    if mode == "--cleaner-core":
        _vlip_load_embedded("debug_trace")
        module = _vlip_load_embedded("receptor_cleaner_core")
        raise SystemExit(module.main())

    if mode == "--cleaner-gui":
        module = _vlip_load_embedded("receptor_cleaner_gui")
        raise SystemExit(module.main())

    if mode == "--pdbqt-prep-gui":
        _vlip_load_embedded("receptor_prep_core")
        module = _vlip_load_embedded("receptor_prep_gui")
        raise SystemExit(module.main())

    if mode == "--ligand-prep-core":
        module = _vlip_load_embedded("ligand_prep_core")
        raise SystemExit(module.main())

    if mode == "--ligand-prep-gui":
        _vlip_load_embedded("ligand_prep_core")
        module = _vlip_load_embedded("ligand_prep_gui")
        raise SystemExit(module.main())

    if mode == "--meeko-wrapper":
        module = _vlip_load_embedded("meeko_receptor_wrapper")
        raise SystemExit(module.main())


    if mode == "--single-file-self-test":
        import json as _json
        report = {
            "vlip_version": "2.0.0",
            "release": "Docking / PLIP",
        }
        try:
            _vlip_load_embedded("debug_trace")
            report["debug_trace"] = "OK"
            cc = _vlip_load_embedded("receptor_cleaner_core")
            report["cleaner_core"] = getattr(cc, "VERSION", getattr(cc, "APP_VERSION", "OK"))
            cg = _vlip_load_embedded("receptor_cleaner_gui")
            report["cleaner_gui"] = getattr(cg, "APP_VERSION", "OK")
            pc = _vlip_load_embedded("receptor_prep_core")
            report["prep_core"] = getattr(pc, "VERSION", "OK")
            pg = _vlip_load_embedded("receptor_prep_gui")
            report["prep_gui"] = "OK" if hasattr(pg, "BulkPrepGUI") else "MISSING"
            mw = _vlip_load_embedded("meeko_receptor_wrapper")
            report["meeko_wrapper"] = "OK" if hasattr(mw, "main") else "MISSING"
            lc = _vlip_load_embedded("ligand_prep_core")
            report["ligand_prep_core"] = getattr(lc, "VERSION", "OK")
            lg = _vlip_load_embedded("ligand_prep_gui")
            report["ligand_prep_gui"] = "OK" if hasattr(lg, "LigandPrepGUI") else "MISSING"
            report["single_file"] = _vlip_os.path.abspath(__file__)
            print(_json.dumps(report, indent=2))
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as exc:
            report["error"] = repr(exc)
            print(_json.dumps(report, indent=2))
            raise SystemExit(1)

    return True

_vlip_special_mode_dispatch()

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import os
import hashlib
import json
import shutil
import tempfile
try:
    import matplotlib.pyplot as plt
except Exception:
    plt = None
from itertools import combinations
import time
import sys
import argparse
import traceback
import re
import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import queue
import urllib.request
import urllib.error
import zipfile
import tarfile
import platform
import csv
import html
import math
import fnmatch
import ctypes
import webbrowser

# Optional overrides are deliberately absent by default, preserving executable defaults.
VINA_OPTION_SPECS = {
    "num_modes": ("Maximum output poses / modes", "int", 1),
    "energy_range": ("Energy range (kcal/mol)", "float", 0),
    "min_rmsd": ("Minimum pose RMSD (Angstrom)", "float", 0),
    "max_evals": ("Maximum evaluations (0 = automatic)", "int", 0),
    "cpu": ("CPU threads (0 = automatic)", "int", 0),
    "seed": ("Random seed (0 = automatic)", "int", -2147483648),
    "spacing": ("Grid spacing (Angstrom)", "positive", 0),
    "no_refine": ("Disable explicit-atom refinement", "bool", 0),
    "force_even_voxels": ("Force even grid voxel counts", "bool", 0),
}

def normalize_vina_options(values):
    import math
    result = {}
    for key, raw in (values or {}).items():
        if key not in VINA_OPTION_SPECS:
            raise ValueError("Unknown Vina option: " + str(key))
        label, kind, minimum = VINA_OPTION_SPECS[key]
        if raw is None or str(raw).strip() == "":
            continue
        if kind == "bool":
            if raw not in (True, False, "True", "False", "1", "0"):
                raise ValueError(label + ": expected a checkbox value")            if raw in (True, "True", "1"):
                result[key] = True
            continue
        try:
            value = int(str(raw).strip()) if kind == "int" else float(raw)
            if not math.isfinite(value) or value < minimum or (kind == "positive" and value <= 0):
                raise ValueError()
            if kind == "int" and value > 2147483647:
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            raise ValueError(label + ": invalid value " + repr(raw)) from None
        result[key] = str(value)
    return result

def vina_option_arguments(values):
    result = []
    for key, value in normalize_vina_options(values).items():
        result.append("--" + key)
        if value is not True:
            result.append(value)
    return result

def vina_option_lines(values):
    values = normalize_vina_options(values)
    return ["Vina " + key + ": " + (str(values[key]) if key in values else
            "not supplied (executable default applies)") for key in VINA_OPTION_SPECS] + [
        "Scoring: executable default (Vina); standard docking workflow",
        "A fixed nonzero seed is reused for every repeat; 0/blank uses automatic seeds.",
        "CPU threads and the live OS affinity/priority controls both apply."]

def probe_vina_options(executable):
    text = ""
    for flag in ("--help", "--help_advanced"):
        try:
            proc = subprocess.run([executable, flag], capture_output=True, text=True,
                                  errors="replace", timeout=10,
                                  **({"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}))
            if proc.returncode == 0:
                text += (proc.stdout or "") + (proc.stderr or "")
        except (OSError, subprocess.SubprocessError):
            pass
    return set(re.findall(r"--([a-z][a-z0-9_]*)", text)), text

APP_SETTINGS_FILENAME = "vina_batch_settings.json"
DOCKING_PROGRESS_FILENAME = "vlip_docking_progress.json"
PROJECT_STATE_FILENAME = "vlip_project.json"
PROJECT_RUN_LOG_FILENAME = "vlip_run.log"
APP_VERSION = "2.0.0"
COMPLETE_PIPELINE_VERSION = "2.0.0"
DEVELOPER_NAME = "Simon"
COMPLETE_SETTINGS_FILENAME = "VLiP_COMPLETE_SETTINGS_USED.txt"
JOB_SETTINGS_FILENAME = "VLiP_SETTINGS_USED.txt"
HTML_REPORT_FILENAME = "VLiP_Project_Report.html"
PERFORMANCE_HISTORY_FILENAME = "VLiP_PERFORMANCE_HISTORY.txt"
MAX_RECENT_PROJECTS = 12
RECEPTOR_TOOLS_DIRNAME = "receptor_tools"
CLEANER_TOOL_DIRNAME = "cleaner"
PDBQT_TOOL_DIRNAME = "pdbqt_preparer"
RECEPTOR_HANDOFF_FILENAME = "vlip_receptor_handoff.json"
LIGAND_HANDOFF_FILENAME = "vlip_ligand_handoff.json"
MANAGED_APP_DIRNAME = "VLiP_2.0"
MANAGED_TOOLS_DIRNAME = "tools"
MANAGED_RUNTIME_DIRNAME = "runtime"
MANAGED_MINICONDA_DIRNAME = "miniconda3"
IS_WINDOWS = os.name == "nt"
SPEED_MODES = ("Gentle", "Balanced", "Full")
SPEED_CORE_FRACTIONS = {"Gentle": 0.25, "Balanced": 0.50, "Full": 1.00}
MINICONDA_INSTALLER_NAME = "Miniconda3-py312_26.7.1-1-Windows-x86_64.exe"
MINICONDA_INSTALLER_URL = f"https://repo.anaconda.com/miniconda/{MINICONDA_INSTALLER_NAME}"
MINICONDA_INSTALLER_SHA256 = "8ae918681b0830314d85207f7a244352762b543bb83d53e0fcf77fbf270f8331"
VINA_RELEASE_TAG = "v1.2.7"
VINA_TRUSTED_SHA256_BY_ASSET = {
    "vina_1.2.7_win.exe": "e0c4b2715e0c1a74f6e92d0f3be0328ac97542eafbc111e6b1efad897a73cce5",
}
PYMOL_DOWNLOAD_URL = "https://pymol.org/"


def managed_root_dir():
    """User-writable location for downloaded executables and the isolated runtime."""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, MANAGED_APP_DIRNAME)
    return os.path.join(os.path.expanduser("~"), ".vlip")


def managed_tools_dir():
    return os.path.join(managed_root_dir(), MANAGED_TOOLS_DIRNAME)


def managed_runtime_dir():
    return os.path.join(managed_root_dir(), MANAGED_RUNTIME_DIRNAME)


def managed_miniconda_dir():
    return os.path.join(managed_root_dir(), MANAGED_MINICONDA_DIRNAME)


def managed_runtime_python(gui=False):
    env = managed_runtime_dir()
    if IS_WINDOWS:
        name = "pythonw.exe" if gui else "python.exe"
        path = os.path.join(env, name)
    else:
        path = os.path.join(env, "bin", "python")
    return path if os.path.isfile(path) else ""


def managed_runtime_subprocess_env():
    """Return an environment that keeps the managed Conda runtime DLLs isolated.

    On Windows, launching ``<prefix>\\python.exe`` directly is not enough: DLLs used
    by Conda packages live under ``Library\bin`` and Windows may otherwise find a
    different Miniconda/Anaconda installation first via the inherited PATH.
    """
    env = os.environ.copy()
    runtime = os.path.abspath(managed_runtime_dir())

    if IS_WINDOWS:
        preferred = [
            runtime,
            os.path.join(runtime, "Library", "mingw-w64", "bin"),
            os.path.join(runtime, "Library", "usr", "bin"),
            os.path.join(runtime, "Library", "bin"),
            os.path.join(runtime, "Scripts"),
            os.path.join(runtime, "bin"),
        ]
        preferred = [p for p in preferred if os.path.isdir(p)]

        runtime_norm = os.path.normcase(runtime).rstrip("\\/") + os.sep
        kept = []
        for item in env.get("PATH", "").split(os.pathsep):
            item = item.strip().strip('"')
            if not item:
                continue
            try:
                norm = os.path.normcase(os.path.abspath(item))
            except Exception:
                norm = os.path.normcase(item)

            # Keep our own runtime paths. Strip DLL-bearing paths from other
            # Conda installations so their FreeType/fontconfig/OpenBabel DLLs
            # cannot be mixed into the managed runtime.
            if norm == os.path.normcase(runtime) or norm.startswith(runtime_norm):
                continue
            low = norm.replace("/", "\\").lower()
            is_other_conda = ("\\miniconda" in low or "\\anaconda" in low)
            is_conda_binary_path = (
                "\\library\\bin" in low
                or low.endswith("\\scripts")
                or low.endswith("\\bin")
            )
            if is_other_conda and is_conda_binary_path:
                continue
            kept.append(item)

        env["PATH"] = os.pathsep.join(preferred + kept)
        env["CONDA_PREFIX"] = runtime
        env["CONDA_DEFAULT_ENV"] = runtime
        env.pop("PYTHONHOME", None)
        env.pop("PYTHONPATH", None)

    return env


def find_pymol_launch_command():
    """Return a Windows PyMOL launch command without assuming it is on PATH."""
    for name in ("PyMOLWin.exe", "pymol.exe", "pymol", "pymol.bat"):
        candidate = shutil.which(name)
        if candidate and os.path.exists(candidate):
            return [candidate]

    localapp = os.environ.get("LOCALAPPDATA", "")
    program_files = os.environ.get("ProgramFiles", "")
    program_files_x86 = os.environ.get("ProgramFiles(x86)", "")
    roots = [root for root in (localapp, program_files, program_files_x86) if root]
    direct_candidates = []
    pythonw_candidates = []
    for root in roots:
        direct_candidates.extend([
            os.path.join(root, "Schrodinger", "PyMOL2", "PyMOLWin.exe"),
            os.path.join(root, "Schrodinger", "PyMOL2", "Scripts", "pymol.exe"),
            os.path.join(root, "Schrodinger", "PyMOL2", "pymol.exe"),
            os.path.join(root, "PyMOL", "PyMOLWin.exe"),
            os.path.join(root, "PyMOL2", "PyMOLWin.exe"),
        ])
        pythonw_candidates.append(os.path.join(root, "Schrodinger", "PyMOL2", "pythonw.exe"))

    for candidate in direct_candidates:
        if os.path.isfile(candidate):
            return [candidate]
    for pythonw in pythonw_candidates:
        if os.path.isfile(pythonw):
            return [pythonw, "-m", "pymol"]
    return []




class RunCancelled(Exception):
    pass


class RunStoppedAfterReceptor(Exception):
    pass


# ======================================================
# Hidden subprocess helpers
# ======================================================

def command_to_text(cmd):
    """Return a readable command string for logs without requiring shell=True."""
    if isinstance(cmd, (list, tuple)):
        return " ".join(str(part) for part in cmd)
    return str(cmd)


def hidden_subprocess_kwargs():
    """
    Prevent child console windows on Windows.
    No-op on non-Windows.

    This is deliberately a bit belt-and-braces because Vina / PLIP /
    OpenBabel style tools are often console programs and Windows can steal
    focus even when stdout/stderr are piped.
    """
    if not IS_WINDOWS:
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESTDHANDLES", 0)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

    return {
        "startupinfo": startupinfo,
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0),
    }


def _normalise_windows_command(cmd):
    """
    Keep command launching predictable on Windows.
    Batch/cmd wrappers are forced through cmd.exe with quiet flags so the
    same no-window startup settings still apply.
    """
    if not IS_WINDOWS or not isinstance(cmd, (list, tuple)) or not cmd:
        return cmd

    first = str(cmd[0])
    lower = first.lower()

    if lower.endswith((".bat", ".cmd")):
        comspec = os.environ.get("ComSpec", "cmd.exe")
        return [comspec, "/d", "/q", "/c", first] + [str(x) for x in cmd[1:]]

    return [str(x) for x in cmd]


def _merged_subprocess_kwargs(kwargs):
    """Central place for subprocess defaults used by Vina, PLIP and self-checks."""
    opts = hidden_subprocess_kwargs()

    # Merge caller creation flags with our no-window flag instead of replacing it.
    caller_flags = kwargs.pop("creationflags", 0) if IS_WINDOWS else kwargs.pop("creationflags", 0)
    if IS_WINDOWS:
        opts["creationflags"] = opts.get("creationflags", 0) | caller_flags
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        kwargs.setdefault("shell", False)

    opts.update(kwargs)
    return opts


def run_hidden_subprocess(cmd, **kwargs):
    """Run a command without flashing a console window on Windows."""
    cmd = _normalise_windows_command(cmd)
    return subprocess.run(cmd, **_merged_subprocess_kwargs(kwargs))


def popen_hidden_subprocess(cmd, **kwargs):
    """Start a command without flashing a console window on Windows."""
    cmd = _normalise_windows_command(cmd)
    return subprocess.Popen(cmd, **_merged_subprocess_kwargs(kwargs))


# ======================================================
# App / packaging helpers
# ======================================================

def app_dir():
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def user_working_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def settings_path():
    return os.path.join(user_working_dir(), APP_SETTINGS_FILENAME)


def docking_progress_path():
    return os.path.join(user_working_dir(), DOCKING_PROGRESS_FILENAME)


def project_state_path(outdir):
    """Per-project save/checkpoint file. Falls back to app folder if outdir is empty."""
    outdir = str(outdir or "").strip()
    base = outdir if outdir else user_working_dir()
    return os.path.join(base, PROJECT_STATE_FILENAME)


def project_logs_dir(outdir):
    outdir = str(outdir or "").strip()
    base = outdir if outdir else user_working_dir()
    return os.path.join(base, "logs")


def project_run_log_path(outdir):
    return os.path.join(project_logs_dir(outdir), PROJECT_RUN_LOG_FILENAME)


def launchable_program():
    """
    Command used to relaunch this program as an internal worker.
    When not frozen on Windows, prefer pythonw.exe to avoid console windows.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable]

    python_exe = sys.executable
    python_dir = os.path.dirname(python_exe)
    pythonw_exe = os.path.join(python_dir, "pythonw.exe")

    if IS_WINDOWS and os.path.exists(pythonw_exe):
        return [pythonw_exe, os.path.abspath(__file__)]

    return [python_exe, os.path.abspath(__file__)]


def patch_pybel_for_plip():
    try:
        from openbabel import pybel
    except Exception:
        return

    original_write = pybel.Molecule.write

    def safe_write(self, format='smi', filename=None, overwrite=False, opt=None):
        fmt = str(format).lower().strip()
        if fmt == "inchikey":
            return ""
        return original_write(self, format=format, filename=filename, overwrite=overwrite, opt=opt)

    pybel.Molecule.write = safe_write


def run_internal_plip_worker():
    patch_pybel_for_plip()

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--plip-worker", action="store_true")
    parser.add_argument("-f", "--file", dest="input_file", required=True)
    parser.add_argument("-o", "--out", dest="out_dir", required=True)
    parser.add_argument("-t", action="store_true")
    parser.add_argument("-x", action="store_true")
    parser.add_argument("-v", action="store_true")
    args, unknown = parser.parse_known_args()

    sys.argv = [
        sys.argv[0],
        "-f", args.input_file,
        "-o", args.out_dir,
    ]
    if args.t:
        sys.argv.append("-t")
    if args.x:
        sys.argv.append("-x")
    if args.v:
        sys.argv.append("-v")
    sys.argv.extend(unknown)

    from plip.plipcmd import main as plip_main
    return plip_main()


# ======================================================
# Startup self-check helpers
# ======================================================

def try_import(module_name):
    try:
        __import__(module_name)
        return True, ""
    except Exception as e:
        return False, str(e)


def check_vina_available(explicit_path=""):
    candidates = []

    if explicit_path:
        candidates.append(explicit_path)

    for base in [app_dir(), user_working_dir(), managed_root_dir()]:
        candidates.append(os.path.join(base, "vina.exe"))
        candidates.append(os.path.join(base, "tools", "vina.exe"))
        candidates.append(os.path.join(base, "bin", "vina.exe"))

    for p in candidates:
        if p and os.path.exists(p):
            try:
                result = run_hidden_subprocess(
                    [p, "--help"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    return True, p, 0
                detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
                return False, p, detail
            except Exception as e:
                return False, p, str(e)

    found = shutil.which("vina")
    if found:
        try:
            result = run_hidden_subprocess(
                [found, "--help"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return True, found, 0
            detail = (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
            return False, found, detail
        except Exception as e:
            return False, found, str(e)

    return False, "", "vina executable not found"


def check_plip_stack():
    # Scientific packages are deliberately owned by the managed runtime. Do NOT
    # import them into the GUI's Python first: a user's base Conda environment
    # can contain incompatible FreeType/fontconfig DLLs and Windows will show an
    # Entry Point Not Found dialog before Python can catch ImportError.
    runtime_py = managed_runtime_python(False)
    if not runtime_py:
        detail = "managed VLiP runtime not installed; use Install / Repair ALL"
        return [("Managed scientific runtime", False, detail)]

    try:
        probe_code = r'''
import importlib
import json
import os
import sys

checks = []
modules = [
    ("PLIP", "plip"),
    ("OpenBabel", "openbabel"),
    ("Pybel", "openbabel.pybel"),
    ("Meeko", "meeko"),
    ("PDB2PQR", "pdb2pqr"),
    ("PROPKA", "propka"),
    ("RDKit", "rdkit"),
    ("SciPy", "scipy"),
    ("Gemmi", "gemmi"),
    ("Matplotlib", "matplotlib"),
]
for label, module_name in modules:
    try:
        importlib.import_module(module_name)
        checks.append([label, True, "managed VLiP runtime"])
    except Exception as exc:
        checks.append([label, False, str(exc)])

root = os.path.dirname(os.path.abspath(sys.executable))
command_dirs = [root, os.path.join(root, "Scripts"), os.path.join(root, "bin")]
def has_command(names):
    return any(os.path.isfile(os.path.join(folder, name)) for folder in command_dirs for name in names)

pdb2pqr_ok = has_command(["pdb2pqr.exe", "pdb2pqr", "pdb2pqr30.exe", "pdb2pqr30"])
meeko_command_ok = has_command([
    "mk_prepare_receptor.py.exe", "mk_prepare_receptor.exe",
    "mk_prepare_receptor.py", "mk_prepare_receptor",
])
checks.append([
    "PDB2PQR command", pdb2pqr_ok,
    "managed VLiP runtime" if pdb2pqr_ok else "PDB2PQR command not found",
])
checks.append([
    "Meeko receptor command", meeko_command_ok,
    "managed VLiP runtime" if meeko_command_ok else "Meeko receptor command not found",
])
print("VLIP_CHECK_JSON=" + json.dumps(checks))
'''
        probe = run_hidden_subprocess(
            [runtime_py, "-c", probe_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            env=managed_runtime_subprocess_env(),
        )
        if probe.returncode == 0:
            marker = "VLIP_CHECK_JSON="
            payload_line = next(
                (line for line in reversed((probe.stdout or "").splitlines()) if line.startswith(marker)),
                "",
            )
            if payload_line:
                payload = json.loads(payload_line[len(marker):])
                return [
                    (str(label), bool(ok), str(detail) if ok else str(detail or "not available"))
                    for label, ok, detail in payload
                ]
        detail = (probe.stderr or probe.stdout or "managed runtime probe failed").strip()[:1200]
    except Exception as exc:
        detail = str(exc)

    return [("Managed scientific runtime", False, detail)]


def format_self_check_report(vina_field_value=""):
    lines = []
    lines.append("VLIP startup self-check")
    lines.append("")

    vina_ok, vina_path, vina_info = check_vina_available(vina_field_value)
    lines.append(f"Vina: {'OK' if vina_ok else 'FAIL'}")
    if vina_path:
        lines.append(f"Path: {vina_path}")
    if vina_info != 0 and vina_info != "vina executable not found":
        lines.append(f"Detail: {vina_info}")
    lines.append("")

    stack_results = check_plip_stack()
    for label, ok, detail in stack_results:
        lines.append(f"{label}: {'OK' if ok else 'FAIL'}")
        if detail:
            lines.append(f"Detail: {detail}")
        lines.append("")

    runtime_py = managed_runtime_python(False)
    runtime_ok = bool(runtime_py) and all(ok for _label, ok, _detail in stack_results)
    if runtime_ok:
        lines.append("Managed receptor/ligand scientific runtime: OK")
        lines.append(f"Path: {managed_runtime_dir()}")
    elif runtime_py:
        lines.append("Managed receptor/ligand scientific runtime: FOUND BUT FAILED VALIDATION")
        lines.append(f"Path: {managed_runtime_dir()}")
        lines.append("Use Receptor Tools -> Install / Repair ALL")
    else:
        lines.append("Managed receptor/ligand scientific runtime: NOT INSTALLED")
        lines.append("Use Receptor Tools -> Install / Repair ALL")
    lines.append("")

    return "\n".join(lines), bool(vina_ok and runtime_ok)


# ======================================================
# Diagnostics helpers
# ======================================================

def read_json_file(path):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except Exception:
        return None


def atomic_write_json(path, data):
    """Write JSON via a temp file so crashes do not corrupt the save point."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)


def atomic_write_text(path, text):
    """Write a text report via a temp file so interruptions cannot leave half a record."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp_path, path)


def sha256_file(path):
    """Return a file fingerprint used to prove that two runs used identical inputs."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except Exception as exc:
        return f"UNAVAILABLE ({exc})"


def command_as_text(cmd):
    """Render the exact argument list in a copyable form, including quoted paths."""
    try:
        return subprocess.list2cmdline([str(part) for part in cmd])
    except Exception:
        return " ".join(str(part) for part in cmd)


_VLIP_LOG_LOCK = threading.Lock()

def normalize_plip_workers(value):
    try:
        workers = int(str(value).strip())
    except (ValueError, TypeError):
        raise ValueError("Parallel PLIP poses must be a whole number from 1 to 32.") from None
    if not 1 <= workers <= 32:
        raise ValueError("Parallel PLIP poses must be a whole number from 1 to 32.")
    return workers

def log_line(path, text):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    with _VLIP_LOG_LOCK:
        with open(path, "a", encoding="utf-8", errors="replace") as f:
            f.write(text.rstrip() + "\n")


def project_log_line(outdir, text):
    """Timestamped project-level log, separate from per-ligand runlog.txt."""
    if not outdir:
        return
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    log_line(project_run_log_path(outdir), f"[{stamp}] {text}")


def warn_path_len(label, path, warn_at=240):
    if os.name == "nt":
        try:
            n = len(os.path.abspath(path))
        except Exception:
            n = len(path)
        if n >= warn_at:
            return f"[WARN] {label} path is long ({n} chars): {path}"
    return None


def wait_for_stable_file(path, timeout_s=10.0, stable_window_s=0.5, cancel_event=None):
    t0 = time.time()
    last_size = None
    stable_since = None

    while time.time() - t0 < timeout_s:
        if cancel_event is not None and cancel_event.is_set():
            raise RunCancelled("Cancelled by user.")

        if os.path.exists(path):
            try:
                sz = os.path.getsize(path)
            except OSError:
                sz = None

            if sz is not None and sz == last_size:
                if stable_since is None:
                    stable_since = time.time()
                elif (time.time() - stable_since) >= stable_window_s:
                    return True
            else:
                stable_since = None
                last_size = sz

        time.sleep(0.1)
    return False


def validate_pdbqt(path, kind="file", require_vina_output=False):
    try:
        atom_count = 0
        model_count = 0
        end_model_count = 0
        vina_result_count = 0

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_number, raw_line in enumerate(f, 1):
                line = raw_line.rstrip("\r\n")

                if line.startswith("MODEL"):
                    model_count += 1
                elif line.startswith("ENDMDL"):
                    end_model_count += 1
                elif line.startswith("REMARK VINA RESULT:"):
                    vina_result_count += 1

                if not line.startswith(("ATOM", "HETATM")):
                    continue

                atom_count += 1
                if "\t" in line:
                    return False, f"{kind}: line {line_number} contains TAB characters"

                try:
                    float(line[30:38])
                    float(line[38:46])
                    float(line[46:54])
                except (TypeError, ValueError):
                    return False, f"{kind}: line {line_number} has non-numeric or misaligned coordinates"

                parts = line.split()
                if len(parts) < 3:
                    return False, f"{kind}: line {line_number} is too short"
                try:
                    float(parts[-2])
                except (TypeError, ValueError):
                    return False, f"{kind}: line {line_number} has a missing/invalid partial charge"
                if not parts[-1].strip():
                    return False, f"{kind}: line {line_number} has a missing atom type"

        if atom_count == 0:
            return False, f"{kind}: no ATOM/HETATM lines"

        if require_vina_output:
            if model_count == 0 or end_model_count == 0:
                return False, f"{kind}: missing MODEL/ENDMDL records"
            if model_count != end_model_count:
                return False, f"{kind}: MODEL/ENDMDL counts do not match"
            if vina_result_count < model_count:
                return False, f"{kind}: one or more poses have no Vina affinity result"

        return True, "OK"
    except Exception as ex:
        return False, f"{kind}: cannot read ({ex})"


WINDOWS_RESERVED_OUTPUT_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def normalized_path_key(path):
    """Return a stable, case-normalized key for input-file identity."""
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path))))


def natural_sort_key(value):
    """Sort pose2 before pose10 while retaining case-insensitive text ordering."""
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", str(value))
    )


def safe_output_stem(path):
    """Return a filesystem-safe folder/file stem derived from an input path."""
    stem = os.path.splitext(os.path.basename(str(path)))[0].strip()
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", stem).rstrip(" .")
    if not stem:
        stem = "item"
    if stem.upper() in WINDOWS_RESERVED_OUTPUT_NAMES:
        stem = "_" + stem
    return stem[:64]


def compact_dock_output_path(run_dir):
    """Canonical short docking output path used by v1.39+ projects."""
    return os.path.join(run_dir, "dock", "dock.pdbqt")


def existing_dock_output_path(run_dir, ligand_name, receptor_name, run_index):
    """Return the v1.39 compact output, falling back to the v1.38 legacy name."""
    compact = compact_dock_output_path(run_dir)
    if os.path.exists(compact):
        return compact
    return os.path.join(
        run_dir, "dock", f"{ligand_name}_{receptor_name}_run{run_index}.pdbqt"
    )


def build_unique_output_names(paths, reserved_names=None):
    """Assign deterministic names without mixing same-basename input files."""
    reserved = {str(name).casefold() for name in (reserved_names or [])}
    items = []
    groups = {}
    for path in paths:
        key = normalized_path_key(path)
        stem = safe_output_stem(path)
        items.append((key, stem))
        groups.setdefault(stem.casefold(), set()).add(key)

    result = {}
    used = set()
    for key, stem in items:
        if key in result:
            continue
        if len(groups[stem.casefold()]) > 1:
            digest = hashlib.sha256(key.encode("utf-8", errors="surrogatepass")).hexdigest()[:8]
            candidate = f"{stem}__{digest}"
        else:
            candidate = stem

        if candidate.casefold() in reserved:
            candidate = f"{candidate}__input"
        base = candidate
        suffix = 2
        while candidate.casefold() in used or candidate.casefold() in reserved:
            candidate = f"{base}_{suffix}"
            suffix += 1
        used.add(candidate.casefold())
        result[key] = candidate
    return result


def remove_generated_files(directory, patterns):
    """Remove only named VLiP-generated files from one expected output folder."""
    if not os.path.isdir(directory):
        return []
    if os.path.islink(directory):
        raise RuntimeError(f"Refusing to clean a symlinked output directory: {directory}")

    folded_patterns = [str(pattern).casefold() for pattern in patterns]
    removed = []
    with os.scandir(directory) as entries:
        for entry in entries:
            folded_name = entry.name.casefold()
            if not any(fnmatch.fnmatchcase(folded_name, pattern) for pattern in folded_patterns):
                continue
            path = os.path.join(directory, entry.name)
            if entry.is_symlink():
                os.remove(path)
                removed.append(path)
            elif entry.is_file(follow_symlinks=False):
                os.remove(path)
                removed.append(path)
    return removed


# ======================================================
# Geometry helpers
# ======================================================

def parse_atoms(pdbqt):
    atoms = []
    with open(pdbqt, "r", encoding="utf-8", errors="replace") as f:
        for l in f:
            if l.startswith(("ATOM", "HETATM")):
                try:
                    x = float(l[30:38])
                    y = float(l[38:46])
                    z = float(l[46:54])
                    res = int(l[22:26].strip())
                    chain = l[21:22].strip()
                    icode = l[26:27].strip().upper()
                    atoms.append((x, y, z, res, chain, icode))
                except Exception:
                    pass
    return atoms


ACTIVE_RESIDUE_TOKEN = re.compile(
    r"^(?:(?P<chain>[^:,\s]+):)?(?P<resnum>-?\d+)(?P<icode>[A-Za-z]?)$"
)


def parse_active_residue_specs(value):
    """Parse residue tokens such as ``42``, ``A:42`` or ``A:42B``.

    An underscore identifies a blank PDB chain. Unqualified residue numbers are
    retained for backwards compatibility, but selection rejects them when the
    same number occurs in more than one chain/insertion-code location.
    """
    tokens = [item.strip() for item in str(value or "").split(",") if item.strip()]
    if not tokens:
        raise ValueError(
            "Active mode requires at least one residue. Use 42 for an unambiguous "
            "single-chain residue, or A:42 / A:42B to include chain and insertion code."
        )
    specs = []
    for token in tokens:
        match = ACTIVE_RESIDUE_TOKEN.fullmatch(token)
        if not match:
            raise ValueError(
                f"Invalid active residue {token!r}. Use comma-separated values such as "
                "42, A:42 or A:42B."
            )
        raw_chain = match.group("chain")
        chain = None if raw_chain is None else raw_chain.strip()
        if chain == "_":
            chain = ""
        if chain is not None and chain and len(chain) != 1:
            raise ValueError(
                f"Invalid chain in active residue {token!r}; legacy PDBQT chain IDs must be one character."
            )
        specs.append((chain, int(match.group("resnum")), (match.group("icode") or "").upper(), token))
    return specs


def select_active_residue_atoms(atoms, value):
    """Return atoms for an exact, fully validated active-residue selection."""
    specs = parse_active_residue_specs(value)
    identities = {(atom[4], atom[3], atom[5]) for atom in atoms}
    chosen = set()
    problems = []

    for chain, resnum, icode, token in specs:
        if chain is not None:
            matches = {identity for identity in identities if identity == (chain, resnum, icode)}
        else:
            matches = {
                identity for identity in identities
                if identity[1] == resnum and (not icode or identity[2] == icode)
            }
            if len(matches) > 1:
                choices = ", ".join(
                    f"{candidate_chain or '_'}:{candidate_resnum}{candidate_icode}"
                    for candidate_chain, candidate_resnum, candidate_icode in sorted(matches)
                )
                problems.append(f"{token!r} is ambiguous ({choices}); specify the chain")
                continue

        if not matches:
            problems.append(f"{token!r} matched no receptor residue")
            continue
        chosen.update(matches)

    if problems:
        raise ValueError("; ".join(problems))

    selected = [atom for atom in atoms if (atom[4], atom[3], atom[5]) in chosen]
    if not selected:
        raise ValueError("The active-residue selection matched no receptor atoms.")
    return selected


def box_from_atoms(atoms, padding):
    xs = [a[0] for a in atoms]
    ys = [a[1] for a in atoms]
    zs = [a[2] for a in atoms]

    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)
    minz, maxz = min(zs), max(zs)

    cx = (minx + maxx) / 2
    cy = (miny + maxy) / 2
    cz = (minz + maxz) / 2

    sx = (maxx - minx) + padding
    sy = (maxy - miny) + padding
    sz = (maxz - minz) + padding

    return cx, cy, cz, sx, sy, sz, minx, maxx, miny, maxy, minz, maxz


# ======================================================
# Lightweight molecular structure / rendering helpers
# ======================================================

MOLECULAR_ELEMENT_COLORS = {
    "H": "#f4f7fb", "C": "#8b98a7", "N": "#4f7cff", "O": "#ff4f5e",
    "F": "#62d97b", "CL": "#35c759", "BR": "#a85a32", "I": "#8e5bd9",
    "P": "#ff9f43", "S": "#ffd43b", "B": "#f5a3a3", "SI": "#d7a36d",
    "FE": "#d46b38", "ZN": "#7f8cff", "MG": "#42c7b9", "CA": "#72d572",
    "NA": "#8d73ff", "K": "#b66cff", "MN": "#a66a9f", "CU": "#c77b30",
}

MOLECULAR_COVALENT_RADII = {
    "H": 0.31, "B": 0.85, "C": 0.76, "N": 0.71, "O": 0.66,
    "F": 0.57, "P": 1.07, "S": 1.05, "CL": 1.02, "BR": 1.20,
    "I": 1.39, "SI": 1.11, "FE": 1.24, "ZN": 1.22, "MG": 1.30,
    "CA": 1.74, "NA": 1.66, "K": 2.03, "MN": 1.39, "CU": 1.32,
}

MOLECULAR_VDW_RADII = {
    "H": 1.20, "B": 1.92, "C": 1.70, "N": 1.55, "O": 1.52,
    "F": 1.47, "P": 1.80, "S": 1.80, "CL": 1.75, "BR": 1.85,
    "I": 1.98, "SI": 2.10, "FE": 1.80, "ZN": 1.39, "MG": 1.73,
    "CA": 2.31, "NA": 2.27, "K": 2.75, "MN": 1.73, "CU": 1.40,
}


def molecular_distance(first, second):
    return math.sqrt(
        (first["x"] - second["x"]) ** 2
        + (first["y"] - second["y"]) ** 2
        + (first["z"] - second["z"]) ** 2
    )


def molecular_element_from_line(line):
    """Infer a chemical element from PDB or AutoDock PDBQT records."""
    field = line[76:78].strip().upper() if len(line) >= 78 else ""
    atom_name = line[12:16].strip().upper() if len(line) >= 16 else ""
    parts = line.split()
    atom_type = parts[-1].upper().replace(".", "") if parts else ""
    type_map = {
        "A": "C", "NA": "N", "NS": "N", "OA": "O", "OS": "O",
        "SA": "S", "HD": "H", "HS": "H", "CL": "CL", "BR": "BR",
    }
    if atom_type in type_map:
        return type_map[atom_type]
    if atom_type in MOLECULAR_ELEMENT_COLORS:
        return atom_type
    if field in MOLECULAR_ELEMENT_COLORS:
        return field
    cleaned = re.sub(r"[^A-Z]", "", atom_name)
    if line[:6].strip() == "ATOM" and cleaned[:1] in {"C", "N", "O", "S", "P", "H"}:
        # Protein atom names such as CA/CB/CD are carbon positions, not metals.
        return cleaned[:1]
    for candidate in (cleaned[:2], cleaned[:1]):
        if candidate in MOLECULAR_ELEMENT_COLORS:
            return candidate
    return "C"


def parse_molecular_atom(line, source="molecule"):
    try:
        serial_text = line[6:11].strip()
        residue_text = line[22:26].strip()
        return {
            "x": float(line[30:38]),
            "y": float(line[38:46]),
            "z": float(line[46:54]),
            "serial": int(serial_text) if serial_text.lstrip("-").isdigit() else 0,
            "name": line[12:16].strip() or "?",
            "resname": line[17:20].strip() or ("LIG" if source == "ligand" else "UNK"),
            "chain": line[21:22].strip() or "-",
            "resseq": int(residue_text) if residue_text.lstrip("-").isdigit() else 0,
            "icode": line[26:27].strip().upper() if len(line) >= 27 else "",
            "altloc": line[16:17].strip(),
            "occupancy": float(line[54:60].strip() or "1"),
            "bfactor": float(line[60:66].strip() or "0"),
            "element": molecular_element_from_line(line),
            "record": line[:6].strip(),
            "source": source,
        }
    except (TypeError, ValueError):
        return None


def read_molecular_models(path, source="ligand"):
    """Read a PDB/PDBQT file into models while retaining Vina affinities."""
    models = []
    current_atoms = []
    current_affinity = None
    current_model_number = None
    segment = 0
    saw_model = False

    with open(path, "r", encoding="utf-8", errors="replace") as structure:
        for raw_line in structure:
            line = raw_line.rstrip("\r\n")
            if line.startswith("MODEL"):
                if current_atoms:
                    models.append({
                        "atoms": current_atoms,
                        "affinity": current_affinity,
                        "model": current_model_number or len(models) + 1,
                    })
                saw_model = True
                current_atoms = []
                current_affinity = None
                try:
                    current_model_number = int(line.split()[1])
                except (IndexError, ValueError):
                    current_model_number = len(models) + 1
                continue
            if line.startswith("REMARK VINA RESULT:"):
                match = re.search(r"REMARK\s+VINA\s+RESULT:\s*([-+0-9.eE]+)", line)
                if match:
                    try:
                        current_affinity = float(match.group(1))
                    except ValueError:
                        pass
                continue
            if line.startswith("ENDMDL"):
                if current_atoms:
                    models.append({
                        "atoms": current_atoms,
                        "affinity": current_affinity,
                        "model": current_model_number or len(models) + 1,
                    })
                current_atoms = []
                current_affinity = None
                current_model_number = None
                continue
            if line[:6].strip() == "TER":
                segment += 1
            if line.startswith(("ATOM", "HETATM")):
                atom = parse_molecular_atom(line, source=source)
                if atom is not None:
                    atom["segment"] = segment
                    current_atoms.append(atom)

    if current_atoms:
        models.append({
            "atoms": current_atoms,
            "affinity": current_affinity,
            "model": current_model_number or len(models) + 1,
        })
    if not models and saw_model:
        return []
    return models


def infer_molecular_bonds(atoms, maximum_atoms=450):
    """Infer display bonds from covalent radii; intended for ligand-sized models."""
    visible = atoms[:maximum_atoms]
    bonds = []
    for first_index, first in enumerate(visible):
        first_radius = MOLECULAR_COVALENT_RADII.get(first["element"], 0.77)
        for second_index in range(first_index + 1, len(visible)):
            second = visible[second_index]
            if first["element"] == second["element"] == "H":
                continue
            dx = first["x"] - second["x"]
            dy = first["y"] - second["y"]
            dz = first["z"] - second["z"]
            distance_squared = dx * dx + dy * dy + dz * dz
            limit = first_radius + MOLECULAR_COVALENT_RADII.get(second["element"], 0.77) + 0.45
            if 0.16 <= distance_squared <= limit * limit:
                bonds.append((first_index, second_index))
    return bonds


def molecular_center(atoms):
    if not atoms:
        return 0.0, 0.0, 0.0
    count = float(len(atoms))
    return (
        sum(atom["x"] for atom in atoms) / count,
        sum(atom["y"] for atom in atoms) / count,
        sum(atom["z"] for atom in atoms) / count,
    )


def molecular_nearby_atoms(receptor_atoms, ligand_atoms, cutoff):
    """Return receptor atoms close to the ligand using a compact spatial grid."""
    if not receptor_atoms or not ligand_atoms:
        return []
    cell_size = max(1.0, float(cutoff))
    grid = {}
    for atom in receptor_atoms:
        cell = (
            int(math.floor(atom["x"] / cell_size)),
            int(math.floor(atom["y"] / cell_size)),
            int(math.floor(atom["z"] / cell_size)),
        )
        grid.setdefault(cell, []).append(atom)
    cutoff_squared = cutoff * cutoff
    found = {}
    for ligand_atom in ligand_atoms:
        origin = (
            int(math.floor(ligand_atom["x"] / cell_size)),
            int(math.floor(ligand_atom["y"] / cell_size)),
            int(math.floor(ligand_atom["z"] / cell_size)),
        )
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for atom in grid.get((origin[0] + dx, origin[1] + dy, origin[2] + dz), []):
                        distance_squared = (
                            (atom["x"] - ligand_atom["x"]) ** 2
                            + (atom["y"] - ligand_atom["y"]) ** 2
                            + (atom["z"] - ligand_atom["z"]) ** 2
                        )
                        if distance_squared <= cutoff_squared:
                            found[id(atom)] = atom
    return list(found.values())


def molecular_residue_key(atom):
    """Return a chain-aware identity for one parsed receptor residue."""
    return (
        atom.get("chain", "-"),
        atom.get("resseq", 0),
        atom.get("icode", ""),
        atom.get("resname", "UNK"),
    )


def molecular_residue_label(atom_or_key):
    """Format compact labels such as TYR A:42 or GLY A:42B."""
    if isinstance(atom_or_key, dict):
        chain, resseq, icode, resname = molecular_residue_key(atom_or_key)
    else:
        chain, resseq, icode, resname = atom_or_key
    return f"{resname} {chain}:{resseq}{icode}"


def molecular_nearby_residue_groups(receptor_atoms, ligand_atoms, cutoff):
    """Return complete receptor residues with any atom inside the ligand cutoff."""
    close_atoms = molecular_nearby_atoms(receptor_atoms, ligand_atoms, cutoff)
    if not close_atoms:
        return []

    distances = {}
    for atom in close_atoms:
        key = molecular_residue_key(atom)
        nearest = min(molecular_distance(atom, ligand_atom) for ligand_atom in ligand_atoms)
        distances[key] = min(distances.get(key, float("inf")), nearest)

    grouped = {key: [] for key in distances}
    for atom in receptor_atoms:
        key = molecular_residue_key(atom)
        if key in grouped:
            grouped[key].append(atom)

    return [
        {
            "key": key,
            "label": molecular_residue_label(key),
            "atoms": grouped[key],
            "distance": distances[key],
        }
        for key in sorted(distances, key=lambda item: (distances[item], item))
    ]


def molecular_plip_pose_number(path):
    """Return the explicit pose number from a VLiP per-pose PLIP filename."""
    name = os.path.basename(str(path or ""))
    match = re.match(r"^pose[_ -]?(\d+)(?:[_ .-]|$)", name, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def molecular_index_plip_reports(paths):
    """Index PLIP summaries by pose without shifting across missing reports."""
    indexed = {}
    for path in paths or []:
        pose_number = molecular_plip_pose_number(path)
        if pose_number is not None and pose_number > 0:
            indexed.setdefault(pose_number, path)
    return indexed


def preferred_pose_plip_summaries(plip_dir):
    """Return one summary per pose, preferring the compact v0.0.0.5 sidecar."""
    try:
        names = os.listdir(plip_dir)
    except OSError:
        return []

    choices = {}
    for name in names:
        compact_match = re.fullmatch(
            r"pose(\d+)_PLIP_compact_summary\.txt", name, flags=re.IGNORECASE
        )
        legacy_match = re.fullmatch(
            r"pose(\d+)_UNL_only_summary\.txt", name, flags=re.IGNORECASE
        )
        match = compact_match or legacy_match
        if not match:
            continue
        pose_number = int(match.group(1))
        priority = 0 if compact_match else 1
        candidate = (priority, natural_sort_key(name), os.path.join(plip_dir, name))
        if pose_number not in choices or candidate[:2] < choices[pose_number][:2]:
            choices[pose_number] = candidate
    return [choices[number][2] for number in sorted(choices)]


def molecular_full_plip_report(summary_path):
    """Resolve the original PLIP text report belonging to a compact/UNL summary."""
    pose_number = molecular_plip_pose_number(summary_path)
    folder = os.path.dirname(str(summary_path or ""))
    if pose_number is None or not os.path.isdir(folder):
        return ""
    wanted = f"pose{pose_number}_report.txt".casefold()
    try:
        for name in os.listdir(folder):
            if name.casefold() == wanted:
                path = os.path.join(folder, name)
                return path if os.path.isfile(path) else ""
    except OSError:
        pass
    return ""


def _plip_interaction_sections(unl_block):
    """Parse PLIP's pipe-delimited text tables into named interaction rows."""
    sections = []
    current = None
    for raw_line in str(unl_block or "").splitlines():
        stripped = raw_line.strip()
        heading = re.fullmatch(r"\*\*(.+?)\*\*", stripped)
        if heading:
            current = {"name": heading.group(1).strip(), "header": None, "rows": []}
            sections.append(current)
            continue
        if current is None or not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not any(cells):
            continue
        if current["header"] is None:
            current["header"] = cells
            continue
        header = current["header"]
        if len(cells) != len(header):
            continue
        row = dict(zip(header, cells))
        if any(value for value in row.values()):
            current["rows"].append(row)
    return sections


def format_compact_pose_plip_summary(unl_block, ligand_name, receptor_name, pose_name, vina_score):
    """Turn PLIP's very wide ASCII tables into a narrow, readable pose summary."""
    score_text = "N/A"
    if vina_score is not None:
        try:
            score_text = f"{float(vina_score):.3f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            score_text = str(vina_score).strip() or "N/A"

    ligand_header = ""
    for line in str(unl_block or "").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith(("*", "+", "|", "=")):
            ligand_header = stripped
            break

    pretty_fields = {
        "DIST": "distance",
        "DIST_H-A": "H–acceptor distance",
        "DIST_D-A": "donor–acceptor distance",
        "CENTDIST": "centre distance",
        "DON_ANGLE": "donor angle",
        "ANGLE": "angle",
        "OFFSET": "offset",
        "LIGCARBONIDX": "ligand atom",
        "PROTCARBONIDX": "protein atom",
        "LIG_IDX_LIST": "ligand atoms",
        "PROT_IDX_LIST": "protein atoms",
        "DONORIDX": "donor atom",
        "ACCEPTORIDX": "acceptor atom",
        "LIG_GROUP": "ligand group",
        "PROTISDON": "protein is donor",
        "PROTISPOS": "protein is positive",
        "SIDECHAIN": "side chain",
    }
    priority = tuple(pretty_fields)
    distance_fields = {"DIST", "DIST_H-A", "DIST_D-A", "CENTDIST"}
    angle_fields = {"DON_ANGLE", "ANGLE"}

    rendered_sections = []
    total_interactions = 0
    for section in _plip_interaction_sections(unl_block):
        if not section["rows"]:
            continue
        rendered = []
        for index, row in enumerate(section["rows"], 1):
            residue_bits = [row.get("RESTYPE", "").strip(), row.get("RESCHAIN", "").strip()]
            residue = " ".join(bit for bit in residue_bits if bit).strip()
            resnr = row.get("RESNR", "").strip()
            if resnr:
                residue = f"{residue}:{resnr}" if residue else f"Residue {resnr}"
            if not residue:
                residue = "Interaction"

            details = []
            for key in priority:
                value = row.get(key, "").strip()
                if not value:
                    continue
                suffix = " Å" if key in distance_fields else ("°" if key in angle_fields else "")
                details.append(f"{pretty_fields[key]} {value}{suffix}")
            rendered.append(
                f"  {index}. {residue}" + (" — " + "; ".join(details) if details else "")
            )
        total_interactions += len(rendered)
        rendered_sections.append((section["name"], rendered))

    lines = [
        "POSE-SPECIFIC PLIP SUMMARY",
        f"Ligand: {ligand_name}",
        f"Receptor: {receptor_name}",
        f"Pose: {pose_name}",
        f"Vina affinity: {score_text} kcal/mol",
    ]
    if ligand_header:
        lines.append(f"PLIP ligand: {ligand_header}")
    lines.extend(["", f"Detected interactions: {total_interactions}"])
    if not rendered_sections:
        lines.extend(["", "No PLIP interactions were reported for this pose."])
    else:
        for section_name, rendered in rendered_sections:
            lines.extend(["", f"{section_name} ({len(rendered)})", *rendered])
    lines.extend([
        "",
        "Full PLIP tables remain available in the matching pose report file.",
    ])
    return "\n".join(lines).rstrip() + "\n"


def molecular_models_centered_at(models, target_center):
    """Return display-only model copies translated to a requested scene centre."""
    centred = []
    for model in models:
        atoms = list(model.get("atoms") or [])
        if atoms:
            current_center = molecular_center(atoms)
            shift = tuple(target_center[index] - current_center[index] for index in range(3))
            display_atoms = [
                dict(
                    atom,
                    x=atom["x"] + shift[0],
                    y=atom["y"] + shift[1],
                    z=atom["z"] + shift[2],
                )
                for atom in atoms
            ]
        else:
            display_atoms = []
        display_model = dict(model)
        display_model["atoms"] = display_atoms
        centred.append(display_model)
    return centred


def molecular_contact_guides(receptor_atoms, ligand_atoms, cutoff=4.2, limit=120):
    """Build geometry-only contact guides; these are not a replacement for PLIP."""
    nearby = molecular_nearby_atoms(receptor_atoms, ligand_atoms, cutoff)
    contacts = []
    polar = {"N", "O", "S"}
    hydrophobic = {"C", "S", "CL", "BR", "I"}
    for ligand_atom in ligand_atoms:
        for receptor_atom in nearby:
            distance = molecular_distance(ligand_atom, receptor_atom)
            if distance > cutoff or distance < 1.0:
                continue
            elements = {ligand_atom["element"], receptor_atom["element"]}
            if elements <= polar and distance <= 3.6:
                kind = "Polar"
            elif elements <= hydrophobic:
                kind = "Hydrophobic"
            elif distance <= 3.3:
                kind = "Close"
            else:
                continue
            contacts.append({
                "ligand": ligand_atom,
                "receptor": receptor_atom,
                "distance": distance,
                "kind": kind,
            })
    contacts.sort(key=lambda item: item["distance"])
    return contacts[:limit]


def blend_hex_colors(first, second, amount):
    amount = max(0.0, min(1.0, float(amount)))
    try:
        first_rgb = tuple(int(first[index:index + 2], 16) for index in (1, 3, 5))
        second_rgb = tuple(int(second[index:index + 2], 16) for index in (1, 3, 5))
        mixed = tuple(round(a + (b - a) * amount) for a, b in zip(first_rgb, second_rgb))
        return "#" + "".join(f"{value:02x}" for value in mixed)
    except Exception:
        return first


class MolecularPoseViewer:
    """Self-contained Tk molecular pose viewer for quick docking inspection."""

    def __init__(self, parent, ligand_models, receptor_atoms=None, title="Docked pose",
                 source_path="", receptor_path="", plip_reports=None,
                 result_info=None, night_mode=False, open_path_callback=None,
                 box_geometry=None, focus_atoms=None, preview_mode=False,
                 preview_note="", result_options=None, result_switch_callback=None):
        self.preview_mode = bool(preview_mode)
        if not ligand_models:
            ligand_models = [{"atoms": [], "affinity": None, "model": 1}]
        if not any(model.get("atoms") for model in ligand_models) and not self.preview_mode:
            raise ValueError("The selected docking file contains no readable atoms.")

        self.parent = parent
        self.models = ligand_models
        self.receptor_atoms = list(receptor_atoms or [])
        self.source_path = source_path
        self.receptor_path = receptor_path
        self.plip_reports = list(plip_reports or [])
        self.plip_reports_by_pose = molecular_index_plip_reports(self.plip_reports)
        self.current_plip_report = ""
        self.current_full_plip_report = ""
        self.result_info = dict(result_info or {})
        self.result_options = [dict(item) for item in (result_options or []) if isinstance(item, dict)]
        self.result_options.sort(key=lambda item: (
            str(item.get("ligand") or "").casefold(),
            str(item.get("receptor") or "").casefold(),
            int(item.get("run", 0) or 0),
            float(item.get("affinity")) if item.get("affinity") is not None else float("inf"),
        ))
        self.result_switch_callback = result_switch_callback
        self.open_path_callback = open_path_callback
        self.box_geometry = dict(box_geometry or {})
        self.focus_atoms = list(focus_atoms or [])
        self.preview_note = str(preview_note or "")
        self.night_mode = bool(night_mode)
        self.palette = self._palette(self.night_mode)

        self.win = tk.Toplevel(parent)
        window_kind = "Receptor Preview" if self.preview_mode else "Pose Viewer"
        self.win.title(f"VLiP {window_kind} — {title}")
        self.win.geometry("1280x800" if self.preview_mode else "1360x800")
        self.win.minsize(920 if self.preview_mode else 1040, 620)
        self.win.transient(parent)

        self.pose_index = 0
        self.ligand_atoms = []
        self.ligand_bonds = []
        self.contacts = []
        self.nearby_residue_groups = []
        self.surface_cache = {}
        self.projected_pick_atoms = []
        self.selected_atom = None
        self.highlighted_residue = None
        self.measurements = []
        self.measure_pending_atom = None
        self.measure_mode = False
        self.drag_start = None
        self.drag_last = None
        self.drag_mode = "rotate"
        self.drag_distance = 0.0
        self.redraw_pending = False
        self.redraw_after_id = None

        self.yaw = math.radians(32.0)
        self.pitch = math.radians(-18.0)
        self.roll = 0.0
        self.scale = 38.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.view_center = (0.0, 0.0, 0.0)

        self.result_var = tk.StringVar()
        self.result_combo = None
        self.pose_var = tk.StringVar()
        self.receptor_style_var = tk.StringVar(value="Backbone" if self.preview_mode else "Hidden")
        self.ligand_style_var = tk.StringVar(value="Ball and stick")
        self.surface_mode_var = tk.StringVar(value="Binding pocket" if self.preview_mode else "Off")
        self.surface_radius_var = tk.DoubleVar(value=6.0)
        self.surface_quality_var = tk.StringVar(value="Medium")
        self.surface_opacity_var = tk.DoubleVar(value=45.0)
        self.nearby_cutoff_var = tk.DoubleVar(value=5.0)
        self.show_nearby_residues_var = tk.BooleanVar(value=True)
        self.show_residue_labels_var = tk.BooleanVar(value=True)
        self.show_hydrogens_var = tk.BooleanVar(value=False)
        self.show_labels_var = tk.BooleanVar(value=False)
        self.show_contacts_var = tk.BooleanVar(value=self.preview_mode)
        self.perspective_var = tk.BooleanVar(value=True)
        self.atom_detail_var = tk.StringVar(value="Click an atom to inspect it")
        self.status_var = tk.StringVar(value="Loading molecular scene…")
        self.measurement_var = tk.StringVar(value="No measurements")
        self.plip_status_var = tk.StringVar(value="Loading pose-specific PLIP summary…")
        self.plip_text = None
        self.plip_button = None

        self._build_ui(title)
        self._load_pose(0, refocus=False)
        self._bind_controls()
        self.win.bind("<Destroy>", self._on_destroy, add="+")
        self.win.after(80, self.reset_view)

    @staticmethod
    def _palette(night_mode):
        if night_mode:
            return {
                "bg": "#15191f", "panel": "#20262e", "panel2": "#29313b",
                "canvas": "#07111d", "canvas2": "#10283a", "fg": "#e9f0f7",
                "muted": "#9caebe", "accent": "#38bdf8", "accent2": "#22d3a6",
                "line": "#53677a", "select": "#ffd166", "surface": "#36b9d4",
                "danger": "#ff6577",
            }
        return {
            "bg": "#eaf0f5", "panel": "#ffffff", "panel2": "#dce8f1",
            "canvas": "#071522", "canvas2": "#16435e", "fg": "#15202b",
            "muted": "#516575", "accent": "#087db5", "accent2": "#008f72",
            "line": "#70899b", "select": "#ffb000", "surface": "#22a9c7",
            "danger": "#d43b55",
        }

    def apply_night_mode(self, night_mode):
        """Update an already-open pose viewer without disturbing its specialised canvas palette."""
        old_palette = self.palette
        self.night_mode = bool(night_mode)
        self.palette = self._palette(self.night_mode)
        new_palette = self.palette
        replacements = {
            str(old_palette[key]).lower(): new_palette[key]
            for key in old_palette
            if key in new_palette
        }

        def replace_option(widget, option):
            try:
                current = str(widget.cget(option)).lower()
                replacement = replacements.get(current)
                if replacement:
                    widget.configure(**{option: replacement})
            except (tk.TclError, AttributeError):
                pass

        def recolor(widget):
            try:
                if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame, tk.PanedWindow)):
                    replace_option(widget, "background")
                elif isinstance(widget, tk.LabelFrame):
                    replace_option(widget, "background")
                    replace_option(widget, "foreground")
                elif isinstance(widget, tk.Label):
                    replace_option(widget, "background")
                    replace_option(widget, "foreground")
                elif isinstance(widget, tk.Button):
                    widget.configure(
                        bg=new_palette["panel"], fg=new_palette["fg"],
                        activebackground=new_palette["panel2"], activeforeground=new_palette["fg"],
                    )
                elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                    widget.configure(
                        bg=new_palette["panel"], fg=new_palette["fg"],
                        activebackground=new_palette["panel"], activeforeground=new_palette["fg"],
                        selectcolor=new_palette["panel2"],
                    )
                elif isinstance(widget, tk.Scale):
                    widget.configure(
                        bg=new_palette["panel"], fg=new_palette["fg"],
                        activebackground=new_palette["accent"],
                        troughcolor=new_palette["panel2"], highlightbackground=new_palette["panel"],
                    )
                elif isinstance(widget, tk.Entry):
                    widget.configure(
                        bg=new_palette["panel2"], fg=new_palette["fg"],
                        readonlybackground=new_palette["panel2"], insertbackground=new_palette["fg"],
                        selectbackground=new_palette["accent"], selectforeground="#ffffff",
                    )
                elif isinstance(widget, tk.Text):
                    widget.configure(
                        bg=new_palette["panel2"], fg=new_palette["fg"],
                        insertbackground=new_palette["fg"],
                        selectbackground=new_palette["accent"], selectforeground="#ffffff",
                    )
                elif isinstance(widget, tk.Scrollbar):
                    widget.configure(
                        bg=new_palette["panel2"], activebackground=new_palette["accent"],
                        troughcolor=new_palette["panel"],
                    )
                elif isinstance(widget, tk.Canvas):
                    widget.configure(bg=new_palette["canvas"])
            except (tk.TclError, AttributeError):
                pass
            try:
                for child in widget.winfo_children():
                    recolor(child)
            except Exception:
                pass

        recolor(self.win)
        _vlip_set_window_dark_titlebar(self.win, self.night_mode)
        self.request_redraw()

    def _build_ui(self, title):
        palette = self.palette
        self.win.configure(bg=palette["bg"])

        header = tk.Frame(self.win, bg="#0b2538", padx=16, pady=11)
        header.pack(fill="x")
        viewer_heading = "VLiP 3D RECEPTOR PREVIEW" if self.preview_mode else "VLiP 3D POSE VIEWER"
        tk.Label(
            header, text=viewer_heading, bg="#0b2538", fg="#69d5ff",
            font=("TkDefaultFont", 9, "bold"), anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header, text=title, bg="#0b2538", fg="#ffffff",
            font=("TkDefaultFont", 17, "bold"), anchor="w",
        ).pack(anchor="w")
        details = []
        for key in ("ligand", "receptor", "run", "affinity_text"):
            value = self.result_info.get(key)
            if value not in (None, ""):
                label = "Affinity" if key == "affinity_text" else key.title()
                suffix = " kcal/mol" if key == "affinity_text" else ""
                details.append(f"{label}: {value}{suffix}")
        tk.Label(
            header, text="   •   ".join(details) or os.path.basename(self.source_path),
            bg="#0b2538", fg="#b8cad7", anchor="w",
        ).pack(anchor="w", pady=(3, 0))
        if self.preview_note:
            tk.Label(
                header, text=self.preview_note, bg="#0b2538", fg="#ffe6a1",
                anchor="w", justify="left", wraplength=1180,
            ).pack(anchor="w", fill="x", pady=(4, 0))

        toolbar = tk.Frame(self.win, bg=palette["panel"], padx=10, pady=7)
        toolbar.pack(fill="x")
        focus_button_text = "Fit docking region" if self.preview_mode else "Fit ligand"
        fit_scene_text = "Fit all" if self.preview_mode else "Fit nearby"
        for text_value, command in (
            (focus_button_text, self.fit_ligand),
            (fit_scene_text, self.fit_all),
            ("Reset view", self.reset_view),
            ("Measure", self.begin_measurement),
            ("Export SVG snapshot", self.export_svg),
            ("Help", self.show_help),
        ):
            tk.Button(toolbar, text=text_value, command=command, padx=10).pack(side="left", padx=(0, 6))
        tk.Label(
            toolbar, text="Drag: rotate   •   Shift-drag/middle: pan   •   Wheel: zoom   •   Click: inspect",
            bg=palette["panel"], fg=palette["muted"],
        ).pack(side="right", padx=6)

        body = tk.PanedWindow(
            self.win, orient="horizontal", sashwidth=7, bg=palette["panel2"],
            bd=0, relief="flat",
        )
        body.pack(fill="both", expand=True)

        canvas_panel = tk.Frame(body, bg=palette["canvas"])
        side_panel = tk.Frame(body, bg=palette["panel"], width=315)
        body.add(canvas_panel, stretch="always", minsize=560 if self.preview_mode else 430)
        body.add(side_panel, stretch="never", minsize=280, width=315)
        plip_panel = None
        if not self.preview_mode:
            plip_panel = tk.Frame(body, bg=palette["panel"], width=360, padx=10, pady=10)
            body.add(plip_panel, stretch="never", minsize=300, width=360)

        self.canvas = tk.Canvas(
            canvas_panel, bg=palette["canvas"], highlightthickness=0,
            cursor="crosshair", takefocus=True,
        )
        self.canvas.pack(fill="both", expand=True)

        notebook = ttk.Notebook(side_panel)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)
        display_tab = tk.Frame(notebook, bg=palette["panel"], padx=10, pady=10)
        inspect_tab = tk.Frame(notebook, bg=palette["panel"], padx=10, pady=10)
        notebook.add(display_tab, text="Display")
        notebook.add(inspect_tab, text="Inspect")

        if not self.preview_mode and len(self.result_options) > 1:
            self._section_label(display_tab, "LIGAND / DOCKING RESULT")
            result_values = [self._result_option_label(item) for item in self.result_options]
            self.result_combo = ttk.Combobox(
                display_tab, textvariable=self.result_var, values=result_values,
                state="readonly", width=34,
            )
            self.result_combo.pack(fill="x", pady=(2, 10))
            current_identity = self._result_identity(self.result_info)
            current_index = next((
                index for index, item in enumerate(self.result_options)
                if self._result_identity(item) == current_identity
            ), 0)
            self.result_combo.current(current_index)
            self.result_var.set(result_values[current_index])

        self._section_label(display_tab, "POSE")
        pose_values = []
        for index, model in enumerate(self.models, 1):
            affinity = model.get("affinity")
            score = f"  |  {affinity:g} kcal/mol" if affinity is not None else ""
            if self.preview_mode:
                label = f"Ligand model {index}" if model.get("atoms") else "Receptor / docking region"
            else:
                label = f"Pose {index}"
            pose_values.append(f"{label}{score}")
        self.pose_combo = ttk.Combobox(
            display_tab, textvariable=self.pose_var, values=pose_values,
            state="readonly", width=30,
        )
        self.pose_combo.pack(fill="x", pady=(2, 10))
        self.pose_var.set(pose_values[0])

        self._section_label(display_tab, "REPRESENTATION")
        if self.preview_mode:
            self._labeled_combo(display_tab, "Receptor", self.receptor_style_var,
                                ("Backbone", "Atoms", "Hidden"))
        self._labeled_combo(display_tab, "Ligand", self.ligand_style_var,                            ("Ball and stick", "Sticks", "Spacefill"))
        if self.preview_mode:
            self._labeled_combo(display_tab, "Receptor surface", self.surface_mode_var,
                                ("Off", "Binding pocket", "Full receptor"))
            self._labeled_combo(display_tab, "Surface quality", self.surface_quality_var,
                                ("Low", "Medium", "High"))

            tk.Label(display_tab, text="Pocket radius (Å)", bg=palette["panel"], fg=palette["fg"], anchor="w").pack(fill="x")
            tk.Scale(
                display_tab, from_=3.5, to=10.0, resolution=0.5, orient="horizontal",
                variable=self.surface_radius_var, showvalue=True, command=lambda _v: self._surface_changed(),
                bg=palette["panel"], fg=palette["fg"], highlightthickness=0,
            ).pack(fill="x", pady=(0, 5))
            tk.Label(display_tab, text="Surface opacity", bg=palette["panel"], fg=palette["fg"], anchor="w").pack(fill="x")
            tk.Scale(
                display_tab, from_=15, to=90, resolution=5, orient="horizontal",
                variable=self.surface_opacity_var, showvalue=True, command=lambda _v: self.request_redraw(),
                bg=palette["panel"], fg=palette["fg"], highlightthickness=0,
            ).pack(fill="x", pady=(0, 8))

        self._section_label(display_tab, "NEARBY RESIDUES")
        tk.Label(
            display_tab, text="Distance from ligand (Å)", bg=palette["panel"],
            fg=palette["fg"], anchor="w",
        ).pack(fill="x")
        tk.Scale(
            display_tab, from_=3.0, to=10.0, resolution=0.5, orient="horizontal",
            variable=self.nearby_cutoff_var, showvalue=True,
            command=lambda _v: self._nearby_changed(),
            bg=palette["panel"], fg=palette["fg"], highlightthickness=0,
        ).pack(fill="x", pady=(0, 5))

        nearby_options = [("Label nearby residues", self.show_residue_labels_var)]
        if self.preview_mode:
            nearby_options.insert(0, ("Show nearby residues", self.show_nearby_residues_var))
        for label, variable in nearby_options:
            tk.Checkbutton(
                display_tab, text=label, variable=variable, command=self.request_redraw,
                bg=palette["panel"], fg=palette["fg"], activebackground=palette["panel"],
                activeforeground=palette["fg"], selectcolor=palette["panel2"], anchor="w",
            ).pack(fill="x", pady=1)

        for label, variable in (
            ("Show hydrogens", self.show_hydrogens_var),
            ("Ligand atom labels", self.show_labels_var),
            ("Geometry contact guides", self.show_contacts_var),
            ("Perspective depth", self.perspective_var),
        ):
            tk.Checkbutton(
                display_tab, text=label, variable=variable, command=self.request_redraw,
                bg=palette["panel"], fg=palette["fg"], activebackground=palette["panel"],
                activeforeground=palette["fg"], selectcolor=palette["panel2"], anchor="w",
            ).pack(fill="x", pady=1)

        tk.Label(
            display_tab,
            text=(
                "Nearby residues include each complete residue when any of its atoms is within the cutoff. "
                + (
                    "The surface is a fast visual envelope; use dedicated chemistry software for quantitative solvent surfaces."
                    if self.preview_mode
                    else "Only these nearby receptor residues are drawn in the Pose Viewer."
                )
            ),
            bg=palette["panel"], fg=palette["muted"], justify="left", wraplength=265,
        ).pack(fill="x", pady=(12, 5))

        self._section_label(inspect_tab, "SELECTED ATOM")
        self.atom_detail_entry = tk.Entry(
            inspect_tab, textvariable=self.atom_detail_var, state="readonly",
            readonlybackground=palette["panel2"], fg=palette["fg"], relief="flat",
        )
        self.atom_detail_entry.pack(fill="x", pady=(2, 5))
        atom_buttons = tk.Frame(inspect_tab, bg=palette["panel"])
        atom_buttons.pack(fill="x", pady=(0, 10))
        tk.Button(atom_buttons, text="Copy details", command=self.copy_selected_atom).pack(side="left", padx=(0, 5))
        tk.Button(atom_buttons, text="Centre atom", command=self.center_selected_atom).pack(side="left", padx=(0, 5))
        tk.Button(atom_buttons, text="Highlight residue", command=self.highlight_selected_residue).pack(side="left")

        self._section_label(inspect_tab, "MEASUREMENTS")
        tk.Label(
            inspect_tab, textvariable=self.measurement_var, bg=palette["panel"], fg=palette["fg"],
            justify="left", anchor="w", wraplength=270,
        ).pack(fill="x", pady=(2, 5))
        tk.Button(inspect_tab, text="Clear measurements", command=self.clear_measurements).pack(anchor="w", pady=(0, 10))

        self._section_label(inspect_tab, "CONTACT GUIDES")
        contact_frame = tk.Frame(inspect_tab, bg=palette["panel"])
        contact_frame.pack(fill="both", expand=True, pady=(2, 5))
        self.contact_tree = ttk.Treeview(
            contact_frame, columns=("kind", "residue", "distance"), show="headings", height=9,
        )
        self.contact_tree.heading("kind", text="Type")
        self.contact_tree.heading("residue", text="Receptor residue")
        self.contact_tree.heading("distance", text="Å")
        self.contact_tree.column("kind", width=80, anchor="w")
        self.contact_tree.column("residue", width=115, anchor="w")
        self.contact_tree.column("distance", width=45, anchor="e")
        contact_scroll = tk.Scrollbar(contact_frame, command=self.contact_tree.yview)
        self.contact_tree.config(yscrollcommand=contact_scroll.set)
        contact_scroll.pack(side="right", fill="y")
        self.contact_tree.pack(side="left", fill="both", expand=True)
        tk.Label(
            inspect_tab,
            text="These are geometry guides inferred from atom types and distances. The panel beside the viewer shows the matched PLIP summary for the selected pose.",
            bg=palette["panel"], fg=palette["muted"], justify="left", wraplength=270,
        ).pack(fill="x", pady=(4, 7))
        report_row = tk.Frame(inspect_tab, bg=palette["panel"])
        report_row.pack(fill="x")
        source_button_text = "Open ligand file" if self.preview_mode and self.source_path != self.receptor_path else (
            "Open receptor file" if self.preview_mode else "Open pose file"
        )
        tk.Button(
            report_row, text=source_button_text, command=lambda: self._open_path(self.source_path),
            state="normal" if self.source_path else "disabled",
        ).pack(side="left")

        if plip_panel is not None:
            self._section_label(plip_panel, "POSE-SPECIFIC PLIP")
            tk.Label(
                plip_panel, textvariable=self.plip_status_var, bg=palette["panel"],
                fg=palette["fg"], anchor="w", justify="left", wraplength=320,
            ).pack(fill="x", pady=(2, 7))
            plip_text_frame = tk.Frame(plip_panel, bg=palette["panel"])
            plip_text_frame.pack(fill="both", expand=True)
            plip_scroll = tk.Scrollbar(plip_text_frame)
            plip_scroll.pack(side="right", fill="y")
            self.plip_text = tk.Text(
                plip_text_frame, wrap="word", state="disabled", relief="flat",
                bg=palette["panel2"], fg=palette["fg"], insertbackground=palette["fg"],
                selectbackground=palette["accent"], selectforeground="#ffffff",
                padx=8, pady=8, yscrollcommand=plip_scroll.set,
                font="TkFixedFont",
            )
            self.plip_text.pack(side="left", fill="both", expand=True)
            plip_scroll.configure(command=self.plip_text.yview)
            plip_actions = tk.Frame(plip_panel, bg=palette["panel"])
            plip_actions.pack(fill="x", pady=(8, 0))
            plip_actions.columnconfigure(0, weight=1)
            plip_actions.columnconfigure(1, weight=1)
            self.plip_button = tk.Button(
                plip_actions, text="Open full PLIP report", command=self.open_plip_report,
                state="disabled",
            )
            self.plip_button.grid(row=0, column=0, sticky="ew", padx=(0, 3), pady=(0, 5))
            tk.Button(
                plip_actions, text="View in PyMOL", command=self.view_in_pymol,
            ).grid(row=0, column=1, sticky="ew", padx=(3, 0), pady=(0, 5))

        status = tk.Frame(self.win, bg=palette["panel2"], padx=10, pady=5)
        status.pack(fill="x")
        tk.Label(status, textvariable=self.status_var, bg=palette["panel2"], fg=palette["fg"], anchor="w").pack(side="left", fill="x", expand=True)
        shortcut_focus = "region" if self.preview_mode else "ligand"
        shortcut_all = "all" if self.preview_mode else "nearby"
        tk.Label(status, text=f"F: {shortcut_focus}  •  A: {shortcut_all}  •  R: reset  •  M: measure  •  Esc: clear selection",
                 bg=palette["panel2"], fg=palette["muted"]).pack(side="right")

    def _section_label(self, parent, text_value):
        tk.Label(
            parent, text=text_value, bg=self.palette["panel"], fg=self.palette["accent"],
            font=("TkDefaultFont", 9, "bold"), anchor="w",
        ).pack(fill="x", pady=(2, 3))

    def _labeled_combo(self, parent, label, variable, values):
        row = tk.Frame(parent, bg=self.palette["panel"])
        row.pack(fill="x", pady=2)
        tk.Label(row, text=label, width=15, anchor="w", bg=self.palette["panel"], fg=self.palette["fg"]).pack(side="left")
        combo = ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=17)
        combo.pack(side="right", fill="x", expand=True)
        combo.bind("<<ComboboxSelected>>", lambda _event: self._surface_changed())
        return combo

    @staticmethod
    def _result_identity(result):
        result = result or {}
        dock_file = str(result.get("dock_file") or "")
        try:
            dock_file = os.path.normcase(os.path.abspath(dock_file)) if dock_file else ""
        except Exception:
            pass
        return (
            dock_file,
            str(result.get("ligand") or ""),
            str(result.get("receptor") or ""),
            int(result.get("run", 0) or 0),
        )

    @staticmethod
    def _result_option_label(result):
        ligand = str(result.get("ligand") or "Ligand")
        receptor = str(result.get("receptor") or "receptor")
        run_index = int(result.get("run", 0) or 0)
        affinity = result.get("affinity")
        affinity_text = f"  |  {float(affinity):g} kcal/mol" if affinity is not None else ""
        return f"{ligand}  |  {receptor}  |  Run {run_index}{affinity_text}"

    def _result_selected(self, _event=None):
        if self.result_combo is None or not self.result_options:
            return
        try:
            index = self.result_combo.current()
        except Exception:
            index = -1
        if index < 0 or index >= len(self.result_options):
            return
        selected = self.result_options[index]
        if self._result_identity(selected) == self._result_identity(self.result_info):
            return
        callback = self.result_switch_callback
        if callback is None:
            return
        self.status_var.set(
            f"Loading {selected.get('ligand', 'ligand')} / {selected.get('receptor', 'receptor')} / Run {selected.get('run', '?')}…"
        )
        try:
            replacement = callback(dict(selected))
        except Exception as exc:
            messagebox.showerror("Could not switch docking result", str(exc), parent=self.win)
            replacement = None
        if replacement is not None:
            try:
                self.win.after_idle(self.win.destroy)
            except Exception:
                pass
        else:
            current_identity = self._result_identity(self.result_info)
            current_index = next((
                item_index for item_index, item in enumerate(self.result_options)
                if self._result_identity(item) == current_identity
            ), 0)
            try:
                self.result_combo.current(current_index)
            except Exception:
                pass

    def _bind_controls(self):
        if self.result_combo is not None:
            self.result_combo.bind("<<ComboboxSelected>>", self._result_selected)
        self.pose_combo.bind("<<ComboboxSelected>>", self._pose_selected)
        self.canvas.bind("<Configure>", lambda _event: self.request_redraw())
        self.canvas.bind("<ButtonPress-1>", self._mouse_press)
        self.canvas.bind("<B1-Motion>", self._mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._mouse_release)
        self.canvas.bind("<ButtonPress-2>", lambda event: self._mouse_press(event, force_pan=True))
        self.canvas.bind("<B2-Motion>", self._mouse_drag)
        self.canvas.bind("<ButtonRelease-2>", self._mouse_release)
        self.canvas.bind("<Button-3>", self._canvas_context_menu)
        self.canvas.bind("<MouseWheel>", self._mouse_wheel)
        self.canvas.bind("<Button-4>", lambda event: self._zoom_at(event.x, event.y, 1.12))
        self.canvas.bind("<Button-5>", lambda event: self._zoom_at(event.x, event.y, 1 / 1.12))
        self.win.bind("<KeyPress-f>", lambda _event: self.fit_ligand())
        self.win.bind("<KeyPress-a>", lambda _event: self.fit_all())
        self.win.bind("<KeyPress-r>", lambda _event: self.reset_view())
        self.win.bind("<KeyPress-m>", lambda _event: self.begin_measurement())
        self.win.bind("<Escape>", lambda _event: self.clear_selection())

    def _pose_selected(self, _event=None):
        try:
            index = self.pose_combo.current()
        except Exception:
            index = 0
        self._load_pose(max(0, index), refocus=True)

    def _proximity_atoms(self):
        """Atoms used as the pocket centre: ligand first, docking focus as fallback."""
        return self.ligand_atoms or self.focus_atoms

    def _update_nearby_residues(self):
        focus = self._proximity_atoms()
        cutoff = max(0.1, float(self.nearby_cutoff_var.get()))
        self.nearby_residue_groups = molecular_nearby_residue_groups(
            self.receptor_atoms, focus, cutoff
        ) if focus else []

    def _nearby_changed(self):
        self._update_nearby_residues()
        self.surface_cache.clear()
        self.request_redraw()

    def _load_pose(self, index, refocus=True):
        self.pose_index = min(max(0, int(index)), len(self.models) - 1)
        self.ligand_atoms = list(self.models[self.pose_index].get("atoms") or [])
        self.ligand_bonds = infer_molecular_bonds(self.ligand_atoms)
        self.contacts = molecular_contact_guides(self.receptor_atoms, self.ligand_atoms)
        self._update_nearby_residues()
        self.selected_atom = None
        self.highlighted_residue = None
        self.measure_pending_atom = None
        self.atom_detail_var.set("Click an atom to inspect it")
        self._refresh_contacts()
        self._refresh_plip_report()
        if refocus:
            self.fit_ligand()
        else:
            self.request_redraw()

    def _refresh_contacts(self):
        self.contact_tree.delete(*self.contact_tree.get_children())
        for contact in self.contacts:
            atom = contact["receptor"]
            residue = molecular_residue_label(atom)
            self.contact_tree.insert("", "end", values=(contact["kind"], residue, f"{contact['distance']:.2f}"))

    def _refresh_plip_report(self):
        """Show only the PLIP summary explicitly belonging to the selected pose."""
        pose_number = self.pose_index + 1
        report_path = self.plip_reports_by_pose.get(pose_number, "")
        self.current_plip_report = report_path if report_path and os.path.isfile(report_path) else ""
        self.current_full_plip_report = molecular_full_plip_report(self.current_plip_report)

        if self.current_plip_report:
            try:
                with open(self.current_plip_report, "r", encoding="utf-8", errors="replace") as source:
                    report_text = source.read()
                self.plip_status_var.set(
                    f"Pose {pose_number} • {os.path.basename(self.current_plip_report)}"
                )
            except OSError as exc:
                self.current_plip_report = ""
                report_text = f"The PLIP summary for Pose {pose_number} could not be read.\n\n{exc}"
                self.plip_status_var.set(f"Pose {pose_number} • PLIP summary could not be read")
        elif self.plip_reports_by_pose:
            report_text = (
                f"No PLIP summary exists for Pose {pose_number}.\n\n"
                "A report from a different pose is not substituted."
            )
            self.plip_status_var.set(f"Pose {pose_number} • no matching PLIP summary")
        else:
            report_text = (
                f"No pose-specific PLIP summary is available for Pose {pose_number}.\n\n"
                "PLIP may have been disabled for this docking run."
            )
            self.plip_status_var.set(f"Pose {pose_number} • PLIP unavailable")

        if self.plip_text is not None:
            self.plip_text.configure(state="normal")
            self.plip_text.delete("1.0", "end")
            self.plip_text.insert("1.0", report_text.strip() or "The matched PLIP summary is empty.")
            self.plip_text.configure(state="disabled")
            self.plip_text.yview_moveto(0.0)
        if self.plip_button is not None:
            self.plip_button.configure(
                state="normal" if self.current_plip_report else "disabled",
                text=(
                    "Open full PLIP report"
                    if self.current_full_plip_report else "Open saved PLIP summary"
                ),
            )

    def _surface_changed(self):
        self.surface_cache.clear()
        self.request_redraw()

    def reset_view(self):
        self.yaw = math.radians(32.0)
        self.pitch = math.radians(-18.0)
        self.roll = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.fit_ligand()

    def fit_ligand(self):
        focus = self._proximity_atoms()
        if self.preview_mode:
            cutoff = max(4.0, float(self.nearby_cutoff_var.get()))
            pocket = molecular_nearby_atoms(self.receptor_atoms, focus, cutoff)
        else:
            pocket = [
                atom
                for group in self.nearby_residue_groups
                for atom in group.get("atoms", [])
            ]
        scene_atoms = list(focus) + pocket
        if self.preview_mode:
            scene_atoms += self._box_scene_atoms()
        self._fit_atoms(scene_atoms, fallback=focus or self.receptor_atoms)

    def fit_all(self):
        if self.preview_mode:
            scene_atoms = self.receptor_atoms + self.ligand_atoms + self._box_scene_atoms()
        else:
            nearby_atoms = [
                atom
                for group in self.nearby_residue_groups
                for atom in group.get("atoms", [])
            ]
            scene_atoms = self.ligand_atoms + nearby_atoms
        self._fit_atoms(scene_atoms, fallback=self._proximity_atoms())

    def _box_scene_atoms(self):
        """Return the eight preview-box corners as lightweight scene atoms."""
        try:
            cx, cy, cz = self.box_geometry["center"]
            sx, sy, sz = self.box_geometry["size"]
        except (KeyError, TypeError, ValueError):
            return []
        corners = []
        for x in (cx - sx / 2.0, cx + sx / 2.0):
            for y in (cy - sy / 2.0, cy + sy / 2.0):
                for z in (cz - sz / 2.0, cz + sz / 2.0):
                    corners.append({
                        "x": x, "y": y, "z": z, "source": "box", "element": "C",
                        "name": "BOX", "record": "", "chain": "-", "resseq": 0,
                        "icode": "", "resname": "BOX", "serial": 0,
                    })
        return corners

    def _fit_atoms(self, atoms, fallback=None):
        atoms = list(atoms or fallback or [])
        if not atoms:
            return
        self.view_center = molecular_center(atoms)
        spans = (
            max(atom["x"] for atom in atoms) - min(atom["x"] for atom in atoms),
            max(atom["y"] for atom in atoms) - min(atom["y"] for atom in atoms),
            max(atom["z"] for atom in atoms) - min(atom["z"] for atom in atoms),
        )
        width = max(500, self.canvas.winfo_width())
        height = max(400, self.canvas.winfo_height())
        largest = max(3.0, *spans)
        self.scale = max(1.3, min(105.0, min(width, height) * 0.70 / largest))
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.request_redraw()

    def _rotated(self, atom):
        x = atom["x"] - self.view_center[0]
        y = atom["y"] - self.view_center[1]
        z = atom["z"] - self.view_center[2]
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        cr, sr = math.cos(self.roll), math.sin(self.roll)
        x1, z1 = cy * x + sy * z, -sy * x + cy * z
        y2, z2 = cp * y - sp * z1, sp * y + cp * z1
        x3, y3 = cr * x1 - sr * y2, sr * x1 + cr * y2
        return x3, y3, z2

    def _project(self, atom):
        x, y, depth = self._rotated(atom)
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        perspective = 1.0
        if self.perspective_var.get():
            focal = 42.0
            perspective = max(0.35, min(2.3, focal / max(8.0, focal + depth)))
        return (
            width / 2 + self.pan_x + x * self.scale * perspective,
            height / 2 + self.pan_y - y * self.scale * perspective,
            depth,
            perspective,
        )

    def request_redraw(self):
        if self.redraw_pending:
            return
        self.redraw_pending = True
        try:
            self.redraw_after_id = self.win.after_idle(self._draw_scene)
        except tk.TclError:
            self.redraw_pending = False
            self.redraw_after_id = None

    def _on_destroy(self, event):
        if event.widget is not self.win:
            return
        if self.redraw_after_id is not None:
            try:
                self.win.after_cancel(self.redraw_after_id)
            except tk.TclError:
                pass
        self.redraw_after_id = None
        self.redraw_pending = False

    def _draw_scene(self):
        self.redraw_pending = False
        self.redraw_after_id = None
        if not self.canvas.winfo_exists():
            return
        canvas = self.canvas
        palette = self.palette
        canvas.delete("all")
        width = max(1, canvas.winfo_width())
        height = max(1, canvas.winfo_height())
        self.projected_pick_atoms = []

        bands = 18
        for index in range(bands):
            colour = blend_hex_colors(palette["canvas"], palette["canvas2"], index / max(1, bands - 1))
            y1 = height * index / bands
            y2 = height * (index + 1) / bands + 1
            canvas.create_rectangle(0, y1, width, y2, fill=colour, outline=colour, tags=("background",))
        canvas.create_text(
            16, 15, anchor="nw",
            text=(
                "RECEPTOR / DOCKING PREVIEW"
                if self.preview_mode
                else f"POSE {self.pose_index + 1} / {len(self.models)}"
            ),
            fill="#7edcff", font=("TkDefaultFont", 10, "bold"), tags=("overlay",),
        )

        # The docking Pose Viewer deliberately never draws the full receptor.
        # Full-receptor and surface views remain available in Receptor Preview.
        if self.preview_mode:
            if self.surface_mode_var.get() != "Off" and self.receptor_atoms:
                self._draw_surface()
            if self.box_geometry:
                self._draw_docking_box()
            if self.receptor_style_var.get() == "Backbone":
                self._draw_receptor_backbone()
            elif self.receptor_style_var.get() == "Atoms":
                self._draw_receptor_atoms()
        if self.show_nearby_residues_var.get():
            self._draw_nearby_residues()
        if self.show_contacts_var.get():
            self._draw_contacts()
        self._draw_ligand()
        self._draw_measurements()
        self._draw_selection()

        affinity = self.models[self.pose_index].get("affinity")
        affinity_text = f" | affinity {affinity:g} kcal/mol" if affinity is not None else ""
        nearby_count = len(self.nearby_residue_groups)
        nearby_atom_count = sum(len(group.get("atoms", [])) for group in self.nearby_residue_groups)
        scene_name = "Preview" if self.preview_mode else f"Pose {self.pose_index + 1}"
        if self.preview_mode:
            surface_count = len(self._surface_atoms()) if self.surface_mode_var.get() != "Off" else 0
            self.status_var.set(
                f"{scene_name}: {len(self.ligand_atoms)} ligand atoms, "
                f"{len(self.receptor_atoms)} receptor atoms, {nearby_count} nearby residues, "
                f"{len(self.contacts)} contact guides"
                f"{affinity_text} | surface atoms {surface_count}"
            )
        else:
            plip_text = "matched PLIP loaded" if self.current_plip_report else "no matched PLIP"
            self.status_var.set(
                f"{scene_name}: ligand + {nearby_count} nearby residues "
                f"({nearby_atom_count} receptor atoms shown), {plip_text}{affinity_text}"
            )

    def _surface_atoms(self):
        mode = self.surface_mode_var.get()
        radius = round(float(self.surface_radius_var.get()), 1)
        quality = self.surface_quality_var.get()
        key = (self.pose_index, mode, radius, quality, self.show_hydrogens_var.get())
        cached = self.surface_cache.get(key)
        if cached is not None:
            return cached
        atoms = self.receptor_atoms
        if mode == "Binding pocket":
            atoms = molecular_nearby_atoms(self.receptor_atoms, self._proximity_atoms(), radius)
        if not self.show_hydrogens_var.get():
            atoms = [atom for atom in atoms if atom["element"] != "H"]
        limits = {"Low": 450, "Medium": 900, "High": 1800}
        maximum = limits.get(quality, 900)
        if len(atoms) > maximum:
            step = int(math.ceil(len(atoms) / maximum))
            atoms = atoms[::step]
        self.surface_cache[key] = atoms
        return atoms

    def _draw_surface(self):
        atoms = self._surface_atoms()
        projected = [(self._project(atom), atom) for atom in atoms]
        projected.sort(key=lambda item: item[0][2], reverse=True)
        opacity = float(self.surface_opacity_var.get())
        if opacity < 33:
            stipple = "gray75"
        elif opacity < 58:
            stipple = "gray50"
        elif opacity < 80:
            stipple = "gray25"
        else:
            stipple = ""
        for (sx, sy, depth, perspective), atom in projected:
            radius = MOLECULAR_VDW_RADII.get(atom["element"], 1.7) * self.scale * perspective * 0.42
            radius = max(2.5, min(18.0, radius))
            element_colour = MOLECULAR_ELEMENT_COLORS.get(atom["element"], "#a7b2bd")
            fill = blend_hex_colors(self.palette["surface"], element_colour, 0.32)
            outline = blend_hex_colors(fill, "#ffffff", 0.28)
            kwargs = {"fill": fill, "outline": outline, "width": 1, "tags": ("surface",)}
            if stipple:
                kwargs["stipple"] = stipple
            self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius, **kwargs)
            self.projected_pick_atoms.append((sx, sy, max(7.0, radius), depth, atom))

    def _draw_docking_box(self):
        corners = self._box_scene_atoms()
        if len(corners) != 8:
            return
        projected = [(atom, self._project(atom)) for atom in corners]
        for first_index, second_index in combinations(range(len(corners)), 2):
            first = corners[first_index]
            second = corners[second_index]
            changed_axes = sum(
                abs(first[axis] - second[axis]) > 1e-9 for axis in ("x", "y", "z")
            )
            if changed_axes != 1:
                continue
            first_point = projected[first_index][1]
            second_point = projected[second_index][1]
            self.canvas.create_line(
                first_point[0], first_point[1], second_point[0], second_point[1],
                fill="#49c8ff", width=2, dash=(7, 4), tags=("docking_box",),
            )

        try:
            cx, cy, cz = self.box_geometry["center"]
        except (KeyError, TypeError, ValueError):
            return
        centre = {
            "x": cx, "y": cy, "z": cz, "source": "box", "element": "C",
            "name": "CENTRE", "record": "", "chain": "-", "resseq": 0,
            "icode": "", "resname": "BOX", "serial": 0,
        }
        sx, sy, _depth, _perspective = self._project(centre)
        self.canvas.create_line(sx - 8, sy, sx + 8, sy, fill="#63f2b5", width=2)
        self.canvas.create_line(sx, sy - 8, sx, sy + 8, fill="#63f2b5", width=2)
        self.canvas.create_text(
            sx + 10, sy - 8, anchor="sw", text="Docking centre",
            fill="#9dffd4", font=("TkDefaultFont", 8, "bold"), tags=("docking_box",),
        )

    def _draw_nearby_residues(self):
        groups = self.nearby_residue_groups[:160]
        show_hydrogens = self.show_hydrogens_var.get()
        for group in reversed(groups):
            atoms = [
                atom for atom in group["atoms"]
                if show_hydrogens or atom["element"] != "H"
            ]
            if not atoms:
                continue
            projected = [self._project(atom) for atom in atoms]
            for first_index, second_index in infer_molecular_bonds(atoms, maximum_atoms=160):
                first = projected[first_index]
                second = projected[second_index]
                midpoint = ((first[0] + second[0]) / 2.0, (first[1] + second[1]) / 2.0)
                first_colour = MOLECULAR_ELEMENT_COLORS.get(atoms[first_index]["element"], "#aeb8c2")
                second_colour = MOLECULAR_ELEMENT_COLORS.get(atoms[second_index]["element"], "#aeb8c2")
                first_colour = blend_hex_colors(first_colour, self.palette["accent2"], 0.32)
                second_colour = blend_hex_colors(second_colour, self.palette["accent2"], 0.32)
                self.canvas.create_line(
                    first[0], first[1], midpoint[0], midpoint[1],
                    fill=first_colour, width=2, tags=("nearby_residue",),
                )
                self.canvas.create_line(
                    midpoint[0], midpoint[1], second[0], second[1],
                    fill=second_colour, width=2, tags=("nearby_residue",),
                )

            ordered = sorted(range(len(atoms)), key=lambda index: projected[index][2], reverse=True)
            for index in ordered:
                atom = atoms[index]
                sx, sy, depth, perspective = projected[index]
                radius = max(2.0, min(4.5, 2.7 * perspective))
                colour = MOLECULAR_ELEMENT_COLORS.get(atom["element"], "#aeb8c2")
                outline = blend_hex_colors(self.palette["accent2"], "#ffffff", 0.35)
                self.canvas.create_oval(
                    sx - radius, sy - radius, sx + radius, sy + radius,
                    fill=colour, outline=outline, width=1, tags=("nearby_residue",),
                )
                self.projected_pick_atoms.append((sx, sy, 7.0, depth, atom))

        if not self.show_residue_labels_var.get():
            return
        for group in groups[:80]:
            atoms = [atom for atom in group["atoms"] if show_hydrogens or atom["element"] != "H"]
            if not atoms:
                continue
            anchor_atom = next((atom for atom in atoms if atom["name"].upper() == "CA"), atoms[0])
            sx, sy, _depth, _perspective = self._project(anchor_atom)
            label = f"{group['label']}  {group['distance']:.1f} Å"
            self.canvas.create_text(
                sx + 6, sy - 6, anchor="sw", text=label,
                fill="#b9ffe9", font=("TkDefaultFont", 8, "bold"),
                tags=("residue_label",),
            )

    def _backbone_atoms(self):
        return [
            atom for atom in self.receptor_atoms
            if atom["record"] == "ATOM" and atom["name"].upper() == "CA"
            and (self.show_hydrogens_var.get() or atom["element"] != "H")
        ]

    def _draw_receptor_backbone(self):
        atoms = self._backbone_atoms()
        previous_by_chain = {}
        for atom in atoms:
            point = self._project(atom)
            previous = previous_by_chain.get(atom["chain"])
            if previous and molecular_distance(previous[0], atom) <= 4.7:
                old_point = previous[1]
                colour = blend_hex_colors("#68a5c4", self.palette["canvas"], 0.18)
                self.canvas.create_line(
                    old_point[0], old_point[1], point[0], point[1],
                    fill=colour, width=2, smooth=True, tags=("receptor",),
                )
            previous_by_chain[atom["chain"]] = (atom, point)
            self.projected_pick_atoms.append((point[0], point[1], 6.0, point[2], atom))
        if self.highlighted_residue:
            self._draw_highlighted_residue()

    def _draw_receptor_atoms(self):
        atoms = [atom for atom in self.receptor_atoms if self.show_hydrogens_var.get() or atom["element"] != "H"]
        if len(atoms) > 3500:
            atoms = atoms[::int(math.ceil(len(atoms) / 3500))]
        projected = [(self._project(atom), atom) for atom in atoms]
        projected.sort(key=lambda item: item[0][2], reverse=True)
        for (sx, sy, depth, perspective), atom in projected:
            radius = max(1.2, min(4.0, 1.7 * perspective))
            colour = blend_hex_colors(MOLECULAR_ELEMENT_COLORS.get(atom["element"], "#9ba8b5"), self.palette["canvas"], 0.28)
            self.canvas.create_oval(sx - radius, sy - radius, sx + radius, sy + radius,
                                    fill=colour, outline="", tags=("receptor",))
            self.projected_pick_atoms.append((sx, sy, 6.0, depth, atom))
        if self.highlighted_residue:
            self._draw_highlighted_residue()

    def _draw_highlighted_residue(self):
        key = self.highlighted_residue
        for atom in self.receptor_atoms:
            if molecular_residue_key(atom) != key:
                continue
            sx, sy, depth, _perspective = self._project(atom)
            self.canvas.create_oval(
                sx - 4, sy - 4, sx + 4, sy + 4,
                fill=self.palette["select"], outline="#ffffff", width=1,
                tags=("highlight",),
            )
            self.projected_pick_atoms.append((sx, sy, 8.0, depth, atom))

    def _draw_contacts(self):
        colours = {"Polar": "#55d6ff", "Hydrophobic": "#f7c95c", "Close": "#ff7d95"}
        for contact in self.contacts[:70]:
            first = self._project(contact["ligand"])
            second = self._project(contact["receptor"])
            self.canvas.create_line(
                first[0], first[1], second[0], second[1],
                fill=colours.get(contact["kind"], "#ffffff"), width=1,
                dash=(4, 4), tags=("contact",),
            )

    def _draw_ligand(self):
        visible_ids = {
            index for index, atom in enumerate(self.ligand_atoms)
            if self.show_hydrogens_var.get() or atom["element"] != "H"
        }
        projected = {index: self._project(atom) for index, atom in enumerate(self.ligand_atoms) if index in visible_ids}
        style = self.ligand_style_var.get()
        bond_width = 4 if style == "Sticks" else 3
        for first_index, second_index in self.ligand_bonds:
            if first_index not in projected or second_index not in projected:
                continue
            first = projected[first_index]
            second = projected[second_index]
            first_colour = MOLECULAR_ELEMENT_COLORS.get(self.ligand_atoms[first_index]["element"], "#aeb8c2")
            second_colour = MOLECULAR_ELEMENT_COLORS.get(self.ligand_atoms[second_index]["element"], "#aeb8c2")
            midpoint = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
            self.canvas.create_line(first[0], first[1], midpoint[0], midpoint[1], fill=first_colour,
                                    width=bond_width, tags=("ligand",))
            self.canvas.create_line(midpoint[0], midpoint[1], second[0], second[1], fill=second_colour,
                                    width=bond_width, tags=("ligand",))

        ordered = sorted(visible_ids, key=lambda index: projected[index][2], reverse=True)
        for index in ordered:
            atom = self.ligand_atoms[index]
            sx, sy, depth, perspective = projected[index]
            if style == "Sticks":
                radius = 2.7
            elif style == "Spacefill":
                radius = MOLECULAR_VDW_RADII.get(atom["element"], 1.7) * self.scale * perspective * 0.26
                radius = max(5.0, min(24.0, radius))
            else:
                radius = max(4.0, min(10.0, 5.2 * perspective))
            colour = MOLECULAR_ELEMENT_COLORS.get(atom["element"], "#aeb8c2")
            outline = blend_hex_colors(colour, "#ffffff", 0.48)
            self.canvas.create_oval(
                sx - radius, sy - radius, sx + radius, sy + radius,
                fill=colour, outline=outline, width=1, tags=("ligand",),
            )
            self.projected_pick_atoms.append((sx, sy, max(8.0, radius), depth, atom))
            if self.show_labels_var.get() and len(visible_ids) <= 180:
                self.canvas.create_text(
                    sx + radius + 2, sy - radius - 1, anchor="sw", text=atom["name"],
                    fill="#e8f7ff", font=("TkDefaultFont", 8), tags=("labels",),
                )

    def _draw_selection(self):
        if self.selected_atom is None:
            return
        sx, sy, _depth, _perspective = self._project(self.selected_atom)
        self.canvas.create_oval(
            sx - 12, sy - 12, sx + 12, sy + 12,
            outline=self.palette["select"], width=3, tags=("selection",),
        )
        self.canvas.create_line(sx - 16, sy, sx - 8, sy, fill=self.palette["select"], width=2)
        self.canvas.create_line(sx + 8, sy, sx + 16, sy, fill=self.palette["select"], width=2)
        self.canvas.create_line(sx, sy - 16, sx, sy - 8, fill=self.palette["select"], width=2)
        self.canvas.create_line(sx, sy + 8, sx, sy + 16, fill=self.palette["select"], width=2)

    def _draw_measurements(self):
        for first, second, distance in self.measurements:
            p1 = self._project(first)
            p2 = self._project(second)
            self.canvas.create_line(p1[0], p1[1], p2[0], p2[1], fill="#ffdf73", width=2,
                                    dash=(6, 3), tags=("measurement",))
            self.canvas.create_text(
                (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2 - 8,
                text=f"{distance:.2f} Å", fill="#fff1a8", font=("TkDefaultFont", 9, "bold"),
                tags=("measurement",),
            )
        if self.measure_pending_atom is not None:
            point = self._project(self.measure_pending_atom)
            self.canvas.create_oval(point[0] - 10, point[1] - 10, point[0] + 10, point[1] + 10,
                                    outline="#ffdf73", width=2, dash=(3, 2), tags=("measurement",))

    def _mouse_press(self, event, force_pan=False):
        self.canvas.focus_set()
        self.drag_start = (event.x, event.y)
        self.drag_last = (event.x, event.y)
        self.drag_distance = 0.0
        self.drag_mode = "pan" if force_pan or (getattr(event, "state", 0) & 0x0001) else "rotate"

    def _mouse_drag(self, event):
        if self.drag_last is None:
            return
        dx = event.x - self.drag_last[0]
        dy = event.y - self.drag_last[1]
        self.drag_distance += abs(dx) + abs(dy)
        if self.drag_mode == "pan":
            self.pan_x += dx
            self.pan_y += dy
        else:
            self.yaw += dx * 0.009
            self.pitch += dy * 0.009
            self.pitch = max(-math.pi / 2, min(math.pi / 2, self.pitch))
        self.drag_last = (event.x, event.y)
        self.request_redraw()

    def _mouse_release(self, event):
        if self.drag_start is not None and self.drag_distance < 5.0:
            self._select_nearest(event.x, event.y)
        self.drag_start = None
        self.drag_last = None

    def _mouse_wheel(self, event):
        factor = 1.12 if event.delta > 0 else 1 / 1.12
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, x, y, factor):
        old_scale = self.scale
        self.scale = max(0.4, min(240.0, self.scale * factor))
        if old_scale > 0:
            ratio = self.scale / old_scale
            centre_x = self.canvas.winfo_width() / 2 + self.pan_x
            centre_y = self.canvas.winfo_height() / 2 + self.pan_y
            self.pan_x += (centre_x - x) * (ratio - 1)
            self.pan_y += (centre_y - y) * (ratio - 1)
        self.request_redraw()

    def _select_nearest(self, x, y):
        candidates = []
        for sx, sy, radius, depth, atom in self.projected_pick_atoms:
            distance = math.hypot(sx - x, sy - y)
            if distance <= max(10.0, radius):
                candidates.append((distance, -depth, atom))
        if not candidates:
            self.clear_selection()
            return
        candidates.sort(key=lambda item: (item[0], item[1]))
        atom = candidates[0][2]
        self.selected_atom = atom
        self.atom_detail_var.set(self._atom_text(atom))
        if self.measure_mode:
            self._measurement_pick(atom)
        self.request_redraw()

    @staticmethod
    def _atom_text(atom):
        source = atom.get("source", "atom").title()
        return (
            f"{source} | {atom['name']} ({atom['element']}) | "
            f"{molecular_residue_label(atom)} | "
            f"{atom['x']:.3f}, {atom['y']:.3f}, {atom['z']:.3f}"
        )

    def begin_measurement(self):
        self.measure_mode = True
        self.measure_pending_atom = None
        self.measurement_var.set("Measurement active: select the first atom")
        self.status_var.set("Measurement active — click two atoms")
        self.request_redraw()

    def _measurement_pick(self, atom):
        if self.measure_pending_atom is None:
            self.measure_pending_atom = atom
            self.measurement_var.set(f"First atom: {self._atom_text(atom)}\nSelect the second atom")
            return
        first = self.measure_pending_atom        distance = molecular_distance(first, atom)
        self.measurements.append((first, atom, distance))
        self.measure_pending_atom = None
        self.measure_mode = False
        self.measurement_var.set(
            f"Latest: {first['name']} — {atom['name']} = {distance:.3f} Å\n"
            f"Stored measurements: {len(self.measurements)}"
        )

    def clear_measurements(self):
        self.measurements = []
        self.measure_pending_atom = None
        self.measure_mode = False
        self.measurement_var.set("No measurements")
        self.request_redraw()

    def clear_selection(self):
        self.selected_atom = None
        self.highlighted_residue = None
        self.atom_detail_var.set("Click an atom to inspect it")
        self.request_redraw()

    def copy_selected_atom(self):
        if self.selected_atom is None:
            return
        self.win.clipboard_clear()
        self.win.clipboard_append(self._atom_text(self.selected_atom))
        self.status_var.set("Selected atom details copied to the clipboard")

    def center_selected_atom(self):
        if self.selected_atom is None:
            return
        atom = self.selected_atom
        self.view_center = (atom["x"], atom["y"], atom["z"])
        self.pan_x = self.pan_y = 0.0
        self.request_redraw()

    def highlight_selected_residue(self):
        if self.selected_atom is None or self.selected_atom.get("source") != "receptor":
            self.status_var.set("Select a receptor atom to highlight its residue")
            return
        atom = self.selected_atom
        self.highlighted_residue = molecular_residue_key(atom)
        self.request_redraw()

    def _canvas_context_menu(self, event):
        if self.drag_distance < 5.0:
            self._select_nearest(event.x, event.y)
        menu = tk.Menu(self.win, tearoff=False, bg=self.palette["panel"], fg=self.palette["fg"])
        state = "normal" if self.selected_atom is not None else "disabled"
        menu.add_command(label="Copy atom details", command=self.copy_selected_atom, state=state)
        menu.add_command(label="Centre on atom", command=self.center_selected_atom, state=state)
        menu.add_command(label="Highlight receptor residue", command=self.highlight_selected_residue, state=state)
        menu.add_separator()
        menu.add_command(label="Start distance measurement", command=self.begin_measurement)
        menu.add_command(label="Clear selection", command=self.clear_selection)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _open_path(self, path):
        if not path:
            return
        if self.open_path_callback is not None:
            self.open_path_callback(path)
            return
        try:
            os.startfile(path)
        except Exception as exc:
            messagebox.showerror("Could not open file", str(exc), parent=self.win)

    def open_plip_report(self):
        if not self.current_plip_report:
            messagebox.showinfo(
                "Pose-specific PLIP",
                f"No matching PLIP summary is available for Pose {self.pose_index + 1}.",
                parent=self.win,
            )
            return
        self._open_path(self.current_full_plip_report or self.current_plip_report)

    @staticmethod

    @staticmethod
    def _pipeline_pdb_line(atom, serial, ligand=False, ligand_resname="UNL"):
        record = "HETATM" if ligand or str(atom.get("record", "")).upper() == "HETATM" else "ATOM"
        atom_name = re.sub(r"[^A-Za-z0-9'*!+\-]", "", str(atom.get("name") or "X"))[:4]
        resname = (ligand_resname if ligand else str(atom.get("resname") or "UNK"))[:3].upper()
        chain = ("Z" if ligand else str(atom.get("chain") or " "))[:1]
        if chain == "-":
            chain = " "
        resseq = 1 if ligand else int(atom.get("resseq") if atom.get("resseq") is not None else 1)
        icode = " " if ligand else str(atom.get("icode") or " ")[:1]
        altloc = " " if ligand else str(atom.get("altloc") or " ")[:1]
        occupancy = float(atom.get("occupancy", 1.0))
        bfactor = float(atom.get("bfactor", 0.0))
        element = re.sub(r"[^A-Za-z]", "", str(atom.get("element") or "C"))[:2].upper()
        return (
            f"{record:<6}{serial:>5d} {atom_name:<4}{altloc:1}{resname:>3} {chain:1}{resseq:>4d}{icode:1}   "
            f"{float(atom['x']):>8.3f}{float(atom['y']):>8.3f}{float(atom['z']):>8.3f}"
            f"{occupancy:>6.2f}{bfactor:>6.2f}          {element:>2}\n"
        )

    def _pipeline_write_complex_pdb(self, destination):
        if not self.receptor_atoms:
            raise RuntimeError(
                "The selected pose has no receptor coordinates loaded. Re-open it from a completed VLiP project."
            )
        if not self.ligand_atoms:
            raise RuntimeError("The selected pose contains no ligand atoms.")

        ligand_resname = str(self.ligand_atoms[0].get("resname") or "UNL")[:3].upper()
        if ligand_resname in {"", "UNK"}:
            ligand_resname = "UNL"
        lines = [f"REMARK   Generated by VLiP v{COMPLETE_PIPELINE_VERSION} for pose viewing\n"]
        serial = 1
        previous_segment = None
        for atom in self.receptor_atoms:
            segment = (atom.get("chain"), atom.get("segment", 0))
            if previous_segment is not None and segment != previous_segment:
                lines.append("TER\n")
            previous_segment = segment
            lines.append(self._pipeline_pdb_line(atom, serial, ligand=False))
            serial += 1
        lines.append("TER\n")
        for atom in self.ligand_atoms:
            lines.append(self._pipeline_pdb_line(atom, serial, ligand=True, ligand_resname=ligand_resname))
            serial += 1
        lines.append("END\n")
        with open(destination, "w", encoding="utf-8", newline="\n") as output:
            output.writelines(lines)

    def _pose_export_directory(self, pose_number):
        info = dict(self.result_info or {})
        project_dir = str(info.get("project_dir") or "")
        ligand_name = str(info.get("ligand") or "ligand")
        receptor_name = str(info.get("receptor") or "receptor")
        try:
            run_index = int(info.get("run") or 0)
        except (TypeError, ValueError):
            run_index = 0
        if project_dir and run_index > 0:
            run_dir = os.path.join(project_dir, ligand_name, receptor_name, f"run_{run_index}")
        else:
            run_dir = os.path.dirname(os.path.dirname(os.path.abspath(self.source_path)))
        return os.path.join(run_dir, "VLiP_2.0_Pose_Exports", f"pose_{pose_number}")

    def _open_pymol_download(self):
        _vlip_command_audit_action(
            "01_environment",
            "open_download_page",
            {"component": "PyMOL", "url": PYMOL_DOWNLOAD_URL},
            source="Pose Viewer",
        )
        try:
            if not webbrowser.open_new_tab(PYMOL_DOWNLOAD_URL):
                raise RuntimeError("Windows did not accept the browser request.")
        except Exception as exc:
            messagebox.showerror(
                "PyMOL download",
                f"Could not open the official PyMOL download page.\n\n{PYMOL_DOWNLOAD_URL}\n\n{exc}",
                parent=self.win,
            )

    def view_in_pymol(self):
        """Open the exact selected receptor/ligand pose in a detected PyMOL install."""
        launch_command = find_pymol_launch_command()
        if not launch_command:
            _vlip_command_audit_action(
                "08_pymol",
                "pymol_not_detected",
                {"pose": self.pose_index + 1, "source": self.source_path},
                source="Pose Viewer",
            )
            if messagebox.askyesno(
                "PyMOL is not installed",
                "VLiP could not find a working PyMOL launcher on PATH or in the standard Windows install folders.\n\n"
                "Open the official PyMOL download page now?",
                parent=self.win,
            ):
                self._open_pymol_download()
            return

        pose_number = self.pose_index + 1
        try:
            handoff_dir = self._pose_export_directory(pose_number)
            os.makedirs(handoff_dir, exist_ok=True)
            complex_path = os.path.join(handoff_dir, f"complex_pose{pose_number}_pymol.pdb")
            self._pipeline_write_complex_pdb(complex_path)
            command = list(launch_command) + [complex_path]
            _vlip_command_audit_action(
                "08_pymol",
                "view_in_pymol",
                {"pose": pose_number, "complex": complex_path, "command": command},
                cwd=handoff_dir,
                source="Pose Viewer",
            )
            popen_hidden_subprocess(command, cwd=handoff_dir)
            self.status_var.set(f"Pose {pose_number} opened in PyMOL")
        except Exception as exc:
            messagebox.showerror(
                "View in PyMOL",
                f"Could not open the selected pose in PyMOL.\n\n{exc}",
                parent=self.win,
            )


    def export_svg(self):
        filename = filedialog.asksaveasfilename(
            parent=self.win, title="Export the current molecular view",
            defaultextension=".svg", filetypes=[("Scalable Vector Graphics", "*.svg")],
            initialfile=f"vlip_pose_{self.pose_index + 1}.svg",
        )
        if not filename:
            return
        self._draw_scene()
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        output = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            f'<title>{html.escape(self.win.title())}</title>',
        ]
        for item in self.canvas.find_all():
            item_type = self.canvas.type(item)
            coordinates = self.canvas.coords(item)
            tags = self.canvas.gettags(item)
            fill = self.canvas.itemcget(item, "fill") or "none"
            outline = self.canvas.itemcget(item, "outline") if item_type in {"oval", "rectangle", "polygon"} else ""
            width_value = self.canvas.itemcget(item, "width") or "1"
            opacity = "0.48" if "surface" in tags else "1"
            if item_type == "rectangle" and len(coordinates) >= 4:
                x1, y1, x2, y2 = coordinates[:4]
                output.append(f'<rect x="{x1:.2f}" y="{y1:.2f}" width="{x2-x1:.2f}" height="{y2-y1:.2f}" fill="{fill}" stroke="{outline or fill}"/>')
            elif item_type == "oval" and len(coordinates) >= 4:
                x1, y1, x2, y2 = coordinates[:4]
                output.append(
                    f'<ellipse cx="{(x1+x2)/2:.2f}" cy="{(y1+y2)/2:.2f}" rx="{abs(x2-x1)/2:.2f}" ry="{abs(y2-y1)/2:.2f}" '
                    f'fill="{fill}" fill-opacity="{opacity}" stroke="{outline or "none"}" stroke-width="{width_value}"/>'
                )
            elif item_type == "line" and len(coordinates) >= 4:
                points = " ".join(f"{coordinates[index]:.2f},{coordinates[index+1]:.2f}" for index in range(0, len(coordinates) - 1, 2))
                dash = self.canvas.itemcget(item, "dash")
                dash_attr = ' stroke-dasharray="5 4"' if dash else ""
                output.append(f'<polyline points="{points}" fill="none" stroke="{fill}" stroke-width="{width_value}" stroke-linecap="round"{dash_attr}/>')
            elif item_type == "text" and len(coordinates) >= 2:
                content = html.escape(self.canvas.itemcget(item, "text"))
                output.append(f'<text x="{coordinates[0]:.2f}" y="{coordinates[1]:.2f}" fill="{fill}" font-family="Segoe UI, sans-serif" font-size="12">{content}</text>')
        output.append("</svg>")
        try:
            with open(filename, "w", encoding="utf-8", newline="\n") as destination:
                destination.write("\n".join(output))
            self.status_var.set(f"SVG snapshot saved: {filename}")
        except OSError as exc:
            messagebox.showerror("Could not export snapshot", str(exc), parent=self.win)

    def show_help(self):
        help_title = "VLiP Receptor Preview controls" if self.preview_mode else "VLiP Pose Viewer controls"
        fit_description = "docking region" if self.preview_mode else "ligand and nearby residues"
        messagebox.showinfo(
            help_title,
            "Rotate: drag with the left mouse button\n"
            "Pan: hold Shift while dragging, or use the middle button\n"
            "Zoom: mouse wheel\n"
            "Inspect: click an atom\n"
            "Atom actions: right-click the molecular view\n"
            "Measure: press M or click Measure, then select two atoms\n\n"
            f"F fits the {fit_description}. "
            + ("A fits the whole receptor. " if self.preview_mode else "A fits the current nearby-residue scene. ")
            + "R resets the orientation. Escape clears the selection.\n\n"
            "Nearby-residue controls show complete receptor residues around the ligand, "
            "with an adjustable distance cutoff and optional residue labels. "
            + (
                "The full receptor and surface controls are available in this receptor preview.\n\n"
                if self.preview_mode
                else "The docking Pose Viewer does not draw the rest of the receptor.\n\n"
            )
            + (
                "The fast surface and contact guides are intended for visual inspection."
                if self.preview_mode
                else "The scrollable panel beside the 3D view follows the selected pose and never substitutes another pose's PLIP report."
            ),
            parent=self.win,
        )


# ======================================================
# Progress overlay
# ======================================================

class ProgressOverlay:
    def __init__(self, parent, pause_callback, cancel_callback, stop_after_receptor_callback,
                 speed_change_callback=None, schedule_change_callback=None,
                 initial_speed_mode="Full", initial_schedule_enabled=False,
                 initial_schedule_start="08:00", initial_schedule_end="18:00",
                 initial_speed_status="", initial_current=0, initial_estimated_seconds=None):
        self.parent = parent
        self.pause_callback = pause_callback
        self.cancel_callback = cancel_callback
        self.stop_after_receptor_callback = stop_after_receptor_callback
        self.speed_change_callback = speed_change_callback
        self.schedule_change_callback = schedule_change_callback
        self.initial_current = max(0, int(initial_current or 0))
        self.initial_estimated_seconds = initial_estimated_seconds
        self.started_monotonic = time.monotonic()
        self.pause_started = None
        self.paused_seconds = 0.0
        self._last_current = self.initial_current
        self._last_total = max(1, self.initial_current + 1)
        self._eta_after_id = None
        self._syncing_speed_controls = False

        self.win = tk.Toplevel(parent)
        self.win.title("Docking in progress")
        self.win.geometry("720x550")
        self.win.resizable(False, False)
        self.win.transient(parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        self.status_var = tk.StringVar(value="Starting...")
        self.count_var = tk.StringVar(value="0 / 0")
        self.ligand_var = tk.StringVar(value="Ligand: ")
        self.receptor_var = tk.StringVar(value="Receptor: ")
        self.run_var = tk.StringVar(value="Run: ")
        self.eta_var = tk.StringVar(value="Elapsed: 0s  •  Estimated remaining: calculating…")
        self.stop_state_var = tk.StringVar(value="Stop-after-receptor: not requested")
        self.speed_mode_var = tk.StringVar(value=initial_speed_mode)
        self.speed_schedule_var = tk.BooleanVar(value=bool(initial_schedule_enabled))
        self.speed_start_var = tk.StringVar(value=initial_schedule_start)
        self.speed_end_var = tk.StringVar(value=initial_schedule_end)
        self.speed_status_var = tk.StringVar(value=initial_speed_status)

        frame = tk.Frame(self.win, padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Docking batch running",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            frame,
            textvariable=self.status_var,
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(0, 8))

        self.pb = ttk.Progressbar(frame, mode="determinate", length=650)
        self.pb.pack(fill="x", pady=(0, 10))

        tk.Label(frame, textvariable=self.count_var).pack(anchor="w", pady=(0, 8))
        tk.Label(frame, textvariable=self.ligand_var, justify="left", wraplength=650).pack(anchor="w", pady=2)
        tk.Label(frame, textvariable=self.receptor_var, justify="left", wraplength=650).pack(anchor="w", pady=2)
        tk.Label(frame, textvariable=self.run_var, justify="left", wraplength=650).pack(anchor="w", pady=2)
        tk.Label(
            frame,
            textvariable=self.eta_var,
            justify="left",
            wraplength=650,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(8, 2))
        tk.Label(frame, textvariable=self.stop_state_var, justify="left", wraplength=650).pack(anchor="w", pady=(8, 2))

        performance = tk.LabelFrame(frame, text="Live performance", padx=8, pady=7)
        performance.pack(fill="x", pady=(10, 2))
        first_row = tk.Frame(performance)
        first_row.pack(fill="x")
        tk.Label(first_row, text="Speed:").pack(side="left")
        self.speed_combo = ttk.Combobox(
            first_row,
            textvariable=self.speed_mode_var,
            values=SPEED_MODES,
            state="readonly",
            width=11,
        )
        self.speed_combo.pack(side="left", padx=(5, 12))
        self.speed_combo.bind("<<ComboboxSelected>>", self._speed_selected)
        self.speed_schedule_check = tk.Checkbutton(
            first_row,
            text="Daily schedule",
            variable=self.speed_schedule_var,
            command=self._schedule_requested,
        )
        self.speed_schedule_check.pack(side="left", padx=(0, 8))
        tk.Label(first_row, text="Gentle from").pack(side="left")
        self.speed_start_entry = tk.Entry(first_row, textvariable=self.speed_start_var, width=6)
        self.speed_start_entry.pack(side="left", padx=4)
        tk.Label(first_row, text="until").pack(side="left")
        self.speed_end_entry = tk.Entry(first_row, textvariable=self.speed_end_var, width=6)
        self.speed_end_entry.pack(side="left", padx=4)
        self.speed_schedule_apply_btn = tk.Button(
            first_row, text="Apply", width=7, command=self._schedule_requested
        )
        self.speed_schedule_apply_btn.pack(side="left", padx=(5, 0))
        tk.Label(
            performance,
            textvariable=self.speed_status_var,
            justify="left",
            anchor="w",
            wraplength=620,
        ).pack(fill="x", anchor="w", pady=(5, 0))

        tk.Label(
            frame,
            text="Speed changes apply to the active Vina/PLIP process. Pause waits for the current subprocess to finish. Stop After Receptor finishes the current receptor's repeats, then stops cleanly.",
            fg="gray",
            wraplength=650,
            justify="left"
        ).pack(anchor="w", pady=(14, 8))

        btns = tk.Frame(frame)
        btns.pack(fill="x", pady=(4, 0))

        self.pause_btn = tk.Button(btns, text="Pause after step", width=16, command=self.pause_callback)
        self.pause_btn.pack(side="left", padx=(0, 8))

        self.stop_after_receptor_btn = tk.Button(
            btns,
            text="Stop After Receptor",
            width=18,
            command=self.stop_after_receptor_callback
        )
        self.stop_after_receptor_btn.pack(side="left", padx=(0, 8))

        self.cancel_btn = tk.Button(btns, text="Cancel Run", width=14, command=self.cancel_callback)
        self.cancel_btn.pack(side="left")

        self.center()
        self.win.withdraw()
        self.win.deiconify()
        self.win.lift()
        self.win.update()
        self._schedule_eta_tick()

    def center(self):
        self.parent.update_idletasks()
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()

        ww = 720
        wh = 550
        x = px + max((pw - ww) // 2, 0)
        y = py + max((ph - wh) // 2, 0)
        self.win.geometry(f"{ww}x{wh}+{x}+{y}")

    def update_progress(self, current, total, status="", ligand="", receptor="", run_text=""):
        total = max(total, 1)
        current = max(0, min(int(current or 0), total))
        self._last_current = current
        self._last_total = total
        self.pb["maximum"] = total
        self.pb["value"] = current
        self.count_var.set(f"{current} / {total}")
        self.status_var.set(status)
        self.ligand_var.set(f"Ligand: {ligand}")
        self.receptor_var.set(f"Receptor: {receptor}")
        self.run_var.set(f"Run: {run_text}")
        self._update_eta(current, total)

    @staticmethod
    def _format_eta_duration(seconds):
        try:
            seconds = max(0, int(round(float(seconds))))
        except (TypeError, ValueError):
            return "unknown"
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _active_elapsed(self):
        paused_now = time.monotonic() - self.pause_started if self.pause_started is not None else 0.0
        return max(0.0, time.monotonic() - self.started_monotonic - self.paused_seconds - paused_now)

    def _update_eta(self, current, total):
        elapsed = self._active_elapsed()
        if current >= total:
            self.eta_var.set(f"Elapsed: {self._format_eta_duration(elapsed)}  •  Complete")
            return

        completed_live = max(0, current - self.initial_current)
        if completed_live:
            remaining = (elapsed / completed_live) * max(0, total - current)
            basis = "live"
        elif self.initial_estimated_seconds is not None:
            initial_jobs = max(1, total - self.initial_current)
            planned_remaining = (
                float(self.initial_estimated_seconds) * max(0, total - current) / initial_jobs
            )
            remaining = max(0.0, planned_remaining - elapsed)
            basis = "history"
        else:
            self.eta_var.set(
                f"Elapsed: {self._format_eta_duration(elapsed)}  •  Estimated remaining: calculating…"
            )
            return

        finish = time.strftime("%H:%M", time.localtime(time.time() + max(0.0, remaining)))
        self.eta_var.set(
            f"Elapsed: {self._format_eta_duration(elapsed)}  •  "
            f"Estimated remaining: {self._format_eta_duration(remaining)}  •  "
            f"Finish about {finish} ({basis})"
        )

    def _schedule_eta_tick(self):
        try:
            if not self.win.winfo_exists():
                return
            self._update_eta(self._last_current, self._last_total)
            self._eta_after_id = self.win.after(1000, self._schedule_eta_tick)
        except Exception:
            self._eta_after_id = None

    def set_paused(self, paused):
        if paused and self.pause_started is None:
            self.pause_started = time.monotonic()
        elif not paused and self.pause_started is not None:
            self.paused_seconds += max(0.0, time.monotonic() - self.pause_started)
            self.pause_started = None
        self.pause_btn.config(text="Resume" if paused else "Pause after step")

    def set_cancelled_state(self):
        self.pause_btn.config(state="disabled")
        self.stop_after_receptor_btn.config(state="disabled")
        self.cancel_btn.config(state="disabled")
        self.speed_combo.config(state="disabled")
        self.speed_schedule_check.config(state="disabled")
        self.speed_start_entry.config(state="disabled")
        self.speed_end_entry.config(state="disabled")
        self.speed_schedule_apply_btn.config(state="disabled")

    def _speed_selected(self, _event=None):
        if self._syncing_speed_controls or self.speed_change_callback is None:
            return
        self.speed_change_callback(self.speed_mode_var.get())

    def _schedule_requested(self):
        if self._syncing_speed_controls or self.schedule_change_callback is None:
            return
        self.schedule_change_callback(
            bool(self.speed_schedule_var.get()),
            self.speed_start_var.get(),
            self.speed_end_var.get(),
        )

    def set_speed_state(self, mode, schedule_enabled, schedule_start, schedule_end, status):
        self._syncing_speed_controls = True
        try:
            self.speed_mode_var.set(mode)
            self.speed_schedule_var.set(bool(schedule_enabled))
            self.speed_start_var.set(schedule_start)
            self.speed_end_var.set(schedule_end)
            self.speed_status_var.set(status)
        finally:
            self._syncing_speed_controls = False

    def set_stop_after_receptor_requested(self, requested):
        if requested:
            self.stop_state_var.set("Stop-after-receptor: requested")
            self.stop_after_receptor_btn.config(text="Stop Requested", state="disabled")
        else:
            self.stop_state_var.set("Stop-after-receptor: not requested")
            self.stop_after_receptor_btn.config(text="Stop After Receptor", state="normal")

    def close(self):
        try:
            if self._eta_after_id is not None:
                self.win.after_cancel(self._eta_after_id)
                self._eta_after_id = None
            self.win.destroy()
        except Exception:
            pass


# ======================================================
# Main GUI
# ======================================================

class VinaBatchGUI:
    def __init__(self, root):
        self.root = root
        self.root.title(f"VLiP {APP_VERSION} — Docking / PLIP")

        self.receptors = []
        self.ligands = []
        self._queue_undo_stack = []
        self.queue_undo_buttons = []
        self._receptor_drag_iid = None
        self._ligand_drag_iid = None

        self.live_console_queue = queue.Queue()
        self._live_console_after_id = None
        self._live_console_line_limit = 2500

        self.job_queue = queue.Queue()
        self.worker_thread = None
        self.overlay = None
        self.run_in_progress = False

        self.pause_event = threading.Event()
        self.cancel_event = threading.Event()
        self.stop_after_receptor_event = threading.Event()

        self.current_process = None
        self.active_processes = set()
        self.current_process_lock = threading.Lock()
        self.speed_lock = threading.Lock()
        self.performance_event_lock = threading.Lock()
        self.available_cpu_ids = self._detect_available_cpu_ids()
        self.active_speed_mode = "Full"
        self.active_schedule_enabled = False
        self.active_schedule_start = "08:00"
        self.active_schedule_end = "18:00"
        self.last_speed_apply_summary = "Performance control is ready."
        self._speed_schedule_after_id = None

        self.last_progress_data = None
        self.checkpoint_write_errors = []
        self.receptor_tool_status_var = tk.StringVar(
            value="Cleaner → PDBQT Prep → prepared receptors auto-import into this queue."
        )
        self.ligand_tool_status_var = tk.StringVar(
            value="SMILES / SDF → audited 3D ligand states → prepared PDBQTs auto-import here."
        )

        self.load_settings()
        self.build_ui()
        self.install_edit_context_menus()
        self.refresh_table()
        self.refresh_ligand_table()
        self._update_undo_buttons()
        self._live_console_after_id = self.root.after(100, self._drain_live_console_queue)

        self._apply_configured_speed(source="startup", record=False)
        self._speed_schedule_after_id = self.root.after(1000, self._speed_schedule_tick)

        self.root.after(200, self.startup_self_check)
        self.root.after(800, self.poll_receptor_handoff)
        self.root.after(900, self.poll_ligand_handoff)

    # ----------------------
    # Application-wide text editing menu
    # ----------------------
    def install_edit_context_menus(self):
        """Give all present and future text controls a conventional right-click menu."""
        for widget_class in ("Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox"):
            try:
                self.root.bind_class(widget_class, "<Button-3>", self.show_edit_context_menu, add="+")
            except tk.TclError:
                pass

    @staticmethod
    def _widget_has_selection(widget):
        try:
            if isinstance(widget, tk.Text):
                return bool(widget.tag_ranges("sel"))
            return bool(widget.selection_present())
        except (tk.TclError, AttributeError):
            return False

    def _edit_widget_action(self, widget, action):
        try:
            if action == "select_all":
                widget.focus_set()
                if isinstance(widget, tk.Text):
                    widget.tag_add("sel", "1.0", "end-1c")
                    widget.mark_set("insert", "end-1c")
                    widget.see("insert")
                else:
                    widget.selection_range(0, "end")
                    widget.icursor("end")
                return
            if action == "delete":
                if isinstance(widget, tk.Text):
                    widget.delete("sel.first", "sel.last")
                else:
                    widget.delete("sel.first", "sel.last")
                return
            event_names = {"cut": "<<Cut>>", "copy": "<<Copy>>", "paste": "<<Paste>>"}
            widget.event_generate(event_names[action])
        except (tk.TclError, KeyError):
            pass

    def show_edit_context_menu(self, event):
        widget = event.widget
        try:
            widget.focus_set()
        except tk.TclError:
            return "break"

        has_selection = self._widget_has_selection(widget)
        try:
            state = str(widget.cget("state"))
        except tk.TclError:
            state = "normal"
        editable = state not in {"disabled", "readonly"}
        try:
            self.root.clipboard_get()
            has_clipboard = True
        except tk.TclError:
            has_clipboard = False

        night_variable = getattr(self, "night_mode_var", None)
        dark = bool(night_variable.get()) if night_variable is not None else False
        menu_bg = "#292d35" if dark else "#ffffff"
        menu_fg = "#f1f3f5" if dark else "#17191c"
        active_bg = "#3c4654" if dark else "#dceeff"
        menu = tk.Menu(
            self.root, tearoff=False, bg=menu_bg, fg=menu_fg,
            activebackground=active_bg, activeforeground=menu_fg,
        )
        menu.add_command(
            label="Cut", command=lambda: self._edit_widget_action(widget, "cut"),
            state="normal" if editable and has_selection else "disabled",
        )
        menu.add_command(
            label="Copy", command=lambda: self._edit_widget_action(widget, "copy"),
            state="normal" if has_selection else "disabled",
        )
        menu.add_command(
            label="Paste", command=lambda: self._edit_widget_action(widget, "paste"),
            state="normal" if editable and has_clipboard else "disabled",
        )
        menu.add_command(
            label="Delete selection", command=lambda: self._edit_widget_action(widget, "delete"),
            state="normal" if editable and has_selection else "disabled",
        )
        menu.add_separator()
        menu.add_command(label="Select all", command=lambda: self._edit_widget_action(widget, "select_all"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    # ----------------------
    # Path / bundled resource helpers
    # ----------------------
    def user_working_dir(self):
        return user_working_dir()

    def find_tool(self, *names):
        candidates = []
        bases = [app_dir(), self.user_working_dir(), managed_root_dir()]
        for base in bases:
            for name in names:
                candidates.append(os.path.join(base, name))
                candidates.append(os.path.join(base, "tools", name))
                candidates.append(os.path.join(base, "bin", name))

        for c in candidates:
            if os.path.exists(c):
                return c

        for name in names:
            found = shutil.which(name)
            if found:
                return found

        return ""

    def resolved_vina_path(self):
        typed = self.vina_var.get().strip()
        if typed and os.path.exists(typed):
            return typed
        return self.find_tool("vina.exe", "vina")

    # ----------------------
    # Bundled receptor tools
    # ----------------------
    def receptor_tools_root(self):
        """Return the bundled receptor-tools folder shipped beside VLiP."""
        candidates = [
            os.path.join(user_working_dir(), RECEPTOR_TOOLS_DIRNAME),
            os.path.join(app_dir(), RECEPTOR_TOOLS_DIRNAME),
        ]
        for path in candidates:
            if os.path.isdir(path):
                return path
        return candidates[0]

    def _bundled_tool_path(self, tool_dir, filename):
        return os.path.join(self.receptor_tools_root(), tool_dir, filename)

    def receptor_handoff_path(self):
        """Shared atomic handoff file used by the bundled PDBQT preparer."""
        return os.path.join(user_working_dir(), RECEPTOR_HANDOFF_FILENAME)

    def ligand_handoff_path(self):
        """Shared atomic handoff file used by the bundled ligand preparer."""
        return os.path.join(user_working_dir(), LIGAND_HANDOFF_FILENAME)

    def _queue_ligand_path(self, path):
        """Add one prepared ligand PDBQT after validating it and checking duplicates."""
        if not path:
            return False, "empty path"
        path = os.path.abspath(os.path.normpath(str(path)))
        if not os.path.isfile(path):
            return False, "file not found"
        if not path.lower().endswith(".pdbqt"):
            return False, "not a .pdbqt file"
        candidate_key = os.path.normcase(path)
        for existing in self.ligands:
            existing_path = os.path.abspath(os.path.normpath(str(existing)))
            if os.path.normcase(existing_path) == candidate_key:
                return False, "already queued"
        ok, detail = validate_pdbqt(path, kind="ligand")
        if not ok:
            return False, detail
        self.ligands.append(path)
        return True, "added"

    def _queue_receptor_path(self, path):
        """Add one receptor PDBQT to the queue if it is valid and not already present."""
        if not path:
            return False, "empty path"
        path = os.path.abspath(os.path.normpath(str(path)))
        if not os.path.isfile(path):
            return False, "file not found"
        if not path.lower().endswith(".pdbqt"):
            return False, "not a .pdbqt file"

        candidate_key = os.path.normcase(path)
        for existing in self.receptors:
            existing_path = os.path.abspath(os.path.normpath(str(existing.get("path", ""))))
            if os.path.normcase(existing_path) == candidate_key:
                return False, "already queued"

        ok, detail = validate_pdbqt(path, kind="receptor")
        if not ok:
            return False, detail

        self.receptors.append({
            "name": os.path.basename(path),
            "path": path,
            "mode": "Whole",
            "residues": "",
            "padding": "",
        })
        return True, "added"

    def poll_receptor_handoff(self):
        """Import prepared PDBQTs sent by the companion receptor-prep GUI."""
        try:
            if not self.run_in_progress:
                handoff = self.receptor_handoff_path()
                if os.path.isfile(handoff):
                    self._consume_receptor_handoff(handoff)
        except Exception as exc:
            self.receptor_tool_status_var.set(f"Prepared receptor import error: {exc}")
        finally:
            try:
                self.root.after(800, self.poll_receptor_handoff)
            except Exception:
                pass

    def _consume_receptor_handoff(self, handoff):
        try:
            with open(handoff, "r", encoding="utf-8", errors="replace") as f:
                payload = json.load(f)
        except Exception:
            # The preparer writes atomically, so a parse failure normally means
            # a genuinely damaged/stale file. Leave it for the next poll/review.
            return

        if payload.get("file_type") != "VLIP_RECEPTOR_HANDOFF":
            return

        paths = payload.get("pdbqt_paths") or []
        if not isinstance(paths, list):
            return

        before = self._queue_snapshot()
        added = []
        duplicates = 0
        rejected = []
        for path in paths:
            was_added, detail = self._queue_receptor_path(path)
            if was_added:
                added.append(os.path.abspath(str(path)))
            elif detail == "already queued":
                duplicates += 1
            else:
                rejected.append((str(path), detail))

        # Consume only after the payload was understood. A failed delete is harmless:
        # duplicate detection prevents a second import on the next poll.
        try:
            os.remove(handoff)
        except OSError:
            pass

        if added:
            self._record_queue_undo(before, f"import {len(added)} receptors")            self.refresh_table()
            self.save_settings()
            text = f"Imported {len(added)} prepared receptor PDBQT(s) into the docking queue."
            if duplicates:
                text += f" {duplicates} duplicate(s) ignored."
            if rejected:
                text += f" {len(rejected)} invalid/missing file(s) skipped."
            self.receptor_tool_status_var.set(text)
        elif duplicates and not rejected:
            self.receptor_tool_status_var.set(
                f"Prepared receptor handoff received; {duplicates} file(s) were already queued."
            )
        elif rejected:
            self.receptor_tool_status_var.set(
                f"Prepared receptor handoff received, but {len(rejected)} file(s) failed validation."
            )

    def poll_ligand_handoff(self):
        """Import prepared ligand PDBQTs sent by the embedded ligand-prep GUI."""
        try:
            if not self.run_in_progress:
                handoff = self.ligand_handoff_path()
                if os.path.isfile(handoff):
                    self._consume_ligand_handoff(handoff)
        except Exception as exc:
            self.ligand_tool_status_var.set(f"Prepared ligand import error: {exc}")
        finally:
            try:
                self.root.after(800, self.poll_ligand_handoff)
            except Exception:
                pass

    def _consume_ligand_handoff(self, handoff):
        try:
            with open(handoff, "r", encoding="utf-8", errors="replace") as handle:
                payload = json.load(handle)
        except Exception:
            return
        if payload.get("file_type") != "VLIP_LIGAND_HANDOFF":
            return
        paths = payload.get("pdbqt_paths") or []
        if not isinstance(paths, list):
            return

        before = self._queue_snapshot()
        added = []
        duplicates = 0
        rejected = []
        for path in paths:
            was_added, detail = self._queue_ligand_path(path)
            if was_added:
                added.append(os.path.abspath(str(path)))
            elif detail == "already queued":
                duplicates += 1
            else:
                rejected.append((str(path), detail))
        try:
            os.remove(handoff)
        except OSError:
            pass

        if added:
            self._record_queue_undo(before, f"import {len(added)} ligands")
            if not self.ligand_var.get().strip() and len(added) == 1:
                self.ligand_var.set(added[0])
            self.refresh_ligand_table()
            self.save_settings()
            text = f"Imported {len(added)} prepared ligand state(s) into the docking queue."
            if duplicates:
                text += f" {duplicates} duplicate(s) ignored."
            if rejected:
                text += f" {len(rejected)} invalid/missing file(s) skipped."
            manifest = str(payload.get("manifest_path") or "").strip()
            if manifest:
                text += " Preparation audit manifest retained in the selected ligand output folder."
            self.ligand_tool_status_var.set(text)
        elif duplicates and not rejected:
            self.ligand_tool_status_var.set(
                f"Prepared ligand handoff received; {duplicates} state(s) were already queued."
            )
        elif rejected:
            self.ligand_tool_status_var.set(
                f"Prepared ligand handoff received, but {len(rejected)} file(s) failed validation."
            )

    def _external_pythonw(self):
        """Python interpreter for dependency-free bundled GUI tools."""
        exe = sys.executable
        if IS_WINDOWS:
            sibling = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(sibling):
                return sibling
            for name in ("pythonw.exe", "pyw.exe", "python.exe", "py.exe"):
                found = shutil.which(name)
                if found:
                    return found
        return exe

    def _find_conda_executable(self):
        candidates = []
        env_conda = os.environ.get("CONDA_EXE", "").strip()
        if env_conda:
            candidates.append(env_conda)

        home = os.path.expanduser("~")
        localapp = os.environ.get("LOCALAPPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", "")
        candidates.extend([
            os.path.join(managed_miniconda_dir(), "Scripts", "conda.exe"),
            os.path.join(home, "miniconda3", "Scripts", "conda.exe"),
            os.path.join(home, "anaconda3", "Scripts", "conda.exe"),
            os.path.join(localapp, "miniconda3", "Scripts", "conda.exe") if localapp else "",
            os.path.join(programdata, "miniconda3", "Scripts", "conda.exe") if programdata else "",
        ])
        found = shutil.which("conda.exe" if IS_WINDOWS else "conda")
        if found:
            candidates.append(found)

        for path in candidates:
            if path and os.path.exists(path):
                return path
        return ""

    def _single_file_script(self):
        """Absolute path to this all-in-one VLiP .pyw file."""
        return os.path.abspath(__file__)

    def _open_official_download_page(self, component, url, parent=None):
        _vlip_command_audit_action(
            "01_environment",
            "open_download_page",
            {"component": component, "url": url},
            source="VLiP Software Downloads",
        )
        try:
            if not webbrowser.open_new_tab(url):
                raise RuntimeError("Windows did not accept the browser request.")
            return True
        except Exception as exc:
            messagebox.showerror(
                f"{component} download",
                f"Could not open the official download page.\n\n{url}\n\n{exc}",
                parent=parent or self.root,
            )
            return False

    def show_software_downloads(self):
        """V2 offers docking dependency repair and an optional PyMOL link only."""
        win = tk.Toplevel(self.root)
        win.title(f"VLiP {APP_VERSION} — Software and diagnostics")
        win.geometry("690x310")
        win.transient(self.root)
        tk.Label(win, text="VLiP 2.0 docking dependencies", font=("TkDefaultFont", 12, "bold")).pack(padx=16, pady=(18, 8))
        tk.Label(win, text=(
            "AutoDock Vina, PLIP, Open Babel, RDKit, Meeko, PDB2PQR, PROPKA, SciPy, "
            "and Gemmi can be installed/repaired into a private runtime. "
            "PyMOL is optional and is not bundled."
        ), wraplength=640, justify="left").pack(padx=16, pady=8)
        tk.Button(win, text="Install / Repair docking dependencies",
                  command=self.install_or_repair_all_tools).pack(padx=12, pady=6)
        tk.Button(win, text="Check dependencies", command=self.run_diagnostics).pack(pady=6)
        tk.Button(win, text="Official PyMOL download",
                  command=lambda: self._open_official_download_page("PyMOL", PYMOL_DOWNLOAD_URL, win)).pack(pady=6)
        tk.Button(win, text="Close", command=win.destroy).pack(pady=(8, 10))
        self.apply_night_mode(save=False)
    def open_receptor_cleaner(self):
        """Open the embedded cleaner by relaunching this same file in cleaner mode."""
        script = self._single_file_script()
        try:
            python_gui = self._external_pythonw()
            theme_args = ["--vlip-follow-theme"]
            night_variable = getattr(self, "night_mode_var", None)
            if night_variable is not None and bool(night_variable.get()):
                theme_args.append("--night-mode")
            cmd = [python_gui, script, "--cleaner-gui"] + theme_args
            if IS_WINDOWS and os.path.basename(python_gui).lower() in ("py.exe", "pyw.exe"):
                cmd = [python_gui, "-3", script, "--cleaner-gui"] + theme_args
            popen_hidden_subprocess(cmd, cwd=self.user_working_dir())
        except Exception as exc:
            messagebox.showerror("Could not open Receptor Cleaner", str(exc))

    def _conda_env_exists(self, conda, env_name="vlip-pdbqt"):
        try:
            result = run_hidden_subprocess(
                [conda, "env", "list", "--json"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return False
            payload = json.loads(result.stdout or "{}")
            for env_path in payload.get("envs", []):
                if os.path.basename(os.path.normpath(str(env_path))).lower() == env_name.lower():
                    return True
        except Exception:
            pass
        return False

    def show_receptor_tool_setup(self):
        text = (
            "Use 'Install / Repair ALL' for the normal setup. It installs into a private VLiP folder under your user profile.\n\n"
            "Managed components:\n"
            f"  AutoDock Vina {VINA_RELEASE_TAG} (pinned and SHA-256 verified)\n"
            f"  {MINICONDA_INSTALLER_NAME} (pinned and SHA-256 verified), only if Conda is unavailable\n"
            "  Python 3.12 isolated runtime\n"
            "  PLIP 2.4.0 + OpenBabel\n"
            "  Meeko 0.7.1\n"
            "  PDB2PQR 3.7.1 + PROPKA\n"
            "  RDKit 2025.9.6, SciPy 1.16.3, Gemmi 0.7.3\n"
            "  Matplotlib for managed scientific-runtime compatibility\n\n"
            "The same managed RDKit/Open Babel/Meeko stack powers the current VLiP ligand-preparation workflow.\n\n"
            f"Managed root:\n{managed_root_dir()}\n\n"
            "The cleaner/preparer scientific source remains embedded in this one .pyw file."
        )
        messagebox.showinfo("VLiP 2.0 docking setup", text)

    def _installer_log(self, message):
        text = str(message).rstrip() + "\n"
        path = getattr(self, "installer_log_path", "")
        if path:
            try:
                with self._installer_file_lock:
                    with open(path, "a", encoding="utf-8") as fh:
                        fh.write(text)
            except Exception:
                pass
        def write():
            try:
                if getattr(self, "installer_text", None) is not None:
                    self.installer_text.configure(state="normal")
                    self.installer_text.insert("end", text)
                    self.installer_text.see("end")
                    self.installer_text.configure(state="disabled")
                if getattr(self, "installer_status_var", None) is not None:
                    self.installer_status_var.set(text.strip().splitlines()[-1])
            except Exception:
                pass
        try:
            self.root.after(0, write)
        except Exception:
            pass

    def _download_to(self, url, destination, label, expected_sha256):
        expected_sha256 = str(expected_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise RuntimeError(f"No trusted SHA-256 is configured for {label}; refusing executable download.")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        if os.path.isfile(destination) and sha256_file(destination) == expected_sha256:
            self._installer_log(f"Using verified repair cache: {label}")
            return destination
        req = urllib.request.Request(url, headers={"User-Agent": f"VLiP/{APP_VERSION} dependency installer"})
        self._installer_log(f"Downloading {label}...")
        part_path = destination + ".part"
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(req, timeout=60) as response, open(part_path, "wb") as out:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                next_mark = 10
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    digest.update(chunk)
                    done += len(chunk)
                    if total:
                        pct = int(done * 100 / total)
                        if pct >= next_mark:
                            self._installer_log(f"{label}: {pct}%")
                            next_mark = min(100, ((pct // 10) + 1) * 10)
            actual_sha256 = digest.hexdigest()
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"SHA-256 mismatch for {label}; expected {expected_sha256}, got {actual_sha256}. "
                    "The file was not installed."
                )
            self._installer_log(f"Verified {label} SHA-256: {actual_sha256}")
            os.replace(part_path, destination)
        except Exception:
            try:
                if os.path.lexists(part_path):
                    os.remove(part_path)
            except OSError:
                pass
            raise
        return destination

    def _run_installer_command(self, cmd, label, timeout=1800, env=None):
        """Execute without shell; stream both stdout and stderr to the saved setup log."""
        self._installer_log(label)
        process = popen_hidden_subprocess(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
        )
        lines = queue.Queue()
        recent = []
        def collect():
            try:
                for line in process.stdout:
                    lines.put(line.rstrip())
            finally:
                lines.put(None)
        reader = threading.Thread(target=collect, daemon=True, name="VLiPSetupOutput")
        reader.start()
        deadline = time.monotonic() + timeout
        finished = False
        while not finished:
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise TimeoutError(f"Installer command timed out after {timeout}s: {command_to_text(cmd)}")
            try:
                item = lines.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                finished = True
                continue
            if item.strip():
                recent.append(item)
                recent = recent[-60:]
                self._installer_log(item)
        code = process.wait(timeout=10)
        if code:
            raise RuntimeError(f"{label} failed (exit code {code}).\n" + "\n".join(recent[-25:]))
        return subprocess.CompletedProcess(cmd, code, "\n".join(recent), "")

    def _ensure_managed_conda(self):
        conda = self._find_conda_executable()
        if conda:
            self._installer_log(f"Conda found: {conda}")
            return conda
        if not IS_WINDOWS:
            raise RuntimeError("Conda was not found. Automatic Miniconda bootstrap is currently implemented for Windows.")

        root = managed_root_dir()
        downloads = os.path.join(root, "downloads")
        os.makedirs(downloads, exist_ok=True)
        installer = os.path.join(downloads, MINICONDA_INSTALLER_NAME)
        self._download_to(
            MINICONDA_INSTALLER_URL,
            installer,
            f"Miniconda {MINICONDA_INSTALLER_NAME}",
            MINICONDA_INSTALLER_SHA256,
        )
        prefix = managed_miniconda_dir()
        os.makedirs(os.path.dirname(prefix), exist_ok=True)
        cmd = [
            installer,
            "/InstallationType=JustMe",
            "/RegisterPython=0",
            "/AddToPath=0",
            "/S",
            f"/D={prefix}",
        ]
        self._run_installer_command(cmd, "Installing private Miniconda...", timeout=1200)
        conda = os.path.join(prefix, "Scripts", "conda.exe")
        if not os.path.isfile(conda):
            raise RuntimeError(f"Miniconda installer finished but conda.exe was not found at {conda}")
        return conda

    def _ensure_vina_executable(self):
        tools = managed_tools_dir()
        os.makedirs(tools, exist_ok=True)
        destination = os.path.join(tools, "vina.exe" if IS_WINDOWS else "vina")

        if os.path.isfile(destination):
            check = run_hidden_subprocess(
                [destination, "--help"], stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, timeout=20,
            )
            if check.returncode == 0:
                self._installer_log("Verified existing Vina executable: " + destination)
                return destination

        if IS_WINDOWS:
            cached = os.path.join(managed_root_dir(), 'downloads', 'vina_1.2.7_win.exe')
            expected = VINA_TRUSTED_SHA256_BY_ASSET.get('vina_1.2.7_win.exe')
            if expected and os.path.isfile(cached) and sha256_file(cached) == expected:
                shutil.copy2(cached, destination)
                check = run_hidden_subprocess([destination, '--help'], capture_output=True, text=True, timeout=20)
                if check.returncode == 0:
                    self._installer_log('Vina restored from verified local cache.')
                    return destination
        # Resolve only the pinned release. Downloaded executables are accepted only
        # when their asset name has a hash in the trusted table above.
        api = f"https://api.github.com/repos/ccsb-scripps/AutoDock-Vina/releases/tags/{VINA_RELEASE_TAG}"
        tag = VINA_RELEASE_TAG
        asset_url = ""
        asset_name = ""
        try:
            req = urllib.request.Request(api, headers={
                "User-Agent": f"VLiP/{APP_VERSION} dependency installer",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            returned_tag = str(payload.get("tag_name") or "")
            if returned_tag != VINA_RELEASE_TAG:
                raise RuntimeError(
                    f"GitHub returned unexpected Vina release {returned_tag!r}; expected {VINA_RELEASE_TAG!r}."
                )
            assets = payload.get("assets") or []
            system = platform.system().lower()
            machine = platform.machine().lower()
            for asset in assets:
                name = str(asset.get("name") or "")
                low = name.lower()
                if "vina_split" in low or not low.startswith("vina_"):
                    continue
                match = False
                if system == "windows":
                    match = ("win" in low and low.endswith(".exe"))
                elif system == "linux":
                    match = ("linux" in low and ("x86_64" in low or "amd64" in low))
                elif system == "darwin":
                    if "arm" in machine or "aarch64" in machine:
                        match = ("mac" in low and ("arm" in low or "aarch64" in low))
                    else:
                        match = ("mac" in low and ("x86_64" in low or "intel" in low))
                if match:
                    asset_url = str(asset.get("browser_download_url") or "")
                    asset_name = name
                    break
        except Exception as exc:
            self._installer_log(f"GitHub release lookup warning: {exc}")

        if not asset_url and IS_WINDOWS:
            asset_name = "vina_1.2.7_win.exe"
            asset_url = "https://github.com/ccsb-scripps/AutoDock-Vina/releases/download/v1.2.7/vina_1.2.7_win.exe"
        if not asset_url:
            raise RuntimeError("Could not resolve a suitable official AutoDock Vina binary for this platform.")

        expected_sha256 = VINA_TRUSTED_SHA256_BY_ASSET.get(asset_name.casefold(), "")
        if not expected_sha256:
            raise RuntimeError(
                f"No trusted SHA-256 is configured for Vina asset {asset_name!r}; refusing to install it."
            )

        temp_path = os.path.join(managed_root_dir(), "downloads", asset_name)
        self._download_to(asset_url, temp_path, f"AutoDock Vina {tag}", expected_sha256)
        shutil.copy2(temp_path, destination)
        if not IS_WINDOWS:
            try:
                os.chmod(destination, os.stat(destination).st_mode | 0o111)
            except Exception:
                pass
        check = run_hidden_subprocess(
            [destination, "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20
        )
        if check.returncode != 0:
            raise RuntimeError(f"Downloaded Vina did not pass --help validation: {check.stderr or check.stdout}")
        self._installer_log(f"Vina ready: {destination}")
        return destination

    def _ensure_managed_runtime(self, conda):
        """Install / repair a fully isolated docking environment, preserving Conda OpenBabel bindings.

        PLIP declares OpenBabel as a pip requirement; pip's Windows source build is not
        interchangeable with conda-forge's DLLs. Install OpenBabel first from conda-forge,
        then install PLIP *without* recursively replacing that dependency.
        """
        env = managed_runtime_dir()
        env_python = os.path.join(env, "python.exe" if IS_WINDOWS else "bin/python")
        action = "install" if os.path.isfile(env_python) else "create"
        command = [conda, action, "-y", "-p", env, "--override-channels", "-c", "conda-forge"]
        command += [
            "python=3.12", "tk=8.6", "pip", "openbabel=3.2.1", "numpy=1.26", "lxml",
            "rdkit=2025.09.6", "scipy=1.16.3", "gemmi=0.7.3", "matplotlib", "tqdm", "packaging",
        ]
        self._run_installer_command(command, "Preparing VLiP's private docking environment...", timeout=3600)
        self._run_installer_command(
            [env_python, "-m", "pip", "install", "pdb2pqr==3.7.1"],
            "Installing PDB2PQR and PROPKA...", timeout=1200, env=managed_runtime_subprocess_env(),
        )
        self._run_installer_command(
            [env_python, "-m", "pip", "install", "--no-deps", "plip==2.4.0", "meeko==0.7.1"],
            "Installing PLIP and Meeko without replacing Conda OpenBabel...",
            timeout=1200, env=managed_runtime_subprocess_env(),
        )
        probe_code = (
            "import tkinter, plip, openbabel, meeko, pdb2pqr, propka, rdkit, scipy, gemmi, matplotlib; "
            "from openbabel import pybel; from pathlib import Path; import sys; "
            "p=Path(sys.executable).resolve().parent; d=[p,p/'Scripts',p/'bin']; "
            "has=lambda names:any((x/n).is_file() for x in d for n in names); "
            "assert has(['pdb2pqr.exe','pdb2pqr']), 'PDB2PQR executable missing'; "
            "assert has(['mk_prepare_receptor.py.exe','mk_prepare_receptor.exe','mk_prepare_receptor.py']), 'Meeko executable missing'; "
            "print('VLiP 2.0 docking runtime OK')"
        )
        self._run_installer_command(
            [env_python, "-c", probe_code], "Validating complete docking runtime...",
            timeout=180, env=managed_runtime_subprocess_env(),
        )
        return env_python

    def _ensure_current_matplotlib(self):
        """Do not mutate the Python/Conda environment used to launch VLiP.

        The v1.44 interactive preview uses VLiP's built-in Tk viewer and no
        longer depends on Matplotlib. The managed runtime may still include it
        for scientific tooling and compatibility.
        """
        if plt is not None:
            self._installer_log("Matplotlib already available to the main VLiP GUI.")
            return True
        self._installer_log(
            "Main GUI Matplotlib not available; leaving the user's Python/Conda environment untouched."
        )
        return False

    def install_or_repair_all_tools(self):
        if getattr(self, "installer_thread", None) is not None and self.installer_thread.is_alive():
            try:
                self.installer_win.lift()
            except Exception:
                pass
            return

        logs_dir = os.path.join(managed_root_dir(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        self.installer_log_path = os.path.join(
            logs_dir, "setup_" + time.strftime("%Y%m%d_%H%M%S") + ".log")
        self._installer_file_lock = threading.RLock()
        win = tk.Toplevel(self.root)
        self.installer_win = win
        win.title("VLiP — Install / Repair ALL dependencies")
        win.geometry("820x520")
        win.transient(self.root)

        self.installer_status_var = tk.StringVar(value="Starting dependency check...")
        tk.Label(win, textvariable=self.installer_status_var, anchor="w", justify="left").pack(fill="x", padx=10, pady=(10, 5))

        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True, padx=10, pady=5)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")
        text = tk.Text(frame, wrap="word", yscrollcommand=scrollbar.set, state="disabled")
        text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=text.yview)
        self.installer_text = text

        tk.Label(win, text=f"Setup log: {self.installer_log_path}", anchor="w", justify="left",
                 wraplength=780).pack(fill="x", padx=10)
        self.installer_close_btn = tk.Button(win, text="Close", state="disabled", command=win.destroy)
        self.installer_close_btn.pack(pady=(5, 10))

        def worker():
            success = False
            vina_path = ""
            try:
                os.makedirs(managed_root_dir(), exist_ok=True)
                self._installer_log(f"Managed VLiP root: {managed_root_dir()}")
                vina_path = self._ensure_vina_executable()
                conda = self._ensure_managed_conda()
                self._ensure_managed_runtime(conda)
                self._ensure_current_matplotlib()
                final_report, success = format_self_check_report(vina_path)
                self._installer_log("POST-INSTALL VALIDATION\n" + final_report)
                if not success:
                    raise RuntimeError("A required docking dependency failed post-install validation.")
                self._installer_log("ALL required VLiP components passed validation.")
            except Exception as exc:
                self._installer_log("INSTALL/REPAIR FAILED")
                self._installer_log(str(exc))
                self._installer_log(traceback.format_exc())

            def finish():
                try:
                    self.installer_close_btn.config(state="normal")
                    if success:
                        if vina_path:
                            self.vina_var.set(vina_path)
                        self.save_settings()
                        self.receptor_tool_status_var.set("Full VLiP toolchain installed and validated.")
                        report, _ = format_self_check_report(self.vina_var.get().strip())
                        self._installer_log("\nPOST-INSTALL SELF-CHECK\n" + report)
                        messagebox.showinfo(
                            "VLiP setup complete",
                            "Everything needed by VLiP has been installed/repaired and validated.\n\n"
                            f"Vina: {vina_path}\n"
                            f"Managed runtime: {managed_runtime_dir()}"
                        )
                    else:
                        self.receptor_tool_status_var.set("Dependency setup failed — see installer log.")
                        messagebox.showerror("VLiP setup failed", "Setup did not finish cleanly. The installer log shows the failing step.")

                    if getattr(self, "_offer_restore_after_installer", False):
                        self._offer_restore_after_installer = False
                        self.root.after(300, self.finish_startup_navigation)
                except Exception:
                    pass
            self.root.after(0, finish)

        self.installer_thread = threading.Thread(target=worker, daemon=True, name="VLIPDependencyInstaller")
        self.installer_thread.start()

    def open_pdbqt_preparer(self):
        """Open the embedded preparer in the managed scientific runtime."""
        script = self._single_file_script()
        theme_args = ["--vlip-follow-theme"]
        if bool(self.night_mode_var.get()):
            theme_args.append("--night-mode")
        try:
            managed_gui_python = managed_runtime_python(True)
            if managed_gui_python:
                popen_hidden_subprocess(
                    [managed_gui_python, script, "--pdbqt-prep-gui", "--vlip-handoff", self.receptor_handoff_path()] + theme_args,
                    cwd=self.user_working_dir(),
                    env=managed_runtime_subprocess_env(),
                )
                return

            # Backwards compatibility with the older named environment.
            if IS_WINDOWS:
                conda = self._find_conda_executable()
                if conda and self._conda_env_exists(conda, "vlip-pdbqt"):
                    cmd = [
                        conda, "run", "--no-capture-output", "-n", "vlip-pdbqt",
                        "pythonw", script, "--pdbqt-prep-gui",
                        "--vlip-handoff", self.receptor_handoff_path(),
                    ] + theme_args
                    popen_hidden_subprocess(cmd, cwd=self.user_working_dir())
                    return

            answer = messagebox.askyesno(
                "VLiP runtime not installed",
                "The receptor-preparation runtime is missing.\n\nRun Install / Repair ALL now?"
            )
            if answer:
                self.install_or_repair_all_tools()
        except Exception as exc:
            messagebox.showerror("Could not open PDB → PDBQT preparer", str(exc))

    def open_ligand_preparer(self):
        """Open the embedded ligand preparer in the managed scientific runtime."""
        script = self._single_file_script()
        theme_args = ["--vlip-follow-theme"]
        if bool(self.night_mode_var.get()):
            theme_args.append("--night-mode")
        try:
            managed_gui_python = managed_runtime_python(True)
            if managed_gui_python:
                popen_hidden_subprocess(
                    [
                        managed_gui_python, script, "--ligand-prep-gui",
                        "--vlip-ligand-handoff", self.ligand_handoff_path(),
                    ] + theme_args,
                    cwd=self.user_working_dir(),
                    env=managed_runtime_subprocess_env(),
                )
                return

            if IS_WINDOWS:
                conda = self._find_conda_executable()
                if conda and self._conda_env_exists(conda, "vlip-pdbqt"):
                    cmd = [
                        conda, "run", "--no-capture-output", "-n", "vlip-pdbqt",
                        "pythonw", script, "--ligand-prep-gui",
                        "--vlip-ligand-handoff", self.ligand_handoff_path(),
                    ] + theme_args
                    popen_hidden_subprocess(cmd, cwd=self.user_working_dir())
                    return

            answer = messagebox.askyesno(
                "VLiP runtime not installed",
                "Ligand preparation needs the managed RDKit/Open Babel/Meeko runtime.\n\n"
                "Run Install / Repair ALL now?",
            )
            if answer:
                self.install_or_repair_all_tools()
        except Exception as exc:
            messagebox.showerror("Could not open Ligand Preparation", str(exc))

    # ----------------------
    # Settings
    # ----------------------
    def load_settings(self):
        self.settings = {}
        sp = settings_path()
        if os.path.exists(sp):
            try:
                with open(sp, "r", encoding="utf-8", errors="replace") as f:
                    self.settings = json.load(f)
            except Exception:
                self.settings = {}

        self.receptors = self.settings.get("receptors", [])
        self.ligands = self.settings.get("ligands", [])
        recent = self.settings.get("recent_projects", [])
        self.recent_projects = [dict(item) for item in recent if isinstance(item, dict)][:MAX_RECENT_PROJECTS]

    def get_experiment_notes(self):
        notes_widget = getattr(self, "experiment_notes_text", None)
        if notes_widget is None:
            return str(self.settings.get("experiment_notes", "")).strip()
        try:
            return notes_widget.get("1.0", "end-1c").strip()
        except Exception:
            return str(self.settings.get("experiment_notes", "")).strip()

    def save_settings(self):
        self.settings.update({
            "ligand": self.ligand_var.get(),
            "ligands": self.ligands,
            "vina": self.vina_var.get(),
            "outdir": self.outdir_var.get(),
            "padding": self.padding_var.get(),
            "repeats": self.repeat_var.get(),
            "exhaust": self.exhaust_var.get(),
            "vina_options": {k: v.get() for k, v in self.vina_option_vars.items()},
            "speed_mode": self._normalize_speed_mode(self.speed_var.get()),
            "speed_schedule_enabled": bool(self.speed_schedule_enabled_var.get()),
            "speed_schedule_start": self.speed_schedule_start_var.get().strip(),
            "speed_schedule_end": self.speed_schedule_end_var.get().strip(),
            "merge": self.merge_var.get(),
            "pdb": self.pdb_var.get(),
            "txt": self.txt_var.get(),
            "run_plip": self.plip_var.get(),
            "plip_workers": self.plip_workers_var.get(),
            "receptors": self.receptors,
            "experiment_notes": self.get_experiment_notes(),
            "recent_projects": list(getattr(self, "recent_projects", []))[:MAX_RECENT_PROJECTS],
            "simple_mode": bool(self.simple_mode_var.get()),
            "night_mode": bool(self.night_mode_var.get()) if hasattr(self, "night_mode_var") else False,
            "show_receptor_tools": bool(self.show_receptor_tools_var.get()) if hasattr(self, "show_receptor_tools_var") else True,
        })
        try:
            with open(settings_path(), "w", encoding="utf-8") as f:
                json.dump(self.settings, f, indent=2)
        except Exception:
            pass

    def apply_night_mode(self, save=True):
        """Apply a saved light/dark palette to existing and future VLiP windows."""
        dark = bool(self.night_mode_var.get())
        palette = {
            "background": "#0c1523" if dark else "#f0f0f0",
            "panel": "#172438" if dark else "#f0f0f0",
            "field": "#101c2c" if dark else "#ffffff",
            "foreground": "#edf3fa" if dark else "#111111",
            "muted": "#a5b4c7" if dark else "#404040",
            "accent": "#263e59" if dark else "#d9e7f5",
            "select": "#287fc1" if dark else "#0078d7",
        }
        bg = palette["background"]
        panel = palette["panel"]
        field = palette["field"]
        fg = palette["foreground"]
        accent = palette["accent"]
        select = palette["select"]

        for pattern, value in (
            ("*Background", bg), ("*Foreground", fg),
            ("*insertBackground", fg), ("*selectBackground", select),
            ("*selectForeground", "#ffffff"),
        ):
            try:
                self.root.option_add(pattern, value, "userDefault")
            except Exception:
                pass

        style = ttk.Style(self.root)
        try:
            target_theme = "clam" if dark else getattr(self, "_base_ttk_theme", style.theme_use())
            if target_theme in style.theme_names():
                style.theme_use(target_theme)
        except Exception:
            pass
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TButton", background=panel, foreground=fg)
        style.map("TButton", background=[("active", accent)])
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.configure("TEntry", fieldbackground=field, foreground=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg)
        style.map("TCombobox", fieldbackground=[("readonly", field)], foreground=[("readonly", fg)])
        style.configure("Treeview", background=field, fieldbackground=field, foreground=fg, rowheight=24)
        style.map("Treeview", background=[("selected", select)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=panel, foreground=fg)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background=panel, foreground=fg)
        style.map("TNotebook.Tab", background=[("selected", accent)])
        style.configure("TProgressbar", background=select, troughcolor=field)
        _vlip_polish_styles(style, bg, panel, field, fg, accent, select)

        def recolor(widget):
            if isinstance(widget, tk.Toplevel):
                viewer = getattr(widget, "_vlip_pose_viewer", None)
                if viewer is not None:
                    try:
                        viewer.apply_night_mode(dark)
                    except Exception:
                        pass
                    return
            try:
                if isinstance(widget, (tk.Tk, tk.Toplevel, tk.Frame, tk.PanedWindow)):
                    widget.configure(bg=bg)
                elif isinstance(widget, tk.LabelFrame):
                    widget.configure(bg=bg, fg=fg, relief="groove", borderwidth=1, font=("Segoe UI", 9, "bold"))
                elif isinstance(widget, (tk.Label, tk.Message)):
                    widget.configure(bg=bg, fg=fg)
                elif isinstance(widget, tk.Button):
                    widget.configure(bg=panel, fg=fg, activebackground=accent, activeforeground=fg,
                                 relief="flat", borderwidth=1, padx=8, pady=4,
                                 highlightthickness=1, highlightbackground=accent, highlightcolor=select,
                                 disabledforeground="#8794a5")
                elif isinstance(widget, (tk.Checkbutton, tk.Radiobutton)):
                    widget.configure(
                        bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                        selectcolor=field,
                    )
                elif isinstance(widget, (tk.Text, tk.Entry, tk.Listbox, tk.Spinbox)):
                    widget.configure(
                        bg=field, fg=fg, insertbackground=fg,
                        selectbackground=select, selectforeground="#ffffff",
                    )
                elif isinstance(widget, tk.Scale):
                    widget.configure(
                        bg=bg, fg=fg, activebackground=accent, troughcolor=field,
                        highlightbackground=bg,
                    )
                elif isinstance(widget, tk.Scrollbar):
                    widget.configure(bg=panel, activebackground=accent, troughcolor=bg)
                elif isinstance(widget, tk.Canvas):
                    widget.configure(bg=bg, highlightbackground=panel)
                elif isinstance(widget, tk.Menu):
                    widget.configure(bg=panel, fg=fg, activebackground=accent, activeforeground=fg,
                                 relief="flat", borderwidth=1, padx=8, pady=4,
                                 highlightthickness=1, highlightbackground=accent, highlightcolor=select,
                                 disabledforeground="#8794a5")
            except (tk.TclError, AttributeError):
                pass
            try:
                for child in widget.winfo_children():
                    recolor(child)
            except Exception:
                pass
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                _vlip_set_window_dark_titlebar(widget, dark)
                callback = getattr(widget, "_vlip_theme_callback", None)
                if callback is not None:
                    try:
                        callback(dark)
                    except Exception:
                        pass

        recolor(self.root)
        try:
            self.run_button.configure(
                bg="#207a3c" if dark else "green",
                fg="white",
                activebackground="#2b9950" if dark else "#159447",
                activeforeground="white",
            )
        except Exception:
            pass
        try:
            self._apply_queue_status_badges(dark)
        except Exception:
            pass
        if save:
            self.save_settings()

    def _theme_mapped_window(self, event):
        """Apply the current palette after any VLiP window finishes constructing."""
        if not isinstance(event.widget, (tk.Tk, tk.Toplevel)):
            return
        window = event.widget
        if getattr(window, "_vlip_theme_pending", False):
            return
        window._vlip_theme_pending = True

        def apply_after_map():
            try:
                window._vlip_theme_pending = False
                self.apply_night_mode(save=False)
            except Exception:
                pass

        try:
            window.after_idle(apply_after_map)
        except Exception:
            pass

    def toggle_receptor_tools(self, save=True):
        """Expand or collapse the receptor-preparation controls without moving other sections."""
        frame = getattr(self, "receptor_tools_frame", None)
        if frame is None:
            return
        if self.show_receptor_tools_var.get():
            if not frame.winfo_manager():
                frame.pack(fill="x", pady=(2, 0))
        else:
            frame.pack_forget()
        self.apply_night_mode(save=False)        if save:
            self.save_settings()

    # ----------------------
    # Projects, results and reporting
    # ----------------------
    def _project_has_data(self, project_dir):
        if not project_dir or not os.path.isdir(project_dir):
            return False
        expected = (
            project_state_path(project_dir),
            os.path.join(project_dir, "all ligands docking scores.txt"),
            os.path.join(project_dir, COMPLETE_SETTINGS_FILENAME),
            os.path.join(project_dir, "VLIP_RUN.json"),
        )
        return any(os.path.isfile(path) for path in expected)

    def _choose_project_dir(self, project_dir=None, title="Select a VLiP project folder"):
        candidate = str(project_dir or "").strip()
        if not candidate:
            current = getattr(self, "outdir_var", None)
            candidate = current.get().strip() if current is not None else ""
        if self._project_has_data(candidate):
            return os.path.abspath(candidate)
        chosen = filedialog.askdirectory(title=title, initialdir=candidate if os.path.isdir(candidate) else None)
        if chosen and self._project_has_data(chosen):
            return os.path.abspath(chosen)
        if chosen:
            messagebox.showwarning(
                "Not a VLiP project",
                "That folder does not contain a VLiP project state, settings record, or combined docking report."
            )
        return ""

    def _remember_recent_project(self, project_dir, status=None):
        if not project_dir:
            return
        project_dir = os.path.abspath(os.path.normpath(project_dir))
        state = read_json_file(project_state_path(project_dir)) or {}
        config = state.get("run_config") or {}
        item = {
            "path": project_dir,
            "status": str(status or state.get("status") or "project"),
            "updated_at": str(state.get("updated_at") or time.strftime("%Y-%m-%d %H:%M:%S")),
            "next_job_index": int(state.get("next_job_index", 0) or 0),
            "total_jobs": int(state.get("total_jobs", 0) or 0),
            "notes": str(config.get("experiment_notes") or "").strip(),
        }
        key = normalized_path_key(project_dir)
        existing = [
            dict(entry) for entry in getattr(self, "recent_projects", [])
            if normalized_path_key(entry.get("path", "")) != key
        ]
        self.recent_projects = [item, *existing][:MAX_RECENT_PROJECTS]
        self.save_settings()

    def _refresh_recent_projects(self):
        refreshed = []
        seen = set()
        for entry in getattr(self, "recent_projects", []):
            raw_path = str(entry.get("path", "")).strip()
            if not raw_path:
                continue
            path = os.path.abspath(os.path.normpath(raw_path))
            key = normalized_path_key(path)
            if key in seen:
                continue
            seen.add(key)
            state = read_json_file(project_state_path(path)) or {}
            config = state.get("run_config") or {}
            refreshed.append({
                "path": path,
                "status": str(state.get("status") or entry.get("status") or ("missing" if not os.path.isdir(path) else "project")),
                "updated_at": str(state.get("updated_at") or entry.get("updated_at") or ""),
                "next_job_index": int(state.get("next_job_index", entry.get("next_job_index", 0)) or 0),
                "total_jobs": int(state.get("total_jobs", entry.get("total_jobs", 0)) or 0),
                "notes": str(config.get("experiment_notes") or entry.get("notes") or "").strip(),
            })
        self.recent_projects = refreshed[:MAX_RECENT_PROJECTS]
        return list(self.recent_projects)

    def _read_project_results(self, project_dir):
        """Read a combined score table and attach checkpoint/PLIP status."""
        score_path = os.path.join(project_dir, "all ligands docking scores.txt")
        if not os.path.isfile(score_path):
            return []

        state = read_json_file(project_state_path(project_dir)) or {}
        config = state.get("run_config") or {}
        plip_enabled = bool(config.get("run_plip", os.path.isfile(os.path.join(project_dir, "all ligands plip.txt"))))
        status_map = {}
        for detail in (state.get("job_statuses") or {}).values():
            if not isinstance(detail, dict):
                continue
            key = (
                str(detail.get("ligand_name") or ""),
                str(detail.get("receptor_name") or ""),
                int(detail.get("run_index", 0) or 0),
            )
            status_map[key] = str(detail.get("status") or "").upper()

        results = []
        with open(score_path, "r", encoding="utf-8", errors="replace", newline="") as source:
            reader = csv.DictReader((line for line in source if not line.startswith("# ")), delimiter="\t")
            if not reader.fieldnames or "Ligand" not in reader.fieldnames:
                return []
            for row in reader:
                ligand = str(row.get("Ligand") or "").strip()
                receptor = str(row.get("Receptor") or "").strip()
                run_text = str(row.get("Run") or "").strip()
                run_match = re.search(r"(\d+)", run_text)
                run_index = int(run_match.group(1)) if run_match else 0
                affinity_text = str(row.get("Affinity (kcal/mol)") or "").strip()
                try:
                    affinity = float(affinity_text)
                except ValueError:
                    affinity = None

                dock_file = str(row.get("Dock File") or "").strip()
                if dock_file and not os.path.isabs(dock_file):
                    dock_file = os.path.abspath(os.path.join(project_dir, dock_file))
                output_file = str(row.get("Output File") or "").strip()

                plip_report = ""
                plip_reports = []
                plip_dir = os.path.join(project_dir, ligand, "plip", receptor, f"run_{run_index}")
                plip_reports = preferred_pose_plip_summaries(plip_dir)
                summary_names = [os.path.basename(path) for path in plip_reports]
                if plip_reports:
                    plip_report = plip_reports[0]

                job_status = status_map.get((ligand, receptor, run_index), "")
                if plip_report:
                    plip_status = f"Available ({len(summary_names)} pose{'s' if len(summary_names) != 1 else ''})"
                elif not plip_enabled:
                    plip_status = "Disabled"
                elif job_status == "PARTIAL":
                    plip_status = "Incomplete"
                elif job_status in {"FAILED", "SKIPPED"}:
                    plip_status = job_status.title()
                else:
                    plip_status = "Not found"

                results.append({
                    "ligand": ligand,
                    "receptor": receptor,
                    "run": run_index,
                    "affinity": affinity,
                    "affinity_text": affinity_text,
                    "output_file": output_file,
                    "dock_file": dock_file,
                    "plip_status": plip_status,
                    "plip_report": plip_report,
                    "plip_reports": plip_reports,
                    "job_status": job_status or "UNKNOWN",
                })
        return results

    def _project_metadata(self, project_dir):
        state = read_json_file(project_state_path(project_dir)) or {}
        config = state.get("run_config") or {}
        record_path = os.path.join(project_dir, COMPLETE_SETTINGS_FILENAME)
        record_text = ""
        if os.path.isfile(record_path):
            try:
                with open(record_path, "r", encoding="utf-8", errors="replace") as source:
                    record_text = source.read()
            except OSError:
                record_text = ""

        wanted = {
            "VLiP version",
            "Configuration fingerprint (SHA-256)",
            "Actual Vina version reported",
            "Vina executable",
            "Actual installed PLIP version",
            "Managed PLIP/Python runtime",
        }
        recorded = {}
        for line in record_text.splitlines():
            if ":" not in line or line[:1].isspace():
                continue
            key, value = line.split(":", 1)
            if key.strip() in wanted and key.strip() not in recorded:
                recorded[key.strip()] = value.strip()

        ligand_paths = [str(path) for path in (config.get("ligands_to_run") or [])]
        receptors = config.get("receptors") or []
        receptor_text = []
        for receptor in receptors:
            if not isinstance(receptor, dict):
                continue
            receptor_text.append(
                f"{receptor.get('path', '')} [mode={receptor.get('mode', 'Whole')}; "
                f"residues={receptor.get('residues', '') or 'none'}; padding={receptor.get('padding', '') or 'default'}]"
            )

        metadata = {
            "Project folder": os.path.abspath(project_dir),
            "Status": str(state.get("status") or "unknown"),
            "Updated": str(state.get("updated_at") or "unknown"),
            "Progress": f"{int(state.get('next_job_index', 0) or 0)} / {int(state.get('total_jobs', 0) or 0)} jobs",
            "VLiP version": recorded.get("VLiP version", "unknown"),
            "Configuration fingerprint": recorded.get("Configuration fingerprint (SHA-256)", "unknown"),
            "Vina version": recorded.get("Actual Vina version reported", "unknown"),
            "Vina executable": recorded.get("Vina executable", str(config.get("vina") or "unknown")),
            "PLIP version": recorded.get("Actual installed PLIP version", "disabled" if not config.get("run_plip") else "unknown"),
            "PLIP runtime": recorded.get("Managed PLIP/Python runtime", "unknown"),
            "Repeats": str(config.get("repeats", "unknown")),
            "Exhaustiveness": str(config.get("exhaustiveness", "unknown")),
            "Vina options": "\n".join(vina_option_lines(config.get("vina_options"))),
            "Default padding": str(config.get("default_padding", "unknown")),
            "Run PLIP": "YES" if config.get("run_plip") else "NO",
            "Save merged PDBQT": "YES" if config.get("save_merge") else "NO",
            "Convert to PDB": "YES" if config.get("save_pdb") else "NO",
            "Save raw Vina text": "YES" if config.get("save_txt") else "NO",
            "Ligands": "\n".join(ligand_paths) if ligand_paths else "not recorded",
            "Receptors": "\n".join(receptor_text) if receptor_text else "not recorded",
            "Experiment notes": str(config.get("experiment_notes") or "").strip() or "(none)",
        }
        return metadata, state, record_text

    def _compare_project_data(self, project_a, project_b):
        metadata_a, _state_a, _record_a = self._project_metadata(project_a)
        metadata_b, _state_b, _record_b = self._project_metadata(project_b)
        settings_rows = []
        for key in metadata_a.keys() | metadata_b.keys():
            if key == "Project folder":
                continue
            value_a = str(metadata_a.get(key, ""))
            value_b = str(metadata_b.get(key, ""))
            settings_rows.append({
                "setting": key,
                "a": value_a,
                "b": value_b,
                "match": value_a == value_b,
            })
        settings_rows.sort(key=lambda row: (row["match"], row["setting"].lower()))

        results_a = {
            (row["ligand"], row["receptor"], row["run"]): row for row in self._read_project_results(project_a)
        }
        results_b = {
            (row["ligand"], row["receptor"], row["run"]): row for row in self._read_project_results(project_b)
        }
        score_rows = []
        for key in sorted(results_a.keys() | results_b.keys()):
            row_a = results_a.get(key)
            row_b = results_b.get(key)
            affinity_a = row_a.get("affinity") if row_a else None
            affinity_b = row_b.get("affinity") if row_b else None
            delta = affinity_b - affinity_a if affinity_a is not None and affinity_b is not None else None
            score_rows.append({
                "ligand": key[0],
                "receptor": key[1],
                "run": key[2],
                "a": affinity_a,
                "b": affinity_b,
                "delta": delta,
            })
        return settings_rows, score_rows

    def _format_duration(self, seconds):
        try:
            seconds = max(0, int(round(float(seconds))))
        except (TypeError, ValueError):
            return "unknown"
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        if minutes:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"

    def _historical_run_estimate(self, args):
        samples = []
        desired_plip = bool(args.get("run_plip"))
        paths = [args.get("outdir", "")]
        paths.extend(entry.get("path", "") for entry in getattr(self, "recent_projects", []))
        seen = set()
        for path in paths:
            key = normalized_path_key(path)
            if not path or key in seen:
                continue
            seen.add(key)
            state = read_json_file(project_state_path(path)) or {}
            state_config = state.get("run_config") or {}
            if bool(state_config.get("run_plip")) != desired_plip:
                continue
            for detail in (state.get("job_statuses") or {}).values():
                if not isinstance(detail, dict) or str(detail.get("status", "")).upper() not in {"COMPLETE", "PARTIAL"}:
                    continue
                try:
                    duration = float(detail.get("duration_seconds"))
                except (TypeError, ValueError):
                    continue
                if duration > 0:
                    samples.append(duration)
        if not samples:
            return None, 0
        average = sum(samples[-500:]) / len(samples[-500:])
        remaining_jobs = max(0, int(args.get("total_jobs", 0)) - int(args.get("resume_from_job", 0) or 0))
        return average * remaining_jobs, len(samples[-500:])

    def _open_local_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showwarning("File not found", f"The selected file or folder no longer exists:\n\n{path}")
            return False
        try:
            if IS_WINDOWS:
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            return True
        except Exception as exc:
            messagebox.showerror("Could not open", str(exc))
            return False

    def _generate_html_project_report(self, project_dir, output_path):
        metadata, state, record_text = self._project_metadata(project_dir)
        results = self._read_project_results(project_dir)
        problem_jobs = []
        for job_index, item in (state.get("job_statuses") or {}).items():
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").upper()
            if status in {"FAILED", "SKIPPED", "PARTIAL"}:
                problem_jobs.append({"job_index": job_index, **item})
        if not problem_jobs:
            problem_jobs = [item for item in (state.get("failed_jobs") or []) if isinstance(item, dict)]

        def esc(value):
            return html.escape(str(value), quote=True)

        metadata_rows = "\n".join(
            f"<tr><th>{esc(key)}</th><td>{esc(value).replace(chr(10), '<br>')}</td></tr>"
            for key, value in metadata.items()
        )
        result_rows = []
        for row in results:
            affinity = row["affinity_text"] or "not available"
            dock_display = row["dock_file"] or row["output_file"]
            result_rows.append(
                "<tr>"
                f"<td>{esc(row['ligand'])}</td><td>{esc(row['receptor'])}</td>"
                f"<td>{esc(row['run'])}</td><td>{esc(affinity)}</td>"
                f"<td>{esc(row['job_status'])}</td><td>{esc(row['plip_status'])}</td>"
                f"<td class='path'>{esc(dock_display)}</td>"
                "</tr>"
            )
        if not result_rows:
            result_rows.append("<tr><td colspan='7'>No combined docking results were found.</td></tr>")

        issue_rows = []
        for item in problem_jobs:
            try:
                display_job_index = int(item.get("job_index", 0)) + 1
            except (TypeError, ValueError):
                display_job_index = item.get("job_index", "?")
            issue_rows.append(
                "<tr>"
                f"<td>{esc(display_job_index)}</td>"
                f"<td>{esc(item.get('ligand_name', item.get('ligand', '')))}</td>"
                f"<td>{esc(item.get('receptor_name', item.get('receptor', '')))}</td>"
                f"<td>{esc(item.get('status', 'FAILED'))}</td>"
                f"<td>{esc(item.get('reason', 'unspecified'))}</td>"
                "</tr>"
            )
        if not issue_rows:
            issue_rows.append("<tr><td colspan='5'>No failed, skipped or partial jobs were recorded.</td></tr>")

        plip_sections = []
        seen_plip_paths = set()
        for row in results:
            report_paths = row.get("plip_reports") or ([row.get("plip_report")] if row.get("plip_report") else [])
            for report_path in report_paths:
                if normalized_path_key(report_path) in seen_plip_paths:
                    continue
                seen_plip_paths.add(normalized_path_key(report_path))
                try:
                    with open(report_path, "r", encoding="utf-8", errors="replace") as source:
                        interaction_text = source.read().strip()
                except OSError as exc:
                    interaction_text = f"Could not read PLIP summary: {exc}"
                pose_number = molecular_plip_pose_number(report_path)
                pose_name = f"pose{pose_number}" if pose_number is not None else os.path.basename(report_path)
                heading = f"{row['ligand']} / {row['receptor']} / Run {row['run']} / {pose_name}"
                plip_sections.append(
                    f"<details><summary>{esc(heading)}</summary><pre>{esc(interaction_text)}</pre></details>"
                )
        if not plip_sections:
            plip_sections.append("<p>No PLIP interaction summaries were available for this project.</p>")

        document = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VLiP Project Report</title>
<style>
body {{ font-family: Segoe UI, Arial, sans-serif; margin: 0; color: #17202a; background: #f4f6f8; }}
main {{ max-width: 1200px; margin: 0 auto; padding: 28px; }}
h1 {{ margin-bottom: 4px; }} .subtitle {{ color: #566573; margin-top: 0; }}
section {{ background: white; border: 1px solid #dfe4ea; border-radius: 8px; padding: 18px; margin: 18px 0; box-shadow: 0 1px 3px #0001; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th, td {{ border: 1px solid #dfe4ea; padding: 8px; text-align: left; vertical-align: top; }}
th {{ background: #edf2f7; }} .path {{ word-break: break-all; }}
pre {{ white-space: pre-wrap; word-break: break-word; background: #f7f9fa; border: 1px solid #e5e8eb; padding: 12px; max-height: 560px; overflow: auto; }}
.note {{ white-space: pre-wrap; background: #fff8dc; padding: 12px; border-left: 4px solid #d4a017; }}
details {{ margin: 10px 0; }} summary {{ cursor: pointer; font-weight: 600; }}
</style>
</head>
<body><main>
<h1>VLiP Project Report</h1>
<p class="subtitle">Generated by VLiP v{esc(APP_VERSION)} on {esc(time.strftime('%Y-%m-%d %H:%M:%S'))}</p>
<section><h2>Experiment Notes</h2><div class="note">{esc(metadata.get('Experiment notes', '(none)'))}</div></section>
<section><h2>Project and Settings</h2><table>{metadata_rows}</table></section>
<section><h2>Docking Results</h2><table><thead><tr><th>Ligand</th><th>Receptor</th><th>Run</th><th>Affinity (kcal/mol)</th><th>Job Status</th><th>PLIP</th><th>Dock File</th></tr></thead><tbody>{''.join(result_rows)}</tbody></table></section>
<section><h2>PLIP Interaction Summaries</h2>{''.join(plip_sections)}</section>
<section><h2>Recorded Problems</h2><table><thead><tr><th>Job</th><th>Ligand</th><th>Receptor</th><th>Status</th><th>Reason</th></tr></thead><tbody>{''.join(issue_rows)}</tbody></table></section>
<section><h2>Complete Reproducibility Record</h2><pre>{esc(record_text or 'Settings record not found.')}</pre></section>
</main></body></html>
"""
        atomic_write_text(output_path, document)
        return output_path

    def show_recent_projects(self, startup=False):
        entries = self._refresh_recent_projects()
        if not entries:
            if not startup:
                messagebox.showinfo("Recent Projects", "No VLiP projects have been recorded yet.")
            return

        existing = getattr(self, "recent_projects_win", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

        win = tk.Toplevel(self.root)
        self.recent_projects_win = win
        win.title(f"Recent VLiP Projects — v{APP_VERSION}")
        win.geometry("980x480")
        win.minsize(760, 360)
        win.transient(self.root)

        tk.Label(
            win,
            text="Recent Projects",
            font=("TkDefaultFont", 15, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 2))
        tk.Label(
            win,
            text="Reopen results, continue working with a project, compare runs, or export a report.",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True, padx=14)
        tree = ttk.Treeview(
            frame,
            columns=("project", "status", "progress", "updated", "notes"),
            show="headings",
            selectmode="browse",
        )
        columns = {
            "project": ("Project Folder", 390),
            "status": ("Status", 120),
            "progress": ("Jobs", 80),
            "updated": ("Last Updated", 150),
            "notes": ("Notes", 220),
        }
        for column, (label, width) in columns.items():
            tree.heading(column, text=label)
            tree.column(column, width=width, anchor="w")
        scrollbar = tk.Scrollbar(frame, command=tree.yview)
        tree.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        rows = {}
        for index, entry in enumerate(entries):
            iid = str(index)
            rows[iid] = entry
            total = int(entry.get("total_jobs", 0) or 0)
            progress = f"{int(entry.get('next_job_index', 0) or 0)}/{total}" if total else "—"
            notes = str(entry.get("notes") or "").replace("\n", " ")
            if len(notes) > 90:
                notes = notes[:87] + "..."
            tree.insert("", "end", iid=iid, values=(
                entry.get("path", ""), entry.get("status", ""), progress,
                entry.get("updated_at", ""), notes,
            ))
        if rows:
            tree.selection_set("0")

        def selected_entry():
            selection = tree.selection()
            return rows.get(selection[0]) if selection else None

        def selected_path():
            entry = selected_entry()
            return str(entry.get("path") or "") if entry else ""

        def set_as_output():
            entry = selected_entry()
            if not entry:
                return
            path = str(entry.get("path") or "")
            if not os.path.isdir(path):
                messagebox.showwarning("Project missing", f"This project folder no longer exists:\n\n{path}")
                return
            self.outdir_var.set(path)
            notes = str(entry.get("notes") or "")
            self.experiment_notes_text.delete("1.0", "end")
            self.experiment_notes_text.insert("1.0", notes)
            self.save_settings()
            messagebox.showinfo("Project selected", "The project is now the active output folder.", parent=win)

        def remove_selected():
            path = selected_path()
            if not path:
                return
            self.recent_projects = [
                entry for entry in self.recent_projects
                if normalized_path_key(entry.get("path", "")) != normalized_path_key(path)
            ]
            self.save_settings()
            close()
            self.show_recent_projects()

        button_row = tk.Frame(win)
        button_row.pack(fill="x", padx=14, pady=14)
        tk.Button(button_row, text="Open Results", command=lambda: self.open_results_explorer(selected_path())).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Compare", command=lambda: self.compare_projects(selected_path())).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Export HTML", command=lambda: self.export_project_report(selected_path())).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Use as Output", command=set_as_output).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Remove from List", command=remove_selected).pack(side="left", padx=(0, 6))

        def close():
            self.recent_projects_win = None
            win.destroy()

        tk.Button(button_row, text="Close", width=12, command=close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)
        tree.bind("<Double-1>", lambda _event: self.open_results_explorer(selected_path()))

    def _resolve_result_receptor_path(self, project_dir, result):
        """Find the original receptor recorded for one Results Explorer row."""
        state = read_json_file(project_state_path(project_dir)) or {}
        config = state.get("run_config") or {}
        target = str(result.get("receptor") or "").casefold()

        job_statuses = state.get("job_statuses") or {}
        for detail in job_statuses.values():
            if not isinstance(detail, dict):
                continue
            if str(detail.get("receptor_name") or "").casefold() != target:
                continue
            candidate = str(detail.get("receptor") or "")
            if candidate and os.path.isfile(candidate):
                return os.path.abspath(candidate)

        for receptor in config.get("receptors") or []:
            if not isinstance(receptor, dict):
                continue
            path = str(receptor.get("path") or "")
            names = {
                str(receptor.get("output_name") or "").casefold(),
                str(receptor.get("name") or "").casefold(),
                safe_output_stem(path).casefold() if path else "",
                os.path.splitext(os.path.basename(path))[0].casefold() if path else "",
            }
            if target in names and path and os.path.isfile(path):
                return os.path.abspath(path)
        return ""

    def _resolve_result_ligand_input(self, project_dir, result):
        """Use only a same-name SDF beside the ligand PDBQT supplied to Vina."""
        resolved = {
            "path": "",
            "kind": "blank_no_same_folder_sdf",
            "queued_path": "",
            "audit_path": "",
            "source_path": "",
            "prepared_sdf": "",
        }
        if not project_dir:
            return resolved

        state = read_json_file(project_state_path(project_dir)) or {}
        config = state.get("run_config") or {}
        target = str(result.get("ligand") or "").casefold()
        output_names = config.get("ligand_output_names") or {}

        for queued in config.get("ligands_to_run") or []:
            queued = str(queued or "")
            if not queued:
                continue
            output_name = output_names.get(normalized_path_key(queued), safe_output_stem(queued))
            names = {
                str(output_name).casefold(),
                safe_output_stem(queued).casefold(),
                os.path.splitext(os.path.basename(queued))[0].casefold(),
            }
            if target in names:
                resolved["queued_path"] = os.path.abspath(queued)
                break

        queued_path = resolved["queued_path"]
        if not queued_path:
            return resolved

        queued_stem = os.path.splitext(os.path.basename(queued_path))[0]
        queued_folder = os.path.dirname(queued_path)
        wanted_name = (queued_stem + ".sdf").casefold()
        try:
            same_folder_sdf = next(
                (
                    os.path.join(queued_folder, name)
                    for name in os.listdir(queued_folder)
                    if name.casefold() == wanted_name
                    and os.path.isfile(os.path.join(queued_folder, name))
                ),
                "",
            )
        except OSError:
            same_folder_sdf = ""

        if same_folder_sdf:
            same_folder_sdf = os.path.abspath(same_folder_sdf)
            resolved.update({
                "path": same_folder_sdf,
                "kind": "same_folder_matching_sdf",
                "source_path": same_folder_sdf,
                "prepared_sdf": same_folder_sdf,
            })
        return resolved

    def _merged_receptor_fallback(self, project_dir, result, ligand_models):
        """Recover receptor coordinates from a retained receptor+ligand complex."""
        ligand_name = str(result.get("ligand") or "")
        receptor_name = str(result.get("receptor") or "")
        run_index = int(result.get("run", 0) or 0)
        merged_dir = os.path.join(project_dir, ligand_name, receptor_name, f"run_{run_index}", "merged")
        if not os.path.isdir(merged_dir):
            return [], ""
        try:
            candidates = sorted(
                (
                    os.path.join(merged_dir, name)
                    for name in os.listdir(merged_dir)
                    if name.lower().endswith(".pdbqt") and "_merged" in name.lower()
                ),
                key=natural_sort_key,
            )
        except OSError:
            candidates = []
        if not candidates:
            return [], ""
        merged_path = candidates[0]
        try:
            merged_models = read_molecular_models(merged_path, source="receptor")
            merged_atoms = list(merged_models[0]["atoms"]) if merged_models else []
            first_ligand_model = next(
                (model for model in ligand_models if model.get("atoms")),
                {},
            )
            ligand_count = len(first_ligand_model.get("atoms") or [])
            if ligand_count and len(merged_atoms) > ligand_count:
                return merged_atoms[:-ligand_count], merged_path
        except OSError:
            pass
        return [], ""

    def open_pose_viewer_dialog(self):
        dock_file = filedialog.askopenfilename(
            title="Select a Vina docking output",
            filetypes=[("Vina PDBQT", "*.pdbqt"), ("PDB structures", "*.pdb"), ("All files", "*.*")],
        )
        if not dock_file:
            return
        receptor_file = filedialog.askopenfilename(
            title="Select the matching receptor (Cancel for ligand-only view)",
            initialdir=os.path.dirname(dock_file),
            filetypes=[("Receptor PDBQT/PDB", "*.pdbqt *.pdb"), ("All files", "*.*")],
        )
        self.open_pose_viewer(
            project_dir=os.path.dirname(dock_file),
            result={
                "ligand": os.path.splitext(os.path.basename(dock_file))[0],
                "receptor": os.path.splitext(os.path.basename(receptor_file))[0] if receptor_file else "Ligand-only",
                "run": 0,
                "dock_file": dock_file,
                "receptor_path": receptor_file,
                "plip_reports": [],
            },
        )

    def open_pose_viewer(self, project_dir, result, result_options=None):
        if not result:
            return
        result = dict(result)
        result["project_dir"] = os.path.abspath(project_dir) if project_dir else ""
        ligand_input = self._resolve_result_ligand_input(project_dir, result)
        result["ligand_source_path"] = ligand_input["path"]
        result["ligand_source_kind"] = ligand_input["kind"]
        result["queued_ligand_path"] = ligand_input["queued_path"]
        result["ligand_preparation_audit"] = ligand_input["audit_path"]
        if result_options is None:
            try:
                result_options = [
                    item for item in self._read_project_results(project_dir)
                    if item.get("dock_file") and os.path.isfile(item.get("dock_file"))
                ] if project_dir else []
            except Exception:
                result_options = []
        else:
            result_options = [
                dict(item) for item in result_options
                if isinstance(item, dict) and item.get("dock_file") and os.path.isfile(item.get("dock_file"))
            ]
        dock_file = str(result.get("dock_file") or "")
        if not dock_file or not os.path.isfile(dock_file):
            messagebox.showwarning(
                "Docked poses not found",
                "The docking PDBQT recorded for this result could not be found.\n\n"
                f"Recorded path:\n{dock_file or '(none)'}",
            )
            return
        try:
            ligand_models = read_molecular_models(dock_file, source="ligand")
        except OSError as exc:
            messagebox.showerror("Could not read docking poses", str(exc))
            return
        if not ligand_models or not any(model.get("atoms") for model in ligand_models):
            messagebox.showwarning(
                "No pose atoms",
                "The selected file contains no readable ATOM/HETATM pose records.",
            )
            return

        # Prefer the retained merged complex so the viewer uses the same receptor
        # coordinates that were combined with the docked ligand for this run.
        receptor_atoms, merged_path = self._merged_receptor_fallback(
            project_dir, result, ligand_models
        )
        receptor_path = merged_path
        if receptor_atoms:
            complex_note = (
                f"Merged complex source: {os.path.basename(merged_path)}. "
                "The view is focused on the ligand and its nearest complete residues."
            )
        else:
            receptor_path = str(result.get("receptor_path") or "")
            if not receptor_path or not os.path.isfile(receptor_path):
                receptor_path = self._resolve_result_receptor_path(project_dir, result)
            complex_note = (
                "Merged complex view reconstructed from the receptor and docked pose. "
                "The view is focused on the ligand and its nearest complete residues."
            )
        if result.get("auto_opened"):
            complex_note += " Automatically opened from the best completed docking result."
        if not receptor_atoms and receptor_path and os.path.isfile(receptor_path):
            try:
                receptor_models = read_molecular_models(receptor_path, source="receptor")
                receptor_atoms = list(receptor_models[0]["atoms"]) if receptor_models else []
            except OSError:
                receptor_atoms = []

        title = (
            f"{result.get('ligand', os.path.basename(dock_file))} / "
            f"{result.get('receptor', 'receptor')} / Run {result.get('run', '?')}"
        )
        try:
            viewer = MolecularPoseViewer(
                self.root,
                ligand_models=ligand_models,
                receptor_atoms=receptor_atoms,
                title=title,
                source_path=dock_file,
                receptor_path=receptor_path,
                plip_reports=result.get("plip_reports") or [],
                result_info=result,
                night_mode=bool(self.night_mode_var.get()),
                open_path_callback=self._open_local_path,
                preview_note=complex_note,
                result_options=result_options,
                result_switch_callback=(
                    (lambda selected, options=result_options: self.open_pose_viewer(
                        project_dir, selected, result_options=options
                    )) if result_options else None
                ),
            )
            viewer.win._vlip_pose_viewer = viewer
            if not receptor_atoms:
                viewer.status_var.set(
                    "Ligand poses loaded. The original receptor and a retained merged complex were not available."
                )
            return viewer
        except Exception as exc:
            messagebox.showerror("Could not open Pose Viewer", str(exc))
            return None

    def open_automatic_run_pose_viewer(self, project_dir):
        """Open every pose from the best completed docking result after a run."""
        try:
            results = self._read_project_results(project_dir)
        except Exception as exc:
            messagebox.showwarning(
                "Automatic Pose Viewer",
                f"Docking finished, but the results could not be loaded automatically.\n\n{exc}",
                parent=self.root,
            )
            return None

        candidates = [
            result for result in results
            if result.get("dock_file") and os.path.isfile(result["dock_file"])
        ]
        if not candidates:
            messagebox.showwarning(
                "Automatic Pose Viewer",
                "Docking finished, but no readable completed pose file was available to display.",
                parent=self.root,
            )
            return None

        candidates.sort(key=lambda result: (
            result.get("affinity") is None,
            result.get("affinity") if result.get("affinity") is not None else float("inf"),
            str(result.get("ligand") or "").casefold(),
            str(result.get("receptor") or "").casefold(),
            int(result.get("run", 0) or 0),
        ))
        selected = dict(candidates[0])
        selected["auto_opened"] = True
        return self.open_pose_viewer(project_dir, selected, result_options=candidates)

    def open_results_explorer(self, project_dir=None):
        project_dir = self._choose_project_dir(project_dir, "Select the VLiP project to explore")
        if not project_dir:
            return
        results = self._read_project_results(project_dir)
        if not results:
            messagebox.showwarning(
                "No docking results",
                "No readable rows were found in 'all ligands docking scores.txt'.",
            )
            return
        self._remember_recent_project(project_dir)

        win = tk.Toplevel(self.root)
        win.title(f"VLiP Results Explorer — {os.path.basename(project_dir) or project_dir}")
        win.geometry("1040x620")
        win.minsize(800, 440)
        win.transient(self.root)

        tk.Label(
            win,
            text="Results Explorer",
            font=("TkDefaultFont", 15, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 2))
        tk.Label(win, text=project_dir, anchor="w", justify="left", wraplength=990).pack(fill="x", padx=14)

        toolbar = tk.Frame(win)
        toolbar.pack(fill="x", padx=14, pady=10)
        tk.Label(toolbar, text="Filter:").pack(side="left")
        filter_var = tk.StringVar()
        filter_entry = tk.Entry(toolbar, textvariable=filter_var, width=35)
        filter_entry.pack(side="left", padx=(5, 12))
        summary_var = tk.StringVar()
        tk.Label(toolbar, textvariable=summary_var, anchor="w").pack(side="left", fill="x", expand=True)

        frame = tk.Frame(win)
        frame.pack(fill="both", expand=True, padx=14)
        columns = ("ligand", "receptor", "run", "affinity", "job", "plip")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        specs = {
            "ligand": ("Ligand", 180),
            "receptor": ("Receptor", 180),
            "run": ("Run", 60),
            "affinity": ("Affinity (kcal/mol)", 130),
            "job": ("Job Status", 100),
            "plip": ("PLIP", 170),
        }
        scrollbar = tk.Scrollbar(frame, command=tree.yview)
        tree.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)

        displayed_rows = {}        sort_state = {column: False for column in columns}

        def sort_results(column):
            reverse = not sort_state[column]
            sort_state[column] = reverse
            key_map = {
                "ligand": lambda row: row["ligand"].lower(),
                "receptor": lambda row: row["receptor"].lower(),
                "run": lambda row: row["run"],
                "affinity": lambda row: float("inf") if row["affinity"] is None else row["affinity"],
                "job": lambda row: row["job_status"],
                "plip": lambda row: row["plip_status"],
            }
            results.sort(key=key_map[column], reverse=reverse)
            refresh()

        for column, (label, width) in specs.items():
            tree.heading(column, text=label, command=lambda c=column: sort_results(c))
            tree.column(column, width=width, anchor="w")

        def refresh(*_args):
            query = filter_var.get().strip().lower()
            tree.delete(*tree.get_children())
            displayed_rows.clear()
            visible = []
            for row in results:
                haystack = " ".join(str(row.get(key, "")) for key in ("ligand", "receptor", "run", "affinity_text", "job_status", "plip_status")).lower()
                if query and query not in haystack:
                    continue
                visible.append(row)
                iid = str(len(displayed_rows))
                displayed_rows[iid] = row
                tree.insert("", "end", iid=iid, values=(
                    row["ligand"], row["receptor"], row["run"],
                    row["affinity_text"] or "—", row["job_status"], row["plip_status"],
                ))
            affinity_values = [row["affinity"] for row in visible if row["affinity"] is not None]
            best = min(affinity_values) if affinity_values else None
            best_text = f" | Best affinity: {best:g} kcal/mol" if best is not None else ""
            summary_var.set(f"Showing {len(visible)} of {len(results)} result(s){best_text}")
            if displayed_rows:
                tree.selection_set("0")

        filter_var.trace_add("write", refresh)
        refresh()

        def selected_result():
            selection = tree.selection()
            return displayed_rows.get(selection[0]) if selection else None

        def open_output():
            row = selected_result()
            if not row:
                return
            target = row.get("dock_file")
            if target and os.path.isfile(target):
                target = os.path.dirname(target)
            self._open_local_path(target or project_dir)

        def open_plip():
            row = selected_result()
            if not row:
                return
            report_path = row.get("plip_report")
            if not report_path:
                messagebox.showinfo("PLIP report", "No PLIP summary is available for this result.", parent=win)
                return
            self._open_local_path(report_path)

        def open_pose():
            row = selected_result()
            if row:
                self.open_pose_viewer(project_dir, row)

        button_row = tk.Frame(win)
        button_row.pack(fill="x", padx=14, pady=14)
        tk.Button(
            button_row, text="View 3D Pose", command=open_pose,
            bg="#087da8", fg="white", activebackground="#075f80", activeforeground="white",
        ).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Open Output Folder", command=open_output).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Open PLIP Report", command=open_plip).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Compare Project", command=lambda: self.compare_projects(project_dir)).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Export HTML", command=lambda: self.export_project_report(project_dir)).pack(side="left", padx=(0, 6))
        tk.Button(button_row, text="Close", width=12, command=win.destroy).pack(side="right")
        tree.bind("<Double-1>", lambda _event: open_pose())
        filter_entry.focus_set()

    def compare_projects(self, first_dir=None, second_dir=None):
        if first_dir and not self._project_has_data(first_dir):
            first_dir = None
        if not first_dir:
            first_dir = filedialog.askdirectory(title="Select the first VLiP project")
        if not first_dir:
            return
        if not self._project_has_data(first_dir):
            messagebox.showwarning("Not a VLiP project", "The first folder does not contain readable VLiP project data.")
            return
        if not second_dir:
            second_dir = filedialog.askdirectory(
                title="Select the second VLiP project",
                initialdir=os.path.dirname(os.path.abspath(first_dir)),
            )
        if not second_dir:
            return
        if not self._project_has_data(second_dir):
            messagebox.showwarning("Not a VLiP project", "The second folder does not contain readable VLiP project data.")
            return
        first_dir = os.path.abspath(first_dir)
        second_dir = os.path.abspath(second_dir)
        if normalized_path_key(first_dir) == normalized_path_key(second_dir):
            messagebox.showwarning("Choose two projects", "Please select two different project folders.")
            return

        settings_rows, score_rows = self._compare_project_data(first_dir, second_dir)
        self._remember_recent_project(first_dir)
        self._remember_recent_project(second_dir)

        win = tk.Toplevel(self.root)
        win.title("Compare VLiP Projects")
        win.geometry("1120x680")
        win.minsize(860, 480)
        win.transient(self.root)

        tk.Label(win, text="Project Comparison", font=("TkDefaultFont", 15, "bold"), anchor="w").pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(win, text=f"A: {first_dir}\nB: {second_dir}", anchor="w", justify="left", wraplength=1070).pack(fill="x", padx=14, pady=(0, 10))

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=14)
        settings_tab = tk.Frame(notebook)
        scores_tab = tk.Frame(notebook)
        notebook.add(settings_tab, text="Settings and Software")
        notebook.add(scores_tab, text="Docking Scores")

        settings_tree = ttk.Treeview(settings_tab, columns=("setting", "a", "b", "match"), show="headings")
        for column, label, width in (
            ("setting", "Setting", 210), ("a", "Project A", 350),
            ("b", "Project B", 350), ("match", "Comparison", 100),
        ):
            settings_tree.heading(column, text=label)
            settings_tree.column(column, width=width, anchor="w")
        dark = bool(self.night_mode_var.get())
        settings_tree.tag_configure("different", background="#5a2e32" if dark else "#ffe8e8")
        settings_tree.tag_configure("same", background="#294b35" if dark else "#eef9ee")
        settings_scroll = tk.Scrollbar(settings_tab, command=settings_tree.yview)
        settings_tree.config(yscrollcommand=settings_scroll.set)
        settings_scroll.pack(side="right", fill="y")
        settings_tree.pack(side="left", fill="both", expand=True)
        for index, row in enumerate(settings_rows):
            settings_tree.insert("", "end", iid=str(index), values=(
                row["setting"], row["a"].replace("\n", "; "), row["b"].replace("\n", "; "),
                "Same" if row["match"] else "Different",
            ), tags=("same" if row["match"] else "different",))

        score_tree = ttk.Treeview(scores_tab, columns=("ligand", "receptor", "run", "a", "b", "delta"), show="headings")
        for column, label, width in (
            ("ligand", "Ligand", 190), ("receptor", "Receptor", 190), ("run", "Run", 60),
            ("a", "Affinity A", 110), ("b", "Affinity B", 110), ("delta", "B − A", 110),
        ):
            score_tree.heading(column, text=label)
            score_tree.column(column, width=width, anchor="w")
        score_tree.tag_configure("missing", background="#5b4a24" if dark else "#fff4d6")
        score_scroll = tk.Scrollbar(scores_tab, command=score_tree.yview)
        score_tree.config(yscrollcommand=score_scroll.set)
        score_scroll.pack(side="right", fill="y")
        score_tree.pack(side="left", fill="both", expand=True)
        for index, row in enumerate(score_rows):
            affinity_a = "—" if row["a"] is None else f"{row['a']:g}"
            affinity_b = "—" if row["b"] is None else f"{row['b']:g}"
            delta = "—" if row["delta"] is None else f"{row['delta']:+.3f}"
            tags = ("missing",) if row["a"] is None or row["b"] is None else ()
            score_tree.insert("", "end", iid=str(index), values=(
                row["ligand"], row["receptor"], row["run"], affinity_a, affinity_b, delta,
            ), tags=tags)

        different_count = sum(not row["match"] for row in settings_rows)
        button_row = tk.Frame(win)
        button_row.pack(fill="x", padx=14, pady=14)
        tk.Label(button_row, text=f"{different_count} setting difference(s) | {len(score_rows)} score row(s)").pack(side="left")
        tk.Button(button_row, text="Open A", command=lambda: self._open_local_path(first_dir)).pack(side="right", padx=(6, 0))
        tk.Button(button_row, text="Open B", command=lambda: self._open_local_path(second_dir)).pack(side="right", padx=(6, 0))
        tk.Button(button_row, text="Close", width=12, command=win.destroy).pack(side="right")

        def update_comparison_tags(theme_dark):
            settings_tree.tag_configure("different", background="#5a2e32" if theme_dark else "#ffe8e8")
            settings_tree.tag_configure("same", background="#294b35" if theme_dark else "#eef9ee")
            score_tree.tag_configure("missing", background="#5b4a24" if theme_dark else "#fff4d6")

        win._vlip_theme_callback = update_comparison_tags

    def export_project_report(self, project_dir=None):
        project_dir = self._choose_project_dir(project_dir, "Select the VLiP project to export")
        if not project_dir:
            return
        output_path = filedialog.asksaveasfilename(
            title="Save VLiP HTML project report",
            initialdir=project_dir,
            initialfile=HTML_REPORT_FILENAME,
            defaultextension=".html",
            filetypes=[("HTML report", "*.html")],
        )
        if not output_path:
            return
        try:
            self._generate_html_project_report(project_dir, output_path)
            self._remember_recent_project(project_dir)
        except Exception as exc:
            messagebox.showerror("Report export failed", str(exc))
            return
        if messagebox.askyesno(
            "Report exported",
            f"The project report was saved successfully:\n\n{output_path}\n\nOpen it now?",
        ):
            self._open_local_path(output_path)

    # ----------------------
    # UI
    # ----------------------
    def apply_simple_mode(self, save=True):
        _vlip_set_simple_visibility(self._simple_items, bool(self.simple_mode_var.get()))
        if save:
            self.save_settings()

    def _create_main_scroll_area(self):
        """Keep docking actions reachable on displays shorter than the full form."""
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        # Explicit window size prevents Tk from growing off the visible display.
        window_w = min(1220, max(480, screen_w - 60))
        window_h = min(870, max(360, screen_h - 100))
        self.root.geometry(f"{window_w}x{window_h}")

        # Pack the footer FIRST. It retains space even while the rest scrolls.
        self.run_footer = tk.Frame(self.root)
        self.run_footer.pack(side="bottom", fill="x")

        self.main_scroll_host = tk.Frame(self.root)
        self.main_scroll_host.pack(side="top", fill="both", expand=True)
        self.main_scrollbar = ttk.Scrollbar(self.main_scroll_host, orient="vertical")
        self.main_scrollbar.pack(side="right", fill="y")
        self.main_canvas = tk.Canvas(self.main_scroll_host, highlightthickness=0, borderwidth=0,
                                     yscrollcommand=self.main_scrollbar.set)
        self.main_canvas.pack(side="left", fill="both", expand=True)
        self.main_scrollbar.configure(command=self.main_canvas.yview)
        self.main_content = tk.Frame(self.main_canvas)
        self._main_content_window = self.main_canvas.create_window((0, 0), window=self.main_content,
                                                                    anchor="nw")
        self.main_content.bind("<Configure>", self._on_main_content_resize)
        self.main_canvas.bind("<Configure>", self._on_main_canvas_resize)
        # Bind at the main toplevel, not bind_all: don't scroll secondary windows.
        self.root.bind("<MouseWheel>", self._scroll_main_with_wheel, add="+")
        self.root.bind("<Button-4>", self._scroll_main_with_wheel, add="+")
        self.root.bind("<Button-5>", self._scroll_main_with_wheel, add="+")
        self._wheel_remainder = 0

    def _on_main_content_resize(self, _event=None):
        self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))

    def _on_main_canvas_resize(self, event):
        # Avoid a second horizontal scrollbar; fit form to available width.
        self.main_canvas.itemconfigure(self._main_content_window, width=event.width)
        self._on_main_content_resize()

    def _scroll_main_with_wheel(self, event):
        # A Text/Treeview/combobox should keep its own wheel scrolling. Modal
        # dialogs and the separate pose viewer are intentionally unaffected.
        widget = event.widget
        if widget.winfo_toplevel() != self.root:
            return
        if isinstance(widget, (tk.Text, tk.Listbox, ttk.Treeview,
                               tk.Scrollbar, ttk.Scrollbar, ttk.Combobox)):
            return
        if getattr(event, "num", None) in (4, 5):
            steps = -1 if event.num == 4 else 1
        else:
            self._wheel_remainder += int(getattr(event, "delta", 0))
            steps = -int(self._wheel_remainder / 120)
            self._wheel_remainder -= -steps * 120
        if not steps:
            return
        self.main_canvas.yview_scroll(steps, "units")
        return "break"

    def build_ui(self):
        self.simple_mode_var = tk.BooleanVar(value=bool(self.settings.get("simple_mode", True)))
        self.night_mode_var = tk.BooleanVar(value=bool(self.settings.get("night_mode", False)))
        self.show_receptor_tools_var = tk.BooleanVar(value=bool(self.settings.get("show_receptor_tools", True)))
        self._base_ttk_theme = ttk.Style(self.root).theme_use()
        self._create_main_scroll_area()
        top = tk.Frame(self.main_content)
        top.pack(fill="x", padx=8, pady=(8, 6))
        tk.Checkbutton(top, text="Simple mode", variable=self.simple_mode_var,
                       command=self.apply_simple_mode).pack(side="right")

        for txt, cmd in [
            ("Select Output Folder", self.pick_outdir),
            ("Diagnose", self.run_diagnostics),
            ("Software Downloads", self.show_software_downloads),
            ("About the Developer", self.show_about_developer),
        ]:
            button = tk.Button(top, text=txt, command=cmd)
            button.pack(side="left", padx=(0, 5))
            if txt == "Select Output Folder":
                self.output_folder_button = button

        project_tools = tk.LabelFrame(self.main_content, text="Projects and Results", padx=6, pady=6)
        project_tools.pack(fill="x", padx=2, pady=(1, 3))
        for txt, cmd in [
            ("Recent Projects", self.show_recent_projects),
            ("Open Results", self.open_results_explorer),
            ("Compare Projects", self.compare_projects),
            ("Export HTML Report", self.export_project_report),
        ]:
            tk.Button(project_tools, text=txt, command=cmd).pack(side="left", padx=(0, 6))
        tk.Checkbutton(
            project_tools,
            text="Night Mode",
            variable=self.night_mode_var,
            command=self.apply_night_mode,
        ).pack(side="right", padx=(8, 0))

        self.receptor_tools_container = tk.Frame(self.main_content)
        self.receptor_tools_container.pack(fill="x", padx=2, pady=(1, 3))
        tk.Checkbutton(
            self.receptor_tools_container,
            text="Show Receptor Tools",
            variable=self.show_receptor_tools_var,
            command=self.toggle_receptor_tools,
            anchor="w",
        ).pack(fill="x", anchor="w")

        receptor_tools = tk.LabelFrame(self.receptor_tools_container, text="Receptor Tools", padx=6, pady=6)
        self.receptor_tools_frame = receptor_tools
        if self.show_receptor_tools_var.get():
            receptor_tools.pack(fill="x", pady=(2, 0))

        tk.Button(
            receptor_tools,
            text="1. Clean / Download PDBs",
            command=self.open_receptor_cleaner,
            width=24
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            receptor_tools,
            text="2. PDB → docking PDBQT",
            command=self.open_pdbqt_preparer,
            width=24
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            receptor_tools,
            text="Install / Repair ALL",
            command=self.install_or_repair_all_tools,
            width=18
        ).pack(side="left", padx=(0, 6))

        tk.Button(
            receptor_tools,
            text="Setup info",
            command=self.show_receptor_tool_setup,
            width=10
        ).pack(side="left", padx=(0, 10))

        tk.Label(
            receptor_tools,
            textvariable=self.receptor_tool_status_var,
            anchor="w",
            justify="left"
        ).pack(side="left", fill="x", expand=True)

        receptor_buttons = tk.Frame(self.main_content)
        receptor_buttons.pack(fill="x", padx=2, pady=(1, 0))
        for txt, cmd in [
            ("Add Files...", self.add_receptor),
            ("Remove", self.remove_receptor),
            ("Move Up", self.move_up),
            ("Move Down", self.move_down),
        ]:
            tk.Button(receptor_buttons, text=txt, command=cmd).pack(side="left")
        receptor_undo = tk.Button(receptor_buttons, text="Undo", command=self.undo_queue_change)
        receptor_undo.pack(side="left", padx=(6, 0))
        self.queue_undo_buttons.append(receptor_undo)
        # External file drops are intentionally disabled: no native callbacks.
        tk.Label(
            self.main_content,
            text="File drag/drop disabled — use Add Files. Drag rows to reorder; right-click for actions.",
            anchor="w",
        ).pack(fill="x", padx=6)

        self.table = ttk.Treeview(
            self.main_content,
            columns=("name", "mode", "res", "padding", "status"),
            show="headings",
            height=4,
        )
        for c, t in zip(
            ("name", "mode", "res", "padding", "status"),
            ("Receptor", "Mode", "Residues", "Padding", "Status"),
        ):
            self.table.heading(c, text=t)
        self.table.column("name", width=230, anchor="w")
        self.table.column("mode", width=90, anchor="center")
        self.table.column("res", width=200, anchor="w")
        self.table.column("padding", width=90, anchor="center")
        self.table.column("status", width=120, anchor="center")
        self.table.pack(fill="x", pady=3)
        self.table.bind("<Double-1>", self.edit_row)
        self.table.bind("<ButtonPress-1>", self._begin_receptor_row_drag, add="+")
        self.table.bind("<ButtonRelease-1>", self._finish_receptor_row_drag, add="+")
        self.table.bind("<Button-3>", self._show_receptor_context_menu, add="+")

        prev = tk.Frame(self.main_content)
        prev.pack(pady=2)
        tk.Button(prev, text="Interactive 3D Preview", command=self.preview).pack(side="left", padx=5)

        cfg = tk.Frame(self.main_content)
        cfg.pack(fill="x")

        self.ligand_var = tk.StringVar(value=self.settings.get("ligand", ""))
        self.vina_var = tk.StringVar(value=self.settings.get("vina", ""))
        self.outdir_var = tk.StringVar(value=self.settings.get("outdir", ""))
        self.padding_var = tk.StringVar(value=self.settings.get("padding", "10"))
        self.repeat_var = tk.StringVar(value=self.settings.get("repeats", "1"))
        self.exhaust_var = tk.StringVar(value=self.settings.get("exhaust", "8"))
        saved_vina_options = self.settings.get("vina_options") or {}
        self.vina_option_vars = {k: (tk.BooleanVar(value=saved_vina_options.get(k, False))
            if spec[1] == "bool" else tk.StringVar(value=saved_vina_options.get(k, "")))
            for k, spec in VINA_OPTION_SPECS.items()}
        self.speed_var = tk.StringVar(
            value=self._normalize_speed_mode(self.settings.get("speed_mode", "Full"))
        )
        self.speed_schedule_enabled_var = tk.BooleanVar(
            value=bool(self.settings.get("speed_schedule_enabled", False))
        )
        self.speed_schedule_start_var = tk.StringVar(
            value=str(self.settings.get("speed_schedule_start", "08:00"))
        )
        self.speed_schedule_end_var = tk.StringVar(
            value=str(self.settings.get("speed_schedule_end", "18:00"))
        )
        self.speed_status_var = tk.StringVar(value="Performance control is ready.")

        self.merge_var = tk.BooleanVar(value=self.settings.get("merge", True))
        self.pdb_var = tk.BooleanVar(value=self.settings.get("pdb", True))
        self.txt_var = tk.BooleanVar(value=self.settings.get("txt", False))
        self.plip_var = tk.BooleanVar(value=self.settings.get("run_plip", False))
        self.plip_workers_var = tk.StringVar(value=str(self.settings.get("plip_workers", 2)))

        def row(r, label, var, btn=None):
            tk.Label(cfg, text=label).grid(row=r, column=0, sticky="w")
            entry = tk.Entry(cfg, textvariable=var, width=55)
            entry.grid(row=r, column=1, sticky="we")
            if btn:
                tk.Button(cfg, text="Browse", command=btn).grid(row=r, column=2)
            return entry

        self.ligand_entry = row(0, "Ligand", self.ligand_var, self.pick_ligand)
        self.vina_entry = row(1, "Vina", self.vina_var, self.pick_vina)
        row(2, "Default Padding", self.padding_var)
        row(3, "Repeats", self.repeat_var)
        row(4, "Exhaustiveness", self.exhaust_var)
        self.ligand_entry.bind(
            "<Button-3>",
            lambda event: self._show_path_context_menu(event, "Ligand", self.ligand_var, self.pick_ligand),
            add="+",
        )
        self.vina_entry.bind(
            "<Button-3>",
            lambda event: self._show_path_context_menu(event, "Vina executable", self.vina_var, self.pick_vina),
            add="+",
        )
        self.output_folder_button.bind("<Button-3>", self._show_output_folder_context_menu, add="+")

        options_row = tk.Frame(cfg)
        options_row.grid(row=11, column=0, columnspan=3, sticky="w", pady=4)
        tk.Label(options_row, text="Max output poses (blank = Vina default):").pack(side="left")
        tk.Entry(options_row, textvariable=self.vina_option_vars["num_modes"], width=8).pack(side="left", padx=5)
        tk.Button(options_row, text="Advanced Vina Options...", command=self.show_vina_options).pack(side="left")

        performance = tk.LabelFrame(cfg, text="Docking performance", padx=6, pady=5)
        performance.grid(row=5, column=0, columnspan=3, sticky="we", pady=(5, 3))
        tk.Label(performance, text="Speed:").pack(side="left")
        self.speed_combo = ttk.Combobox(
            performance,
            textvariable=self.speed_var,
            values=SPEED_MODES,
            state="readonly",
            width=11,
        )
        self.speed_combo.pack(side="left", padx=(5, 12))
        self.speed_combo.bind("<<ComboboxSelected>>", self.on_manual_speed_change)
        tk.Checkbutton(
            performance,
            text="Daily schedule",
            variable=self.speed_schedule_enabled_var,
            command=self.on_speed_schedule_change,
        ).pack(side="left", padx=(0, 8))
        tk.Label(performance, text="Gentle from").pack(side="left")
        tk.Entry(performance, textvariable=self.speed_schedule_start_var, width=6).pack(side="left", padx=4)
        tk.Label(performance, text="until").pack(side="left")
        tk.Entry(performance, textvariable=self.speed_schedule_end_var, width=6).pack(side="left", padx=4)
        tk.Button(performance, text="Apply schedule", command=self.on_speed_schedule_change).pack(side="left", padx=(5, 8))
        tk.Label(
            cfg,
            textvariable=self.speed_status_var,
            anchor="w",
            justify="left",
        ).grid(row=6, column=0, columnspan=3, sticky="w", padx=4)

        tk.Checkbutton(cfg, text="Merge receptor+ligand (merged.pdbqt)", variable=self.merge_var).grid(row=7, column=0, columnspan=3, sticky="w")
        tk.Checkbutton(cfg, text="Convert to PDB", variable=self.pdb_var).grid(row=8, column=0, columnspan=3, sticky="w")
        tk.Checkbutton(cfg, text="Save per-run summary (.txt)", variable=self.txt_var).grid(row=9, column=0, columnspan=3, sticky="w")
        tk.Checkbutton(cfg, text="Run PLIP interaction analysis", variable=self.plip_var).grid(row=10, column=0, columnspan=3, sticky="w")

        plip_workers_row = tk.Frame(cfg)
        plip_workers_row.grid(row=12, column=0, columnspan=3, sticky="w", pady=3)
        tk.Label(plip_workers_row, text="Parallel PLIP poses:").pack(side="left")
        tk.Spinbox(plip_workers_row, from_=1, to=32, width=5,
                   textvariable=self.plip_workers_var).pack(side="left", padx=5)
        tk.Label(plip_workers_row, text="1 = sequential; start with 2, try 4 for larger runs").pack(side="left")

        notes_frame = tk.LabelFrame(self.main_content, text="Experiment Notes (optional)", padx=6, pady=4)
        notes_frame.pack(fill="x", padx=2, pady=(3, 1))
        self.experiment_notes_text = tk.Text(notes_frame, height=2, wrap="word")
        self.experiment_notes_text.pack(fill="x", expand=True)
        saved_notes = str(self.settings.get("experiment_notes", ""))
        if saved_notes:
            self.experiment_notes_text.insert("1.0", saved_notes)

        ligand_tools = tk.LabelFrame(self.main_content, text="Ligand Preparation", padx=6, pady=6)
        ligand_tools.pack(fill="x", padx=2, pady=(1, 3))
        tk.Button(
            ligand_tools,
            text="SMILES / SDF → docking PDBQT",
            command=self.open_ligand_preparer,
            width=28,
        ).pack(side="left", padx=(0, 8))
        tk.Label(
            ligand_tools,
            textvariable=self.ligand_tool_status_var,
            anchor="w",
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        ligand_frame = tk.LabelFrame(self.main_content, text="Ligand Queue")
        ligand_frame.pack(fill="both", expand=False, pady=4, padx=2)

        ligand_btns = tk.Frame(ligand_frame)
        ligand_btns.pack(fill="x", pady=2)

        tk.Button(ligand_btns, text="Add current ligand", command=self.add_current_ligand).pack(side="left")
        tk.Button(ligand_btns, text="Add Files...", command=self.add_ligands).pack(side="left")
        tk.Button(ligand_btns, text="Remove", command=self.remove_ligand).pack(side="left")
        tk.Button(ligand_btns, text="Move Up", command=self.move_ligand_up).pack(side="left")
        tk.Button(ligand_btns, text="Move Down", command=self.move_ligand_down).pack(side="left")
        tk.Button(ligand_btns, text="Clear Queue", command=self.clear_ligands).pack(side="left")
        ligand_undo = tk.Button(ligand_btns, text="Undo", command=self.undo_queue_change)
        ligand_undo.pack(side="left", padx=(6, 0))
        self.queue_undo_buttons.append(ligand_undo)
        # External file drops are intentionally disabled: no native callbacks.
        tk.Label(
            ligand_frame,
            text="File drag/drop disabled — use Add Files. Drag rows to reorder; right-click for actions.",
            anchor="w",
        ).pack(fill="x", padx=6)

        self.ligand_table = ttk.Treeview(
            ligand_frame,
            columns=("name", "path", "status"),
            show="headings",
            height=4
        )
        self.ligand_table.heading("name", text="Ligand")
        self.ligand_table.heading("path", text="Path")
        self.ligand_table.heading("status", text="Status")
        self.ligand_table.column("name", width=180, anchor="w")
        self.ligand_table.column("path", width=590, anchor="w")
        self.ligand_table.column("status", width=120, anchor="center")
        self.ligand_table.pack(fill="x", pady=2)
        self.ligand_table.bind("<ButtonPress-1>", self._begin_ligand_row_drag, add="+")
        self.ligand_table.bind("<ButtonRelease-1>", self._finish_ligand_row_drag, add="+")
        self.ligand_table.bind("<Button-3>", self._show_ligand_context_menu, add="+")

        tk.Label(
            ligand_frame,
            text="If queue is not empty, RUN DOCKING uses the queued ligands. If queue is empty, it uses the single Ligand field above."
        ).pack(anchor="w", padx=4, pady=(0, 4))

        live_frame = tk.LabelFrame(self.main_content, text="Live Vina / PLIP Commands", padx=5, pady=4)
        live_frame.pack(fill="both", expand=False, padx=2, pady=(2, 3))
        live_toolbar = tk.Frame(live_frame)
        live_toolbar.pack(fill="x")
        self.live_console_status_var = tk.StringVar(value="Idle — Vina and PLIP commands/output will appear here.")
        tk.Label(live_toolbar, textvariable=self.live_console_status_var, anchor="w").pack(side="left", fill="x", expand=True)
        self.live_console_autoscroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(live_toolbar, text="Auto-scroll", variable=self.live_console_autoscroll_var).pack(side="right", padx=(6, 0))
        tk.Button(live_toolbar, text="Copy", command=self._copy_live_console).pack(side="right", padx=(4, 0))
        tk.Button(live_toolbar, text="Clear", command=self._clear_live_console).pack(side="right", padx=(4, 0))

        live_text_frame = tk.Frame(live_frame)
        live_text_frame.pack(fill="both", expand=True, pady=(3, 0))
        live_scroll = tk.Scrollbar(live_text_frame)
        live_scroll.pack(side="right", fill="y")
        self.live_console_text = tk.Text(
            live_text_frame, height=7, wrap="none", state="disabled",
            yscrollcommand=live_scroll.set, font=("TkFixedFont", 9),
        )
        self.live_console_text.pack(side="left", fill="both", expand=True)
        live_scroll.config(command=self.live_console_text.yview)
        self.live_console_text.bind("<Button-3>", self._show_live_console_context_menu, add="+")

        self.run_button = tk.Button(
            self.run_footer,
            text="RUN DOCKING",
            bg="green",
            fg="white",
            height=2,
            command=self.run_docking
        )
        self.run_button.pack(fill="x", padx=8, pady=5)
        advanced = [notes_frame, live_frame, performance, options_row, plip_workers_row]
        advanced.extend(w for w in cfg.grid_slaves() if int(w.grid_info()['row']) in (6, 7, 8, 9))
        for container, labels in (
            (top, {'Diagnose', 'Software Downloads', 'About the Developer'}),
            (project_tools, {'Compare Projects', 'Export HTML Report'}),
            (receptor_tools, {'Install / Repair ALL', 'Setup info'}),
        ):
            advanced.extend(w for w in container.winfo_children()
                            if isinstance(w, tk.Button) and w.cget('text') in labels)
        self._simple_items = _vlip_capture_visibility(advanced)
        self.apply_simple_mode(save=False)
        self.root.bind_all("<Map>", self._theme_mapped_window, add="+")
        self.apply_night_mode(save=False)

    # ----------------------
    # Docking progress / resume helpers
    # ----------------------
    def _progress_updated_value(self, progress):
        if not progress:
            return ""
        return str(progress.get("updated_at") or progress.get("created_at") or "")

    def load_docking_progress(self):
        """
        Load the newest checkpoint for the current output folder.
        A global checkpoint from an unrelated project must never drive resume state.
        """
        candidates = []

        global_progress = read_json_file(docking_progress_path())
        if global_progress:
            candidates.append(global_progress)

        outdir = ""
        try:
            if hasattr(self, "outdir_var"):
                outdir = self.outdir_var.get().strip()
        except Exception:
            outdir = ""

        if not outdir:
            try:
                outdir = (self.settings or {}).get("outdir", "")
            except Exception:
                outdir = ""

        project_progress = read_json_file(project_state_path(outdir)) if outdir else None
        if project_progress:
            candidates.append(project_progress)

        if not candidates:
            return None

        if outdir:
            outdir_key = normalized_path_key(outdir)
            matching = []
            for candidate in candidates:
                candidate_outdir = ((candidate.get("run_config") or {}).get("outdir") or "").strip()
                if candidate_outdir and normalized_path_key(candidate_outdir) == outdir_key:
                    matching.append(candidate)
            if not matching:
                return None
            candidates = matching

        candidates.sort(key=self._progress_updated_value, reverse=True)
        return candidates[0]

    def _record_checkpoint_write_error(self, label, path, exc, data=None):
        """Make checkpoint failures visible without aborting a docking run."""
        message = f"{label} checkpoint write failed: {path} ({exc})"
        errors = getattr(self, "checkpoint_write_errors", None)
        if errors is None:
            self.checkpoint_write_errors = errors = []
        if message not in errors:
            errors.append(message)
            if len(errors) > 20:
                del errors[:-20]

        outdir = str((((data or {}).get("run_config") or {}).get("outdir") or "")).strip()
        try:
            project_log_line(outdir, "[CHECKPOINT ERROR] " + message)
        except Exception:
            pass
        try:
            print("VLiP WARNING: " + message, file=sys.stderr)
        except Exception:
            pass
        return False

    def write_docking_progress(self, data):
        path = docking_progress_path()
        try:
            atomic_write_json(path, data)
            return True
        except Exception as exc:
            return self._record_checkpoint_write_error("Global", path, exc, data)

    def write_project_progress(self, data):
        cfg = data.get("run_config") or {}
        outdir = cfg.get("outdir", "")
        if not outdir:
            return True
        path = project_state_path(outdir)
        data["project_state_file"] = path
        try:
            atomic_write_json(path, data)
            return True
        except Exception as exc:
            return self._record_checkpoint_write_error("Project", path, exc, data)

    def show_vina_options(self):
        supported, help_text = probe_vina_options(self.resolved_vina_path())
        win = tk.Toplevel(self.root)
        win.title("Advanced Vina Options")
        win.transient(self.root)
        tk.Label(win, text="Blank fields preserve the selected executable's defaults.\n"
                 "Pose count is a maximum; energy/RMSD filters may produce fewer poses.\n"
                 "A fixed nonzero seed repeats the same search on identical inputs.", justify="left").pack(padx=12, pady=8)
        form = tk.Frame(win)
        form.pack(padx=12, pady=5)
        draft = {}
        for row, (key, (label, kind, minimum)) in enumerate(VINA_OPTION_SPECS.items()):
            var = tk.BooleanVar(value=self.vina_option_vars[key].get()) if kind == "bool" else tk.StringVar(value=self.vina_option_vars[key].get())
            draft[key] = var
            tk.Label(form, text=label).grid(row=row, column=0, sticky="w")
            field = tk.Checkbutton(form, variable=var) if kind == "bool" else tk.Entry(form, textvariable=var, width=18)
            field.grid(row=row, column=1, padx=8, pady=3)
            # Keep existing overrides editable so they can be cleared after changing executable.
            tk.Label(form, text="supported" if key in supported else "not detected; clear to use defaults").grid(row=row, column=2, sticky="w")
        tk.Label(win, text="Exhaustiveness and docking boxes are set on the main screen.\n"
                 "Scoring/maps, flexible receptors and score/local/randomize-only modes are omitted\n"
                 "because this pipeline expects standard Vina docking output.", justify="left").pack(padx=12, pady=8)
        def apply():
            try:
                values = normalize_vina_options({k: v.get() for k, v in draft.items()})
                missing = set(values) - supported
                if missing:
                    raise ValueError("Selected executable did not advertise: " + ", ".join(sorted(missing)))
            except ValueError as exc:
                messagebox.showerror("Vina options", str(exc), parent=win)
                return
            for key, var in self.vina_option_vars.items():
                var.set(values.get(key, False if VINA_OPTION_SPECS[key][1] == "bool" else ""))
            self.save_settings()
            win.destroy()
        buttons = tk.Frame(win)
        buttons.pack(pady=10)
        def reset():
            for key, var in draft.items():
                var.set(False if VINA_OPTION_SPECS[key][1] == "bool" else "")
        tk.Button(buttons, text="Use executable defaults", command=reset).pack(side="left", padx=5)
        tk.Button(buttons, text="Apply", command=apply).pack(side="left", padx=5)
        tk.Button(buttons, text="Cancel", command=win.destroy).pack(side="left", padx=5)
        self.apply_night_mode(save=False)

    def build_run_config_snapshot(self, vina, outdir, ligands_to_run, receptors_copy,
                                  repeats, exhaustiveness, default_padding,
                                  ligand_output_names=None):
        return {
            "vina": vina,
            "outdir": outdir,
            "ligands_to_run": list(ligands_to_run),
            "receptors": [dict(r) for r in receptors_copy],
            "repeats": int(repeats),
            "exhaustiveness": str(exhaustiveness),
            "vina_options": normalize_vina_options({k: v.get() for k, v in self.vina_option_vars.items()}),
            "default_padding": float(default_padding),
            "save_merge": bool(self.merge_var.get()),
            "save_pdb": bool(self.pdb_var.get()),
            "save_txt": bool(self.txt_var.get()),
            "run_plip": bool(self.plip_var.get()),
            "plip_workers": normalize_plip_workers(self.plip_workers_var.get()),
            "ligand_output_names": dict(ligand_output_names or {}),
            "experiment_notes": self.get_experiment_notes(),
            "performance_mode": self.active_speed_mode,
            "performance_schedule_enabled": bool(self.speed_schedule_enabled_var.get()),
            "performance_schedule_start": self.speed_schedule_start_var.get().strip(),
            "performance_schedule_end": self.speed_schedule_end_var.get().strip(),
        }

    def _fingerprint_details(self, path, args=None):
        """Return stable input details, caching hashes for the lifetime of one run."""
        normalized = os.path.abspath(os.path.normpath(str(path)))
        cache = args.setdefault("_file_fingerprint_cache", {}) if args is not None else {}
        key = normalized_path_key(normalized)
        if key not in cache:
            try:
                size = os.path.getsize(normalized)
            except OSError:
                size = "UNAVAILABLE"
            cache[key] = {
                "path": normalized,
                "size_bytes": size,
                "sha256": sha256_file(normalized),
            }
        return dict(cache[key])

    def _configuration_fingerprint(self, identity):
        encoded = json.dumps(
            identity,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _software_version_details(self, args):
        """Detect and cache the actual Vina and PLIP versions used for this run."""
        cached = args.get("_software_version_details")
        if cached is not None:
            return dict(cached)

        def probe(cmd, env=None):
            try:
                result = run_hidden_subprocess(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=15,
                    env=env,
                )
                output = "\n".join(
                    part.strip() for part in (result.stdout, result.stderr)
                    if part and part.strip()
                )
                compact = " | ".join(line.strip() for line in output.splitlines() if line.strip())
                if result.returncode == 0 and compact:
                    return compact[:500]
                detail = compact or f"exit code {result.returncode}"
                return f"UNAVAILABLE ({detail[:500]})"
            except Exception as exc:
                return f"UNAVAILABLE ({exc})"

        runtime_py = managed_runtime_python(False)
        plip_version = "disabled for this run"
        if args.get("run_plip"):
            if runtime_py:
                version_probe = (
                    "import importlib.metadata as m; "
                    "print(m.version('plip'))"
                )
                plip_version = probe(
                    [runtime_py, "-c", version_probe],
                    env=managed_runtime_subprocess_env(),
                )
            else:
                plip_version = "UNAVAILABLE (managed VLiP runtime not found)"

        details = {
            "vina_version": probe([args["vina"], "--version"]),
            "plip_version": plip_version,
            "plip_runtime": runtime_py or "not used / not found",
        }
        args["_software_version_details"] = dict(details)
        return details

    def _receptor_prep_record(self, receptor_path):
        """Find and summarize the preparer's sidecar log when this receptor came from VLiP."""
        receptor_path = os.path.abspath(os.path.normpath(str(receptor_path)))
        stem = os.path.splitext(os.path.basename(receptor_path))[0]
        candidate = os.path.join(os.path.dirname(receptor_path), "logs", f"{stem}.log")
        if not os.path.isfile(candidate):
            return None

        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as f:
                source_lines = f.read().splitlines()
        except Exception:
            source_lines = []

        # Keep the complete settings/audit header and the two exact preparation
        # commands, without copying hundreds of lines of third-party stdout.
        excerpt = []
        for line in source_lines:
            if line == "PDB2PQR / PROPKA":
                break
            excerpt.append(line)
        for heading in ("PDB2PQR / PROPKA", "MEEKO RECEPTOR PREPARATION"):
            try:
                index = source_lines.index(heading)
            except ValueError:
                continue
            excerpt.append(heading)
            for line in source_lines[index + 1:index + 8]:
                if line.startswith("--- STDOUT") or line.startswith("--- STDERR"):
                    break
                excerpt.append(line)

        return {
            "path": candidate,
            "size_bytes": os.path.getsize(candidate),
            "sha256": sha256_file(candidate),
            "settings_excerpt": "\n".join(excerpt).strip(),
        }

    def _expected_job_settings_paths(self, args):
        """Yield only files belonging to the ligand/receptor/run matrix for this project."""
        for ligand in args.get("ligands_to_run", []):
            ligand_name = (args.get("ligand_output_names") or {}).get(
                normalized_path_key(ligand), safe_output_stem(ligand)
            )
            for receptor in args.get("receptors", []):
                receptor_name = receptor.get("output_name") or safe_output_stem(
                    receptor.get("name", receptor.get("path", "receptor"))
                )
                for run_index in range(1, int(args.get("repeats", 1)) + 1):
                    yield os.path.join(
                        args["outdir"], ligand_name, "plip", receptor_name,
                        f"run_{run_index}", JOB_SETTINGS_FILENAME
                    )

    def _write_complete_settings_record(self, args, include_job_records=False):
        """Write the master human-readable record beside the combined PLIP report."""
        os.makedirs(args["outdir"], exist_ok=True)
        _vlip_write_run_marker(args["outdir"], "Docking pipeline")
        _vlip_command_audit_set_project_root(args["outdir"])
        record_path = os.path.join(args["outdir"], COMPLETE_SETTINGS_FILENAME)

        ligand_records = []
        for index, ligand in enumerate(args.get("ligands_to_run", []), 1):
            item = self._fingerprint_details(ligand, args)
            item["queue_number"] = index
            item["output_name"] = (args.get("ligand_output_names") or {}).get(
                normalized_path_key(ligand), safe_output_stem(ligand)
            )
            ligand_records.append(item)

        receptor_records = args.get("_master_receptor_records")
        if receptor_records is None:
            receptor_records = []
            master_log = project_run_log_path(args["outdir"])
            for index, receptor in enumerate(args.get("receptors", []), 1):
                item = self._fingerprint_details(receptor.get("path", ""), args)
                item.update({
                    "queue_number": index,
                    "name": receptor.get("name", os.path.basename(receptor.get("path", ""))),
                    "output_name": receptor.get("output_name") or safe_output_stem(
                        receptor.get("name", receptor.get("path", "receptor"))
                    ),
                    "requested_mode": receptor.get("mode", "Whole"),
                    "requested_residues": receptor.get("residues", ""),
                    "requested_padding": receptor.get("padding", "") or "use project default",
                })
                item["preparation_record"] = self._receptor_prep_record(receptor.get("path", ""))
                ok, ctx = self._prepare_receptor_context(
                    receptor, args.get("default_padding", 10.0), master_log
                )
                item["box_status"] = "OK" if ok else f"UNAVAILABLE ({ctx.get('reason', 'unknown error')})"
                if ok:
                    item.update({
                        "effective_mode": ctx.get("effective_mode", receptor.get("mode", "Whole")),
                        "effective_padding": ctx["padding"],
                        "center": list(ctx["center"]),
                        "size": list(ctx["size"]),
                        "receptor_atom_count": len(ctx.get("atoms", [])),
                        "box_atom_count": int(ctx.get("box_atom_count", len(ctx.get("atoms", [])))),
                    })
                receptor_records.append(item)
            args["_master_receptor_records"] = receptor_records

        software_versions = self._software_version_details(args)
        identity = {
            "vlip_version": APP_VERSION,
            "vina": self._fingerprint_details(args["vina"], args),
            "vina_version": software_versions["vina_version"],
            "plip_version": software_versions["plip_version"],
            "plip_runtime": software_versions["plip_runtime"],
            "ligands": ligand_records,
            "receptors": receptor_records,
            "repeats": int(args["repeats"]),
            "exhaustiveness": str(args["exhaustiveness"]),
            "vina_options": dict(args.get("vina_options") or {}),
            "default_padding": float(args["default_padding"]),
            "save_merge": bool(args["save_merge"]),
            "save_pdb": bool(args["save_pdb"]),
            "save_txt": bool(args["save_txt"]),
            "run_plip": bool(args["run_plip"]),
            "plip_workers": args.get("plip_workers", 2),
            "plip_arguments": ["-t", "-x", "-v", "--maxthreads", "1"] if args["run_plip"] else [],
            "plip_ligand_filter": "UNL" if args["run_plip"] else "disabled",
        }
        fingerprint = self._configuration_fingerprint(identity)
        args["_configuration_fingerprint"] = fingerprint
        args["_complete_settings_path"] = record_path

        app_path = self._single_file_script()
        vina_details = identity["vina"]
        yes_no = lambda value: "YES" if value else "NO"
        lines = [
            "=" * 100,
            "VLiP COMPLETE SETTINGS USED",
            "=" * 100,
            f"VLiP version: {APP_VERSION}",
            f"Record written: {time.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"Project output folder: {args['outdir']}",
            f"Configuration fingerprint (SHA-256): {fingerprint}",
            "",
            "Compare the fingerprint above between projects. Matching values mean the VLiP, Vina and PLIP",
            "versions, input file contents, docking boxes and configured options recorded here are identical.",
            "Automatically generated Vina seeds are recorded in the exact per-job records below after execution.",
            "",
            "SOFTWARE AND ENVIRONMENT",
            "-" * 100,
            f"VLiP application: {app_path}",
            f"VLiP application SHA-256: {sha256_file(app_path)}",
            f"Python: {sys.version.replace(os.linesep, ' ')}",
            f"Operating system: {platform.platform()}",
            f"Vina executable: {vina_details['path']}",
            f"Actual Vina version reported: {software_versions['vina_version']}",
            f"Vina executable size: {vina_details['size_bytes']} bytes",
            f"Vina executable SHA-256: {vina_details['sha256']}",
            f"PLIP: {'enabled' if args['run_plip'] else 'disabled'}",
            f"Actual installed PLIP version: {software_versions['plip_version']}",
            "PLIP package requested by VLiP installer: 2.4.0",
            f"Managed PLIP/Python runtime: {software_versions['plip_runtime']}",
            "Ligand preparation: built-in preparation is available; docking records the exact supplied PDBQT files by SHA-256, while built-in preparations retain a separate audit manifest",
            "",
            "PROJECT SETTINGS",
            "-" * 100,
            f"Queued ligands: {len(ligand_records)}",
            f"Queued receptors: {len(receptor_records)}",
            f"Repeats per ligand/receptor pair: {args['repeats']}",
            f"Total expected docking jobs: {args['total_jobs']}",
            f"Vina exhaustiveness: {args['exhaustiveness']}",
            f"Default docking-box padding: {args['default_padding']}",
            f"Performance mode at run start: {args.get('performance_mode_at_start', 'Full')}",
            f"Daily performance schedule at run start: {args.get('performance_schedule', 'Off')}",
            f"Live performance history: {os.path.join(args['outdir'], PERFORMANCE_HISTORY_FILENAME)}",
            *vina_option_lines(args.get("vina_options")),
            f"Save merged receptor+ligand PDBQT: {yes_no(args['save_merge'])}",
            f"Convert complexes to PDB: {yes_no(args['save_pdb'])}",
            f"Save per-run raw Vina text: {yes_no(args['save_txt'])}",
            f"Run PLIP interaction analysis: {yes_no(args['run_plip'])}",
            f"Parallel PLIP poses: {args.get('plip_workers', 2)}",
            "PLIP command flags: -t (text), -x (XML), -v (verbose), --maxthreads 1" if args["run_plip"] else "PLIP command flags: none",
            "PLIP ligand section retained by VLiP: UNL" if args["run_plip"] else "PLIP ligand section retained by VLiP: not applicable",
            "",
            "EXPERIMENT NOTES",
            "-" * 100,
            str(args.get("experiment_notes") or "(none)"),
            "",
            "INPUT LIGANDS (queue order)",
            "-" * 100,
        ]

        for item in ligand_records:
            lines.extend([
                f"[{item['queue_number']}] Output name: {item['output_name']}",
                f"    Path: {item['path']}",
                f"    Size: {item['size_bytes']} bytes",
                f"    SHA-256: {item['sha256']}",
            ])

        lines.extend(["", "RECEPTORS AND ACTUAL DOCKING BOXES (queue order)", "-" * 100])
        for item in receptor_records:
            lines.extend([
                f"[{item['queue_number']}] Output name: {item['output_name']}",
                f"    Path: {item['path']}",
                f"    Size: {item['size_bytes']} bytes",
                f"    SHA-256: {item['sha256']}",
                f"    Requested mode: {item['requested_mode']}",
                f"    Requested residues: {item['requested_residues'] or '(none)'}",
                f"    Requested padding: {item['requested_padding']}",
                f"    Box calculation: {item['box_status']}",
            ])
            prep_record = item.get("preparation_record")
            if prep_record:
                lines.extend([
                    f"    Receptor-preparation log: {prep_record['path']}",
                    f"    Receptor-preparation log SHA-256: {prep_record['sha256']}",
                    "    Receptor-preparation settings/audit excerpt:",
                ])
                lines.extend(f"        {line}" for line in prep_record["settings_excerpt"].splitlines())
            else:
                lines.append("    Receptor-preparation log: not found beside this receptor")
            if item["box_status"] == "OK":
                center = item["center"]
                size = item["size"]
                lines.extend([
                    f"    Effective mode: {item['effective_mode']}",
                    f"    Effective padding: {item['effective_padding']}",
                    f"    Receptor atoms / box atoms: {item['receptor_atom_count']} / {item['box_atom_count']}",
                    f"    Actual center_x, center_y, center_z: {center[0]}, {center[1]}, {center[2]}",
                    f"    Actual size_x, size_y, size_z: {size[0]}, {size[1]}, {size[2]}",
                ])

        lines.extend([
            "",
            "EXACT PER-JOB RECORDS",
            "-" * 100,
        ])
        job_files = [path for path in self._expected_job_settings_paths(args) if os.path.isfile(path)]
        if include_job_records and job_files:
            for path in job_files:
                lines.extend(["", "#" * 100, f"SOURCE FILE: {path}", "#" * 100])
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        lines.append(f.read().strip())
                except Exception as exc:
                    lines.append(f"[ERROR READING JOB SETTINGS: {exc}]")
        elif include_job_records:
            lines.append("No per-job PLIP settings records were produced.")
        else:
            lines.append("The complete per-job records, commands and Vina-reported seeds are added here as jobs run.")

        atomic_write_text(record_path, "\n".join(lines).rstrip() + "\n")
        return record_path

    def _write_job_settings_record(self, args, ligand, ligand_name, receptor, receptor_name,
                                   run_index, job_index, center, size, effective_mode,
                                   effective_padding, vina_cmd, plip_dir):
        """Write the exact settings for one docking/PLIP job inside its PLIP folder."""
        os.makedirs(plip_dir, exist_ok=True)

        ligand_details = self._fingerprint_details(ligand, args)
        receptor_details = self._fingerprint_details(receptor["path"], args)
        vina_details = self._fingerprint_details(args["vina"], args)
        software_versions = self._software_version_details(args)
        prep_record = self._receptor_prep_record(receptor["path"])
        cx, cy, cz = center
        sx, sy, sz = size
        identity = {
            "vlip_version": APP_VERSION,
            "ligand_sha256": ligand_details["sha256"],
            "receptor_sha256": receptor_details["sha256"],
            "vina_sha256": vina_details["sha256"],
            "vina_version": software_versions["vina_version"],
            "plip_version": software_versions["plip_version"],
            "plip_runtime": software_versions["plip_runtime"],
            "ligand_output_name": ligand_name,
            "receptor_output_name": receptor_name,
            "run_index": int(run_index),
            "center": [cx, cy, cz],
            "size": [sx, sy, sz],
            "effective_mode": effective_mode,
            "effective_padding": effective_padding,
            "exhaustiveness": str(args["exhaustiveness"]),
            "vina_options": dict(args.get("vina_options") or {}),
            "vina_command": [str(part) for part in vina_cmd],
            "plip_workers": args.get("plip_workers", 2),
            "plip_arguments": ["-t", "-x", "-v", "--maxthreads", "1"] if args["run_plip"] else [],
            "plip_ligand_filter": "UNL",
        }
        job_fingerprint = self._configuration_fingerprint(identity)
        record_path = os.path.join(plip_dir, JOB_SETTINGS_FILENAME)
        lines = [
            "=" * 100,
            "VLiP EXACT SETTINGS USED FOR THIS DOCKING + PLIP JOB",
            "=" * 100,
            f"VLiP version: {APP_VERSION}",
            f"Project configuration fingerprint: {args.get('_configuration_fingerprint', 'not available')}",
            f"Job configuration fingerprint: {job_fingerprint}",
            f"Job number: {job_index + 1} of {args['total_jobs']}",
            f"Ligand: {ligand_name}",
            f"Receptor: {receptor_name}",
            f"Repeat/run: {run_index} of {args['repeats']}",
            "",
            "INPUT FILES",
            "-" * 100,
            f"Ligand path: {ligand_details['path']}",
            f"Ligand size: {ligand_details['size_bytes']} bytes",
            f"Ligand SHA-256: {ligand_details['sha256']}",
            f"Receptor path: {receptor_details['path']}",
            f"Receptor size: {receptor_details['size_bytes']} bytes",
            f"Receptor SHA-256: {receptor_details['sha256']}",
            f"Receptor-preparation log: {prep_record['path'] if prep_record else 'not found beside this receptor'}",
            f"Receptor-preparation log SHA-256: {prep_record['sha256'] if prep_record else 'not available'}",
            "",
            "ACTUAL DOCKING SETTINGS",
            "-" * 100,
            f"Requested receptor mode: {receptor.get('mode', 'Whole')}",
            f"Requested active residues: {receptor.get('residues', '') or '(none)'}",
            f"Effective receptor mode: {effective_mode}",
            f"Effective padding: {effective_padding}",
            f"center_x: {cx}",
            f"center_y: {cy}",
            f"center_z: {cz}",
            f"size_x: {sx}",
            f"size_y: {sy}",
            f"size_z: {sz}",
            f"exhaustiveness: {args['exhaustiveness']}",
            f"Performance mode when this job was launched: {self.active_speed_mode}",
            f"Performance profile at launch: {self._speed_profile_text(self.active_speed_mode)}",
            f"Live performance changes: {os.path.join(args['outdir'], PERFORMANCE_HISTORY_FILENAME)}",
            *vina_option_lines(args.get("vina_options")),
            f"Vina executable: {vina_details['path']}",
            f"Actual Vina version reported: {software_versions['vina_version']}",
            f"Vina executable SHA-256: {vina_details['sha256']}",
            f"Exact Vina command: {command_as_text(vina_cmd)}",
            "",
            "OUTPUT / PLIP SETTINGS",
            "-" * 100,
            f"Save merged receptor+ligand PDBQT: {'YES' if args['save_merge'] else 'NO'}",
            f"Convert complexes to PDB: {'YES' if args['save_pdb'] else 'NO'}",
            f"Save per-run raw Vina text: {'YES' if args['save_txt'] else 'NO'}",
            f"Run PLIP: {'YES' if args['run_plip'] else 'NO'}",
            f"Actual installed PLIP version: {software_versions['plip_version']}",
            "PLIP package requested by VLiP installer: 2.4.0",
            f"Managed PLIP/Python runtime: {software_versions['plip_runtime']}",
            f"Parallel PLIP poses: {args.get('plip_workers', 2)}",
            "PLIP fixed flags: -t (text), -x (XML), -v (verbose), --maxthreads 1" if args["run_plip"] else "PLIP flags: disabled",
            "PLIP ligand section retained by VLiP: UNL",
            "PLIP input: each receptor+pose complex converted by VLiP to PDB",
            "",
            "ACTUAL VALUES REPORTED DURING EXECUTION",
            "-" * 100,
        ]
        atomic_write_text(record_path, "\n".join(lines) + "\n")
        return record_path

    def current_config_matches_progress(self, progress, run_config):
        old = progress.get("run_config") or {}
        keys = [
            "vina", "outdir", "ligands_to_run", "receptors", "repeats",
            "exhaustiveness", "default_padding", "save_merge", "save_pdb",
            "save_txt", "run_plip", "ligand_output_names"
        ]
        return (all(old.get(k) == run_config.get(k) for k in keys)
                and normalize_vina_options(old.get("vina_options")) == normalize_vina_options(run_config.get("vina_options")))

    def restore_run_config_from_progress(self, progress):
        cfg = progress.get("run_config") or {}
        if not cfg:
            return False

        try:
            self.vina_var.set(cfg.get("vina", ""))
            self.outdir_var.set(cfg.get("outdir", ""))
            self.padding_var.set(str(cfg.get("default_padding", "10")))
            self.repeat_var.set(str(cfg.get("repeats", "1")))
            self.exhaust_var.set(str(cfg.get("exhaustiveness", "8")))
            restored_options = normalize_vina_options(cfg.get("vina_options"))
            for key, var in self.vina_option_vars.items():
                var.set(restored_options.get(key, False if VINA_OPTION_SPECS[key][1] == "bool" else ""))
            self.merge_var.set(bool(cfg.get("save_merge", True)))
            self.pdb_var.set(bool(cfg.get("save_pdb", True)))
            self.txt_var.set(bool(cfg.get("save_txt", False)))
            self.plip_var.set(bool(cfg.get("run_plip", False)))
            self.plip_workers_var.set(str(cfg.get("plip_workers", 2)))
            self.speed_var.set(self._normalize_speed_mode(cfg.get("performance_mode", "Full")))
            self.speed_schedule_enabled_var.set(bool(cfg.get("performance_schedule_enabled", False)))
            self.speed_schedule_start_var.set(str(cfg.get("performance_schedule_start", "08:00")))
            self.speed_schedule_end_var.set(str(cfg.get("performance_schedule_end", "18:00")))
            self._apply_configured_speed(source="restored run", record=False)
            self.experiment_notes_text.delete("1.0", "end")
            self.experiment_notes_text.insert("1.0", str(cfg.get("experiment_notes") or ""))

            ligands = cfg.get("ligands_to_run") or []
            self.ligands = list(ligands)
            self.ligand_var.set(ligands[0] if len(ligands) == 1 else "")

            self.receptors = [dict(r) for r in cfg.get("receptors", [])]
            self.refresh_table()
            self.refresh_ligand_table()
            self.save_settings()
            return True
        except Exception:
            return False

    def offer_return_to_last_docking_position(self):
        if self.run_in_progress:
            return False

        progress = self.load_docking_progress()
        self.last_progress_data = progress
        if not progress:
            return False
        if progress.get("completed", False):
            return False

        last_position = progress.get("last_position") or {}
        run_config = progress.get("run_config") or {}
        if not last_position and not run_config:
            return False

        next_job = int(progress.get("next_job_index", 0) or 0)
        total_jobs = int(progress.get("total_jobs", 0) or 0)
        status = f"saved at job {next_job} / {total_jobs}"

        answer = messagebox.askyesno(
            "Return to docking position?",
            "A saved docking setup was found.\n\n"
            f"Status: {status}\n"
            f"Ligand: {last_position.get('ligand_name', '?')}\n"
            f"Receptor: {last_position.get('receptor_name', '?')}\n\n"
            "Do you want to return to that saved docking setup/position?"
        )

        if answer:
            if self.restore_run_config_from_progress(progress):
                messagebox.showinfo("Docking position restored", "Saved docking setup restored.")
            else:
                messagebox.showwarning("Could not restore", "The saved docking setup could not be restored cleanly.")
        return True

    def finish_startup_navigation(self):
        """Offer an interrupted setup first; otherwise show the recent-project list."""
        progress = self.load_docking_progress() or {}
        if progress.get("completed", False):
            completed_outdir = str((progress.get("run_config") or {}).get("outdir") or "")
            if self._project_has_data(completed_outdir):
                self._remember_recent_project(completed_outdir)
        if not self.offer_return_to_last_docking_position():
            self.show_recent_projects(startup=True)

    def make_initial_progress_data(self, run_config, total_jobs, resume_from_job=0):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        outdir = (run_config or {}).get("outdir", "")
        return {
            "file_type": "VLIP_PROJECT_STATE",
            "version": 3,
            "created_at": now,
            "updated_at": now,
            "completed": False,
            "total_jobs": int(total_jobs),
            "next_job_index": int(resume_from_job),
            "run_config": run_config,
            "last_position": {},
            "job_statuses": {},
            "failed_jobs": [],
            "status": "running" if resume_from_job else "started",
            "global_progress_file": docking_progress_path(),
            "project_state_file": project_state_path(outdir),
        }

    def save_worker_progress(self, args, next_job_index, status="running", last_position=None):
        fresh_start = status == "started" and int(next_job_index) == 0
        data = None if fresh_start else self.load_docking_progress()
        if data is None:
            data = self.make_initial_progress_data(
                args.get("run_config", {}),
                args.get("total_jobs", 0),
                next_job_index
            )
        data["file_type"] = "VLIP_PROJECT_STATE"
        data["version"] = max(int(data.get("version", 1) or 1), 3)
        data["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data["completed"] = status in {"completed", "completed_with_issues"}
        data["status"] = status
        data["total_jobs"] = int(args.get("total_jobs", data.get("total_jobs", 0)) or 0)
        data["next_job_index"] = int(next_job_index)
        data["run_config"] = args.get("run_config", data.get("run_config", {}))
        data.setdefault("job_statuses", {})
        data.setdefault("failed_jobs", [])
        outdir = (data.get("run_config") or {}).get("outdir", "")
        data["global_progress_file"] = docking_progress_path()
        data["project_state_file"] = project_state_path(outdir)
        if last_position is not None:
            data["last_position"] = last_position
        self.write_docking_progress(data)
        self.write_project_progress(data)

        if status != "running" or last_position is not None:
            project_log_line(
                outdir,
                f"checkpoint status={status} next_job={int(next_job_index)} / {int(data.get('total_jobs', 0) or 0)}"
            )

    def update_job_status(self, args, job_index, status, detail=None):
        """Record per-job status in both progress files without changing the resume pointer."""
        data = self.load_docking_progress() or self.make_initial_progress_data(
            args.get("run_config", {}),
            args.get("total_jobs", 0),
            int(args.get("resume_from_job", 0) or 0)
        )

        detail = dict(detail or {})
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        job_key = str(int(job_index))

        data["file_type"] = "VLIP_PROJECT_STATE"
        data["version"] = max(int(data.get("version", 1) or 1), 3)
        data["updated_at"] = now
        data["run_config"] = args.get("run_config", data.get("run_config", {}))
        data["total_jobs"] = int(args.get("total_jobs", data.get("total_jobs", 0)) or 0)
        data.setdefault("job_statuses", {})
        data.setdefault("failed_jobs", [])
        data["job_statuses"][job_key] = {
            "status": status,
            "updated_at": now,
            **detail,
        }

        data["failed_jobs"] = [
            item for item in data.get("failed_jobs", [])
            if not isinstance(item, dict) or str(item.get("job_index")) != job_key
        ]
        if status == "FAILED":
            data["failed_jobs"].append({"job_index": int(job_index), "updated_at": now, **detail})

        timing_samples = []
        terminal_count = 0
        for job in data["job_statuses"].values():
            if not isinstance(job, dict):
                continue
            job_status = str(job.get("status", "")).upper()
            if job_status in {"COMPLETE", "PARTIAL", "FAILED", "SKIPPED"}:
                terminal_count += 1
            if job_status not in {"COMPLETE", "PARTIAL"}:
                continue
            try:
                duration = float(job.get("duration_seconds"))
            except (TypeError, ValueError):
                continue
            if duration > 0:
                timing_samples.append(duration)
        if timing_samples:
            average = sum(timing_samples) / len(timing_samples)
            remaining = max(0, int(data["total_jobs"]) - terminal_count)
            data["average_job_seconds"] = average
            data["timing_sample_count"] = len(timing_samples)
            data["estimated_remaining_seconds"] = average * remaining

        outdir = (data.get("run_config") or {}).get("outdir", "")
        data["global_progress_file"] = docking_progress_path()
        data["project_state_file"] = project_state_path(outdir)

        self.write_docking_progress(data)
        self.write_project_progress(data)
        project_log_line(outdir, f"job {int(job_index) + 1}/{data['total_jobs']} -> {status}: {detail.get('ligand_name', '')} {detail.get('receptor_name', '')} run {detail.get('run_index', '')}")

    def _current_eta_suffix(self):
        progress = self.load_docking_progress() or {}
        seconds = progress.get("estimated_remaining_seconds")
        if seconds is None:
            return ""
        return f" | about {self._format_duration(seconds)} remaining"

    # ----------------------
    # Startup checks / diagnostics
    # ----------------------
    def startup_self_check(self):
        """Check dependencies without freezing the opening window, then offer repair."""
        if getattr(self, "_startup_check_started", False):
            return
        self._startup_check_started = True
        vina_field_value = self.vina_var.get().strip()
        self.receptor_tool_status_var.set("Checking Vina, PLIP and the managed scientific runtime...")

        def worker():
            try:
                report, all_ready = format_self_check_report(vina_field_value)
                failed = not all_ready
            except Exception as exc:
                report = f"VLiP startup dependency check could not complete:\n\n{exc}"
                failed = True

            def finish():
                if failed:
                    self.receptor_tool_status_var.set(
                        "Setup incomplete — use Install / Repair ALL to enable every feature."
                    )
                    install_now = messagebox.askyesno(
                        "VLiP setup needed",
                        report
                        + "\n\nSome features will not work until these components are installed or repaired."
                        + "\n\nRun Install / Repair ALL now?",
                        parent=self.root,
                    )
                    if install_now:
                        self._offer_restore_after_installer = True
                        self.install_or_repair_all_tools()
                        return
                else:
                    self.receptor_tool_status_var.set(
                        "Startup check passed — Vina, PLIP and the managed runtime are ready."
                    )

                self.root.after(300, self.finish_startup_navigation)

            try:
                self.root.after(0, finish)
            except Exception:
                pass

        self.startup_check_thread = threading.Thread(
            target=worker,
            daemon=True,
            name="VLiPStartupDependencyCheck",
        )
        self.startup_check_thread.start()

    def run_diagnostics(self):
        report, _ = format_self_check_report(self.vina_var.get().strip())

        diag_file = os.path.join(user_working_dir(), "vlip_diagnostics.txt")
        try:
            with open(diag_file, "w", encoding="utf-8") as f:
                f.write(report + "\n")
            messagebox.showinfo(
                "Diagnostics",
                report + f"\n\nSaved to:\n{diag_file}"
            )
        except Exception:
            messagebox.showinfo("Diagnostics", report)

    def show_about_developer(self):
        """Show VLiP's origin story and the developer's aims in a readable window."""
        existing = getattr(self, "about_developer_win", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.lift()
                existing.focus_force()
                return
        except Exception:
            pass

        win = tk.Toplevel(self.root)
        self.about_developer_win = win
        win.title(f"About the Developer — VLiP v{APP_VERSION}")
        win.geometry("820x680")
        win.minsize(680, 520)
        win.transient(self.root)

        tk.Label(
            win,
            text="About the Developer",
            font=("TkDefaultFont", 17, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(18, 2))
        tk.Label(
            win,
            text=f"VLiP was created and developed by {DEVELOPER_NAME}",
            font=("TkDefaultFont", 11, "bold"),
            anchor="w",
        ).pack(fill="x", padx=18, pady=(0, 12))

        text_frame = tk.Frame(win)
        text_frame.pack(fill="both", expand=True, padx=18)
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        about_text = tk.Text(
            text_frame,
            wrap="word",
            padx=14,
            pady=14,
            spacing1=2,
            spacing2=2,
            spacing3=8,
            yscrollcommand=scrollbar.set,
        )
        about_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=about_text.yview)

        story = f"""VLiP — FROM A BATCH TOOL TO A COMPLETE WORKFLOW

Developer: {DEVELOPER_NAME}
Current version: {APP_VERSION}

WHY I FIRST MADE VLiP

VLiP began with a straightforward practical purpose: I wanted an easier way to carry out docking work in batches. The earliest version was centred on AutoDock Vina alone. Running Vina jobs individually, repeating the same setup, keeping track of different ligands and receptors, and manually organising the resulting files quickly became repetitive. The original program was therefore made for my own use as a way to reduce that repeated work and let the computer handle a queue of docking jobs in a consistent order.

At the beginning, the aim was not to build a large application. It was simply to make batch work quicker, more organised and less prone to avoidable manual mistakes. Once I started using it, however, it became clear that launching several Vina jobs was only one part of the real workflow.

HOW THE PROGRAM GREW

Docking work involves much more than pressing a Run button. Receptors need to be obtained, cleaned, prepared and checked. Ligands and receptors need to be organised into sensible queues. Docking boxes need to be calculated and previewed. A long run needs progress information, safe stopping and a way to resume after an interruption. The resulting poses and scores need to be converted, analysed, summarised and stored in a form that still makes sense later.

One of the most difficult parts of that growth was creating a dependable route from an ordinary receptor PDB file to a docking-ready PDBQT file. It was not simply a matter of changing a file extension. The structure had to pass through a chain of cleaning, preparation, validation and conversion steps, while several scientific tools and Python packages had to agree with one another. Different PDB structures could contain awkward records, multiple models, malformed sections or chemistry that exposed another edge case. Getting the PDB → cleaned PDB → docking PDBQT chain to work reliably caused some of the biggest development problems in the project. Those problems are a major reason VLiP now includes dedicated Receptor Tools, detailed checks, preparation records and a managed scientific runtime.

PLIP was not part of the original Vina-only program. It was added later so that VLiP could go beyond docking scores and help organise protein–ligand interaction analysis for the generated poses. Adding PLIP created another substantial stage: Vina's output had to be split and combined with the correct receptor, converted into a PLIP-ready PDB complex, analysed, filtered and then gathered into readable summaries. This was an important step in VLiP's transition from a batch launcher into a broader docking and analysis workflow.

As those needs became clearer, VLiP gradually grew beyond its original batch-processing role. Receptor cleaning and PDBQT preparation were brought into the same workflow. Multiple ligands and receptors could be queued together. Whole-receptor and active-residue docking modes were added, along with docking-box previews. PLIP interaction analysis, PDB conversion, combined reports, per-receptor reports and organised output folders made the results easier to inspect.

The program also gained practical protections: input validation, progress checkpoints, pause and cancellation controls, stop-after-receptor behaviour, restoration of saved work, diagnostics and automatic dependency checks. Exact settings records were added so that Vina and PLIP versions, file fingerprints, docking boxes, commands, seeds and important options could be compared between projects instead of relying on memory.

WHY I DECIDED TO MAKE IT A MORE COMPLETE PACKAGE

As VLiP became more capable, I decided it should feel like one coherent package rather than a collection of disconnected scripts. A useful scientific tool should not require the user to remember a long series of hidden setup steps every time it is opened. The program should explain what is selected, warn when something is wrong, preserve the details of what it did and organise the output in a predictable way.

That is why newer versions focus not only on adding scientific functions, but also on making the whole process easier to follow. The startup check confirms that the required software is ready. The pre-run review shows the planned job count, programs, inputs and settings before any docking begins. Reproducibility records provide an audit trail after the run. These features are intended to make VLiP more dependable for repeated experiments and more approachable for someone who did not write the program.

Version 1.37 added a new visual inspection stage through VLiP's built-in 3D Pose Viewer. Docked Vina poses can now be rotated, zoomed, compared pose by pose and viewed with the matching receptor without leaving the results workflow. Binding-pocket and whole-receptor surface modes, atom inspection, residue highlighting, distance measurements, geometry contact guides and SVG snapshots make it easier to understand an output before moving into specialist molecular graphics software. The viewer deliberately labels its fast surfaces and inferred contacts as visual aids; PLIP and appropriate scientific analysis remain the authority for interaction interpretation.

Usability continues to matter alongside scientific capability. Text controls throughout the application now have right-click Cut, Copy, Paste, Delete Selection and Select All actions, making paths, notes, settings and report text easier to work with using familiar desktop controls.

THE DEVELOPMENT PHILOSOPHY

VLiP is built around a few simple ideas:

• Repetitive work should be automated where it can be automated safely.

• Important scientific settings should be visible before a run and recorded afterward.

• A failed or interrupted job should leave useful information rather than a confusing folder.

• Powerful tools are more useful when their workflow is clear and their setup can check itself.

• The user should remain in control of the inputs, assumptions and interpretation of the results.

VLiP does not replace scientific judgement, careful validation or appropriate experimental follow-up. Its purpose is to make the computational workflow easier to prepare, repeat, inspect and compare.

A NOTE FROM THE DEVELOPER

What started as a program to help me perform batch work has steadily developed into a broader ligand–protein docking and analysis package. Each addition has come from seeing another part of the workflow that could be made clearer, safer or less repetitive. VLiP is still evolving, but its direction remains the same: bring the useful stages of the workflow together while keeping the process understandable and the record of each run complete.

— {DEVELOPER_NAME}
"""
        about_text.insert("1.0", story)
        about_text.config(state="disabled")

        button_row = tk.Frame(win)
        button_row.pack(fill="x", padx=18, pady=14)

        def close():
            self.about_developer_win = None
            win.destroy()

        tk.Button(button_row, text="Close", width=14, command=close).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", close)
        win.bind("<Escape>", lambda _event: close())

        win.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - win.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - win.winfo_height()) // 2)
            win.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ----------------------
    # Pickers
    # ----------------------
    def pick_outdir(self):
        d = filedialog.askdirectory()
        if d:
            self.outdir_var.set(d)

    def pick_ligand(self):
        f = filedialog.askopenfilename(filetypes=[("PDBQT", "*.pdbqt")])
        if f:
            self.ligand_var.set(f)

    def pick_vina(self):
        f = filedialog.askopenfilename()
        if f:
            self.vina_var.set(f)

    # ----------------------
    # Queue reordering and context-menu helpers
    # ----------------------
    def _popup_menu(self):
        dark = bool(self.night_mode_var.get()) if hasattr(self, "night_mode_var") else False
        bg = "#292d35" if dark else "#ffffff"
        fg = "#f1f3f5" if dark else "#17191c"
        active = "#3c4654" if dark else "#dceeff"
        return tk.Menu(
            self.root, tearoff=False, bg=bg, fg=fg,
            activebackground=active, activeforeground=fg,
        )

    @staticmethod
    def _copy_text_to_clipboard(widget, text):
        try:
            widget.clipboard_clear()
            widget.clipboard_append(str(text or ""))
            widget.update_idletasks()
        except Exception:
            pass

    def _show_path_context_menu(self, event, label, variable, browse_command):
        value = variable.get().strip()
        menu = self._popup_menu()
        menu.add_command(label="Browse...", command=browse_command)
        if value:
            menu.add_command(
                label="Open",
                command=lambda p=value: self._open_local_path(p),
                state="normal" if os.path.exists(value) else "disabled",
            )
            parent = value if os.path.isdir(value) else os.path.dirname(value)
            menu.add_command(
                label="Open containing folder",
                command=lambda p=parent: self._open_local_path(p),
                state="normal" if parent and os.path.isdir(parent) else "disabled",
            )
            menu.add_separator()
            menu.add_command(label="Copy path", command=lambda p=value: self._copy_text_to_clipboard(self.root, p))
            menu.add_command(label="Clear", command=lambda: (variable.set(""), self.save_settings()))
        else:
            menu.add_separator()
            menu.add_command(label="No path selected", state="disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _show_output_folder_context_menu(self, event):
        value = self.outdir_var.get().strip() if hasattr(self, "outdir_var") else ""
        menu = self._popup_menu()
        menu.add_command(label="Choose output folder...", command=self.pick_outdir)
        menu.add_command(
            label="Open current output folder",
            command=lambda p=value: self._open_local_path(p),
            state="normal" if value and os.path.isdir(value) else "disabled",
        )
        menu.add_command(
            label="Copy output path",
            command=lambda p=value: self._copy_text_to_clipboard(self.root, p),
            state="normal" if value else "disabled",
        )
        menu.add_command(
            label="Clear output folder",
            command=lambda: (self.outdir_var.set(""), self.save_settings()),
            state="normal" if value else "disabled",
        )
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    @staticmethod
    def _tree_right_click_select(tree, event):
        iid = tree.identify_row(event.y)
        if iid:
            if iid not in tree.selection():
                tree.selection_set(iid)
            tree.focus(iid)
        return iid

    def _selected_receptor_paths(self):
        return list(self.table.selection()) if hasattr(self, "table") else []

    def _selected_ligand_paths(self):
        return list(self.ligand_table.selection()) if hasattr(self, "ligand_table") else []

    def _open_first_selected_path(self, paths, containing=False):
        if not paths:
            return
        path = paths[0]
        target = os.path.dirname(path) if containing else path
        if target:
            self._open_local_path(target)

    def _show_receptor_context_menu(self, event):
        self._tree_right_click_select(self.table, event)
        paths = self._selected_receptor_paths()
        menu = self._popup_menu()
        one = len(paths) == 1
        any_selected = bool(paths)
        menu.add_command(label="Edit receptor settings", command=lambda: self.edit_row(event), state="normal" if one and not self.run_in_progress else "disabled")
        menu.add_command(label="Open receptor file", command=lambda p=paths: self._open_first_selected_path(p), state="normal" if one and os.path.isfile(paths[0]) else "disabled")
        menu.add_command(label="Open containing folder", command=lambda p=paths: self._open_first_selected_path(p, True), state="normal" if one else "disabled")
        menu.add_command(label="Copy path", command=lambda p=paths: self._copy_text_to_clipboard(self.root, p[0] if p else ""), state="normal" if one else "disabled")
        menu.add_separator()
        menu.add_command(label="Move up", command=self.move_up, state="normal" if any_selected and not self.run_in_progress else "disabled")
        menu.add_command(label="Move down", command=self.move_down, state="normal" if any_selected and not self.run_in_progress else "disabled")
        menu.add_command(label="Remove", command=self.remove_receptor, state="normal" if any_selected and not self.run_in_progress else "disabled")
        menu.add_separator()
        menu.add_command(label="Add receptor(s)...", command=self.add_receptor, state="disabled" if self.run_in_progress else "normal")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _show_ligand_context_menu(self, event):
        self._tree_right_click_select(self.ligand_table, event)
        paths = self._selected_ligand_paths()
        menu = self._popup_menu()
        one = len(paths) == 1
        any_selected = bool(paths)
        menu.add_command(
            label="Set as current ligand",
            command=lambda p=paths: (self.ligand_var.set(p[0]), self.save_settings()) if p else None,
            state="normal" if one and not self.run_in_progress else "disabled",
        )
        menu.add_command(label="Open ligand file", command=lambda p=paths: self._open_first_selected_path(p), state="normal" if one and os.path.isfile(paths[0]) else "disabled")
        menu.add_command(label="Open containing folder", command=lambda p=paths: self._open_first_selected_path(p, True), state="normal" if one else "disabled")
        menu.add_command(label="Copy path", command=lambda p=paths: self._copy_text_to_clipboard(self.root, p[0] if p else ""), state="normal" if one else "disabled")
        menu.add_separator()
        menu.add_command(label="Move up", command=self.move_ligand_up, state="normal" if any_selected and not self.run_in_progress else "disabled")
        menu.add_command(label="Move down", command=self.move_ligand_down, state="normal" if any_selected and not self.run_in_progress else "disabled")
        menu.add_command(label="Remove", command=self.remove_ligand, state="normal" if any_selected and not self.run_in_progress else "disabled")        menu.add_separator()
        menu.add_command(label="Add ligand(s)...", command=self.add_ligands, state="disabled" if self.run_in_progress else "normal")
        menu.add_command(label="Clear ligand queue", command=self.clear_ligands, state="normal" if self.ligands and not self.run_in_progress else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    # ----------------------
    # Live external-tool console
    # ----------------------
    def _live_console_emit(self, stage, text, stream=""):
        stage = str(stage or "TOOL").upper()
        text = str(text or "")
        if not text:
            return
        self.live_console_queue.put((stage, str(stream or "").upper(), text))

    def _drain_live_console_queue(self):
        widget = getattr(self, "live_console_text", None)
        inserted = False
        last_stage = None
        if widget is not None:
            try:
                widget.configure(state="normal")
                for _ in range(400):
                    try:
                        stage, stream, text = self.live_console_queue.get_nowait()
                    except queue.Empty:
                        break
                    last_stage = stage
                    prefix = f"[{stage}{' ' + stream if stream else ''}] "
                    chunks = text.replace("\r\n", "\n").replace("\r", "\n").splitlines(True)
                    if not chunks:
                        chunks = [text]
                    for chunk in chunks:
                        if chunk.endswith("\n"):
                            widget.insert("end", prefix + chunk)
                        else:
                            widget.insert("end", prefix + chunk + "\n")
                    inserted = True
                if inserted:
                    try:
                        line_count = int(widget.index("end-1c").split(".")[0])
                        if line_count > self._live_console_line_limit:
                            delete_to = line_count - self._live_console_line_limit
                            widget.delete("1.0", f"{delete_to}.0")
                    except Exception:
                        pass
                    if bool(self.live_console_autoscroll_var.get()):
                        widget.see("end")
                widget.configure(state="disabled")
            except tk.TclError:
                return
        if last_stage and hasattr(self, "live_console_status_var"):
            self.live_console_status_var.set(f"{last_stage} output is live.")
        try:
            self._live_console_after_id = self.root.after(100, self._drain_live_console_queue)
        except tk.TclError:
            self._live_console_after_id = None

    def _clear_live_console(self):
        widget = getattr(self, "live_console_text", None)
        if widget is None:
            return
        try:
            widget.configure(state="normal")
            widget.delete("1.0", "end")
            widget.configure(state="disabled")
            self.live_console_status_var.set("Console cleared — waiting for Vina / PLIP.")
        except tk.TclError:
            pass

    def _copy_live_console(self):
        widget = getattr(self, "live_console_text", None)
        if widget is None:
            return
        try:
            if widget.tag_ranges("sel"):
                payload = widget.get("sel.first", "sel.last")
            else:
                payload = widget.get("1.0", "end-1c")
            self._copy_text_to_clipboard(self.root, payload)
        except tk.TclError:
            pass

    def _show_live_console_context_menu(self, event):
        widget = self.live_console_text
        menu = self._popup_menu()
        try:
            has_selection = bool(widget.tag_ranges("sel"))
        except tk.TclError:
            has_selection = False
        menu.add_command(label="Copy selection", command=self._copy_live_console, state="normal" if has_selection else "disabled")
        menu.add_command(label="Copy all", command=lambda: self._copy_text_to_clipboard(self.root, widget.get("1.0", "end-1c")))
        menu.add_command(label="Select all", command=lambda: (widget.tag_add("sel", "1.0", "end-1c"), widget.see("end")))
        menu.add_separator()
        menu.add_command(label="Clear", command=self._clear_live_console)
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
        return "break"

    # ----------------------
    # Queue quality-of-life helpers
    # ----------------------
    def _queue_snapshot(self):
        return {
            "receptors": [dict(item) for item in self.receptors],
            "ligands": list(self.ligands),
        }

    def _record_queue_undo(self, before, description):
        if before == self._queue_snapshot():
            return False
        self._queue_undo_stack.append((before, str(description or "queue change")))
        del self._queue_undo_stack[:-30]
        self._update_undo_buttons()
        return True

    def _update_undo_buttons(self):
        description = self._queue_undo_stack[-1][1] if self._queue_undo_stack else ""
        for button in getattr(self, "queue_undo_buttons", []):
            try:
                button.configure(
                    text=f"Undo: {description[:16]}" if description else "Undo",
                    state="normal" if description and not self.run_in_progress else "disabled",
                )
            except Exception:
                pass

    def undo_queue_change(self):
        if self.run_in_progress or not self._queue_undo_stack:
            return
        snapshot, description = self._queue_undo_stack.pop()
        self.receptors = [dict(item) for item in snapshot.get("receptors", [])]
        self.ligands = list(snapshot.get("ligands", []))
        self.refresh_table()
        self.refresh_ligand_table()
        self.save_settings()
        self._update_undo_buttons()
        self.receptor_tool_status_var.set(f"Undid queue change: {description}.")
        self.ligand_tool_status_var.set(f"Undid queue change: {description}.")

    def _begin_receptor_row_drag(self, event):
        self._receptor_drag_iid = self.table.identify_row(event.y)

    def _finish_receptor_row_drag(self, event):
        source = self._receptor_drag_iid
        self._receptor_drag_iid = None
        target = self.table.identify_row(event.y)
        if not source or not target or source == target:
            return
        source_index = next((i for i, item in enumerate(self.receptors) if item["path"] == source), None)
        target_index = next((i for i, item in enumerate(self.receptors) if item["path"] == target), None)
        if source_index is None or target_index is None:
            return
        before = self._queue_snapshot()
        moved = self.receptors.pop(source_index)
        self.receptors.insert(target_index, moved)
        self._record_queue_undo(before, "reorder receptors")
        self.refresh_table()
        self.table.selection_set(source)
        self.table.focus(source)
        self.save_settings()

    def _begin_ligand_row_drag(self, event):
        self._ligand_drag_iid = self.ligand_table.identify_row(event.y)

    def _finish_ligand_row_drag(self, event):
        source = self._ligand_drag_iid
        self._ligand_drag_iid = None
        target = self.ligand_table.identify_row(event.y)
        if not source or not target or source == target:
            return
        try:
            source_index = self.ligands.index(source)
            target_index = self.ligands.index(target)
        except ValueError:
            return
        before = self._queue_snapshot()
        moved = self.ligands.pop(source_index)
        self.ligands.insert(target_index, moved)
        self._record_queue_undo(before, "reorder ligands")
        self.refresh_ligand_table()
        self.ligand_table.selection_set(source)
        self.ligand_table.focus(source)
        self.save_settings()

    def _ligand_queue_status(self, path):
        if not path or not os.path.isfile(path):
            return "MISSING", "missing"
        if not str(path).lower().endswith(".pdbqt"):
            return "WRONG TYPE", "invalid"
        ok, _detail = validate_pdbqt(path, kind="ligand")
        return ("READY", "ready") if ok else ("INVALID", "invalid")

    def _receptor_queue_status(self, receptor):
        path = receptor.get("path", "")
        if not path or not os.path.isfile(path):
            return "MISSING", "missing"
        ok, _detail = validate_pdbqt(path, kind="receptor")
        if not ok:
            return "INVALID", "invalid"
        try:
            padding = float(str(receptor.get("padding", "")).strip() or self.padding_var.get())
            if padding <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return "BAD PADDING", "invalid"
        mode = receptor.get("mode", "Whole")
        if mode not in {"Whole", "Active"}:
            return "BAD MODE", "invalid"
        if mode == "Active":
            try:
                select_active_residue_atoms(parse_atoms(path), receptor.get("residues", ""))
            except (OSError, ValueError):
                return "CHECK RESIDUES", "warning"
        return "READY", "ready"

    def _apply_queue_status_badges(self, dark=None):
        if dark is None:
            dark = bool(self.night_mode_var.get())
        colors = {
            "ready": (("#153d29", "#b9f6ca") if dark else ("#dff4e7", "#155b32")),
            "warning": (("#4b3712", "#ffe19a") if dark else ("#fff0c7", "#744d00")),
            "invalid": (("#4a2419", "#ffc7b5") if dark else ("#ffe2d9", "#8d2d13")),
            "missing": (("#481f29", "#ffc1d0") if dark else ("#fbdde4", "#8b1f3b")),
        }
        for table in (getattr(self, "table", None), getattr(self, "ligand_table", None)):
            if table is None:
                continue
            for tag, (background, foreground) in colors.items():
                table.tag_configure(tag, background=background, foreground=foreground)

    # ----------------------
    # Ligand queue helpers
    # ----------------------
    def add_ligand_path(self, path):
        if not path:
            return False
        norm = os.path.abspath(os.path.normpath(path))
        for existing in self.ligands:
            if os.path.normcase(os.path.abspath(existing)) == os.path.normcase(norm):
                return False
        self.ligands.append(norm)
        return True

    def add_current_ligand(self):
        ligand = self.ligand_var.get().strip()
        if not ligand:
            messagebox.showwarning("No ligand", "Pick a ligand first or type one in the Ligand field.")
            return
        if not os.path.exists(ligand):
            messagebox.showerror("Missing ligand", f"Ligand not found:\n{ligand}")
            return
        before = self._queue_snapshot()
        self.add_ligand_path(ligand)
        self._record_queue_undo(before, "add ligand")
        self.refresh_ligand_table()
        self.save_settings()

    def add_ligands(self):
        files = filedialog.askopenfilenames(filetypes=[("PDBQT", "*.pdbqt")])
        before = self._queue_snapshot()
        added = 0
        for f in files:
            added += int(self.add_ligand_path(f))
        self._record_queue_undo(before, f"add {added} ligands")
        self.refresh_ligand_table()
        self.save_settings()

    def remove_ligand(self):
        sel = self.ligand_table.selection()
        if not sel:
            return
        before = self._queue_snapshot()
        remove_paths = set(sel)
        self.ligands = [p for p in self.ligands if p not in remove_paths]
        self._record_queue_undo(before, f"remove {len(sel)} ligand{'s' if len(sel) != 1 else ''}")
        self.refresh_ligand_table()
        self.save_settings()

    def move_ligand_up(self):
        sel = self.ligand_table.selection()
        before = self._queue_snapshot()
        for s in sel:
            i = next((idx for idx, p in enumerate(self.ligands) if p == s), None)
            if i is not None and i > 0:
                self.ligands[i], self.ligands[i - 1] = self.ligands[i - 1], self.ligands[i]
        self._record_queue_undo(before, "move ligands up")
        self.refresh_ligand_table()
        for s in sel:
            if self.ligand_table.exists(s):
                self.ligand_table.selection_add(s)
        self.save_settings()

    def move_ligand_down(self):
        sel = self.ligand_table.selection()
        before = self._queue_snapshot()
        for s in reversed(sel):
            i = next((idx for idx, p in enumerate(self.ligands) if p == s), None)
            if i is not None and i < len(self.ligands) - 1:
                self.ligands[i], self.ligands[i + 1] = self.ligands[i + 1], self.ligands[i]
        self._record_queue_undo(before, "move ligands down")
        self.refresh_ligand_table()
        for s in sel:
            if self.ligand_table.exists(s):
                self.ligand_table.selection_add(s)
        self.save_settings()

    def clear_ligands(self):
        before = self._queue_snapshot()
        self.ligands = []
        self._record_queue_undo(before, "clear ligand queue")
        self.refresh_ligand_table()
        self.save_settings()

    def refresh_ligand_table(self):
        self.ligand_table.delete(*self.ligand_table.get_children())
        for lig in self.ligands:
            status, tag = self._ligand_queue_status(lig)
            self.ligand_table.insert(
                "",
                "end",
                iid=lig,
                values=(os.path.basename(lig), lig, status),
                tags=(tag,),
            )
        self._apply_queue_status_badges()

    # ----------------------
    # Receptor table
    # ----------------------
    def add_receptor(self):
        before = self._queue_snapshot()
        added = 0
        rejected = []
        for p in filedialog.askopenfilenames(filetypes=[("PDBQT", "*.pdbqt")]):
            was_added, detail = self._queue_receptor_path(p)
            if was_added:
                added += 1
            elif detail != "already queued":
                rejected.append((p, detail))
        if added:
            self._record_queue_undo(before, f"add {added} receptor{'s' if added != 1 else ''}")
            self.refresh_table()
            self.save_settings()
        if rejected:
            sample = "\n".join(f"{os.path.basename(p)}: {why}" for p, why in rejected[:8])
            if len(rejected) > 8:
                sample += f"\n...and {len(rejected) - 8} more"
            messagebox.showwarning("Some receptors were not added", sample)

    def remove_receptor(self):
        sel_paths = self.table.selection()
        if not sel_paths:
            return
        before = self._queue_snapshot()
        self.receptors = [r for r in self.receptors if r["path"] not in sel_paths]
        self._record_queue_undo(before, f"remove {len(sel_paths)} receptor{'s' if len(sel_paths) != 1 else ''}")
        self.refresh_table()
        self.save_settings()

    def move_up(self):
        sel = self.table.selection()
        before = self._queue_snapshot()
        for s in sel:
            i = next((idx for idx, r in enumerate(self.receptors) if r["path"] == s), None)
            if i is not None and i > 0:
                self.receptors[i], self.receptors[i - 1] = self.receptors[i - 1], self.receptors[i]
        self._record_queue_undo(before, "move receptors up")
        self.refresh_table()
        for s in sel:
            self.table.selection_add(s)
        self.save_settings()

    def move_down(self):
        sel = self.table.selection()
        before = self._queue_snapshot()
        for s in reversed(sel):
            i = next((idx for idx, r in enumerate(self.receptors) if r["path"] == s), None)
            if i is not None and i < len(self.receptors) - 1:
                self.receptors[i], self.receptors[i + 1] = self.receptors[i + 1], self.receptors[i]
        self._record_queue_undo(before, "move receptors down")
        self.refresh_table()
        for s in sel:
            self.table.selection_add(s)
        self.save_settings()

    def edit_row(self, event):
        if self.run_in_progress:
            return

        sel = self.table.selection()
        if not sel:
            return
        r = next(x for x in self.receptors if x["path"] == sel[0])

        win = tk.Toplevel(self.root)
        win.title(f"Edit {r['name']}")
        mode = tk.StringVar(value=r["mode"])
        res = tk.StringVar(value=r["residues"])
        pad = tk.StringVar(value=r["padding"])

        ttk.Combobox(win, textvariable=mode, values=["Whole", "Active"], state="readonly").pack(pady=2)
        tk.Entry(win, textvariable=res, width=40).pack(pady=2)
        tk.Entry(win, textvariable=pad, width=10).pack(pady=2)
        tk.Label(
            win,
            text="Residues: 42 (only if unambiguous), A:42, or A:42B | comma-separated | Padding optional"
        ).pack()

        def save():
            before = self._queue_snapshot()
            r["mode"] = mode.get()
            r["residues"] = res.get()
            r["padding"] = pad.get()
            self._record_queue_undo(before, "edit receptor")
            self.refresh_table()
            self.save_settings()
            win.destroy()

        tk.Button(win, text="Save", command=save).pack(pady=5)

    def refresh_table(self):
        self.table.delete(*self.table.get_children())
        for r in self.receptors:
            pad = r["padding"] if r["padding"] else self.padding_var.get()
            status, tag = self._receptor_queue_status(r)
            self.table.insert(
                "",
                "end",
                iid=r["path"],
                values=(r["name"], r["mode"], r["residues"], pad, status),
                tags=(tag,),
            )
        self._apply_queue_status_badges()

    # ----------------------
    # Preview
    # ----------------------
    def preview(self):
        if self.run_in_progress:
            return

        sel = self.table.selection()
        if not sel:
            messagebox.showinfo("Select a receptor", "Select one receptor row to preview.")
            return
        r = next(x for x in self.receptors if x["path"] == sel[0])

        try:
            self.root.config(cursor="watch")
            self.root.update_idletasks()

            box_source_atoms = parse_atoms(r["path"])
            if not box_source_atoms:
                messagebox.showerror("Error", f"No atoms parsed from:\n{r['path']}")
                return

            receptor_models = read_molecular_models(r["path"], source="receptor")
            receptor_atoms = list(receptor_models[0].get("atoms") or []) if receptor_models else []
            if not receptor_atoms:
                messagebox.showerror("Error", f"No molecular records parsed from:\n{r['path']}")
                return

            padding = float(r["padding"]) if r["padding"] else float(self.padding_var.get())

            mode = str(r.get("mode", "")).strip()
            if mode not in {"Whole", "Active"}:
                messagebox.showerror("Invalid docking mode", f"Unsupported receptor mode: {mode or '(blank)'}")
                return

            box_atoms = box_source_atoms
            if mode == "Active":
                try:
                    box_atoms = select_active_residue_atoms(box_source_atoms, r.get("residues", ""))
                except ValueError as exc:
                    messagebox.showerror(
                        "Invalid active-residue selection",
                        f"{exc}\n\nVLiP will not switch this receptor to whole-receptor docking."
                    )
                    return

            cx, cy, cz, sx, sy, sz, *_ = box_from_atoms(box_atoms, padding)

            focus_atoms = []
            if mode == "Active":
                selected_identities = {(atom[4] or "-", atom[3], atom[5]) for atom in box_atoms}
                focus_atoms = [
                    atom for atom in receptor_atoms
                    if (atom.get("chain", "-"), atom.get("resseq", 0), atom.get("icode", ""))
                    in selected_identities
                ]
            if not focus_atoms:
                focus_atoms = [{
                    "x": cx, "y": cy, "z": cz, "source": "preview", "element": "C",
                    "name": "CENTRE", "record": "", "chain": "-", "resseq": 0,
                    "icode": "", "resname": "BOX", "serial": 0,
                }]

            ligand_candidates = []
            try:
                ligand_candidates.extend(self.ligand_table.selection())
            except (AttributeError, tk.TclError):
                pass
            ligand_candidates.extend(self.ligands[:1])
            ligand_candidates.append(self.ligand_var.get().strip())
            ligand_path = next(
                (
                    os.path.abspath(candidate) for candidate in ligand_candidates
                    if candidate and os.path.isfile(candidate)
                ),
                "",
            )

            ligand_models = []
            ligand_name = "Not loaded"
            if ligand_path:
                try:
                    ligand_models = read_molecular_models(ligand_path, source="ligand")
                except OSError:
                    ligand_models = []
                if any(model.get("atoms") for model in ligand_models):
                    ligand_models = molecular_models_centered_at(ligand_models, (cx, cy, cz))
                    ligand_name = os.path.basename(ligand_path)
                else:
                    ligand_models = []
                    ligand_path = ""

            if ligand_models:
                preview_note = (
                    "Preview only: the selected ligand is centred in the docking box so pocket residues and "
                    "surface coverage can be inspected. Source coordinates are unchanged; this is not a docked pose."
                )
            else:
                preview_note = (
                    "No readable queued/current ligand was loaded. Nearby-residue and binding-pocket controls "
                    "use the selected active region (or docking-box centre) until a ligand is selected."
                )

            viewer = MolecularPoseViewer(
                self.root,
                ligand_models=ligand_models,
                receptor_atoms=receptor_atoms,
                title=f"{r['name']} — {mode} docking box",
                source_path=ligand_path or r["path"],
                receptor_path=r["path"],
                result_info={
                    "ligand": ligand_name,
                    "receptor": r["name"],
                    "run": f"{mode} mode; padding {padding:g} Å",
                },
                night_mode=bool(self.night_mode_var.get()),
                open_path_callback=self._open_local_path,
                box_geometry={
                    "center": (cx, cy, cz),
                    "size": (sx, sy, sz),
                    "mode": mode,
                },
                focus_atoms=focus_atoms,
                preview_mode=True,
                preview_note=preview_note,
            )
            viewer.win._vlip_pose_viewer = viewer
        finally:
            try:
                self.root.config(cursor="")
            except Exception:
                pass

    # ----------------------
    # UI state / process control
    # ----------------------
    @staticmethod
    def _normalize_speed_mode(mode):
        text = str(mode or "").strip().title()
        return text if text in SPEED_MODES else "Full"

    @staticmethod
    def _time_text_to_minutes(value):
        match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
        if not match:
            raise ValueError("Use 24-hour HH:MM times, for example 08:00 or 18:30.")
        hour, minute = int(match.group(1)), int(match.group(2))
        if hour > 23 or minute > 59:
            raise ValueError("Use a valid 24-hour time between 00:00 and 23:59.")
        return hour * 60 + minute

    @classmethod
    def _scheduled_speed_mode(cls, start_text, end_text, when=None):
        start = cls._time_text_to_minutes(start_text)
        end = cls._time_text_to_minutes(end_text)
        if start == end:
            raise ValueError("The Gentle start and end times must be different.")
        current = when or time.localtime()
        minute = int(current.tm_hour) * 60 + int(current.tm_min)
        in_gentle_window = (
            start <= minute < end if start < end else minute >= start or minute < end
        )
        return "Gentle" if in_gentle_window else "Full"

    def _detect_available_cpu_ids(self):
        fallback = list(range(max(1, int(os.cpu_count() or 1))))
        if not IS_WINDOWS:
            try:
                return sorted(int(cpu) for cpu in os.sched_getaffinity(0))
            except (AttributeError, OSError):
                return fallback
        try:
            kernel32 = ctypes.windll.kernel32
            kernel32.GetCurrentProcess.restype = ctypes.c_void_p
            process_mask = ctypes.c_size_t()
            system_mask = ctypes.c_size_t()
            ok = kernel32.GetProcessAffinityMask(
                kernel32.GetCurrentProcess(),
                ctypes.byref(process_mask),
                ctypes.byref(system_mask),
            )
            if ok and process_mask.value:
                width = ctypes.sizeof(ctypes.c_size_t) * 8
                detected = [index for index in range(width) if process_mask.value & (1 << index)]
                if detected:
                    return detected
        except Exception:
            pass
        return fallback

    def _speed_cpu_ids(self, mode):
        mode = self._normalize_speed_mode(mode)
        available = list(self.available_cpu_ids or [0])
        wanted = max(1, int(math.ceil(len(available) * SPEED_CORE_FRACTIONS[mode])))
        return available[:wanted]

    def _speed_profile_text(self, mode):
        mode = self._normalize_speed_mode(mode)
        used = len(self._speed_cpu_ids(mode))
        total = max(1, len(self.available_cpu_ids))
        priority = "below-normal priority" if mode == "Gentle" else "normal priority"
        return f"{mode}: {used} of {total} logical CPU cores, {priority}"

    def _apply_speed_to_process(self, proc, mode=None):
        mode = self._normalize_speed_mode(mode or self.active_speed_mode)
        if proc is None or proc.poll() is not None:
            return False, f"{self._speed_profile_text(mode)}; applies when the next external step starts."

        cpu_ids = self._speed_cpu_ids(mode)
        try:
            if IS_WINDOWS:
                handle = ctypes.c_void_p(int(proc._handle))
                mask = 0
                for cpu_id in cpu_ids:
                    mask |= 1 << int(cpu_id)
                kernel32 = ctypes.windll.kernel32
                set_affinity = kernel32.SetProcessAffinityMask
                set_affinity.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                set_affinity.restype = ctypes.c_int
                if not set_affinity(handle, ctypes.c_size_t(mask)):
                    raise ctypes.WinError()
                set_priority = kernel32.SetPriorityClass
                set_priority.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                set_priority.restype = ctypes.c_int
                priority_class = 0x00004000 if mode == "Gentle" else 0x00000020
                if not set_priority(handle, priority_class):
                    raise ctypes.WinError()
            elif hasattr(os, "sched_setaffinity"):
                os.sched_setaffinity(proc.pid, set(cpu_ids))
            else:
                return False, (
                    f"{self._speed_profile_text(mode)}; live CPU limiting is unavailable "
                    f"on {platform.system() or 'this operating system'}."
                )
        except Exception as exc:
            return False, f"Could not apply {mode} to process {proc.pid}: {exc}"

        return True, f"{self._speed_profile_text(mode)}; applied now to process {proc.pid}."

    def _performance_history_path(self):
        outdir = str(getattr(self, "active_run_outdir", "") or "").strip()
        return os.path.join(outdir, PERFORMANCE_HISTORY_FILENAME) if outdir else ""

    def _record_performance_event(self, source, message):
        path = self._performance_history_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {source} | {message}\n"
            with self.performance_event_lock:
                with open(path, "a", encoding="utf-8", errors="replace") as handle:
                    handle.write(line)
        except Exception:
            pass

    def _post_speed_state(self):
        if self.run_in_progress:
            self.job_queue.put({
                "type": "speed_status",
                "mode": self.active_speed_mode,
                "schedule_enabled": self.active_schedule_enabled,
                "schedule_start": self.active_schedule_start,
                "schedule_end": self.active_schedule_end,
                "status": self.last_speed_apply_summary,
            })

    def _sync_speed_controls(self):
        status = self.last_speed_apply_summary
        try:
            self.speed_status_var.set(status)
        except Exception:
            pass
        if self.overlay is not None:
            try:
                self.overlay.set_speed_state(
                    self.active_speed_mode,
                    bool(self.speed_schedule_enabled_var.get()),
                    self.speed_schedule_start_var.get().strip(),
                    self.speed_schedule_end_var.get().strip(),
                    status,
                )
            except Exception:
                pass

    def _set_speed_mode(self, mode, source="manual", record=True, force_event=False):
        mode = self._normalize_speed_mode(mode)
        self.active_schedule_enabled = bool(self.speed_schedule_enabled_var.get())
        self.active_schedule_start = self.speed_schedule_start_var.get().strip()
        self.active_schedule_end = self.speed_schedule_end_var.get().strip()
        with self.speed_lock:
            changed = mode != self.active_speed_mode
            self.active_speed_mode = mode
        self.speed_var.set(mode)

        with self.current_process_lock:
            processes = list(self.active_processes)
        summaries = [self._apply_speed_to_process(proc, mode)[1] for proc in processes]
        summary = " | ".join(summaries) if summaries else self._apply_speed_to_process(None, mode)[1]
        self.last_speed_apply_summary = summary
        self._sync_speed_controls()
        if record and (changed or force_event):
            self._record_performance_event(source, summary)
        return summary

    def _apply_configured_speed(self, source="schedule", record=True, force_event=False):
        self.active_schedule_enabled = bool(self.speed_schedule_enabled_var.get())
        self.active_schedule_start = self.speed_schedule_start_var.get().strip()
        self.active_schedule_end = self.speed_schedule_end_var.get().strip()
        if self.active_schedule_enabled:
            try:
                mode = self._scheduled_speed_mode(
                    self.active_schedule_start,
                    self.active_schedule_end,
                )
            except ValueError:
                self.speed_schedule_enabled_var.set(False)
                self.active_schedule_enabled = False
                mode = self.speed_var.get()
        else:
            mode = self.speed_var.get()
        return self._set_speed_mode(mode, source=source, record=record, force_event=force_event)

    def _schedule_description(self):
        if not bool(self.speed_schedule_enabled_var.get()):
            return "Off (manual speed)"
        return (
            f"Gentle {self.speed_schedule_start_var.get().strip()}–"
            f"{self.speed_schedule_end_var.get().strip()}; Full outside those hours"
        )

    def on_manual_speed_change(self, _event=None, mode=None):
        selected = self._normalize_speed_mode(mode or self.speed_var.get())
        self.speed_schedule_enabled_var.set(False)
        self._set_speed_mode(selected, source="manual change", force_event=True)
        self.save_settings()

    def on_speed_schedule_change(self, enabled=None, start_text=None, end_text=None):
        if enabled is not None:
            self.speed_schedule_enabled_var.set(bool(enabled))
        if start_text is not None:
            self.speed_schedule_start_var.set(str(start_text).strip())
        if end_text is not None:
            self.speed_schedule_end_var.set(str(end_text).strip())

        if bool(self.speed_schedule_enabled_var.get()):
            try:
                self._scheduled_speed_mode(
                    self.speed_schedule_start_var.get(),
                    self.speed_schedule_end_var.get(),
                )
            except ValueError as exc:
                self.speed_schedule_enabled_var.set(False)
                messagebox.showerror("Invalid performance schedule", str(exc))
                self._sync_speed_controls()
                return False

        self._apply_configured_speed(source="schedule change", force_event=True)
        self._record_performance_event("schedule", self._schedule_description())
        self.save_settings()
        return True

    def on_overlay_speed_change(self, mode):
        self.on_manual_speed_change(mode=mode)

    def on_overlay_schedule_change(self, enabled, start_text, end_text):
        self.on_speed_schedule_change(enabled=enabled, start_text=start_text, end_text=end_text)

    def _speed_schedule_tick(self):
        try:
            if bool(self.speed_schedule_enabled_var.get()):
                scheduled = self._scheduled_speed_mode(
                    self.speed_schedule_start_var.get(),
                    self.speed_schedule_end_var.get(),
                )
                if scheduled != self.active_speed_mode:
                    self._set_speed_mode(scheduled, source="daily schedule", force_event=True)
                    self.save_settings()
        except (tk.TclError, ValueError):
            pass
        finally:
            try:
                self._speed_schedule_after_id = self.root.after(15000, self._speed_schedule_tick)
            except tk.TclError:
                self._speed_schedule_after_id = None

    def set_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"

        for child in self.root.winfo_children():
            self._set_state_recursive(child, state)

        if self.overlay is not None and not enabled:
            try:
                self.overlay.pause_btn.config(state="normal")
                self.overlay.stop_after_receptor_btn.config(
                    state="disabled" if self.stop_after_receptor_event.is_set() else "normal"
                )
                self.overlay.cancel_btn.config(state="normal")
            except Exception:
                pass
        if enabled:
            self._update_undo_buttons()

    def _set_state_recursive(self, widget, state):
        if self.overlay is not None and widget == self.overlay.win:
            return
        try:
            widget.configure(state=state)
        except Exception:
            pass
        for child in widget.winfo_children():
            self._set_state_recursive(child, state)

    def set_current_process(self, proc):
        with self.current_process_lock:
            self.current_process = proc
            self.active_processes.add(proc)
        _ok, summary = self._apply_speed_to_process(proc)
        self.last_speed_apply_summary = summary
        self._record_performance_event("external step started", summary)
        self._post_speed_state()

    def clear_current_process(self, proc):
        with self.current_process_lock:
            self.active_processes.discard(proc)
            if self.current_process is proc:
                self.current_process = next(iter(self.active_processes), None)

    def terminate_current_process(self):
        # Signal every worker promptly. Its owning thread waits and escalates.
        with self.current_process_lock:
            processes = list(self.active_processes)
        for proc in processes:
            try:
                if proc.poll() is None:
                    proc.terminate()
            except OSError:
                pass

    def on_pause_resume_clicked(self):
        if not self.run_in_progress:
            return

        if self.pause_event.is_set():
            self.pause_event.clear()
            if self.overlay is not None:
                self.overlay.set_paused(False)
                try:
                    current = self.overlay.pb["value"]
                    total = self.overlay.pb["maximum"]
                except Exception:
                    current, total = 0, 1
                self.overlay.update_progress(
                    current, total,
                    status="Resuming...",
                    ligand=self.overlay.ligand_var.get().replace("Ligand: ", "", 1),
                    receptor=self.overlay.receptor_var.get().replace("Receptor: ", "", 1),
                    run_text=self.overlay.run_var.get().replace("Run: ", "", 1)                )
        else:
            self.pause_event.set()
            if self.overlay is not None:
                self.overlay.set_paused(True)
                try:
                    current = self.overlay.pb["value"]
                    total = self.overlay.pb["maximum"]
                except Exception:
                    current, total = 0, 1
                self.overlay.update_progress(
                    current, total,
                    status="Pause requested - current Vina/PLIP step will finish, then VLiP will pause safely",
                    ligand=self.overlay.ligand_var.get().replace("Ligand: ", "", 1),
                    receptor=self.overlay.receptor_var.get().replace("Receptor: ", "", 1),
                    run_text=self.overlay.run_var.get().replace("Run: ", "", 1)
                )

    def on_stop_after_receptor_clicked(self):
        if not self.run_in_progress:
            return
        if self.stop_after_receptor_event.is_set():
            return

        self.stop_after_receptor_event.set()

        if self.overlay is not None:
            self.overlay.set_stop_after_receptor_requested(True)
            try:
                current = self.overlay.pb["value"]
                total = self.overlay.pb["maximum"]
            except Exception:
                current, total = 0, 1
            self.overlay.update_progress(
                current,
                total,
                status="Stop requested - will stop after current receptor finishes",
                ligand=self.overlay.ligand_var.get().replace("Ligand: ", "", 1),
                receptor=self.overlay.receptor_var.get().replace("Receptor: ", "", 1),
                run_text=self.overlay.run_var.get().replace("Run: ", "", 1)
            )

    def on_cancel_clicked(self):
        if not self.run_in_progress:
            return

        self.cancel_event.set()
        self.pause_event.clear()

        if self.overlay is not None:
            self.overlay.set_paused(False)
            self.overlay.set_cancelled_state()
            try:
                current = self.overlay.pb["value"]
                total = self.overlay.pb["maximum"]
            except Exception:
                current, total = 0, 1
            self.overlay.update_progress(
                current, total,
                status="Cancelling... waiting for current process to stop",
                ligand=self.overlay.ligand_var.get().replace("Ligand: ", "", 1),
                receptor=self.overlay.receptor_var.get().replace("Receptor: ", "", 1),
                run_text=self.overlay.run_var.get().replace("Run: ", "", 1)
            )

        self.terminate_current_process()

    # ----------------------
    # Queue / status pump
    # ----------------------
    def post_progress(self, current, total, status="", ligand="", receptor="", run_text=""):
        self.job_queue.put({
            "type": "progress",
            "current": current,
            "total": total,
            "status": status,
            "ligand": ligand,
            "receptor": receptor,
            "run_text": run_text,
        })

    def post_done(self, kind, title, message, project_dir="", auto_show_poses=False):
        self.job_queue.put({
            "type": "done",
            "kind": kind,
            "title": title,
            "message": message,
            "project_dir": project_dir,
            "auto_show_poses": bool(auto_show_poses),
        })

    def start_progress_poll(self):
        self.root.after(80, self.process_job_queue)

    def process_job_queue(self):
        try:
            while True:
                item = self.job_queue.get_nowait()
                typ = item.get("type")

                if typ == "progress":
                    if self.overlay is not None:
                        self.overlay.update_progress(
                            item.get("current", 0),
                            item.get("total", 1),
                            status=item.get("status", ""),
                            ligand=item.get("ligand", ""),
                            receptor=item.get("receptor", ""),
                            run_text=item.get("run_text", "")
                        )
                        try:
                            self.overlay.win.update_idletasks()
                        except Exception:
                            pass

                elif typ == "speed_status":
                    self.last_speed_apply_summary = item.get("status", self.last_speed_apply_summary)
                    self.speed_status_var.set(self.last_speed_apply_summary)
                    if self.overlay is not None:
                        self.overlay.set_speed_state(
                            item.get("mode", self.active_speed_mode),
                            bool(item.get("schedule_enabled", False)),
                            item.get("schedule_start", "08:00"),
                            item.get("schedule_end", "18:00"),
                            self.last_speed_apply_summary,
                        )

                elif typ == "done":
                    self.finish_run_ui(
                        item["kind"], item["title"], item["message"],
                        project_dir=item.get("project_dir", ""),
                        auto_show_poses=bool(item.get("auto_show_poses", False)),
                    )
                    return

        except queue.Empty:
            pass

        if self.run_in_progress:
            self.root.after(80, self.process_job_queue)

    def finish_run_ui(self, kind, title, message, project_dir="", auto_show_poses=False):
        self.run_in_progress = False
        self.pause_event.clear()
        self.cancel_event.clear()
        self.stop_after_receptor_event.clear()

        with self.current_process_lock:
            self.current_process = None
            self.active_processes.clear()

        try:
            self.root.config(cursor="")
        except Exception:
            pass

        self.set_controls_enabled(True)

        if self.overlay is not None:
            self.overlay.close()
            self.overlay = None

        active_outdir = getattr(self, "active_run_outdir", "")
        if active_outdir:
            _vlip_write_run_marker(active_outdir, "Docking pipeline")
            try:
                concise_message = " ".join(str(message or "").split())
                self._record_performance_event("run end", f"{title}: {concise_message[:500]}")
                self._remember_recent_project(active_outdir)
            except Exception:
                pass
            self.active_run_outdir = ""

        if kind == "error":
            messagebox.showerror(title, message)
        elif kind == "warning":
            messagebox.showwarning(title, message)
        else:
            messagebox.showinfo(title, message)

        if auto_show_poses and project_dir and kind != "error":
            self.root.after_idle(
                lambda path=project_dir: self.open_automatic_run_pose_viewer(path)
            )

    # ----------------------
    # Pause / cancel / stop helpers for worker
    # ----------------------
    def check_cancelled(self):
        if self.cancel_event.is_set():
            raise RunCancelled("Cancelled by user.")

    def check_stop_after_receptor_boundary(self, runlog, ligand_name, receptor_name):
        if self.stop_after_receptor_event.is_set():
            log_line(
                runlog,
                f"[INFO] Stop-after-receptor triggered after ligand '{ligand_name}', receptor '{receptor_name}'"
            )
            raise RunStoppedAfterReceptor(
                f"Stopped after receptor: ligand '{ligand_name}', receptor '{receptor_name}'"
            )

    def wait_if_paused_or_cancelled(self, current, total, status, ligand, receptor, run_text):
        self.check_cancelled()

        posted = False
        while self.pause_event.is_set():
            self.check_cancelled()
            if not posted:
                self.post_progress(
                    current, total,
                    status="Paused safely between external-tool steps - waiting to resume",
                    ligand=ligand,
                    receptor=receptor,
                    run_text=run_text
                )
                posted = True
            time.sleep(0.15)

        self.check_cancelled()

    def run_tracked_subprocess(self, cmd, cwd=None, timeout=None, env=None, live_stage=None):
        """
        Single tracked route for long-running external tools.
        Vina/PLIP stdout and stderr are streamed into the GUI while still being
        captured in full for the existing run logs, error reports and seed parsing.
        """
        self.check_cancelled()
        started = time.time()
        stage = str(live_stage or "").upper()
        if stage:
            self._live_console_emit(stage, command_as_text(cmd), "CMD")

        proc = popen_hidden_subprocess(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.set_current_process(proc)

        stdout_parts = []
        stderr_parts = []
        stream_queue = queue.Queue()

        def reader(stream, stream_name, sink):
            try:
                while True:
                    line = stream.readline()
                    if line == "":
                        break
                    sink.append(line)
                    stream_queue.put((stream_name, line))
                tail = stream.read()
                if tail:
                    sink.append(tail)
                    stream_queue.put((stream_name, tail))
            except Exception as exc:
                stream_queue.put((stream_name, f"[VLiP stream reader warning: {exc}]\n"))
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        readers = []
        for stream, name, sink in (
            (proc.stdout, "STDOUT", stdout_parts),
            (proc.stderr, "STDERR", stderr_parts),
        ):
            thread = threading.Thread(target=reader, args=(stream, name, sink), daemon=True)
            thread.start()
            readers.append(thread)

        timed_out = False
        try:
            while proc.poll() is None:
                if self.cancel_event.is_set():
                    try:
                        proc.terminate()
                    except OSError:
                        pass
                    break
                if timeout is not None and (time.time() - started) > timeout:
                    timed_out = True
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    break
                try:
                    stream_name, chunk = stream_queue.get(timeout=0.05)
                    if stage:
                        self._live_console_emit(stage, chunk, stream_name)
                except queue.Empty:
                    pass

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                proc.wait()

            for thread in readers:
                thread.join(timeout=2.0)

            while True:
                try:
                    stream_name, chunk = stream_queue.get_nowait()
                except queue.Empty:
                    break
                if stage:
                    self._live_console_emit(stage, chunk, stream_name)
        finally:
            self.clear_current_process(proc)

        stdout = "".join(stdout_parts)
        stderr = "".join(stderr_parts)

        if timed_out:
            if stage:
                self._live_console_emit(stage, f"Process timed out after {timeout} seconds.", "ERROR")
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr)

        if self.cancel_event.is_set():
            if stage:
                self._live_console_emit(stage, "Process cancelled by user.", "STATUS")
            raise RunCancelled("Cancelled by user.")

        if proc.returncode != 0:
            if stage:
                self._live_console_emit(stage, f"Process exited with code {proc.returncode}.", "ERROR")
            raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout, stderr=stderr)

        if stage:
            elapsed = time.time() - started
            self._live_console_emit(stage, f"Completed successfully in {elapsed:.2f} seconds.", "STATUS")
        return stdout, stderr

    # ----------------------
    # PLIP summary filtering
    # ----------------------
    def extract_unl_section(self, text):
        lines = text.splitlines()
        blocks = []
        current = []
        current_header = None

        for line in lines:
            stripped = line.strip()

            is_header = False
            if stripped and ":" in stripped and "(" in stripped and ") -" in stripped:
                is_header = True

            if is_header:
                if current:
                    blocks.append((current_header, "\n".join(current).rstrip() + "\n"))
                current_header = stripped
                current = [line]
            else:
                if current:
                    current.append(line)

        if current:
            blocks.append((current_header, "\n".join(current).rstrip() + "\n"))

        for header, block in blocks:
            if header and header.startswith("UNL:Z:1"):
                return block

        for header, block in blocks:
            if header and header.startswith("UNL:"):
                return block

        return ""

    def rebuild_all_pose_summary(self, plip_dir, runlog, ligand_name, receptor_name):
        summary_files = preferred_pose_plip_summaries(plip_dir)

        out_path = os.path.join(plip_dir, "ALL_POSES_UNL_SUMMARY.txt")

        try:
            with open(out_path, "w", encoding="utf-8") as out:
                if not summary_files:
                    out.write("No pose UNL summaries available.\n")
                else:
                    for i, path in enumerate(summary_files):
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            text = f.read().strip()

                        out.write(text + "\n")

                        if i != len(summary_files) - 1:
                            out.write("\n")

            log_line(runlog, f"[INFO] Wrote combined PLIP summary: {out_path}")
            return out_path
        except Exception as e:
            log_line(runlog, f"[ERROR] Failed writing combined PLIP summary: {e}")
            return None

    # ----------------------
    # Internal PLIP runner
    # ----------------------
    def _run_plip_pose_jobs(self, jobs, workers):
        """Bound in-flight processes; collect on this coordinator in pose order."""
        workers = min(normalize_plip_workers(workers), len(jobs))
        if not jobs:
            return []
        results = {}
        pending = {}
        next_job = 0
        completed = 0
        started = time.monotonic()
        self._live_console_emit("PLIP", f"Analysing {len(jobs)} poses; up to {workers} at once.", "STATUS")
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="vlip-plip") as pool:
            try:
                while next_job < len(jobs) or pending:
                    self.check_cancelled()
                    while next_job < len(jobs) and len(pending) < workers and not self.pause_event.is_set():
                        self.check_cancelled()
                        job = jobs[next_job]
                        pending[pool.submit(self.run_plip_for_pdb, **job)] = next_job
                        next_job += 1
                    if not pending:
                        self.cancel_event.wait(0.1)
                        continue
                    done, _ = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    for future in done:
                        index = pending.pop(future)
                        try:
                            results[index] = bool(future.result())
                        except RunCancelled:
                            raise
                        except Exception as exc:
                            results[index] = False
                            job = jobs[index]
                            log_line(job["runlog"], f"[ERROR] PLIP {job['pose_name']}: {exc}")
                        completed += 1
                        self._live_console_emit("PLIP", f"{completed}/{len(jobs)} poses finished; "
                            f"{len(pending)} active; {sum(not ok for ok in results.values())} failed.", "STATUS")
            except BaseException:
                self.cancel_event.set()
                for future in pending:
                    future.cancel()
                self.terminate_current_process()
                raise
        elapsed = time.monotonic() - started
        log_line(jobs[0]["runlog"], f"[PLIP TIMING] {len(jobs)} poses; workers={workers}; elapsed={elapsed:.2f}s")
        return [(job, results[index]) for index, job in enumerate(jobs)]

    def run_plip_for_pdb(self, pdb_file, plip_dir, runlog, pose_name, ligand_name, receptor_name,
                         vina_score=None, settings_record_path=None):
        self.check_cancelled()
        plip_ok = False

        os.makedirs(plip_dir, exist_ok=True)

        temp_pose_dir = tempfile.mkdtemp(prefix="vlip_plip_")

        runtime_py = managed_runtime_python(False)
        runtime_env = None
        if runtime_py:
            cmd = [runtime_py, self._single_file_script()]
            runtime_env = managed_runtime_subprocess_env()
        else:
            cmd = launchable_program()
        cmd += [
            "--plip-worker",
            "-f", pdb_file,
            "-o", temp_pose_dir,
            "-t",
            "-x",
            "-v", "--maxthreads", "1"
        ]

        log_line(runlog, f"[INFO] PLIP short-path staging: {temp_pose_dir}")
        log_line(runlog, "[PLIP CMD] " + " ".join(cmd))
        if settings_record_path:
            log_line(settings_record_path, "")
            log_line(settings_record_path, f"Exact PLIP command for {pose_name}: {command_as_text(cmd)}")
            log_line(settings_record_path, f"{pose_name} Vina affinity supplied to report: {self._format_vina_score(vina_score)} kcal/mol")

        try:
            stdout, stderr = self.run_tracked_subprocess(cmd, env=runtime_env, live_stage=f"PLIP {pose_name}")

            if stdout:
                log_line(runlog, "[PLIP STDOUT] " + stdout.strip().replace("\n", "\n[PLIP STDOUT] "))
            if stderr:
                log_line(runlog, "[PLIP STDERR] " + stderr.strip().replace("\n", "\n[PLIP STDERR] "))

            produced_files = []
            for root, _, files in os.walk(temp_pose_dir):
                for fname in files:
                    src = os.path.join(root, fname)
                    prefixed_name = f"{pose_name}_{fname}"
                    dst = os.path.join(plip_dir, prefixed_name)
                    if os.path.lexists(dst):
                        if os.path.isdir(dst) and not os.path.islink(dst):
                            raise RuntimeError(f"Refusing to replace directory with PLIP output: {dst}")
                        os.remove(dst)
                    shutil.move(src, dst)
                    produced_files.append(dst)

            try:
                shutil.rmtree(temp_pose_dir, ignore_errors=True)
            except Exception:
                pass

            report_candidates = []
            for path in produced_files:
                base = os.path.basename(path).lower()
                if base.startswith(f"{pose_name.lower()}_") and (base.endswith(".txt") or base.endswith(".report")):
                    report_candidates.append(path)

            report_candidates.sort(
                key=lambda p: (
                    0 if os.path.basename(p).lower() == f"{pose_name.lower()}_report.txt" else 1,
                    len(p)
                )
            )

            if report_candidates:
                try:
                    with open(report_candidates[0], "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()

                    unl_block = self.extract_unl_section(text)

                    if unl_block.strip():
                        summary_path = os.path.join(plip_dir, f"{pose_name}_UNL_only_summary.txt")
                        with open(summary_path, "w", encoding="utf-8") as f:
                            f.write("=" * 80 + "\n")
                            f.write(f"Ligand: {ligand_name}\n")
                            f.write(f"Receptor: {receptor_name}\n")
                            score_text = self._format_vina_score(vina_score)
                            f.write(f"Pose: {pose_name}  vina score:{score_text} kcal/mol\n")
                            f.write("=" * 80 + "\n")
                            f.write(unl_block.strip() + "\n")
                            f.write(self._vina_report_text(plip_dir))

                        log_line(runlog, f"[INFO] Wrote UNL-only PLIP summary: {summary_path}")
                        compact_path = os.path.join(
                            plip_dir, f"{pose_name}_PLIP_compact_summary.txt"
                        )
                        compact_text = format_compact_pose_plip_summary(
                            unl_block,
                            ligand_name,
                            receptor_name,
                            pose_name,
                            vina_score,
                        )
                        with open(compact_path, "w", encoding="utf-8", newline="\n") as f:
                            f.write(compact_text + "\n" + self._vina_report_text(plip_dir))
                        log_line(runlog, f"[INFO] Wrote compact pose-specific PLIP summary: {compact_path}")
                        _vlip_command_audit_action(
                            "07_plip",
                            "write_compact_pose_plip_summary",
                            {
                                "pose": pose_name,
                                "source_report": report_candidates[0],
                                "unl_summary": summary_path,
                                "compact_summary": compact_path,
                            },
                            cwd=plip_dir,
                            source="VLiP PLIP post-processing",
                        )
                        plip_ok = True
                    else:
                        log_line(runlog, f"[WARN] Could not find UNL section in PLIP report for {pose_name}.")
                except Exception as e:
                    log_line(runlog, f"[ERROR] Failed creating UNL-only summary for {pose_name}: {e}")
            else:
                log_line(runlog, f"[WARN] No PLIP text report found after rename for {pose_name}.")

            if settings_record_path:
                log_line(settings_record_path, f"{pose_name} PLIP exit status: {'SUCCESS' if plip_ok else 'COMPLETED BUT UNL SUMMARY NOT PRODUCED'}")

        except RunCancelled:
            log_line(runlog, f"[INFO] PLIP cancelled for {pdb_file}")
            if settings_record_path:
                log_line(settings_record_path, f"{pose_name} PLIP exit status: CANCELLED")
            raise
        except subprocess.CalledProcessError as e:
            errlog = os.path.join(plip_dir, f"{pose_name}_plip_error.log")
            with open(errlog, "w", encoding="utf-8", errors="replace") as f:
                f.write("CMD:\n" + " ".join(e.cmd) + "\n\n")
                f.write("STDOUT:\n" + (e.output or "") + "\n\n")
                f.write("STDERR:\n" + (e.stderr or "") + "\n")
            log_line(runlog, f"[ERROR] PLIP failed for {pdb_file}. See: {errlog}")
            if settings_record_path:
                log_line(settings_record_path, f"{pose_name} PLIP exit status: FAILED (return code {e.returncode})")
                log_line(settings_record_path, f"{pose_name} PLIP error log: {errlog}")
        except Exception as e:
            errlog = os.path.join(plip_dir, f"{pose_name}_plip_error.log")
            with open(errlog, "w", encoding="utf-8", errors="replace") as f:
                f.write("Unexpected PLIP launch error:\n")
                f.write(str(e) + "\n\n")
                f.write(traceback.format_exc())
            log_line(runlog, f"[ERROR] PLIP launch crashed for {pdb_file}. See: {errlog}")
            if settings_record_path:
                log_line(settings_record_path, f"{pose_name} PLIP exit status: CRASHED ({e})")
                log_line(settings_record_path, f"{pose_name} PLIP error log: {errlog}")
        finally:
            try:
                shutil.rmtree(temp_pose_dir, ignore_errors=True)
            except Exception:
                pass
        return plip_ok

    # ----------------------
    # Run validation and start
    # ----------------------
    def _confirm_pre_run_summary(self, args, software_versions):
        """Show a copyable final review and return True only when the user confirms."""
        dialog = tk.Toplevel(self.root)
        dialog.title(f"VLiP v{APP_VERSION} — Check Before Docking")
        dialog.transient(self.root)
        dialog.minsize(720, 560)
        dialog.geometry("820x680")

        decision = {"confirmed": False}

        tk.Label(
            dialog,
            text="Check everything before docking starts",
            font=("TkDefaultFont", 14, "bold"),
            anchor="w",
        ).pack(fill="x", padx=14, pady=(14, 2))
        tk.Label(
            dialog,
            text="Nothing has started yet. Choose Go Back to change any selection or setting.",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 10))

        text_frame = tk.Frame(dialog)
        text_frame.pack(fill="both", expand=True, padx=14)
        scrollbar = tk.Scrollbar(text_frame)
        scrollbar.pack(side="right", fill="y")
        report = tk.Text(
            text_frame,
            wrap="word",
            font="TkFixedFont",
            padx=10,
            pady=10,
            yscrollcommand=scrollbar.set,
        )
        report.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=report.yview)

        yes_no = lambda value: "YES" if value else "NO"
        remaining_jobs = max(0, int(args["total_jobs"]) - int(args.get("resume_from_job", 0) or 0))
        if "estimated_seconds" in args:
            estimated_seconds = args.get("estimated_seconds")
            timing_samples = int(args.get("estimate_samples", 0) or 0)
        else:
            estimated_seconds, timing_samples = self._historical_run_estimate(args)
        warnings = []
        if str(software_versions.get("vina_version", "")).startswith("UNAVAILABLE"):
            warnings.append("Vina's version could not be read, although its executable file passed validation.")
        if args["run_plip"] and str(software_versions.get("plip_version", "")).startswith("UNAVAILABLE"):
            warnings.append("PLIP is selected but its installed version/runtime could not be confirmed.")
        try:
            output_has_files = False
            if os.path.isdir(args["outdir"]):
                with os.scandir(args["outdir"]) as entries:
                    output_has_files = any(entries)
        except OSError:
            output_has_files = False
        if output_has_files and not args.get("resume_from_job"):
            warnings.append("The output folder already contains files; matching report names may be replaced.")

        lines = [
            "RUN SCOPE",
            "-" * 76,
            f"Ligands:                 {len(args['ligands_to_run'])}",
            f"Receptors:               {len(args['receptors'])}",
            f"Repeats per pair:         {args['repeats']}",
            f"Total docking jobs:       {args['total_jobs']}",
            f"Jobs to run now:          {remaining_jobs}",
            f"Estimated run time:       {self._format_duration(estimated_seconds)} ({timing_samples} prior job{'s' if timing_samples != 1 else ''})" if estimated_seconds is not None else "Estimated run time:       available after timed jobs have completed",
            f"Resume point:             {args.get('resume_from_job', 0) or 'new run'}",
            "Input-file checks:       PASSED",
            "",
            "SOFTWARE",
            "-" * 76,
            f"VLiP:                     {APP_VERSION}",
            f"Vina version:             {software_versions.get('vina_version', 'unknown')}",
            f"Vina executable:          {args['vina']}",
            f"PLIP enabled:             {yes_no(args['run_plip'])}",
            f"Parallel PLIP poses:      {args.get('plip_workers', 2)}",
            f"PLIP version:             {software_versions.get('plip_version', 'unknown')}",
            f"PLIP runtime:             {software_versions.get('plip_runtime', 'not used / not found')}",
            "",
            "DOCKING SETTINGS",
            "-" * 76,
            f"Exhaustiveness:           {args['exhaustiveness']}",
            *vina_option_lines(args.get("vina_options")),
            f"Starting performance:     {args.get('performance_mode_at_start', 'Full')}",
            f"Daily speed schedule:     {args.get('performance_schedule', 'Off')}",
            f"Default box padding:      {args['default_padding']}",
            f"Merge receptor+ligand:    {yes_no(args['save_merge'])}",
            f"Convert complexes to PDB: {yes_no(args['save_pdb'])}",
            f"Save raw Vina text:       {yes_no(args['save_txt'])}",
            f"Run PLIP analysis:        {yes_no(args['run_plip'])}",
            "",
            "OUTPUT",
            "-" * 76,
            f"Folder: {args['outdir']}",
            f"Settings record: {COMPLETE_SETTINGS_FILENAME}",
            "Combined docking report: all ligands docking scores.txt",
            "Combined PLIP report: all ligands plip.txt" if args["run_plip"] else "Combined PLIP report: disabled",
            "",
            "EXPERIMENT NOTES",
            "-" * 76,
            str(args.get("experiment_notes") or "(none)"),
            "",
            "LIGANDS",
            "-" * 76,
        ]
        lines.extend(f"{index}. {path}" for index, path in enumerate(args["ligands_to_run"], 1))
        lines.extend(["", "RECEPTORS", "-" * 76])
        for index, receptor in enumerate(args["receptors"], 1):
            mode = receptor.get("mode", "Whole")
            residues = receptor.get("residues", "").strip()
            padding = receptor.get("padding", "").strip() or f"default ({args['default_padding']})"
            detail = f"mode={mode}; padding={padding}"
            if residues:
                detail += f"; residues={residues}"
            lines.append(f"{index}. {receptor.get('path', '')}")
            lines.append(f"   {detail}")

        lines.extend(["", "WARNINGS", "-" * 76])
        if warnings:
            lines.extend(f"• {warning}" for warning in warnings)
        else:
            lines.append("None — the run is ready to start.")

        configuration_text = "\n".join(lines)
        report.insert("1.0", configuration_text)
        report.config(state="disabled")

        button_row = tk.Frame(dialog)
        button_row.pack(fill="x", padx=14, pady=14)

        def close(confirmed=False):
            decision["confirmed"] = bool(confirmed)
            dialog.destroy()

        action_status_var = tk.StringVar(value="")

        def copy_configuration():
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(configuration_text)
                self.root.update_idletasks()
                action_status_var.set("Configuration copied.")
            except Exception as exc:
                messagebox.showerror("Copy failed", str(exc), parent=dialog)

        def export_configuration():
            initial_dir = args.get("outdir", "")
            if not os.path.isdir(initial_dir):
                initial_dir = user_working_dir()
            output_path = filedialog.asksaveasfilename(
                parent=dialog,
                title="Export docking configuration",
                initialdir=initial_dir,
                initialfile=f"VLiP_v{APP_VERSION}_docking_configuration.txt",
                defaultextension=".txt",
                filetypes=[("Text file", "*.txt"), ("All files", "*.*")],
            )
            if not output_path:
                return
            try:
                with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(configuration_text.rstrip() + "\n")
                action_status_var.set(f"Exported: {output_path}")
            except Exception as exc:
                messagebox.showerror("Export failed", str(exc), parent=dialog)

        tk.Button(
            button_row,
            text="Copy Configuration",
            command=copy_configuration,
        ).pack(side="left")
        tk.Button(
            button_row,
            text="Export Configuration…",
            command=export_configuration,
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            button_row,
            textvariable=action_status_var,
            anchor="w",
        ).pack(side="left", padx=(10, 0), fill="x", expand=True)

        tk.Button(
            button_row,
            text="Go Back",
            width=16,
            command=lambda: close(False),
        ).pack(side="right", padx=(8, 0))
        confirm_button = tk.Button(
            button_row,
            text="CONFIRM AND RUN",
            width=20,
            bg="green",
            fg="white",
            command=lambda: close(True),
        )
        confirm_button.pack(side="right")
        dialog._vlip_theme_callback = lambda theme_dark: confirm_button.configure(
            bg="#207a3c" if theme_dark else "green",
            fg="white",
            activebackground="#2b9950" if theme_dark else "#159447",
            activeforeground="white",
        )

        dialog.protocol("WM_DELETE_WINDOW", lambda: close(False))
        dialog.bind("<Escape>", lambda _event: close(False))
        dialog.bind("<Control-Return>", lambda _event: close(True))
        dialog.update_idletasks()
        try:
            x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_width()) // 2)
            y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_height()) // 2)
            dialog.geometry(f"+{x}+{y}")
        except Exception:
            pass
        dialog.grab_set()
        confirm_button.focus_set()
        self.root.wait_window(dialog)
        return decision["confirmed"]

    def run_docking(self):
        if self.run_in_progress:
            return

        self._apply_configured_speed(source="pre-run", record=False)
        self.save_settings()

        vina = self.resolved_vina_path()
        outdir = self.outdir_var.get().strip()

        ligands_to_run = list(self.ligands) if self.ligands else []
        if not ligands_to_run:
            single_ligand = self.ligand_var.get().strip()
            if single_ligand:
                ligands_to_run = [single_ligand]

        if not vina or not outdir:
            messagebox.showerror("Error", "Missing Vina or output folder.")
            return

        if not ligands_to_run:
            messagebox.showerror("Error", "No ligand selected. Pick one ligand or add ligands to the queue.")
            return

        if not self.receptors:
            messagebox.showerror("Error", "No receptors loaded.")
            return

        if not os.path.exists(vina):
            messagebox.showerror("Error", f"Vina not found:\n{vina}")
            return

        bad_ligands = [lig for lig in ligands_to_run if not os.path.exists(lig)]
        if bad_ligands:
            messagebox.showerror(
                "Error",
                "These ligand files are missing:\n\n" + "\n".join(bad_ligands[:20])
            )
            return

        try:
            repeats = int(self.repeat_var.get())
            if repeats < 1:
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Repeats must be a positive integer.")
            return

        try:
            exhaustiveness_value = int(self.exhaust_var.get())
            if exhaustiveness_value < 1:
                raise ValueError
            exhaustiveness = str(exhaustiveness_value)
        except Exception:
            messagebox.showerror("Error", "Exhaustiveness must be a positive integer.")
            return

        try:
            normalize_plip_workers(self.plip_workers_var.get())            overrides = normalize_vina_options({k: v.get() for k, v in self.vina_option_vars.items()})
            if overrides:
                supported, _ = probe_vina_options(vina)
                missing = set(overrides) - supported
                if missing:
                    raise ValueError("Selected Vina executable did not advertise: " + ", ".join(sorted(missing)))
        except ValueError as exc:
            messagebox.showerror("Vina options", str(exc))
            return

        try:
            default_padding = float(self.padding_var.get())
            if default_padding <= 0:
                raise ValueError
        except Exception:
            messagebox.showerror("Error", "Default Padding must be a positive number.")
            return

        for ligand in ligands_to_run:
            ligand_ok, ligand_msg = validate_pdbqt(ligand, kind="ligand")
            if not ligand_ok:
                messagebox.showerror("Error", f"Ligand PDBQT sanity check failed:\n{ligand_msg}\n\n{ligand}")
                return

        for receptor in self.receptors:
            receptor_path = receptor.get("path", "")
            if not receptor_path or not os.path.exists(receptor_path):
                messagebox.showerror("Error", f"Receptor file is missing:\n{receptor_path or '(no path)'}")
                return
            receptor_ok, receptor_msg = validate_pdbqt(receptor_path, kind="receptor")
            if not receptor_ok:
                messagebox.showerror(
                    "Error",
                    f"Receptor PDBQT sanity check failed:\n{receptor_msg}\n\n{receptor_path}"
                )
                return

        total_jobs = len(ligands_to_run) * len(self.receptors) * repeats

        ligand_output_names = build_unique_output_names(ligands_to_run)
        receptors_copy = [dict(r) for r in self.receptors]
        receptor_output_names = build_unique_output_names(
            [r["path"] for r in receptors_copy],
            reserved_names={"pdb", "plip"}
        )
        for receptor in receptors_copy:
            receptor["output_name"] = receptor_output_names[normalized_path_key(receptor["path"])]

        run_config = self.build_run_config_snapshot(
            vina=vina,
            outdir=outdir,
            ligands_to_run=ligands_to_run,
            receptors_copy=receptors_copy,
            repeats=repeats,
            exhaustiveness=exhaustiveness,
            default_padding=default_padding,
            ligand_output_names=ligand_output_names
        )

        resume_from_job = 0
        existing_progress = self.load_docking_progress()
        if existing_progress and not existing_progress.get("completed", False):
            saved_next_job = int(existing_progress.get("next_job_index", 0) or 0)
            saved_total = int(existing_progress.get("total_jobs", 0) or 0)
            if saved_next_job > 0 and self.current_config_matches_progress(existing_progress, run_config):
                answer = messagebox.askyesno(
                    "Continue previous run?",
                    "A previous incomplete docking run was found.\n\n"
                    f"Progress: {saved_next_job} / {saved_total} jobs finished.\n\n"
                    "Do you want to continue from there?"
                )
                if answer:
                    resume_from_job = min(saved_next_job, total_jobs)
            elif saved_next_job > 0:
                messagebox.showwarning(
                    "Saved run does not match",
                    "An incomplete saved run exists, but it does not match the current ligand/receptor/settings setup.\n\n"
                    "This run will start from the beginning and overwrite the saved progress file."
                )

        args = {
            "vina": vina,
            "outdir": outdir,
            "ligands_to_run": ligands_to_run,
            "receptors": receptors_copy,
            "repeats": repeats,
            "total_jobs": total_jobs,
            "exhaustiveness": exhaustiveness,
            "vina_options": dict(run_config["vina_options"]),
            "default_padding": default_padding,
            "save_merge": bool(self.merge_var.get()),
            "save_pdb": bool(self.pdb_var.get()),
            "save_txt": bool(self.txt_var.get()),
            "run_plip": bool(self.plip_var.get()),
            "plip_workers": normalize_plip_workers(self.plip_workers_var.get()),
            "ligand_output_names": ligand_output_names,
            "run_config": run_config,
            "resume_from_job": resume_from_job,
            "experiment_notes": str(run_config.get("experiment_notes") or ""),
            "performance_mode_at_start": self.active_speed_mode,
            "performance_schedule": self._schedule_description(),
        }

        estimated_seconds, estimate_samples = self._historical_run_estimate(args)
        args["estimated_seconds"] = estimated_seconds
        args["estimate_samples"] = estimate_samples

        try:
            self.root.config(cursor="watch")
            self.root.update_idletasks()
            software_versions = self._software_version_details(args)
        finally:
            try:
                self.root.config(cursor="")
            except Exception:
                pass

        if not self._confirm_pre_run_summary(args, software_versions):
            return

        # The review dialog can remain open across a scheduled boundary, so
        # capture the actual performance state again at the moment the run starts.
        args["performance_mode_at_start"] = self.active_speed_mode
        args["performance_schedule"] = self._schedule_description()
        self.active_run_outdir = outdir
        self._record_performance_event(
            "run start",
            f"{self._speed_profile_text(self.active_speed_mode)}; schedule: {self._schedule_description()}",
        )
        self._remember_recent_project(outdir, status="starting")
        self.checkpoint_write_errors = []
        self.run_in_progress = True
        self.pause_event.clear()
        self.cancel_event.clear()
        self.stop_after_receptor_event.clear()

        self.set_controls_enabled(False)

        try:
            self.root.config(cursor="watch")
        except Exception:
            pass

        self.overlay = ProgressOverlay(
            self.root,
            pause_callback=self.on_pause_resume_clicked,
            cancel_callback=self.on_cancel_clicked,
            stop_after_receptor_callback=self.on_stop_after_receptor_clicked,
            speed_change_callback=self.on_overlay_speed_change,
            schedule_change_callback=self.on_overlay_schedule_change,
            initial_speed_mode=self.active_speed_mode,
            initial_schedule_enabled=bool(self.speed_schedule_enabled_var.get()),
            initial_schedule_start=self.speed_schedule_start_var.get().strip(),
            initial_schedule_end=self.speed_schedule_end_var.get().strip(),
            initial_speed_status=self.last_speed_apply_summary,
            initial_current=resume_from_job,
            initial_estimated_seconds=estimated_seconds,
        )
        self.overlay.set_paused(False)
        self.overlay.set_stop_after_receptor_requested(False)
        self.overlay.update_progress(
            resume_from_job,
            total_jobs,
            status=("Preparing resumed run..." if resume_from_job else "Preparing run..."),
            ligand=f"{len(ligands_to_run)} queued",
            receptor=f"{len(receptors_copy)} receptors loaded",
            run_text=f"Repeats: {repeats}"
        )
        self.root.update_idletasks()

        self.worker_thread = threading.Thread(
            target=self._run_docking_worker,
            args=(args,),
            daemon=True
        )
        self.worker_thread.start()
        self.start_progress_poll()

    # ----------------------
    # Worker helpers
    # ----------------------
    def _read_best_vina_affinity(self, path):
        best = None
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not line.startswith("REMARK VINA RESULT:"):
                        continue
                    try:
                        value = float(line.split()[3])
                    except (IndexError, ValueError):
                        continue
                    if best is None or value < best:
                        best = value
        except OSError:
            return None
        return best

    def _read_plip_summary_score(self, path):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    match = re.search(r"vina score:\s*([^\s]+)", line, flags=re.IGNORECASE)
                    if match:
                        try:
                            return float(match.group(1))
                        except ValueError:
                            return None
        except OSError:
            pass
        return None

    def _load_existing_aggregate_entries(self, args):
        """Rebuild combined-report rows for jobs skipped by a resumed run."""
        resume_limit = int(args.get("resume_from_job", 0) or 0)
        docking_entries = []
        plip_entries = []
        if resume_limit <= 0:
            return plip_entries, docking_entries

        job_index = 0
        ligand_names = args.get("ligand_output_names") or {}
        for ligand in args["ligands_to_run"]:
            ligand_name = ligand_names.get(normalized_path_key(ligand), safe_output_stem(ligand))
            ligand_folder = os.path.join(args["outdir"], ligand_name)
            for receptor in args["receptors"]:
                receptor_name = receptor.get("output_name") or safe_output_stem(
                    receptor.get("name", receptor.get("path", "receptor"))
                )
                base = os.path.join(ligand_folder, receptor_name)
                for run_index in range(1, int(args["repeats"]) + 1):
                    if job_index >= resume_limit:
                        return plip_entries, docking_entries

                    run_dir = os.path.join(base, f"run_{run_index}")
                    dock_out = existing_dock_output_path(
                        run_dir, ligand_name, receptor_name, run_index
                    )
                    affinity = self._read_best_vina_affinity(dock_out)
                    if affinity is not None:
                        docking_entries.append({
                            "ligand": ligand_name,
                            "receptor": receptor_name,
                            "run": run_index,
                            "affinity": affinity,
                            "output_file": os.path.basename(dock_out),
                            "dock_pdbqt": dock_out,
                        })

                    if args.get("run_plip"):
                        organized_plip_dir = os.path.join(
                            ligand_folder, "plip", receptor_name, f"run_{run_index}"
                        )
                        legacy_plip_dir = os.path.join(run_dir, "plip")
                        plip_dir = next(
                            (path for path in (organized_plip_dir, legacy_plip_dir) if os.path.isdir(path)),
                            organized_plip_dir
                        )
                        summary_paths = preferred_pose_plip_summaries(plip_dir)
                        for summary_path in summary_paths:
                            pose_number = molecular_plip_pose_number(summary_path)
                            pose_name = f"pose{pose_number}" if pose_number is not None else os.path.basename(summary_path)
                            plip_entries.append({
                                "ligand": ligand_name,
                                "receptor": receptor_name,
                                "run": run_index,
                                "pose": pose_name,
                                "vina_score": self._read_plip_summary_score(summary_path),
                                "path": summary_path,
                            })
                    job_index += 1

        return plip_entries, docking_entries

    def _run_docking_worker(self, args):
        completed_jobs = 0
        completed_ligands = 0
        global_plip_entries = []
        global_docking_entries = []
        last_runlog = None

        try:
            resume_from_job = int(args.get("resume_from_job", 0) or 0)
            if resume_from_job:
                global_plip_entries, global_docking_entries = self._load_existing_aggregate_entries(args)
            else:
                removed = remove_generated_files(args["outdir"], [
                    "all ligands docking scores.txt",
                    "all ligands plip.txt",
                    HTML_REPORT_FILENAME,
                    COMPLETE_SETTINGS_FILENAME,
                ])
                receptor_reports = os.path.join(args["outdir"], "receptor_reports")
                removed.extend(remove_generated_files(receptor_reports, ["all ligands plip - *.txt"]))
                if removed:
                    project_log_line(
                        args["outdir"],
                        f"fresh run removed {len(removed)} stale generated aggregate file(s)",
                    )
            self.save_worker_progress(
                args,
                resume_from_job,
                status=("resumed" if resume_from_job else "started")
            )
            try:
                settings_record = self._write_complete_settings_record(args, include_job_records=False)
                project_log_line(args["outdir"], f"complete settings record started: {settings_record}")
            except Exception as exc:
                project_log_line(args["outdir"], f"failed to start complete settings record: {exc}")

            for ligand in args["ligands_to_run"]:
                last_runlog, completed_jobs = self._process_single_ligand(
                    args=args,
                    ligand=ligand,
                    completed_jobs=completed_jobs,
                    global_plip_entries=global_plip_entries,
                    global_docking_entries=global_docking_entries
                )
                completed_ligands += 1

            if args["run_plip"]:
                self._write_top_level_plip_summary(
                    outdir=args["outdir"],
                    ligands_to_run=args["ligands_to_run"],
                    global_plip_entries=global_plip_entries
                )

            self._write_top_level_docking_summary(
                outdir=args["outdir"],
                ligands_to_run=args["ligands_to_run"],
                global_docking_entries=global_docking_entries
            )

            try:
                settings_record = self._write_complete_settings_record(args, include_job_records=True)
                project_log_line(args["outdir"], f"complete settings record finalized: {settings_record}")
            except Exception as exc:
                project_log_line(args["outdir"], f"failed to finalize complete settings record: {exc}")

            progress = self.load_docking_progress() or {}
            statuses = [
                str(item.get("status", "")).upper()
                for item in (progress.get("job_statuses") or {}).values()
                if isinstance(item, dict)
            ]
            failed_count = statuses.count("FAILED")
            skipped_count = statuses.count("SKIPPED")
            partial_count = statuses.count("PARTIAL")
            issue_count = failed_count + skipped_count + partial_count
            checkpoint_error_count = len(getattr(self, "checkpoint_write_errors", []) or [])
            final_status = "completed_with_issues" if (issue_count or checkpoint_error_count) else "completed"
            self.save_worker_progress(args, args["total_jobs"], status=final_status)
            checkpoint_error_count = len(getattr(self, "checkpoint_write_errors", []) or [])
            try:
                html_report = self._generate_html_project_report(
                    args["outdir"], os.path.join(args["outdir"], HTML_REPORT_FILENAME)
                )
                project_log_line(args["outdir"], f"HTML project report written: {html_report}")
            except Exception as exc:
                project_log_line(args["outdir"], f"HTML project report failed: {exc}")

            self.post_progress(
                args["total_jobs"],
                args["total_jobs"],
                status=("Finished with issues" if issue_count else "Finished"),
                ligand=f"{completed_ligands}/{len(args['ligands_to_run'])} ligands processed",
                receptor=(f"{issue_count} job(s) need attention" if issue_count else "Done"),
                run_text=("Review results" if issue_count else "Complete")
            )

            if issue_count or checkpoint_error_count:
                checkpoint_note = ""
                if checkpoint_error_count:
                    checkpoint_note = (
                        f"\nCheckpoint write warnings: {checkpoint_error_count}\n"
                        "The docking run continued, but resume/progress files may be incomplete. "
                        "See logs/vlip_run.log for details.\n"
                    )
                self.post_done(
                    "warning",
                    "Completed with issues",
                    "Docking reached the end, but not every part completed cleanly.\n\n"
                    f"Failed: {failed_count}\nSkipped: {skipped_count}\n"
                    f"Docked but PLIP incomplete: {partial_count}\n"
                    f"{checkpoint_note}\n"
                    f"Output folder:\n{args['outdir']}",
                    project_dir=args["outdir"],
                    auto_show_poses=True,
                )
            else:
                self.post_done(
                    "info",
                    "Done",
                    f"Docking finished.\n\nLigands processed: {completed_ligands}/{len(args['ligands_to_run'])}\nOutput folder:\n{args['outdir']}",
                    project_dir=args["outdir"],
                    auto_show_poses=True,
                )

        except RunStoppedAfterReceptor as e:
            try:
                self.save_worker_progress(args, completed_jobs, status="stopped")
                if last_runlog:
                    log_line(last_runlog, f"[INFO] Graceful stop requested: {e}")
            except Exception:
                pass

            self.post_done(
                "info",
                "Stopped",
                f"Run stopped cleanly after current receptor.\n\n{e}"
            )

        except RunCancelled:
            try:
                self.save_worker_progress(args, completed_jobs, status="cancelled")
                if last_runlog:
                    log_line(last_runlog, f"[INFO] Run cancelled by user at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception:
                pass

            self.post_done("info", "Cancelled", "Docking run cancelled.")

        except Exception:
            try:
                self.save_worker_progress(args, completed_jobs, status="failed")
                if last_runlog:
                    log_line(last_runlog, "[FATAL] Unhandled exception:\n" + traceback.format_exc())
            except Exception:
                pass

            self.post_done("error", "Docking failed", traceback.format_exc())

    def _process_single_ligand(self, args, ligand, completed_jobs, global_plip_entries, global_docking_entries):
        ligand_name = (args.get("ligand_output_names") or {}).get(
            normalized_path_key(ligand), safe_output_stem(ligand)
        )
        ligand_folder = os.path.join(args["outdir"], ligand_name)
        os.makedirs(ligand_folder, exist_ok=True)

        runlog = os.path.join(ligand_folder, "runlog.txt")

        log_line(runlog, f"=== START {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        log_line(runlog, f"Python: {sys.version}")
        log_line(runlog, f"Vina: {args['vina']}")
        log_line(runlog, f"Ligand: {ligand}")
        log_line(runlog, f"Total queued ligands: {len(args['ligands_to_run'])}")
        log_line(runlog, f"Total receptor x repeat jobs for this ligand: {len(args['receptors']) * args['repeats']}")
        log_line(runlog, f"Grand total jobs this run: {args['total_jobs']}")

        w = warn_path_len("ligand_folder", ligand_folder)
        if w:
            log_line(runlog, w)

        final_summary_file = os.path.join(ligand_folder, "all_runs_summary.txt")
        if int(args.get("resume_from_job", 0) or 0) > 0 and os.path.exists(final_summary_file):
            try:
                with open(final_summary_file, "r", encoding="utf-8", errors="replace") as f:
                    final_summary_lines = [line for line in f if not line.startswith("# ")]
                if not final_summary_lines:
                    final_summary_lines = ["Receptor\tRun\tAffinity (kcal/mol)\tOutput File\n"]
            except Exception:
                final_summary_lines = ["Receptor\tRun\tAffinity (kcal/mol)\tOutput File\n"]
        else:
            final_summary_lines = ["Receptor\tRun\tAffinity (kcal/mol)\tOutput File\n"]

        for receptor in args["receptors"]:
            completed_jobs = self._process_single_receptor(
                args=args,
                ligand=ligand,
                ligand_name=ligand_name,
                ligand_folder=ligand_folder,
                receptor=receptor,
                runlog=runlog,
                final_summary_lines=final_summary_lines,
                completed_jobs=completed_jobs,
                global_plip_entries=global_plip_entries,
                global_docking_entries=global_docking_entries
            )

            receptor_name = receptor.get("output_name") or safe_output_stem(receptor.get("name", receptor["path"]))
            self.check_stop_after_receptor_boundary(runlog, ligand_name, receptor_name)

        with open(final_summary_file, "w", encoding="utf-8") as f:
            f.writelines(final_summary_lines)
            f.write("".join("# " + line + "\n" for line in self._vina_report_text(ligand_folder).splitlines()))

        if args.get("run_plip"):
            self._write_single_ligand_plip_summary(
                ligand_folder=ligand_folder,
                ligand_name=ligand_name,
                global_plip_entries=global_plip_entries,
                runlog=runlog,
            )

        log_line(runlog, f"=== END {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        return runlog, completed_jobs

    def _prepare_receptor_context(self, receptor, default_padding, runlog):
        receptor_name = receptor.get("output_name") or safe_output_stem(receptor.get("name", receptor["path"]))

        if not os.path.exists(receptor["path"]):
            log_line(runlog, f"[ERROR] Receptor missing: {receptor['path']}")
            return False, {"reason": "missing receptor", "receptor_name": receptor_name}

        rec_ok, rec_msg = validate_pdbqt(receptor["path"], kind=f"receptor {receptor_name}")
        if not rec_ok:
            log_line(runlog, f"[ERROR] Receptor sanity check failed: {rec_msg} -> {receptor['path']}")
            return False, {"reason": "invalid receptor", "receptor_name": receptor_name}

        atoms = parse_atoms(receptor["path"])
        if not atoms:
            log_line(runlog, f"[ERROR] No atoms parsed from receptor: {receptor['path']}")
            return False, {"reason": "no atoms", "receptor_name": receptor_name}

        try:
            padding = float(receptor["padding"]) if receptor["padding"] else default_padding
            if padding <= 0:
                raise ValueError
        except Exception:
            log_line(runlog, f"[ERROR] Invalid padding for {receptor_name}: {receptor['padding']}")
            return False, {"reason": "bad padding", "receptor_name": receptor_name}

        requested_mode = str(receptor.get("mode", "")).strip()
        if requested_mode not in {"Whole", "Active"}:
            log_line(runlog, f"[ERROR] Invalid docking mode for {receptor_name}: {requested_mode or '(blank)'}")
            return False, {
                "reason": "invalid docking mode",
                "receptor_name": receptor_name,
                "job_status": "FAILED",
            }

        box_atoms = atoms
        effective_mode = "Whole"
        if requested_mode == "Active":
            try:
                box_atoms = select_active_residue_atoms(atoms, receptor.get("residues", ""))
            except ValueError as exc:
                log_line(
                    runlog,
                    f"[ERROR] Invalid active-residue selection for {receptor_name}: {exc}. "
                    "Refusing to change the requested experiment to whole-receptor docking."
                )
                return False, {
                    "reason": f"invalid active-residue selection: {exc}",
                    "receptor_name": receptor_name,
                    "job_status": "FAILED",
                }
            effective_mode = "Active"

        try:
            cx, cy, cz, sx, sy, sz, *_ = box_from_atoms(box_atoms, padding)
        except Exception as ex:
            log_line(runlog, f"[ERROR] Failed to build docking box for {receptor_name}: {ex}")
            return False, {"reason": "bad docking box", "receptor_name": receptor_name}

        return True, {
            "receptor_name": receptor_name,
            "atoms": atoms,
            "box_atom_count": len(box_atoms),
            "effective_mode": effective_mode,
            "padding": padding,
            "center": (cx, cy, cz),
            "size": (sx, sy, sz),
        }

    def _process_single_receptor(self, args, ligand, ligand_name, ligand_folder,
                                 receptor, runlog, final_summary_lines,
                                 completed_jobs, global_plip_entries,
                                 global_docking_entries):
        receptor_basename = os.path.basename(receptor["path"])

        self.wait_if_paused_or_cancelled(
            completed_jobs, args["total_jobs"],
            "Waiting to start receptor...",
            os.path.basename(ligand),
            receptor_basename,
            "-"
        )

        ok, ctx = self._prepare_receptor_context(receptor, args["default_padding"], runlog)
        if not ok:
            terminal_status = str(ctx.get("job_status", "SKIPPED") or "SKIPPED").upper()
            for repeat_offset in range(args["repeats"]):
                skipped_job = completed_jobs + repeat_offset
                self.update_job_status(args, skipped_job, terminal_status, {
                    "ligand": ligand,
                    "ligand_name": ligand_name,
                    "receptor": receptor.get("path", ""),
                    "receptor_name": ctx.get("receptor_name", receptor_basename),
                    "run_index": repeat_offset + 1,
                    "reason": ctx.get("reason", "receptor preparation failed"),
                })
            completed_jobs += args["repeats"]
            self.save_worker_progress(args, completed_jobs, status="running")
            self.post_progress(
                completed_jobs,
                args["total_jobs"],
                status=f"Skipping {ctx['reason']}...",
                ligand=os.path.basename(ligand),
                receptor=receptor_basename,
                run_text="-"
            )
            return completed_jobs

        receptor_name = ctx["receptor_name"]

        base = os.path.join(ligand_folder, receptor_name)
        os.makedirs(base, exist_ok=True)

        summary_folder = os.path.join(base, "summary")
        os.makedirs(summary_folder, exist_ok=True)

        for i in range(args["repeats"]):
            completed_jobs = self._run_single_receptor_job(
                args=args,
                ligand=ligand,
                ligand_name=ligand_name,
                receptor=receptor,
                receptor_name=receptor_name,
                base=base,
                summary_folder=summary_folder,
                runlog=runlog,
                final_summary_lines=final_summary_lines,
                completed_jobs=completed_jobs,
                run_index=i + 1,
                job_index=completed_jobs,
                center=ctx["center"],
                size=ctx["size"],
                effective_mode=ctx.get("effective_mode", receptor.get("mode", "Whole")),
                effective_padding=ctx["padding"],
                global_plip_entries=global_plip_entries,
                global_docking_entries=global_docking_entries
            )

        return completed_jobs

    def _run_single_receptor_job(self, args, ligand, ligand_name, receptor, receptor_name,
                                 base, summary_folder, runlog, final_summary_lines,
                                 completed_jobs, run_index, job_index, center, size,
                                 effective_mode, effective_padding,
                                 global_plip_entries, global_docking_entries):
        receptor_basename = os.path.basename(receptor["path"])

        if completed_jobs < int(args.get("resume_from_job", 0) or 0):
            return completed_jobs + 1

        job_started = time.time()
        cx, cy, cz = center
        sx, sy, sz = size
        job_detail = {
            "ligand": ligand,
            "ligand_name": ligand_name,
            "receptor": receptor.get("path", ""),
            "receptor_name": receptor_name,
            "run_index": run_index,
            "center": {"x": cx, "y": cy, "z": cz},
            "size": {"x": sx, "y": sy, "z": sz},
            "mode": receptor.get("mode", ""),
            "effective_mode": effective_mode,
            "residues": receptor.get("residues", ""),
            "padding": effective_padding,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }

        def finished_detail(extra=None):
            return {
                **job_detail,
                **dict(extra or {}),
                "duration_seconds": round(max(0.0, time.time() - job_started), 3),
            }

        self.save_worker_progress(
            args,
            completed_jobs,
            status="running",
            last_position={"job_index": completed_jobs, **job_detail}
        )
        self.update_job_status(args, job_index, "RUNNING", job_detail)

        self.wait_if_paused_or_cancelled(
            completed_jobs, args["total_jobs"],
            "Waiting to start run...",
            os.path.basename(ligand),
            receptor_basename,
            f"{run_index}/{args['repeats']}"
        )

        self.post_progress(
            completed_jobs,
            args["total_jobs"],
            status="Running docking...",
            ligand=os.path.basename(ligand),
            receptor=receptor_basename,
            run_text=f"{run_index}/{args['repeats']}"
        )

        run_dir = os.path.join(base, f"run_{run_index}")
        dock_dir = os.path.join(run_dir, "dock")
        pose_dir = os.path.join(run_dir, "poses")
        merged_dir = os.path.join(run_dir, "merged")
        ligand_folder = os.path.dirname(base)
        pdb_dir = os.path.join(ligand_folder, "pdb", receptor_name, f"run_{run_index}")
        plip_dir = os.path.join(ligand_folder, "plip", receptor_name, f"run_{run_index}")

        # This job is about to run (completed resume jobs returned above), so remove
        # only its prior generated artefacts. Otherwise a rerun that produces fewer
        # poses can silently retain and report pose files from an older experiment.
        removed = []
        removed.extend(remove_generated_files(dock_dir, ["dock.pdbqt", "*.pdbqt"]))
        removed.extend(remove_generated_files(pose_dir, ["pose*.pdbqt"]))
        removed.extend(remove_generated_files(merged_dir, ["pose*_merged.pdbqt"]))
        removed.extend(remove_generated_files(pdb_dir, ["pose*.pdb"]))
        removed.extend(remove_generated_files(plip_dir, [
            "pose*",
            "all_poses_unl_summary.txt",
            JOB_SETTINGS_FILENAME,
        ]))
        removed.extend(remove_generated_files(summary_folder, [
            f"run{run_index}_summary.txt",
            f"vina_error_*_run{run_index}.log",
            f"postprocess_error_run{run_index}.log",
        ]))
        if removed:
            log_line(runlog, f"[INFO] Removed {len(removed)} stale generated file(s) for this job.")

        for d in (dock_dir, pose_dir, merged_dir):
            os.makedirs(d, exist_ok=True)
        if args["save_pdb"]:
            os.makedirs(pdb_dir, exist_ok=True)
        if args["run_plip"]:
            os.makedirs(plip_dir, exist_ok=True)

        dock_out = compact_dock_output_path(run_dir)

        for label, pth in [("receptor", receptor["path"]), ("ligand", ligand), ("dock_out", dock_out)]:
            w = warn_path_len(label, pth)
            if w:
                log_line(runlog, w)

        cx, cy, cz = center
        sx, sy, sz = size

        cmd = [
            args["vina"],
            "--receptor", receptor["path"],
            "--ligand", ligand,
            "--center_x", str(cx),
            "--center_y", str(cy),
            "--center_z", str(cz),
            "--size_x", str(sx),
            "--size_y", str(sy),
            "--size_z", str(sz),
            "--exhaustiveness", args["exhaustiveness"],
            "--out", dock_out
        ]
        cmd.extend(vina_option_arguments(args.get("vina_options")))
        job_settings_record = None
        try:
            job_settings_record = self._write_job_settings_record(
                args=args,
                ligand=ligand,
                ligand_name=ligand_name,
                receptor=receptor,
                receptor_name=receptor_name,
                run_index=run_index,
                job_index=job_index,
                center=center,
                size=size,
                effective_mode=effective_mode,
                effective_padding=effective_padding,
                vina_cmd=cmd,
                plip_dir=plip_dir,
            )
            log_line(runlog, f"[INFO] Wrote exact job settings: {job_settings_record}")
        except Exception as exc:
            log_line(runlog, f"[ERROR] Failed writing exact job settings: {exc}")

        log_line(runlog, f"\n[RUN] {receptor_name} run {run_index}")
        log_line(runlog, "CMD: " + " ".join(cmd))

        try:
            stdout, stderr = self.run_tracked_subprocess(cmd, live_stage="VINA")
            if stdout:
                log_line(runlog, "[VINA STDOUT] " + stdout.strip().replace("\n", "\n[VINA STDOUT] "))
            if stderr:
                log_line(runlog, "[VINA STDERR] " + stderr.strip().replace("\n", "\n[VINA STDERR] "))
            if job_settings_record:
                reported = "\n".join(part for part in (stdout, stderr) if part)
                seed_match = re.search(r"(?im)random\s+seed\s*[:=]\s*(-?\d+)", reported)
                if seed_match:
                    log_line(job_settings_record, f"Actual Vina random seed reported: {seed_match.group(1)}")
                else:
                    log_line(job_settings_record, "Actual Vina random seed reported: NOT FOUND IN VINA OUTPUT")
                log_line(job_settings_record, "Vina exit status: SUCCESS")
        except RunCancelled:
            log_line(runlog, f"[INFO] Cancelled during Vina run for {receptor_name} run {run_index}")
            if job_settings_record:
                log_line(job_settings_record, "Vina exit status: CANCELLED")
            raise
        except subprocess.CalledProcessError as e:
            errlog = os.path.join(summary_folder, f"vina_error_{receptor_name}_run{run_index}.log")
            with open(errlog, "w", encoding="utf-8", errors="replace") as f:
                f.write("CMD:\n" + " ".join(e.cmd) + "\n\n")
                f.write("STDOUT:\n" + (e.output or "") + "\n\n")
                f.write("STDERR:\n" + (e.stderr or "") + "\n")
            log_line(runlog, f"[ERROR] Vina failed for {receptor_name} run {run_index}. See: {errlog}")
            if job_settings_record:
                log_line(job_settings_record, f"Vina exit status: FAILED (return code {e.returncode})")
                log_line(job_settings_record, f"Vina error log: {errlog}")
            self.update_job_status(args, job_index, "FAILED", finished_detail({"reason": "Vina failed", "error_log": errlog}))

            completed_jobs += 1
            self.save_worker_progress(args, completed_jobs, status="running")
            self.post_progress(
                completed_jobs,
                args["total_jobs"],
                status="Run failed, continuing..." + self._current_eta_suffix(),
                ligand=os.path.basename(ligand),
                receptor=receptor_basename,
                run_text=f"{run_index}/{args['repeats']}"
            )
            return completed_jobs

        if not wait_for_stable_file(dock_out, timeout_s=30.0, stable_window_s=0.5, cancel_event=self.cancel_event):
            log_line(runlog, f"[ERROR] Docking output not stable/found for {receptor_name} run {run_index}: {dock_out}")
            if job_settings_record:
                log_line(job_settings_record, "Docking output validation: FAILED (output missing or unstable)")
            self.update_job_status(args, job_index, "FAILED", finished_detail({"reason": "Docking output missing or unstable", "dock_out": dock_out}))
            completed_jobs += 1
            self.save_worker_progress(args, completed_jobs, status="running")
            self.post_progress(
                completed_jobs,
                args["total_jobs"],
                status="Output missing/unstable, continuing..." + self._current_eta_suffix(),
                ligand=os.path.basename(ligand),
                receptor=receptor_basename,
                run_text=f"{run_index}/{args['repeats']}"
            )
            return completed_jobs

        out_ok, out_msg = validate_pdbqt(
            dock_out,
            kind=f"dock_out {receptor_name} run {run_index}",
            require_vina_output=True
        )
        if not out_ok:
            log_line(runlog, f"[ERROR] Output sanity check failed: {out_msg} -> {dock_out}")
            if job_settings_record:
                log_line(job_settings_record, f"Docking output validation: FAILED ({out_msg})")
            self.update_job_status(args, job_index, "FAILED", finished_detail({"reason": out_msg, "dock_out": dock_out}))
            completed_jobs += 1
            self.save_worker_progress(args, completed_jobs, status="running")
            self.post_progress(
                completed_jobs,
                args["total_jobs"],
                status="Bad output file, continuing..." + self._current_eta_suffix(),
                ligand=os.path.basename(ligand),
                receptor=receptor_basename,
                run_text=f"{run_index}/{args['repeats']}"
            )
            return completed_jobs

        if job_settings_record:
            log_line(job_settings_record, "Docking output validation: PASSED")
            log_line(job_settings_record, f"Docking output file: {dock_out}")

        log_line(runlog, "[INFO] Using compact docking/post-processing paths (v1.40 hardening).")

        try:
            postprocess = self.split_merge_convert(
                dock_pdbqt=dock_out,
                receptor_pdbqt=receptor["path"],
                ligand_name=ligand_name,
                receptor_name=receptor_name,
                run=run_index,
                pose_dir=pose_dir,
                merged_dir=merged_dir,
                pdb_dir=pdb_dir,
                plip_dir=plip_dir,
                summary_folder=summary_folder,
                final_summary_lines=final_summary_lines,
                run_dir=run_dir,
                runlog=runlog,
                save_merge=args["save_merge"],
                save_pdb=args["save_pdb"],
                save_txt=args["save_txt"],
                run_plip=args["run_plip"],
                plip_workers=args.get("plip_workers", 2),
                job_settings_record=job_settings_record,
                global_plip_entries=global_plip_entries,
                global_docking_entries=global_docking_entries
            )
        except RunCancelled:
            raise
        except Exception as exc:
            errlog = os.path.join(summary_folder, f"postprocess_error_run{run_index}.log")
            try:
                with open(errlog, "w", encoding="utf-8", errors="replace") as f:
                    f.write(f"Post-processing failed for {receptor_name} run {run_index}:\n{exc}\n\n")
                    f.write(traceback.format_exc())            except Exception:
                errlog = ""
            log_line(
                runlog,
                f"[ERROR] Post-processing failed for {receptor_name} run {run_index}; "
                "marking only this job FAILED and continuing." + (f" See: {errlog}" if errlog else "")
            )
            if job_settings_record:
                log_line(job_settings_record, f"Post-processing exit status: FAILED ({exc})")
                if errlog:
                    log_line(job_settings_record, f"Post-processing error log: {errlog}")
            self.update_job_status(args, job_index, "FAILED", finished_detail({
                "dock_out": dock_out,
                "reason": f"Post-processing failed: {exc}",
                "error_log": errlog,
            }))
            completed_jobs += 1
            self.save_worker_progress(args, completed_jobs, status="running")
            self.post_progress(
                completed_jobs,
                args["total_jobs"],
                status="Docked; post-processing failed, continuing..." + self._current_eta_suffix(),
                ligand=os.path.basename(ligand),
                receptor=receptor_basename,
                run_text=f"{run_index}/{args['repeats']}"
            )
            return completed_jobs

        plip_failures = int((postprocess or {}).get("plip_failures", 0) or 0)
        if args["run_plip"] and plip_failures:
            self.update_job_status(args, job_index, "PARTIAL", finished_detail({
                "dock_out": dock_out,
                "reason": f"PLIP failed for {plip_failures} pose(s)",
                "plip_attempts": int((postprocess or {}).get("plip_attempts", 0) or 0),
                "plip_failures": plip_failures,
            }))
        else:
            self.update_job_status(args, job_index, "COMPLETE", finished_detail({"dock_out": dock_out}))

        completed_jobs += 1
        self.save_worker_progress(args, completed_jobs, status="running")
        self.post_progress(
            completed_jobs,
            args["total_jobs"],
            status=("Docked; PLIP incomplete" if plip_failures else "Completed run") + self._current_eta_suffix(),
            ligand=os.path.basename(ligand),
            receptor=receptor_basename,
            run_text=f"{run_index}/{args['repeats']}"
        )

        return completed_jobs

    def _vina_report_text(self, folder):
        current = os.path.abspath(folder)
        while True:
            path = os.path.join(current, COMPLETE_SETTINGS_FILENAME)
            if os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as source:
                    return "\n".join(line for line in source.read().split("EXPERIMENT NOTES", 1)[0].splitlines() if line.startswith(("Vina ", "Scoring:", "A fixed nonzero", "CPU threads"))) + "\n"
            parent = os.path.dirname(current)
            if parent == current:
                return "Vina settings record unavailable.\n"
            current = parent

    def _safe_report_filename_part(self, value):
        """Return a Windows-safe filename fragment for generated summary reports."""
        value = str(value or "UNKNOWN").strip()
        value = re.sub(r'[<>:"/\\|?*]+', "_", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value[:120] if value else "UNKNOWN"

    def _format_vina_score(self, score):
        """Format a per-pose Vina affinity without unnecessary trailing zeroes."""
        if score is None:
            return "N/A"
        try:
            return f"{float(score):.3f}".rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return str(score).strip() or "N/A"

    def _write_single_ligand_plip_summary(self, ligand_folder, ligand_name,
                                          global_plip_entries, runlog):
        """Write one combined PLIP report inside this ligand's own PLIP tree."""
        plip_root = os.path.join(ligand_folder, "plip")
        report_path = os.path.join(plip_root, f"{ligand_name}_all_plip.txt")
        deduped = {}
        for entry in global_plip_entries:
            if entry.get("ligand") != ligand_name:
                continue
            key = (entry.get("receptor"), entry.get("run"), entry.get("pose"))
            deduped[key] = entry
        entries = list(deduped.values())

        try:
            os.makedirs(plip_root, exist_ok=True)
            with open(report_path, "w", encoding="utf-8") as out:
                out.write(self._vina_report_text(ligand_folder))
                out.write("#" * 100 + "\n")
                out.write(f"PLIP REPORT FOR LIGAND: {ligand_name}\n")
                out.write("Includes all receptors, runs and poses for this ligand.\n")
                out.write("#" * 100 + "\n\n")

                if not entries:
                    out.write("No PLIP summaries were generated for this ligand.\n")
                else:
                    for i, entry in enumerate(entries, 1):
                        try:
                            with open(entry["path"], "r", encoding="utf-8", errors="replace") as f:
                                text = f.read().strip()
                        except Exception as e:
                            text = f"[ERROR READING SUMMARY: {e}]"

                        out.write("=" * 100 + "\n")
                        out.write(f"Ligand: {entry['ligand']}\n")
                        out.write(f"Receptor: {entry['receptor']}\n")
                        out.write(f"Run: {entry['run']}\n")
                        score_text = self._format_vina_score(entry.get("vina_score"))
                        out.write(f"Pose: {entry['pose']}  vina score:{score_text} kcal/mol\n")
                        out.write("=" * 100 + "\n")
                        out.write(text + "\n")
                        if i != len(entries):
                            out.write("\n\n")

            log_line(runlog, f"[INFO] Wrote per-ligand PLIP summary: {report_path}")
            return report_path
        except Exception as e:
            log_line(runlog, f"[ERROR] Failed writing per-ligand PLIP summary: {e}")
            return None

    def _write_top_level_plip_summary(self, outdir, ligands_to_run, global_plip_entries):
        top_plip_file = os.path.join(outdir, "all ligands plip.txt")
        deduped = {}
        for entry in global_plip_entries:
            key = (entry.get("ligand"), entry.get("receptor"), entry.get("run"), entry.get("pose"))
            deduped[key] = entry
        global_plip_entries = list(deduped.values())
        ligand_output_names = build_unique_output_names(ligands_to_run)

        try:
            # Original full all-ligand PLIP dump.
            with open(top_plip_file, "w", encoding="utf-8") as out:
                out.write(self._vina_report_text(outdir))
                if not global_plip_entries:
                    out.write("No PLIP summaries were generated.\n")
                else:
                    for i, entry in enumerate(global_plip_entries, 1):
                        with open(entry["path"], "r", encoding="utf-8", errors="replace") as f:
                            text = f.read().strip()

                        out.write("=" * 100 + "\n")
                        out.write(f"Ligand: {entry['ligand']}\n")
                        out.write(f"Receptor: {entry['receptor']}\n")
                        out.write(f"Run: {entry['run']}\n")
                        score_text = self._format_vina_score(entry.get("vina_score"))
                        out.write(f"Pose: {entry['pose']}  vina score:{score_text} kcal/mol\n")
                        out.write("=" * 100 + "\n")
                        out.write(text + "\n")

                        if i != len(global_plip_entries):
                            out.write("\n\n")

            # Separate per-receptor reports in a dedicated project-level folder.
            # Move reports produced by v1.26 out of the project root as a one-time migration.
            per_receptor_files = []
            receptor_report_dir = os.path.join(outdir, "receptor plip reports")
            try:
                legacy_names = [
                    name for name in os.listdir(outdir)
                    if name.lower().startswith("all ligands plip - ")
                    and name.lower().endswith(".txt")
                ]
            except OSError:
                legacy_names = []
            if legacy_names:
                os.makedirs(receptor_report_dir, exist_ok=True)
                for legacy_name in legacy_names:
                    try:
                        os.replace(
                            os.path.join(outdir, legacy_name),
                            os.path.join(receptor_report_dir, legacy_name)
                        )
                    except OSError:
                        pass

            # Each new file includes all ligands/runs/poses for one receptor.
            if global_plip_entries:
                os.makedirs(receptor_report_dir, exist_ok=True)
                receptor_groups = {}
                for entry in global_plip_entries:
                    receptor = entry.get("receptor", "UNKNOWN_RECEPTOR")
                    receptor_groups.setdefault(receptor, []).append(entry)

                for receptor_name in sorted(receptor_groups.keys()):
                    safe_receptor = self._safe_report_filename_part(receptor_name)
                    receptor_report = os.path.join(
                        receptor_report_dir,
                        f"all ligands plip - {safe_receptor}.txt"
                    )
                    per_receptor_files.append(receptor_report)

                    with open(receptor_report, "w", encoding="utf-8") as out:
                        out.write(self._vina_report_text(outdir))
                        out.write("#" * 100 + "\n")
                        out.write(f"PER-RECEPTOR PLIP REPORT: {receptor_name}\n")
                        out.write("Includes all ligands, runs and poses for this receptor.\n")
                        out.write("#" * 100 + "\n\n")

                        for i, entry in enumerate(receptor_groups[receptor_name], 1):
                            try:
                                with open(entry["path"], "r", encoding="utf-8", errors="replace") as f:
                                    text = f.read().strip()
                            except Exception as e:
                                text = f"[ERROR READING SUMMARY: {e}]"

                            out.write("=" * 100 + "\n")
                            out.write(f"Ligand: {entry['ligand']}\n")
                            out.write(f"Receptor: {entry['receptor']}\n")
                            out.write(f"Run: {entry['run']}\n")
                            score_text = self._format_vina_score(entry.get("vina_score"))
                            out.write(f"Pose: {entry['pose']}  vina score:{score_text} kcal/mol\n")
                            out.write("=" * 100 + "\n")
                            out.write(text + "\n")

                            if i != len(receptor_groups[receptor_name]):
                                out.write("\n\n")

            for ligand in ligands_to_run:
                ligand_name = ligand_output_names.get(normalized_path_key(ligand), safe_output_stem(ligand))
                ligand_folder = os.path.join(outdir, ligand_name)
                runlog = os.path.join(ligand_folder, "runlog.txt")
                if os.path.exists(runlog):
                    log_line(runlog, f"[INFO] Wrote top-level PLIP summary: {top_plip_file}")
                    for receptor_report in per_receptor_files:
                        log_line(runlog, f"[INFO] Wrote per-receptor PLIP summary: {receptor_report}")

        except Exception as e:
            for ligand in ligands_to_run:
                ligand_name = ligand_output_names.get(normalized_path_key(ligand), safe_output_stem(ligand))
                ligand_folder = os.path.join(outdir, ligand_name)
                runlog = os.path.join(ligand_folder, "runlog.txt")
                if os.path.exists(runlog):
                    log_line(runlog, f"[ERROR] Failed writing top-level/per-receptor PLIP summary: {e}")

    def _write_top_level_docking_summary(self, outdir, ligands_to_run, global_docking_entries):
        top_docking_file = os.path.join(outdir, "all ligands docking scores.txt")
        deduped = {}
        for entry in global_docking_entries:
            key = (entry.get("ligand"), entry.get("receptor"), entry.get("run"))
            deduped[key] = entry
        global_docking_entries = list(deduped.values())
        ligand_output_names = build_unique_output_names(ligands_to_run)

        try:
            with open(top_docking_file, "w", encoding="utf-8") as out:
                if not global_docking_entries:
                    out.write("No docking scores were generated.\n")
                else:
                    out.write("Ligand\tReceptor\tRun\tAffinity (kcal/mol)\tOutput File\tDock File\n")

                    for entry in global_docking_entries:
                        out.write(
                            f"{entry['ligand']}\t"
                            f"{entry['receptor']}\t"
                            f"Run {entry['run']}\t"
                            f"{entry['affinity']}\t"
                            f"{entry['output_file']}\t"
                            f"{entry['dock_pdbqt']}\n"
                        )

            with open(top_docking_file, "a", encoding="utf-8") as out:
                out.write("".join("# " + line + "\n" for line in self._vina_report_text(outdir).splitlines()))
            for ligand in ligands_to_run:
                ligand_name = ligand_output_names.get(normalized_path_key(ligand), safe_output_stem(ligand))
                ligand_folder = os.path.join(outdir, ligand_name)
                runlog = os.path.join(ligand_folder, "runlog.txt")
                if os.path.exists(runlog):
                    log_line(runlog, f"[INFO] Wrote top-level docking summary: {top_docking_file}")

        except Exception as e:
            for ligand in ligands_to_run:
                ligand_name = ligand_output_names.get(normalized_path_key(ligand), safe_output_stem(ligand))
                ligand_folder = os.path.join(outdir, ligand_name)
                runlog = os.path.join(ligand_folder, "runlog.txt")
                if os.path.exists(runlog):
                    log_line(runlog, f"[ERROR] Failed writing top-level docking summary: {e}")

    # ----------------------
    # Split / merge / convert
    # ----------------------
    def split_merge_convert(self, dock_pdbqt, receptor_pdbqt,
                            ligand_name, receptor_name, run,
                            pose_dir, merged_dir, pdb_dir, plip_dir,
                            summary_folder, final_summary_lines,
                            run_dir, runlog,
                            save_merge, save_pdb, save_txt, run_plip,
                            job_settings_record=None,
                            global_plip_entries=None,
                            global_docking_entries=None, plip_workers=2):

        with tempfile.TemporaryDirectory(prefix="vlip_poses_") as pose_temp_dir:
            self.check_cancelled()

            best_affinity = None
            plip_attempts = 0
            plip_failures = 0
            output_file = os.path.basename(dock_pdbqt)
            run_summary_file = os.path.join(summary_folder, f"run{run}_summary.txt")

            if not os.path.exists(dock_pdbqt):
                log_line(runlog, f"[WARN] Docking file missing, skipping: {dock_pdbqt}")
                return {"best_affinity": None, "plip_attempts": 0, "plip_failures": 0}

            with open(dock_pdbqt, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            if save_txt:
                with open(run_summary_file, "w", encoding="utf-8") as f:
                    f.write(self._vina_report_text(run_dir))
                    f.writelines(lines)

            receptor_atom_count = self.count_atom_records(receptor_pdbqt)

            pose = []
            idx = 1
            current_pose_affinity = None
            generated_pose_summaries = []
            plip_jobs = []

            for l in lines:
                self.check_cancelled()

                if l.startswith("MODEL"):
                    pose = []
                    current_pose_affinity = None

                elif l.startswith("ENDMDL"):
                    pose_file = os.path.join(
                        pose_dir, f"pose{idx}.pdbqt"
                    )
                    with open(pose_file, "w", encoding="utf-8") as o:
                        o.writelines(pose)

                    # PLIP and PDB export both need a receptor+ligand complex.
                    # Previously PLIP silently depended on BOTH "Save merged" and
                    # "Convert to PDB" being enabled.  Build a temporary merged
                    # complex whenever downstream conversion/PLIP needs one, while
                    # keeping the save checkboxes as output-retention choices only.
                    need_complex = bool(save_merge or save_pdb or run_plip)
                    merged_file = pose_file
                    temp_merged_file = None

                    if need_complex:
                        if save_merge:
                            merged_file = os.path.join(
                                merged_dir, f"pose{idx}_merged.pdbqt"
                            )
                        else:
                            fd, temp_merged_file = tempfile.mkstemp(prefix="merged_", suffix=".pdbqt", dir=pose_temp_dir)
                            os.close(fd)
                            merged_file = temp_merged_file

                        with open(merged_file, "w", encoding="utf-8") as m:
                            with open(receptor_pdbqt, "r", encoding="utf-8", errors="replace") as rfile:
                                for rl in rfile:
                                    if rl.startswith(("ATOM", "HETATM")):
                                        m.write(rl)
                            for pl in pose:
                                m.write(pl)

                    temp_pdb_file = None
                    if save_pdb or run_plip:
                        if save_pdb:
                            pdb_file = os.path.join(
                                pdb_dir, f"pose{idx}.pdb"
                            )
                        else:
                            os.makedirs(plip_dir, exist_ok=True)
                            fd, temp_pdb_file = tempfile.mkstemp(prefix="input_", suffix=".pdb", dir=pose_temp_dir)
                            os.close(fd)
                            pdb_file = temp_pdb_file

                        self.pdbqt_to_pdb(merged_file, pdb_file, receptor_atom_count)

                        if run_plip:
                            plip_jobs.append(dict(
                                pdb_file=pdb_file, plip_dir=plip_dir, runlog=runlog,
                                pose_name=f"pose{idx}", ligand_name=ligand_name,
                                receptor_name=receptor_name, vina_score=current_pose_affinity,
                                settings_record_path=job_settings_record))

                    # All temporary inputs remain alive until the pool has drained.
                    idx += 1

                else:
                    if l.startswith("REMARK VINA RESULT:"):
                        try:
                            aff = float(l.split()[3])
                            current_pose_affinity = aff
                            if best_affinity is None or aff < best_affinity:
                                best_affinity = aff
                        except Exception:
                            current_pose_affinity = None

                    if l.startswith(("ATOM", "HETATM")):
                        pose.append(l)

            if plip_jobs:
                results = self._run_plip_pose_jobs(plip_jobs, plip_workers)
                plip_attempts = len(results)
                plip_failures = sum(not ok for _, ok in results)
                for job, ok in results:
                    if not ok:
                        continue
                    pose_name = job["pose_name"]
                    compact = os.path.join(plip_dir, f"{pose_name}_PLIP_compact_summary.txt")
                    legacy = os.path.join(plip_dir, f"{pose_name}_UNL_only_summary.txt")
                    summary = compact if os.path.isfile(compact) else legacy
                    if os.path.isfile(summary):
                        generated_pose_summaries.append(summary)
                        if global_plip_entries is not None:
                            global_plip_entries.append(dict(ligand=ligand_name, receptor=receptor_name,
                                run=run, pose=pose_name, vina_score=job["vina_score"], path=summary))

            if run_plip and os.path.isdir(plip_dir) and generated_pose_summaries:
                self.rebuild_all_pose_summary(plip_dir, runlog, ligand_name, receptor_name)

            if best_affinity is not None:
                final_summary_lines.append(f"{receptor_name}\tRun {run}\t{best_affinity}\t{output_file}\n")

                if global_docking_entries is not None:
                    global_docking_entries.append({
                        "ligand": ligand_name,
                        "receptor": receptor_name,
                        "run": run,
                        "affinity": best_affinity,
                        "output_file": output_file,
                        "dock_pdbqt": dock_pdbqt
                    })

            return {
                "best_affinity": best_affinity,
                "plip_attempts": plip_attempts,
                "plip_failures": plip_failures,
            }

    # ----------------------
    # PDB helpers
    # ----------------------
    def count_atom_records(self, path):
        n = 0
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith(("ATOM", "HETATM")):
                    n += 1
        return n

    def guess_element(self, line):
        parts = line.split()
        atomtype = parts[-1].strip() if parts else ""
        at_up = atomtype.upper().replace(".", "")

        autodock_map = {
            "C": "C",
            "A": "C",
            "N": "N",
            "NA": "N",
            "NS": "N",
            "OA": "O",
            "OS": "O",
            "O": "O",
            "S": "S",
            "SA": "S",
            "P": "P",
            "F": "F",
            "CL": "Cl",
            "BR": "Br",
            "I": "I",
            "HD": "H",
            "H": "H",
            "MG": "Mg",
            "ZN": "Zn",
            "CA": "Ca",
            "MN": "Mn",
            "FE": "Fe",
            "CU": "Cu",
            "K": "K",
            "NA+": "Na",
            "NA1": "Na",
        }

        if at_up in autodock_map:
            return autodock_map[at_up]

        atom_name = line[12:16].strip()
        atom_up = atom_name.upper()

        if atom_up.startswith("CL"):
            return "Cl"
        if atom_up.startswith("BR"):
            return "Br"
        if atom_up.startswith("ZN"):
            return "Zn"
        if atom_up.startswith("FE"):
            return "Fe"
        if atom_up.startswith("MG"):
            return "Mg"
        if atom_up.startswith("CA"):
            return "Ca"
        if atom_up.startswith("MN"):
            return "Mn"
        if atom_up.startswith("CU"):
            return "Cu"

        if atom_up:
            ch = atom_up[0]
            if ch in {"H", "C", "N", "O", "S", "P", "F", "I", "K", "B"}:
                return ch

        return "C"

    def is_ligand_hydrogen(self, line):
        element = self.guess_element(line)
        if element == "H":
            return True

        atom_name = line[12:16].strip().upper()
        if atom_name.startswith("H"):
            return True

        return False

    def make_atom_name(self, element, count):
        return f"{element}{count}"

    def format_pdb_atom_line(
        self,
        record,
        serial,
        atom_name,
        resname,
        chain,
        resid,
        x,
        y,
        z,
        occupancy,
        temp_factor,
        element
    ):
        atom_name = (atom_name or "X")[:4]
        resname = (resname or "UNK")[:3]
        chain = (chain or "A")[:1]
        element = (element or "").strip()[:2].rjust(2)

        if len(atom_name) < 4:
            atom_name = atom_name.rjust(4)

        altloc = ""
        icode = ""

        return (
            f"{record:<6}"
            f"{serial:>5} "
            f"{atom_name:<4}"
            f"{altloc:1}"
            f"{resname:>3} "
            f"{chain:1}"
            f"{resid:>4}"
            f"{icode:1}   "
            f"{x:>8.3f}"
            f"{y:>8.3f}"
            f"{z:>8.3f}"
            f"{occupancy:>6.2f}"
            f"{temp_factor:>6.2f}"
            f"          "
            f"{element:>2}\n"
        )

    def pdbqt_to_plip_ready_pdb(self, src, dst, receptor_atom_count):
        with open(src, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.read().splitlines()

        atom_lines = [line for line in raw_lines if line.startswith(("ATOM", "HETATM"))]

        if not atom_lines:
            raise ValueError(f"No ATOM/HETATM records found in {src}")

        protein_lines = atom_lines[:receptor_atom_count]
        ligand_lines = atom_lines[receptor_atom_count:]

        if not protein_lines:
            raise ValueError("No protein atoms found during conversion.")

        if not ligand_lines:
            raise ValueError("No ligand atoms found during conversion.")

        out_lines = []

        for line in protein_lines:
            out_lines.append(line[:66].rstrip() + "\n")

        out_lines.append("TER\n")

        serial = receptor_atom_count + 2
        element_counts = {}

        for line in ligand_lines:
            if self.is_ligand_hydrogen(line):
                continue

            try:
                x = float(line[30:38])
                y = float(line[38:46])
                z = float(line[46:54])
            except Exception:
                continue

            element = self.guess_element(line)
            element_counts[element] = element_counts.get(element, 0) + 1
            atom_name = self.make_atom_name(element, element_counts[element])

            out_lines.append(
                self.format_pdb_atom_line(
                    record="HETATM",
                    serial=serial,
                    atom_name=atom_name,
                    resname="UNL",
                    chain="Z",
                    resid=1,
                    x=x,
                    y=y,
                    z=z,
                    occupancy=1.00,
                    temp_factor=0.00,
                    element=element
                )
            )
            serial += 1

        out_lines.append("END\n")

        with open(dst, "w", encoding="utf-8") as out:
            out.writelines(out_lines)

    def pdbqt_to_pdb(self, src, dst, receptor_atom_count):
        self.pdbqt_to_plip_ready_pdb(src, dst, receptor_atom_count)


# ======================================================
if __name__ == "__main__":
    if "--plip-worker" in sys.argv:
        sys.exit(run_internal_plip_worker())

    root = tk.Tk()
    app = VinaBatchGUI(root)
    if "--setup-only" in sys.argv:
        # Avoid the ordinary first-run prompt racing with the explicit installer.
        app._startup_check_started = True
        root.after(300, app.install_or_repair_all_tools)
    root.mainloop()