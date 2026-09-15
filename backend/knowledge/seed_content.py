"""The curated document set `ingest_knowledge` loads — this project's own
equivalent of `data/synthetic/scenario.py` for the knowledge base.

HONESTY NOTE, read before adding anything here: every document below is
either `DocumentAuthority.INTERNAL` (this project's own documented rules —
verified accurate against the actual code, since it describes this
application) or `DocumentAuthority.REFERENCE` (general, widely-known
public-health reference material this project's team wrote in plain
language, explicitly NOT presented as verbatim text from WHO, MoHFW, NHM,
or any other named body). No `OFFICIAL` document is seeded here — doing
that responsibly requires an actual verified, licensed source file, which
this environment has no way to fetch or authenticate. Ingesting a real
official guideline (an IMNCI/RBSK/NVBDCP PDF, a WHO fact sheet, etc.) is
documented as the next real step in RAG_ARCHITECTURE.md, not simulated
here by mislabeling reference content as official.
"""

from __future__ import annotations

from .chunking import RawSection
from .models import DocumentAuthority, DocumentType, KnowledgeTopic

REFERENCE_ORG = "GramSentinel Project Team — general reference (not verbatim official text)"

DOCUMENTS: list[dict] = [
    # ------------------------------------------------------------------
    # GRAMSENTINEL_INTERNAL — the application's own documented rules.
    # ------------------------------------------------------------------
    {
        "title": "GramSentinel Evidence & Missing-Data Policy",
        "organization": "GramSentinel Project Team",
        "authority": DocumentAuthority.INTERNAL,
        "document_type": DocumentType.APPLICATION_DOCUMENTATION,
        "topic": KnowledgeTopic.GRAMSENTINEL_INTERNAL,
        "subtopic": "Missing data, freshness, corroboration",
        "jurisdiction": "GramSentinel platform",
        "sections": [
            RawSection(
                "Missing data is never treated as zero", 1,
                "When a community data source does not submit a report for a "
                "reporting period, GramSentinel records that period as "
                "not-reported rather than as a value of zero. A source that "
                "genuinely reports zero cases is recorded as a reported zero. "
                "These two states are kept structurally distinct throughout "
                "the platform, because treating an outage or a reporting gap "
                "as reassuring good news is a well-known failure mode in "
                "health surveillance systems.",
            ),
            RawSection(
                "Source Freshness is informational, not a safety signal", 1,
                "The Source Freshness Indicator classifies each source as "
                "Fresh, Aging, Stale or Missing based only on how long ago it "
                "last reported. This classification never changes the "
                "deterministic Safety Engine's verdict, an alert's severity, "
                "or whether an alert is created. A stale or missing source is "
                "not automatically unsafe, and a fresh source is not "
                "automatically safe — freshness only tells a Health Officer "
                "how recent the evidence in front of them actually is.",
            ),
            RawSection(
                "Corroboration requirement", 2,
                "A community signal generally needs at least two independent "
                "corroborating sources exceeding their own baseline before it "
                "is treated as higher-confidence evidence. A single anomalous "
                "source, on its own, is capped at lower confidence by the "
                "Safety Engine's own rules, regardless of how large that one "
                "source's rise is.",
            ),
        ],
    },
    {
        "title": "GramSentinel Alert Lifecycle & Investigation Workflow",
        "organization": "GramSentinel Project Team",
        "authority": DocumentAuthority.INTERNAL,
        "document_type": DocumentType.APPLICATION_DOCUMENTATION,
        "topic": KnowledgeTopic.GRAMSENTINEL_INTERNAL,
        "subtopic": "Signals, alerts, investigation, human decision",
        "jurisdiction": "GramSentinel platform",
        "sections": [
            RawSection(
                "What a signal is, and what it is not", 1,
                "A community signal is one source's reported value for one "
                "health category in one reporting week, compared against its "
                "own recent baseline. A signal being above baseline is not, "
                "by itself, a diagnosis, an outbreak, or a confirmed health "
                "event — it is a data point the platform's deterministic "
                "agents and Safety Engine evaluate together with other "
                "sources before anything is raised for human attention.",
            ),
            RawSection(
                "What an alert is", 2,
                "An Alert is created only after the deterministic Safety "
                "Engine has evaluated the available evidence and returned a "
                "verdict of PASS or DOWNGRADE with at least one corroborating "
                "source. A BLOCK verdict, or zero corroborating sources, "
                "means no Alert is created, though the evaluation itself is "
                "still recorded. An Alert is a request for a qualified "
                "human's attention, never a conclusion and never an outbreak "
                "declaration.",
            ),
            RawSection(
                "Investigation and the human decision", 3,
                "Every Alert requires human review — this is a structural "
                "property of the platform, not a configurable setting. A "
                "Health Officer investigates the evidence, may mark the "
                "alert under investigation, and ultimately records one of "
                "three outcomes: Valid Signal, False Alert, or Resolved. "
                "'Valid Signal' means a human confirmed the alert was worth "
                "raising — it does not mean any specific disease or outbreak "
                "was confirmed. The Health Officer's decision is the only "
                "point in the whole pipeline where the platform's evaluation "
                "becomes a real-world conclusion.",
            ),
        ],
    },
    {
        "title": "RuralCare to GramSentinel Aggregation Boundary",
        "organization": "GramSentinel Project Team",
        "authority": DocumentAuthority.INTERNAL,
        "document_type": DocumentType.APPLICATION_DOCUMENTATION,
        "topic": KnowledgeTopic.GRAMSENTINEL_INTERNAL,
        "subtopic": "Privacy boundary",
        "jurisdiction": "GramSentinel platform",
        "sections": [
            RawSection(
                "How individual visits become a community signal", 1,
                "Individual patient assessments are aggregated into a weekly "
                "count per health category per village before they ever "
                "reach the community layer. This aggregation step reads only "
                "a village, a category, an encounter count and a time "
                "window — no patient name, symptom text, vitals, or any "
                "other individual field is selected by this step, by design. "
                "The resulting count is treated as one source among several, "
                "not as a privileged or higher-authority source.",
            ),
        ],
    },
    # ------------------------------------------------------------------
    # CLINICAL / REFERRAL — general reference, explicitly not verbatim
    # official guidance.
    # ------------------------------------------------------------------
    {
        "title": "General Reference: Fever in a Rural Primary-Care Setting",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.GUIDELINE,
        "topic": KnowledgeTopic.CLINICAL,
        "subtopic": "Fever, duration, danger signs",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Why duration matters", 1,
                "A fever lasting several days is generally regarded as more "
                "concerning than a fever of one or two days, because it "
                "narrows the range of likely causes and increases the "
                "chance that the underlying condition needs professional "
                "evaluation rather than resolving on its own. Persistent "
                "fever alongside other symptoms — breathlessness, repeated "
                "vomiting, reduced alertness — is commonly treated as a "
                "stronger reason for prompt referral than fever alone.",
            ),
            RawSection(
                "Danger signs commonly prompting urgent referral", 1,
                "Widely-taught danger signs in a frontline-care context "
                "include: difficulty breathing or fast breathing, inability "
                "to drink or feed, repeated vomiting, convulsions, lethargy "
                "or unconsciousness, and very high or very low temperature. "
                "The presence of any of these alongside a fever is commonly "
                "treated as reason for same-day evaluation at a facility "
                "rather than routine follow-up.",
            ),
            RawSection(
                "Fever in young children", 2,
                "Young children, and especially infants, are generally "
                "treated with a lower threshold for concern than adults with "
                "an equivalent set of findings, because deterioration can "
                "happen faster and early signs can be harder to recognise. "
                "A fever in a very young infant is commonly treated as "
                "warranting professional evaluation regardless of how the "
                "infant otherwise appears.",
            ),
        ],
    },
    {
        "title": "General Reference: Diarrhoeal Illness and Dehydration",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.GUIDELINE,
        "topic": KnowledgeTopic.CLINICAL,
        "subtopic": "Diarrhoea, dehydration, referral",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Recognising dehydration", 1,
                "Common signs used to recognise dehydration in a "
                "frontline-care setting include sunken eyes, a very dry "
                "mouth, reduced skin elasticity, reduced urination, and "
                "unusual thirst or an inability to drink. Severe "
                "dehydration — an inability to drink, lethargy, or very "
                "sunken eyes together — is commonly treated as an indication "
                "for prompt referral rather than home management alone.",
            ),
            RawSection(
                "Ongoing fluids while arranging care", 1,
                "Continuing oral fluids while arranging professional "
                "evaluation is a widely-taught principle for diarrhoeal "
                "illness, since dehydration is often the most immediately "
                "dangerous part of the presentation rather than the "
                "diarrhoea itself.",
            ),
        ],
    },
    {
        "title": "General Reference: When to Refer from Community Level",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.REFERRAL_GUIDANCE,
        "topic": KnowledgeTopic.REFERRAL,
        "subtopic": "Referral thresholds",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Same-day facility referral", 1,
                "Presentations combining multiple danger signs, or a single "
                "severe danger sign such as difficulty breathing, repeated "
                "convulsions, or an inability to drink, are commonly treated "
                "as warranting same-day evaluation at the nearest capable "
                "facility rather than a scheduled follow-up visit.",
            ),
            RawSection(
                "Routine follow-up vs facility referral", 2,
                "Where no danger sign is present and the presentation is "
                "mild, community-level follow-up with clear guidance on "
                "when to return is commonly considered appropriate, with "
                "the household advised to seek care promptly if the "
                "condition changes or new symptoms appear.",
            ),
        ],
    },
    # ------------------------------------------------------------------
    # TERMINOLOGY
    # ------------------------------------------------------------------
    {
        "title": "General Reference: Plain-Language Symptom Terms",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.TERMINOLOGY_REFERENCE,
        "topic": KnowledgeTopic.TERMINOLOGY,
        "subtopic": "Common phrasing for recognised symptoms",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Fever-related phrasing", 1,
                "Phrases such as 'body is very hot', 'burning up', 'running "
                "a temperature', or 'feeling feverish' commonly refer to the "
                "recognised symptom fever. A description of a hot body "
                "without a measured temperature is still commonly treated "
                "as describing fever for the purpose of recording a symptom.",
            ),
            RawSection(
                "Breathlessness-related phrasing", 1,
                "Phrases such as 'can't catch breath', 'breathing fast', "
                "'chest feels tight', or 'gasping' commonly refer to the "
                "recognised symptom breathlessness or difficulty breathing.",
            ),
            RawSection(
                "Dehydration-related phrasing", 1,
                "Phrases such as 'not passing urine', 'very dry mouth', or "
                "'won't drink anything' commonly relate to dehydration or an "
                "inability to drink, both of which are recognised danger "
                "signs.",
            ),
        ],
    },
    # ------------------------------------------------------------------
    # SURVEILLANCE / PUBLIC_HEALTH / INVESTIGATION
    # ------------------------------------------------------------------
    {
        "title": "General Reference: Interpreting Multi-Source Community Signals",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.SURVEILLANCE_GUIDANCE,
        "topic": KnowledgeTopic.SURVEILLANCE,
        "subtopic": "Source triangulation",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Why more than one source matters", 1,
                "A rise reported by a single source can reflect many things "
                "besides a genuine change in community health — a reporting "
                "change, a data-entry pattern, or normal week-to-week "
                "variation. A pattern that several independent sources show "
                "at the same time is generally treated as more credible "
                "evidence than the same pattern from one source alone, which "
                "is why triangulating across sources is a standard "
                "principle in community-level surveillance.",
            ),
            RawSection(
                "Context sources vs corroborating sources", 2,
                "Environmental information such as rainfall can make a "
                "health-related pattern more plausible without itself being "
                "direct evidence of a health event — this kind of source is "
                "commonly treated as supporting context rather than "
                "independent corroboration.",
            ),
            RawSection(
                "Handling a source that disagrees", 2,
                "When one source's trend conflicts with the others, the "
                "disagreement itself is useful information — it is "
                "generally treated as a reason to look more closely (verify "
                "reporting quality, check for a data gap, or wait for the "
                "next reporting period) rather than a reason to discard "
                "either source's data.",
            ),
        ],
    },
    {
        "title": "General Reference: Verifying a Potential Community Signal",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.INVESTIGATION_GUIDANCE,
        "topic": KnowledgeTopic.INVESTIGATION,
        "subtopic": "Verification steps",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Common verification steps", 1,
                "Commonly-used verification steps when reviewing a potential "
                "community signal include: obtaining a missing source's "
                "report for the same period where possible, checking whether "
                "the pattern persists into the next reporting period rather "
                "than being a single-week spike, confirming there is no "
                "duplicate or double-counted reporting, and, where clinically "
                "appropriate, seeking laboratory confirmation for a sample of "
                "cases to add direct evidence rather than relying on "
                "category-level counts alone.",
            ),
            RawSection(
                "Persistence over time", 2,
                "A pattern that continues to appear across more than one "
                "reporting period is generally treated as stronger evidence "
                "than an isolated single-week rise, which can more easily be "
                "explained by normal variation or a one-off reporting "
                "irregularity.",
            ),
        ],
    },
    {
        "title": "General Reference: Community Health Worker Role in Surveillance",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.SURVEILLANCE_GUIDANCE,
        "topic": KnowledgeTopic.PUBLIC_HEALTH,
        "subtopic": "CHW reporting role",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Why frontline reporting matters", 1,
                "Frontline community health workers are often the first "
                "point of contact for a health concern in a rural area, "
                "which makes their reporting an early and valuable source "
                "of community-level information — often earlier than "
                "facility-based records, which depend on someone actually "
                "reaching a facility first.",
            ),
        ],
    },
    # ------------------------------------------------------------------
    # CHW_ASHA — educational content for frontline workers.
    # ------------------------------------------------------------------
    {
        "title": "General Reference: What to Check Before Referring a Child with Diarrhoea",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.CHW_GUIDANCE,
        "topic": KnowledgeTopic.CHW_ASHA,
        "subtopic": "Diarrhoea in children",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "What to check", 1,
                "Before referring, it is commonly useful to check: how many "
                "days the diarrhoea has lasted, whether there is blood in "
                "the stool, whether the child is drinking normally, whether "
                "the child appears unusually sleepy or hard to wake, and "
                "whether the eyes look sunken. These observations help "
                "whoever the child is referred to understand the situation "
                "quickly.",
            ),
            RawSection(
                "What to tell the household", 2,
                "Households are commonly advised to keep offering fluids, "
                "to continue feeding as tolerated, and to seek care promptly "
                "if the child cannot drink, becomes unusually sleepy, or the "
                "diarrhoea does not improve.",
            ),
        ],
    },
    {
        "title": "General Reference: Warning Signs Worth a Second Look",
        "organization": REFERENCE_ORG,
        "authority": DocumentAuthority.REFERENCE,
        "document_type": DocumentType.CHW_GUIDANCE,
        "topic": KnowledgeTopic.CHW_ASHA,
        "subtopic": "General danger signs",
        "jurisdiction": "General",
        "sections": [
            RawSection(
                "Signs that commonly warrant prompt attention", 1,
                "Signs commonly treated as warranting prompt attention "
                "regardless of the presenting complaint include: difficulty "
                "breathing, convulsions, unusual sleepiness or "
                "unresponsiveness, inability to drink or feed, repeated "
                "vomiting, and a very high fever. Noting which of these are "
                "present — and which are absent — is commonly useful "
                "information to pass along when referring someone onward.",
            ),
        ],
    },
]
