from django.contrib import admin

from .models import (
    ActionPlan,
    ActionPlanProgressUpdate,
    ChecklistItemTemplate,
    Department,
    FieldVisit,
    Inspection,
    InspectionAttachment,
    InspectionChecklistResponse,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)


@admin.register(ChecklistItemTemplate)
class ChecklistItemTemplateAdmin(admin.ModelAdmin):
    list_display = ("category", "order", "text", "is_active")
    list_filter = ("category", "is_active")
    ordering = ("category", "order")


@admin.register(FieldVisit)
class FieldVisitAdmin(admin.ModelAdmin):
    list_display = ("village", "assigned_officer", "visit_date", "status", "priority")
    list_filter = ("status", "priority", "village")


class InspectionChecklistResponseInline(admin.TabularInline):
    model = InspectionChecklistResponse
    extra = 0
    readonly_fields = ("template_item",)


class InspectionAttachmentInline(admin.TabularInline):
    model = InspectionAttachment
    extra = 0
    readonly_fields = ("filename", "mime", "uploaded_by", "created_at")
    can_delete = False


@admin.register(Inspection)
class InspectionAdmin(admin.ModelAdmin):
    list_display = ("village", "inspection_type", "officer", "inspection_date", "status")
    list_filter = ("status", "inspection_type", "village")
    inlines = [InspectionChecklistResponseInline, InspectionAttachmentInline]


class ActionPlanProgressUpdateInline(admin.TabularInline):
    model = ActionPlanProgressUpdate
    extra = 0
    readonly_fields = ("previous_percentage", "new_percentage", "update_note", "updated_by", "created_at")
    can_delete = False


@admin.register(ActionPlan)
class ActionPlanAdmin(admin.ModelAdmin):
    list_display = ("title", "village", "department", "status", "priority", "progress_percentage", "deadline")
    list_filter = ("status", "priority", "department", "village")
    inlines = [ActionPlanProgressUpdateInline]
