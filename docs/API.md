# API Guide

All endpoints are versioned under `/api/v1` unless noted.

## Authentication

- `POST /api/v1/auth/register` (available only when `ALLOW_REGISTRATION=true`; returns 403 when disabled)
- `POST /api/v1/auth/login`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/me/status`
- `POST /api/v1/auth/logout`

Browser logins set an httpOnly auth cookie by default. For non-browser clients, the same JWT can be sent as `Authorization: Bearer <token>` after extracting it from that cookie.

For server-to-server integrations, refinement workflow endpoints also support `X-API-Key: <integration-api-key>` when `INTEGRATION_API_KEY` is configured on the API service.

## Agent integration guide

This section is the primary reference for building agents or automated integrations. It describes the state machine, decision logic, quick-reply handling, and RAG field mapping needed to drive the full workflow programmatically.

### The four-phase pipeline

```
Phase 1 — Discover               GET  /frameworks
Phase 2 — Refine/clarify (loop)          POST /start  →  loop: POST /answer
Phase 3 — Synthesize (core)      POST /synthesize  (Agents A → B → C, orchestrated)
          Full chain             POST /synthesize  with include_expansion=true  (Agents A → B → C → D)
           or call individually:  POST /normalize   (Agent A only)
                                  POST /represent   (Agent B only)
                                  POST /construct   (Agent C only)
Phase 4 — Expand (optional)      POST /expand  (Agent D, standalone)
```

### Authentication for agents

Use the `X-API-Key` header for all requests:

```
X-API-Key: <value of INTEGRATION_API_KEY env var>
```

The integration service user must have explicit framework access. Grant it once on the server:

```bash
poetry run python scripts/create_user.py \
  --username api_integration_service \
  --framework <framework_name>
```

### State machine

```
POST /start
  │
  ├─ ready_for_synthesis = true  ──────────────────────────────────► POST /synthesize
  │
  └─ next_prompt ≠ null
       │
       ▼
   ┌──────────────────────────────────────────────────┐
   │  REFINEMENT LOOP                                  │
   │                                                   │
   │  1. Present next_prompt.question to user          │
   │  2. Optionally render next_prompt.examples        │
   │     as clickable buttons                          │
   │  3. Collect answer (free text or clicked example) │
   │  4. POST /answer  { "answer": "<string>" }        │
   │                                                   │
   │  Response branch:                                 │
   │  ├─ ready_for_synthesis = true ──────────────────►│── POST /synthesize
   │  ├─ next_prompt ≠ null  (loop continues) ────────►│── back to step 1
   │  └─ next_prompt = null && !ready_for_synthesis    │
   │       (no more questions, force synthesize) ─────►│── POST /synthesize
   └──────────────────────────────────────────────────┘

POST /synthesize
  │
  └─ structured_output ──► RAG retrieval (see field mapping below)
                      └──► POST /expand  (optional broadening levels, Agent D)

POST /synthesize  with include_expansion=true
  │
  └─ structured_output + expansion_levels + expansion_metadata
     (full chained A → B → C → D response)
```

### Minimal integration loop (pseudocode)

```python
BASE = "http://localhost:8001/api/v1"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

# Phase 1 — pick a framework
frameworks = GET(f"{BASE}/refinement/frameworks")["frameworks"]
framework_name = frameworks[0]   # or let the user choose

# Phase 2 — start and refine
r = POST(f"{BASE}/refinement/start", {
    "original_query": user_query,
    "framework_name": framework_name,
    "source": "api_integration",
})
query_id = r["query_id"]

while not r.get("ready_for_synthesis"):
    prompt = r.get("next_prompt")
    if not prompt:
        break  # no more questions

    question  = prompt["question"]       # plain prose question
    examples  = prompt["examples"]       # list[str] — quick-reply options (may be empty)
    aspect_id = prompt["aspect_id"]

    # Present question + examples to user (or have agent select)
    answer = agent_or_user_select(question, examples)

    r = POST(f"{BASE}/refinement/queries/{query_id}/answer", {"answer": answer})

# Phase 3 — synthesize A→B→C
synthesis = POST(f"{BASE}/refinement/synthesize", {"query_id": query_id})

# Or run the full chained path A→B→C→D in one call
full_chain = POST(f"{BASE}/refinement/synthesize", {
    "query_id": query_id,
    "include_expansion": True
})
```

### Synthesis agents

Each agent is an independent LLM call with a defined input/output contract and its own HTTP endpoint. They are designed to be called in sequence (A → B → C → D), but each can be invoked individually.

```
Agent A  POST /normalize   Normalization — session → clarified_query
Agent B  POST /represent   Semantic Representation — statement → queries + concept_graph
Agent C  POST /construct   Search Construction — statement + concept_graph → keyword artifacts
Agent D  POST /expand      Search Expansion — statement → broadening levels (optional)
```

`POST /synthesize` is the **shortest path** for A → B → C.  
`POST /synthesize` with `include_expansion=true` is the **shortest chained path** for A → B → C → D.  
Call the individual endpoints when you need only a subset of the pipeline or want to cache intermediate outputs.

#### Agent A — Normalization

**Endpoint:** `POST /api/v1/refinement/normalize`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "query_id": 123 }` — completed refinement session.

**Output:**

| Field                       | Description                                                                 |
| --------------------------- | --------------------------------------------------------------------------- |
| `clarified_query`           | Clarified research statement — the review anchor and Level 0 query          |
| `dimensions_specifications` | Per-dimension refined values assembled deterministically from session state |

`clarified_query` is the primary human-readable output. If you only need the refined query (for display, QA forwarding, or logging), call `/normalize` — Agents B and C are not invoked and the session is not marked as synthesized.

Pass `clarified_query` as input to `/represent` (Agent B) or `/expand` (Agent D).

#### Agent B — Semantic Representation

