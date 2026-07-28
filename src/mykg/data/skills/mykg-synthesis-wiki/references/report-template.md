---
title: <Human-readable report title>
created: <YYYY-MM-DD>
updated: <YYYY-MM-DD>
theme: <one theme label, e.g. "AI capabilities">
domains:
- <Domain the cited entities come from, one per line, e.g. Research>
entities:
- <mykg_id of each cited entity, one per line>
---

# <Report title>

## Answer

<Synthesized prose grounded strictly in the KG. Reference entities inline as
`[[<mykg_id>|<display name>]]`. When a fact spans domains, name the domain.>

## Diagram

<Optional. Mermaid block for relationships/flow, e.g.:

```mermaid
graph LR
  A["Alice Chen"] -->|works_at| B["Acme Corp"]
```

or an embedded PNG chart:

![[assets/<slug>-01.png]]
>

## Key entities

- [[<mykg_id>|<display name>]] — <one-line role in this answer>

## Domains & grounding

- Domains read: <Research, Yard, ...>
- All statements above are grounded in nodes.jsonl / edges.jsonl for those domains.
