"""Project (client folder) discovery, run_by_tag.sh parsing/editing, uploads, results."""
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
from werkzeug.utils import secure_filename

from .config import Config

TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
SUBFOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*(/[A-Za-z0-9][A-Za-z0-9_\-]*)*$")
PROJECT_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{1,40}$")
# Only JMeter property style args may be stored in EXTRA_ARGS or passed from the UI.
PROP_ARG_RE = re.compile(r"^-[JGD][A-Za-z0-9_.\-]+=[A-Za-z0-9_.,:/@%+\-]*$")

CASE_ENTRY_RE = re.compile(r'^\s*"?([^"\s()*]+)"?\)\s*$')
GROUP_RE = re.compile(r"^\s*#\s*-{3,}\s*(.+?)\s*-{3,}\s*$")
SCRIPT_RE = re.compile(r'^\s*SCRIPT="([^"]*)"')
EXTRA_RE = re.compile(r'^\s*EXTRA_ARGS="([^"]*)"')
END_MARKER = "# @@WEBAPP_TAGS_END@@"
HELP_GROUP_RE = re.compile(r"^\s*#\s*-+\s*Ayuda por defecto", re.IGNORECASE)
DEFAULT_RE = re.compile(r"^\s*\*\)\s*$")


class ProjectError(ValueError):
    pass


# --------------------------------------------------------------------------- paths
def _inside(base: Path, target: Path) -> Path:
    base = base.resolve()
    target = target.resolve()
    if target != base and base not in target.parents:
        raise ProjectError("Path escapes the project folder")
    return target


def project_dir(name: str) -> Path:
    if not name or "/" in name or name.startswith(".") or not name.endswith(Config.PROJECT_SUFFIX):
        raise ProjectError("Unknown project")
    p = _inside(Config.REPO_ROOT, Config.REPO_ROOT / name)
    if not (p / "run_by_tag.sh").is_file():
        raise ProjectError("Unknown project")
    return p


def safe_path(project: str, rel: str) -> Path:
    base = project_dir(project)
    return _inside(base, base / rel)


# --------------------------------------------------------------------------- discovery
def list_projects():
    out = []
    for p in sorted(Config.REPO_ROOT.iterdir()):
        if p.is_dir() and p.name.endswith(Config.PROJECT_SUFFIX) and (p / "run_by_tag.sh").is_file():
            tags = parse_tags(p.name)
            results = list_results(p.name, limit=1)
            out.append({
                "name": p.name,
                "label": p.name[: -len(Config.PROJECT_SUFFIX)],
                "tags": len(tags),
                "broken_tags": sum(1 for t in tags if not t["exists"]),
                "scripts": sum(1 for _ in (p / "tests").rglob("*.jmx")) if (p / "tests").exists() else 0,
                "data_files": sum(1 for f in (p / "data").rglob("*") if f.is_file() and not f.name.startswith("."))
                if (p / "data").exists() else 0,
                "last_result": results[0] if results else None,
            })
    return out


# --------------------------------------------------------------------------- tags
def parse_tags(project: str):
    """Read the case dictionary of run_by_tag.sh -> list of {tag, script, extra_args, group}."""
    base = project_dir(project)
    lines = (base / "run_by_tag.sh").read_text(errors="replace").splitlines()
    tags, group, current, in_case = [], "General", None, False
    for line in lines:
        if not in_case:
            if re.match(r'^\s*case\s+"?\$TAG"?\s+in', line):
                in_case = True
            continue
        if re.match(r"^\s*esac\b", line):
            break
        g = GROUP_RE.match(line)
        if g and current is None:
            if not HELP_GROUP_RE.match(line):
                group = g.group(1)
            continue
        if DEFAULT_RE.match(line):
            current = None
            continue
        m = CASE_ENTRY_RE.match(line)
        if m and current is None:
            current = {"tag": m.group(1), "script": "", "extra_args": "", "group": group}
            continue
        if current is not None:
            s = SCRIPT_RE.match(line)
            if s:
                current["script"] = s.group(1)
            e = EXTRA_RE.match(line)
            if e:
                current["extra_args"] = e.group(1)
            if ";;" in line:
                current["exists"] = bool(current["script"]) and (base / current["script"]).is_file()
                tags.append(current)
                current = None
    seen = {}
    for t in tags:
        seen[t["tag"]] = seen.get(t["tag"], 0) + 1
    for t in tags:
        t["duplicate"] = seen[t["tag"]] > 1
    return tags