**Endpoint:** `POST /api/v1/refinement/represent`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "statement": "..." }` — no session required. (Use `clarified_query` from POST /normalize.)

**Output:**

| Field                | Description                                                                                                                                              |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `semantic_statement` | Dense embedding query (2-3 sentences, 50-70 words) for vector/semantic search. Information-need framing using document-side vocabulary.                  |
| `keyword_statement`  | Natural-language keyword query (15-35 words) for BM25/simple keyword search. Key concepts + primary synonyms; no Boolean operators; no metadata filters. |
| `concept_graph`      | Per-concept retrieval metadata — synonyms, abbreviations, domain terms, controlled vocabulary hints                                                      |

Both `semantic_statement` and `keyword_statement` are filter-free — they share the same `search_filters` produced by Agent C. Pass `concept_graph` to `/construct` (Agent C) and `/expand` (Agent D).

Each entry in `concept_graph`:

```json
{
  "query_role": "intervention_or_exposure_or_phenomenon",
  "true_synonyms": ["acetylsalicylic acid"],
  "abbreviations": ["ASA"],
  "spelling_variants": [],
  "lexical_variants": [],
  "domain_terms": ["antiplatelet agent"],
  "colloquial": ["blood thinner"],
  "controlled_vocabulary_hints": [
    { "vocabulary_name": "MeSH", "terms": ["Aspirin"], "confidence": "high" }
  ]
}
```

`domain_terms` (hyponyms/narrower terms) are not included in the Agent C anchor Boolean query but are included in Agent D Level 1 for maximum recall. `colloquial` terms are not used in formal database queries.

#### Agent C — Search Construction

**Endpoint:** `POST /api/v1/refinement/construct`  
Also invoked automatically by `POST /api/v1/refinement/synthesize`.

**Input:** `{ "statement": "...", "concept_graph": {...} }` — no session required. (Use `clarified_query` from POST /normalize and `concept_graph` from POST /represent.)

**Output:**

| Field                     | Description                                                                                                                                             |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `keyword.combined_blocks` | **Primary RAG artifact** — one AND-block per concept with `role`, `free_text` terms, and `controlled_vocabulary`                                        |
| `keyword.structured`      | Boolean anchor query (fallback)                                                                                                                         |
| `keyword.phrases`         | Exact key phrases                                                                                                                                       |
| `search_filters`          | Metadata narrowing filters (`publication_years`, `publication_types`, etc.) — applies to both `semantic_statement` and `keyword_statement` from Agent B |

`combined_blocks` connector logic:
```
OR  free_text terms  within each block
OR  controlled_vocabulary terms  within each block
AND all blocks together
```

Use `controlled_vocabulary` only for PubMed (MeSH). Use `free_text` alone for all other sources (WHO IRIS, OpenAlex, CORE, ReliefWeb).

#### Agent D — Search Expansion

**Endpoint:** `POST /api/v1/refinement/expand` (standalone, optional)

Agent D generates a Cochrane-compliant recall ladder — progressive broadening levels for use when initial retrieval yields insufficient results. Level 0 (the anchor) **is returned** as `levels[0]` so clients have one uniform structure across all levels.

**Input:**

| Field                          | Source                    | Required                                |
| ------------------------------ | ------------------------- | --------------------------------------- |
| `statement`                    | Agent A `clarified_query` | Yes                                     |
| `search_context.concept_graph` | Agent B `concept_graph`   | No, but enables full lexical broadening |

**Top-level response fields:**
- `levels`
- `geography_broadening_strategy`
- `recommended_starting_level`
- `recommendation_rationale`
- `search_filters`
- `phrases`
- `metadata`

**Output levels:** `levels` — Levels 0–3 (all sharing the same `ExpansionLevel` structure).

| Level | Strategy                                               | Description                                                                                                                                                                                                  |
| ----- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1     | `lexical`                                              | Full synonym + domain-term ring. Every concept block expanded to its OR-union of true_synonyms, abbreviations, spelling_variants, lexical_variants, and domain_terms from Agent B. No conceptual broadening. |
| 2     | `conceptual_single_aspect`                             | Level 1 ring with one SAFE aspect broadened. Priority: geography first (replaced by contextual analogy or geographic superset), then setting, then population.                                               |
| 3     | `conceptual_single_aspect` / `conceptual_multi_aspect` | If Level 2 broadened geography, Level 3 removes it entirely (`"geography": "(no restriction)"`) — the Cochrane-compliant globally sensitive search. Otherwise broadens the next SAFE aspect.                 |

Each level object:

```json
{
  "level": 1,
  "label": "Full lexical ring — anchor scope",
  "strategy": "lexical",
  "query": "How to improve mental health outcomes in displacement camps in Ethiopia.",
  "semantic_query": "How to improve mental health outcomes in displacement camps in Ethiopia.",
  "keyword_query": "mental health displacement camps Ethiopia",
  "boolean_query": "(mental health OR psychological wellbeing OR MHPSS OR ...) AND ...",
  "relaxed_aspects": {},
  "rationale": "Full synonym and domain-term ring for every concept block."
}
```

Apply levels in order: run the recommended starting level first; escalate when result count is insufficient.

Example standalone Agent D response for clients:

```json
{
  "levels": [
    {
      "level": 0,
      "label": "Anchor query",
      "query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
      "semantic_query": "Studies examining interventions to improve mental health outcomes among children in refugee camp settings in Ethiopia.",
      "keyword_query": "mental health children refugee camp Ethiopia",
      "boolean_query": "(mental health OR psychological wellbeing OR MHPSS) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (Qoloji OR Ethiopia)",
      "controlled_vocabulary": {
        "MeSH": ["Mental Health", "Child", "Ethiopia"]
      },
      "blocks": [
        {
          "role": "topic_or_condition",
          "free_text": ["mental health", "psychological wellbeing", "MHPSS"],
          "controlled_vocabulary": {"MeSH": ["Mental Health"]}
        }
      ],
      "broadened_aspect": "",
      "broadened_value": "",
      "rationale": "Your refined query as-is — exact concepts from your refinement session, no broadening.",
      "cochrane_compliant": false
    },
    {
      "level": 1,
      "label": "Full lexical ring",
      "query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
      "semantic_query": "How to improve mental health outcomes among children in Qoloji camp, Ethiopia.",
      "keyword_query": "mental health psychological wellbeing MHPSS children under five young children refugee camp displacement camp Qoloji Ethiopia",
      "boolean_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety) AND (children under five OR young children OR U5) AND (refugee camp OR displacement camp OR IDP camp) AND (Qoloji OR Ethiopia)",
      "controlled_vocabulary": {
        "MeSH": ["Mental Health", "Child", "Ethiopia"]
      },
      "blocks": [
        {
          "role": "topic_or_condition",
          "free_text": ["mental health", "psychological wellbeing", "MHPSS", "depression", "anxiety"],
          "controlled_vocabulary": {"MeSH": ["Mental Health"]}
        }
      ],
      "broadened_aspect": "",
      "broadened_value": "",
      "rationale": "Full synonym and domain-term ring for every concept block.",
      "cochrane_compliant": false
    }
  ],
  "geography_broadening_strategy": "context_proxy",
  "recommended_starting_level": 2,
  "recommendation_rationale": "The named camp is too specific for first-pass retrieval; start with a comparable-context search.",
  "search_filters": {
    "publication_years": "",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Public Health", "Psychology"]
  },
  "phrases": ["mental health outcomes", "children under five", "refugee camp Ethiopia"],
  "metadata": {
    "status": "completed",
    "generated_level_count": 3,
    "used_llm": true,
    "total_tokens": 1234
  }
}
```

Client consumption guidance:

- Use `recommended_starting_level` as the first retrieval level.
- Use `levels[n].boolean_query` for sparse/Boolean search engines.
- Use `levels[n].semantic_query` for vector or semantic retrieval.
- Use `levels[n].keyword_query` for BM25/simple keyword search.
- Use `levels[n].blocks` when you need source-specific query rendering without parsing `boolean_query`.
- Use `search_filters` and `phrases` as cross-level retrieval metadata.

**Cochrane compliance rules enforced by Agent D:**
- Geography is a search artifact: always broaden or remove progressively. Never keep a specific named location past Level 1.
- Setting or context is research scope: keep at every level. Never remove (e.g. "displacement camps" stays at Level 3).
- Named proper-noun locations (e.g. "Qoloji camp") are context proxies: replace with a contextual analogy at Level 2 (e.g. "conflict-affected low- and middle-income countries") before the containment hierarchy.

Calling agents individually in sequence:

```python
# Agent A
norm = POST(f"{BASE}/refinement/normalize", {"query_id": query_id})

# Agent B
sem = POST(f"{BASE}/refinement/represent", {
    "statement": norm["clarified_query"]
})

# Agent C
search = POST(f"{BASE}/refinement/construct", {
    "statement": norm["clarified_query"],
    "concept_graph": sem["concept_graph"]
})

# Agent D (optional)
expand = POST(f"{BASE}/refinement/expand", {
    "statement": norm["clarified_query"],
    "anchor_blocks": search["keyword"]["combined_blocks"],
    "search_context": {"concept_graph": sem["concept_graph"]}
})
```

Or use the single-call orchestration path (POST /synthesize) to run A → B → C at once:

```python
synthesis = POST(f"{BASE}/refinement/synthesize", {"query_id": query_id})
so = synthesis["structured_output"]

expand = POST(f"{BASE}/refinement/expand", {
    "statement": synthesis["clarified_query"],
    "anchor_blocks": so["search_optimized"]["keyword"]["combined_blocks"],
    "search_context": {"concept_graph": so["concept_graph"]}
})
```

Or use the full chained path A → B → C → D directly:

```python
full_chain = POST(f"{BASE}/refinement/synthesize", {
    "query_id": query_id,
    "include_expansion": True
})

levels = full_chain["expansion_levels"]
meta = full_chain["expansion_metadata"]
starting_level = meta["recommended_starting_level"]
```

### Quick-reply / examples field

Every `next_prompt` includes an `examples` list:

```json
"examples": ["elderly patients (65+)", "working-age adults (18–64)", "children under 12"]
```

- Each string is a **complete, standalone answer** — submit it verbatim as `answer`.
- Examples span the clarification range; they are not biased toward the LLM's guess.
- Empty list `[]` is valid — it means the question is open-ended or the aspect was auto-completed.
- A clicked example is submitted identically to a free-text answer:
  ```json
  POST /refinement/queries/{query_id}/answer
  { "answer": "elderly patients (65+)" }
  ```

### RAG field mapping

After `POST /synthesize`, `structured_output` contains all retrieval artifacts:

| Use case                                     | Field path                                                   | Source agent                              |
| -------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------- |
| Dense / vector retrieval                     | `structured_output.search_optimized.semantic`                | Agent B                                   |
| **Primary RAG keyword search**               | `structured_output.search_optimized.keyword.combined_blocks` | Agent C                                   |
| Boolean anchor query (fallback)              | `structured_output.search_optimized.keyword.structured`      | Agent C                                   |
| Exact key phrases                            | `structured_output.search_optimized.keyword.phrases`         | Agent C                                   |
| Controlled vocabulary (MeSH — PubMed only)   | `combined_blocks[i].controlled_vocabulary`                   | Agent C                                   |
| Metadata narrowing filters                   | `structured_output.search_filters`                           | Agent C                                   |
| Synonym expansion per concept                | `structured_output.concept_graph.<concept>`                  | Agent B                                   |
| Clarified research statement                 | `clarified_query`                                            | Agent A                                   |
| Keyword query (BM25 / simple keyword search) | `structured_output.keyword_statement`                        | Agent B                                   |
| Per-dimension refined values                 | `structured_output.dimensions_specifications`                | Agent A                                   |
| Terminology / synonym map                    | `structured_output.terminology`                              | Agent B (legacy — prefer `concept_graph`) |
| Broadening fallback levels                   | `POST /expand` with `statement` + `concept_graph`            | Agent D                                   |

**`combined_blocks` connector rules:**

```
OR  free_text terms  within each block
OR  controlled_vocabulary terms  within each block
AND all blocks together
```

Use `controlled_vocabulary` only for PubMed (MeSH). Use `free_text` alone for all other sources (WHO IRIS, OpenAlex, CORE, ReliefWeb).

### Error handling for agents

| HTTP code | Meaning                 | Action                                                |
| --------- | ----------------------- | ----------------------------------------------------- |
| 401       | Missing or invalid auth | Check `X-API-Key` or `Authorization` header           |
| 403       | Framework access denied | Grant the integration user access to the framework    |
| 404       | Query/session not found | Session may have expired — restart with `/start`      |
| 409       | Already synthesized     | Call `/status` to retrieve the existing result        |
| 422       | Validation error        | Check request body — see error envelope below         |
| 503       | Session lock held       | Retry after 1–2 s; concurrent request on same session |

Retry pattern for 503 (session contention):
```python
for attempt in range(3):
    r = POST(url, body)
    if r.status_code != 503:
        break
    time.sleep(1.5 ** attempt)
