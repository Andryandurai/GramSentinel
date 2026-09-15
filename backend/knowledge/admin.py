"""Section 42 of the task: authorized administrators can inspect and
activate/deactivate documents; ordinary Health Workers have no admin
access at all (Django admin's own staff/superuser gate already enforces
this — nothing extra was needed here), and there is deliberately no
"upload a document" action exposed to any non-staff role anywhere in this
app's REST API (see urls.py — no such endpoint exists)."""

from django.contrib import admin

from .models import KnowledgeChunk, KnowledgeDocument, RagQueryLog


class KnowledgeChunkInline(admin.TabularInline):
    model = KnowledgeChunk
    extra = 0
    fields = ("chunk_index", "section_title", "page_number", "embedding_model")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "organization",
        "authority",
        "topic",
        "document_type",
        "version",
        "active",
        "chunk_count",
    )
    list_filter = ("authority", "topic", "document_type", "active", "jurisdiction")
    search_fields = ("title", "organization", "subtopic")
    readonly_fields = ("checksum", "created_at", "updated_at")
    inlines = [KnowledgeChunkInline]
    actions = ["activate_documents", "deactivate_documents"]

    def chunk_count(self, obj: KnowledgeDocument) -> int:
        return obj.chunks.count()

    @admin.action(description="Activate selected documents")
    def activate_documents(self, request, queryset):
        queryset.update(active=True)

    @admin.action(description="Deactivate selected documents")
    def deactivate_documents(self, request, queryset):
        queryset.update(active=False)


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ("document", "chunk_index", "section_title", "page_number", "embedding_model")
    list_filter = ("document__topic", "embedding_model")
    search_fields = ("chunk_text", "section_title")
    readonly_fields = ("created_at", "updated_at")


@admin.register(RagQueryLog)
class RagQueryLogAdmin(admin.ModelAdmin):
    list_display = ("query_type", "user", "user_role", "topic", "grounded", "used_llm", "created_at")
    list_filter = ("query_type", "topic", "grounded", "used_llm")
    readonly_fields = [f.name for f in RagQueryLog._meta.fields]

    def has_add_permission(self, request) -> bool:
        return False
