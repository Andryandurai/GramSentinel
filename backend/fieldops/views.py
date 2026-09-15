"""Field Operations API — Field Visit Planner, Inspection Checklist
System, and Action Plan Management. Every list/detail/action view below
scopes through `users.scoping.scope_queryset` and returns 404 (not 403)
for a cross-village lookup, the same convention every other officer-facing
view in this project already uses.
"""

from __future__ import annotations

import datetime as dt

from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from users.permissions import IsHealthOfficer
from users.scoping import scope_queryset, scoped_village_id

from . import services
from .models import (
    ActionPlan,
    ActionPlanStatus,
    ChecklistItemTemplate,
    Department,
    FieldVisit,
    FieldVisitStatus,
    Inspection,
    InspectionAttachment,
    InspectionChecklistResponse,
    InspectionStatus,
    InspectionType,
    Priority,
    VISIT_OBJECTIVE_TEMPLATES,
)
from .serializers import (
    ActionPlanCreateSerializer,
    ActionPlanProgressInputSerializer,
    ActionPlanSerializer,
    DepartmentSerializer,
    FieldVisitCreateSerializer,
    FieldVisitOutcomeSerializer,
    FieldVisitSerializer,
    InspectionAttachmentCreateSerializer,
    InspectionAttachmentSerializer,
    InspectionChecklistResponseSerializer,
    InspectionChecklistResponseUpdateSerializer,
    InspectionCreateSerializer,
    InspectionSerializer,
    InspectionSummaryRemarksSerializer,
)

DUE_SOON_WINDOW_DAYS = 7


# ---------------------------------------------------------------------------
# Landing dashboard
# ---------------------------------------------------------------------------
class FieldOperationsSummaryView(APIView):
    """One aggregate read for every summary card across the landing view
    and the three section dashboards — real database counts, always
    scoped to the officer's own village (or every village for a
    district-wide account, same rule as everywhere else in this project)."""

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        today = timezone.localdate()
        due_soon_cutoff = today + dt.timedelta(days=DUE_SOON_WINDOW_DAYS)

        visits = scope_queryset(FieldVisit.objects.all(), request.user)
        inspections = scope_queryset(Inspection.objects.all(), request.user)
        action_plans = scope_queryset(ActionPlan.objects.all(), request.user)
        checklist_items = scope_queryset(
            InspectionChecklistResponse.objects.all(), request.user, field="inspection__village_id"
        )

        active_visits = visits.exclude(status__in=[FieldVisitStatus.COMPLETED, FieldVisitStatus.CANCELLED])
        active_plans = action_plans.exclude(status=ActionPlanStatus.COMPLETED)

        return Response(
            {
                "field_visits": {
                    "upcoming": visits.filter(status=FieldVisitStatus.SCHEDULED, visit_date__gte=today).count(),
                    "pending": visits.filter(status__in=[FieldVisitStatus.SCHEDULED, FieldVisitStatus.IN_PROGRESS]).count(),
                    "completed": visits.filter(status=FieldVisitStatus.COMPLETED).count(),
                    "overdue": active_visits.filter(visit_date__lt=today).count(),
                },
                "inspections": {
                    "draft": inspections.filter(status=InspectionStatus.DRAFT).count(),
                    "in_progress": inspections.filter(status=InspectionStatus.IN_PROGRESS).count(),
                    "completed": inspections.filter(status=InspectionStatus.COMPLETED).count(),
                    "needs_action_items": checklist_items.filter(status="NEEDS_ACTION").count(),
                    "failed_items": checklist_items.filter(status="FAILED").count(),
                },
                "action_plans": {
                    "open": action_plans.filter(status=ActionPlanStatus.PENDING).count(),
                    "in_progress": action_plans.filter(status=ActionPlanStatus.IN_PROGRESS).count(),
                    "due_soon": active_plans.filter(deadline__gte=today, deadline__lte=due_soon_cutoff).count(),
                    "overdue": active_plans.filter(deadline__lt=today).count(),
                    "completed": action_plans.filter(status=ActionPlanStatus.COMPLETED).count(),
                },
            }
        )


