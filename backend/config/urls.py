from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path

#: Deliberately a hand-written string, not a template file: this is the only
#: place in the project that renders HTML rather than JSON, so adding a
#: templates/ directory and touching TEMPLATES/STATICFILES config for one
#: static page would be more machinery than the page is worth. No external
#: CDN, font, image, or script — everything the page needs is inline, so it
#: renders identically whether or not the request has network access to
#: anything but this server.
ROOT_STATUS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GramSentinel — Backend Service</title>
<style>
  :root { color-scheme: light; }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    background: #f4f7f6;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial,
      sans-serif;
    color: #1f2a28;
  }
  .card {
    width: 100%;
    max-width: 30rem;
    background: #ffffff;
    border: 1px solid #dde6e3;
    border-radius: 12px;
    padding: 2.25rem 2rem;
    box-shadow: 0 1px 2px rgba(16, 44, 38, 0.04), 0 8px 24px rgba(16, 44, 38, 0.06);
  }
  .eyebrow {
    margin: 0 0 0.35rem;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #4c7d72;
  }
  h1 {
    margin: 0;
    font-size: 1.7rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    color: #16302a;
  }
  .subtitle {
    margin: 0.4rem 0 1.5rem;
    font-size: 0.92rem;
    line-height: 1.45;
    color: #52655f;
  }
  .section-label {
    margin: 0 0 0.75rem;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #7c8d87;
  }
  .status-banner {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    padding: 0.7rem 0.9rem;
    margin-bottom: 1.25rem;
    background: #eaf6f1;
    border: 1px solid #cfe9df;
    border-radius: 8px;
    font-size: 0.9rem;
    font-weight: 600;
    color: #1e6e52;
  }
  .dot {
    width: 0.55rem;
    height: 0.55rem;
    border-radius: 50%;
    background: #2fa876;
    flex-shrink: 0;
  }
  .rows { border-top: 1px solid #eef2f1; }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.65rem 0;
    border-bottom: 1px solid #eef2f1;
    font-size: 0.88rem;
  }
  .row .name { color: #3c4a46; }
  .row .value {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: 600;
    color: #1e6e52;
    white-space: nowrap;
  }
  .row .value .dot { width: 0.4rem; height: 0.4rem; }
  footer {
    margin-top: 1.75rem;
    padding-top: 1.1rem;
    border-top: 1px solid #eef2f1;
    font-size: 0.75rem;
    line-height: 1.5;
    color: #93a29d;
    text-align: center;
  }
  footer strong { color: #5d6d68; font-weight: 600; }
</style>
</head>
<body>
  <main class="card">
    <p class="eyebrow">GramSentinel</p>
    <h1>GramSentinel</h1>
    <p class="subtitle">Multi-Agent Rural Health Early Warning System</p>

    <p class="section-label">Backend Service</p>
    <div class="status-banner">
      <span class="dot" aria-hidden="true"></span>
      <span>Service Running</span>
    </div>

    <div class="rows">
      <div class="row">
        <span class="name">Django REST API</span>
        <span class="value"><span class="dot" aria-hidden="true"></span>Online</span>
      </div>
      <div class="row">
        <span class="name">Health Check</span>
        <span class="value"><span class="dot" aria-hidden="true"></span>Online</span>
      </div>
      <div class="row">
        <span class="name">ASGI / Channels</span>
        <span class="value"><span class="dot" aria-hidden="true"></span>Enabled</span>
      </div>
    </div>

    <footer>
      <strong>GramSentinel Backend Service</strong><br>
      This is only a backend status page.
    </footer>
  </main>
</body>
</html>
"""


def root(_request):
    """Backend status landing page at "/".

    This is not, and must not become, the React frontend — the frontend is a
    separate Render Static Site with its own origin. This exists only so a
    browser or health probe hitting the backend's bare domain gets a clean
    status page instead of a 404 (Django has no route for "/" unless one is
    declared, since the frontend has always lived elsewhere) or bare JSON.
    """
    return HttpResponse(ROOT_STATUS_PAGE, content_type="text/html; charset=utf-8")


def health(_request):
    return JsonResponse(
        {
            "service": "GramSentinel",
            "description": (
                "Rural Healthcare Intelligence & Community Early-Warning Platform"
            ),
            "status": "ok",
            "data_notice": "Prototype. Synthetic / public / anonymised data only.",
            "disclaimer": (
                "Decision-support only. Does not replace professional medical "
                "care. Human approval required."
            ),
        }
    )


urlpatterns = [
    path("", root, name="root"),
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/auth/", include("users.urls")),
    path("api/", include("core.urls")),
    path("api/", include("patients.urls")),
    path("api/", include("assessments.urls")),
    path("api/", include("community.urls")),
    path("api/", include("alerts.urls")),
]
