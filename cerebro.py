#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEGUNDO CÉREBRO — motor de memória persistente para Claude Code e Codex.

Comandos:
  hook-start        (Claude Code SessionStart)      injeta contexto do projeto
  hook-prompt       (Claude Code UserPromptSubmit)  pesquisa notas relacionadas com o pedido
  hook-stop         (Claude Code Stop)              regista a linha do tempo e pede o registo final
  record            regista decisões/problemas/aprendizagens (JSON via stdin ou --file)
  codex-notify      (Codex notify)                  regista a linha do tempo de uma sessão Codex
  context           contexto para início de tarefa (usado pelo Codex)  --cwd X --query "..."
  search "termos"   pesquisa no cofre
  reindex           regenera índices e painel
  bootstrap         importa memórias e histórico do Claude Code, descobre projetos
  doctor            diagnóstico
Só usa a biblioteca padrão do Python.
"""
import sys, os, json, re, math, unicodedata, datetime as dt, traceback
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

HOME = Path(os.path.expanduser("~"))
BASE = Path(__file__).resolve().parent
CFG_PATH = BASE / "config.json"
STATE = BASE / "estado"
LOG = BASE / "cerebro.log"
SCRIPT_CMD = "python " + str(BASE / "cerebro.py").replace("\\", "/")

DEFAULT_CFG = {
    "cofre": str(HOME / "SegundoCerebro"),  # muda em config.json
    "aliases_projetos": {},
    "ignorar_caminhos": [str(HOME / "AppData" / "Local" / "Temp"), str(BASE)],
    "contexto_max_chars": 3500,
    "pesquisa_max_chars": 2400,
    "pesquisa_top": 6,
    "pesquisa_min_score": 1.5,
    "pedir_registo": True,
    "registo_min_edicoes": 1,
    "registo_min_ferramentas": 5,
    "registo_em_tarefas_agendadas": False,
}

F = {
    "inicio": "00 Início",
    "projetos": "01 Projetos",
    "sessoes": "02 Sessões",
    "decisoes": "03 Decisões",
    "problemas": "04 Problemas e Soluções",
    "aprend": "05 Aprendizagens",
    "padroes": "06 Padrões e Preferências",
    "tec": "07 Tecnologias e Ferramentas",
    "config": "08 Configurações",
    "tarefas": "09 Tarefas",
    "recursos": "10 Recursos",
    "templates": "90 Templates",
    "sistema": "99 Sistema",
}
NAO_PESQUISAR = {F["inicio"], F["templates"], F["sistema"], ".obsidian", ".trash"}

STOP = set("""
a o e de da do das dos em no na nos nas um uma uns umas para por com sem que se ao aos as os
mais muito pouco como qual quais quando onde porque porque isso isto esse essa este esta ele ela
eu tu nos voce voces meu minha seu sua nosso ja nao sim ser estar ter foi sao era ate entre sobre
faz fazer feito quero queria preciso pode podes agora tudo todo toda cada outro outra mesmo tambem
the and for with this that from are was were have has you your not but all can will just into out
then them they its our use using what when how why who which also than only very more most some
like make made need want get got let lets please ok sim fica vai vou esta estou ainda depois antes
""".split())


# --------------------------------------------------------------------------- utilidades
def cfg():
    c = dict(DEFAULT_CFG)
    try:
        c.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
    except Exception:
        pass
    return c


CFG = cfg()
V = Path(CFG["cofre"])


def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except Exception:
        pass


def now():
    return dt.datetime.now()


def today():
    return now().strftime("%Y-%m-%d")


def stamp():
    return now().strftime("%Y-%m-%d %H:%M")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s).lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def tokens(s):
    return [t for t in re.findall(r"[a-z0-9_]{3,}", norm(s)) if t not in STOP]


def safe_name(s, maxlen=80):
    s = re.sub(r'[\\/:*?"<>|#^\[\]\r\n\t]+', " ", str(s))
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return (s[:maxlen].rstrip(" .-")) or "Sem título"


def rel(p):
    try:
        return Path(p).relative_to(V).as_posix()
    except Exception:
        return str(p)


def link(p_or_name, alias=None):
    name = Path(p_or_name).stem if (isinstance(p_or_name, Path) or str(p_or_name).endswith(".md")) else str(p_or_name)
    return f"[[{name}|{alias}]]" if alias else f"[[{name}]]"


def read(p):
    try:
        return Path(p).read_text(encoding="utf-8")
    except Exception:
        return ""


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def jload(p, default):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:
        return default


def jsave(p, obj):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def clip(s, n):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


# --------------------------------------------------------------------------- frontmatter
def parse_fm(text):
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw, body = text[4:end], text[end + 4:].lstrip("\n")
    fm, key = {}, None
    for line in raw.split("\n"):
        m = re.match(r"^([A-Za-z0-9_\-À-ÿ]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if val == "":
                fm[key] = []
            elif val.startswith("[") and val.endswith("]") and not val.startswith("[["):
                fm[key] = [unq(x) for x in val[1:-1].split(",") if x.strip()]
            elif val in ("true", "false"):
                fm[key] = val == "true"
            else:
                fm[key] = unq(val)
        elif key and re.match(r"^\s*-\s+", line):
            if not isinstance(fm.get(key), list):
                fm[key] = []
            fm[key].append(unq(re.sub(r"^\s*-\s+", "", line)))
    return fm, body


def unq(v):
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        if v[0] == '"':
            try:
                return json.loads(v)
            except Exception:
                return v[1:-1]
        return v[1:-1]
    return v


def q(v):
    v = str(v)
    if re.fullmatch(r"[A-Za-z0-9_\-. À-ÿ]+", v) and not v.strip() != v and v.lower() not in ("true", "false", "null", "yes", "no"):
        return v
    return json.dumps(v, ensure_ascii=False)


def dump_fm(fm):
    out = ["---"]
    for k, v in fm.items():
        if isinstance(v, bool):
            out.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            out.append(f"{k}: {v}")
        elif isinstance(v, list):
            if not v:
                out.append(f"{k}: []")
            else:
                out.append(f"{k}:")
                out += [f"  - {q(x)}" for x in v]
        else:
            out.append(f"{k}: {q(v)}")
    out.append("---")
    return "\n".join(out) + "\n"


def write_note(p, fm, body):
    write(p, dump_fm(fm) + body.rstrip() + "\n")


def update_fm(p, **fields):
    fm, body = parse_fm(read(p))
    for k, v in fields.items():
        if v is None:
            continue
        if isinstance(v, list) and isinstance(fm.get(k), list):
            for x in v:
                if x not in fm[k]:
                    fm[k].append(x)
        else:
            fm[k] = v
    write_note(p, fm, body)


def add_under(p, heading, line, top=False, dedupe=True):
    """Acrescenta `line` à secção `heading` (## ...) de uma nota."""
    text = read(p).replace("\r\n", "\n")
    lines = text.split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        write(p, text.rstrip() + f"\n\n{heading}\n{line}\n")
        return True
    j = i + 1
    while j < len(lines) and not re.match(r"^#{1,2} ", lines[j]):
        j += 1
    section = "\n".join(lines[i + 1: j])
    if dedupe and norm(re.sub(r"\s+", " ", line.strip("- []x").strip()))[:120] in norm(re.sub(r"\s+", " ", section)):
        return False
    if top:
        k = i + 1
        while k < j and (lines[k].strip() == "" or lines[k].startswith(">") or lines[k].startswith("<!--")):
            k += 1
        lines.insert(k, line)
    else:
        k = j
        while k > i + 1 and lines[k - 1].strip() == "":
            k -= 1
        lines.insert(k, line)
    write(p, "\n".join(lines))
    return True


# --------------------------------------------------------------------------- projetos
def is_ignored(cwd):
    c = norm(str(cwd)).replace("\\", "/")
    for ig in CFG.get("ignorar_caminhos", []):
        if c.startswith(norm(ig).replace("\\", "/")):
            return True
    return False


def detect_project(cwd):
    if not cwd:
        return "Geral", None
    p = Path(cwd)
    c = norm(str(p)).replace("\\", "/").rstrip("/")
    best = None
    for k, name in (CFG.get("aliases_projetos") or {}).items():
        kk = norm(k).replace("\\", "/").rstrip("/")
        if c == kk or c.startswith(kk + "/"):
            if not best or len(kk) > len(best[0]):
                best = (kk, name)
    if best:
        return best[1], None
    root = p
    for cand in [p] + list(p.parents):
        if (cand / ".git").exists():
            root = cand
            break
    if len(root.parts) <= 1 or root == HOME:
        return "Geral", root
    return safe_name(root.name, 60), root


STACK_HINTS = [
    ("package.json", "Node.js"), ("tsconfig.json", "TypeScript"), ("requirements.txt", "Python"),
    ("pyproject.toml", "Python"), ("Cargo.toml", "Rust"), ("go.mod", "Go"), ("Dockerfile", "Docker"),
    (".mq5", "MQL5"), (".mq4", "MQL4"), (".py", "Python"), (".ts", "TypeScript"), (".js", "JavaScript"),
    (".R", "R"), (".ipynb", "Jupyter"), (".html", "HTML e CSS"), (".bat", "Windows Batch"), (".ps1", "PowerShell"),
]


def guess_stack(root, limit=3000):
    found, n = set(), 0
    if not root or not Path(root).exists():
        return []
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in ("node_modules", ".git", "venv", ".venv", "__pycache__", "dist", "build")]
        if dp.count(os.sep) - str(root).count(os.sep) > 2:
            dns[:] = []
        for fn in fns:
            n += 1
            for hint, tech in STACK_HINTS:
                if fn == hint or (hint.startswith(".") and fn.endswith(hint)):
                    found.add(tech)
            if n > limit:
                return sorted(found)
    return sorted(found)