def get_tag(project, tag):
    for t in parse_tags(project):
        if t["tag"] == tag:
            return t
    return None


def validate_prop_args(raw: str):
    tokens = (raw or "").split()
    for tok in tokens:
        if not PROP_ARG_RE.match(tok):
            raise ProjectError(f"Invalid argument '{tok}'. Use -Jname=value / -Gname=value "
                               "(no spaces or quotes).")
    return tokens


def _backup(path: Path):
    bdir = Config.INSTANCE_DIR / "backups" / path.parent.name
    bdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, bdir / f"{path.name}.{time.strftime('%Y%m%d_%H%M%S')}")


def _write_checked(path: Path, content: str, original: str):
    path.write_text(content)
    check = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
    if check.returncode != 0:
        path.write_text(original)
        raise ProjectError(f"Edit aborted, bash syntax check failed: {check.stderr.strip()}")


def add_tag(project, tag, script_rel, extra_args="", group=""):
    base = project_dir(project)
    if not TAG_RE.match(tag or ""):
        raise ProjectError("Tag: letters, digits, '_', '-', '.' (max 64)")
    if get_tag(project, tag):
        raise ProjectError(f"Tag '{tag}' already exists")
    script_rel = (script_rel or "").strip()
    if not script_rel.startswith("tests/") or not script_rel.endswith(".jmx") or '"' in script_rel:
        raise ProjectError("Script must be a .jmx inside tests/")
    if not _inside(base, base / script_rel).is_file():
        raise ProjectError("Script file not found")
    validate_prop_args(extra_args)
    group = re.sub(r"[^A-Za-z0-9 _.\-—/()]", "", group or "").strip()

    path = base / "run_by_tag.sh"
    original = path.read_text()
    lines = original.splitlines()
    block = [f'    "{tag}")', f'        SCRIPT="{script_rel}"', f'        EXTRA_ARGS="{extra_args.strip()}"',
             "        ;;"]

    anchor = _end_anchor(lines)
    insert_at = anchor
    if group:
        gidx = next((i for i, l in enumerate(lines[:anchor])
                     if GROUP_RE.match(l) and GROUP_RE.match(l).group(1) == group), None)
        if gidx is not None:
            insert_at = next((i for i in range(gidx + 1, anchor) if GROUP_RE.match(lines[i])), anchor)
        else:
            block = [f"    # ---------------- {group} ----------------"] + block
    block = block + [""]
    lines[insert_at:insert_at] = block
    _backup(path)
    _write_checked(path, "\n".join(lines) + "\n", original)


def remove_tag(project, tag):
    base = project_dir(project)
    path = base / "run_by_tag.sh"
    original = path.read_text()
    lines = original.splitlines()
    start = next((i for i, l in enumerate(lines)
                  if CASE_ENTRY_RE.match(l) and CASE_ENTRY_RE.match(l).group(1) == tag), None)
    if start is None:
        raise ProjectError("Tag not found")
    end = next((i for i in range(start, len(lines)) if ";;" in lines[i]), None)
    if end is None:
        raise ProjectError("Malformed tag block")
    del lines[start:end + 1]
    _backup(path)
    _write_checked(path, "\n".join(lines) + "\n", original)


def _end_anchor(lines):
    for rx in (re.compile(re.escape(END_MARKER)), HELP_GROUP_RE, DEFAULT_RE):
        for i, l in enumerate(lines):
            if rx.search(l):
                return i
    raise ProjectError("Could not find where to insert the tag in run_by_tag.sh")


# --------------------------------------------------------------------------- files
def _file_info(base: Path, f: Path):
    st = f.stat()
    return {"path": str(f.relative_to(base)), "name": f.name, "size": st.st_size, "mtime": st.st_mtime}


def list_scripts(project):
    base = project_dir(project)
    tests = base / "tests"
    tagged = {}
    for t in parse_tags(project):
        tagged.setdefault(t["script"], []).append(t["tag"])
    out = []
    if tests.exists():
        for f in sorted(tests.rglob("*")):
            if f.is_file() and f.suffix.lower() in (".jmx", ".md", ".csv", ".txt") and not f.name.startswith("."):
                info = _file_info(base, f)
                info["folder"] = str(f.parent.relative_to(base))
                info["tags"] = tagged.get(info["path"], [])
                out.append(info)
    return out