```

---

### Agent output examples

All examples use the same input query: `"How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in Qoloji camp, Ethiopia."` This query has geography-as-context-proxy (Qoloji / Ethiopia), a setting block (displacement camp), a population block (two groups), and an intervention block — making it a good test of all agent features.

#### Agent A output

```json
{
  "clarified_query": "How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in Qoloji camp, Ethiopia.",
  "dimensions_specifications": {
    "population": "Children under 5 and pregnant and lactating women (PLW)",
    "intervention": "Mental health and substance misuse interventions",
    "setting": "Qoloji displacement camp, Somali Region, Ethiopia",
    "outcomes": null
  }
}
```

Notes:
- `clarified_query` is the anchor — passed verbatim to Agents B, C, D as `statement`.
- `[SKIPPED]` dimensions map to `null`.
- Filler language ("I want to study", "maybe") is removed; meaningful scope content is kept.

#### Agent B output

```json
{
  "semantic_statement": "Studies on interventions to improve mental health and substance misuse outcomes — including psychosocial support, mental health programming, and harm reduction — in children under 5 and pregnant and lactating women residing in humanitarian displacement settings. Evidence from refugee and internally displaced persons camps in conflict-affected, low-resource contexts.",
  "keyword_statement": "mental health substance misuse MHPSS psychosocial interventions children under 5 pregnant lactating women PLW displacement camp refugee camp IDP Ethiopia humanitarian",
  "concept_graph": {
    "mental health": {
      "query_role": "topic_or_condition",
      "true_synonyms": ["psychological wellbeing", "psychosocial wellbeing", "mental wellbeing"],
      "abbreviations": ["MHPSS"],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": ["depression", "anxiety", "PTSD", "psychological distress", "trauma"],
      "colloquial": ["emotional health"],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Mental Health", "Mental Disorders", "Psychosocial Support Systems"], "confidence": "high"}
      ]
    },
    "substance misuse": {
      "query_role": "topic_or_condition",
      "true_synonyms": ["substance use disorder", "substance abuse", "drug misuse"],
      "abbreviations": ["SUD"],
      "spelling_variants": [],
      "lexical_variants": ["misuse*", "abuse*"],
      "domain_terms": ["alcohol misuse", "drug dependence", "harmful substance use"],
      "colloquial": ["drug abuse"],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Substance-Related Disorders", "Alcohol-Related Disorders"], "confidence": "high"}
      ]
    },
    "children under 5": {
      "query_role": "population_or_entity",
      "true_synonyms": ["under-five children", "young children", "early childhood"],
      "abbreviations": ["U5"],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": ["infants", "toddlers", "neonates", "preschool children"],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Child, Preschool", "Infant"], "confidence": "high"}
      ]
    },
    "pregnant and lactating women": {
      "query_role": "population_or_entity",
      "true_synonyms": ["pregnant women", "lactating women", "breastfeeding mothers"],
      "abbreviations": ["PLW"],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": ["perinatal women", "antenatal women", "postnatal women"],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Pregnant Women", "Breast Feeding"], "confidence": "high"}
      ]
    },
    "interventions to improve outcomes": {
      "query_role": "intervention_or_exposure_or_phenomenon",
      "true_synonyms": ["mental health interventions", "psychosocial interventions", "treatment programmes"],
      "abbreviations": [],
      "spelling_variants": [],
      "lexical_variants": ["treat*", "improv*", "manag*", "support*", "prevent*"],
      "domain_terms": ["cognitive behavioural therapy", "psychoeducation", "case management", "peer support"],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Mental Health Services", "Psychotherapy", "Community Mental Health Services"], "confidence": "medium"}
      ]
    },
    "displacement camp": {
      "query_role": "setting_or_context",
      "true_synonyms": ["refugee camp", "IDP camp", "humanitarian camp"],
      "abbreviations": ["IDP"],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": ["informal settlements", "transit camps", "collective centres"],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Refugees", "Transients and Migrants"], "confidence": "medium"}
      ]
    },
    "Qoloji camp": {
      "query_role": "geography",
      "true_synonyms": [],
      "abbreviations": [],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": [],
      "colloquial": [],
      "controlled_vocabulary_hints": []
    },
    "Ethiopia": {
      "query_role": "geography",
      "true_synonyms": ["Ethiopian"],
      "abbreviations": [],
      "spelling_variants": [],
      "lexical_variants": [],
      "domain_terms": [],
      "colloquial": [],
      "controlled_vocabulary_hints": [
        {"vocabulary_name": "MeSH", "terms": ["Ethiopia"], "confidence": "high"}
      ]
    }
  }
}
```

Notes:
- `domain_terms` (depression, PTSD, CBT, etc.) do NOT appear in Agent C's anchor Boolean query — they widen scope and are reserved for Agent D Level 1.
- Proper noun locations (Qoloji camp, Ethiopia) have empty `domain_terms` by rule — their broadening (e.g. "conflict-affected LMICs") is Agent D's job.
- Geography and setting are extracted as **separate** concepts because "Qoloji camp, Ethiopia" is location (geography) while "displacement camp" is a type of place (setting_or_context).
- `colloquial` terms ("drug abuse") never appear in academic database queries.

#### Agent C output

```json
{
  "keyword": {
    "structured": "(mental health OR psychological wellbeing OR psychosocial wellbeing OR mental wellbeing OR MHPSS OR substance misuse* OR substance use* OR substance abuse* OR SUD) AND (children under 5 OR under-five children OR young children OR early childhood OR U5 OR pregnant and lactating women OR pregnant women OR lactating women OR breastfeeding mothers OR PLW) AND (mental health interventions OR psychosocial interventions OR treatment programmes OR treat* OR improv* OR manag* OR support* OR prevent*) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian camp) AND (Qoloji OR Ethiopia OR Ethiopian)",
    "phrases": [
      "mental health outcomes",
      "substance misuse",
      "children under 5",
      "pregnant and lactating women",
      "displacement camp",
      "psychosocial interventions"
    ],
    "terms": {
      "required": ["mental health", "substance misuse", "displacement camp"],
      "optional": ["MHPSS", "PLW", "psychosocial", "IDP", "humanitarian", "Ethiopia"],
      "excluded": []
    },
    "combined_blocks": [
      {
        "role": "topic_or_condition",
        "free_text": ["mental health", "psychological wellbeing", "psychosocial wellbeing", "mental wellbeing", "MHPSS", "substance misuse", "substance use disorder", "substance abuse", "drug misuse", "SUD"],
        "controlled_vocabulary": {
          "MeSH": ["Mental Health", "Mental Disorders", "Psychosocial Support Systems", "Substance-Related Disorders", "Alcohol-Related Disorders"]
        }
      },
      {
        "role": "population_or_entity",
        "free_text": ["children under 5", "under-five children", "young children", "early childhood", "U5", "pregnant and lactating women", "pregnant women", "lactating women", "breastfeeding mothers", "PLW"],
        "controlled_vocabulary": {
          "MeSH": ["Child, Preschool", "Infant", "Pregnant Women", "Breast Feeding"]
        }
      },
      {
        "role": "intervention_or_exposure_or_phenomenon",
        "free_text": ["mental health interventions", "psychosocial interventions", "treatment programmes", "treat*", "improv*", "manag*", "support*", "prevent*"],
        "controlled_vocabulary": {
          "MeSH": ["Mental Health Services", "Psychotherapy", "Community Mental Health Services"]
        }
      },
      {
        "role": "setting_or_context",
        "free_text": ["displacement camp", "refugee camp", "IDP camp", "humanitarian camp"],
        "controlled_vocabulary": {
          "MeSH": ["Refugees", "Transients and Migrants"]
        }
      },
      {
        "role": "geography",
        "free_text": ["Qoloji", "Ethiopia", "Ethiopian"],
        "controlled_vocabulary": {
          "MeSH": ["Ethiopia"]
        }
      }
    ]
  },
  "search_filters": {
    "publication_years": "",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": ["Medicine", "Public Health"]
  }
}
```

Notes:
- `combined_blocks` mirrors `keyword.structured` block-for-block in the same order. This invariant must hold — connectors derive source-specific queries from `combined_blocks`, not from `keyword.structured`.
- 5 blocks are used (not the default 4) because setting_or_context AND geography are both present — they are always kept as separate AND-blocks. Merging them with OR would collapse the query hierarchy and treat "Ethiopia" as an alternative to "refugee camp" instead of a geographic constraint on where the camps are.
- Wildcards (`misuse*`, `treat*`, `improv*`) are mandatory on verbs and productive nouns. `Qoloji`, `Ethiopia`, `MHPSS`, `PLW`, `IDP`, `SUD` are not wildcarded (proper nouns and abbreviations).
- `domain_terms` (depression, PTSD, CBT, cognitive behavioural therapy, etc.) are absent from `combined_blocks.free_text` and `keyword.structured`. They appear only in Agent D Level 1.

**Using `combined_blocks` with different databases:**

```
PubMed:    (free_text[tiab] OR "MeSH term"[MeSH Terms]) for each block → AND all blocks
WHO IRIS:  free_text terms only (no MeSH tagging) → AND all blocks
OpenAlex:  free_text terms only → AND all blocks
CORE:      free_text terms only → AND all blocks
ReliefWeb: use clarified_query (NL) or keyword_statement from Agent B
```

#### Agent D output

Agent D takes Agent C's `combined_blocks` and Agent B's `concept_graph` and builds a recall ladder. Level 1 is constructed deterministically in Python by enriching each block's `free_text` with `domain_terms` from the concept graph — **no LLM call for Level 1**. Levels 2 and 3 are built by Python from LLM-proposed geography broadening terms.

Every level has the same structure, making them uniform for downstream consumption:

```json
{
  "levels": [
    {
      "level": 1,
      "label": "Full lexical ring",
      "search_query": "(mental health OR psychological wellbeing OR psychosocial wellbeing OR mental wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR psychological distress OR trauma OR substance misuse OR substance use disorder OR substance abuse OR drug misuse OR SUD OR alcohol misuse OR drug dependence OR harmful substance use) AND (children under 5 OR under-five children OR young children OR early childhood OR U5 OR infants OR toddlers OR neonates OR preschool children OR pregnant and lactating women OR pregnant women OR lactating women OR breastfeeding mothers OR PLW OR perinatal women OR antenatal women OR postnatal women) AND (mental health interventions OR psychosocial interventions OR treatment programmes OR treat* OR improv* OR manag* OR support* OR prevent* OR cognitive behavioural therapy OR psychoeducation OR case management OR peer support) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian camp OR informal settlements OR transit camps OR collective centres) AND (Qoloji OR Ethiopia OR Ethiopian)",
      "clarified_query": "How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in Qoloji camp, Ethiopia.",
      "controlled_vocabulary": {
        "MeSH": ["Mental Health", "Mental Disorders", "Psychosocial Support Systems", "Substance-Related Disorders", "Child, Preschool", "Infant", "Pregnant Women", "Mental Health Services", "Psychotherapy", "Refugees", "Transients and Migrants", "Ethiopia"]
      },
      "broadened_aspect": "",
      "broadened_value": "",
      "rationale": "Deterministically built from Agent C combined_blocks enriched with domain_terms from Agent B concept_graph. Adds depression, PTSD, CBT, peer support and other domain terms not present in the Agent C anchor query.",
      "cochrane_compliant": false
    },
    {
      "level": 2,
      "label": "Contextual analogy — conflict-affected LMICs",
      "search_query": "(mental health OR psychological wellbeing OR psychosocial wellbeing OR mental wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR psychological distress OR trauma OR substance misuse OR substance use disorder OR substance abuse OR drug misuse OR SUD OR alcohol misuse OR drug dependence OR harmful substance use) AND (children under 5 OR under-five children OR young children OR early childhood OR U5 OR infants OR toddlers OR neonates OR preschool children OR pregnant and lactating women OR pregnant women OR lactating women OR breastfeeding mothers OR PLW OR perinatal women OR antenatal women OR postnatal women) AND (mental health interventions OR psychosocial interventions OR treatment programmes OR treat* OR improv* OR manag* OR support* OR prevent* OR cognitive behavioural therapy OR psychoeducation OR case management OR peer support) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian camp OR informal settlements OR transit camps OR collective centres) AND (\"conflict-affected low-income countries\" OR \"conflict-affected middle-income countries\" OR \"fragile states\" OR \"post-conflict countries\" OR \"humanitarian crisis countries\")",
      "clarified_query": "How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in displacement camps in conflict-affected low- and middle-income countries.",
      "controlled_vocabulary": {
        "MeSH": ["Mental Health", "Mental Disorders", "Psychosocial Support Systems", "Substance-Related Disorders", "Child, Preschool", "Infant", "Pregnant Women", "Mental Health Services", "Psychotherapy", "Refugees", "Transients and Migrants"]
      },
      "broadened_aspect": "geography",
      "broadened_value": "conflict-affected low- and middle-income countries",
      "rationale": "Qoloji camp and Ethiopia are context proxies for a humanitarian displacement crisis. Replacing them with a contextual analogy captures equivalent evidence from South Asia, the Middle East, and Latin America. Ethiopia MeSH heading excluded — it would incorrectly restrict to Ethiopian-indexed literature.",
      "cochrane_compliant": false
    },
    {
      "level": 3,
      "label": "No geographic restriction — Cochrane-sensitive search",
      "search_query": "(mental health OR psychological wellbeing OR psychosocial wellbeing OR mental wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR psychological distress OR trauma OR substance misuse OR substance use disorder OR substance abuse OR drug misuse OR SUD OR alcohol misuse OR drug dependence OR harmful substance use) AND (children under 5 OR under-five children OR young children OR early childhood OR U5 OR infants OR toddlers OR neonates OR preschool children OR pregnant and lactating women OR pregnant women OR lactating women OR breastfeeding mothers OR PLW OR perinatal women OR antenatal women OR postnatal women) AND (mental health interventions OR psychosocial interventions OR treatment programmes OR treat* OR improv* OR manag* OR support* OR prevent* OR cognitive behavioural therapy OR psychoeducation OR case management OR peer support) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian camp OR informal settlements OR transit camps OR collective centres)",
      "clarified_query": "How to improve mental health and substance misuse outcomes in children under 5 and pregnant and lactating women in displacement camps globally.",
      "controlled_vocabulary": {
        "MeSH": ["Mental Health", "Mental Disorders", "Psychosocial Support Systems", "Substance-Related Disorders", "Child, Preschool", "Infant", "Pregnant Women", "Mental Health Services", "Psychotherapy", "Refugees", "Transients and Migrants"]
      },
      "broadened_aspect": "geography",
      "broadened_value": "(no restriction)",
      "rationale": "Geography block removed entirely. Setting block (displacement camp) is retained — it defines the research scope and must never be removed. This is the Cochrane-compliant globally sensitive search.",
      "cochrane_compliant": true
    }
  ],
  "geography_broadening_strategy": "context_proxy",
  "recommended_starting_level": 2,
  "recommendation_rationale": "Level 1 names Qoloji camp — a specific site appearing in almost no published literature. Level 2 broadens to conflict-affected displacement contexts globally with substantially better coverage while still retaining a meaningful context signal."
}
```

Notes:
- All three levels share the same output structure — downstream consumers (PubMed connectors, WHO IRIS connectors, UI display) iterate the same array uniformly.
- `controlled_vocabulary` at Level 1 includes all blocks including geography (Ethiopia MeSH). At Levels 2 and 3, geography block MeSH terms are excluded — geographic MeSH headings are search artifacts that should not carry over to a broadened search.
- `clarified_query` at each level is the NL anchor adapted to that level's geographic scope. Use this for databases that accept NL input (ReliefWeb, WHO IRIS NL mode) and for display in the UI.
- `cochrane_compliant: true` at Level 3 signals the Cochrane-sensitive search: no geographic restriction, setting retained.

### Applying Agent D levels to external databases

Every `ExpansionLevel` in the `levels` array carries three query forms:

| Field                   | Use for                                                                  |
| ----------------------- | ------------------------------------------------------------------------ |
| `search_query`          | Boolean keyword query — submit directly to most databases                |
| `clarified_query`       | Natural language equivalent — use for display and NL-accepting databases |
| `controlled_vocabulary` | MeSH headings — enrich PubMed queries only                               |

Start at `recommended_starting_level`. Escalate to the next level if result count falls below your threshold. `cochrane_compliant: true` (Level 3) is the widest search — use it when coverage is the priority.

#### PubMed (MEDLINE)

PubMed supports boolean queries with field tags. You can submit `search_query` as-is — PubMed applies automatic term mapping to untagged terms. For maximum precision, rebuild per block with field tags:

- `free_text` terms → `term[tiab]` (title and abstract)
- `controlled_vocabulary.MeSH` → `"Heading"[MeSH Terms]`

At Levels 2–3, `controlled_vocabulary` already excludes geography MeSH terms — do not re-add them (a geographic heading would silently re-restrict the search).

**Level 2 example (field-tagged, built from Agent C blocks with geography replaced):**

```
(mental health[tiab] OR MHPSS[tiab] OR "Mental Health"[MeSH Terms] OR "Mental Disorders"[MeSH Terms])
AND (children under 5[tiab] OR U5[tiab] OR "Child, Preschool"[MeSH Terms] OR pregnant women[tiab] OR "Pregnant Women"[MeSH Terms])
AND (treat*[tiab] OR improv*[tiab] OR "Mental Health Services"[MeSH Terms])
AND (displacement camp[tiab] OR refugee camp[tiab] OR "Refugees"[MeSH Terms])
AND (conflict-affected low-income countries[tiab] OR fragile states[tiab] OR humanitarian crisis[tiab])
```

PubMed supports wildcard truncation (`treat*`, `improv*`) up to 600 expansions per term.

#### WHO IRIS

Submit `search_query` directly to the WHO IRIS search endpoint. No controlled vocabulary tagging is needed — use free-text terms only with OR within blocks and AND between blocks.

For natural language access, submit `clarified_query` as the query value instead.

#### ReliefWeb

Use `clarified_query` as the `query.value` field — ReliefWeb's Lucene engine handles natural language queries well and this is the most reliable approach. For structured boolean, `search_query` can be submitted directly:

```python
requests.post(
    "https://api.reliefweb.int/v1/reports",
    json={"query": {"value": level["clarified_query"]}, "limit": 20}
)
```

`controlled_vocabulary` is not applicable to ReliefWeb.

#### CORE

Submit `search_query` directly as the `q` parameter in the CORE v3 API:

```python
requests.post(
    "https://api.core.ac.uk/v3/search/works",
    headers={"Authorization": f"Bearer {CORE_API_KEY}"},
    json={"q": level["search_query"], "limit": 25}
)
```

`controlled_vocabulary` is not applicable to CORE.

#### OpenAlex

Build a space-separated keyword string from the most important `free_text` terms (topic/condition and intervention blocks are usually sufficient) and pass it as the `search` parameter:

```
GET https://api.openalex.org/works?search=mental+health+MHPSS+psychosocial+displacement+camp
```

For field-scoped precision, use `title.search` and `abstract.search` filters. OpenAlex has a ~4 KB URL limit — use the top terms from each block rather than the full `search_query`. `controlled_vocabulary` is not applicable.

---

## Refinement Workflow

- `GET /api/v1/refinement/frameworks`
- `POST /api/v1/refinement/start`
- `POST /api/v1/refinement/queries/{query_id}/answer`
- `GET /api/v1/refinement/queries/{query_id}/status`
- `POST /api/v1/refinement/queries/{query_id}/resume`
- `POST /api/v1/refinement/normalize`
- `POST /api/v1/refinement/represent`
- `POST /api/v1/refinement/construct`
- `POST /api/v1/refinement/synthesize`
- `POST /api/v1/refinement/expand`
- `POST /api/v1/refinement/queries/{query_id}/forward-to-qa`
- `GET /api/v1/refinement/queries/{query_id}/command-history`
- `GET /api/v1/refinement/queries/{query_id}/inspect-messages`
- `GET /api/v1/refinement/queries/{query_id}/progress`
- `POST /api/v1/refinement/sessions/abandon`

Refinement workflow endpoints require either `Authorization: Bearer <token>` or `X-API-Key: <integration-api-key>`.

`X-API-Key` authentication resolves to the configured integration service user. That user must already have framework access assigned, or `/api/v1/refinement/start` will return `403` with `You are not authorized to use framework ...`.

`/api/v1/refinement/start` is **POST-only** (no GET variant is implemented).

`POST /api/v1/refinement/start` accepts:

- `original_query` (string)
- `framework_name` (string)
- `source` (optional: `gui` or `api_integration`, defaults to `gui`)
- `skip_refinement` (optional boolean, defaults to `false`) — when `true`, all refinement dimensions are skipped and synthesis is executed immediately as part of the same request. No per-dimension LLM calls are made; the response contains a `synthesis` object with the final result. Intended for API integrations that want a single-call workflow at the cost of refinement quality.

Start response includes: `session_id`, `query_id`, `summary`, optional `next_prompt`, `ready_for_synthesis`, `source`, and optional `synthesis` (populated only when `skip_refinement=true`).

`POST /api/v1/refinement/queries/{query_id}/answer` returns:

- `SubmitAnswerResponse` for normal answers (includes `ready_for_synthesis`)
- `CommandResponse` for slash commands (includes optional `synthesis_ready` when using `/submit` or `/end`)

### Refinement response shapes

The workflow endpoints return different response envelopes depending on the step.

#### `POST /api/v1/refinement/start`

Returns `StartRefinementResponse` with these fields:

- `session_id`: database session ID
- `query_id`: database query ID
- `summary`: initialization summary for the new workflow
- `next_prompt`: the first refinement question, or `null` if the workflow is already complete
- `ready_for_synthesis`: `true` when no more refinement questions are needed
- `source`: `gui` or `api_integration`
- `synthesis`: present only when `skip_refinement=true`; contains the same synthesis envelope returned by `/refinement/synthesize`

`summary` is a compact object that reports the overall workflow state. Clients should expect counts such as:

- `total_aspects`
- `aspects_needing_refinement`
- `aspects_clear`
- `is_complete`

`next_prompt` is the next question the client should display to the user. It uses this shape:

```json
{
	"aspect_id": "population",
	"name": "Population",
	"question": "Which population does your query target?",
	"description": "Target population characteristics",
	"examples": [
		"elderly patients (65+)",
		"working-age adults (18–64)",
		"children under 12",
		"all ages"
	]
}
```

- `question` — plain prose clarifying question, no embedded examples.
- `examples` — 0–4 concrete quick-reply strings that **span the clarification space**. Each string is a complete, standalone answer the user can select as-is. Intended to be rendered as clickable buttons. Empty when the question does not apply (e.g. the aspect was already clear) or when `complete=true`.

#### `POST /api/v1/refinement/queries/{query_id}/answer`

This endpoint is polymorphic. The response depends on whether the submitted text is a normal answer or a slash command.

Normal answers return `SubmitAnswerResponse`:

- `refinement_step_id`: refinement step record ID
- `followup_id`: follow-up record ID
- `is_complete`: whether the current aspect is complete
- `next_prompt`: the next question, or `null` if no follow-up is needed
- `ready_for_synthesis`: `true` when all aspects are complete and the workflow can move to synthesis

Slash commands return `CommandResponse`:

- `command_type`: the parsed command name such as `status`, `back`, `skip`, `submit`, or `steps`
- `success`: whether the command executed successfully
- `message`: human-readable feedback
- `next_prompt`: the next question after the command, or `null`
- `invalidated_aspects`: aspect IDs that were reset or marked for review
- `synthesis_ready`: `true` when `/submit` or `/end` has completed the workflow
- `step_summary`: present for `/status`
- `step_list`: present for `/steps`
- `force_required`: `true` when the command needs `force=true` to continue

`next_prompt` uses the same shape as the start response. When returned after a command, it can be used directly by the UI without extra transformation.

#### `POST /api/v1/refinement/queries/{query_id}/resume`

Returns `ResumeRefinementResponse` (extends `GetRefinementStatusResponse`) with the same fields as the status endpoint. Use this to explicitly regenerate the next prompt after a server restart or Redis session eviction. The endpoint does not advance the workflow — it only ensures the session is loaded and the active prompt is ready. Returns 404 if the query does not exist, 403 if access is denied, and 503 if the session lock is temporarily held by another request.

#### `GET /api/v1/refinement/queries/{query_id}/status`

- `query_id`: query record ID
- `original_query`: the original user question
- `refined_query`: the latest refined statement, or `null` if synthesis has not completed
- `is_complete`: whether the workflow is fully complete
- `current_aspect`: the current aspect being refined, or `null`
- `aspects_summary`: overall workflow summary
- `next_prompt`: the next question, or `null`
- `ready_for_synthesis`: `true` when synthesis can be started
- `aspects`: per-aspect status records
- `conversation_history`: the UI restoration history for the session

The `aspects` array contains lightweight status objects such as:

```json
{
	"aspect_id": "population",
	"name": "Population",
	"is_complete": false,
	"needs_review": false,
	"was_skipped": false,
	"status": "active"
}
```

The `conversation_history` array is ordered and contains the visible interaction trail. Typical items include:

- `type`: `query`, `question`, or `answer`
- `content`: the message text
- `aspectId`: optional aspect identifier
- `aspectName`: optional display label

#### `POST /api/v1/refinement/synthesize`

Returns `SynthesizeQueryResponse` with these fields:

- `query_id`: query record ID
- `clarified_query`: the final clarified statement
- `used_llm`: whether synthesis used the LLM path
- `structured_output`: optional structured result for clients that need search-ready fields

Canonical synthesis field names used by the API and internal runtime are:

- `clarified_query` (Agent A output; called `statement` when passed as input to Agents B, C, D)
- `dimensions_specifications`
- `search_optimized`
- `search_filters`
- `terminology`
- `metadata`
- `processing_log`

The query persistence schema now uses the same canonical synthesis names. The SQLAlchemy model exposes the `metadata` database column as `synthesis_metadata` because `metadata` is a reserved declarative attribute name.

The detailed `structured_output` contract is described below.

#### `POST /api/v1/refinement/expand`

Generates optional search expansion levels from a standalone request payload. The endpoint does not depend on a persisted query or a completed synthesis result. Callers provide the exact Level 0 statement (from Agent A's `clarified_query`) and optional search context with filters and synonyms.

The service runs a two-stage pipeline:

1. **Aspect assessment** — the anchor query is assessed against a fixed internal ontology of six search aspects: `topic_or_condition`, `population_or_entity`, `intervention_or_exposure_or_phenomenon`, `setting_or_context`, `geography`, and `time_scope`. For each detected aspect, the assessment records the value as expressed in the anchor and an ordered list of strict-superset broadening candidates.
2. **Expansion generation** — a deterministic safety policy classifies each detected aspect as `safe`, `conditional` (`topic_or_condition` and `intervention_or_exposure_or_phenomenon`), or `avoid` (undetected aspects). Expansion levels may relax only safe or conditional aspects, at most two per level, and at most one conditional aspect per level.

Request body:

```json
{
	"statement": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"search_context": {
		"filters": {
			"publication_types": ["randomized controlled trial"]
		},
		"concept_graph": {"...": "structured_output.concept_graph from POST /synthesize"}
	},
	"model": "optional-model-override"
}
```

The `statement` parameter is required and must be provided. Optional parameters:
- `search_context`: optional retrieval context. Set `search_context.concept_graph` to `structured_output["concept_graph"]` from a prior `/represent` or `/synthesize` call for best results.
- `model`: optional LLM model override.

`search_context.concept_graph` should be set to `structured_output["concept_graph"]` from a prior `/synthesize` call. It provides the full lexical context (synonyms, domain terms, controlled vocabulary hints) for each concept, enabling more accurate broadening candidates. Without it, Agent D falls back to aspect detection from the anchor query text alone.

Returns `SearchExpandResponse` with these fields:

- `levels`: list of `ExpansionLevel` objects — Level 1 (deterministic) plus up to two broader levels
- `geography_broadening_strategy`: `context_proxy`, `containment_hierarchy`, or `none`
- `recommended_starting_level`: integer (1–3) recommended by the LLM
- `recommendation_rationale`: rationale for the recommended starting level
- `metadata`: token and generation metadata

Each level in `levels` has the same structure: `level`, `label`, `search_query`, `clarified_query`, `controlled_vocabulary`, `broadened_aspect`, `broadened_value`, `rationale`, `cochrane_compliant`. Level 1 is always `levels[0]` and is built deterministically in Python — no LLM call. The LLM only proposes geography broadening terms and `clarified_query` for Levels 2–3.

`metadata.status` is one of: `completed`, `no_geography` (no geography block — Level 1 only returned), or `failed`.

### Generic external integration snippet

```bash
curl -X POST http://localhost:8001/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'X-API-Key: <integration-api-key>' \
	-d '{
		"original_query": "effects of aspirin in older adults",
		"framework_name": "pico_advanced",
		"source": "api_integration"
	}'