def project_path(name):
    return V / F["projetos"] / f"{safe_name(name, 60)}.md"


def ensure_project(name, root=None):
    p = project_path(name)
    if p.exists():
        return p
    stack = guess_stack(root) if root else []
    fm = {
        "tipo": "projeto", "estado": "ativo", "caminho": str(root or ""), "objetivo": "",
        "stack": stack, "criado": today(), "atualizado": today(), "tags": ["projeto"],
    }
    stack_links = ", ".join(f"[[{t}]]" for t in stack) or "_(por detetar)_"
    for t in stack:
        ensure_tech(t, name)
    body = f"""# {name}

> [!abstract] Projeto
> **Caminho:** `{root or '—'}`
> **Estado:** ativo · **Stack:** {stack_links}

## Objetivo
_(preenchido automaticamente quando o assistente o identificar)_

## Estado atual

## Stack e ferramentas
{chr(10).join(f'- [[{t}]]' for t in stack)}

## Estrutura e configurações importantes

## Notas do projeto

## Histórico de sessões
"""
    write_note(p, fm, body)
    log(f"projeto criado: {name}")
    return p


def ensure_tech(tech, project=None):
    tech = safe_name(tech, 50)
    p = V / F["tec"] / f"{tech}.md"
    if not p.exists():
        write_note(p, {"tipo": "tecnologia", "criado": today(), "tags": ["tecnologia"]},
                   f"# {tech}\n\n> [!info] Tecnologia / ferramenta\n\n## Usado em\n\n## Notas e truques\n")
    if project:
        add_under(p, "## Usado em", f"- [[{safe_name(project, 60)}]]")
    return p


# --------------------------------------------------------------------------- sessões
def sess_state(sid):
    return jload(STATE / "sessoes" / f"{sid}.json", {})


def save_sess_state(sid, st):
    jsave(STATE / "sessoes" / f"{sid}.json", st)


def ensure_session_note(sid, project, tool, title, cwd, when=None, imported=False):
    st = sess_state(sid)
    if st.get("nota") and (V / st["nota"]).exists():
        return V / st["nota"], st
    when = when or now()
    title = clip(re.sub(r"<[^>]+>", " ", title or "Sessão"), 70)
    fname = f"{when:%Y-%m-%d} {safe_name(project, 40)} — {safe_name(title, 60)} ({sid[:6]})"
    p = V / F["sessoes"] / f"{when:%Y}" / f"{when:%m}" / f"{fname}.md"
    fm = {
        "tipo": "sessao", "ferramenta": tool, "projeto": f"[[{safe_name(project, 60)}]]",
        "data": f"{when:%Y-%m-%d}", "hora": f"{when:%H:%M}", "sessao_id": sid, "cwd": str(cwd or ""),
        "titulo": title, "importado": imported, "tags": ["sessao", tool],
    }
    body = f"# {title}\n\n> [!note] Sessão {tool} · [[{safe_name(project, 60)}]] · {when:%Y-%m-%d %H:%M}\n\n## Resumo\n\n## Linha do tempo\n"
    write_note(p, fm, body)
    st.update({"nota": rel(p), "projeto": project, "ferramenta": tool, "offset": st.get("offset", 0)})
    save_sess_state(sid, st)
    pp = ensure_project(project)
    add_under(pp, "## Histórico de sessões", f"- {when:%Y-%m-%d} {link(p, title)}", top=True)
    update_fm(pp, atualizado=f"{when:%Y-%m-%d}")
    return p, st


def clean_prompt(t):
    t = re.sub(r"<(system-reminder|command-message|local-command-stdout|pasted_content)[^>]*>.*?</\1[^>]*>", " ", t, flags=re.S)
    t = re.sub(r"<command-name>(.*?)</command-name>", r"\1", t, flags=re.S)
    t = re.sub(r"<[^>]{1,40}>", " ", t)
    return t.strip()


