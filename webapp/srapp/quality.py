"""Revisión rápida de calidad de scripts JMeter contra la Guía de Scripting del equipo (docs/).

Cada regla (R01..R18) corresponde a una sección de la guía. Uso:
  * en la app: pestaña Quality del proyecto, al subir un .jmx y en la página Git antes del commit
  * CLI / CI:  cd webapp && python -m srapp.quality [--changed <base-ref>] [--md salida.md] [rutas .jmx ...]
               (sale con código 1 si hay hallazgos de severidad "error")
"""
import argparse
import os
import re
import sys
from pathlib import Path

from defusedxml import ElementTree as ET

SEV_WEIGHT = {"error": 15, "warn": 5, "info": 1}
SEV_LABEL = {"error": "Error", "warn": "Advertencia", "info": "Sugerencia"}
NAME_RE = re.compile(r"^[Ss][Cc][Rr][Ii][Pp][Tt]\d{2}_[A-Za-z0-9]+_[A-Za-z0-9]+_[A-Za-z0-9_\-]+\.jmx$")
LEGACY_RE = re.compile(r"^G\d_")
EXTRACTORS = {"RegexExtractor": "RegexExtractor.refname", "JSONPostProcessor": "JSONPostProcessor.referenceNames",
              "XPathExtractor": "XPathExtractor.refname", "XPath2Extractor": "XPathExtractor2.refname",
              "BoundaryExtractor": "BoundaryExtractor.refname", "HtmlExtractor": "HtmlExtractor.refname",
              "JMESPathExtractor": "JMESExtractor.referenceName"}
PROP_RE = re.compile(r"\$\{__P(?:roperty)?\(")
SECRET_RE = re.compile(r"(?i)(password|passwd|pwd|contrase[nñ]a|secret|api[_-]?key|token)\s*[=:\"']\s*[\"']?(?!\$\{)[^\s\"'&,}]{4,}")
AUTH_RE = re.compile(r"(?i)^(basic|bearer)\s+(?!\$\{)[A-Za-z0-9+/=._\-]{12,}")
TIMERS = ("ConstantTimer", "UniformRandomTimer", "GaussianRandomTimer", "PoissonRandomTimer", "ConstantThroughputTimer",
          "PreciseThroughputTimer", "SyncTimer")
ASSERTIONS = ("ResponseAssertion", "JSONPathAssertion", "DurationAssertion", "SizeAssertion", "XPathAssertion",
              "XPath2Assertion", "JSR223Assertion", "BeanShellAssertion", "MD5HexAssertion", "HTMLAssertion")
HEAVY = {"ViewResultsFullVisualizer": "View Results Tree", "SummaryReport": "Summary Report",
         "StatVisualizer": "Aggregate Report", "GraphVisualizer": "Graph Results", "TableVisualizer": "View Results in Table",
         "RespTimeGraphVisualizer": "Response Time Graph", "StatGraphVisualizer": "Aggregate Graph"}


def _enabled(el):
    return el.get("enabled", "true") != "false"


def _prop(el, name):
    for kind in ("stringProp", "intProp", "longProp", "boolProp"):
        p = el.find(f"./{kind}[@name='{name}']")
        if p is not None:
            return (p.text or "").strip()
    return ""


def _uses_prop(value, variables):
    if PROP_RE.search(value or ""):
        return True
    m = re.fullmatch(r"\$\{([A-Za-z0-9_.\-]+)\}", value or "")
    return bool(m and PROP_RE.search(variables.get(m.group(1), "")))


def _arguments(tree):
    out = {}
    for el in tree.iter("elementProp"):
        if el.get("elementType") == "Argument":
            n, v = el.find("./stringProp[@name='Argument.name']"), el.find("./stringProp[@name='Argument.value']")
            if n is not None and n.text:
                out[n.text.strip()] = (v.text or "") if v is not None else ""
    return out


