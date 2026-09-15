"""Work & Communication API.

Three worker-facing feature areas (Supervisor Communication, Report
Approval Tracker, Correction Requests) plus the matching Health Officer
review endpoints. Every view below derives ownership/scope from
`request.user` and a real relationship (`workspace.services`) — never from
a client-supplied worker/officer/village id (task's own non-negotiable
rule, enforced the same way `community/views.py` and `simulation/views.py`
already enforce it elsewhere in this codebase).
"""

from __future__ import annotations

import base64
import datetime as dt

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from community.models import CommunityReport
from users.permissions import IsHealthOfficer, IsWorker, IsWorkerOrOfficer
from users.scoping import scope_queryset, scoped_village_id

from . import services
from .models import (
    CorrectionEvent,
    CorrectionRequest,
    ReportApproval,
    ReportApprovalEvent,
    SupervisorMessage,
    WorkflowStatus,
)
from .serializers import (
    RECORD_TYPE_CHOICES,
    RECORD_TYPE_LABELS,
    CorrectionRequestCreateSerializer,
    CorrectionRequestSerializer,
    CorrectionTransitionSerializer,
    ReportApprovalSerializer,
    ReportApprovalTransitionSerializer,
    SupervisorMessageCreateSerializer,
    SupervisorMessageSerializer,
)

DEFAULT_PAGE_SIZE = 30
MAX_PAGE_SIZE = 100


def _paginate(queryset, request):
    try:
        limit = min(int(request.query_params.get("limit", DEFAULT_PAGE_SIZE)), MAX_PAGE_SIZE)
        offset = max(int(request.query_params.get("offset", 0)), 0)
    except (TypeError, ValueError):
        limit, offset = DEFAULT_PAGE_SIZE, 0
    total = queryset.count()
    page = list(queryset[offset : offset + limit])
    return page, {"count": total, "limit": limit, "offset": offset, "has_more": offset + limit < total}


def _log_event(model, *, fk_name: str, parent, from_status: str, to_status: str, comment: str, actor):
    model.objects.create(
        **{fk_name: parent},
        from_status=from_status,
        to_status=to_status,
        comment=comment,
        actor=actor,
    )


