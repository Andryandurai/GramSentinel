# GramSentinel — RAG Knowledge Layer Architecture

**What this document is:** a technical description of the Retrieval-Augmented Generation (RAG) layer added in `backend/knowledge/`. It is a side-car to the existing deterministic system, not a replacement for any part of it. Read this alongside `ALLDETAILS.md` and `DATA_PROVENANCE_AUDIT.md`, which describe the rest of the platform this layer sits next to.

---

## 1. Why RAG was added

RuralCare and GramSentinel's deterministic agents produce a result — a triage level, a referral pathway, a community signal, a safety verdict — but that result on its own doesn't tell a worker or officer *why* it matters, or what established practice says about handling it. RAG retrieves curated, cited reference material and asks a language model to explain the connection between the retrieved text and the already-computed result. It exists to make explanations more grounded and traceable, not to make the platform's decisions.

## 2. What RAG does

- Retrieves relevant chunks from a curated, version-controlled knowledge base, filtered by topic/document type and scored by a hybrid of vector similarity and keyword overlap.
- Asks an LLM (the same one already used elsewhere in this project) to explain, in grounded language, how the retrieved material relates to a result the deterministic system already produced.
- Returns every citation's source document, organization, authority level, section, page, and version — never inventing any of these when the source document doesn't have them.
- Degrades gracefully: no relevant documents, no LLM, or a retrieval failure all return a clean "nothing to show" state rather than breaking the caller.

## 3. What RAG does NOT do

- It does not calculate a triage score, triage level, or referral pathway. Those are computed entirely by `agents/ruralcare/` before RAG is ever called, and RAG's response has no field that could overwrite them.
- It does not determine a community alert's severity, or create an `Alert`. Alert creation happens entirely inside `alerts/services.py::run_community_pipeline()`, which never imports `knowledge`.
- It does not modify the deterministic Safety Engine (`safety/engine.py`) in either direction — confirmed by `tests/test_knowledge_rag.py::test_rag_cannot_modify_safety_engine`.
- It does not determine Source Freshness (`FRESH`/`AGING`/`STALE`/`MISSING`) — that remains entirely `community/freshness.py`'s own computation from `CommunitySignal.ingested_at`.
- It does not diagnose a patient or name a disease, and does not declare or imply an outbreak — enforced both by the system prompt (`knowledge/prompts.py::GROUNDING_SYSTEM_PROMPT`) and, for the operational community pipeline, by the pre-existing, unrelated Safety Engine Rule 6.
- It does not run on the offline device — see Section 12.
- It is not connected to any live medical or surveillance data source. See Section 5.

## 4. Architecture

```
                    APPLICATION DATA
                           |
                           v
                EXISTING DETERMINISTIC
                     AGENT LOGIC
                           |
                           v
                   APPLICATION RESULT
                           |
                ┌──────────┴──────────┐
                |                     |
                v                     v
          EXISTING SAFETY          RAG
             ENGINE                 |
                |                    v
                |             knowledge/retrieval.py
                |          (metadata filter + vector +
                |           keyword + rerank + top-k)
                |                    |
                |                    v
                |             Retrieved Chunks
                |                    |
                |                    v
                |          agents.llm.get_llm_client()
                |          (the SAME LLM client already
                |           used elsewhere in this project)
                |                    |
                └──────────┬─────────┘
                           v
                     HUMAN USER
                           |
                           v
                   HUMAN DECISION
```

Document flow, separate from the runtime path above (Section 27 of the implementation task — ingestion is offline/maintenance, never triggered by a user request):

```
Curated document (knowledge/seed_content.py)
        |
        v
knowledge/chunking.py   -- section-aware chunking, page/section preserved
        |
        v
knowledge/embeddings.py -- EmbeddingService.embed() per chunk
        |
        v
KnowledgeDocument + KnowledgeChunk rows (knowledge/ingestion.py::ingest_document)
        |
        v
python manage.py ingest_knowledge   (idempotent — duplicate content is skipped)
```

## 5. Knowledge sources — exactly what was actually ingested

**No `OFFICIAL`-authority document is ingested in this project.** Every document in `knowledge/seed_content.py` is one of:

- **`INTERNAL`** (3 documents) — this project's own documented rules (missing-data policy, alert lifecycle, the RuralCare→GramSentinel privacy boundary), written by the project team and verified accurate against the actual code they describe.
- **`REFERENCE`** (9 documents) — general, widely-known public-health/frontline-care reference material, written in plain language by the project team, explicitly attributed as `"GramSentinel Project Team — general reference (not verbatim official text)"`, never presented as WHO/MoHFW/NHM's own words.

This is a deliberate, honest choice: ingesting a real `OFFICIAL` document (an actual WHO fact sheet, an IMNCI/RBSK/NVBDCP guideline PDF, etc.) requires a verified, licensed source file this sandboxed environment has no way to fetch or authenticate. The `DocumentAuthority.OFFICIAL` level exists in the schema and is enforced everywhere a citation is shown (`authority_label` is always displayed alongside a source) — it is simply not used by anything ingested in this session. **Ingesting real, verified official guidance documents is the direct next step for a production deployment**, not simulated here by mislabeling reference content.

Full list (title / organization / authority / topic): see `backend/knowledge/seed_content.py::DOCUMENTS` — 12 documents, ~26 chunks, spanning all 8 `KnowledgeTopic` values.

## 6. Document ingestion

`knowledge/ingestion.py::ingest_document()` — validates by computing a SHA-256 checksum of the document's full raw text; an exact-content duplicate raises `DuplicateDocumentError` rather than re-ingesting. A same-title/organization/topic document with *different* content is treated as a new version: the previous version is marked `active=False` and linked via `superseded_by`, never deleted — so a chunk cited in the past remains traceable to the exact version it came from, while only active documents are ever retrieved going forward.

Ingestion only ever happens via `python manage.py ingest_knowledge` (or `rebuild_embeddings` after an embedding-provider change) — never at request time.

## 7. Chunking

`knowledge/chunking.py` — chunks never cross a section boundary. A document is supplied (in `seed_content.py`) as a list of `(section_title, page_number, text)` tuples; each becomes one chunk unless it exceeds 800 characters, in which case it is split on sentence boundaries (never mid-sentence) and re-packed into <=800-character pieces. `sections_from_plain_text()` exists as a fallback for an arbitrary plain-text upload with no known section structure — not used by any currently-seeded document, since every seeded document supplies real section/page structure.

## 8. Embeddings

`knowledge/embeddings.py::EmbeddingService` — pluggable, same graceful-degradation contract as `agents/llm/client.py`:

- **`local`** (default, and the only provider exercised by this project's tests and seed data): a deterministic hashed bag-of-words/bigram vectoriser (the "hashing trick" — the same technique behind Vowpal Wabbit and scikit-learn's `HashingVectorizer`), fixed dimension (`RAG_LOCAL_EMBEDDING_DIM`, default 256), L2-normalised. No network call, no API key, no ML library dependency. The same text always produces the same vector; texts sharing more words point in a more similar direction. This is honestly a lexical-overlap-aware vectoriser, not a trained semantic embedding model — sufficient for a small, curated knowledge base's retrieval to be meaningfully better than random, not a claim of state-of-the-art semantic search.
- **`openai`**: a real external embeddings API call (plain `requests`, no SDK — matching `agents/llm/client.py`'s own approach), active only when `RAG_EMBEDDING_PROVIDER=openai` and `RAG_EMBEDDING_API_KEY` is set. **Not exercised in this environment** — no such key is configured here. Included so a real deployment has a working, documented upgrade path to genuine semantic embeddings without changing any caller of this module (`retrieval.py` only ever calls `embedder.embed(text)`, regardless of provider).

## 9. Vector database

**No `pgvector` column is used.** `KnowledgeChunk.embedding` is a plain Django `JSONField` (a list of floats) — this works identically on SQLite (this project's local/dev/test database) and PostgreSQL (production), since it isn't a Postgres-specific column type.

This was a deliberate choice, not an oversight: `pgvector` requires a PostgreSQL extension that cannot be installed or exercised against this project's local SQLite database, and this task's own instructions are explicit that an unrelated vector database (Chroma, FAISS, Pinecone, etc.) must not be silently substituted. Retrieval therefore computes cosine similarity in Python (`knowledge/embeddings.py::cosine_similarity`) over the small, curated chunk set (currently ~26 chunks) — correct, fully testable in this environment, and fast enough at this scale.

**Documented production upgrade path:** once the curated document set grows large enough that brute-force comparison stops being the right tradeoff, migrate `KnowledgeChunk.embedding` to a real `pgvector.django.VectorField` with an HNSW or IVFFlat index, install the `pgvector` Postgres extension and the `pgvector` Python package, and swap `retrieval.py`'s in-Python cosine-similarity loop for a native `<->`/`<=>` ORM query. The schema (`document`, `chunk_text`, `section_title`, `page_number`, `metadata`, `embedding_model`) does not need to change for this migration.

## 10. Hybrid retrieval

`knowledge/retrieval.py::retrieve()`:

```
query, topic filter(s), document_type filter, jurisdiction filter
        |
        v
KnowledgeChunk.objects.filter(document__active=True, document__topic__in=..., ...)
        |
        v
for each candidate:
    vector_score   = cosine_similarity(query_embedding, chunk.embedding)
    keyword_score  = |query_tokens ∩ chunk_tokens| / |query_tokens|
    combined       = 0.6 * vector_score + 0.4 * keyword_score
        |
        v
knowledge/reranking.py::rerank()  -- +0.08 bonus if a query word appears
                                      in the chunk's own section title
        |
        v
sort by combined score, take top RAG_TOP_K (default 5)
        |
        v
is_sufficiently_relevant()?  best score >= RAG_MIN_RELEVANCE (default 0.15)
        |                                    |
       no                                   yes
        |                                    |
        v                                    v
  "no_grounding" state                 proceed to LLM
```

Metadata filtering happens **before** any scoring — a chunk from the wrong `KnowledgeTopic` is never a candidate at all, regardless of how textually similar it might be.

## 11. Reranking

`knowledge/reranking.py::rerank()` — a small, explainable bonus (capped at +0.08) for a chunk whose own section title shares a word with the query. Not a learned re-ranker; bounded so it can only ever reorder among already-plausible candidates, never rescue an irrelevant one past the relevance gate.

## 12. Source citations

Every citation (`knowledge/provenance.py::citation_for()`) carries: document title, organization, `authority` + `authority_label` (never omitted — this is how the UI can never present reference material as official guidance), document type, section, page, version, source URL, jurisdiction, and the relevance score. `section`/`page`/`source_url` are `None` — never fabricated — when the source document doesn't carry that metadata.

Frontend: `frontend/src/components/RagGuidancePanel.tsx` renders these as a small citation list under the retrieved explanation, each showing its authority label; `[View source]` only appears when a `source_url` actually exists.

## 13. RuralCare RAG (modules 1, 3, 4)

`knowledge/queries.py::ruralcare_guidance()` — called from `POST /api/rag/ruralcare/` (`IsWorker`), wired into `frontend/src/pages/worker/NewAssessment.tsx` right under the existing `TriageSupportPanel`. Input is exactly the fields the existing `/api/assessments/preview/` response already returns (`triage_level`, `contributing_factors`, `syndrome_groups`, `referral_pathway`) — no patient id, name, code, phone, or vitals are ever passed. Retrieval is filtered to `KnowledgeTopic.CLINICAL` + `KnowledgeTopic.REFERRAL`.

**Consolidation note:** modules 1 (clinical), 3 (triage explanation), and 4 (referral guidance) share one retrieval call and one API endpoint, since in the actual UI a worker views clinical context and referral rationale together in one panel. Each module's topic tag remains independently retrievable and is independently exercised by tests.

## 14. Terminology RAG (module 2)

`knowledge/queries.py::terminology_suggestion()` — `POST /api/rag/terminology/` (`IsWorker`), scoped to `KnowledgeTopic.TERMINOLOGY`. Intended to run only for text the deterministic `agents/ruralcare/vocabulary.py` lookup already failed to recognise, and its result is always a suggestion, never an automatic conversion. **Known limitation:** the backend endpoint is implemented and tested, but is not yet wired into `NewAssessment.tsx`'s `unrecognised_entries` display — see Section 27 (Limitations).

## 15. Triage explanation RAG — see Section 13 (consolidated).

## 16. Referral guidance RAG — see Section 13 (consolidated).

## 17. GramSentinel surveillance RAG (module 5) — see Section 19 (consolidated with 6, 7, 9, 10).

## 18. Freshness / evidence-context RAG (module 6)

Consolidated into `investigation_guidance()` — see Section 19. Freshness classification itself is never touched; RAG only explains what the (unchanged) evidence and freshness state means. Confirmed by `test_freshness_classification_unchanged_by_rag` and `test_missing_remains_missing_after_rag`.

## 19. Investigation RAG (modules 5, 6, 7, 9, 10)

`knowledge/queries.py::investigation_guidance()` — `POST /api/rag/investigation/` (`IsHealthOfficer`), wired into `frontend/src/pages/officer/EvidenceView.tsx`. Input is derived **server-side** from the alert itself (`{alert_id, mode}` is all the client sends) — category, which source kinds corroborate/provide context/are missing, cross-level verdict, safety verdict — read through the same village-scoped `officer_alert_queryset()` every other alert endpoint uses, so an officer cannot request guidance for an alert outside their own village (404, matching the existing convention). Retrieval spans `SURVEILLANCE`, `PUBLIC_HEALTH`, `INVESTIGATION`, and `GRAMSENTINEL_INTERNAL` topics.

`mode="what_if"` reframes the same call toward "what additional information would strengthen or weaken this signal" — this is the What-If/counterfactual guidance module (9). **Known limitation:** the backend capability is implemented and tested (`investigation_guidance(mode="what_if", ...)`), but is not yet wired into the Simulation Lab's own frontend (`SimulationLab.tsx`, ~2900 lines — the largest file in the project) given time constraints on this implementation pass. The existing What-If engine (`simulation/what_if.py`) is completely unmodified and remains the only thing that runs a hypothetical scenario.

Module 10 (GramSentinel internal knowledge) is reachable through this same endpoint via the `GRAMSENTINEL_INTERNAL` topic — e.g. a question like "why is School marked Missing" retrieves `knowledge/seed_content.py`'s own "GramSentinel Evidence & Missing-Data Policy" document.

## 20. ASHA/CHW knowledge RAG (module 8)

`knowledge/queries.py::chw_knowledge()` — `POST /api/rag/chw/` (`IsWorker`), wired into a small "Health knowledge" card on the Worker Dashboard (`frontend/src/components/ChwKnowledgeCard.tsx`). The only endpoint accepting free text directly from a user; scoped to a single fixed `KnowledgeTopic.CHW_ASHA` the client cannot override, so it cannot become an unrestricted knowledge endpoint.

## 21. What-If RAG (module 9) — see Section 19.

## 22. Internal GramSentinel knowledge RAG (module 10) — see Section 19.

## 23. Privacy

No query builder in `knowledge/queries.py` accepts a patient name, patient code, phone number, house location, raw symptom text, vitals, Sugar reading, or patient history — confirmed both by each function's own parameter list and by `test_patient_identifiers_not_sent_to_rag`/`test_community_rag_receives_aggregate_context_only`, which introspect the actual function signatures. `investigation_guidance()` receives only already-aggregated evidence (source kinds, verdicts, a category label) — the same shape `AlertEvidenceView` already exposes, itself built only from `CommunitySignal`/`AlertEvidence` aggregate rows, never `Patient`/`PatientAssessment`.

## 24. Security

- Every RAG endpoint requires authentication and the same role permission classes the operational endpoints next to it already use (`IsWorker`, `IsHealthOfficer`).
- `InvestigationGuidanceView` derives its evidence from an `alert_id` looked up through the existing village-scoped queryset — a client cannot fabricate an evidence shape to fish for unrelated guidance, and cannot reach another village's alert.
- No endpoint accepts a client-supplied village id, source authority, or topic override for a fixed-topic endpoint (CHW, terminology).
- No document upload endpoint exists anywhere in the REST API — ingestion is a management command only, and Django admin (`knowledge/admin.py`) gates document activate/deactivate behind Django's own staff/superuser permission, not exposed to Health Worker or Health Officer accounts.
- `RagQueryLog` (audit trail) never records raw question text or patient data — only query type, user, role, topic, and retrieved document/chunk ids.

## 25. Failure fallback

`knowledge/rag_service.py::get_grounded_explanation()` never raises. Every failure mode — `RAG_ENABLED=False`, a retrieval exception, no LLM configured, an `LLMUnavailable`, no sufficiently relevant chunks — returns a clean, typed response (`status` one of `disabled`/`unavailable`/`no_grounding`/`grounded`) rather than propagating an exception. Confirmed by `test_rag_failure_does_not_fail_assessment`, which breaks retrieval entirely and verifies the real assessment-preview endpoint is completely unaffected.

## 26. Human oversight

RAG's output is always displayed as a labeled, separate panel underneath the application's own result — never merged into or replacing it. The Health Officer's investigation decision vocabulary (`Feedback.Outcome`: `VALID_SIGNAL`/`FALSE_ALERT`/`RESOLVED`) is entirely untouched by this feature; no RAG endpoint can create, update, or submit an `Investigation` or `Feedback` record (confirmed by `test_rag_cannot_automatically_submit_investigation_decision`).

## 27. Current limitations

- No `OFFICIAL`-authority document has been ingested — see Section 5.
- The local embedding provider is a deterministic hashed vectoriser, not a trained semantic embedding model — retrieval quality reflects lexical overlap more than deep semantic understanding. The `openai` provider code path is implemented but not exercised in this environment (no API key configured).
- No `pgvector` column — brute-force cosine similarity in Python, appropriate at the current knowledge-base scale (~26 chunks), documented as needing an upgrade before a much larger knowledge base.
- Terminology-suggestion RAG (module 2) has a working, tested backend endpoint but is not yet wired into the New Assessment page's UI.
- What-If guidance RAG (module 9) has a working, tested backend endpoint (`mode="what_if"`) but is not yet wired into the Simulation Lab's frontend, given that file's size and the time available for this implementation pass.
- No frontend automated tests exist for the new RAG UI components, consistent with the rest of this project (no frontend test framework is installed anywhere in the codebase) — `npm run typecheck` and `npm run build` are the verification gates used here, plus manual/live verification.
- `RagQueryLog` has no admin-side filtering-by-date-range UI beyond Django admin's own defaults.

## 28. Synthetic vs. real-world data

Nothing in this RAG layer changes any of the platform's existing data-provenance facts (see `DATA_PROVENANCE_AUDIT.md`): community health data remains synthetic/demo, Manikkampatti's demographic profile remains public/static seed data, and there is no live PHC/pharmacy/school/lab/weather/government integration anywhere in this project, including in this new module. The knowledge base is an **additional curated reference source** — it does not turn any existing synthetic operational data into real surveillance data, and it must never be described as connected to live Manikkampatti medical information.

## 29. Future real-world deployment

To move this layer toward production readiness: ingest actual verified, licensed `OFFICIAL`-authority documents (obtained directly from WHO/MoHFW/NHM or an equivalent body, with their real publication dates and source URLs); switch the embedding provider to a real semantic model via the already-implemented `openai` provider path (or add another real provider following the same pattern); migrate `KnowledgeChunk.embedding` to a `pgvector` column with an ANN index once the document set is large; wire the two documented-but-not-yet-UI-connected capabilities (terminology suggestions, What-If guidance) into their respective frontend pages; and have the resulting explanations reviewed by qualified clinical/public-health professionals before any real-world use.

---

## Jury explanation

"RAG is used as a grounded knowledge layer, not as the decision-maker. Our existing deterministic agents analyze the actual application data and produce the triage or community-signal result. The RAG layer retrieves relevant information from a curated knowledge base of approved clinical, public-health, surveillance and frontline-health guidance. The language model then uses those retrieved sources to provide a traceable explanation or investigation context. The deterministic Safety Engine remains independent of RAG and the LLM, and the Health Officer remains responsible for the final investigation decision."

"The system separates three things: what our data shows, what authoritative guidance says, and what the human decides."
