"""Uniform API error envelope.

Section 33 of the spec: invalid login, missing fields, agent failure, LLM
failure, safety-engine failure and database failure must all surface as a
predictable payload rather than an HTML traceback.
"""

import logging

from django.db import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger("gramsentinel.api")


class AgentFailure(Exception):
    """Raised when an agent cannot produce a usable structured result."""


class SafetyEngineFailure(Exception):
    """Raised when the deterministic safety engine cannot complete.

    This is deliberately fatal for the request: a finding must never reach a
    human as 'verified' when verification did not actually run.
    """


def gramsentinel_exception_handler(exc, context):
    response = exception_handler(exc, context)

    if response is not None:
        response.data = {
            "error": True,
            "detail": response.data,
            "status_code": response.status_code,
        }
        return response

    if isinstance(exc, SafetyEngineFailure):
        logger.error("Safety engine failure: %s", exc)
        return Response(
            {
                "error": True,
                "detail": (
                    "Safety verification could not complete. No finding is "
                    "released without deterministic verification."
                ),
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if isinstance(exc, AgentFailure):
        logger.warning("Agent failure: %s", exc)
        return Response(
            {
                "error": True,
                "detail": f"An analysis agent failed: {exc}",
                "status_code": status.HTTP_502_BAD_GATEWAY,
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    if isinstance(exc, DatabaseError):
        logger.exception("Database error")
        return Response(
            {
                "error": True,
                "detail": "A database error occurred.",
                "status_code": status.HTTP_503_SERVICE_UNAVAILABLE,
            },
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return response