def test_subfolders(project):
    base = project_dir(project)
    tests = base / "tests"
    if not tests.exists():
        return []
    return sorted(str(d.relative_to(tests)) for d in tests.rglob("*") if d.is_dir() and not d.name.startswith("."))


def list_data(project):
    base = project_dir(project)
    data = base / "data"
    if not data.exists():
        return []
    return [_file_info(base, f) for f in sorted(data.rglob("*"))
            if f.is_file() and not f.name.startswith(".")]


def inspect_jmx(path: Path, base: Path):
    """Validate a JMX and return warnings about data files it references."""
    try:
        root = next(ET.iterparse(str(path), events=("start",)))[1]
    except (ET.ParseError, StopIteration, DefusedXmlException) as exc:
        raise ProjectError(f"Not a valid JMX/XML file: {exc}")
    if root.tag != "jmeterTestPlan":
        raise ProjectError("XML root is not <jmeterTestPlan>")
    warnings, refs = [], set()
    for _, el in ET.iterparse(str(path)):
        if el.tag == "stringProp" and el.get("name") == "filename" and (el.text or "").strip():
            refs.add(el.text.strip())
        el.clear()
    for ref in sorted(refs):
        if ref in ("NUL", "/dev/null") or ref.startswith("results/") or "${" in ref:
            continue
        if re.match(r"^[A-Za-z]:[\\/]", ref) or "\\" in ref:
            warnings.append(f"Windows path will not exist on the Linux generators: {ref}")
        elif ref.startswith("/"):
            warnings.append(f"Absolute path, must exist on Master AND every Slave: {ref}")
        elif not (base / ref).exists():
            warnings.append(f"Referenced data file not found in project: {ref}")
    return warnings


def save_upload(project, kind, storage, subfolder="", overwrite=False):
    base = project_dir(project)
    filename = secure_filename(storage.filename or "")
    if not filename:
        raise ProjectError("Invalid file name")
    ext = Path(filename).suffix.lower()
    if kind == "script":
        if ext != ".jmx":
            raise ProjectError("Scripts must be .jmx files")
        subfolder = (subfolder or "").strip().strip("/")
        if subfolder and not SUBFOLDER_RE.match(subfolder):
            raise ProjectError("Folder: letters, digits, '_' or '-', separated by '/'")
        target_dir = base / "tests" / subfolder if subfolder else base / "tests"
    elif kind == "data":
        if ext not in Config.DATA_EXTENSIONS:
            raise ProjectError(f"Allowed data extensions: {', '.join(sorted(Config.DATA_EXTENSIONS))}")
        target_dir = base / "data"
    else:
        raise ProjectError("Unknown upload type")
    target_dir = _inside(base, target_dir)
    target = target_dir / filename
    if target.exists() and not overwrite:
        raise ProjectError(f"{target.relative_to(base)} already exists (tick 'overwrite' to replace it)")
    target_dir.mkdir(parents=True, exist_ok=True)
    tmp = target_dir / f".upload_{filename}"
    storage.save(str(tmp))
    warnings = []
    try:
        if kind == "script":
            warnings = inspect_jmx(tmp, base)
    except ProjectError:
        tmp.unlink(missing_ok=True)
        raise
    if target.exists():
        _trash(base, target)
    tmp.replace(target)
    return str(target.relative_to(base)), warnings


def _trash(base: Path, f: Path):
    tdir = Config.INSTANCE_DIR / "trash" / base.name / time.strftime("%Y%m%d_%H%M%S")
    dest = tdir / f.relative_to(base)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), str(dest))


def remove_file(project, rel):
    base = project_dir(project)
    f = safe_path(project, rel)
    if not f.is_file() or f.parts[len(base.parts)] not in ("tests", "data"):
        raise ProjectError("Only files inside tests/ or data/ can be removed")
    in_use = [t["tag"] for t in parse_tags(project) if t["script"] == rel]
    if in_use:
        raise ProjectError(f"Script is used by tag(s): {', '.join(in_use)}. Remove the tag first.")
    _trash(base, f)


