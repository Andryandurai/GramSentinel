from django.contrib import admin

from .models import (
    CorrectionEvent,
    CorrectionRequest,
    ReportApproval,
    ReportApprovalEvent,
    SupervisorMessage,
)


class ReportApprovalEventInline(admin.TabularInline):
    model = ReportApprovalEvent
    extra = 0
    readonly_fields = ("from_status", "to_status", "comment", "actor", "created_at")
    can_delete = False


@admin.register(ReportApproval)
class ReportApprovalAdmin(admin.ModelAdmin):
    list_display = ("report", "village", "worker", "status", "reviewed_by", "updated_at")
    list_filter = ("status", "village")
    inlines = [ReportApprovalEventInline]


class CorrectionEventInline(admin.TabularInline):
    model = CorrectionEvent
    extra = 0
    readonly_fields = ("from_status", "to_status", "comment", "actor", "created_at")
    can_delete = False


@admin.register(CorrectionRequest)
class CorrectionRequestAdmin(admin.ModelAdmin):
    list_display = ("record_label", "village", "worker", "status", "reviewed_by", "created_at")
    list_filter = ("status", "village")
    readonly_fields = ("content_type", "object_id", "original_snapshot")
    inlines = [CorrectionEventInline]


@admin.register(SupervisorMessage)
class SupervisorMessageAdmin(admin.ModelAdmin):
    list_display = ("worker", "officer", "sender", "subject", "created_at", "read_at")
    list_filter = ("village",)
    search_fields = ("subject", "body")
    readonly_fields = [f.name for f in SupervisorMessage._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False
