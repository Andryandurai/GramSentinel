"""Build the deterministic demonstration scenario.

    python manage.py seed_demo [--reset]

Runs the whole platform end to end on synthetic data: registers villages,
facilities, sources and users; ingests five weeks of community signals through
the Integration Layer; records synthetic encounters through the RuralCare agent
chain; aggregates them across the privacy boundary; then runs the community
pipeline so an alert is waiting on the officer dashboard.

Idempotent — re-running produces the same result rather than a second copy.
"""

from __future__ import annotations

import datetime as dt

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agents.orchestration import RuralCareOrchestrator
from alerts.models import AgentRun, Alert, Feedback, Investigation, SafetyCheck
from alerts.services import run_community_pipeline
from assessments.models import FollowUp, PatientAssessment
from community.aggregation import (
    aggregate_village_week,
    get_or_create_ruralcare_source,
)
from community.models import (
    CommunityReport,
    CommunityReportEntry,
    CommunitySignal,
    DataSource,
)
from community.views import chw_source_for, rolling_baseline
from core.constants import DataQuality, SignalCategory, SourceKind
from core.models import Facility, Village
from data.synthetic import scenario as S
from integrations.ingestion import ingest_batch
from integrations.models import IngestionEvent
from patients.models import Patient

User = get_user_model()

SOURCE_FIELD_BY_KIND = {
    SourceKind.CHW: ("chw", SignalCategory.FEVER),
    SourceKind.PHC: ("phc", SignalCategory.FEVER),
    SourceKind.PHARMACY: ("pharmacy", SignalCategory.FEVER),
    SourceKind.SCHOOL: ("school", SignalCategory.FEVER),
    SourceKind.WEATHER: ("weather", SignalCategory.ENVIRONMENT),
    SourceKind.LAB: ("lab", SignalCategory.LAB_CONFIRMATION),
}

CHANNEL_BY_KIND = {
    SourceKind.CHW: DataSource.Channel.PORTAL,
    SourceKind.PHC: DataSource.Channel.API,
    SourceKind.PHARMACY: DataSource.Channel.EXPORT,
    SourceKind.SCHOOL: DataSource.Channel.PORTAL,
    SourceKind.WEATHER: DataSource.Channel.PUBLIC_FEED,
    SourceKind.LAB: DataSource.Channel.API,
}


