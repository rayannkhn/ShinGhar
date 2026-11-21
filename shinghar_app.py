"""Start the ShinGhar demo:  .venv/bin/uvicorn shinghar_app:app --host 127.0.0.1 --port 8100

Same app as app.py (SailAb GLOF + ShinGhar pages), but "/" opens ShinGhar; the SailAb dashboard moves to /sailab.
app.py is unchanged and still opens the SailAb dashboard at "/".
"""
from fastapi.responses import RedirectResponse
from fastapi.routing import APIRoute

from webapp.main import create_app

app = create_app()
_sailab_dashboard = next(r for r in app.router.routes if isinstance(r, APIRoute) and r.path == "/")
app.router.routes.remove(_sailab_dashboard)
app.add_api_route("/sailab", _sailab_dashboard.endpoint, methods=["GET"], response_class=_sailab_dashboard.response_class)
app.add_api_route("/", lambda: RedirectResponse("/shinghar", status_code=307), methods=["GET"], include_in_schema=False)
