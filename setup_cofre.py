# -*- coding: utf-8 -*-
"""Cria/atualiza a estrutura do cofre Obsidian do Segundo Cérebro. Idempotente: não apaga notas."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import cerebro as C

V, F = C.V, C.F
OBS = V / ".obsidian"

CORES = {  # pasta: (cor, ícone, descrição)
    F["inicio"]: ("#a78bfa", "🧠", "Painel, índices e vistas"),
    F["projetos"]: ("#3b82f6", "🚀", "Uma nota por projeto + subnotas"),
    F["sessoes"]: ("#64748b", "🗓️", "Registo de cada sessão Claude Code / Codex"),
    F["decisoes"]: ("#f59e0b", "⚖️", "Decisões tomadas e porquê"),
    F["problemas"]: ("#ef4444", "🐞", "Problemas encontrados e soluções"),
    F["aprend"]: ("#22c55e", "💡", "Aprendizagens e melhorias"),
    F["padroes"]: ("#ec4899", "🎯", "Preferências pessoais e padrões de trabalho"),
    F["tec"]: ("#06b6d4", "🧰", "Tecnologias, ferramentas e stacks"),
    F["config"]: ("#8b5cf6", "⚙️", "Configurações e estruturas importantes"),
    F["tarefas"]: ("#eab308", "✅", "Tarefas por projeto"),
    F["recursos"]: ("#14b8a6", "📚", "Referências, links e anexos"),
    F["templates"]: ("#94a3b8", "🧩", "Templates"),
    F["sistema"]: ("#6b7280", "🛠️", "Guia e documentação do sistema"),
}
TAGS = {"projeto": "#3b82f6", "sessao": "#64748b", "decisao": "#f59e0b", "problema": "#ef4444", "aprendizagem": "#22c55e",
        "preferencias": "#ec4899", "padroes": "#ec4899", "tecnologia": "#06b6d4", "configuracao": "#8b5cf6", "tarefas": "#eab308",
        "memoria": "#a78bfa", "indice": "#a78bfa", "codex": "#10b981", "claude-code": "#d97706"}


def css():
    out = ["/* Segundo Cérebro — sistema visual de cores (gerado por setup_cofre.py) */"]
    for folder, (cor, ico, _) in CORES.items():
        out.append(f'.nav-folder-title[data-path="{folder}"] {{ color: {cor}; font-weight: 600; border-left: 3px solid {cor}; padding-left: 6px; }}')
        out.append(f'.nav-folder-title[data-path="{folder}"] .nav-folder-title-content::before {{ content: "{ico}  "; }}')
        out.append(f'.nav-folder-title[data-path^="{folder}/"] {{ color: {cor}; opacity: .9; }}')
        out.append(f'.nav-file-title[data-path^="{folder}/"] {{ border-left: 2px solid {cor}55; }}')
    for tag, cor in TAGS.items():
        out.append(f'a.tag[href="#{tag}"], .cm-hashtag.cm-tag-{tag} {{ background-color: {cor}26; color: {cor}; border: 1px solid {cor}66; }}')
    out.append("""
.cerebro-home h1 { font-size: 2.1em; letter-spacing: -.5px; }
.cerebro-home h2 { border-bottom: 2px solid var(--interactive-accent); padding-bottom: 4px; margin-top: 1.4em; }
.cerebro-home ul li { margin: 2px 0; }
.callout[data-callout="important"] { --callout-color: 245, 158, 11; }
.callout[data-callout="bug"] { --callout-color: 239, 68, 68; }
.callout[data-callout="tip"] { --callout-color: 34, 197, 94; }
.callout[data-callout="example"] { --callout-color: 139, 92, 246; }
.callout[data-callout="todo"] { --callout-color: 234, 179, 8; }
.callout[data-callout="abstract"] { --callout-color: 59, 130, 246; }
""")
    return "\n".join(out)


def hexint(h):
    return int(h.lstrip("#"), 16)


TEMPLATES = {
    "Projeto": """---
tipo: projeto
estado: ativo
caminho: ""
objetivo: ""
stack: []
criado: {{date:YYYY-MM-DD}}
atualizado: {{date:YYYY-MM-DD}}
tags:
  - projeto
---
# {{title}}

> [!abstract] Projeto
> **Caminho:** `` · **Estado:** ativo

## Objetivo

## Estado atual

## Stack e ferramentas

## Estrutura e configurações importantes

## Notas do projeto

## Histórico de sessões
""",
    "Sessão": """---
tipo: sessao
ferramenta: manual
projeto: "[[]]"
data: {{date:YYYY-MM-DD}}
hora: {{time:HH:mm}}
titulo: "{{title}}"
tags:
  - sessao
---
# {{title}}

> [!note] Sessão · {{date:YYYY-MM-DD}} {{time:HH:mm}}

## Resumo

