"""Tests for deterministic search-readiness checks and repair."""

from query_refinement_module.schema.search_quality import (
    assess_search,
    check_syntax,
    find_leaked_terms,
    find_redundant_blocks,
    find_ungrounded_blocks,
    repair_search,
    split_top_level,
    user_source_text,
)

# Observed on 2026-10-07: population skipped, yet Agent C restated the condition as a population block
COPD_STRUCTURED = (
    "(chronic obstructive pulmonary disease OR COPD OR chronic obstructive lung disease) AND "
    "(COPD population OR patients with chronic obstructive pulmonary disease OR COPD sufferers OR individuals with COPD) AND "
    "(exercise intervention OR exercise training OR exercis*)"
)
COPD_BLOCKS = [
    {"role": "topic_or_condition", "free_text": ["chronic obstructive pulmonary disease", "COPD", "chronic obstructive lung disease"]},
    {"role": "population_or_entity", "free_text": ["COPD population", "patients with chronic obstructive pulmonary disease", "COPD sufferers", "individuals with COPD"]},
    {"role": "intervention_or_exposure_or_phenomenon", "free_text": ["exercise intervention", "exercise training", "exercis*"]},
]
COPD_SOURCE = user_source_text("Does exercise help people with COPD?", {"population": None, "intervention": "exercise"})


def test_split_top_level_respects_parentheses():
    assert split_top_level("(a OR (b AND c)) AND d") == ["(a OR (b AND c))", "d"]


def test_check_syntax_flags_structural_problems():
    assert check_syntax("(a OR b) AND (c)") == []
    assert "unbalanced parentheses" in check_syntax("(a OR b AND c")
    assert "empty group" in check_syntax("(a) AND ()")
    assert "dangling operator" in check_syntax("(a OR) AND b")
    assert "double quotes in query" in check_syntax('("a b" OR c)')


def test_redundant_population_block_detected():
    assert find_redundant_blocks(COPD_BLOCKS) == [1]


def test_real_qualifier_is_not_redundant():
    blocks = [
        {"role": "population_or_entity", "free_text": ["older adults", "elderly adults"]},
        {"role": "topic_or_condition", "free_text": ["adults"]},
    ]
    assert find_redundant_blocks(blocks) == []


def test_ungrounded_setting_block_detected():
    # Observed: "no restriction" on population produced an invented severity/comorbidity block
    blocks = COPD_BLOCKS[:1] + [
        {"role": "setting_or_context", "free_text": ["disease severity", "GOLD stage", "FEV1", "comorbidities"]},
    ]
    source = user_source_text("Does exercise help people with COPD?", {"population": "All adults with COPD, no restriction"})
    assert find_ungrounded_blocks(blocks, source) == [1]


def test_synonym_expansion_of_user_concept_is_grounded():
    blocks = [{"role": "intervention_or_exposure_or_phenomenon", "free_text": ["mindfulness", "MBSR", "mindfulness-based stress reduction"]}]
    assert find_ungrounded_blocks(blocks, "mindfulness for anxiety in students") == []


def test_leaked_domain_terms_reported():
    graph = {"anticoagulants": {"true_synonyms": ["anticoagulant therapy"], "domain_terms": ["warfarin", "heparin"], "colloquial": ["blood thinners"]}}
    leaks = find_leaked_terms("(anticoagulant therapy OR warfarin OR blood thinners) AND (surgery)", graph)
    assert leaks == {"domain_terms": ["warfarin"], "colloquial": ["blood thinners"]}


def test_repair_drops_redundant_block_and_reports_it():
    structured, blocks, actions = repair_search(COPD_STRUCTURED, COPD_BLOCKS, source_text=COPD_SOURCE)

    assert len(blocks) == 2
    assert "COPD population" not in structured
    assert structured.startswith("(chronic obstructive pulmonary disease")
    assert actions == [{
        "action": "drop_block",
        "reason": "redundant",
        "role": "population_or_entity",
        "terms": COPD_BLOCKS[1]["free_text"],
    }]
    assert assess_search(structured, blocks, source_text=COPD_SOURCE)["search_ready"] is True


def test_repair_keeps_minimum_blocks_and_skips_misaligned_queries():
    two_blocks = COPD_BLOCKS[:2]
    two_structured = " AND ".join(split_top_level(COPD_STRUCTURED)[:2])
    assert repair_search(two_structured, two_blocks, source_text=COPD_SOURCE, min_blocks=2)[2] == []

    misaligned = "(chronic obstructive pulmonary disease OR COPD) AND (exercis*)"
    assert repair_search(misaligned, COPD_BLOCKS, source_text=COPD_SOURCE)[2] == []


def test_assess_search_counts_issues():
    report = assess_search(COPD_STRUCTURED, COPD_BLOCKS, source_text=COPD_SOURCE)
    assert report["aligned"] is True
    assert report["redundant_blocks"] == [1]
    assert report["search_ready"] is False
    assert report["issue_count"] == 1