def parse_transcript(path, start=0):
    out = {"prompts": [], "edits": [], "cmds": [], "tools": 0, "last_text": "", "title": "",
           "total": 0, "first_ts": None, "cwd": None, "scheduled": False}
    try:
        f = open(path, encoding="utf-8", errors="replace")
    except Exception:
        return out
    with f:
        for i, line in enumerate(f):
            out["total"] = i + 1
            try:
                o = json.loads(line)
            except Exception:
                continue
            t = o.get("type")
            if t in ("ai-title", "summary"):
                out["title"] = o.get("aiTitle") or o.get("title") or o.get("summary") or out["title"]
            if i < start or o.get("isSidechain"):
                continue
            if t not in ("user", "assistant"):
                continue
            out["cwd"] = out["cwd"] or o.get("cwd")
            if not out["first_ts"] and o.get("timestamp"):
                out["first_ts"] = o["timestamp"]
            c = (o.get("message") or {}).get("content")
            if t == "user":
                if o.get("isMeta") or o.get("toolUseResult") is not None:
                    continue
                texts = [c] if isinstance(c, str) else [x.get("text", "") for x in (c or []) if isinstance(x, dict) and x.get("type") == "text"]
                for tx in texts:
                    if tx.lstrip().startswith("<scheduled-task"):
                        out["scheduled"] = True
                        m = re.search(r'name="([^"]+)"', tx)
                        out["prompts"].append(f"(tarefa agendada: {m.group(1) if m else '?'})")
                        continue
                    ct = clean_prompt(tx)
                    if ct and not ct.startswith("Tool loaded") and not ct.startswith("[Request interrupted"):
                        out["prompts"].append(ct)
            else:
                for x in c or []:
                    if not isinstance(x, dict):
                        continue
                    if x.get("type") == "text" and x.get("text", "").strip():
                        out["last_text"] = x["text"]
                    elif x.get("type") == "tool_use":
                        out["tools"] += 1
                        n, inp = x.get("name", ""), x.get("input") or {}
                        if n in ("Edit", "Write", "MultiEdit", "NotebookEdit") and inp.get("file_path"):
                            if inp["file_path"] not in out["edits"]:
                                out["edits"].append(inp["file_path"])
                        elif n in ("Bash", "PowerShell") and inp.get("command"):
                            out["cmds"].append(clip(inp["command"], 140))
    return out


def timeline_entry(tr, when=None):
    when = when or now()
    lines = [f"### {when:%H:%M} — {clip(tr['prompts'][0] if tr['prompts'] else 'continuação', 90)}"]
    for ptxt in tr["prompts"][:3]:
        lines.append("> " + clip(ptxt, 400))
    if tr["edits"]:
        lines.append("- **Ficheiros alterados:** " + ", ".join(f"`{e}`" for e in tr["edits"][:15]))
    if tr["cmds"]:
        lines.append("- **Comandos:** " + " · ".join(f"`{c}`" for c in tr["cmds"][:6]))
    if tr["last_text"]:
        lines.append("- **Resposta final:** " + clip(tr["last_text"], 700))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- pesquisa
def iter_notes():
    if not V.exists():
        return
    for p in V.rglob("*.md"):
        r = p.relative_to(V).parts
        if r and r[0] in NAO_PESQUISAR:
            continue
        yield p


def load_index():
    idx = jload(STATE / "indice.json", {})
    seen, changed = set(), False
    for p in iter_notes():
        r = rel(p)
        seen.add(r)
        try:
            mt = p.stat().st_mtime
        except Exception:
            continue
        e = idx.get(r)
        if e and e.get("mt") == mt:
            continue
        text = read(p)
        fm, body = parse_fm(text)
        title = p.stem
        tf = {}
        for tk in tokens(title) * 3 + tokens(" ".join(map(str, fm.get("tags", []) if isinstance(fm.get("tags"), list) else [fm.get("tags", "")]))) * 2 + tokens(body):
            tf[tk] = tf.get(tk, 0) + 1
        proj = fm.get("projeto", "")
        proj = re.sub(r"[\[\]]", "", proj.split("|")[0]) if isinstance(proj, str) else ""
        if fm.get("tipo") == "projeto":
            proj = title
        idx[r] = {"mt": mt, "t": title, "tipo": fm.get("tipo", ""), "proj": proj, "data": fm.get("data") or fm.get("atualizado") or fm.get("criado") or "",
                  "imp": str(fm.get("importado", "")).lower() == "true", "tf": tf, "len": sum(tf.values()) or 1}
        changed = True
    for r in list(idx):
        if r not in seen:
            del idx[r]
            changed = True
    if changed:
        jsave(STATE / "indice.json", idx)
    return idx


TIPO_PESO = {"decisao": 1.35, "problema": 1.45, "aprendizagem": 1.35, "projeto": 1.2, "configuracao": 1.3,
             "tecnologia": 0.9, "preferencias": 1.1, "padroes": 1.1, "sessao": 1.0, "tarefas": 1.0}


def search(query, project=None, k=6, exclude=()):
    qt = list(dict.fromkeys(tokens(query)))
    if not qt:
        return []
    idx = load_index()
    N = len(idx) or 1
    avg = sum(e["len"] for e in idx.values()) / N if idx else 1
    df = {t: sum(1 for e in idx.values() if t in e["tf"]) for t in qt}
    res = []
    for r, e in idx.items():
        if r in exclude:
            continue
        s = 0.0
        hits = 0
        for t in qt:
            f = e["tf"].get(t, 0)
            if not f:
                continue
            hits += 1
            idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * (f * 2.2) / (f + 1.2 * (0.25 + 0.75 * e["len"] / avg))
        if not hits:
            continue
        s *= (0.6 + 0.4 * hits / len(qt))
        s *= TIPO_PESO.get(e["tipo"], 1.0)
        if e["imp"]:
            s *= 0.8
        if project and e["proj"] and norm(e["proj"]) == norm(project):
            s *= 1.25
        res.append((s, r, e))
    res.sort(key=lambda x: -x[0])
    return res[:k]


def snippet(relpath, query, n=230):
    _, body = parse_fm(read(V / relpath))
    qt = set(tokens(query))
    best, bs = "", -1
    for line in body.split("\n"):
        l = line.strip()
        if len(l) < 12 or l.startswith("#") and len(l) < 30:
            continue
        sc = len(qt & set(tokens(l)))
        if sc > bs:
            best, bs = l, sc
    return clip(re.sub(r"^[>\-*\s]+", "", best), n)


TIPO_ROTULO = {"decisao": "decisão", "problema": "problema→solução", "aprendizagem": "aprendizagem", "projeto": "projeto",
               "sessao": "sessão", "tecnologia": "tecnologia", "configuracao": "configuração", "tarefas": "tarefas",
               "preferencias": "preferências", "padroes": "padrões"}