class FieldOperationsMetaView(APIView):
    """The form vocabulary this UI renders from — served by the backend so
    the form and the stored values can never drift apart (same rationale
    `community/views.py::ReportCategoryListView` already states)."""

    permission_classes = (IsHealthOfficer,)

    def get(self, request):
        village = request.user.village
        return Response(
            {
                "village_id": village.id if village else None,
                "village_name": village.name if village else None,
                "inspection_types": [{"value": v, "label": l} for v, l in InspectionType.choices],
                "priorities": [{"value": v, "label": l} for v, l in Priority.choices],
                "visit_objective_templates": list(VISIT_OBJECTIVE_TEMPLATES),
                "departments": DepartmentSerializer(Department.objects.filter(is_active=True), many=True).data,
                "officers": [
                    {"id": o.id, "name": o.display_name}
                    for o in services.officers_in_village(scoped_village_id(request.user))
                ],
                "staff": [
                    {"id": s.id, "name": s.display_name}
                    for s in services.staff_in_village(scoped_village_id(request.user))
                ],
            }
        )


def _filtered(queryset, request, *, fields: dict[str, str]):
    for query_param, orm_field in fields.items():
        value = request.query_params.get(query_param)
        if value:
            queryset = queryset.filter(**{orm_field: value})
    return queryset


# ---------------------------------------------------------------------------
# Field Visits
# ---------------------------------------------------------------------------
class FieldVisitListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsHealthOfficer,)

    def get_serializer_class(self):
        return FieldVisitCreateSerializer if self.request.method == "POST" else FieldVisitSerializer

    def get_queryset(self):
        queryset = scope_queryset(
            FieldVisit.objects.select_related("village", "assigned_officer", "created_by"), self.request.user
        )
        queryset = _filtered(
            queryset, self.request,
            fields={"village": "village_id", "officer": "assigned_officer_id", "status": "status", "priority": "priority", "date": "visit_date"},
        )
        search = (self.request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(objective__icontains=search)
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = FieldVisitCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        village = serializer.validated_data["village"]
        village_id = scoped_village_id(request.user)
        if village_id is not None and village.id != village_id:
            return Response({"detail": "You may only schedule visits in your own village."}, status=status.HTTP_403_FORBIDDEN)

        visit = serializer.save(created_by=request.user)
        return Response(FieldVisitSerializer(visit).data, status=status.HTTP_201_CREATED)


class FieldVisitDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsHealthOfficer,)
    serializer_class = FieldVisitSerializer

    def get_queryset(self):
        return scope_queryset(FieldVisit.objects.select_related("village", "assigned_officer", "created_by"), self.request.user)

    def update(self, request, *args, **kwargs):
        visit = self.get_object()
        if visit.status in (FieldVisitStatus.COMPLETED, FieldVisitStatus.CANCELLED):
            return Response({"detail": "A completed or cancelled visit cannot be edited."}, status=status.HTTP_400_BAD_REQUEST)
        # An explicit allowlist, not the raw request body — village,
        # assigned_officer and status can never be changed through this
        # endpoint (status has its own transition endpoint below).
        allowed_fields = {"visit_date", "start_time", "end_time", "objective", "priority", "notes"}
        for field, value in request.data.items():
            if field in allowed_fields:
                setattr(visit, field, value)
        visit.save()
        return Response(FieldVisitSerializer(visit).data)


class FieldVisitTransitionView(APIView):
    permission_classes = (IsHealthOfficer,)

    def _visit_or_404(self, request, pk):
        queryset = scope_queryset(FieldVisit.objects.select_related("village"), request.user)
        return generics.get_object_or_404(queryset, pk=pk)

    def post(self, request, pk: int, target: str):
        visit = self._visit_or_404(request, pk)
        try:
            services.apply_field_visit_transition(visit.status, target)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if target == FieldVisitStatus.COMPLETED:
            outcome = FieldVisitOutcomeSerializer(data=request.data)
            outcome.is_valid(raise_exception=True)
            for field, value in outcome.validated_data.items():
                setattr(visit, field, value)
            services.mark_visit_completed_fields(visit)

        visit.status = target
        visit.save()
        return Response(FieldVisitSerializer(visit).data)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
class InspectionListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsHealthOfficer,)

    def get_serializer_class(self):
        return InspectionCreateSerializer if self.request.method == "POST" else InspectionSerializer

    def get_queryset(self):
        queryset = scope_queryset(
            Inspection.objects.select_related("village", "officer").prefetch_related("responses__template_item", "attachments"),
            self.request.user,
        )
        queryset = _filtered(
            queryset, self.request,
            fields={"village": "village_id", "inspection_type": "inspection_type", "status": "status", "date": "inspection_date"},
        )
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = InspectionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        village = serializer.validated_data["village"]
        village_id = scoped_village_id(request.user)
        if village_id is not None and village.id != village_id:
            return Response({"detail": "You may only inspect your own village."}, status=status.HTTP_403_FORBIDDEN)

        inspection = serializer.save(officer=request.user)
        services.create_inspection_responses(inspection)
        return Response(InspectionSerializer(inspection).data, status=status.HTTP_201_CREATED)


class InspectionDetailView(generics.RetrieveAPIView):
    permission_classes = (IsHealthOfficer,)
    serializer_class = InspectionSerializer

    def get_queryset(self):
        return scope_queryset(
            Inspection.objects.select_related("village", "officer").prefetch_related("responses__template_item", "attachments"),
            self.request.user,
        )


class InspectionTransitionView(APIView):
    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int, target: str):
        queryset = scope_queryset(Inspection.objects.select_related("village"), request.user)
        inspection = generics.get_object_or_404(queryset, pk=pk)
        try:
            services.apply_inspection_transition(inspection.status, target)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        if target == InspectionStatus.COMPLETED:
            remarks = InspectionSummaryRemarksSerializer(data=request.data)
            remarks.is_valid(raise_exception=True)
            inspection.summary_remarks = remarks.validated_data["summary_remarks"]
            services.mark_inspection_completed_fields(inspection)

        inspection.status = target
        inspection.save()
        return Response(InspectionSerializer(inspection).data)


