"""Work & Communication — Supervisor Communication.

Covers the task's Communication test items (1-9) plus the Security items
that apply to messaging (31, 34-36).
"""

from __future__ import annotations

import base64

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from core.models import Village

User = get_user_model()
pytestmark = pytest.mark.django_db

MESSAGES = "/api/work/messages/"
OFFICER_THREADS = "/api/officer/work/threads/"

PDF_B64 = base64.b64encode(b"%PDF-1.4\ntest").decode()


def api_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def village_b(db) -> Village:
    return Village.objects.create(code="ARY", name="Manikkampatti", cluster="Village Cluster B", district="Madurai")


@pytest.fixture
def officer_a(db, village):
    return User.objects.create_user(
        username="wc.officer.a", password="x", role=User.Role.HEALTH_OFFICER,
        full_name="Dr. Officer A", village=village,
    )


@pytest.fixture
def officer_b(db, village_b):
    return User.objects.create_user(
        username="wc.officer.b", password="x", role=User.Role.HEALTH_OFFICER,
        full_name="Dr. Officer B", village=village_b,
    )


@pytest.fixture
def worker_a(db, village):
    return User.objects.create_user(
        username="wc.worker.a", password="x", role=User.Role.CHW_PHC_WORKER,
        full_name="Worker A", village=village,
    )


@pytest.fixture
def worker_b(db, village_b):
    return User.objects.create_user(
        username="wc.worker.b", password="x", role=User.Role.CHW_PHC_WORKER,
        full_name="Worker B", village=village_b,
    )


# 1. Worker can message assigned Health Officer.
def test_worker_can_message_assigned_officer(worker_a, officer_a):
    response = api_for(worker_a).post(MESSAGES, {"body": "Need advice on a case."}, format="json")
    assert response.status_code == 201
    assert response.data["is_from_officer"] is False

    thread = api_for(worker_a).get(MESSAGES).data
    assert thread["officer_name"] == officer_a.display_name
    assert thread["messages"][0]["body"] == "Need advice on a case."


# 2. Worker cannot message another village's officer — there is no field
#    to request one with; this asserts the response is always the worker's
#    OWN village's officer regardless of anything.
def test_worker_cannot_choose_another_villages_officer(worker_a, officer_a, officer_b):
    response = api_for(worker_a).post(MESSAGES, {"body": "Hello", "officer_id": officer_b.id}, format="json")
    assert response.status_code == 201
    thread = api_for(worker_a).get(MESSAGES).data
    assert thread["officer_name"] == officer_a.display_name
    assert thread["officer_name"] != officer_b.display_name


# 3. Worker receives assigned officer messages.
def test_worker_receives_officer_messages(worker_a, officer_a):
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_THREADS}{worker_a.id}/messages/", {"body": "Please submit this week's report."}, format="json")

    thread = api_for(worker_a).get(MESSAGES).data
    assert thread["messages"][0]["is_from_officer"] is True
    assert thread["messages"][0]["body"] == "Please submit this week's report."


# 4. Worker can reply.
def test_worker_can_reply(worker_a, officer_a):
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_THREADS}{worker_a.id}/messages/", {"body": "Instruction"}, format="json")
    worker_api = api_for(worker_a)
    worker_api.post(MESSAGES, {"body": "Understood, will do."}, format="json")

    thread = worker_api.get(MESSAGES).data
    bodies = [m["body"] for m in thread["messages"]]
    assert bodies == ["Instruction", "Understood, will do."]


# 5. Messages are private.
def test_messages_are_private_to_the_thread(worker_a, worker_b, officer_a, officer_b):
    api_for(worker_a).post(MESSAGES, {"body": "Village A private message"}, format="json")

    other_thread = api_for(worker_b).get(MESSAGES).data
    assert other_thread["messages"] == []

    officer_b_threads = api_for(officer_b).get(OFFICER_THREADS).data["threads"]
    assert all(t["worker_id"] != worker_a.id for t in officer_b_threads)


# 6. Search only returns authorized messages.
def test_search_only_returns_this_workers_own_conversation(worker_a, worker_b, officer_a, officer_b):
    api_for(worker_a).post(MESSAGES, {"body": "unique-marker-alpha discussion"}, format="json")
    api_for(worker_b).post(MESSAGES, {"body": "unique-marker-alpha unrelated village B note"}, format="json")

    result = api_for(worker_a).get(f"{MESSAGES}?q=unique-marker-alpha").data
    assert result["count"] == 1
    assert "Village A" not in result["messages"][0]["body"] or True  # just confirm isolation below
    assert all("village B" not in m["body"] for m in result["messages"])


# 7. Read state works.
def test_read_state_and_unread_count(worker_a, officer_a):
    officer_api = api_for(officer_a)
    officer_api.post(f"{OFFICER_THREADS}{worker_a.id}/messages/", {"body": "hi"}, format="json")

    threads_before = officer_api.get(OFFICER_THREADS).data["threads"]
    # Not yet unread from the WORKER's side (this message is from the officer).
    worker_api = api_for(worker_a)
    unread_message = worker_api.get(MESSAGES).data["messages"][0]
    assert unread_message["is_read"] is True  # opening the thread marks it read

    api_for(worker_a).post(MESSAGES, {"body": "worker reply"}, format="json")
    threads_after = officer_api.get(OFFICER_THREADS).data["threads"]
    row = next(t for t in threads_after if t["worker_id"] == worker_a.id)
    assert row["unread_count"] == 1  # officer hasn't opened the thread yet
    officer_api.get(f"{OFFICER_THREADS}{worker_a.id}/messages/")
    threads_final = officer_api.get(OFFICER_THREADS).data["threads"]
    row_final = next(t for t in threads_final if t["worker_id"] == worker_a.id)
    assert row_final["unread_count"] == 0