def format_results(results, query, project, maxc):
    out, used = [], 0
    for s, r, e in results:
        other = e["proj"] and project and norm(e["proj"]) != norm(project)
        tag = TIPO_ROTULO.get(e["tipo"]) or ("memória" if e["tipo"].startswith("memoria") else e["tipo"] or "nota")
        where = f"outro projeto: {e['proj']}" if other else (e["proj"] or "geral")
        line = f"- [{tag} · {where}{' · ' + e['data'] if e['data'] else ''}] **{e['t']}** — {snippet(r, query)}\n  ↳ `{(V / r).as_posix()}`"
        if used + len(line) > maxc:
            break
        out.append(line)
        used += len(line)
    return "\n".join(out)


# --------------------------------------------------------------------------- contexto
def section(text, heading, maxlines=12):
    lines = text.replace("\r\n", "\n").split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == heading)
    except StopIteration:
        return []
    out = []
    for l in lines[i + 1:]:
        if re.match(r"^#{1,2} ", l):
            break
        if l.strip() and not l.strip().startswith("_("):
            out.append(l.rstrip())
        if len(out) >= maxlines:
            break
    return out


def project_context(project, root=None):
    p = ensure_project(project, root)
    fm, body = parse_fm(read(p))
    parts = [f"🧠 SEGUNDO CÉREBRO ativo — cofre Obsidian `{V.as_posix()}`.",
             f"Projeto atual: **{project}** (nota: `{p.as_posix()}`)"]
    if fm.get("objetivo"):
        parts.append(f"Objetivo: {fm['objetivo']}")
    est = section(body, "## Estado atual", 5)
    if est:
        parts.append("Estado atual:\n" + "\n".join(est))
    if fm.get("stack"):
        parts.append("Stack: " + ", ".join(fm["stack"] if isinstance(fm["stack"], list) else [fm["stack"]]))
    notas = section(body, "## Notas do projeto", 14)
    if notas:
        parts.append("Notas do projeto:\n" + "\n".join(notas))
    hist = section(body, "## Histórico de sessões", 6)
    if hist:
        parts.append("Últimas sessões:\n" + "\n".join(hist))
    tp = V / F["tarefas"] / f"{safe_name(project, 60)} — Tarefas.md"
    pend = [l for l in read(tp).split("\n") if l.strip().startswith("- [ ]")][:8]
    if pend:
        parts.append("Tarefas pendentes:\n" + "\n".join(pend))
    prefs = []
    for nm in ("Preferências pessoais.md", "Padrões de trabalho.md"):
        prefs += [l for l in read(V / F["padroes"] / nm).split("\n") if l.startswith("- ")][-10:]
    if prefs:
        parts.append("Preferências e padrões do utilizador:\n" + "\n".join(prefs[-16:]))
    parts.append(
        "Como usar: a cada pedido, o sistema injeta automaticamente notas relacionadas (incluindo de OUTROS projetos). "
        "Lê as notas relevantes antes de agir e reaproveita soluções já usadas. Pesquisa manual: "
        f"`{SCRIPT_CMD} search \"termos\"`. O registo no fim da tarefa é pedido automaticamente.")
    txt = "\n\n".join(parts)
    return txt[: CFG["contexto_max_chars"]]


# --------------------------------------------------------------------------- memória do Claude Code
def sanitize_cwd(cwd):
    return re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def memory_titles(memdir):
    titles = {}
    for line in read(memdir / "MEMORY.md").split("\n"):
        m = re.match(r"^\s*-\s*\[([^\]]+)\]\(([^)]+)\)", line)
        if m:
            titles[Path(m.group(2)).stem] = m.group(1)
    return titles


def sync_memory(memdir, project):
    memdir = Path(memdir)
    if not memdir.exists():
        return 0
    st = jload(STATE / "memorias.json", {})
    titles = memory_titles(memdir)
    name_by_slug = {}
    files = [f for f in memdir.glob("*.md") if f.name != "MEMORY.md"]
    metas = {}
    for f in files:
        fm, body = parse_fm(read(f))
        slug = fm.get("name") or f.stem
        title = safe_name(titles.get(f.stem) or titles.get(slug) or slug.replace("-", " ").title(), 70)
        name_by_slug[slug] = title
        name_by_slug[f.stem] = title
        metas[f] = (fm, body, title)
    n = 0
    for f, (fm, body, title) in metas.items():
        mt = f.stat().st_mtime
        key = str(f)
        typ = (fm.get("metadata") if isinstance(fm.get("metadata"), str) else "") or ""
        m = re.search(r"(?m)^\s*type:\s*(\w+)", read(f)[:600])
        typ = m.group(1) if m else "project"
        folder = {"user": F["padroes"], "feedback": F["padroes"], "reference": F["recursos"]}.get(typ, f"{F['projetos']}/{safe_name(project, 60)}")
        target = V / folder / f"{title}.md"
        if st.get(key, {}).get("mt") == mt and target.exists():
            continue
        body2 = re.sub(r"\[\[([^\]|]+)\]\]", lambda mm: f"[[{name_by_slug.get(mm.group(1), mm.group(1))}]]", body)
        nfm = {"tipo": f"memoria-{typ}", "origem": "claude-memory", "projeto": f"[[{safe_name(project, 60)}]]",
               "descricao": fm.get("description", ""), "fonte": f.as_posix(), "atualizado": dt.datetime.fromtimestamp(mt).strftime("%Y-%m-%d"),
               "tags": ["memoria", typ]}
        write_note(target, nfm, f"# {title}\n\n> [!quote] Memória do Claude Code ({typ})\n> {fm.get('description', '')}\n\n{body2}\n\n---\n*Sincronizado automaticamente de `{f.name}`.*")
        if typ == "project":
            add_under(ensure_project(project), "## Notas do projeto", f"- [[{title}]] — {clip(fm.get('description', ''), 140)}")
        st[key] = {"mt": mt, "nota": rel(target)}
        n += 1
    jsave(STATE / "memorias.json", st)
    return n


# --------------------------------------------------------------------------- registo estruturado
def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def txt(x, *keys):
    if isinstance(x, dict):
        for k in keys:
            if x.get(k):
                return str(x[k])
        return " ".join(str(v) for v in x.values())
    return str(x)