class InspectionResponseUpdateView(APIView):
    """POST /api/officer/inspections/<id>/responses/<response_id>/ — the
    ONLY way a checklist item's status/remarks changes. Refuses once the
    inspection itself is COMPLETED (task: "Lock checklist answers from
    ordinary editing" once completed)."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int, response_id: int):
        inspection_queryset = scope_queryset(Inspection.objects.all(), request.user)
        inspection = generics.get_object_or_404(inspection_queryset, pk=pk)
        if inspection.status == InspectionStatus.COMPLETED:
            return Response(
                {"detail": "This inspection is completed and its checklist can no longer be edited."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_obj = generics.get_object_or_404(
            InspectionChecklistResponse.objects.select_related("template_item"), pk=response_id, inspection=inspection
        )
        serializer = InspectionChecklistResponseUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        response_obj.status = serializer.validated_data["status"]
        response_obj.remarks = serializer.validated_data["remarks"]
        response_obj.save(update_fields=["status", "remarks", "updated_at"])
        return Response(InspectionChecklistResponseSerializer(response_obj).data)


class InspectionAttachmentListCreateView(APIView):
    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        queryset = scope_queryset(Inspection.objects.all(), request.user)
        inspection = generics.get_object_or_404(queryset, pk=pk)

        serializer = InspectionAttachmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attachment = InspectionAttachment.objects.create(
            inspection=inspection, file=data["file"], filename=data["filename"], mime=data["mime"], uploaded_by=request.user,
        )
        return Response(InspectionAttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


class InspectionAttachmentDownloadView(APIView):
    permission_classes = (IsHealthOfficer,)

    def get(self, request, pk: int, attachment_id: int):
        import base64

        from django.http import HttpResponse

        queryset = scope_queryset(InspectionAttachment.objects.select_related("inspection"), request.user, field="inspection__village_id")
        attachment = generics.get_object_or_404(queryset, pk=attachment_id, inspection_id=pk)

        _prefix, _, payload = attachment.file.partition(",")
        raw = base64.b64decode(payload)
        response = HttpResponse(raw, content_type=attachment.mime or "application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{attachment.filename or "attachment"}"'
        return response


# ---------------------------------------------------------------------------
# Action Plans
# ---------------------------------------------------------------------------
class ActionPlanListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsHealthOfficer,)

    def get_serializer_class(self):
        return ActionPlanCreateSerializer if self.request.method == "POST" else ActionPlanSerializer

    def get_queryset(self):
        queryset = scope_queryset(
            ActionPlan.objects.select_related("village", "department", "responsible_officer", "created_by").prefetch_related("progress_updates"),
            self.request.user,
        )
        queryset = _filtered(
            queryset, self.request,
            fields={"village": "village_id", "department": "department_id", "status": "status", "priority": "priority"},
        )
        search = (self.request.query_params.get("q") or "").strip()
        if search:
            queryset = queryset.filter(Q(title__icontains=search) | Q(problem_finding__icontains=search))
        return queryset

    def create(self, request, *args, **kwargs):
        serializer = ActionPlanCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        village = serializer.validated_data["village"]
        village_id = scoped_village_id(request.user)
        if village_id is not None and village.id != village_id:
            return Response({"detail": "You may only create action plans for your own village."}, status=status.HTTP_403_FORBIDDEN)

        progress = serializer.validated_data.get("progress_percentage", 0)
        action_plan = serializer.save(created_by=request.user, status=services.status_for_progress(progress))
        services.mark_action_plan_completion_fields(action_plan, previously_completed=False)
        action_plan.save(update_fields=["completed_at"])
        return Response(ActionPlanSerializer(action_plan).data, status=status.HTTP_201_CREATED)


class ActionPlanDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = (IsHealthOfficer,)
    serializer_class = ActionPlanSerializer

    def get_queryset(self):
        return scope_queryset(
            ActionPlan.objects.select_related("village", "department", "responsible_officer", "created_by").prefetch_related("progress_updates"),
            self.request.user,
        )

    def update(self, request, *args, **kwargs):
        action_plan = self.get_object()
        allowed_fields = {"title", "problem_finding", "department", "responsible_officer", "deadline", "required_resources", "priority", "notes"}
        payload = {k: v for k, v in request.data.items() if k in allowed_fields}
        if "department" in payload:
            payload["department_id"] = payload.pop("department")
        if "responsible_officer" in payload:
            payload["responsible_officer_id"] = payload.pop("responsible_officer")
        for field, value in payload.items():
            setattr(action_plan, field, value)
        action_plan.save()
        return Response(ActionPlanSerializer(action_plan).data)


class ActionPlanProgressView(APIView):
    """POST /api/officer/action-plans/<id>/progress/ — the only way
    `progress_percentage` (and, derived from it, `status`) ever changes.
    Every update, whatever the new value, is recorded in
    `ActionPlanProgressUpdate` — progress history is never overwritten."""

    permission_classes = (IsHealthOfficer,)

    def post(self, request, pk: int):
        queryset = scope_queryset(ActionPlan.objects.select_related("village"), request.user)
        action_plan = generics.get_object_or_404(queryset, pk=pk)

        serializer = ActionPlanProgressInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_percentage = serializer.validated_data["new_percentage"]
        note = serializer.validated_data["update_note"].strip()

        previous_percentage = action_plan.progress_percentage
        previously_completed = action_plan.status == ActionPlanStatus.COMPLETED

        action_plan.progress_percentage = new_percentage
        action_plan.status = services.status_for_progress(new_percentage)
        services.mark_action_plan_completion_fields(action_plan, previously_completed=previously_completed)
        action_plan.save(update_fields=["progress_percentage", "status", "completed_at", "updated_at"])

        from .models import ActionPlanProgressUpdate

        ActionPlanProgressUpdate.objects.create(
            action_plan=action_plan, previous_percentage=previous_percentage, new_percentage=new_percentage,
            update_note=note, updated_by=request.user,
        )
        return Response(ActionPlanSerializer(action_plan).data)
