# Segundo Cérebro — persistent memory for Claude Code

Claude Code forgets everything between sessions. Segundo Cérebro ("second brain") fixes that with three hooks and an Obsidian vault:

- **SessionStart** → injects the current project's note, recent sessions, open tasks and the user's preferences.
- **UserPromptSubmit** → searches the vault for notes related to the prompt (from any project) and injects the best matches.
- **Stop** → asks Claude to record what happened (decisions, problems → solutions, learnings, preferences, tasks) as structured JSON, which becomes linked Markdown notes.

Single file, **Python standard library only**, everything stays local. About 1,700 lines.

```
prompt ──▶ hook-prompt ──▶ search vault (BM25-style ranking) ──▶ context injected
session end ──▶ hook-stop ──▶ Claude runs `cerebro.py record` ──▶ notes: Sessions · Decisions · Problems · Learnings · Tasks
```

## Install

```bash
git clone <this repo> ~/.cerebro
cd ~/.cerebro
echo '{"cofre": "C:/path/to/your/ObsidianVault"}' > config.json   # optional; default is ~/SegundoCerebro
python setup_cofre.py          # creates the vault structure, templates and guide
python cerebro.py doctor       # checks paths and hooks
```

Add the hooks to `~/.claude/settings.json` (same pattern for `UserPromptSubmit` → `hook-prompt` and `Stop` → `hook-stop`):

```json
"hooks": {
  "SessionStart": [{ "hooks": [{ "type": "command", "command": "python",
    "args": ["C:/Users/<you>/.cerebro/cerebro.py", "hook-start"], "timeout": 20 }] }]
}
```

## Commands

| Command | What it does |
|---|---|
| `hook-start` / `hook-prompt` / `hook-stop` | Claude Code hooks |
| `record --sessao <id>` | Record a session (JSON on stdin or `--file`) |
| `search "terms"` | Search the vault |
| `context --cwd X --query "..."` | Context for a task start (also used by Codex) |
| `codex-notify` | Codex timeline hook |
| `reindex` · `bootstrap` · `doctor` | Rebuild indexes · import existing Claude Code memory · diagnostics |

## Privacy

- Everything stays on your machine: the vault, `estado/` (index and session state) and `cerebro.log` are git-ignored.
- The recording prompt tells Claude never to store secrets, passwords, keys or tokens.
- Injected notes are framed as data, not instructions.

## License

MIT — see [LICENSE](LICENSE).
