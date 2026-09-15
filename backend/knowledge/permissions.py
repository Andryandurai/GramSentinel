"""Reuses the project's existing role permission classes rather than
inventing a parallel permission system — RAG endpoints are gated exactly
like the operational endpoints they sit next to."""

from users.permissions import IsHealthOfficer, IsWorker, IsWorkerOrOfficer

__all__ = ["IsWorker", "IsHealthOfficer", "IsWorkerOrOfficer"]