# --------------------------------------------------------------------------- results
def _summary(stats_file: Path):
    try:
        total = json.loads(stats_file.read_text()).get("Total")
    except (OSError, ValueError):
        return None
    if not total:
        return None
    return {
        "samples": total.get("sampleCount"),
        "error_pct": round(total.get("errorPct", 0), 2),
        "avg_ms": round(total.get("meanResTime", 0)),
        "p95_ms": round(total.get("pct2ResTime", 0)),
        "tps": round(total.get("throughput", 0), 2),
    }


def list_results(project, limit=None):
    base = project_dir(project)
    rdir = base / "results"
    if not rdir.exists():
        return []
    dirs = sorted((d for d in rdir.iterdir() if d.is_dir() and d.name.startswith("Ejecucion_")),
                  key=lambda d: d.stat().st_mtime, reverse=True)
    if limit:
        dirs = dirs[:limit]
    out = []
    for d in dirs:
        jtls = list(d.glob("*.jtl"))
        out.append({
            "name": d.name,
            "mtime": d.stat().st_mtime,
            "has_report": (d / "html_report" / "index.html").is_file(),
            "jtl_size": sum(j.stat().st_size for j in jtls),
            "tar": (rdir / f"{d.name}.tar.gz").is_file(),
            "summary": _summary(d / "html_report" / "statistics.json"),
        })
    return out


def result_stats(project, run_name):
    """Per-transaction statistics of a finished run (html_report/statistics.json)."""
    f = result_dir(project, run_name) / "html_report" / "statistics.json"
    try:
        raw = json.loads(f.read_text())
    except (OSError, ValueError):
        return {}
    out = {}
    for name, s in raw.items():
        out[name] = {
            "samples": s.get("sampleCount"), "errors": s.get("errorCount"),
            "error_pct": round(s.get("errorPct", 0), 2), "avg": round(s.get("meanResTime", 0), 1),
            "p90": round(s.get("pct1ResTime", 0), 1), "p95": round(s.get("pct2ResTime", 0), 1),
            "p99": round(s.get("pct3ResTime", 0), 1), "max": s.get("maxResTime"),
            "tps": round(s.get("throughput", 0), 2),
        }
    return out


def result_dir(project, run_name):
    if not run_name.startswith("Ejecucion_") or "/" in run_name:
        raise ProjectError("Unknown result")
    d = safe_path(project, f"results/{run_name}")
    if not d.is_dir():
        raise ProjectError("Unknown result")
    return d


# --------------------------------------------------------------------------- creation
TEXT_SUFFIXES = {".md", ".sh", ".yml", ".yaml", ".txt", ""}


def create_project(slug, app_name, folders):
    slug = (slug or "").strip().lower()
    if not PROJECT_RE.match(slug):
        raise ProjectError("Project id: lowercase letters, digits and '-' (2-41 chars)")
    folder = f"{slug}{Config.PROJECT_SUFFIX}"
    dest = Config.REPO_ROOT / folder
    if dest.exists():
        raise ProjectError(f"{folder} already exists")
    app_name = re.sub(r"[^A-Za-z0-9 _\-]", "", app_name or "").strip() or slug.upper()
    subfolders = []
    for f in (folders or "").replace("\n", ",").split(","):
        f = f.strip().strip("/")
        if not f:
            continue
        if not SUBFOLDER_RE.match(f):
            raise ProjectError(f"Invalid test folder '{f}'")
        subfolders.append(f)
    if not Config.TEMPLATE_DIR.is_dir():
        raise ProjectError(f"Template folder not found: {Config.TEMPLATE_DIR}")

    replacements = {"{{PROJECT_FOLDER}}": folder, "{{APP_NAME}}": app_name,
                    "{{APP_SLUG}}": slug, "{{CREATED}}": time.strftime("%Y-%m-%d")}
    shutil.copytree(Config.TEMPLATE_DIR, dest)
    for f in dest.rglob("*"):
        if f.is_file() and (f.suffix in TEXT_SUFFIXES or f.name == "Jenkinsfile"):
            text = f.read_text()
            for k, v in replacements.items():
                text = text.replace(k, v)
            f.write_text(text)
        if f.suffix == ".sh":
            f.chmod(0o755)
    for sub in subfolders:
        (dest / "tests" / sub).mkdir(parents=True, exist_ok=True)
        (dest / "tests" / sub / ".gitkeep").touch()
    return folder
