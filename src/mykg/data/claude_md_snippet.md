## mykg knowledge graph

This project uses [mykg](https://github.com/SenolIsci/mykg) — a knowledge
graph extracted from source documents in this repo. The agent-mode skill is
installed; query it via `/mykg`.

### Find the latest session

Don't guess the session name. Run one of these from the project root:

```bash
# Path to latest session root (use this in subsequent commands):
ls -td kg_sessions/*/ 2>/dev/null | head -1

# One-line wiki status (node count + session path):
ls -td kg_sessions/*/output/nodes.jsonl 2>/dev/null | head -1 \
  | xargs -I{} sh -c 'echo "mykg wiki: $(wc -l < {}) nodes in $(dirname $(dirname {}))"'
```

If the first command prints nothing, there is no graph yet — tell the user to
run `/mykg extract <dir>` first instead of fabricating an answer.

### What's in a session

Under `<latest-session>/output/`:

- `nodes.jsonl` — entities with confidence-scored attributes
- `edges.jsonl` — typed relationships
- `knowledge_graph.ttl` — RDFS/OWL view (SPARQL-queryable)
- `obsidian_vault/` — markdown notes with wikilinks (when generated)

### Read before answering

Before answering any domain question about this corpus, invoke
`/mykg query <question>` so the skill reads the latest session's graph for
you and returns the relevant material into context. The skill picks the
right source automatically:

- **wiki-style** ("who is Alice", "what does the wiki say about X", named
  entities, prose questions) → reads `obsidian_vault/`
- **graph-structural** ("most connected node", "what links A to B",
  "shortest path", topology / aggregate questions) → reads `nodes.jsonl`
  and `edges.jsonl`

The graph is grounded in the source documents — your training data is not.
Answer from what the skill returns, not from memory.

If you cannot use the slash command (skill not installed, broken, etc.),
fall back to reading the same files directly via the paths in the next
section.

### Extending the graph

There is no project-wide "input folder" — each run takes a `<dir>` argument.
To find the directory that was used most recently (line 1 of `run.log`
records the full invocation):

```bash
# Input directory of the most recent extract-graph run:
head -1 "$(ls -td kg_sessions/*/run.log 2>/dev/null | head -1)" \
  | sed -nE 's/.*mykg extract-graph ([^ ]+).*/\1/p'
```

To add new source documents: either drop them into that same directory and
re-run, or pass a fresh directory containing them. From inside Claude Code:
`/mykg append the new notes in <dir>`. From a shell:
`mykg extract-graph <dir> --append --session <name> --obsidian-vault`. The
`--obsidian-vault` flag regenerates the markdown vault alongside the JSONL /
TTL outputs so the Obsidian view stays in sync.

### Do not edit outputs directly

`nodes.jsonl` / `edges.jsonl` are regenerated from
`intermediate/edge_metadata.json` on every run. To correct the graph, edit the
source markdown or `intermediate/schema.json` and re-run the affected pipeline
step (`/mykg from-step <step> on the last session`).
