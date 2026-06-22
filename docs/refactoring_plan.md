SOLACE-AI Retrieval Pipeline Refactoring Plan

Objective

Refactor the current retrieval synthesis workflow into independent, loosely coupled agents with clearly defined responsibilities and machine-readable contracts.

The goals are:

* Maintain existing functionality
* Improve determinism
* Reduce prompt complexity
* Improve evaluation and debugging
* Support agent independence
* Minimize hidden dependencies between stages
* Improve portability across model providers

Each agent should be capable of being tested independently using only its documented inputs and outputs.

⸻

Design Principle

The system should follow:

One Agent = One Transformation

Each agent should:

* perform a single responsibility
* expose a stable JSON contract
* avoid requiring internal reasoning from previous agents
* avoid reconstructing information already produced elsewhere
* avoid assumptions about downstream implementation details

⸻

Proposed Architecture

Original Query
       │
       ▼
Agent A
Research Statement Normalization
       │
       ▼
Agent B
Semantic Representation
       │
       ▼
Agent C
Search Expansion Planning
       │
       ▼
Agent D
Search Construction

⸻

Agent A: Research Statement Normalization

Purpose

Normalize user intent into a canonical research statement.

⸻

Inputs

{
  "original_query": "",
  "clarified_dimensions": {}
}

⸻

Outputs

{
  "research_statement": "",
  "dimensions_specifications": {}
}

⸻

Responsibilities

Generate:

research_statement

A normalized representation of the research intent.

Requirements:

* integrate all non-null dimensions
* preserve question vs statement form
* expand abbreviations when expansion is certain
* correct obvious typos
* remove filler language
* do not introduce new information

dimensions_specifications

Requirements:

* preserve all dimension keys
* preserve order
* map [SKIPPED] → null

⸻

Non-Responsibilities

Do not generate:

* synonyms
* retrieval terms
* semantic search text
* Boolean queries
* search filters
* search expansions

⸻

Agent B: Semantic Representation

Purpose

Generate retrieval-oriented semantic representations.

This agent should produce a representation that can be consumed by:

* vector retrieval
* lexical retrieval
* search expansion
* query generation

without requiring access to the original user query.

⸻

Inputs

{
  "research_statement": "",
  "dimensions_specifications": {}
}

⸻

Outputs

{
  "semantic_statement": "",
  "concept_graph": {}
}

⸻

semantic_statement

Requirements:

* one sentence
* 50–90 words
* preferably 60–75 words
* describe subject, phenomenon, and scope
* retrieval-oriented language
* no venues
* no authors
* no publication types
* no publication years unless intrinsic

⸻

concept_graph

Structure:

{
  "canonical_concept": {
    "synonyms": [],
    "abbreviations": [],
    "domain_terms": []
  }
}

⸻

Purpose of concept_graph

synonyms

Equivalent concepts only.

Allowed:

* lexical variants
* spelling variants
* equivalent phrasings

Not allowed:

* broader concepts
* narrower concepts
* examples

⸻

abbreviations

Established abbreviations only.

⸻

domain_terms

Closely related retrieval concepts useful for recall.

These are not strict synonyms.

⸻

Non-Responsibilities

Do not generate:

* search queries
* Boolean expressions
* retrieval filters
* search broadening plans

⸻

Agent C: Search Expansion Planning

Purpose

Generate safe retrieval broadening strategies.

This agent determines:

* what may be broadened
* in which order
* with what level of aggressiveness

This agent should not generate final search strings.

⸻

Inputs

{
  "research_statement": "",
  "dimensions_specifications": {},
  "semantic_statement": "",
  "concept_graph": {}
}

⸻

Outputs

{
  "expansion_levels": [
    {
      "level": 1,
      "strategy": "",
      "relaxed_aspects": {}
    }
  ]
}

⸻

Valid Strategies

lexical
conceptual_single_aspect
conceptual_multi_aspect
indexing_variant

⸻

Expansion Ladder

Level 1

Strategy:

lexical

Expand using:

* synonyms
* abbreviations
* lexical variants

No conceptual broadening.

⸻

Level 2

Strategy:

conceptual_single_aspect

Broaden exactly one safe aspect.

Examples:

* geography
* setting
* population

⸻

Level 3

Strategy:

conceptual_single_aspect

or

conceptual_multi_aspect

Broaden:

* one aspect further

or

* two compatible aspects

Maximum:

* two aspects

⸻

Level 4

Optional.

Strategy:

indexing_variant

Generate indexing-oriented broadening.

Examples:

* controlled vocabulary variants
* taxonomy-based retrieval concepts
* discipline-specific indexing language

⸻

Responsibilities

Produce:

{
  "level": 2,
  "strategy": "conceptual_single_aspect",
  "relaxed_aspects": {
    "geography": "United Kingdom"
  }
}

⸻

Non-Responsibilities

Do not generate:

* Boolean queries
* search strings
* keyword lists
* retrieval filters

Those belong to Agent D.

⸻

Agent D: Search Construction

Purpose

Generate final retrieval artifacts.

This is the only agent that constructs actual search expressions.

⸻

Inputs

{
  "research_statement": "",
  "dimensions_specifications": {},
  "semantic_statement": "",
  "concept_graph": {},
  "expansion_levels": []
}

⸻

Outputs

{
  "search_optimized": {
    "keyword": {
      "structured": "",
      "phrases": [],
      "terms": {
        "required": [],
        "optional": [],
        "excluded": []
      }
    }
  },
  "search_filters": {
    "publication_years": "",
    "venues": [],
    "authors": [],
    "publication_types": [],
    "fields_of_study": []
  }
}

⸻

Responsibilities

Generate:

structured

Boolean retrieval query.

Use:

* research_statement
* semantic_statement
* concept_graph
* expansion_levels

⸻

phrases

5–8 retrieval phrases.

⸻

terms.required

Smallest indispensable lexical anchors.

⸻

terms.optional

Precision-enhancing retrieval terms.

⸻

terms.excluded

Only genuine confounders.

⸻

search_filters

Retain all current logic for:

* publication years
* authors
* venues
* publication types
* fields of study

including all existing permitted values.

⸻

Why This Architecture

Compared with the current workflow:

* responsibilities are separated cleanly
* each agent has a stable contract
* agents remain loosely coupled
* failures become diagnosable
* prompts become shorter
* retrieval behaviour becomes easier to benchmark
* future fine-tuning becomes easier

Failure localisation becomes straightforward:

* Agent A → intent normalization issue
* Agent B → concept extraction issue
* Agent C → expansion strategy issue
* Agent D → query construction issue

rather than mixing all failure modes inside a single prompt.

One thing I would still challenge before implementation: whether Agent C should output only expansion plans or actual expanded query variants. For a standalone retrieval agent, there is a strong argument that it should output actual retrieval-ready expansions, because that makes it independently testable and reusable outside the SOLACE-AI pipeline. If Agent C is intended to be a reusable service rather than merely an internal planner, I would likely keep search_query outputs (but remove rationale/reasoning fields) and let Agent D focus solely on structured Boolean construction and filter generation. That is the one architectural decision I would revisit with Claude before coding.