def record(data, sid=None):
    sid = sid or data.get("sessao") or data.get("sessao_id") or "manual-" + now().strftime("%Y%m%d%H%M%S")
    st = sess_state(sid)
    cwd = data.get("cwd") or st.get("cwd") or os.getcwd()
    project = data.get("projeto") or st.get("projeto") or detect_project(cwd)[0]
    tool = data.get("ferramenta") or st.get("ferramenta") or "claude-code"
    titulo = data.get("titulo") or "Execução"
    sp, st = ensure_session_note(sid, project, tool, titulo, cwd)
    pp = ensure_project(project, detect_project(cwd)[1])
    P = f"[[{safe_name(project, 60)}]]"
    S = link(sp)
    created = []

    for d in as_list(data.get("decisoes")):
        t = safe_name(txt(d, "titulo", "decisao"), 70)
        p = V / F["decisoes"] / f"{today()} {t}.md"
        if isinstance(d, dict):
            body = f"# {t}\n\n> [!important] Decisão · {P} · {today()}\n\n## Contexto\n{d.get('contexto', '')}\n\n## Decisão\n{d.get('decisao', t)}\n\n## Porquê\n{d.get('porque', '')}\n\n## Origem\n{S}\n"
        else:
            body = f"# {t}\n\n> [!important] Decisão · {P} · {today()}\n\n## Decisão\n{d}\n\n## Origem\n{S}\n"
        write_note(p, {"tipo": "decisao", "projeto": P, "data": today(), "sessao": S, "tags": ["decisao"]}, body)
        created.append(("Decisão", p))

    for pr in as_list(data.get("problemas")):
        t = safe_name(txt(pr, "titulo", "problema"), 70)
        p = V / F["problemas"] / f"{t}.md"
        sol = pr.get("solucao", "") if isinstance(pr, dict) else ""
        causa = pr.get("causa", "") if isinstance(pr, dict) else ""
        occ = f"## Ocorrência {today()} · {P}\n- **Problema:** {txt(pr, 'problema', 'titulo')}\n" + (f"- **Causa:** {causa}\n" if causa else "") + f"- **Solução:** {sol or '_(por resolver)_'}\n- **Sessão:** {S}\n"
        if p.exists():
            write(p, read(p).rstrip() + "\n\n" + occ)
            update_fm(p, estado="resolvido" if sol else None, data=today())
        else:
            write_note(p, {"tipo": "problema", "projeto": P, "estado": "resolvido" if sol else "aberto", "data": today(), "tags": ["problema"]},
                       f"# {t}\n\n> [!bug] Problema → Solução\n\n{occ}")
        created.append(("Problema", p))

    for a in as_list(data.get("aprendizagens")):
        t = safe_name(txt(a, "titulo", "aprendizagem"), 70)
        det = a.get("detalhe", "") if isinstance(a, dict) else ""
        p = V / F["aprend"] / f"{t}.md"
        entry = f"- {today()} · {P} · {S}" + (f"\n  {det}" if det else "")
        if p.exists():
            add_under(p, "## Ocorrências", entry)
        else:
            write_note(p, {"tipo": "aprendizagem", "projeto": P, "data": today(), "tags": ["aprendizagem"]},
                       f"# {t}\n\n> [!tip] Aprendizagem\n> {txt(a, 'aprendizagem', 'titulo')}\n\n{det}\n\n## Ocorrências\n{entry}\n")
        created.append(("Aprendizagem", p))

    for key, nm, tipo, cal in (("preferencias", "Preferências pessoais", "preferencias", "Preferências pessoais do utilizador"),
                               ("padroes", "Padrões de trabalho", "padroes", "Padrões de trabalho recorrentes")):
        items = as_list(data.get(key))
        if not items:
            continue
        p = V / F["padroes"] / f"{nm}.md"
        if not p.exists():
            write_note(p, {"tipo": tipo, "tags": [tipo]}, f"# {nm}\n\n> [!quote] {cal} — atualizado automaticamente\n\n## Lista\n")
        for it in items:
            add_under(p, "## Lista", f"- {txt(it)} _({today()} · {P})_")
        created.append((nm, p))

    techs = [safe_name(txt(t), 50) for t in as_list(data.get("tecnologias"))]
    for t in techs:
        ensure_tech(t, project)
        add_under(pp, "## Stack e ferramentas", f"- [[{t}]]")
    if techs:
        update_fm(pp, stack=techs)

    for c in as_list(data.get("configuracoes")):
        t = safe_name(txt(c, "titulo"), 70)
        det = c.get("detalhe", "") if isinstance(c, dict) else str(c)
        p = V / F["config"] / f"{t}.md"
        entry = f"## {today()} · {P}\n{det}\n- Sessão: {S}\n"
        if p.exists():
            write(p, read(p).rstrip() + "\n\n" + entry)
        else:
            write_note(p, {"tipo": "configuracao", "projeto": P, "data": today(), "tags": ["configuracao"]},
                       f"# {t}\n\n> [!example] Configuração / estrutura importante\n\n{entry}")
        add_under(pp, "## Estrutura e configurações importantes", f"- [[{t}]]")
        created.append(("Configuração", p))

    tarefas = as_list(data.get("tarefas_pendentes"))
    concl = as_list(data.get("tarefas_concluidas"))
    if tarefas or concl:
        p = V / F["tarefas"] / f"{safe_name(project, 60)} — Tarefas.md"
        if not p.exists():
            write_note(p, {"tipo": "tarefas", "projeto": P, "tags": ["tarefas"]}, f"# Tarefas — {project}\n\n> [!todo] Tarefas do projeto {P}\n\n## Pendentes\n\n## Concluídas\n")
        for t in tarefas:
            add_under(p, "## Pendentes", f"- [ ] {txt(t)} _({today()})_ {S}")
        text = read(p)
        for t in concl:
            nt = norm(txt(t))[:60]
            lines = text.split("\n")
            for i, l in enumerate(lines):
                if l.startswith("- [ ]") and nt and nt in norm(l):
                    lines[i] = l.replace("- [ ]", "- [x]", 1) + f" ✅ {today()}"
            text = "\n".join(lines)
        write(p, text)
        created.append(("Tarefas", p))

    upd = {"atualizado": today()}
    if data.get("objetivo_projeto"):
        upd["objetivo"] = clip(data["objetivo_projeto"], 300)
        txt_p = read(pp)
        txt_p = re.sub(r"^_\(preenchido automaticamente[^\n]*$", lambda m: data["objetivo_projeto"].strip(), txt_p, count=1, flags=re.M)
        write(pp, txt_p)
    update_fm(pp, **upd)
    if data.get("estado_projeto"):
        add_under(pp, "## Estado atual", f"- {today()}: {clip(data['estado_projeto'], 400)}", top=True)
    if data.get("resumo"):
        add_under(pp, "## Histórico de sessões", f"- {today()} {link(sp, clip(titulo, 60))} — {clip(data['resumo'], 160)}", top=True, dedupe=True)

    # nota da sessão
    blk = [f"## 🧠 Registo {stamp()} — {titulo}"]
    if data.get("resumo"):
        blk.append(data["resumo"].strip())
    for it in as_list(data.get("feito")):
        blk.append(f"- ✅ {txt(it)}")
    if created:
        blk.append("\n**Notas criadas/atualizadas:** " + " · ".join(f"{k}: {link(p)}" for k, p in created))
    if techs:
        blk.append("**Tecnologias:** " + ", ".join(f"[[{t}]]" for t in techs))
    write(sp, read(sp).rstrip() + "\n\n" + "\n".join(blk) + "\n")
    if data.get("resumo"):
        fm, body = parse_fm(read(sp))
        body = body.replace("## Resumo\n", f"## Resumo\n{clip(data['resumo'], 600)}\n", 1) if "## Resumo\n\n## Linha" in body else body
        fm["titulo"] = fm.get("titulo") or titulo
        write_note(sp, fm, body)
    st["registos"] = st.get("registos", 0) + 1
    st["pedido_pendente"] = False
    save_sess_state(sid, st)
    rebuild_indexes()
    log(f"registo {sid[:8]} {project}: {len(created)} notas")
    return sp, created


