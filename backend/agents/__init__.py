"""GramSentinel's multi-agent layer.

Fourteen agents, each with one narrow job:

  RuralCare (individual, 5)   listener -> symptom -> triage -> referral -> safety
  GramSentinel (community, 8) CHW, PHC, pharmacy, school, weather, lab,
                              village trend, cluster detection
  Cross-Level (1)             does aggregated individual evidence agree with
                              community evidence, in the same place and week?

Agents exchange structured records, not free text. Most are deterministic
statistical logic; the LLM is confined to narrative synthesis and is never in
the safety-critical path.
"""