```

### Expected response structures (integration)

The following are the expected response envelopes for external integrations.

#### `GET /api/v1/refinement/frameworks` (200)

```json
{
	"frameworks": ["pico_advanced", "mph_dissertation"],
	"count": 2
}
```

#### `POST /api/v1/refinement/start` (201)

```json
{
	"session_id": 101,
	"query_id": 123,
	"summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 3,
		"aspects_clear": 1,
		"is_complete": false
	},
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Which population does your query target?",
		"description": "Target population characteristics",
		"examples": ["elderly patients (65+)", "working-age adults (18–64)", "children under 12"]
	},
	"ready_for_synthesis": false,
	"source": "api_integration",
	"synthesis": null
}
```

Notes:

- `next_prompt` can be `null` when the session is already complete.
- `ready_for_synthesis=true` means the next call should be `/refinement/synthesize`.
- `synthesis` is `null` in normal flow. When `skip_refinement=true` it is populated with the same envelope as `/refinement/synthesize` so no follow-up call is needed.

##### `POST /api/v1/refinement/start` with `skip_refinement=true` (201)

```bash
curl -X POST http://localhost:8001/api/v1/refinement/start \
	-H 'Content-Type: application/json' \
	-H 'X-API-Key: <integration-api-key>' \
	-d '{
		"original_query": "effects of aspirin in older adults",
		"framework_name": "pico_advanced",
		"source": "api_integration",
		"skip_refinement": true
	}'