# --------------------------------------------------------------------------- índices
def scan_meta():
    out = []
    for p in V.rglob("*.md"):
        r = p.relative_to(V).parts
        if not r or r[0] in (F["templates"], F["sistema"], F["inicio"], ".obsidian"):
            continue
        fm, _ = parse_fm(read(p)[:3000])
        out.append((p, fm))
    return out


def plain(v):
    return re.sub(r"[\[\]]", "", str(v or "")).split("|")[0]


def rebuild_indexes():
    if not V.exists():
        return
    metas = scan_meta()
    by = {}
    for p, fm in metas:
        by.setdefault(fm.get("tipo", ""), []).append((p, fm))

    def d(fm):
        return str(fm.get("data") or fm.get("atualizado") or fm.get("criado") or "")

    projs = sorted(by.get("projeto", []), key=lambda x: d(x[1]), reverse=True)
    sess = sorted(by.get("sessao", []), key=lambda x: (d(x[1]), str(x[1].get("hora", ""))), reverse=True)
    decs = sorted(by.get("decisao", []), key=lambda x: d(x[1]), reverse=True)
    probs = sorted(by.get("problema", []), key=lambda x: d(x[1]), reverse=True)
    aprs = sorted(by.get("aprendizagem", []), key=lambda x: d(x[1]), reverse=True)
    techs = sorted(by.get("tecnologia", []), key=lambda x: x[0].stem.lower())
    confs = sorted(by.get("configuracao", []), key=lambda x: d(x[1]), reverse=True)
    pend = []
    for p, fm in by.get("tarefas", []):
        for l in read(p).split("\n"):
            if l.startswith("- [ ]"):
                pend.append((plain(fm.get("projeto")), l[6:]))

    I = V / F["inicio"]

    def idx_note(name, title, callout, rows, empty="_(vazio por enquanto)_"):
        body = f"# {title}\n\n> [!{callout}] Índice gerado automaticamente — atualizado {stamp()}\n\n" + ("\n".join(rows) if rows else empty) + "\n"
        write_note(I / f"{name}.md", {"tipo": "indice", "tags": ["indice"]}, body)

    rows = []
    for p, fm in projs:
        rows.append(f"| [[{p.stem}]] | {fm.get('estado', '')} | {clip(fm.get('objetivo', ''), 80)} | {', '.join(fm.get('stack', [])) if isinstance(fm.get('stack'), list) else fm.get('stack', '')} | {d(fm)} |")
    idx_note("Índice — Projetos", "🚀 Projetos", "abstract", (["| Projeto | Estado | Objetivo | Stack | Atualizado |", "|---|---|---|---|---|"] + rows) if rows else [])

    rows, cur = [], None
    for p, fm in sess:
        mon = d(fm)[:7]
        if mon != cur:
            rows.append(f"\n## {mon}")
            cur = mon
        rows.append(f"- {d(fm)} {fm.get('hora', '')} · `{fm.get('ferramenta', '')}` · [[{plain(fm.get('projeto'))}]] · {link(p, clip(fm.get('titulo', p.stem), 70))}")
    idx_note("Índice — Sessões", "🗓️ Sessões", "note", rows)

    def simple(lst):
        return [f"- {d(fm)} · {link(p)} · [[{plain(fm.get('projeto'))}]]" + (f" · `{fm.get('estado')}`" if fm.get("estado") else "") for p, fm in lst]

    idx_note("Índice — Decisões", "⚖️ Decisões", "important", simple(decs))
    idx_note("Índice — Problemas e Soluções", "🐞 Problemas e Soluções", "bug", simple(probs))
    idx_note("Índice — Aprendizagens", "💡 Aprendizagens", "tip", simple(aprs))
    idx_note("Índice — Configurações", "⚙️ Configurações", "example", simple(confs))
    idx_note("Índice — Tecnologias", "🧰 Tecnologias e Ferramentas", "info",
             [f"- [[{p.stem}]] — usado em: " + ", ".join(section(read(p), "## Usado em", 30)).replace("- ", "") for p, fm in techs])
    idx_note("Índice — Tarefas pendentes", "✅ Tarefas pendentes", "todo", [f"- [ ] **{pj}** — {t}" for pj, t in pend])

    home = V / F["inicio"] / "🧠 Início.md"
    auto = [
        "<!-- auto:inicio -->",
        f"> [!abstract] Painel atualizado automaticamente — {stamp()}",
        f"> **{len(projs)}** projetos · **{len(sess)}** sessões · **{len(decs)}** decisões · **{len(probs)}** problemas · **{len(aprs)}** aprendizagens · **{len(pend)}** tarefas pendentes",
        "",
        "## 🚀 Projetos ativos",
        *[f"- [[{p.stem}]] — {clip(fm.get('objetivo', '') or fm.get('caminho', ''), 90)} _(atualizado {d(fm)})_" for p, fm in projs if fm.get("estado", "ativo") == "ativo"][:15],
        "",
        "## 🗓️ Últimas sessões",
        *[f"- {d(fm)} · [[{plain(fm.get('projeto'))}]] · {link(p, clip(fm.get('titulo', p.stem), 70))}" for p, fm in sess[:10]],
        "",
        "## ⚖️ Decisões recentes",
        *(simple(decs[:8]) or ["_(nenhuma ainda)_"]),
        "",
        "## 🐞 Problemas resolvidos recentes",
        *(simple(probs[:8]) or ["_(nenhum ainda)_"]),
        "",
        "## 💡 Aprendizagens recentes",
        *(simple(aprs[:8]) or ["_(nenhuma ainda)_"]),
        "",
        "## ✅ Tarefas pendentes",
        *([f"- [ ] **{pj}** — {t}" for pj, t in pend[:10]] or ["_(nenhuma)_"]),
        "<!-- auto:fim -->",
    ]
    ht = read(home)
    if "<!-- auto:inicio -->" in ht and "<!-- auto:fim -->" in ht:
        ht = re.sub(r"<!-- auto:inicio -->.*?<!-- auto:fim -->", lambda m: "\n".join(auto), ht, flags=re.S)
        write(home, ht)
    else:
        write(home, HOME_HEADER + "\n".join(auto) + "\n" + HOME_FOOTER)