def review_file(path, project_dir=None, tagged_scripts=None):
    """Return {script, score, grade, counts, findings[]} for one .jmx."""
    path = Path(path)
    findings = []

    def add(rule, sev, title, detail, fix, element=""):
        findings.append({"rule": rule, "severity": sev, "title": title, "detail": detail, "fix": fix, "element": element})

    rel = path.name
    if project_dir:
        try:
            rel = path.relative_to(project_dir).as_posix()
        except ValueError:
            pass
    try:
        tree = ET.parse(str(path))
    except Exception as exc:  # noqa: BLE001
        add("R00", "error", "El archivo no es un JMX válido", str(exc)[:200], "Abrir y guardar de nuevo en JMeter 5.6.x.")
        return _result(rel, findings)
    root = tree.getroot()
    if root.tag != "jmeterTestPlan":
        add("R00", "error", "El archivo no es un plan de JMeter", f"Raíz <{root.tag}>", "Exportar el plan desde JMeter.")
        return _result(rel, findings)
    variables = _arguments(tree)

    # R01 nomenclatura
    if LEGACY_RE.match(path.name):
        add("R01", "info", "Nombre con la convención anterior (G1_/G2_)",
            f"«{path.name}»", "Al modificarlo, renombrar a ScriptXX_Ambiente_AppName_Objetivo.jmx y actualizar su tag.")
    elif not NAME_RE.match(path.name):
        add("R01", "warn", "Nombre fuera de la convención",
            f"«{path.name}» no sigue ScriptXX_Ambiente_AppName_ObjetivoDelScript.jmx",
            "Renombrar, p. ej. Script01_QA_BaseInet_TransferenciaSPEI.jmx, y actualizar el tag en run_by_tag.sh.")
    # R02 tag registrado
    if tagged_scripts is not None and rel not in tagged_scripts:
        add("R02", "warn", "El script no tiene tag en run_by_tag.sh",
            "No se puede ejecutar desde el Control Center, programaciones ni pipelines.",
            "Registrar un tag (pestaña Tags → Register tag) con sus EXTRA_ARGS.")

    # R15 plan
    for tp in root.iter("TestPlan"):
        if _prop(tp, "TestPlan.functional_mode") == "true":
            add("R15", "error", "Modo funcional activado en el Test Plan",
                "Guarda request/response de cada muestra: consume memoria y disco en carga.",
                "Test Plan → desmarcar «Functional Test Mode».", tp.get("testname", ""))
        if not (_prop(tp, "TestPlan.comments")):
            add("R18", "info", "El Test Plan no tiene descripción",
                "Sin objetivo, autor, ambiente ni ticket en el campo Comments.",
                "Completar Comments del Test Plan: objetivo, endpoints, datos requeridos, autor y fecha.")

    # R03 thread groups parametrizados
    tgs = [el for el in root.iter() if el.tag.endswith("ThreadGroup") and _enabled(el)]
    if not tgs:
        add("R03", "error", "No hay Thread Group habilitado", "", "Agregar un Thread Group con usuarios parametrizados.")
    for tg in tgs:
        name = tg.get("testname", tg.tag)
        if tg.tag in ("ThreadGroup", "SetupThreadGroup", "PostThreadGroup"):
            threads, ramp = _prop(tg, "ThreadGroup.num_threads"), _prop(tg, "ThreadGroup.ramp_time")
            dur = _prop(tg, "ThreadGroup.duration")
        else:  # plugins (Concurrency / Stepping / Ultimate Thread Group ...)
            threads = _prop(tg, "TargetLevel") or _prop(tg, "ThreadGroup.num_threads")
            ramp, dur = _prop(tg, "RampUp"), _prop(tg, "Hold")
        if tg.tag in ("SetupThreadGroup", "PostThreadGroup"):
            continue
        if threads and not _uses_prop(threads, variables):
            add("R03", "error", "Usuarios fijos en el Thread Group",
                f"«{name}»: {threads} usuarios en duro; no se puede ajustar la carga desde el run ni dividirla entre slaves.",
                "Usar ${__P(threads,1)} (y ${__P(rampup,1)}, ${__P(duration,60)}) para el número de usuarios, rampa y duración.", name)
        if ramp and not _uses_prop(ramp, variables) and ramp not in ("0", "1"):
            add("R03", "warn", "Rampa fija", f"«{name}»: ramp-up = {ramp} en duro.", "Usar ${__P(rampup,<valor>)}.", name)
        if dur and not _uses_prop(dur, variables) and dur not in ("", "0"):
            add("R03", "warn", "Duración fija", f"«{name}»: duración = {dur} en duro.", "Usar ${__P(duration,<seg>)}.", name)

    # R04 datos CSV
    for csv in root.iter("CSVDataSet"):
        if not _enabled(csv):
            continue
        name, fn = csv.get("testname", "CSV Data Set"), _prop(csv, "filename")
        if re.match(r"^[A-Za-z]:[\\/]", fn) or "\\" in fn:
            add("R04", "error", "Ruta de Windows en CSV Data Set", f"«{name}»: {fn}",
                "Usar ${__P(data_dir,data)}/archivo.csv; los generadores son Linux.", name)
        elif fn.startswith("/"):
            add("R04", "error", "Ruta absoluta en CSV Data Set", f"«{name}»: {fn}",
                "Usar ${__P(data_dir,data)}/archivo.csv para que funcione igual en Master y Slaves.", name)
        elif fn and "data_dir" not in fn:
            add("R04", "warn", "CSV con ruta relativa sin data_dir",
                f"«{name}»: {fn}. En modo distribuido cada slave resuelve la ruta desde su propio directorio y no encuentra el archivo.",
                "Cambiar a ${__P(data_dir,data)}/" + fn.split("/")[-1] + " (el Control Center pasa data_dir automáticamente).", name)
        base_name = re.sub(r"^\$\{__P\(data_dir,[^)]*\)\}/", "data/", fn)
        if project_dir and base_name and "${" not in base_name and not re.match(r"^([A-Za-z]:|/)", base_name) \
                and not (Path(project_dir) / base_name).exists():
            add("R04", "error", "Archivo de datos inexistente", f"«{name}»: {base_name} no está en el proyecto.",
                "Subir el CSV a data/ (pestaña Data files) o corregir el nombre.", name)
        if _prop(csv, "recycle") == "true" and _prop(csv, "stopThread") == "true":
            add("R04", "info", "CSV con recycle y stopThread a la vez", f"«{name}»", "Elegir uno: reciclar datos o detener hilos al terminar.", name)

    # R05 backend listener
    bls = [b for b in root.iter("BackendListener") if _enabled(b)
           and "influxdb" in (_prop(b, "classname") or "").lower()]
    if not bls:
        add("R05", "warn", "Sin Backend Listener de InfluxDB",
            "No habrá métricas en vivo (Live monitor, Grafana) ni gráficas para el reporte de Confluence.",
            "Agregar el Backend Listener InfluxDB con application, measurement=jmeter y percentiles 90;95;99.")
    for b in bls:
        args = {}
        for el in b.iter("elementProp"):
            n, v = el.find("./stringProp[@name='Argument.name']"), el.find("./stringProp[@name='Argument.value']")
            if n is not None and n.text:
                args[n.text] = (v.text or "").strip() if v is not None else ""
        url = args.get("influxdbUrl", "")
        if re.search(r"//(localhost|127\.0\.0\.1)[:/]", url) and "${" not in url:
            add("R05", "error", "InfluxDB apuntando a localhost",
                f"influxdbUrl = {url}. En ejecución distribuida cada slave envía a su propio localhost y se pierden las métricas.",
                "Usar ${__P(influx_url," + url + ")} y pasar -Ginflux_url con la IP privada del Master.")
        if not args.get("application") or "${" in args.get("application", "") and not PROP_RE.search(args["application"]):
            add("R05", "warn", "Backend Listener sin 'application'", "", "Definir application = <APP>_<AMBIENTE>, p. ej. BlackList_QA.")
        if not any(k.startswith("TAG_") for k in args):
            add("R05", "warn", "Falta TAG_host en el Backend Listener",
                "Con 2 slaves las series de InfluxDB se sobreescriben y los conteos salen a la mitad.",
                "Agregar el argumento TAG_host = ${__machineName()}.")
        if "95" not in args.get("percentiles", ""):
            add("R05", "info", "Percentiles sin p95", f"percentiles = {args.get('percentiles', '')}", "Usar 90;95;99.")
    if len(bls) > 1:
        add("R05", "warn", "Más de un Backend Listener habilitado", f"{len(bls)} listeners duplican el envío de métricas.",
            "Dejar uno solo a nivel Test Plan.")

    # R06 listeners pesados
    for rc in root.iter("ResultCollector"):
        if not _enabled(rc):
            continue
        gui = (rc.get("guiclass") or "").split(".")[-1]
        errors_only = _prop(rc, "ResultCollector.error_logging") == "true"
        label = HEAVY.get(gui, gui or "ResultCollector")
        if errors_only:
            continue
        sev = "error" if gui == "ViewResultsFullVisualizer" else "warn"
        add("R06", sev, f"Listener «{label}» habilitado",
            "Los listeners de GUI consumen memoria/CPU del generador y alteran los tiempos en carga.",
            "Deshabilitarlo (el Control Center genera el reporte HTML). Para depurar usar solo «errors only».",
            rc.get("testname", label))

    # R07 debug
    for tag in ("DebugSampler", "DebugPostProcessor"):
        for el in root.iter(tag):
            if _enabled(el):
                add("R07", "warn", f"{tag} habilitado", "Agrega muestras/ruido al reporte.", "Deshabilitar antes de subir.",
                    el.get("testname", tag))

    http = [s for s in root.iter("HTTPSamplerProxy") if _enabled(s)]
    # R08 think time
    has_timer = any(_enabled(el) for t in TIMERS for el in root.iter(t)) or any(
        _enabled(el) and "timers" in el.tag.lower() for el in root.iter() if el.tag.startswith("kg.apc"))
    if http and not has_timer:
        add("R08", "warn", "Sin think time", "Sin timers la carga no representa usuarios reales y satura el sistema.",
            "Agregar Uniform Random Timer con ${__P(P_tt,1000)} o Constant Throughput Timer según el escenario.")
    # R09 aserciones
    if http and not any(_enabled(el) for a in ASSERTIONS for el in root.iter(a)):
        add("R09", "warn", "Sin aserciones", "Las respuestas 200 con error de negocio cuentan como éxito.",
            "Agregar Response Assertion (código + texto clave) o JSON Assertion en cada transacción crítica.")
    # R10 transacciones / nombres
    tcs = [el for el in root.iter("TransactionController") if _enabled(el)]
    if http and not tcs:
        add("R10", "info", "Sin Transaction Controllers", "El reporte agrupa por request, no por paso de negocio.",
            "Agrupar los requests de cada paso en un Transaction Controller T01_<Paso>, T02_<Paso>…")
    bad = [t.get("testname", "") for t in tcs if not re.search(r"(^|_)T\d{2}_", t.get("testname", ""))]
    if bad:
        add("R10", "warn", "Transacciones fuera de la convención", ", ".join(bad[:5]),
            "Nombrar ScriptXX_Ambiente_AppName_Objetivo_TXX_DescripcionDelPaso, p. ej. …_T01_AbrirPaginaInicio.")
    no_parent = [t.get("testname", "") for t in tcs if _prop(t, "TransactionController.parent") != "true"]
    if no_parent:
        add("R10", "warn", "Transaction Controller sin «Generate parent sample»", ", ".join(no_parent[:5]),
            "Marcar «Generate parent sample» para que el reporte muestre la transacción y no cada request suelto.")
    names = [s.get("testname", "") for s in http]
    dups = sorted({n for n in names if names.count(n) > 1 and n})
    if dups:
        add("R10", "warn", "Samplers con nombre repetido", ", ".join(dups[:5]),
            "Nombres únicos por request: si se repiten, el reporte mezcla sus estadísticas.")
    # R11 host parametrizado
    defaults = [c for c in root.iter("ConfigTestElement") if c.get("guiclass") == "HttpDefaultsGui" and _enabled(c)]
    hard = [s.get("testname", "") for s in http
            if _prop(s, "HTTPSampler.domain") and "${" not in _prop(s, "HTTPSampler.domain")]
    if hard:
        add("R11", "warn", "Host en duro en los requests", f"{len(hard)} request(s), p. ej. «{hard[0]}».",
            "Dejar el dominio vacío en cada request y definirlo en HTTP Request Defaults con ${__P(P_DNS,<host-qa>)}.")
    if http and not defaults:
        add("R11", "warn", "Sin HTTP Request Defaults", "Cambiar de ambiente obliga a editar cada request.",
            "Agregar HTTP Request Defaults al inicio del Thread Group con protocolo, ${__P(P_DNS,…)}, puerto y timeouts.")
    for d in defaults:
        if not _prop(d, "HTTPSampler.connect_timeout") or not _prop(d, "HTTPSampler.response_timeout"):
            add("R11", "info", "Sin timeouts en HTTP Request Defaults", "",
                "Definir connect/response timeout (p. ej. 10000/60000 ms) para no colgar hilos.", d.get("testname", ""))
    # R12 recursos embebidos
    emb = [s.get("testname", "") for s in http if _prop(s, "HTTPSampler.image_parser") == "true"]
    if emb:
        add("R12", "warn", "Descarga de recursos embebidos activa", ", ".join(emb[:3]),
            "Desactivar «Retrieve All Embedded Resources» salvo en pruebas de front.")
    # R13 cookie manager
    if http and not any(_enabled(el) for el in root.iter("CookieManager")):
        add("R13", "info", "Sin HTTP Cookie Manager", "", "Agregarlo si la aplicación maneja sesión por cookies.")
    # R14 credenciales en duro
    for el in root.iter("stringProp"):
        txt = (el.text or "").strip()
        if not txt or len(txt) > 4000:
            continue
        if el.get("name") == "Header.value" and AUTH_RE.search(txt):
            add("R14", "error", "Credencial en duro en un header", f"Authorization = {txt[:12]}…",
                "Obtener el token en un paso previo o leerlo de ${__P(token)} / CSV; nunca subir tokens reales.")
            break
        if SECRET_RE.search(txt):
            add("R14", "error", "Posible contraseña o secreto en duro", f"«{SECRET_RE.search(txt).group(0)[:40]}…»",
                "Mover a variables del CSV de datos o a propiedades (-J); no versionar credenciales reales.")
            break
    # R19 parámetros P_ / R20 correlaciones C_
    for csv in root.iter("CSVDataSet"):
        if not _enabled(csv):
            continue
        names = [n.strip() for n in _prop(csv, "variableNames").split(",") if n.strip()]
        badp = [n for n in names if not n.startswith("P_")]
        if badp:
            add("R19", "warn", "Parámetros sin prefijo P_", f"«{csv.get('testname', 'CSV')}»: {', '.join(badp[:6])}",
                "Nombrar las columnas del CSV como P_UserName, P_Password… (y usar ${P_UserName} en los requests).",
                csv.get("testname", ""))
    badc = []
    for tag, prop in EXTRACTORS.items():
        for el in root.iter(tag):
            if not _enabled(el):
                continue
            for ref in (r.strip() for r in _prop(el, prop).split(";") if r.strip()):
                if not ref.startswith("C_"):
                    badc.append(f"{ref} ({el.get('testname', tag)})")
    if badc:
        add("R20", "warn", "Correlaciones sin prefijo C_", ", ".join(badc[:6]),
            "Nombrar las variables extraídas como C_AccessToken, C_SessionId… para distinguirlas de los parámetros.")

    # R16 tamaño / R17 deshabilitados
    size_mb = path.stat().st_size / 1024 / 1024
    if size_mb > 5:
        add("R16", "info", "Script muy grande", f"{size_mb:.1f} MB", "Dividir por módulo o eliminar elementos deshabilitados.")
    disabled = sum(1 for el in root.iter() if el.get("enabled") == "false")
    if disabled > 25:
        add("R17", "info", "Muchos elementos deshabilitados", f"{disabled} elementos", "Eliminar lo que ya no se usa (queda en el historial de git).")
    return _result(rel, findings)


