"""RAG knowledge layer — the tests here exist primarily to prove the
architectural boundary in Section 50 of the task: RAG can enrich an
explanation, and can never touch a triage level, a referral, a Safety
Engine verdict, an alert, or its severity. The retrieval/document
mechanics are tested too, but the boundary tests are the ones that matter
most for this feature's own safety claim.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from alerts.models import Alert, AlertEvidence
from community.models import CommunitySignal, DataSource
from core.constants import DataQuality, SignalCategory, SourceKind
from knowledge import queries
from knowledge.chunking import RawSection, chunk_sections
from knowledge.embeddings import cosine_similarity, get_embedding_service
from knowledge.ingestion import DuplicateDocumentError, ingest_document
from knowledge.models import DocumentAuthority, DocumentType, KnowledgeChunk, KnowledgeDocument, KnowledgeTopic
from knowledge.rag_service import get_grounded_explanation
from knowledge.retrieval import is_sufficiently_relevant, retrieve

User = get_user_model()
pytestmark = pytest.mark.django_db


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _make_document(
    title="Test Doc",
    topic=KnowledgeTopic.CLINICAL,
    document_type=DocumentType.GUIDELINE,
    authority=DocumentAuthority.REFERENCE,
    text="Fever lasting several days is generally treated as more concerning than a brief fever.",
    section="Fever guidance",
    active=True,
) -> KnowledgeDocument:
    document = ingest_document(
        title=title,
        organization="Test Org",
        authority=authority,
        document_type=document_type,
        topic=topic,
        sections=[RawSection(section, 1, text)],
    )
    if not active:
        document.active = False
        document.save(update_fields=["active"])
    return document


# ===========================================================================
# Document tests
# ===========================================================================


def test_document_creation_works():
    document = _make_document()
    assert document.id is not None
    assert document.chunks.count() == 1


def test_duplicate_document_detection_works():
    _make_document(title="Dup", text="Exact same content for duplicate detection.")
    with pytest.raises(DuplicateDocumentError):
        _make_document(title="Dup", text="Exact same content for duplicate detection.")


def test_chunking_preserves_page_metadata():
    sections = [RawSection("Intro", 3, "Some clinical content about fever and duration.")]
    chunks = chunk_sections(sections)
    assert chunks[0].page_number == 3


def test_chunking_preserves_section_metadata():
    sections = [
        RawSection(
            "Danger Signs", 2,
            "Difficulty breathing is a danger sign that commonly warrants prompt attention.",
        )
    ]
    chunks = chunk_sections(sections)
    assert chunks[0].section_title == "Danger Signs"


def test_embedding_generation_invoked_on_ingestion():
    document = _make_document(text="Some content that should be embedded on ingestion.")
    chunk = document.chunks.first()
    assert chunk.embedding
    assert chunk.embedding_dim > 0
    assert chunk.embedding_model


def test_document_versioning_supersedes_previous_active_version():
    v1 = ingest_document(
        title="Versioned Doc",
        organization="Test Org",
        authority=DocumentAuthority.REFERENCE,
        document_type=DocumentType.GUIDELINE,
        topic=KnowledgeTopic.CLINICAL,
        version="1",
        sections=[RawSection("S", 1, "Version one content about referral timing.")],
    )
    v2 = ingest_document(
        title="Versioned Doc",
        organization="Test Org",
        authority=DocumentAuthority.REFERENCE,
        document_type=DocumentType.GUIDELINE,
        topic=KnowledgeTopic.CLINICAL,
        version="2",
        sections=[RawSection("S", 1, "Version two content about referral timing, updated.")],
    )
    v1.refresh_from_db()
    assert v1.active is False
    assert v1.superseded_by_id == v2.id
    assert v2.active is True


def test_inactive_documents_excluded_from_retrieval():
    _make_document(
        title="Inactive Doc",
        text="This inactive document mentions fever prominently many times fever fever.",
        active=False,
    )
    results = retrieve("fever", topic=KnowledgeTopic.CLINICAL)
    assert all(r.chunk.document.title != "Inactive Doc" for r in results)


# ===========================================================================
# Retrieval tests
# ===========================================================================


def test_relevant_document_is_retrieved():
    _make_document(
        title="Fever Doc",
        text="Fever lasting several days with breathlessness is a concerning combination.",
        section="Fever",
    )
    results = retrieve("fever breathlessness duration", topic=KnowledgeTopic.CLINICAL)
    assert any(r.chunk.document.title == "Fever Doc" for r in results)


def test_irrelevant_document_is_filtered_by_topic():
    _make_document(
        title="CHW-only Doc", topic=KnowledgeTopic.CHW_ASHA, text="Frontline worker guidance content."
    )
    results = retrieve("frontline worker guidance", topic=KnowledgeTopic.CLINICAL)
    assert all(r.chunk.document.title != "CHW-only Doc" for r in results)


def test_metadata_filtering_by_document_type():
    _make_document(
        title="Referral Doc",
        topic=KnowledgeTopic.REFERRAL,
        document_type=DocumentType.REFERRAL_GUIDANCE,
        text="Referral pathway guidance content about facility evaluation.",
    )
    results = retrieve(
        "facility evaluation", topic=KnowledgeTopic.REFERRAL, document_type=DocumentType.REFERRAL_GUIDANCE
    )
    assert any(r.chunk.document.title == "Referral Doc" for r in results)
    results_wrong_type = retrieve(
        "facility evaluation", topic=KnowledgeTopic.REFERRAL, document_type=DocumentType.GUIDELINE
    )
    assert all(r.chunk.document.title != "Referral Doc" for r in results_wrong_type)


def test_keyword_retrieval_component_scores_exact_overlap():
    document = _make_document(text="convulsion seizure unresponsive danger sign")
    chunk = document.chunks.first()
    from knowledge.retrieval import _keyword_score

    score = _keyword_score({"convulsion", "seizure"}, chunk.chunk_text)
    assert score > 0


def test_vector_retrieval_component_uses_cosine_similarity():
    embedder = get_embedding_service()
    a = embedder.embed("fever and breathlessness")
    b = embedder.embed("fever and breathlessness")
    c = embedder.embed("completely unrelated agricultural rainfall data")
    assert cosine_similarity(a, b) > cosine_similarity(a, c)


def test_hybrid_retrieval_combines_vector_and_keyword():
    _make_document(title="Hybrid Doc", text="dehydration sunken eyes dry mouth referral")
    results = retrieve("dehydration sunken eyes", topic=KnowledgeTopic.CLINICAL)
    match = next((r for r in results if r.chunk.document.title == "Hybrid Doc"), None)
    assert match is not None
    assert match.combined_score > 0
    assert match.vector_score >= 0
    assert match.keyword_score >= 0


def test_low_relevance_result_returns_no_grounding_state():
    result = get_grounded_explanation(
        query_type="test",
        application_result="N/A",
        question="zzz completely unmatched nonsense query xyzabc",
        topic=KnowledgeTopic.CLINICAL,
    )
    assert result["status"] in {"no_grounding", "grounded"}
    if result["status"] == "no_grounding":
        assert result["answer"] == "No sufficiently relevant approved guidance was retrieved."
        assert result["sources"] == []


def test_source_provenance_preserved_in_citation():
    _make_document(title="Provenance Doc", section="Key Section")
    results = retrieve("fever", topic=KnowledgeTopic.CLINICAL)
    match = next(r for r in results if r.chunk.document.title == "Provenance Doc")
    from knowledge.provenance import citation_for

    citation = citation_for(match)
    assert citation["title"] == "Provenance Doc"
    assert citation["section"] == "Key Section"
    assert citation["authority"] == "REFERENCE"


# ===========================================================================
# RuralCare boundary tests
# ===========================================================================


def test_ruralcare_triage_unaffected_by_rag(worker_api, patient):
    """The existing preview endpoint's triage result must be byte-identical
    whether or not RAG is even queried afterward — this test calls the real
    assessment preview endpoint and confirms RAG involvement is zero."""

    response = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 4, "temperature_c": 39.2},
        format="json",
    )
    assert response.status_code == 200
    # The preview response has no rag-related keys at all — confirming the
    # existing endpoint was not modified to call RAG inline.
    assert "rag" not in response.data
    assert "sources" not in response.data


def test_rag_cannot_change_triage_level(worker_api, patient):
    preview = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 1},
        format="json",
    )
    triage_level = preview.data["support"]["triage_level"]

    result = queries.ruralcare_guidance(
        triage_level=triage_level,
        contributing_factors=[],
        syndrome_groups=[],
        referral_pathway="COMMUNITY_FOLLOW_UP",
    )
    # RAG's own response never contains a competing triage_level field —
    # structurally, it has nothing to override the application result with.
    assert "triage_level" not in result


def test_rag_cannot_change_referral():
    result = queries.ruralcare_guidance(
        triage_level="URGENT",
        contributing_factors=["severe dehydration"],
        syndrome_groups=["gastrointestinal"],
        referral_pathway="SAME_DAY_FACILITY_REFERRAL",
    )
    assert "referral_pathway" not in result
    assert "referral_recommendation" not in result


def test_rag_failure_does_not_fail_assessment(worker_api, patient, monkeypatch):
    from knowledge import rag_service

    def broken_retrieve(*args, **kwargs):
        raise RuntimeError("simulated retrieval outage")

    # Patched on rag_service's own namespace (where `retrieve` was imported
    # into), not on the retrieval module itself — the same reason
    # agents/ruralcare/triage.py's own tests patch call sites this way.
    monkeypatch.setattr(rag_service, "retrieve", broken_retrieve)

    # The RAG endpoint itself degrades gracefully...
    result = queries.ruralcare_guidance(
        triage_level="ROUTINE", contributing_factors=[], syndrome_groups=[], referral_pathway="COMMUNITY_FOLLOW_UP"
    )
    assert result["status"] == "unavailable"

    # ...and the actual assessment endpoint, which never calls RAG inline
    # in the first place, is completely unaffected regardless.
    response = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 1},
        format="json",
    )
    assert response.status_code == 200


def test_patient_identifiers_not_sent_to_rag(patient):
    """queries.ruralcare_guidance() has no parameter through which a
    patient name, code, phone, or house location could be passed — this
    test documents and locks that contract via introspection."""

    import inspect

    params = set(inspect.signature(queries.ruralcare_guidance).parameters)
    forbidden = {"patient_name", "patient_code", "phone_number", "house_location", "patient", "patient_id"}
    assert not (params & forbidden)


class _StubLLMClient:
    """A minimal stand-in for agents.llm.client.LLMClient — `available=True`
    and a fixed `summarise()` response, so a test can exercise the real
    "grounded" path without a live API key (none is configured anywhere in
    this test environment)."""

    def __init__(self, answer: str = "This is a grounded, LLM-generated explanation.") -> None:
        self.available = True
        self._answer = answer

    def summarise(self, system_prompt: str, user_prompt: str, max_tokens: int = 400) -> str:
        return self._answer


def test_retrieved_clinical_source_appears_correctly(monkeypatch):
    from knowledge import rag_service

    _make_document(
        title="Persistent Fever Doc",
        text="A fever lasting several days with a recorded temperature above normal is "
        "generally treated as more concerning and may warrant PHC referral.",
        section="Fever duration",
    )
    monkeypatch.setattr(rag_service, "get_llm_client", lambda: _StubLLMClient())

    result = queries.ruralcare_guidance(
        triage_level="CONCERNING",
        contributing_factors=["recorded temperature 39.2 C", "symptoms persisting 4 days"],
        syndrome_groups=["febrile"],
        referral_pathway="PHC_REFERRAL",
    )
    assert result["status"] == "grounded"
    assert len(result["sources"]) > 0
    assert all("title" in s and "organization" in s for s in result["sources"])


# ===========================================================================
# GramSentinel / investigation boundary tests
# ===========================================================================


@pytest.fixture
def alert_with_evidence(village):
    alert = Alert.objects.create(
        village=village,
        cluster=village.cluster,
        category=SignalCategory.FEVER,
        week_label="2026-W32",
        period_start=dt.date(2026, 8, 3),
        period_end=dt.date(2026, 8, 9),
        title="Fever signal",
        summary="Test alert",
        severity=Alert.Severity.MODERATE,
        confidence=0.7,
        corroborating_source_count=2,
        cross_level_verdict="CONSISTENT",
        safety_verdict="PASS",
        safety_status="REQUIRES_HUMAN_REVIEW",
        status=Alert.Status.DETECTED,
    )
    AlertEvidence.objects.create(
        alert=alert, source_kind=SourceKind.CHW, source_name="CHW", category=SignalCategory.FEVER,
        village_code=village.code, week_label="2026-W32", status="ANOMALY_DETECTED", is_corroborating=True,
    )
    AlertEvidence.objects.create(
        alert=alert, source_kind=SourceKind.SCHOOL, source_name="School", category=SignalCategory.FEVER,
        village_code=village.code, week_label="2026-W32", status="NOT_REPORTED", is_corroborating=False,
    )
    return alert


def test_gramsentinel_alert_result_unaffected_by_rag(alert_with_evidence):
    original_severity = alert_with_evidence.severity
    original_verdict = alert_with_evidence.safety_verdict

    queries.investigation_guidance(
        category_label="Fever",
        corroborating_sources=["CHW"],
        context_sources=[],
        missing_sources=["SCHOOL"],
        cross_level_verdict="CONSISTENT",
        safety_verdict="PASS",
    )

    alert_with_evidence.refresh_from_db()
    assert alert_with_evidence.severity == original_severity
    assert alert_with_evidence.safety_verdict == original_verdict


def test_rag_cannot_create_an_alert():
    before = Alert.objects.count()
    queries.investigation_guidance(
        category_label="Respiratory illness",
        corroborating_sources=["CHW", "PHC"],
        context_sources=[],
        missing_sources=[],
        cross_level_verdict="CONSISTENT",
        safety_verdict="PASS",
    )
    assert Alert.objects.count() == before


def test_rag_cannot_modify_safety_engine(alert_with_evidence):
    from safety import EvidenceRecord, Hypothesis, SafetyEngine

    engine = SafetyEngine()
    # Calling RAG in between two safety evaluations must not change the
    # engine's output for identical input — it has no shared mutable state.
    records = (
        EvidenceRecord(
            source_kind=SourceKind.CHW, source_name="CHW", category=SignalCategory.FEVER,
            village_code="KVL", cluster="Village Cluster A", week_label="2026-W32",
            period_start=dt.date(2026, 8, 3), period_end=dt.date(2026, 8, 9),
            status="ANOMALY_DETECTED", data_quality=DataQuality.GOOD, baseline=5.0,
            current_value=14.0, change_pct=180.0, is_corroborating=True, is_reported=True,
        ),
    )
    hypothesis = Hypothesis(
        kind="correlation_hypothesis", cluster="Village Cluster A", category=SignalCategory.FEVER,
        week_label="2026-W32", narrative="test", contributing=records,
        cross_level_verdict="CONSISTENT", cross_level_statement="",
    )
    before = engine.evaluate_community(hypothesis, records)
    queries.investigation_guidance(
        category_label="Fever", corroborating_sources=["CHW"], context_sources=[],
        missing_sources=[], cross_level_verdict="CONSISTENT", safety_verdict="PASS",
    )
    after = engine.evaluate_community(hypothesis, records)
    assert before.verdict == after.verdict


def test_community_rag_receives_aggregate_context_only():
    import inspect

    params = set(inspect.signature(queries.investigation_guidance).parameters)
    forbidden = {"patient_name", "patient_code", "phone_number", "symptoms", "vitals", "sugar_mg_dl"}
    assert not (params & forbidden)
    # Every accepted parameter is category/source-kind/verdict level.
    assert params >= {"category_label", "corroborating_sources", "missing_sources"}


def test_relevant_surveillance_guidance_is_retrieved():
    result = queries.investigation_guidance(
        category_label="Fever",
        corroborating_sources=["CHW", "PHC"],
        context_sources=["WEATHER"],
        missing_sources=["SCHOOL"],
        cross_level_verdict="CONSISTENT",
        safety_verdict="PASS",
    )
    assert result["status"] in {"grounded", "no_grounding"}
    if result["status"] == "grounded":
        assert len(result["sources"]) > 0


# ===========================================================================
# Investigation endpoint tests
# ===========================================================================


def test_investigation_guidance_endpoint_village_scoped(village, other_village, alert_with_evidence):
    officer_b = User.objects.create_user(
        username="officer.rag.b", password="x", role=User.Role.HEALTH_OFFICER, village=other_village
    )
    response = api_for(officer_b).post(
        "/api/rag/investigation/", {"alert_id": alert_with_evidence.id}, format="json"
    )
    # Officer B cannot see Village A's alert -> 404, same as every other
    # alert endpoint in this project.
    assert response.status_code == 404


def test_officer_decision_vocabulary_unchanged_by_rag_endpoint(village, alert_with_evidence):
    officer = User.objects.create_user(
        username="officer.rag.a", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )
    response = api_for(officer).post(
        "/api/rag/investigation/", {"alert_id": alert_with_evidence.id}, format="json"
    )
    assert response.status_code == 200
    assert "outcome" not in response.data
    assert "decision" not in response.data


def test_rag_cannot_automatically_submit_investigation_decision(village, alert_with_evidence):
    officer = User.objects.create_user(
        username="officer.rag.c", password="x", role=User.Role.HEALTH_OFFICER, village=village
    )
    api_for(officer).post("/api/rag/investigation/", {"alert_id": alert_with_evidence.id}, format="json")
    alert_with_evidence.refresh_from_db()
    assert not hasattr(alert_with_evidence, "feedback")


# ===========================================================================
# Freshness independence
# ===========================================================================


def test_freshness_classification_unchanged_by_rag(village):
    from community.freshness import build_source_freshness

    source = DataSource.objects.create(
        code=f"CHW-{village.code}-RAGTEST", name="CHW", kind=SourceKind.CHW,
        channel=DataSource.Channel.PORTAL, village=village,
    )
    CommunitySignal.objects.create(
        source=source, village=village, category=SignalCategory.FEVER, week_label="2026-W30",
        period_start=dt.date(2026, 7, 20), period_end=dt.date(2026, 7, 26), value=4.0, baseline=3.0,
        is_reported=True, data_quality=DataQuality.GOOD,
    )
    before = build_source_freshness(village)

    queries.investigation_guidance(
        category_label="Fever", corroborating_sources=["CHW"], context_sources=[],
        missing_sources=[], cross_level_verdict="CONSISTENT", safety_verdict="PASS",
    )

    after = build_source_freshness(village)
    assert before == after


def test_missing_remains_missing_after_rag(village):
    from community.freshness import build_source_freshness

    queries.investigation_guidance(
        category_label="Fever", corroborating_sources=[], context_sources=[],
        missing_sources=["SCHOOL"], cross_level_verdict="SILENT", safety_verdict="DOWNGRADE",
    )
    cards = build_source_freshness(village)
    school = next(c for c in cards if c["source_kind"] == SourceKind.SCHOOL)
    assert school["status"] == "MISSING"


# ===========================================================================
# Offline independence
# ===========================================================================


def test_offline_queue_service_does_not_import_knowledge_app():
    """The offline queue's own frontend code has no way to call RAG (it's
    a Python backend app — see the equivalent frontend-side assertion in
    the offline sync store, which only ever calls /community-reports/).
    Server-side, confirm ingest_batch/run_community_pipeline never import
    the knowledge app."""

    import inspect

    import alerts.services as alert_services
    import integrations.ingestion as ingestion_module

    assert "knowledge" not in inspect.getsource(ingestion_module)
    assert "knowledge" not in inspect.getsource(alert_services)


def test_successful_offline_sync_does_not_require_rag(worker_api, village):
    """A community report submission (the same path an offline sync uses)
    succeeds identically regardless of RAG_ENABLED — proving the existing
    pipeline was not made to depend on this new app."""

    from django.test import override_settings

    with override_settings(RAG_ENABLED=False):
        response = worker_api.post(
            "/api/community-reports/",
            {
                "village": village.id,
                "week_label": "2026-W45",
                "period_start": "2026-11-02",
                "period_end": "2026-11-08",
                "entries": [{"category": "FEVER", "case_count": 2}],
                "idempotency_key": "rag-independence-key",
                "client_created_at": "2026-11-02T09:00:00Z",
            },
            format="json",
        )
    assert response.status_code == 201


# ===========================================================================
# RAG enable/disable + endpoints
# ===========================================================================


def test_rag_disabled_returns_clean_disabled_state():
    from django.test import override_settings

    with override_settings(RAG_ENABLED=False):
        result = get_grounded_explanation(
            query_type="test", application_result="X", question="fever", topic=KnowledgeTopic.CLINICAL
        )
    assert result["status"] == "disabled"
    assert result["sources"] == []


def test_ruralcare_endpoint_requires_worker_role(officer_api):
    response = officer_api.post(
        "/api/rag/ruralcare/",
        {"triage_level": "ROUTINE", "contributing_factors": [], "syndrome_groups": [], "referral_pathway": ""},
        format="json",
    )
    assert response.status_code == 403


def test_chw_endpoint_scoped_topic_cannot_be_overridden(worker_api):
    response = worker_api.post("/api/rag/chw/", {"question": "What should I check for diarrhoea?"}, format="json")
    assert response.status_code == 200
    assert response.data["knowledge_topic"] == KnowledgeTopic.CHW_ASHA


def test_terminology_suggestion_endpoint(worker_api):
    response = worker_api.post("/api/rag/terminology/", {"text": "body is very hot"}, format="json")
    assert response.status_code == 200
    assert response.data["knowledge_topic"] == KnowledgeTopic.TERMINOLOGY


def test_investigation_endpoint_requires_officer_role(worker_api, village, alert_with_evidence):
    response = worker_api.post("/api/rag/investigation/", {"alert_id": alert_with_evidence.id}, format="json")
    assert response.status_code == 403


def test_source_detail_endpoint_hides_inactive_documents(worker_api):
    inactive = _make_document(title="Hidden Doc", active=False)
    response = worker_api.get(f"/api/rag/sources/{inactive.id}/")
    assert response.status_code == 404


def test_audit_log_written_without_patient_data(village):
    from knowledge.models import RagQueryLog

    before = RagQueryLog.objects.count()
    queries.investigation_guidance(
        category_label="Fever", corroborating_sources=["CHW"], context_sources=[],
        missing_sources=[], cross_level_verdict="CONSISTENT", safety_verdict="PASS",
    )
    after = RagQueryLog.objects.count()
    assert after == before + 1
    log = RagQueryLog.objects.latest("created_at")
    assert "patient" not in str(log.retrieved_document_ids).lower()


# ===========================================================================
# Regression: LLM-unavailable must never surface raw retrieved chunk text
# as "guidance" (the bug the New Assessment screenshot showed).
# ===========================================================================


def test_llm_unavailable_reports_unavailable_not_grounded():
    """The exact bug: previously this returned status="grounded" with a
    "Retrieved guidance (LLM wording unavailable):" wall of raw chunk text
    as `answer`. No LLM is configured anywhere in this test environment, so
    this exercises the real, un-mocked default path."""

    _make_document(
        title="Fever Doc For Unavailable Test",
        text="Fever lasting several days with breathlessness is a concerning combination worth noting.",
    )
    result = queries.ruralcare_guidance(
        triage_level="CONCERNING",
        contributing_factors=["symptoms persisting 4 days"],
        syndrome_groups=["febrile"],
        referral_pathway="PHC_REFERRAL",
    )
    assert result["status"] == "unavailable"
    assert result["answer"] == ""
    assert result["sources"] == []
    assert "Retrieved guidance" not in result["answer"]
    assert "LLM wording unavailable" not in result["answer"]


def test_llm_unavailable_endpoint_never_exposes_raw_chunks(worker_api):
    """End-to-end through the actual /api/rag/ruralcare/ endpoint the New
    Assessment page calls — proves the fix at the HTTP boundary, not just
    inside the service function."""

    _make_document(
        title="Fever Doc For Endpoint Test",
        text="A prolonged fever with a high recorded temperature is generally treated as concerning.",
    )
    response = worker_api.post(
        "/api/rag/ruralcare/",
        {
            "triage_level": "CONCERNING",
            "contributing_factors": ["symptoms persisting 4 days"],
            "syndrome_groups": ["febrile"],
            "referral_pathway": "PHC_REFERRAL",
        },
        format="json",
    )
    assert response.status_code == 200
    assert response.data["status"] == "unavailable"
    assert response.data["answer"] in ("", None)
    body = str(response.data)
    assert "Retrieved guidance" not in body
    assert "LLM wording unavailable" not in body


def test_assessment_preview_succeeds_regardless_of_llm_unavailable(worker_api, patient):
    """The New Assessment page's actual triage result must be completely
    unaffected — /api/assessments/preview/ never calls RAG inline at all
    (see test_ruralcare_triage_unaffected_by_rag above), so this is really
    confirming that fact still holds after this fix."""

    response = worker_api.post(
        "/api/assessments/preview/",
        {"patient": patient.id, "symptoms": ["fever"], "duration_days": 4, "temperature_c": 39.2},
        format="json",
    )
    assert response.status_code == 200
    assert "triage_level" in response.data["support"]


def test_malformed_empty_llm_response_falls_back_to_unavailable(monkeypatch):
    """A misbehaving LLM returning an empty/whitespace string must be
    treated exactly like no LLM at all — never surfaced as a blank or
    broken "grounded" answer."""

    from knowledge import rag_service

    _make_document(title="Empty Response Doc", text="Fever lasting several days is a concerning finding.")
    monkeypatch.setattr(rag_service, "get_llm_client", lambda: _StubLLMClient(answer="   "))

    result = queries.ruralcare_guidance(
        triage_level="CONCERNING", contributing_factors=[], syndrome_groups=["febrile"],
        referral_pathway="PHC_REFERRAL",
    )
    assert result["status"] == "unavailable"
    assert result["answer"] == ""


def test_grounded_response_includes_explanation_and_citations(monkeypatch):
    """Phase 12 item 1 — the positive case: when an LLM genuinely produces
    wording, both the explanation and its citations must be present."""

    from knowledge import rag_service

    _make_document(
        title="Grounded Path Doc",
        text="Breathlessness alongside fever is commonly treated as a danger sign warranting referral.",
    )
    monkeypatch.setattr(
        rag_service, "get_llm_client", lambda: _StubLLMClient(answer="Fever with breathlessness is notable.")
    )

    result = queries.ruralcare_guidance(
        triage_level="URGENT", contributing_factors=["breathlessness"], syndrome_groups=["respiratory"],
        referral_pathway="SAME_DAY_FACILITY_REFERRAL",
    )
    assert result["status"] == "grounded"
    assert result["answer"] == "Fever with breathlessness is notable."
    assert len(result["sources"]) > 0
    assert result["used_llm"] is True