```

```json
{
	"session_id": 101,
	"query_id": 124,
	"summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 0,
		"aspects_clear": 4,
		"is_complete": true
	},
	"next_prompt": null,
	"ready_for_synthesis": true,
	"source": "api_integration",
	"synthesis": {
		"query_id": 124,
		"clarified_query": "In adults, compare aspirin versus placebo for stroke prevention.",
		"used_llm": true,
		"structured_output": null
	}
}
```

Notes:

- All dimensions are recorded as skipped in the database (audit trail preserved).
- A subsequent call to `/refinement/synthesize` will return `409 Conflict` because synthesis was already performed.
- The `/refinement/synthesize` endpoint remains available for normal (non-skip) workflows.

#### `POST /api/v1/refinement/queries/{query_id}/answer` (200)

Request body (for both regular answers and slash commands):

```json
{ "answer": "elderly patients aged 65 and over" }
```

To submit a quick-reply example, send its string verbatim:

```json
{ "answer": "elderly patients (65+)" }
```

Slash commands use the same field:

```json
{ "answer": "/skip" }
{ "answer": "/back" }
{ "answer": "/status" }
{ "answer": "/done" }
{ "answer": "/submit" }
```

This endpoint has two response types.

**A) Regular answer (`SubmitAnswerResponse`)**

```json
{
	"refinement_step_id": 88,
	"followup_id": 351,
	"is_complete": false,
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Any age range constraints?",
		"description": "Target population characteristics",
		"examples": ["all ages", "adults only (18+)", "elderly (65+)"]
	},
	"ready_for_synthesis": false
}
```

**B) Slash command (`CommandResponse`)**

```json
{
	"command_type": "status",
	"success": true,
	"message": "Session status retrieved",
	"next_prompt": {
		"aspect_id": "intervention",
		"name": "Intervention",
		"question": "Which intervention does your query examine?",
		"description": "Intervention details",
		"examples": ["drug therapy", "surgical procedure", "behavioural intervention"]
	},
	"invalidated_aspects": null,
	"synthesis_ready": null,
	"step_summary": {
		"total": 4,
		"completed": 2,
		"active": 1,
		"needs_review": 0
	},
	"step_list": null,
	"force_required": null
}
```

Command-specific fields to expect:

- `/status` -> `step_summary` populated
- `/steps` -> `step_list` populated
- `/submit`, `/end` -> `synthesis_ready=true`, `next_prompt=null`
- `/back`, `/restart` -> `invalidated_aspects` may be populated
- force confirmation required -> `force_required=true`

#### `POST /api/v1/refinement/queries/{query_id}/resume` (200)

Returns the same JSON envelope as `GET /api/v1/refinement/queries/{query_id}/status`. The endpoint reconstructs the session from the database if it is not in Redis, regenerates the active prompt if one is missing, and returns the current workflow state. Idempotent — safe to call multiple times.

#### `GET /api/v1/refinement/queries/{query_id}/status` (200)

```json
{
	"query_id": 123,
	"original_query": "effects of aspirin in older adults",
	"refined_query": null,
	"is_complete": false,
	"current_aspect": "Population",
	"aspects_summary": {
		"total_aspects": 4,
		"aspects_needing_refinement": 2,
		"aspects_clear": 2,
		"is_complete": false
	},
	"next_prompt": {
		"aspect_id": "population",
		"name": "Population",
		"question": "Any age range constraints?",
		"description": "Target population characteristics",
		"examples": ["all ages", "adults only (18+)", "elderly (65+)"]
	},
	"ready_for_synthesis": false,
	"aspects": [
		{
			"aspect_id": "population",
			"name": "Population",
			"is_complete": false,
			"needs_review": false,
			"was_skipped": false,
			"status": "active"
		}
	],
	"conversation_history": [
		{"type": "query", "content": "effects of aspirin in older adults"},
		{"type": "question", "content": "Which population are you focusing on?", "aspectId": "population", "aspectName": "Population"},
		{"type": "answer", "content": "Adults over 65", "aspectId": "population"}
	]
}
```

#### `POST /api/v1/refinement/synthesize` (200)

Request body:

```json
{ "query_id": 123 }
```

Response:

```json
{
	"query_id": 123,
	"clarified_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"used_llm": true,
	"structured_output": {
		"dimensions_specifications": {
			"population": "Adults over 65",
			"intervention": "Aspirin",
			"comparator": "Placebo",
			"outcome": "Stroke prevention"
		},
		"search_optimized": {
			"semantic": "Studies of aspirin compared with placebo for stroke prevention in adults over 65.",
			"keyword": {
				"structured": "(aspirin OR acetylsalicylic acid OR ASA) AND (placebo OR control OR sham) AND (stroke prevention OR cerebrovascular accident prevention OR stroke prophylaxis)",
				"phrases": ["stroke prevention", "older adults", "aspirin trial"],
				"terms": {
					"required": ["aspirin", "stroke", "placebo"],
					"optional": ["acetylsalicylic acid", "cerebrovascular", "older adults"],
					"excluded": []
				},
				"combined_blocks": [
					{
						"role": "topic_or_condition",
						"free_text": ["stroke prevention", "cerebrovascular accident prevention", "stroke prophylaxis"],
						"controlled_vocabulary": {
							"MeSH": ["Stroke", "Brain Ischemia", "Cerebrovascular Disorders"]
						}
					},
					{
						"role": "population_or_entity",
						"free_text": ["adults over 65", "older adults", "elderly"],
						"controlled_vocabulary": {
							"MeSH": ["Aged", "Aged, 80 and over"]
						}
					},
					{
						"role": "intervention_or_exposure_or_phenomenon",
						"free_text": ["aspirin", "acetylsalicylic acid", "ASA"],
						"controlled_vocabulary": {
							"MeSH": ["Aspirin", "Platelet Aggregation Inhibitors"]
						}
					}
				]
			},
		},
		"concept_graph": {
			"aspirin": {
				"query_role": "intervention_or_exposure_or_phenomenon",
				"true_synonyms": ["acetylsalicylic acid"],
				"abbreviations": ["ASA"],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["antiplatelet agent", "salicylate"],
				"colloquial": ["blood thinner"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Aspirin", "Platelet Aggregation Inhibitors"], "confidence": "high"}
				]
			},
			"stroke prevention": {
				"query_role": "topic_or_condition",
				"true_synonyms": ["cerebrovascular accident prevention", "stroke prophylaxis"],
				"abbreviations": [],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["ischaemic stroke prevention", "TIA prevention"],
				"colloquial": ["clot prevention"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Stroke", "Brain Ischemia"], "confidence": "high"}
				]
			},
			"adults over 65": {
				"query_role": "population_or_entity",
				"true_synonyms": ["older adults", "elderly"],
				"abbreviations": [],
				"spelling_variants": [],
				"lexical_variants": [],
				"domain_terms": ["geriatric population", "senior adults"],
				"colloquial": ["elderly people"],
				"controlled_vocabulary_hints": [
					{"vocabulary_name": "MeSH", "terms": ["Aged", "Aged, 80 and over"], "confidence": "high"}
				]
			}
		},
		"search_filters": {
			"publication_years": "2020-2026",
			"venues": [],
			"authors": [],
			"publication_types": [],
			"fields_of_study": ["Medicine", "Public Health"]
		},
		"terminology": {
			"synonyms": {
				"aspirin": ["acetylsalicylic acid", "ASA"],
				"placebo": ["sham", "control"],
				"stroke prevention": ["cerebrovascular prevention", "stroke prophylaxis"]
			}
		}
	}
}
```

Notes:

- `structured_output` can be `null` when the service cannot derive a structured payload from the synthesis result.
- When present, `structured_output` is assembled from the three internal synthesis agents (A → B → C):
  - `clarified_query` (**Agent A**): clarified research statement — the review anchor and Level 0 query (passed as `statement` to Agents B, C, D)
  - `dimensions_specifications` (**Agent A**): the refined value for each dimension, keyed by dimension id — assembled deterministically from session state, never from the LLM
  - `search_optimized` (**Agents B + C**): retrieval-ready search artifacts:
    - `semantic` (**Agent B**): dense embedding query for vector search
    - `keyword.structured` (**Agent C**): Boolean anchor query for sparse/keyword search
    - `keyword.combined_blocks` (**Agent C**): **primary RAG artifact** — one entry per AND-block with `role`, `free_text` terms, and `controlled_vocabulary` (vocabulary name → headings). Source connectors: OR `free_text` with `controlled_vocabulary` within each block, then AND all blocks. Use `controlled_vocabulary` only for PubMed (MeSH); use `free_text` alone for all other sources (WHO IRIS, OpenAlex, CORE, ReliefWeb).
  - `concept_graph` (**Agent B**): per-concept retrieval metadata — pass as `search_context.concept_graph` to `/expand` for Agent D broadening levels. Each concept entry has: `query_role`, `true_synonyms`, `abbreviations`, `spelling_variants`, `lexical_variants`, `domain_terms`, `colloquial`, `controlled_vocabulary_hints`.
  - `search_filters` (**Agent C**): optional narrowing filters — `publication_years`, `venues`, `authors`, and `publication_types` are extracted deterministically from the query text; `fields_of_study` is LLM-generated and constrained to a permitted-values list
  - `terminology` (**Agent B**, legacy): synonym mappings — use `concept_graph` in preference to this for structured retrieval
- `search_optimized.keyword.terms.required` contains the smallest set of anchors that should remain in the query.
- `search_optimized.keyword.terms.optional` contains precision-raising terms.
- `search_optimized.keyword.terms.excluded` contains only true confounders, not close variants of the target concept.

#### `POST /api/v1/refinement/expand` (200)

Example using the Qoloji query (see "Agent output examples" above for full Agent D context):

```json
{
	"levels": [
		{
			"level": 1,
			"label": "Full lexical ring",
			"search_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR substance misuse OR substance use disorder OR SUD) AND (children under 5 OR U5 OR infants OR pregnant women OR PLW OR lactating women) AND (treat* OR improv* OR manag* OR support* OR prevent*) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian setting) AND (Qoloji OR Ethiopia OR Ethiopian)",
			"clarified_query": "What interventions improve mental health and substance misuse outcomes for children under 5 and pregnant and lactating women in Qoloji camp, Ethiopia?",
			"controlled_vocabulary": {
				"MeSH": ["Mental Health", "Substance-Related Disorders", "Child, Preschool", "Pregnant Women", "Refugees", "Ethiopia"]
			},
			"broadened_aspect": "",
			"broadened_value": "",
			"rationale": "Level 1 built deterministically from Agent C combined_blocks plus domain_terms from Agent B concept graph. All concept blocks AND-joined; synonyms and domain terms OR-grouped per block.",
			"cochrane_compliant": false
		},
		{
			"level": 2,
			"label": "Broader geography — contextual analogy",
			"search_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR substance misuse OR substance use disorder OR SUD) AND (children under 5 OR U5 OR infants OR pregnant women OR PLW OR lactating women) AND (treat* OR improv* OR manag* OR support* OR prevent*) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian setting) AND (conflict-affected low- and middle-income countries OR humanitarian crisis OR fragile states)",
			"clarified_query": "What interventions improve mental health and substance misuse outcomes for children under 5 and pregnant and lactating women in conflict-affected low- and middle-income countries?",
			"controlled_vocabulary": {
				"MeSH": ["Mental Health", "Substance-Related Disorders", "Child, Preschool", "Pregnant Women", "Refugees"]
			},
			"broadened_aspect": "geography",
			"broadened_value": "conflict-affected low- and middle-income countries",
			"rationale": "Qoloji and Ethiopia are context proxies for a humanitarian displacement crisis. Replaced with a contextual analogy covering equivalent crises globally. Geography MeSH terms excluded. Setting block unchanged.",
			"cochrane_compliant": false
		},
		{
			"level": 3,
			"label": "No geographic restriction — Cochrane-sensitive search",
			"search_query": "(mental health OR psychological wellbeing OR MHPSS OR depression OR anxiety OR PTSD OR substance misuse OR substance use disorder OR SUD) AND (children under 5 OR U5 OR infants OR pregnant women OR PLW OR lactating women) AND (treat* OR improv* OR manag* OR support* OR prevent*) AND (displacement camp OR refugee camp OR IDP camp OR humanitarian setting)",
			"clarified_query": "What interventions improve mental health and substance misuse outcomes for children under 5 and pregnant and lactating women in humanitarian or displacement settings?",
			"controlled_vocabulary": {
				"MeSH": ["Mental Health", "Substance-Related Disorders", "Child, Preschool", "Pregnant Women", "Refugees"]
			},
			"broadened_aspect": "geography",
			"broadened_value": "",
			"rationale": "Geography block removed entirely — Cochrane-compliant sensitive search. Setting block retained: it defines the research scope and must not be removed.",
			"cochrane_compliant": true
		}
	],
	"geography_broadening_strategy": "context_proxy",
	"recommended_starting_level": 2,
	"recommendation_rationale": "Qoloji is a named camp with very limited indexed literature; Level 2 (contextual analogy) provides recall without losing humanitarian displacement framing.",
	"metadata": {
		"used_llm": true,
		"status": "completed",
		"generated_level_count": 2,
		"prompt_tokens": 620,
		"completion_tokens": 480,
		"total_tokens": 1100
	}
}
```

Notes:

- `levels[0]` is always Level 1, built deterministically in Python from Agent C `combined_blocks` + Agent B `concept_graph`. No LLM call needed for Level 1.
- Levels 2–3 are built by Python from the LLM's geography broadening proposals — the LLM only proposes `boolean_terms` and `clarified_query` per level.
- `cochrane_compliant: true` marks levels where the geography block has been removed entirely, consistent with Cochrane Handbook sensitive search guidance.
- Geography `controlled_vocabulary` (e.g. `Ethiopia[MeSH]`) is excluded at Levels 2 and 3 — MeSH geography tags would re-restrict the broadened search.
- Setting or context is never removed — it defines the research scope and its removal would change the research question, not improve recall.
- `geography_broadening_strategy` is one of `context_proxy` (named location proxies a crisis type — contextual analogy preferred), `containment_hierarchy` (true geographic containment — region/continent), or `none` (no geography block detected).
- `metadata.status` is one of: `completed`, `no_geography` (no geography block — Level 1 only returned), or `failed`.

#### `POST /api/v1/refinement/queries/{query_id}/forward-to-qa` (200)

Request body:

```json
{
	"qa_system_url": "https://qa.example.com/api/query",
	"qa_system_auth": { "Authorization": "Bearer <token>" },
	"timeout_seconds": 30,
	"include_refinement_metadata": true,
	"forward_original_query": false
}
```

- `qa_system_url` must be a public HTTPS URL — private/loopback IPs and RFC-1918 addresses are rejected.
- `qa_system_auth` accepts any custom HTTP headers except hop-by-hop headers (`host`, `connection`, etc.).
- `forward_original_query`: when `true`, the original unrefined query is also sent alongside the refined query.

Response:

```json
{
	"query_id": 123,
	"refined_query": "In adults over 65, compare aspirin versus placebo for stroke prevention.",
	"original_query": null,
	"qa_system_url": "https://qa.example.com/api/query",
	"qa_system_response": {
		"answer": "..."
	},
	"qa_system_status_code": 200,
	"response_time_ms": 1250,
	"refinement_metadata": {
		"framework": "pico_advanced",
		"total_steps": 4,
		"dimensions_refined": ["population", "intervention", "comparator", "outcome"],
		"query_id": 123
	}
}
```

Notes:

- `original_query` is only included when `forward_original_query=true`.
- `refinement_metadata` is only included when `include_refinement_metadata=true`.

#### `GET /api/v1/refinement/queries/{query_id}/command-history` (200)

```json
{
	"query_id": 123,
	"total_commands": 2,
	"commands": [
		{
			"timestamp": "2026-02-23T10:00:00.000000",
			"event_id": 9001,
			"command": "status",
			"command_input": "/status",
			"argument": null,
			"active_dimension": "population",
			"success": true,
			"status": "success",
			"force_requested": false,
			"force_confirmation_needed": false,
			"cleared_aspects": null,
			"invalidated_aspects": null,
			"target_aspect": null,
			"deleted_db_records": null,
			"username": "api_integration_service",
			"request_id": "req_abc123"
		}
	]
}
```

#### `GET /api/v1/refinement/queries/{query_id}/inspect-messages` (200)

```json
{
	"query_id": 123,
	"current_dimension": "population",
	"message_count": 3,
	"messages": [
		{"role": "system", "content": "..."},
		{"role": "user", "content": "..."}
	],
	"user_context_detected": true,
	"user_context_preview": "User Context: ..."
}
```

#### `POST /api/v1/refinement/sessions/abandon` (200)

```json
{
	"status": "success",
	"session_id": 101,
	"deletion_counts": {
		"queries": 1,
		"refinement_steps": 4,
		"followups": 7,
		"feedback": 0
	},
	"message": "Session 101 abandoned successfully. Deleted 1 queries, 4 refinement steps."
}
```

#### `GET /api/v1/refinement/queries/{query_id}/progress` (200)

```json
{
	"query_id": "123",
	"stage": "generating_suggestions",
	"progress": 0.4,
	"message": "Generating refinement suggestions...",
	"started_at": "2026-02-23T10:30:00Z",
	"updated_at": "2026-02-23T10:30:08Z",
	"elapsed_seconds": 8.2,
	"turn_number": 2,
	"total_turns": 4,
	"llm_calls_made": 2
}
```

## Common error structure

Validation errors use a detailed envelope:

```json
{
	"detail": "Validation error",
	"errors": [
		{
			"field": "body -> original_query",
			"message": "Field required",
			"type": "missing"
		}
	]
}
```

Most non-validation API errors return:

```json
{
	"detail": "Human-readable error message"
}
```

## Queries and Sessions

- `POST /api/v1/queries/sessions`
- `GET /api/v1/queries/sessions`
- `GET /api/v1/queries/sessions/{session_id}`
- `POST /api/v1/queries/sessions/{session_id}/end`
- `POST /api/v1/queries`
- `GET /api/v1/queries/{query_id}`
- `PUT /api/v1/queries/{query_id}`
- `GET /api/v1/queries/sessions/{session_id}/queries`
- `POST /api/v1/queries/refinement-steps`
- `GET /api/v1/queries/{query_id}/refinement-steps`
- `POST /api/v1/queries/followups`
- `PUT /api/v1/queries/followups/{followup_id}`
- `GET /api/v1/queries/refinement-steps/{step_id}/followups`

When a query has already been synthesized, `QueryResponse` exposes the canonical synthesis fields:

- `clarified_query`
- `dimensions_specifications`
- `search_optimized`
- `search_filters`
- `terminology`
- `levels` (Agent D expansion levels)
- `metadata`
- `processing_log`

`refined_query` remains available only as a legacy convenience field.

## Feedback

- `POST /api/v1/feedback`
- `GET /api/v1/feedback/my-feedback`
- `GET /api/v1/feedback/query/{query_id}`

## Audit Logs

Audit log endpoints require a superuser account.

- `GET /api/v1/audit/logs` — paginated log list; supports filters `event_type`, `user_id`, `start_date`, `end_date`
- `GET /api/v1/audit/logs/{audit_id}` — single log entry by ID
- `GET /api/v1/audit/stats` — aggregated event counts and activity summary
- `GET /api/v1/audit/event-types` — list of all known event type strings
- `GET /api/v1/audit/trace/{request_id}` — all log entries sharing a request ID (full request trace)
- `GET /api/v1/audit/export/csv` — download log entries as CSV
- `GET /api/v1/audit/export/json` — download log entries as JSON
- `DELETE /api/v1/audit/cleanup` — delete log entries older than a configurable retention period

## Monitoring

- `GET /api/v1/monitoring/llm-health`
- `GET /api/v1/monitoring/circuit-breakers`

## Frontend Logs

- `POST /api/v1/logs/frontend`
- `GET /api/v1/logs/frontend`
- `GET /api/v1/logs/frontend/stats`
- `GET /api/v1/logs/frontend/errors`
- `GET /api/v1/logs/frontend/trace/{request_id}`

## Metadata

- `GET /api/version` (unversioned)
- `GET /health`
- `GET /ready`

## User Commands

The frontend and API accept slash commands during refinement:

- `/back`, `/prev`
- `/restart`
- `/skip` (marks current dimension skipped, no final value persisted)
- `/done` (marks current dimension complete and persists captured current value, including partial values)
- `/submit`, `/end`
- `/status`
- `/steps`
- `/help`

## Admin Endpoints

Admin endpoints require a superuser account.

- Core admin routes use: `/api/v1/admin/...`
- Additional admin route groups are exposed under: `/api/v1/api/admin/...`

Current split:

- Sessions: `/api/v1/api/admin/sessions/...`
- Frameworks: `/api/v1/api/admin/frameworks/...`
- Analytics: `/api/v1/api/admin/analytics/...`

Notable analytics endpoint:

- `GET /api/v1/api/admin/analytics/dashboard`

If you are building a new integration, prefer non-admin workflow routes under `/api/v1/refinement/*`, `/api/v1/queries/*`, and `/api/v1/webhooks/*` unless superuser-level operations are required.