## Linha do tempo
""",
    "Decisão": """---
tipo: decisao
projeto: "[[]]"
data: {{date:YYYY-MM-DD}}
tags:
  - decisao
---
# {{title}}

> [!important] Decisão · {{date:YYYY-MM-DD}}

## Contexto

## Decisão

## Porquê

## Alternativas consideradas

## Origem
""",
    "Problema e Solução": """---
tipo: problema
projeto: "[[]]"
estado: aberto
data: {{date:YYYY-MM-DD}}
tags:
  - problema
---
# {{title}}

> [!bug] Problema → Solução

## Ocorrência {{date:YYYY-MM-DD}}
- **Problema:**
- **Causa:**
- **Solução:**
""",
    "Aprendizagem": """---
tipo: aprendizagem
projeto: "[[]]"
data: {{date:YYYY-MM-DD}}
tags:
  - aprendizagem
---
# {{title}}

> [!tip] Aprendizagem
>

## Ocorrências
""",
    "Tecnologia": """---
tipo: tecnologia
criado: {{date:YYYY-MM-DD}}
tags:
  - tecnologia
---
# {{title}}

> [!info] Tecnologia / ferramenta

## Usado em

## Notas e truques
""",
    "Configuração": """---
tipo: configuracao
projeto: "[[]]"
data: {{date:YYYY-MM-DD}}
tags:
  - configuracao
---
# {{title}}

> [!example] Configuração / estrutura importante

## Detalhes
""",
    "Diário": """---
tipo: diario
data: {{date:YYYY-MM-DD}}
tags:
  - diario
---
# {{date:dddd, D [de] MMMM YYYY}}

## Foco do dia

## Notas

## Ligações
- [[🧠 Início]]
""",
}

BASES = {
    "Projetos.base": """filters:
  and:
    - tipo == "projeto"
views:
  - type: table
    name: Projetos
    order:
      - file.name
      - estado
      - objetivo
      - stack
      - atualizado
    sort:
      - property: atualizado
        direction: DESC
  - type: cards
    name: Cartões
    order:
      - file.name
      - estado
      - atualizado
""",
    "Conhecimento.base": """filters:
  or:
    - tipo == "decisao"
    - tipo == "problema"
    - tipo == "aprendizagem"
    - tipo == "configuracao"
views:
  - type: table
    name: Conhecimento recente
    order:
      - file.name
      - tipo
      - projeto
      - estado
      - data
    sort:
      - property: data
        direction: DESC
    limit: 30
  - type: table
    name: Problemas abertos
    filters:
      and:
        - tipo == "problema"
        - estado == "aberto"
    order:
      - file.name
      - projeto
      - data
""",
    "Sessões.base": """filters:
  and:
    - tipo == "sessao"
views:
  - type: table
    name: Sessões recentes
    order:
      - file.name
      - ferramenta
      - projeto
      - data
      - hora
    sort:
      - property: data
        direction: DESC
    limit: 50
""",
}

GUIA = f"""---
tipo: guia
tags:
  - sistema
---
# Guia do Segundo Cérebro

> [!info] O que é
> Este cofre é a memória de longo prazo de **todo** o trabalho feito com o **Claude Code** e o **Codex**, em qualquer projeto do computador.
> Funciona sozinho: não é preciso pedir ao assistente que consulte ou que guarde.

## Ciclo automático
| Momento | Claude Code | Codex |
|---|---|---|
| Abrir sessão | hook **SessionStart** injeta a nota do projeto, o estado, as tarefas pendentes e as tuas preferências | `AGENTS.md` global obriga a correr `cerebro.py context` antes de começar |
| Cada pedido | hook **UserPromptSubmit** pesquisa o cofre todo (todos os projetos) e injeta as notas relacionadas | `context --query` com a descrição da tarefa |
| Fim de cada execução | hook **Stop** grava a linha do tempo (pedido, ficheiros, comandos, resposta) e pede ao assistente o registo estruturado (`cerebro.py record`) | `notify` grava a linha do tempo; o `AGENTS.md` pede o `record` no fim |

## Onde fica cada coisa
| Pasta | Conteúdo |
|---|---|
""" + "\n".join(f"| {ico} `{k}` | {d} |" for k, (c, ico, d) in CORES.items()) + f"""

## Motor
- Código: `{(C.BASE / 'cerebro.py').as_posix()}` (Python, sem dependências)
- Configuração: `{(C.BASE / 'config.json').as_posix()}`
- Estado e índice de pesquisa: `{(C.STATE).as_posix()}`
- Log de erros: `{(C.LOG).as_posix()}`

## Comandos úteis
```bash
python {(C.BASE / 'cerebro.py').as_posix()} search "termos a procurar"
python {(C.BASE / 'cerebro.py').as_posix()} context --cwd "C:/caminho/do/projeto" --query "o que vou fazer"
python {(C.BASE / 'cerebro.py').as_posix()} reindex
python {(C.BASE / 'cerebro.py').as_posix()} doctor
```