HOME_HEADER = """---
tipo: painel
tags:
  - painel
cssclasses:
  - cerebro-home
---
# 🧠 Segundo Cérebro

> [!info] Como funciona
> Tudo o que fazes no **Claude Code** e no **Codex**, em qualquer projeto, é registado aqui automaticamente.
> No início de cada tarefa, o assistente consulta este cofre; no fim, regista o que foi feito, as decisões, os problemas e as aprendizagens.

**Navegação:** [[Índice — Projetos|🚀 Projetos]] · [[Índice — Sessões|🗓️ Sessões]] · [[Índice — Decisões|⚖️ Decisões]] · [[Índice — Problemas e Soluções|🐞 Problemas]] · [[Índice — Aprendizagens|💡 Aprendizagens]] · [[Índice — Tecnologias|🧰 Tecnologias]] · [[Índice — Configurações|⚙️ Configurações]] · [[Índice — Tarefas pendentes|✅ Tarefas]] · [[Preferências pessoais|🎯 Preferências]] · [[Padrões de trabalho|🔁 Padrões]] · [[Guia do Segundo Cérebro|📘 Guia]]

"""
HOME_FOOTER = """
## 📊 Vistas dinâmicas (Bases)
![[Projetos.base]]

![[Conhecimento.base]]
"""


# --------------------------------------------------------------------------- hooks Claude Code
def read_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False))
    sys.stdout.flush()