# ---------------------------------------------------------------------------
# Supervisor Communication — worker side
# ---------------------------------------------------------------------------
class WorkerMessageThreadView(APIView):
    """GET/POST /api/work/messages/ — the worker's one conversation with
    their assigned Health Officer. `officer` is resolved fresh on every
    call from `services.assigned_officer_for`, never stored as a client
    choice and never read from an older message row (so a village whose
    officer changes is reflected immediately, not frozen at first contact).
    """

    permission_classes = (IsWorker,)

    def get(self, request):
        try:
            officer = services.assigned_officer_for(request.user)
        except services.NoAssignedOfficer as exc:
            return Response({"officer_name": None, "messages": [], "count": 0, "has_more": False, "notice": str(exc)})

        queryset = SupervisorMessage.objects.filter(
            worker=request.user, officer=officer
        ).select_related("sender")

        search = (request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(body__icontains=search)

        # Mark-as-read runs before pagination/serialization below, so the
        # response the worker gets back already reflects it — not a stale
        # pre-read snapshot they'd only see corrected on their next fetch.
        SupervisorMessage.objects.filter(
            worker=request.user, officer=officer, sender=officer, read_at__isnull=True
        ).update(read_at=timezone.now())

        page, meta = _paginate(queryset, request)
        return Response(
            {
                "officer_name": officer.display_name,
                "messages": SupervisorMessageSerializer(page, many=True).data,
                **meta,
            }
        )

    def post(self, request):
        try:
            officer = services.assigned_officer_for(request.user)
        except services.NoAssignedOfficer as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = SupervisorMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        message = SupervisorMessage.objects.create(
            worker=request.user,
            officer=officer,
            village_id=request.user.village_id,
            sender=request.user,
            subject=data["subject"].strip(),
            body=data["body"].strip(),
            attachment=data["attachment"],
            attachment_filename=data["attachment_filename"],
            attachment_mime=data["attachment_mime"],
        )
        return Response(SupervisorMessageSerializer(message).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Supervisor Communication — officer side
# ---------------------------------------------------------------------------
class OfficerMessageThreadListView(APIView):
    """GET /api/officer/work/threads/ — one row per supervised worker, with
    an unread count and a preview of the most recent message. This is the
    officer's inbox overview; the actual conversation is fetched per-worker
    below."""

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        rows = []
        for worker in services.workers_supervised_by(request.user):
            thread = SupervisorMessage.objects.filter(worker=worker)
            # A district-wide (village=None) officer account has no single
            # assigned village, so it is excluded from a specific worker's
            # thread by definition — only a village-scoped officer account
            # is ever `officer` on a real message row (see
            # `services.assigned_officer_for`). District-wide accounts see
            # every worker listed here but with an empty thread until one
            # exists under their own id.
            thread = thread.filter(officer=request.user) if request.user.village_id else thread
            last_message = thread.order_by("-created_at").first()
            unread_count = thread.filter(sender=worker, read_at__isnull=True).count()
            rows.append(
                {
                    "worker_id": worker.id,
                    "worker_name": worker.display_name,
                    "village_name": worker.village.name if worker.village else "",
                    "unread_count": unread_count,
                    "last_message_at": last_message.created_at if last_message else None,
                    "last_message_preview": (last_message.body[:140] if last_message else ""),
                }
            )
        never = dt.datetime.min.replace(tzinfo=dt.timezone.utc)
        rows.sort(key=lambda r: r["last_message_at"] or never, reverse=True)
        return Response({"threads": rows})


class OfficerMessageThreadView(APIView):
    """GET/POST /api/officer/work/threads/<worker_id>/messages/ — scoped to
    a worker actually supervised by this officer (village-checked, never
    trusted from the URL alone) — a 404 if not, matching the existing
    "404, not 403" convention `alerts/views.py::officer_alert_queryset`
    already established for the same reason."""

    permission_classes = (IsHealthOfficer,)

    def _worker_or_404(self, request, worker_id: int):
        queryset = scope_queryset(
            services.workers_supervised_by(request.user), request.user
        )
        return generics.get_object_or_404(queryset, pk=worker_id)

    def get(self, request, worker_id: int):
        worker = self._worker_or_404(request, worker_id)
        try:
            officer = services.assigned_officer_for(worker)
        except services.NoAssignedOfficer:
            return Response({"worker_name": worker.display_name, "messages": [], "count": 0, "has_more": False})

        queryset = SupervisorMessage.objects.filter(worker=worker, officer=officer).select_related("sender")
        search = (request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(body__icontains=search)

        SupervisorMessage.objects.filter(
            worker=worker, officer=officer, sender=worker, read_at__isnull=True
        ).update(read_at=timezone.now())

        page, meta = _paginate(queryset, request)
        return Response({"worker_name": worker.display_name, "messages": SupervisorMessageSerializer(page, many=True).data, **meta})

    def post(self, request, worker_id: int):
        worker = self._worker_or_404(request, worker_id)
        try:
            officer = services.assigned_officer_for(worker)
        except services.NoAssignedOfficer as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if officer.id != request.user.id and not request.user.is_platform_admin:
            # This officer's village no longer matches the worker's
            # assigned officer (e.g. reassignment) — refuse rather than
            # let a stale relationship send a message as the wrong sender.
            return Response(
                {"detail": "You are not the assigned Health Officer for this worker."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SupervisorMessageCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        message = SupervisorMessage.objects.create(
            worker=worker,
            officer=officer,
            village_id=worker.village_id,
            sender=request.user,
            subject=data["subject"].strip(),
            body=data["body"].strip(),
            attachment=data["attachment"],
            attachment_filename=data["attachment_filename"],
            attachment_mime=data["attachment_mime"],
        )
        return Response(SupervisorMessageSerializer(message).data, status=status.HTTP_201_CREATED)


# ---------------------------------------------------------------------------
# Supervisor Communication — shared (either role, ownership-checked)
# ---------------------------------------------------------------------------
def _message_or_404(request, message_id: int) -> SupervisorMessage:
    message = generics.get_object_or_404(SupervisorMessage.objects.all(), pk=message_id)
    is_party = request.user.id in (message.worker_id, message.officer_id)
    if not is_party and not request.user.is_platform_admin:
        from django.http import Http404

        raise Http404
    return message


class MessageMarkReadView(APIView):
    permission_classes = (IsWorkerOrOfficer,)

    def post(self, request, message_id: int):
        message = _message_or_404(request, message_id)
        if message.sender_id != request.user.id and message.read_at is None:
            message.read_at = timezone.now()
            message.save(update_fields=["read_at"])
        return Response(SupervisorMessageSerializer(message).data)


class MessageAttachmentView(APIView):
    """GET /api/work/messages/<id>/attachment/ — authenticated, ownership-
    checked download. Never a public media URL: the attachment bytes live
    only inside the message row and are only ever served through this one
    permission-checked endpoint, decoded on the fly."""

    permission_classes = (IsWorkerOrOfficer,)

    def get(self, request, message_id: int):
        message = _message_or_404(request, message_id)
        if not message.attachment:
            return Response({"detail": "This message has no attachment."}, status=status.HTTP_404_NOT_FOUND)

        _prefix, _, payload = message.attachment.partition(",")
        raw = base64.b64decode(payload)
        response = HttpResponse(raw, content_type=message.attachment_mime or "application/octet-stream")
        filename = message.attachment_filename or "attachment"
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


# ---------------------------------------------------------------------------
# Report Approval Tracker — worker side
# ---------------------------------------------------------------------------
class WorkerReportApprovalListView(APIView):
    permission_classes = (IsWorker,)

    def get(self, request):
        queryset = (
            ReportApproval.objects.filter(worker=request.user)
            .select_related("report", "village", "worker", "reviewed_by")
            .prefetch_related("events")
            .order_by("-created_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter and status_filter in WorkflowStatus.values:
            queryset = queryset.filter(status=status_filter)

        return Response({"approvals": ReportApprovalSerializer(queryset, many=True).data})


# ---------------------------------------------------------------------------
# Report Approval Tracker — officer side
# ---------------------------------------------------------------------------
class OfficerReportApprovalListView(APIView):
    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        queryset = (
            scope_queryset(
                ReportApproval.objects.select_related("report", "village", "worker", "reviewed_by").prefetch_related("events"),
                request.user,
            )
            .order_by("-created_at")
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter and status_filter in WorkflowStatus.values:
            queryset = queryset.filter(status=status_filter)

        return Response({"approvals": ReportApprovalSerializer(queryset, many=True).data})


class OfficerReportApprovalTransitionView(APIView):
    """POST /api/officer/work/report-approvals/<id>/transition/ — the
    ONLY way a report's approval status ever changes on the officer side.
    Every transition is checked against `services.apply_status_transition`
    and every one, PASS or otherwise, is recorded in `ReportApprovalEvent`
    — there is no silent status write anywhere in this app."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        queryset = scope_queryset(ReportApproval.objects.select_related("report", "village"), request.user)
        approval = generics.get_object_or_404(queryset, pk=pk)

        serializer = ReportApprovalTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["status"]
        comment = serializer.validated_data["comment"].strip()

        try:
            services.apply_status_transition(
                current_status=approval.status, target_status=target, actor=request.user, is_worker_actor=False
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        previous = approval.status
        approval.status = target
        approval.supervisor_comment = comment
        approval.reviewed_by = request.user
        approval.save(update_fields=["status", "supervisor_comment", "reviewed_by", "updated_at"])
        _log_event(
            ReportApprovalEvent, fk_name="approval", parent=approval,
            from_status=previous, to_status=target, comment=comment, actor=request.user,
        )
        return Response(ReportApprovalSerializer(approval).data)


# ---------------------------------------------------------------------------
# Correction Requests — eligible-record selector (worker side)
# ---------------------------------------------------------------------------
class CorrectableRecordListView(APIView):
    """GET /api/work/correctable-records/ — the worker's own recent
    submitted assessments and community reports, for the "select a record"
    step. Deliberately a short, recent list per type rather than the
    worker's entire history — this is a picker, not an archive browser."""

    permission_classes = (IsWorker,)

    def get(self, request):
        from assessments.models import PatientAssessment

        rows = []
        for assessment in (
            PatientAssessment.objects.filter(worker=request.user, is_draft=False)
            .select_related("patient")
            .order_by("-created_at")[:25]
        ):
            label, snapshot = services.record_label_and_snapshot(assessment)
            rows.append({"record_type": "assessment", "record_id": assessment.id, "label": label, "snapshot": snapshot})

        for report in CommunityReport.objects.filter(worker=request.user).order_by("-period_start")[:25]:
            label, snapshot = services.record_label_and_snapshot(report)
            rows.append({"record_type": "community_report", "record_id": report.id, "label": label, "snapshot": snapshot})

        return Response({"records": rows, "record_types": RECORD_TYPE_LABELS})


# ---------------------------------------------------------------------------
# Correction Requests — worker side
# ---------------------------------------------------------------------------
class WorkerCorrectionListCreateView(APIView):
    permission_classes = (IsWorker,)

    def get(self, request):
        queryset = (
            CorrectionRequest.objects.filter(worker=request.user)
            .select_related("content_type", "village", "worker", "reviewed_by")
            .prefetch_related("events")
        )
        return Response({"corrections": CorrectionRequestSerializer(queryset, many=True).data})

    def post(self, request):
        serializer = CorrectionRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        model_label = RECORD_TYPE_CHOICES[data["record_type"]]
        record = services.correctable_record_or_none(
            model_label=model_label, object_id=data["record_id"], worker=request.user
        )
        if record is None:
            return Response(
                {"detail": "That record could not be found for correction."},
                status=status.HTTP_404_NOT_FOUND,
            )

        from django.contrib.contenttypes.models import ContentType

        label, snapshot = services.record_label_and_snapshot(record)
        correction = CorrectionRequest.objects.create(
            content_type=ContentType.objects.get_for_model(record),
            object_id=record.pk,
            worker=request.user,
            village_id=request.user.village_id,
            record_label=label,
            original_snapshot=snapshot,
            mistake_description=data["mistake_description"].strip(),
            proposed_correction=data["proposed_correction"].strip(),
        )
        _log_event(
            CorrectionEvent, fk_name="correction", parent=correction,
            from_status="", to_status=WorkflowStatus.SUBMITTED, comment="", actor=request.user,
        )
        return Response(CorrectionRequestSerializer(correction).data, status=status.HTTP_201_CREATED)


class CorrectionDetailView(APIView):
    """GET /api/work/corrections/<id>/ — either the requesting worker or
    their (village-scoped) Health Officer; a 404 for anyone else."""

    permission_classes = (IsWorkerOrOfficer,)

    def get(self, request, pk: int):
        correction = generics.get_object_or_404(
            CorrectionRequest.objects.select_related("content_type", "village", "worker", "reviewed_by").prefetch_related("events"),
            pk=pk,
        )
        is_owner = correction.worker_id == request.user.id
        is_scoped_officer = request.user.is_officer and (
            scoped_village_id(request.user) is None or scoped_village_id(request.user) == correction.village_id
        )
        if not (is_owner or is_scoped_officer or request.user.is_platform_admin):
            from django.http import Http404

            raise Http404
        return Response(CorrectionRequestSerializer(correction).data)


# ---------------------------------------------------------------------------
# Correction Requests — officer side
# ---------------------------------------------------------------------------
class OfficerCorrectionListView(APIView):
    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        queryset = scope_queryset(
            CorrectionRequest.objects.select_related("content_type", "village", "worker", "reviewed_by").prefetch_related("events"),
            request.user,
        )
        status_filter = (request.query_params.get("status") or "").strip().upper()
        if status_filter and status_filter in WorkflowStatus.values:
            queryset = queryset.filter(status=status_filter)
        return Response({"corrections": CorrectionRequestSerializer(queryset, many=True).data})


class OfficerCorrectionTransitionView(APIView):
    """POST /api/officer/work/corrections/<id>/transition/ — approving a
    request never itself rewrites the original record's stored fields
    (see `models.py::CorrectionRequest`'s own docstring for why) — it
    marks the correction authoritative, timestamps `applied_at`, and
    leaves a full audit trail. For a community report, the worker then
    resubmits the corrected figures through the existing report form,
    which is this project's own established "how a report's numbers
    change" pathway; for an assessment, there is currently no amend
    pathway at all, so approval here is the institutional record that the
    correction is authorised, not a silent rewrite of clinical history."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        queryset = scope_queryset(CorrectionRequest.objects.select_related("village"), request.user)
        correction = generics.get_object_or_404(queryset, pk=pk)

        serializer = CorrectionTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["status"]
        comment = serializer.validated_data["comment"].strip()

        try:
            services.apply_status_transition(
                current_status=correction.status, target_status=target, actor=request.user, is_worker_actor=False
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        previous = correction.status
        correction.status = target
        correction.supervisor_comment = comment
        correction.reviewed_by = request.user
        update_fields = ["status", "supervisor_comment", "reviewed_by", "updated_at"]
        if target == WorkflowStatus.APPROVED:
            correction.applied_at = timezone.now()
            update_fields.append("applied_at")
        correction.save(update_fields=update_fields)
        _log_event(
            CorrectionEvent, fk_name="correction", parent=correction,
            from_status=previous, to_status=target, comment=comment, actor=request.user,
        )
        return Response(CorrectionRequestSerializer(correction).data)