class Command(BaseCommand):
    help = "Seed the synthetic Village Cluster A demonstration scenario."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demonstration data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        today = timezone.localdate()

        if options["reset"]:
            self._reset()

        self.stdout.write(self.style.MIGRATE_HEADING("GramSentinel — seeding demo"))
        self.stdout.write("SYNTHETIC DEMONSTRATION DATA — NOT REAL PATIENT DATA.\n")

        villages = self._seed_villages()
        self._seed_facilities(villages)
        sources = self._seed_sources(villages)
        self._seed_users(villages)
        patients = self._seed_patients(villages)
        self._link_patient_accounts(patients)

        self._seed_community_signals(sources, today)
        self._seed_prior_aggregates(villages, today)
        self._seed_historical_reports(villages, today)
        self._seed_chw_reports(villages, today)
        self._seed_historical_alerts(villages, today)
        self._seed_encounters(patients, today)
        self._seed_followups(patients, today)
        self._aggregate(villages, today)
        self._run_pipelines(villages, today)

        self._report(today)

    # ------------------------------------------------------------------
    def _reset(self):
        self.stdout.write("Clearing previous demonstration data...")
        for model in (
            Feedback,
            Investigation,
            SafetyCheck,
            Alert,
            AgentRun,
            FollowUp,
            PatientAssessment,
            Patient,
            CommunitySignal,
            CommunityReportEntry,
            CommunityReport,
            IngestionEvent,
            DataSource,
            Facility,
        ):
            model.objects.all().delete()
        User.objects.filter(
            username__in=[u["username"] for u in S.DEMO_USERS]
        ).delete()
        Village.objects.all().delete()

    def _seed_villages(self) -> dict[str, Village]:
        villages = {}
        for row in S.VILLAGES:
            village, _ = Village.objects.update_or_create(
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "cluster": row["cluster"],
                    "block": row["block"],
                    "district": row["district"],
                    "population": row["population"],
                },
            )
            villages[row["code"]] = village
        self.stdout.write(f"  villages ............ {len(villages)}")
        return villages

    def _seed_facilities(self, villages) -> dict[str, Facility]:
        facilities = {}
        for row in S.FACILITIES:
            facility, _ = Facility.objects.update_or_create(
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "kind": row["kind"],
                    "village": villages[row["village"]],
                },
            )
            facilities[row["code"]] = facility
        self.stdout.write(f"  facilities .......... {len(facilities)}")
        return facilities

    def _seed_sources(self, villages) -> dict[str, DataSource]:
        facilities = {f.code: f for f in Facility.objects.all()}
        sources = {}
        for row in S.DATA_SOURCES:
            source, _ = DataSource.objects.update_or_create(
                code=row["code"],
                defaults={
                    "name": row["name"],
                    "kind": row["kind"],
                    "channel": row["channel"],
                    "village": villages[row["village"]],
                    "facility": facilities.get(row.get("facility", "")),
                    "is_active": True,
                    "simulated": True,
                },
            )
            sources[row["code"]] = source
        self.stdout.write(f"  data sources ........ {len(sources)} (all simulated)")
        return sources

    def _seed_users(self, villages):
        facilities = {f.code: f for f in Facility.objects.all()}
        for row in S.DEMO_USERS:
            user, created = User.objects.get_or_create(
                username=row["username"],
                defaults={
                    "role": row["role"],
                    "full_name": row["full_name"],
                    "district": row.get("district", ""),
                    "is_staff": row.get("is_staff", False),
                    "is_superuser": row.get("is_superuser", False),
                },
            )
            user.role = row["role"]
            user.full_name = row["full_name"]
            user.district = row.get("district", "")
            user.village = villages.get(row.get("village", ""))
            user.facility = facilities.get(row.get("facility", ""))
            user.is_staff = row.get("is_staff", False)
            user.is_superuser = row.get("is_superuser", False)
            # Professional profile details. Synthetic, and only filled in where
            # the scenario supplies them — a photograph is never seeded, so the
            # portal shows an initials avatar until one is uploaded.
            user.email = row.get("email", "")
            user.phone_number = row.get("phone_number", "")
            user.staff_id = row.get("staff_id", "")
            user.qualification = row.get("qualification", "")
            user.experience_years = row.get("experience_years")
            user.set_password(row["password"])
            user.save()
        self.stdout.write(f"  demo users .......... {len(S.DEMO_USERS)}")

    def _seed_patients(self, villages) -> dict[str, Patient]:
        patients = {}
        for row in S.PATIENTS:
            patient, _ = Patient.objects.update_or_create(
                patient_code=row["code"],
                defaults={
                    "display_name": row["name"],
                    "age_years": row["age_years"],
                    "sex": row["sex"],
                    "village": villages[row["village"]],
                },
            )
            patients[row["code"]] = patient
        self.stdout.write(f"  synthetic patients .. {len(patients)}")
        return patients

    def _link_patient_accounts(self, patients):
        """Attach the patient demo login to its own synthetic record."""

        linked = 0
        for row in S.DEMO_USERS:
            code = row.get("linked_patient")
            if not code:
                continue
            user = User.objects.filter(username=row["username"]).first()
            patient = patients.get(code)
            if user and patient:
                patient.linked_user = user
                patient.save(update_fields=["linked_user"])
                linked += 1
        if linked:
            self.stdout.write(f"  patient logins ...... {linked} linked to own record")

    def _seed_community_signals(self, sources, today: dt.date):
        """Push five weeks through the Integration Layer, one batch per week.

        Baselines are computed from the preceding weeks in the same table, so
        the anomaly arithmetic the agents perform is genuine even though the
        inputs are fixed.
        """

        by_village_kind: dict[tuple[str, str], DataSource] = {
            (s.village.code, s.kind): s for s in sources.values()
        }

        total_events = 0
        for village_code, weeks in S.HISTORY.items():
            ordered = sorted(weeks, key=lambda w: -w["weeks_ago"])
            history: dict[str, list[float]] = {}

            for week in ordered:
                week_start = S.week_start_for(today, week["weeks_ago"])
                label = S.week_label_for(week_start)
                records = []

                for kind, (field, category) in SOURCE_FIELD_BY_KIND.items():
                    source = by_village_kind.get((village_code, kind))
                    if source is None or field not in week:
                        continue

                    value = week[field]
                    seen = history.setdefault(field, [])
                    baseline = (
                        round(sum(seen[-4:]) / len(seen[-4:]), 2) if seen else None
                    )

                    if value is None:
                        # Deliberate gap: recorded as not submitted, not as 0.
                        records.append(
                            {
                                "source_code": source.code,
                                "category": category,
                                "week_label": label,
                                "value": None,
                                "baseline": baseline,
                                "is_reported": False,
                            }
                        )
                        continue

                    records.append(
                        {
                            "source_code": source.code,
                            "category": category,
                            "week_label": label,
                            "value": value,
                            "baseline": baseline if baseline is not None else value,
                            "is_reported": True,
                            "data_quality": DataQuality.GOOD,
                        }
                    )
                    seen.append(float(value))

                if records:
                    ingest_batch(
                        records,
                        channel=DataSource.Channel.API,
                        week_label=label,
                    )
                    total_events += 1

        self.stdout.write(f"  ingestion batches ... {total_events}")

    def _seed_prior_aggregates(self, villages, today: dt.date):
        """Give the aggregated RuralCare signal a prior-week baseline."""

        prior_start = S.week_start_for(today, 1)
        label = S.week_label_for(prior_start)

        for village_code, counts in S.PRIOR_WEEK_ENCOUNTER_COUNTS.items():
            village = villages[village_code]
            source = get_or_create_ruralcare_source(village)
            for category, count in counts.items():
                CommunitySignal.objects.update_or_create(
                    source=source,
                    category=category,
                    week_label=label,
                    defaults={
                        "village": village,
                        "period_start": prior_start,
                        "period_end": prior_start + dt.timedelta(days=6),
                        "value": float(count),
                        "baseline": float(count),
                        "unit": "encounters",
                        "is_reported": True,
                        "data_quality": DataQuality.GOOD,
                        "metadata": {"origin": "privacy_preserving_aggregation"},
                    },
                )

    def _seed_historical_reports(self, villages, today: dt.date):
        """Six weeks of community reporting, one story per village.

        Idempotent through update_or_create on (village, week_label, worker),
        and entries are replaced rather than appended, so re-running the seed
        does not double any count.
        """

        worker_by_village = {
            u.village.code: u
            for u in User.objects.filter(role=User.Role.CHW_PHC_WORKER)
            if u.village and u.username.startswith("worker.")
        }

        weeks = 0
        for code, history in S.HISTORICAL_REPORTS.items():
            village = villages[code]
            worker = worker_by_village.get(code)
            source = chw_source_for(village)

            for week in sorted(history, key=lambda w: -w["weeks_ago"]):
                week_start = S.week_start_for(today, week["weeks_ago"])
                label = S.week_label_for(week_start)
                entries = week["entries"]
                descriptions = week.get("descriptions", {})

                report, _ = CommunityReport.objects.update_or_create(
                    village=village,
                    week_label=label,
                    worker=worker,
                    defaults={
                        "period_start": week_start,
                        "period_end": week_start + dt.timedelta(days=6),
                        "fever_cases": entries.get(SignalCategory.FEVER, 0),
                        "respiratory_cases": entries.get(
                            SignalCategory.RESPIRATORY, 0
                        ),
                        "diarrhoeal_cases": entries.get(
                            SignalCategory.DIARRHOEAL, 0
                        ),
                        "other_cases": entries.get(SignalCategory.OTHER, 0),
                        "unusual_observation": week.get("unusual", False),
                        "notes": week.get("notes", ""),
                        # Historical reports are treated as already seen, so the
                        # "new report" indicator reflects the current week only.
                        "acknowledged_at": timezone.now(),
                    },
                )

                report.entries.all().delete()
                CommunityReportEntry.objects.bulk_create(
                    [
                        CommunityReportEntry(
                            report=report,
                            category=category,
                            case_count=count,
                            description=descriptions.get(category, ""),
                        )
                        for category, count in entries.items()
                    ]
                )

                ingest_batch(
                    [
                        {
                            "source_code": source.code,
                            "category": category,
                            "week_label": label,
                            "value": count,
                            "baseline": rolling_baseline(source, category, label),
                            "is_reported": True,
                            "data_quality": DataQuality.GOOD,
                        }
                        for category, count in entries.items()
                    ],
                    channel=DataSource.Channel.PORTAL,
                    week_label=label,
                )
                weeks += 1

        self.stdout.write(
            f"  historical reports .. {weeks} village-weeks "
            f"({len(S.HISTORICAL_REPORTS)} villages × ~5 weeks)"
        )

    def _seed_historical_alerts(self, villages, today: dt.date):
        """Backdated alerts with realistic mixed outcomes.

        Uses the existing Alert / Investigation / Feedback models unchanged.
        `created_at` is auto_now_add, so it is backdated with a follow-up
        queryset update — the only way to place a record in the past without
        altering the model.
        """

        officer_by_village = {
            u.village.code: u
            for u in User.objects.filter(role=User.Role.HEALTH_OFFICER)
            if u.village
        }

        titles = {
            SignalCategory.FEVER: "Fever-related signals rising",
            SignalCategory.RESPIRATORY: "Respiratory signals rising",
            SignalCategory.DIARRHOEAL: "Diarrhoeal signals rising",
            SignalCategory.WATER_BORNE: "Water-borne illness indicators rising",
            SignalCategory.SKIN: "Skin-related signals rising",
        }

        made = 0
        for code, entries in S.HISTORICAL_ALERTS.items():
            village = villages[code]
            officer = officer_by_village.get(code)

            for spec in entries:
                week_start = S.week_start_for(today, spec["weeks_ago"])
                label = S.week_label_for(week_start)
                category = spec["category"]

                # Historical alerts sit on past weeks, so they never collide
                # with the current-week pipeline run.
                if Alert.objects.filter(
                    village=village, week_label=label, category=category
                ).exists():
                    continue

                outcome = spec.get("outcome")
                status = (
                    Alert.Status.CLOSED if outcome else spec.get("status", "DETECTED")
                )

                alert = Alert.objects.create(
                    village=village,
                    cluster=village.cluster,
                    category=category,
                    week_label=label,
                    period_start=week_start,
                    period_end=week_start + dt.timedelta(days=6),
                    title=(
                        f"{titles.get(category, 'Health signals rising')} — "
                        f"{village.cluster}"
                    ),
                    summary=(
                        f"{spec['sources']} independent source(s) moved above "
                        f"their own baselines in {village.cluster} during "
                        f"{label}. Recorded as a possible pattern for human "
                        "review."
                    ),
                    severity=spec["severity"],
                    confidence=spec["confidence"],
                    corroborating_source_count=spec["sources"],
                    cross_level_verdict=(
                        "CONSISTENT" if spec["sources"] >= 3 else "SILENT"
                    ),
                    cross_level_statement=(
                        "Aggregated individual encounters moved in the same "
                        "direction."
                        if spec["sources"] >= 3
                        else "Aggregated individual encounters were not decisive."
                    ),
                    safety_verdict=spec.get("safety_verdict", "PASS"),
                    safety_status=spec.get(
                        "safety_status", "REQUIRES_HUMAN_REVIEW"
                    ),
                    status=status,
                )

                created_at = timezone.make_aware(
                    dt.datetime.combine(
                        week_start + dt.timedelta(days=5), dt.time(9, 30)
                    )
                )
                Alert.objects.filter(pk=alert.pk).update(created_at=created_at)

                # A per-rule record so the Evidence view is not empty for
                # historical alerts either.
                SafetyCheck.objects.create(
                    alert=alert,
                    scope=SafetyCheck.Scope.COMMUNITY,
                    verdict=alert.safety_verdict,
                    passed=alert.safety_verdict == "PASS",
                    status=alert.safety_status,
                    rules=[],
                    reasons=[
                        f"{spec['sources']} independent corroborating source(s) "
                        "recorded for this window."
                    ],
                    village=village,
                    week_label=label,
                )

                if outcome or status == "UNDER_INVESTIGATION":
                    Investigation.objects.update_or_create(
                        alert=alert,
                        defaults={
                            "officer": officer,
                            "status": (
                                Investigation.Status.COMPLETED
                                if outcome
                                else Investigation.Status.UNDER_INVESTIGATION
                            ),
                            "notes": spec.get("notes", ""),
                        },
                    )

                if outcome:
                    feedback = Feedback.objects.create(
                        alert=alert,
                        officer=officer,
                        outcome=outcome,
                        notes=spec.get("notes", ""),
                        resolution_latency_seconds=3 * 24 * 3600,
                    )
                    Feedback.objects.filter(pk=feedback.pk).update(
                        created_at=created_at + dt.timedelta(days=3)
                    )

                made += 1

        self.stdout.write(f"  historical alerts ... {made} across 3 villages")

    def _seed_chw_reports(self, villages, today: dt.date):
        """One community report per village, each with a different shape.

        Village A is the corroborated fever cluster; Village B is a described
        skin/eye concern no other source corroborates; Village C is quiet with
        an injury note. This gives each officer dashboard something distinct.
        """

        week_start = S.week_start_for(today, 0)
        label = S.week_label_for(week_start)

        worker_by_village = {
            u.village.code: u
            for u in User.objects.filter(role=User.Role.CHW_PHC_WORKER)
            if u.village and u.username.startswith("worker.")
        }

        notes_by_village = {
            "KVL": (
                "Several households reporting febrile illness after the recent "
                "rainfall."
            ),
            "ARY": (
                "Skin and eye complaints noticed during home visits this week. "
                "Recording for visibility — cause unclear."
            ),
            "MLR": "Routine week. Injuries relate to harvest activity.",
        }

        made = 0
        for code, entries in S.VILLAGE_REPORT_ENTRIES.items():
            village = villages[code]
            worker = worker_by_village.get(code)
            totals = {e["category"]: e["case_count"] for e in entries}

            report, _ = CommunityReport.objects.update_or_create(
                village=village,
                week_label=label,
                worker=worker,
                defaults={
                    "period_start": week_start,
                    "period_end": week_start + dt.timedelta(days=6),
                    "fever_cases": totals.get(SignalCategory.FEVER, 0),
                    "respiratory_cases": totals.get(SignalCategory.RESPIRATORY, 0),
                    "diarrhoeal_cases": totals.get(SignalCategory.DIARRHOEAL, 0),
                    "other_cases": totals.get(SignalCategory.OTHER, 0),
                    "unusual_observation": code in {"KVL", "ARY"},
                    "notes": notes_by_village.get(code, ""),
                    "acknowledged_at": None,
                },
            )

            report.entries.all().delete()
            CommunityReportEntry.objects.bulk_create(
                [
                    CommunityReportEntry(
                        report=report,
                        category=entry["category"],
                        case_count=entry["case_count"],
                        description=entry.get("description", ""),
                    )
                    for entry in entries
                ]
            )

            # Ingest every reported category so the expanded vocabulary is
            # visible in Local Signals, not only the original four.
            source = chw_source_for(village)
            ingest_batch(
                [
                    {
                        "source_code": source.code,
                        "category": entry["category"],
                        "week_label": label,
                        "value": entry["case_count"],
                        "baseline": rolling_baseline(
                            source, entry["category"], label
                        ),
                        "is_reported": True,
                        "data_quality": DataQuality.GOOD,
                    }
                    for entry in entries
                ],
                channel=DataSource.Channel.PORTAL,
                week_label=label,
            )
            made += 1

        self.stdout.write(
            f"  CHW reports ......... {made} (one per village, distinct profiles)"
        )

    def _seed_encounters(self, patients, today: dt.date):
        """Run each synthetic encounter through the real RuralCare agent chain."""

        orchestrator = RuralCareOrchestrator()
        worker_by_village = {
            u.village.code: u
            for u in User.objects.filter(role=User.Role.CHW_PHC_WORKER)
            if u.village
        }
        created = 0

        for row in S.SEED_ENCOUNTERS:
            patient = patients[row["patient"]]
            encounter_date = today - dt.timedelta(days=row["days_ago"])
            created += self._create_encounter(
                orchestrator, worker_by_village, patient, encounter_date, row
            )

        # Two earlier weeks, so the dashboard's week filter has real history to
        # filter rather than a single week.
        history = 0
        for row in S.SEED_HISTORY_ENCOUNTERS:
            patient = patients[row["patient"]]
            encounter_date = S.week_start_for(
                today, row["weeks_ago"]
            ) + dt.timedelta(days=row["day_offset"])
            history += self._create_encounter(
                orchestrator, worker_by_village, patient, encounter_date, row
            )

        self.stdout.write(
            f"  encounters .......... {created} (through the agent chain)"
        )
        self.stdout.write(
            f"  earlier weeks ....... {history} (two prior weeks of encounters)"
        )

    def _create_encounter(
        self,
        orchestrator,
        worker_by_village,
        patient,
        encounter_date: dt.date,
        row: dict,
    ) -> int:
        """One synthetic encounter through the real agent chain. Idempotent."""

        if PatientAssessment.objects.filter(
            patient=patient, encounter_date=encounter_date, is_draft=False
        ).exists():
            return 0

        result = orchestrator.run(
            {
                "symptoms": row["symptoms"],
                "duration_days": row["duration_days"],
                "temperature_c": row.get("temperature_c"),
                "age_months": patient.age_in_months,
                "village_code": patient.village.code,
                "cluster": patient.village.cluster,
            }
        )
        if not result.get("ok"):
            self.stderr.write(f"    agent chain failed for {patient.patient_code}")
            return 0

        PatientAssessment.objects.create(
            patient=patient,
            worker=worker_by_village.get(patient.village.code),
            village=patient.village,
            symptoms=result["normalised_symptoms"],
            duration_days=row["duration_days"],
            temperature_c=row.get("temperature_c"),
            primary_category=result["signal_category"],
            triage_level=result["triage_level"],
            triage_score=result["triage_score"],
            reasoning_summary=result["reasoning_summary"],
            referral_recommendation=result["referral_recommendation"],
            followup_interval_days=result["followup_interval_days"],
            red_flags=result["red_flags"],
            escalation_forced=result["escalation_forced"],
            safety_status=result["safety_status"],
            agent_trace=result["agent_trace"],
            llm_used=result["used_llm"],
            is_draft=False,
            encounter_date=encounter_date,
        )
        return 1

    def _seed_followups(self, patients, today: dt.date):
        """Pending and completed follow-ups across the three villages.

        Dates are offsets from the day the seed runs, so the dashboard always
        shows the same mixture — something overdue, something due today, and
        several upcoming — whenever the demonstration is given.

        Each pending follow-up is attached to that patient's most recent
        encounter where one exists, so opening the patient shows the assessment
        the follow-up came from. Patients registered for review with no
        encounter yet are left unattached, which the portal handles.
        """

        worker_by_village = {
            u.village.code: u
            for u in User.objects.filter(role=User.Role.CHW_PHC_WORKER)
            if u.village and u.username.startswith("worker.")
        }

        made = 0
        for row in getattr(S, "SEED_FOLLOWUPS", []):
            patient = patients.get(row["patient"])
            if patient is None:
                continue

            due_date = today + dt.timedelta(days=row["days"])
            assessment = (
                PatientAssessment.objects.filter(patient=patient, is_draft=False)
                .order_by("-encounter_date", "-created_at")
                .first()
            )

            FollowUp.objects.update_or_create(
                patient=patient,
                due_date=due_date,
                defaults={
                    "assessment": assessment,
                    "status": row.get("status", FollowUp.Status.PENDING),
                    "notes": row.get("notes", ""),
                    "created_by": worker_by_village.get(patient.village.code),
                },
            )
            made += 1

        pending = FollowUp.objects.filter(status=FollowUp.Status.PENDING).count()
        overdue = FollowUp.objects.filter(
            status=FollowUp.Status.PENDING, due_date__lt=today
        ).count()
        self.stdout.write(
            f"  follow-ups .......... {made} ({pending} pending, {overdue} overdue)"
        )

    def _aggregate(self, villages, today: dt.date):
        total = 0
        for village in villages.values():
            # Oldest first, so each week's rolling baseline is built from the
            # weeks before it, exactly as it would be in normal operation.
            for weeks_ago in (2, 1):
                aggregate_village_week(village, S.week_start_for(today, weeks_ago))
            total += len(aggregate_village_week(village, today))
        self.stdout.write(
            f"  aggregated signals .. {total} (anonymised counts across the boundary)"
        )

    def _run_pipelines(self, villages, today: dt.date):
        label = S.week_label_for(S.week_start_for(today, 0))
        self.stdout.write("\n  Running the six-stage pipeline per village:")
        for village in villages.values():
            outcome = run_community_pipeline(village, label, SignalCategory.FEVER)
            safety = outcome["safety"]
            if outcome["alert_raised"]:
                alert = outcome["alert"]
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    {village.name:<10} ALERT  {alert.severity:<8} "
                        f"safety={safety['verdict']:<9} "
                        f"sources={safety['corroborating_source_count']} "
                        f"confidence={alert.confidence}"
                    )
                )
            else:
                self.stdout.write(
                    f"    {village.name:<10} none   "
                    f"safety={safety['verdict']:<9} "
                    f"sources={safety['corroborating_source_count']} "
                    f"({outcome['reason']})"
                )

    def _report(self, today: dt.date):
        label = S.week_label_for(S.week_start_for(today, 0))
        self.stdout.write(self.style.MIGRATE_HEADING("\nDemo ready"))
        self.stdout.write(f"  Current week ........ {label}")
        self.stdout.write(f"  Alerts on dashboard . {Alert.objects.count()}")
        self.stdout.write(f"  Agent runs recorded . {AgentRun.objects.count()}")
        self.stdout.write(f"  Safety checks ....... {SafetyCheck.objects.count()}")
        self.stdout.write("\n  Demonstration accounts (password: demo1234)")
        self.stdout.write(
            "    AREA        USERNAME     ROLE               SCOPE"
        )
        self.stdout.write("    " + "-" * 68)
        rows = [
            ("Village A", "worker.a", "CHW / PHC Worker", "Kovilur only"),
            ("Village A", "officer.a", "Health Officer", "Kovilur only"),
            ("Village B", "worker.b", "CHW / PHC Worker", "Ariyanur only"),
            ("Village B", "officer.b", "Health Officer", "Ariyanur only"),
            ("Village C", "worker.c", "CHW / PHC Worker", "Melur only"),
            ("Village C", "officer.c", "Health Officer", "Melur only"),
        ]
        for area, username, role, scope in rows:
            self.stdout.write(
                self.style.SUCCESS(
                    f"    {area:<11} {username:<12} {role:<18} {scope}"
                )
            )
        self.stdout.write("    " + "-" * 68)
        for area, username, role, scope in (
            ("—", "patient", "Patient", "Own record only"),
            ("—", "admin", "Administrator", "All villages"),
            ("—", "worker", "CHW (original)", "Kovilur only"),
            ("—", "officer", "Officer (original)", "District-wide"),
        ):
            self.stdout.write(
                f"    {area:<11} {username:<12} {role:<18} {scope}"
            )
        self.stdout.write(
            "\n  All data is synthetic. No real patient, pharmacy, school, "
            "laboratory\n  or government data is used, and no access to any real "
            "system is claimed.\n"
        )