## Desligar temporariamente
Define a variável de ambiente `CEREBRO_OFF=1`, ou põe `"pedir_registo": false` em `config.json` para manter só a linha do tempo automática.

## Mapear pastas para um projeto
Em `config.json`, `"aliases_projetos": {{"C:/caminho/da/pasta": "Nome do Projeto"}}`.
"""

PREFS_SEED = [
    "Exemplo: respostas e notas em português",
    "Exemplo: prefere implementações funcionais a planos teóricos",
]
PADROES_SEED = [
    "Exemplo: itera em versões (v1 → v2) e testa antes de usar em produção",
]


def main():
    V.mkdir(parents=True, exist_ok=True)
    for k in CORES:
        (V / k).mkdir(exist_ok=True)
    (V / F["recursos"] / "Anexos").mkdir(exist_ok=True)
    (V / F["sessoes"] / "Diário").mkdir(exist_ok=True)

    for name, body in TEMPLATES.items():
        p = V / F["templates"] / f"{name}.md"
        if not p.exists():
            C.write(p, body)
    for name, body in BASES.items():
        C.write(V / F["inicio"] / name, body)
    C.write(V / F["sistema"] / "Guia do Segundo Cérebro.md", GUIA)

    for nm, tipo, seed, cal in (("Preferências pessoais", "preferencias", PREFS_SEED, "Preferências pessoais do utilizador"),
                                ("Padrões de trabalho", "padroes", PADROES_SEED, "Padrões de trabalho recorrentes")):
        p = V / F["padroes"] / f"{nm}.md"
        if not p.exists():
            C.write_note(p, {"tipo": tipo, "tags": [tipo]}, f"# {nm}\n\n> [!quote] {cal} — atualizado automaticamente\n\n## Lista\n")
        for s in seed:
            C.add_under(p, "## Lista", f"- {s}")

    # Obsidian
    OBS.mkdir(exist_ok=True)
    (OBS / "snippets").mkdir(exist_ok=True)
    C.write(OBS / "snippets" / "cerebro-cores.css", css())
    ap = C.jload(OBS / "appearance.json", {})
    snips = set(ap.get("enabledCssSnippets", [])) | {"cerebro-cores"}
    ap["enabledCssSnippets"] = sorted(snips)
    C.jsave(OBS / "appearance.json", ap)

    app = C.jload(OBS / "app.json", {})
    app.update({"newFileLocation": "folder", "newFileFolderPath": F["inicio"], "attachmentFolderPath": f"{F['recursos']}/Anexos",
                "alwaysUpdateLinks": True, "showUnsupportedFiles": False, "propertiesInDocument": "visible"})
    C.jsave(OBS / "app.json", app)
    C.jsave(OBS / "templates.json", {"folder": F["templates"], "dateFormat": "YYYY-MM-DD", "timeFormat": "HH:mm"})
    C.jsave(OBS / "daily-notes.json", {"folder": f"{F['sessoes']}/Diário", "template": f"{F['templates']}/Diário", "format": "YYYY-MM-DD"})

    g = C.jload(OBS / "graph.json", {})
    g["colorGroups"] = [{"query": f'path:"{k}"', "color": {"a": 1, "rgb": hexint(c)}} for k, (c, _, _) in CORES.items()
                        if k not in (F["templates"], F["sistema"])]
    g["search"] = f'-path:"{F["templates"]}" -path:"{F["sistema"]}"'
    g.setdefault("showTags", False)
    C.jsave(OBS / "graph.json", g)

    bm = C.jload(OBS / "bookmarks.json", {"items": []})
    paths = {i.get("path") for i in bm.get("items", [])}
    ts = int(time.time() * 1000)
    for pth, title in ((f"{F['inicio']}/🧠 Início.md", "🧠 Início"), (f"{F['inicio']}/Índice — Projetos.md", "🚀 Projetos"),
                       (f"{F['inicio']}/Índice — Tarefas pendentes.md", "✅ Tarefas"), (f"{F['sistema']}/Guia do Segundo Cérebro.md", "📘 Guia")):
        if pth not in paths:
            bm["items"].append({"type": "file", "ctime": ts, "path": pth, "title": title})
    C.jsave(OBS / "bookmarks.json", bm)

    cp = C.jload(OBS / "core-plugins.json", {})
    for k in ("templates", "daily-notes", "bases", "bookmarks", "graph", "backlink", "outgoing-link", "tag-pane", "properties", "canvas"):
        cp[k] = True
    C.jsave(OBS / "core-plugins.json", cp)

    C.rebuild_indexes()
    print("cofre pronto:", V)


if __name__ == "__main__":
    main()
