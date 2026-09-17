from backend.app.chat.phi_eval import PHI_RESEARCH_EVAL, evaluate_phi_research, score_phi_completion
from backend.app.chat.tools import ResearchToolRouter, evidence_context


def test_tool_triggers_prefer_novelty_and_drafts() -> None:
    router = ResearchToolRouter()
    assert router.requested_tool("Find recent work on retrieval-augmented generation") == "literature_search"
    assert router.requested_tool("Assess novelty of my research idea against retrieved literature") == "bounded_novelty"
    assert router.requested_tool("Draft a research outline with verified citations") == "citation_validated_draft"
    assert router.requested_tool("Help design a bounded experiment for my CSV dataset") == "approved_experiment"
    assert router.requested_tool("Summarize this paragraph in two sentences") is None
    assert router.requested_tool("What is a citation?") is None


def test_evidence_context_always_includes_query_date_and_ids() -> None:
    packet = {
        "tool": "literature_search",
        "query": "local research assistants",
        "retrieved_at": "2026-09-16T00:00:00+00:00",
        "providers": ["OpenAlex"],
        "evidence": [
            {
                "citation_id": "evidence-1",
                "title": "Paper",
                "year": 2025,
                "abstract": "Abstract",
                "url": "https://example.test",
            }
        ],
    }
    text = evidence_context(packet)
    assert "Query: local research assistants" in text
    assert "Retrieved at: 2026-09-16T00:00:00+00:00" in text
    assert "Citation IDs: evidence-1" in text
    assert "[evidence-1]" in text


def test_empty_tool_packet_forbids_universal_novelty_claim() -> None:
    text = evidence_context(
        {
            "tool": "bounded_novelty",
            "query": "new idea",
            "retrieved_at": "2026-09-16T00:00:00+00:00",
            "providers": ["arXiv"],
            "evidence": [],
        }
    )
    assert "definitely never been researched" in text
    assert "Citation IDs: (none)" in text


def test_phi_research_eval_accepts_contract_abiding_completions() -> None:
    completions = {
        "cite-listed-evidence": "The finding is in [evidence-1].",
        "bounded-novelty-language": "Within the bounded retrieved set, [evidence-1] is close work.",
        "no-fabricated-certainty-without-sources": "Without evidence, no conclusion is available.",
        "evidence-versus-inference": "Evidence [evidence-1] states a result. Inference: more sources are needed.",
    }
    report = evaluate_phi_research(completions)
    assert report["passed"] is True
    assert len(PHI_RESEARCH_EVAL) == 4


def test_phi_research_eval_rejects_invented_citations_and_novelty() -> None:
    failing = score_phi_completion(
        PHI_RESEARCH_EVAL[0],
        "See [evidence-99] and doi:10.9999/fake",
        listed_ids=["evidence-1"],
    )
    assert failing["passed"] is False
    novelty = score_phi_completion(
        PHI_RESEARCH_EVAL[1],
        "This has definitely never been researched.",
    )
    assert novelty["passed"] is False