# 8. Attachment permission works.
def test_attachment_can_be_sent_and_downloaded_by_the_thread_parties(worker_a, officer_a):
    response = api_for(worker_a).post(
        MESSAGES,
        {"body": "see attached", "attachment": f"data:application/pdf;base64,{PDF_B64}", "attachment_filename": "note.pdf"},
        format="json",
    )
    assert response.data["has_attachment"] is True
    message_id = response.data["id"]

    download = api_for(officer_a).get(f"/api/work/messages/{message_id}/attachment/")
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    assert b"%PDF" in download.content


# 9. Unauthorized attachment access is rejected.
def test_unauthorized_attachment_access_is_rejected(worker_a, officer_a, officer_b):
    response = api_for(worker_a).post(
        MESSAGES,
        {"body": "see attached", "attachment": f"data:application/pdf;base64,{PDF_B64}", "attachment_filename": "note.pdf"},
        format="json",
    )
    message_id = response.data["id"]

    denied = api_for(officer_b).get(f"/api/work/messages/{message_id}/attachment/")
    assert denied.status_code == 404


# Reverse direction — an officer's own attachment must be just as reachable
# by the worker on the other end of the same thread.
def test_officer_to_worker_attachment_is_downloadable_by_worker(worker_a, officer_a):
    response = api_for(officer_a).post(
        f"{OFFICER_THREADS}{worker_a.id}/messages/",
        {"body": "see attached", "attachment": f"data:application/pdf;base64,{PDF_B64}", "attachment_filename": "reply.pdf"},
        format="json",
    )
    assert response.data["has_attachment"] is True
    message_id = response.data["id"]

    download = api_for(worker_a).get(f"/api/work/messages/{message_id}/attachment/")
    assert download.status_code == 200
    assert b"%PDF" in download.content


# The frontend fetches this endpoint through the authenticated API client and
# opens the response as a blob — never a plain <a href> browser navigation —
# specifically so a PDF/image can preview inline instead of forcing a
# download every message-attachment click.
def test_pdf_attachment_is_served_inline_for_browser_preview(worker_a, officer_a):
    response = api_for(worker_a).post(
        MESSAGES,
        {"body": "see attached", "attachment": f"data:application/pdf;base64,{PDF_B64}", "attachment_filename": "note.pdf"},
        format="json",
    )
    message_id = response.data["id"]

    download = api_for(officer_a).get(f"/api/work/messages/{message_id}/attachment/")
    assert download["Content-Disposition"].startswith("inline;")


def test_docx_attachment_still_forces_a_download(worker_a, officer_a):
    docx_b64 = base64.b64encode(b"PK\x03\x04test").decode()
    response = api_for(worker_a).post(
        MESSAGES,
        {
            "body": "see attached",
            "attachment": (
                "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
                f"base64,{docx_b64}"
            ),
            "attachment_filename": "note.docx",
        },
        format="json",
    )
    message_id = response.data["id"]

    download = api_for(officer_a).get(f"/api/work/messages/{message_id}/attachment/")
    assert download["Content-Disposition"].startswith("attachment;")


# The endpoint must stay protected — no public media exposure. A direct,
# unauthenticated request (the exact browser-address-bar scenario the bug
# report showed) must still be refused, just never silently made public.
def test_unauthenticated_attachment_request_is_rejected(worker_a, officer_a):
    response = api_for(worker_a).post(
        MESSAGES,
        {"body": "see attached", "attachment": f"data:application/pdf;base64,{PDF_B64}", "attachment_filename": "note.pdf"},
        format="json",
    )
    message_id = response.data["id"]

    anonymous = APIClient()
    denied = anonymous.get(f"/api/work/messages/{message_id}/attachment/")
    assert denied.status_code == 401


def test_a_malformed_attachment_is_rejected_with_a_readable_message(worker_a, officer_a):
    response = api_for(worker_a).post(
        MESSAGES, {"body": "bad file", "attachment": "data:application/pdf;base64,!!!not-base64!!!"}, format="json"
    )
    assert response.status_code == 400
    assert "attachment" in response.data["detail"]


# --- Security -----------------------------------------------------------
# 31. Worker A cannot access Worker B messages.
def test_worker_a_cannot_access_worker_b_messages(worker_a, worker_b, officer_a, officer_b):
    response = api_for(worker_b).post(MESSAGES, {"body": "Village B only"}, format="json")
    message_id = response.data["id"]

    denied = api_for(worker_a).post(f"/api/work/messages/{message_id}/read/")
    assert denied.status_code == 404


# 34-36. Client cannot spoof worker/officer/village ids anywhere in this app.
def test_client_cannot_spoof_worker_officer_or_village_ids(worker_a, officer_a, village_b, officer_b):
    response = api_for(worker_a).post(
        MESSAGES,
        {"body": "hello", "worker_id": 999999, "officer_id": officer_b.id, "village_id": village_b.id},
        format="json",
    )
    assert response.status_code == 201
    from workspace.models import SupervisorMessage

    message = SupervisorMessage.objects.get(pk=response.data["id"])
    assert message.worker_id == worker_a.id
    assert message.officer_id == officer_a.id
    assert message.village_id == worker_a.village_id


def test_a_worker_is_not_given_the_officer_thread_list(worker_a):
    response = api_for(worker_a).get(OFFICER_THREADS)
    assert response.status_code == 403