def _result(rel, findings):
    """Group repeated findings (same rule + title) and score each distinct problem once."""
    grouped = {}
    for f in findings:
        key = (f["rule"], f["severity"], f["title"])
        g = grouped.setdefault(key, {**f, "occurrences": 0, "elements": [], "details": []})
        g["occurrences"] += 1
        if f["element"] and f["element"] not in g["elements"]:
            g["elements"].append(f["element"])
        if f["detail"] and f["detail"] not in g["details"]:
            g["details"].append(f["detail"])
    items = []
    for g in grouped.values():
        shown = g["details"][:3]
        more = len(g["details"]) - len(shown)
        g["detail"] = " · ".join(shown) + (f" (+{more} más)" if more > 0 else "")
        if g["occurrences"] > 1:
            g["title"] = f"{g['title']} ({g['occurrences']}×)"
        g["element"] = ", ".join(g["elements"][:5])
        items.append(g)
    counts = {s: sum(1 for f in items if f["severity"] == s) for s in SEV_WEIGHT}
    score = max(0, 100 - sum(SEV_WEIGHT[f["severity"]] for f in items))
    grade = "A" if score >= 90 else "B" if score >= 75 else "C" if score >= 55 else "D"
    order = {"error": 0, "warn": 1, "info": 2}
    return {"script": rel, "score": score, "grade": grade, "counts": counts,
            "findings": sorted(items, key=lambda f: (order[f["severity"]], f["rule"]))}