def hook_start():
    d = read_stdin_json()
    cwd = d.get("cwd") or os.getcwd()
    sid = d.get("session_id", "")
    if os.environ.get("CEREBRO_OFF") or is_ignored(cwd) or not V.exists():
        return
    project, root = detect_project(cwd)
    ensure_project(project, root)
    try:
        sync_memory(HOME / ".claude" / "projects" / sanitize_cwd(cwd) / "memory", project)
    except Exception as e:
        log(f"sync_memory erro: {e}")
    st = sess_state(sid) if sid else {}
    st.update({"projeto": project, "cwd": cwd, "ferramenta": "claude-code"})
    if sid:
        st.setdefault("injetadas", [])
        save_sess_state(sid, st)
    ctx = project_context(project, root)
    emit({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": ctx}})


def hook_prompt():
    d = read_stdin_json()
    prompt = d.get("prompt", "") or ""
    cwd = d.get("cwd") or os.getcwd()
    sid = d.get("session_id", "")
    if os.environ.get("CEREBRO_OFF") or is_ignored(cwd) or not V.exists():
        return
    clean = clean_prompt(prompt)
    if len(clean) < 12 or clean.startswith("/") and len(clean) < 40:
        return
    st = sess_state(sid) if sid else {}
    project = st.get("projeto") or detect_project(cwd)[0]
    excl = set(st.get("injetadas", []))
    if st.get("nota"):
        excl.add(st["nota"])
    res = [r for r in search(clean, project, k=CFG["pesquisa_top"] + 4, exclude=excl) if r[0] >= CFG["pesquisa_min_score"]][: CFG["pesquisa_top"]]
    if not res:
        return
    body = format_results(res, clean, project, CFG["pesquisa_max_chars"])
    ctx = ("🧠 Segundo cérebro — consulta automática: encontrei notas relacionadas com este pedido "
           "(experiências, decisões e soluções anteriores, incluindo noutros projetos). Lê as relevantes com Read antes de agir "
           "e reaproveita o que já foi feito; menciona ao utilizador quando reaproveitares algo.\n" + body)
    if sid:
        st.setdefault("injetadas", []).extend(r for _, r, _ in res)
        st["injetadas"] = st["injetadas"][-80:]
        save_sess_state(sid, st)
    emit({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": ctx}})


RECORD_INSTR = """🧠 SEGUNDO CÉREBRO — registo automático desta execução (pedido pelo sistema, não pelo utilizador).
Antes de terminar, corre UM único comando Bash, sem comentar:

{cmd} record --sessao {sid} <<'CEREBRO_EOF'
{{"titulo": "...", "resumo": "1-3 frases", "feito": ["..."], "decisoes": [{{"titulo": "...", "contexto": "...", "decisao": "...", "porque": "..."}}], "problemas": [{{"problema": "...", "causa": "...", "solucao": "..."}}], "aprendizagens": [{{"titulo": "...", "detalhe": "..."}}], "preferencias": ["..."], "padroes": ["..."], "tecnologias": ["..."], "configuracoes": [{{"titulo": "...", "detalhe": "caminhos/valores importantes"}}], "tarefas_pendentes": ["..."], "tarefas_concluidas": ["..."], "objetivo_projeto": "...", "estado_projeto": "..."}}
CEREBRO_EOF

Regras: JSON válido, omite campos vazios; só factos reais e reutilizáveis desta execução (o que mudou, porquê, o que falhou e como se resolveu, preferências que o utilizador mostrou); nunca segredos, palavras-passe ou tokens. Se esta execução não teve nada que valha a pena guardar, envia só {{"titulo": "...", "resumo": "..."}}. Depois de correr o comando, termina sem repetir a resposta anterior."""


def hook_stop():
    d = read_stdin_json()
    sid = d.get("session_id", "")
    cwd = d.get("cwd") or os.getcwd()
    tp = d.get("transcript_path")
    if os.environ.get("CEREBRO_OFF") or not sid or is_ignored(cwd) or not V.exists():
        return
    st = sess_state(sid)
    start = st.get("offset", 0)
    tr = parse_transcript(tp, start) if tp else None
    if not tr or tr["total"] <= start:
        return
    project = st.get("projeto") or detect_project(cwd)[0]
    title = tr["title"] or (tr["prompts"][0] if tr["prompts"] else "Sessão")
    sp, st = ensure_session_note(sid, project, "claude-code", title, cwd)
    st = sess_state(sid)
    if tr["prompts"] or tr["edits"] or tr["tools"]:
        write(sp, read(sp).rstrip() + "\n\n" + timeline_entry(tr))
    st["offset"] = tr["total"]
    st["cwd"] = cwd
    acc = st.get("acumulado", {"edits": 0, "tools": 0})
    acc["edits"] += len(tr["edits"])
    acc["tools"] += tr["tools"]
    st["acumulado"] = acc
    save_sess_state(sid, st)
    if d.get("stop_hook_active"):
        rebuild_indexes()
        return
    substantive = acc["edits"] >= CFG["registo_min_edicoes"] or acc["tools"] >= CFG["registo_min_ferramentas"]
    if tr["scheduled"] and not CFG["registo_em_tarefas_agendadas"]:
        substantive = False
    if CFG["pedir_registo"] and substantive:
        st["acumulado"] = {"edits": 0, "tools": 0}
        st["pedido_pendente"] = True
        save_sess_state(sid, st)
        emit({"decision": "block", "reason": RECORD_INSTR.format(cmd=SCRIPT_CMD, sid=sid)})
    else:
        rebuild_indexes()


# --------------------------------------------------------------------------- Codex
def codex_notify(arg):
    try:
        d = json.loads(arg)
    except Exception:
        return
    if d.get("type") not in (None, "agent-turn-complete"):
        return
    sid = str(d.get("thread-id") or d.get("thread_id") or d.get("session-id") or d.get("conversation-id") or ("codex-" + today()))
    cwd = d.get("cwd") or os.getcwd()
    if is_ignored(cwd):
        return
    project, root = detect_project(cwd)
    ensure_project(project, root)
    msgs = d.get("input-messages") or d.get("input_messages") or []
    tr = {"prompts": [clean_prompt(m if isinstance(m, str) else json.dumps(m, ensure_ascii=False)) for m in msgs][-3:],
          "edits": [], "cmds": [], "tools": 0, "last_text": d.get("last-assistant-message") or d.get("last_assistant_message") or ""}
    sp, st = ensure_session_note(sid, project, "codex", tr["prompts"][0] if tr["prompts"] else "Sessão Codex", cwd)
    write(sp, read(sp).rstrip() + "\n\n" + timeline_entry(tr))
    st = sess_state(sid)
    st.update({"cwd": cwd, "projeto": project, "ferramenta": "codex"})
    save_sess_state(sid, st)
    rebuild_indexes()


def context_cmd(args):
    cwd = args.get("--cwd") or os.getcwd()
    query = args.get("--query") or ""
    project, root = detect_project(cwd)
    out = [project_context(project, root)]
    if query:
        res = [r for r in search(query, project, k=CFG["pesquisa_top"]) if r[0] >= CFG["pesquisa_min_score"]]
        if res:
            out.append("Notas relacionadas com a tarefa:\n" + format_results(res, query, project, CFG["pesquisa_max_chars"]))
        else:
            out.append("Sem notas relacionadas com a tarefa.")
    print("\n\n".join(out))


# --------------------------------------------------------------------------- bootstrap
def sort_history(pp):
    lines = read(pp).replace("\r\n", "\n").split("\n")
    try:
        i = next(k for k, l in enumerate(lines) if l.strip() == "## Histórico de sessões")
    except StopIteration:
        return
    j = i + 1
    while j < len(lines) and not re.match(r"^#{1,2} ", lines[j]):
        j += 1
    items = [l for l in lines[i + 1:j] if l.startswith("- ")]
    items.sort(reverse=True)
    write(pp, "\n".join(lines[: i + 1] + items + [""] + lines[j:]))


def bootstrap():
    projects_dir = HOME / ".claude" / "projects"
    n_sess = n_mem = 0
    current = os.environ.get("CEREBRO_SKIP_SESSION", "")
    for pd in sorted(projects_dir.glob("*")) if projects_dir.exists() else []:
        if not pd.is_dir():
            continue
        cwd = None
        jsonls = sorted(pd.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        for f in jsonls:
            tr = parse_transcript(f)
            cwd = cwd or tr["cwd"]
            sid = f.stem
            if not tr["prompts"] or (sess_state(sid).get("nota") and (V / sess_state(sid)["nota"]).exists()):
                continue
            if tr["cwd"] and is_ignored(tr["cwd"]):
                continue
            project, root = detect_project(tr["cwd"] or "")
            ensure_project(project, root)
            when = dt.datetime.fromtimestamp(f.stat().st_mtime)
            if tr["first_ts"]:
                try:
                    when = dt.datetime.fromisoformat(tr["first_ts"].replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
                except Exception:
                    pass
            title = tr["title"] or tr["prompts"][0]
            sp, st = ensure_session_note(sid, project, "claude-code", title, tr["cwd"], when=when, imported=True)
            fm, body = parse_fm(read(sp))
            resumo = f"Sessão importada do histórico. Pedido inicial: {clip(tr['prompts'][0], 300)}"
            body = body.replace("## Resumo\n", f"## Resumo\n{resumo}\n", 1)
            tl = timeline_entry(tr, when)
            write_note(sp, fm, body.rstrip() + "\n\n" + tl)
            st = sess_state(sid)
            st.update({"offset": tr["total"], "cwd": tr["cwd"], "projeto": project})
            save_sess_state(sid, st)
            n_sess += 1
        if cwd:
            n_mem += sync_memory(pd / "memory", detect_project(cwd)[0])
    for pp in (V / F["projetos"]).glob("*.md"):
        sort_history(pp)
    rebuild_indexes()
    load_index()
    print(f"bootstrap: {n_sess} sessões importadas, {n_mem} memórias sincronizadas")


def doctor():
    print("cofre:", V, "existe" if V.exists() else "NÃO EXISTE")
    print("motor:", BASE / "cerebro.py")
    s = jload(HOME / ".claude" / "settings.json", {})
    print("hooks Claude Code:", ", ".join((s.get("hooks") or {}).keys()) or "nenhum")
    print("Codex config:", (HOME / ".codex" / "config.toml").exists(), "AGENTS.md:", (HOME / ".codex" / "AGENTS.md").exists())
    idx = load_index()
    print("notas indexadas:", len(idx))
    print("log:", LOG)


# --------------------------------------------------------------------------- main
def parse_args(argv):
    a, pos, i = {}, [], 0
    while i < len(argv):
        if argv[i].startswith("--"):
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                a[argv[i]] = argv[i + 1]
                i += 2
            else:
                a[argv[i]] = True
                i += 1
        else:
            pos.append(argv[i])
            i += 1
    return a, pos


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd, rest = sys.argv[1], sys.argv[2:]
    args, pos = parse_args(rest)
    try:
        if cmd == "hook-start":
            hook_start()
        elif cmd == "hook-prompt":
            hook_prompt()
        elif cmd == "hook-stop":
            hook_stop()
        elif cmd == "record":
            raw = read(args["--file"]) if args.get("--file") else sys.stdin.read()
            raw = raw.strip()
            m = re.search(r"\{.*\}", raw, re.S)
            raw = m.group(0) if m else raw
            try:
                data = json.loads(raw, strict=False)
            except json.JSONDecodeError:
                data = json.loads(re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", raw), strict=False)
            if args.get("--ferramenta"):
                data["ferramenta"] = args["--ferramenta"]
            if args.get("--cwd"):
                data["cwd"] = args["--cwd"]
            sp, created = record(data, args.get("--sessao"))
            print(f"🧠 Registado: {sp.as_posix()} (+{len(created)} notas)")
        elif cmd == "codex-notify":
            codex_notify(pos[-1] if pos else sys.stdin.read())
        elif cmd == "context":
            context_cmd(args)
        elif cmd == "search":
            qy = " ".join(pos)
            proj = detect_project(args.get("--cwd") or os.getcwd())[0]
            res = search(qy, proj, k=int(args.get("--k", 8)))
            print(format_results(res, qy, proj, 8000) or "sem resultados")
        elif cmd == "reindex":
            rebuild_indexes()
            print("índices regenerados:", len(load_index()), "notas")
        elif cmd == "bootstrap":
            bootstrap()
        elif cmd == "doctor":
            doctor()
        else:
            print("comando desconhecido:", cmd)
    except Exception:
        log(f"ERRO {cmd}: {traceback.format_exc()}")
        if cmd in ("record", "search", "context", "reindex", "bootstrap", "doctor"):
            raise


if __name__ == "__main__":
    main()