def _tagged(project_dir):
    sh = Path(project_dir) / "run_by_tag.sh"
    if not sh.is_file():
        return None
    return set(re.findall(r'SCRIPT="([^"]+)"', sh.read_text(errors="replace")))


def review_project(project_dir):
    project_dir = Path(project_dir)
    tagged = _tagged(project_dir)
    out = [review_file(f, project_dir, tagged) for f in sorted((project_dir / "tests").rglob("*.jmx"))]
    return out


def project_of(path):
    for parent in Path(path).resolve().parents:
        if (parent / "run_by_tag.sh").is_file():
            return parent
    return None


def to_markdown(results, title="Revisión de calidad de scripts JMeter"):
    lines = [f"## {title}", "", "| Script | Puntaje | Errores | Advertencias | Sugerencias |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        c = r["counts"]
        lines.append(f"| `{r['script']}` | **{r['score']}** ({r['grade']}) | {c['error']} | {c['warn']} | {c['info']} |")
    for r in results:
        if not r["findings"]:
            continue
        lines += ["", f"### `{r['script']}` — {r['score']}/100", ""]
        for f in r["findings"]:
            lines.append(f"- **{SEV_LABEL[f['severity']]} {f['rule']} · {f['title']}**"
                         + (f" — {f['detail']}" if f["detail"] else "") + f"  \n  ➜ {f['fix']}")
    lines += ["", "_Reglas R01–R18: ver «Guía de scripting y uso del JMeter Control Center»._"]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Revisión de calidad de scripts JMeter (.jmx)")
    ap.add_argument("paths", nargs="*", help=".jmx o carpetas de proyecto (default: todo el repositorio)")
    ap.add_argument("--changed", metavar="BASE", help="solo los .jmx cambiados respecto a BASE (git)")
    ap.add_argument("--md", metavar="FILE", help="escribir el reporte en Markdown (p. ej. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--fail-on", choices=("error", "warn", "never"), default="error")
    a = ap.parse_args(argv)
    repo = Path(os.environ.get("SR_REPO_ROOT") or Path(__file__).resolve().parents[2])
    files = []
    if a.changed:
        import subprocess
        out = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", "--diff-filter=AM", a.changed, "--", "*.jmx"],
                             capture_output=True, text=True).stdout
        files = [repo / p for p in out.split() if p.endswith(".jmx")]
    for p in a.paths:
        p = Path(p)
        files += sorted(p.rglob("*.jmx")) if p.is_dir() else [p]
    if not a.changed and not a.paths:
        files = sorted(f for f in repo.glob("*-jmeter-framework/tests/**/*.jmx"))
    results = []
    for f in files:
        proj = project_of(f)
        results.append(review_file(f, proj, _tagged(proj) if proj else None))
        if proj:
            results[-1]["script"] = f"{proj.name}/{results[-1]['script']}"
    md = to_markdown(results) if results else "No hay scripts .jmx para revisar."
    if a.md:
        with open(a.md, "a", encoding="utf-8") as fh:
            fh.write(md + "\n")
    print(md)
    if a.fail_on == "never":
        return 0
    bad = sum(r["counts"]["error"] + (r["counts"]["warn"] if a.fail_on == "warn" else 0) for r in results)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
