from html import escape

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from app.api.routes.student import _resolve_artifact_file_path
from app.db.database import get_db
from app.services.artifact_service import ArtifactService
from app.services.artifact_service import normalize_exam_session
from app.services.mock_lms_service import mock_lms_service
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

QUIZ_META = {
    "part-a": {"time_limit": "20 mins", "grade_max": "10.00", "safe_browser": True},
    "part-bc-questions": {"time_limit": "1 hour 10 mins", "grade_max": "80.00", "safe_browser": False},
}


def _get_logged_in_user(request: Request):
    token = request.cookies.get("mock_lms_session")
    return mock_lms_service.get_user_from_token(token) if token else None


def _require_user(request: Request):
    user = _get_logged_in_user(request)
    if not user:
        return None, RedirectResponse(url="/lms/login/index.php", status_code=302)
    return user, None


def _is_faculty(user: dict) -> bool:
    return user.get("role") == "faculty"


def _label_for_section(section_slug: str) -> str:
    mapping = {
        "cia-1-examination": "CIA-I",
        "cia-2-examination": "CIA-II",
        "cia-3-examination": "CIA-III",
    }
    return normalize_exam_session(mapping.get(section_slug, "CIA-I"))


def _topic_sections() -> list[dict]:
    return [
        {
            "slug": "cia-1-examination",
            "title": "CIA- I EXAMINATION",
            "items": [
                {"type": "quiz", "slug": "part-a", "label": "PART A"},
                {"type": "quiz", "slug": "part-bc-questions", "label": "PART B and C QUESTIONS"},
                {"type": "submission", "slug": "part-bc-answer-script", "label": "PART B and C ANSWER SCRIPT"},
            ],
        },
        {
            "slug": "cia-2-examination",
            "title": "CIA-II EXAMINATION",
            "items": [
                {"type": "quiz", "slug": "part-a", "label": "CIA-II PART A"},
                {"type": "quiz", "slug": "part-bc-questions", "label": "CIA-II PART B AND C QUESTIONS"},
                {"type": "submission", "slug": "part-bc-answer-script", "label": "CIA-II PART B AND C ANSWER SCRIPT"},
            ],
        },
        {
            "slug": "cia-3-examination",
            "title": "CIA-III EXAMINATION",
            "items": [
                {"type": "quiz", "slug": "part-a", "label": "CIA-III PART A"},
                {"type": "quiz", "slug": "part-bc-questions", "label": "CIA-III PART B AND C QUESTIONS"},
                {"type": "submission", "slug": "part-bc-answer-script", "label": "CIA-III PART B AND C ANSWER SCRIPT"},
            ],
        },
    ]


def _find_item(section_slug: str, item_slug: str):
    for section in _topic_sections():
        if section["slug"] == section_slug:
            for item in section["items"]:
                if item["slug"] == item_slug:
                    return section, item
    return None, None


def _layout(title: str, body: str, user=None, footer: bool = False, guest_login_link: bool = False) -> HTMLResponse:
    if user:
        identity = f"{escape(user.get('fullname', user['username']).upper())} {escape(user.get('register_number', ''))}".strip()
        home_link = "/lms/faculty/courses" if _is_faculty(user) else "/lms/my/courses.php"
        right = f"""
        <div class="m-user">
          <span>🔔</span>
          <span>💬</span>
          <a href="{home_link}">{identity}</a>
          <span class="m-avatar"></span>
          <a href="/lms/logout">⌄</a>
        </div>
        """
    else:
        right = '<div class="m-user"><a href="/lms/login/index.php">Log in</a></div>' if guest_login_link else '<div class="m-user"></div>'

    footer_html = (
        f"""
        <footer class="m-footer">
          <div class="m-footer-inner">
            <div class="m-footer-copy">You are logged in as <a href="#">{escape(user.get('fullname', user['username']))}</a>.</div>
            <div class="m-footer-links">
              <a href="/lms/logout">Log out</a>
              <span class="m-footer-sep">|</span>
              <a href="#">Data retention summary</a>
              <span class="m-footer-sep">|</span>
              <a href="#">Get the mobile app</a>
            </div>
          </div>
        </footer>
        """
        if footer and user
        else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --blue:#0f6cbf; --blue-deep:#0b4f8a; --text:#1f2d3d; --muted:#6d7a88; --line:#d9dfe7; --line-soft:#e7edf4; --bg:#eef3f8; --footer:#1f2937;
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; min-height:100vh; display:flex; flex-direction:column; font-family:"Segoe UI",Tahoma,Geneva,Verdana,sans-serif; color:var(--text); background:radial-gradient(circle at top, rgba(255,255,255,.92), transparent 34%), linear-gradient(180deg,#f7fbff 0%, var(--bg) 42%, #edf2f8 100%); }}
    a {{ color:var(--blue); text-decoration:none; }}
    a:hover {{ text-decoration:underline; }}
    .m-top {{ min-height:64px; background:rgba(255,255,255,.96); border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; padding:0 16px 0 2px; box-shadow:0 10px 26px rgba(15,23,42,.06); backdrop-filter:blur(16px); position:sticky; top:0; z-index:20; }}
    .m-page {{ flex:1 0 auto; display:flex; flex-direction:column; }}
    .m-left {{ display:flex; align-items:center; gap:22px; }}
    .m-menu {{ width:68px; height:60px; border-right:1px solid #eef2f6; background:linear-gradient(180deg,#f8fafc 0%,#eef3f8 100%); display:flex; align-items:center; justify-content:center; font-size:22px; }}
    .m-brand {{ font-size:18px; color:#111; font-weight:600; letter-spacing:.02em; }}
    .m-user {{ display:flex; align-items:center; gap:12px; color:#617084; font-size:16px; }}
    .m-avatar {{ width:42px; height:42px; border-radius:50%; background:#eef1f5; border:1px solid #dde3ea; display:inline-block; }}
    .m-shell {{ width:min(100%, 1560px); margin:0 auto; padding:32px 24px 0; }}
    .m-panel {{ background:linear-gradient(180deg,#ffffff 0%,#fbfdff 100%); border:1px solid #dce5f0; border-radius:28px; padding:34px 38px; margin-bottom:24px; box-shadow:0 18px 45px rgba(15,23,42,.08); }}
    .m-heading {{ font-weight:300; font-size:clamp(34px, 4vw, 52px); line-height:1.08; margin:0 0 14px; letter-spacing:-0.03em; }}
    .m-breadcrumbs {{ color:var(--muted); font-size:15px; line-height:1.8; max-width:1000px; }}
    .m-breadcrumbs a {{ font-weight:600; }}
    .m-home-grid {{ display:grid; grid-template-columns:minmax(250px,300px) minmax(0,1.7fr) minmax(250px,300px); gap:22px; align-items:start; }}
    .m-side,.m-home-main,.m-topics {{ background:rgba(255,255,255,.94); border:1px solid var(--line-soft); border-radius:26px; box-shadow:0 16px 40px rgba(15,23,42,.06); }}
    .m-side,.m-home-main {{ padding:24px 26px; }}
    .m-side-title,.m-home-main h2,.m-summary-title {{ font-size:30px; font-weight:300; margin:0 0 16px; }}
    .m-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
    .m-card-link {{ display:block; color:inherit; }}
    .m-card {{ border:1px solid var(--line); background:#fff; border-radius:22px; overflow:hidden; box-shadow:0 12px 28px rgba(15,23,42,.06); }}
    .m-card-cover {{ height:112px; background:linear-gradient(90deg,rgba(255,255,255,.10) 0 12%,transparent 12% 24%,rgba(255,255,255,.10) 24% 36%,transparent 36% 48%,rgba(255,255,255,.10) 48% 60%,transparent 60% 72%,rgba(255,255,255,.10) 72% 84%,transparent 84% 100%),linear-gradient(rgba(255,255,255,.08) 0 18%,transparent 18% 36%,rgba(255,255,255,.08) 36% 54%,transparent 54% 72%,rgba(255,255,255,.08) 72% 100%),linear-gradient(135deg,#5fa5ea,#77b7f6); }}
    .m-card-body {{ padding:14px 14px 18px; }}
    .m-topics {{ padding:8px 24px; }}
    .m-topic {{ padding:28px 8px 34px; border-bottom:1px solid #dde4eb; }}
    .m-topic:last-child {{ border-bottom:0; }}
    .m-topic-title {{ font-weight:300; color:var(--blue); font-size:30px; margin-bottom:26px; }}
    .m-resource {{ display:flex; align-items:flex-start; justify-content:space-between; gap:24px; margin:16px 0; padding:16px 18px; border:1px solid #ebf0f5; border-radius:18px; background:linear-gradient(180deg,#ffffff 0%,#f9fbfd 100%); }}
    .m-resource-main {{ display:flex; align-items:flex-start; gap:12px; }}
    .m-doc {{ width:24px; height:28px; border:1px solid #c4d9f1; background:linear-gradient(180deg,#f6fbff,#e9f2ff); position:relative; margin-top:2px; }}
    .m-doc:before {{ content:""; position:absolute; right:-1px; top:-1px; border-width:0 10px 10px 0; border-style:solid; border-color:transparent #dfeeff transparent transparent; }}
    .m-doc.quiz:after {{ content:"✓"; position:absolute; left:-5px; bottom:-3px; color:#f06a00; font-weight:700; font-size:18px; }}
    .m-doc.file {{ border-color:#ead7be; background:linear-gradient(180deg,#fff7ee,#f4e4d0); border-radius:0 0 12px 12px; }}
    .m-restricted {{ margin:14px 0 0 24px; font-size:15px; }}
    .m-badge {{ display:inline-block; background:#2aa0be; color:#001a24; font-weight:700; padding:2px 8px; margin-right:6px; font-size:13px; }}
    .m-quiz-title {{ font-size:40px; font-weight:300; margin:0 0 18px; }}
    .m-quiz-meta {{ text-align:center; padding:10px 0 26px; font-size:18px; line-height:2.7; }}
    .m-table,.m-status-table {{ width:100%; border-collapse:collapse; margin-top:6px; overflow:hidden; }}
    .m-table th,.m-table td {{ border-top:1px solid #d9dfe7; padding:16px; text-align:left; font-size:17px; vertical-align:top; background:#f7f7f7; }}
    .m-table th {{ background:#fff; font-size:18px; font-weight:700; }}
    .m-table tr.alt td {{ background:#d9eef9; }}
    .m-status-table td {{ border:1px solid #d9dfe7; padding:9px 10px; vertical-align:top; background:#f2f2f2; font-size:13px; }}
    .m-status-table td:first-child {{ width:140px; font-weight:700; background:#ececec; }}
    .ok {{ background:#d7f0d0 !important; }}
    .neutral {{ background:#e5e7eb !important; color:#374151; }}
    .m-final-grade {{ text-align:center; font-size:28px; font-weight:300; margin:34px 0 10px; }}
    .m-file-row {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap; }}
    .m-file-icon {{ width:10px; height:12px; background:#d93a3a; display:inline-block; }}
    .m-login-wrap {{ min-height:calc(100vh - 58px); display:flex; align-items:center; justify-content:center; padding:40px 24px; background:radial-gradient(circle at 20% 25%, rgba(255,255,255,.95), rgba(255,255,255,.78) 26%, transparent 56%), linear-gradient(90deg, rgba(242,246,250,.96), rgba(229,236,243,.94)); }}
    .m-login {{ width:100%; max-width:568px; background:#fff; border-radius:6px; padding:34px 54px; box-shadow:0 18px 48px rgba(42,63,88,.14); }}
    .m-login h1 {{ font-weight:300; font-size:50px; margin:10px 0 24px; }}
    .m-login input,.m-login textarea {{ width:100%; min-height:50px; border:1px solid #aeb8c2; border-radius:6px; padding:10px 18px; font-size:18px; margin-bottom:18px; }}
    .m-login button,.m-btn {{ border:0; padding:12px 20px; background:var(--blue); color:#fff; border-radius:4px; font-size:16px; cursor:pointer; }}
    .m-login-page {{ min-height:calc(100vh - 150px); display:flex; align-items:center; justify-content:center; padding:56px 24px; }}
    .m-login-card {{ width:100%; max-width:900px; background:#fff; border:1px solid #d8dde6; }}
    .m-login-card-head {{ padding:22px 28px 18px; text-align:center; font-size:38px; font-weight:300; border-bottom:1px solid #d8dde6; }}
    .m-login-card-body {{ display:grid; grid-template-columns:1fr 1fr; gap:36px; padding:46px 54px 24px; }}
    .m-login-left label {{ display:block; font-size:15px; margin-bottom:10px; color:#425466; }}
    .m-login-left input {{ width:100%; min-height:46px; border:1px solid #c8d1dc; padding:10px 16px; font-size:16px; margin-bottom:18px; }}
    .m-login-remember {{ display:flex; align-items:center; gap:10px; font-size:16px; color:#253647; margin:4px 0 22px; }}
    .m-login-remember input {{ width:18px; height:18px; min-height:auto; margin:0; }}
    .m-login-submit {{ width:100%; min-height:46px; background:#2377c9; font-size:18px; color:#fff !important; }}
    .m-login-side {{ font-size:18px; line-height:1.55; color:#23384d; }}
    .m-login-side a {{ display:inline-block; margin-bottom:18px; }}
    .m-login-guest {{ margin-top:28px; }}
    .m-login-guest-btn {{ width:100%; min-height:44px; background:#9ca9b8; color:#fff !important; font-size:16px; }}
    .m-dashboard-grid {{ display:grid; grid-template-columns:minmax(0,1.75fr) minmax(300px,380px); gap:22px; align-items:start; }}
    .m-dash-panel {{ background:rgba(255,255,255,.96); border:1px solid #d8dde6; border-radius:26px; padding:24px; box-shadow:0 16px 36px rgba(15,23,42,.06); }}
    .m-dash-title {{ font-size:26px; font-weight:300; margin:0 0 18px; }}
    .m-recent-header {{ display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:18px; }}
    .m-dash-cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:14px; }}
    .m-dash-card {{ border:1px solid #d8dde6; background:#fff; border-radius:20px; overflow:hidden; box-shadow:0 12px 26px rgba(15,23,42,.05); }}
    .m-dash-cover {{ height:92px; background:
      radial-gradient(circle at 8% 28%, rgba(255,255,255,.10) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 25% 30%, rgba(67,116,176,.22) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 41% 32%, rgba(255,255,255,.10) 0 11%, transparent 12% 100%),
      radial-gradient(circle at 59% 30%, rgba(255,255,255,.08) 0 8%, transparent 9% 100%),
      radial-gradient(circle at 78% 30%, rgba(67,116,176,.26) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 92% 33%, rgba(255,255,255,.10) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 15% 63%, rgba(255,255,255,.10) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 32% 63%, rgba(255,255,255,.10) 0 12%, transparent 13% 100%),
      radial-gradient(circle at 49% 63%, rgba(120,174,232,.20) 0 10%, transparent 11% 100%),
      radial-gradient(circle at 66% 61%, rgba(255,255,255,.08) 0 8%, transparent 9% 100%),
      radial-gradient(circle at 84% 66%, rgba(67,116,176,.28) 0 12%, transparent 13% 100%),
      linear-gradient(135deg,#7fc0ff,#66a8ee); }}
    .m-theme-purple .m-dash-cover {{ background:
      radial-gradient(circle at 50% -10%, rgba(255,255,255,.16) 0 28%, transparent 29% 100%),
      radial-gradient(circle at 22% 100%, rgba(255,255,255,.14) 0 30%, transparent 31% 100%),
      radial-gradient(circle at 78% 100%, rgba(255,255,255,.12) 0 28%, transparent 29% 100%),
      linear-gradient(135deg,#7a67ea,#6653d7); }}
    .m-theme-aqua .m-dash-cover {{ background:
      repeating-radial-gradient(circle at 50% -30%, rgba(36,132,142,.18) 0 8%, transparent 8% 13%),
      linear-gradient(180deg,#83ecec,#6fe0e0); }}
    .m-theme-teal-grid .m-dash-cover {{ background:
      linear-gradient(135deg, rgba(255,255,255,.08) 25%, transparent 25%) -16px 0/32px 32px,
      linear-gradient(225deg, rgba(255,255,255,.08) 25%, transparent 25%) -16px 0/32px 32px,
      linear-gradient(315deg, rgba(255,255,255,.08) 25%, transparent 25%) 0 0/32px 32px,
      linear-gradient(45deg, rgba(255,255,255,.08) 25%, transparent 25%) 0 0/32px 32px,
      linear-gradient(135deg,#11c3b0,#10a38f); }}
    .m-theme-blue-tri .m-dash-cover {{ background:
      linear-gradient(150deg, rgba(0,0,0,.06) 16%, transparent 16% 50%, rgba(0,0,0,.06) 50% 66%, transparent 66% 100%),
      linear-gradient(210deg, rgba(255,255,255,.08) 16%, transparent 16% 50%, rgba(255,255,255,.08) 50% 66%, transparent 66% 100%),
      linear-gradient(135deg,#2e97e8,#2379c4); }}
    .m-theme-hex .m-dash-cover {{ background:
      linear-gradient(120deg, rgba(255,255,255,.10) 25%, transparent 25%) 0 0/38px 38px,
      linear-gradient(60deg, rgba(255,255,255,.10) 25%, transparent 25%) 0 0/38px 38px,
      linear-gradient(135deg,#7ab8fb,#8cc5ff); }}
    .m-dash-body {{ padding:16px 18px; }}
    .m-dash-term {{ font-size:14px; color:#526273; margin-bottom:8px; }}
    .m-dash-name {{ font-size:15px; color:#213447; line-height:1.35; min-height:40px; }}
    .m-dash-side {{ display:grid; gap:20px; }}
    .m-side-box {{ background:rgba(255,255,255,.96); border:1px solid #d8dde6; border-radius:22px; padding:22px; box-shadow:0 14px 30px rgba(15,23,42,.05); }}
    .m-side-box h3 {{ margin:0 0 18px; font-size:24px; font-weight:300; }}
    .m-side-toolbar {{ display:flex; justify-content:space-between; gap:10px; margin-bottom:20px; }}
    .m-side-btn {{ min-width:74px; min-height:46px; border:1px solid #b8c5d3; background:#fff; color:#5c6d7f; display:flex; align-items:center; justify-content:center; font-size:22px; }}
    .m-side-empty {{ min-height:160px; display:flex; flex-direction:column; align-items:center; justify-content:center; color:#8a98a8; text-align:center; font-size:18px; border-top:1px solid #e2e8f0; }}
    .m-side-link {{ display:block; margin:10px 0; font-size:18px; }}
    .m-user-line {{ display:flex; align-items:center; gap:10px; font-size:18px; }}
    .m-user-dot {{ width:18px; height:18px; border-radius:50%; background:#e5e7eb; border:1px solid #d5dbe3; display:inline-block; }}
    .m-card-link:hover .m-dash-card {{ box-shadow:0 8px 22px rgba(15,23,42,.10); }}
    .m-customize-bar {{ display:flex; justify-content:flex-end; margin-bottom:18px; }}
    .m-customize-btn {{ min-height:44px; padding:0 18px; border:1px solid #c9d3de; background:#eef2f6; color:#334155; font-size:16px; }}
    .m-btn.secondary {{ background:#ccd3db; color:#1e2e3d; }}
    .m-grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
    .m-faculty-list {{ display:grid; gap:12px; }}
    .m-sub-card {{ border:1px solid var(--line); background:#fff; padding:16px; }}
    .m-grade-grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; align-items:start; }}
    .m-grade-card {{ background:linear-gradient(180deg,#ffffff 0%,#f8fbff 100%); border:1px solid #d8e4f0; border-radius:18px; overflow:hidden; box-shadow:0 12px 30px rgba(15,23,42,.10); transition:transform .2s ease, box-shadow .2s ease, border-color .2s ease; }}
    .m-grade-card:hover {{ transform:translateY(-3px); box-shadow:0 18px 40px rgba(15,23,42,.14); border-color:#bfd4ea; }}
    .m-grade-preview {{ height:128px; background:radial-gradient(circle at top left, rgba(15,108,191,.16), transparent 48%), linear-gradient(135deg,#eff6ff 0%,#dbeafe 52%,#e0f2fe 100%); border-bottom:1px solid #d8e4f0; display:flex; align-items:center; justify-content:center; overflow:hidden; position:relative; }}
    .m-grade-preview:after {{ content:"Submitted Paper"; position:absolute; left:12px; bottom:10px; padding:5px 9px; border-radius:999px; background:rgba(255,255,255,.82); color:#0f4c81; font-size:11px; font-weight:700; letter-spacing:.06em; text-transform:uppercase; backdrop-filter:blur(8px); }}
    .m-grade-preview object,.m-grade-preview iframe,.m-grade-preview img {{ width:100%; height:100%; border:0; object-fit:cover; }}
    .m-grade-empty {{ font-size:48px; color:#94a3b8; }}
    .m-grade-body {{ padding:14px; display:flex; flex-direction:column; gap:10px; }}
    .m-grade-top {{ display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }}
    .m-grade-title {{ font-size:16px; font-weight:700; line-height:1.25; color:#0f172a; }}
    .m-grade-status {{ display:inline-flex; align-items:center; padding:6px 12px; border-radius:999px; font-size:11px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .m-grade-status.pending {{ background:#fff3cd; color:#9a6700; }}
    .m-grade-status.done {{ background:#d1fae5; color:#047857; }}
    .m-grade-meta {{ color:#586579; font-size:13px; line-height:1.5; }}
    .m-grade-meta strong {{ color:#0f4c81; }}
    .m-grade-actions {{ display:flex; gap:8px; margin-top:6px; }}
    .m-btn.ghost {{ background:#fff; color:var(--blue); border:1px solid #bcd1e6; text-align:center; box-shadow:inset 0 0 0 1px rgba(255,255,255,.35); }}
    .m-grade-actions .m-btn {{ flex:1; min-height:38px; font-size:14px; font-weight:700; border-radius:12px; }}
    .m-grade-actions .m-btn:not(.ghost) {{ background:linear-gradient(135deg,#0f6cbf,#0ea5e9); box-shadow:0 10px 20px rgba(14,165,233,.20); }}
    .m-grade-actions .m-btn:not(.ghost):hover {{ filter:brightness(1.03); }}
    .m-grade-form {{ display:grid; gap:10px; margin-top:6px; }}
    .m-grade-row {{ display:grid; grid-template-columns:1fr 1fr; gap:10px; }}
    .m-empty-panel {{ border:1px dashed #bfd1e5; border-radius:22px; padding:54px 28px; text-align:center; color:#5c6f84; background:linear-gradient(180deg,#f9fbfe 0%,#f3f7fc 100%); box-shadow:inset 0 1px 0 rgba(255,255,255,.8); }}
    .m-empty-panel:before {{ content:"No submissions"; display:block; width:max-content; margin:0 auto 18px; padding:8px 14px; border-radius:999px; background:#e7f1fb; color:#0f6cbf; font-size:12px; font-weight:700; letter-spacing:.08em; text-transform:uppercase; }}
    .m-grade-name {{ color:#334155; font-size:13px; }}
    .m-grade-modal-backdrop {{ position:fixed; inset:0; background:radial-gradient(circle at top, rgba(14,165,233,.16), transparent 28%), rgba(15,23,42,.58); display:none; align-items:center; justify-content:center; z-index:2000; padding:24px; backdrop-filter:blur(8px); }}
    .m-grade-modal-backdrop.open {{ display:flex; }}
    .m-grade-modal {{ width:100%; max-width:600px; background:linear-gradient(180deg,#ffffff 0%,#f8fbff 100%); border-radius:24px; box-shadow:0 28px 80px rgba(15,23,42,.30); overflow:hidden; border:1px solid rgba(191,212,234,.8); }}
    .m-grade-modal-head {{ padding:22px 24px; border-bottom:1px solid #dbe7f3; display:flex; align-items:flex-start; justify-content:space-between; gap:16px; background:linear-gradient(135deg,#eef6ff 0%,#f8fbff 100%); }}
    .m-grade-modal-title {{ font-size:28px; font-weight:300; margin:0; color:#0f172a; }}
    .m-grade-modal-sub {{ color:#64748b; font-size:14px; margin-top:8px; line-height:1.5; }}
    .m-grade-modal-body {{ padding:24px; }}
    .m-grade-modal-close {{ border:0; background:#ffffff; color:#334155; width:40px; height:40px; border-radius:999px; cursor:pointer; font-size:20px; box-shadow:0 6px 18px rgba(15,23,42,.08); }}
    .m-grade-modal .m-grade-form {{ margin-top:0; }}
    .m-grade-modal .m-btn {{ width:auto; }}
    .m-grade-modal input {{ width:100%; min-height:50px; border:1px solid #cbd5e1; border-radius:14px; padding:12px 14px; font-size:15px; background:#fff; }}
    .m-grade-modal input:focus {{ outline:none; border-color:#0ea5e9; box-shadow:0 0 0 4px rgba(14,165,233,.12); }}
    .m-grade-modal .m-btn {{ min-height:48px; border-radius:14px; background:linear-gradient(135deg,#0f6cbf,#0ea5e9); font-size:15px; font-weight:700; box-shadow:0 14px 26px rgba(14,165,233,.22); }}
    .m-grade-modal-actions {{ display:grid; grid-template-columns:1fr; gap:12px; margin-top:4px; }}
    .m-grade-modal-actions.reaccess {{ grid-template-columns:1fr 1fr; }}
    .m-grade-modal .m-btn.m-remove {{ background:linear-gradient(135deg,#ef4444,#dc2626); box-shadow:0 14px 26px rgba(239,68,68,.22); }}
    .m-grade-modal .m-btn.is-idle {{ background:#dbe5ef !important; color:#7b8794 !important; box-shadow:none !important; cursor:not-allowed; }}
    .m-focus-shell {{ width:min(100%, 1280px); margin:0 auto; }}
    .m-wide-shell {{ width:min(100%, 1640px); max-width:1640px; margin:0 auto; }}
    .m-focus-shell .m-panel:first-child {{ background:linear-gradient(135deg,#ffffff 0%,#f7fbff 100%); }}
    .m-answer-panel {{ padding:34px 38px; }}
    .m-answer-title {{ font-size:24px; font-weight:400; margin-bottom:28px; }}
    .m-answer-section {{ font-size:18px; margin-bottom:18px; }}
    .m-answer-table td {{ font-size:16px; padding:13px 14px; }}
    .m-answer-table td:first-child {{ width:190px; font-size:15px; }}
    .m-answer-feedback-title {{ font-size:30px; font-weight:300; margin:54px 0 18px; }}
    .m-footer {{ margin-top:auto; background:linear-gradient(135deg,#1f2937 0%,#111827 100%); color:#e5edf7; min-height:92px; box-shadow:0 -1px 0 rgba(255,255,255,.08); }}
    .m-footer-inner {{ width:min(100%, 1640px); margin:0 auto; padding:18px 24px 22px; display:flex; align-items:center; justify-content:space-between; gap:16px; flex-wrap:wrap; font-size:15px; line-height:1.7; }}
    .m-footer-copy {{ color:#dce6f3; }}
    .m-footer-links {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; }}
    .m-footer-sep {{ color:#66758a; }}
    .m-footer a {{ color:#ffffff; text-decoration:none; font-weight:600; }}
    .m-footer a:hover {{ text-decoration:underline; }}
    @media (max-width:1480px) {{ .m-home-grid {{ grid-template-columns:minmax(220px,280px) minmax(0,1fr) minmax(220px,280px); }} .m-grade-grid {{ grid-template-columns:repeat(3,minmax(0,1fr)); }} }}
    @media (max-width:1320px) {{ .m-dashboard-grid {{ grid-template-columns:minmax(0,1fr) 340px; }} .m-dash-cards {{ grid-template-columns:repeat(2,minmax(220px,1fr)); }} }}
    @media (max-width:1180px) {{ .m-home-grid {{ grid-template-columns:1fr; }} .m-dashboard-grid,.m-grid-2,.m-grade-row,.m-login-card-body {{ grid-template-columns:1fr; }} .m-grade-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} .m-shell {{ padding-top:26px; }} }}
    @media (max-width:900px) {{ .m-shell {{ padding:22px 18px 0; }} .m-panel,.m-answer-panel,.m-side,.m-home-main,.m-topics,.m-dash-panel,.m-side-box {{ padding:22px 20px; border-radius:20px; }} .m-top {{ padding-right:10px; }} .m-user {{ gap:8px; font-size:14px; }} .m-breadcrumbs {{ font-size:14px; }} .m-resource {{ flex-direction:column; align-items:flex-start; gap:12px; }} .m-grade-grid,.m-dash-cards {{ grid-template-columns:1fr; }} .m-footer-inner {{ padding:16px 18px 18px; }} }}
    @media (max-width:640px) {{ .m-shell {{ padding:18px 12px 0; }} .m-panel,.m-answer-panel,.m-side,.m-home-main,.m-topics,.m-dash-panel,.m-side-box {{ padding:18px 16px; border-radius:18px; }} .m-menu {{ width:56px; height:56px; }} .m-left {{ gap:14px; }} .m-brand {{ font-size:16px; }} .m-heading {{ font-size:30px; }} .m-summary-title,.m-side-title,.m-home-main h2 {{ font-size:24px; }} .m-login-card-head {{ font-size:26px; }} .m-login-card-body {{ padding:28px 20px 20px; gap:24px; }} .m-topic-title,.m-quiz-title {{ font-size:28px; }} .m-footer-inner {{ font-size:14px; padding:16px 12px 18px; }} }}
  </style>
</head>
<body>
  <div class="m-top">
    <div class="m-left">
      <div class="m-menu">≡</div>
      <div class="m-brand"><a style="color:#111;text-decoration:none;" href="/lms/site-home">SEC</a></div>
    </div>
    {right}
  </div>
  <main class="m-page">
    {body}
  </main>
  {footer_html}
</body>
</html>"""
    return HTMLResponse(html)


def _guest_home() -> HTMLResponse:
    body = f"""
    <div class="m-shell">
      <div class="m-panel">
        <div class="m-heading">Saveetha Engineering College</div>
        <div class="m-breadcrumbs"><a href="/lms/site-home">Home</a></div>
      </div>
      <div class="m-home-grid">
        <aside class="m-side"><div class="m-side-title">Navigation</div><div><a href="/lms/site-home">Home</a></div><div><a href="/lms/login/index.php">Log in</a></div></aside>
        <section class="m-home-main"><h2>Site announcements</h2><div style="background:#d4eef7;padding:18px 24px;border-radius:4px;">There are no discussion topics yet in this forum</div></section>
        <aside class="m-side"><div class="m-side-title">Online users</div><div style="text-align:center;font-size:16px;">{mock_lms_service.get_online_user_count()} online users (last 5 minutes)</div></aside>
      </div>
    </div>
    """
    return _layout("SEC", body, guest_login_link=True)


def _login_page(error: bool = False) -> HTMLResponse:
    error_html = '<div style="background:#fce6e5;color:#9b1c1c;border:1px solid #efb7b4;padding:14px 16px;border-radius:6px;margin-bottom:18px;">Invalid LMS username or password. Please try again.</div>' if error else ""
    body = f"""
    <div class="m-login-page">
      <div class="m-login-card">
        <div class="m-login-card-head">Saveetha Engineering College</div>
        <div class="m-login-card-body">
          <div class="m-login-left">
            {error_html}
            <form method="post" action="/lms/login">
              <input name="username" value="{escape(str(mock_lms_service.default_users[0]['username']))}" placeholder="Username" />
              <input name="password" type="password" value="{escape(str(mock_lms_service.default_users[0]['password']))}" placeholder="Password" />
              <label class="m-login-remember"><input type="checkbox" /> Remember username</label>
              <button class="m-login-submit" type="submit">Log in</button>
            </form>
          </div>
          <div class="m-login-side">
            <a href="#">Forgotten your username or password?</a>
            <div>Cookies must be enabled in your browser</div>
            <div class="m-login-guest">
              <div style="margin-bottom:14px;">Some courses may allow guest access</div>
              <button type="button" class="m-login-guest-btn">Log in as a guest</button>
            </div>
          </div>
        </div>
      </div>
    </div>
    """
    return _layout("Log in to SEC", body)


def _courses_page(user: dict) -> HTMLResponse:
    cards = []
    base = "/lms/faculty/course" if _is_faculty(user) else "/lms/course"
    title = "Faculty courses" if _is_faculty(user) else "My courses"
    courses = mock_lms_service.get_courses()
    course_themes = {
        "19AI404": "m-theme-blue",
        "19AI405": "m-theme-purple",
        "19AI505": "m-theme-aqua",
        "19AI411": "m-theme-teal-grid",
        "19AI512C": "m-theme-blue-tri",
    }
    fallback_themes = ["m-theme-blue", "m-theme-purple", "m-theme-aqua", "m-theme-teal-grid", "m-theme-blue-tri", "m-theme-hex"]
    for course in courses[:6]:
        theme_class = course_themes.get(course["course_code"]) or fallback_themes[len(cards) % len(fallback_themes)]
        cards.append(
            f'<a class="m-card-link" href="{base}/{escape(course["course_code"])}">'
            f'<article class="m-dash-card {theme_class}"><div class="m-dash-cover"></div><div class="m-dash-body">'
            f'<div class="m-dash-term">{escape(course.get("category","Course"))}</div>'
            f'<div class="m-dash-name">{escape(course["course_short_name"])}-{escape(course["course_name"])}</div>'
            f'</div></article></a>'
        )
    primary_name = escape(user.get("fullname", user["username"]))
    primary_reg = escape(user.get("register_number", ""))
    body = f"""
    <div class="m-shell">
      <div class="m-customize-bar"><button type="button" class="m-customize-btn">Customise this page</button></div>
      <div class="m-dashboard-grid">
        <section class="m-dash-panel">
          <div class="m-recent-header">
            <h2 class="m-dash-title">Recently accessed courses</h2>
            <div style="display:flex; gap:0;">
              <button class="m-side-btn" type="button">&#8249;</button>
              <button class="m-side-btn" type="button">&#8250;</button>
            </div>
          </div>
          <div class="m-dash-cards">{''.join(cards)}</div>
        </section>
        <aside class="m-dash-side">
          <section class="m-side-box">
            <h3>Timeline</h3>
            <div class="m-side-toolbar">
              <button class="m-side-btn" type="button">&#9716;</button>
              <button class="m-side-btn" type="button">&#8801;</button>
            </div>
            <div class="m-side-empty">
              <div style="font-size:46px; line-height:1;">&#128196;</div>
              <div style="margin-top:14px;">No upcoming activities due</div>
            </div>
          </section>
          <section class="m-side-box">
            <h3>Private files</h3>
            <a class="m-side-link" href="#">{escape(courses[0]["course_short_name"])} notes.pdf</a>
            <a class="m-side-link" href="#">Manage private files...</a>
          </section>
          <section class="m-side-box">
            <h3>Online users</h3>
            <div style="font-size:18px; margin-bottom:16px;">1 online user (last 5 minutes)</div>
            <div class="m-user-line"><span class="m-user-dot"></span><a href="#">{primary_name} {primary_reg}</a></div>
          </section>
          <section class="m-side-box">
            <h3>Latest badges</h3>
            <div style="font-size:18px; color:#5c6b7b;">You have no badges to display</div>
          </section>
          <section class="m-side-box">
            <h3>Upcoming events</h3>
            <div style="font-size:18px; color:#5c6b7b; line-height:1.6;">
              There are no upcoming events<br>
              <a class="m-side-link" href="#" style="margin-top:10px;">Go to calendar...</a>
            </div>
          </section>
        </aside>
      </div>
    </div>
    """
    return _layout(title, body, user=user)


def _course_topics_page(user: dict, course: dict, faculty: bool) -> HTMLResponse:
    topics = []
    prefix = "/lms/faculty/course" if faculty else "/lms/course"
    for section in _topic_sections():
        items = []
        for item in section["items"]:
            href = f"{prefix}/{course['course_code']}/{section['slug']}/{item['slug']}"
            items.append(f'<div class="m-resource"><div class="m-resource-main"><span class="m-doc {"quiz" if item["type"]=="quiz" else "file"}"></span><div><a href="{href}">{escape(item["label"])}</a></div></div><div><input type="checkbox"></div></div>')
            if item["type"] == "submission":
                items.append('<div class="m-restricted"><span class="m-badge">Restricted</span>Not available unless: Matching ip-address/subnet. (Your IP:172.17.90.126)</div>')
        topics.append(f'<section class="m-topic"><div class="m-topic-title">{escape(section["title"])}</div>{"".join(items)}</section>')
    body = f'<div class="m-shell"><div class="m-topics">{"".join(topics)}</div></div>'
    return _layout(course["course_name"], body, user=user)


def _quiz_page(user: dict, course: dict, section: dict, item: dict, faculty: bool) -> HTMLResponse:
    meta = QUIZ_META[item["slug"]]
    body = f"""
    <div class="m-shell">
      <div class="m-panel">
        <div class="m-heading">{escape(course['course_code'])}-{escape(course['course_name'])}</div>
        <div class="m-breadcrumbs"><a href="/lms/site-home">Dashboard</a> / <a href="{"/lms/faculty/courses" if faculty else "/lms/my/courses.php"}">My courses</a> / <a href="{"/lms/faculty/course" if faculty else "/lms/course"}/{course["course_code"]}">{escape(course["course_code"])}</a> / {escape(section["title"])} / {escape(item["label"])}</div>
      </div>
      <div class="m-panel">
        <div class="m-quiz-title">{escape(item["label"])}</div>
        <div class="m-quiz-meta">
          <div>Attempts allowed: 2</div>
          <div>This quiz closed on Wednesday, 27 September 2023, 11:00 PM</div>
          {'<div>This quiz has been configured so that students may only attempt it using the Safe Exam Browser.</div>' if meta['safe_browser'] else ''}
          <div>Time limit: {meta['time_limit']}</div>
          <div>Grading method: Highest grade</div>
        </div>
        <div class="m-summary-title">Summary of your previous attempts</div>
        <table class="m-table">
          <thead><tr><th>Attempt</th><th>State</th><th>Grade / {meta['grade_max']}</th><th>Review</th></tr></thead>
          <tbody><tr><td>1</td><td>Finished<br>Submitted Friday, 28 April 2023, 11:39 AM</td><td>0.00</td><td><a href="#">Review</a></td></tr></tbody>
        </table>
        <div class="m-final-grade">Your final grade for this quiz is 0.00/{meta['grade_max']}.</div>
      </div>
    </div>
    """
    return _layout(item["label"], body, user=user)


def _student_submission_page(user: dict, course: dict, section: dict, item: dict) -> HTMLResponse:
    exam_session = _label_for_section(section["slug"])
    submissions = mock_lms_service.get_submissions_for_course(course["course_code"], exam_session=exam_session)
    latest = next(
        (
            s for s in reversed(submissions)
            if s.get("student_username") == user["username"]
            and s.get("register_number") == user.get("register_number")
        ),
        None,
    )
    submitted = latest is not None
    graded = bool(latest and latest.get("grading_status") == "graded")
    status_class = "ok" if submitted else "neutral"
    grading_class = "ok" if graded else "neutral"
    status_text = "Submitted for grading" if submitted else "No submission"
    grading_text = "Graded" if graded else "Not graded"
    file_row = (
        f'<div class="m-file-row"><span class="m-file-icon"></span><a href="#">{escape(latest["filename"])}</a><span>{escape(latest["created_at"].replace("T"," ")[:19])}</span></div>'
        if submitted else "No files submitted"
    )
    feedback_html = ""
    if graded:
        feedback_comment_html = (
            f"<tr><td>Feedback<br>comments</td><td>{escape(latest.get('feedback_comment') or '-')}</td></tr>"
            if latest.get("feedback_comment")
            else ""
        )
        feedback_html = f"""
        <div class="m-answer-feedback-title">Feedback</div>
        <table class="m-status-table m-answer-table">
          <tr><td>Grade</td><td>{latest['grade']:.2f} / {float(latest.get('grade_max',100)):.2f}</td></tr>
          <tr><td>Graded on</td><td>{escape(latest['graded_on'].replace('T',' ')[:19])}</td></tr>
          <tr><td>Graded by</td><td>{escape(latest['graded_by'] or '')}</td></tr>
          <tr><td>Annotate PDF</td><td><div class="m-file-row"><span class="m-file-icon"></span><a href="#">{escape(latest.get('feedback_pdf') or 'feedback.pdf')}</a></div><div style="margin-top:8px;"><a href="#">View annotated PDF...</a></div></td></tr>
          {feedback_comment_html}
        </table>
        """
    submission_comment_form = ""
    if submitted:
        latest_comments = latest.get("submission_comment_items") or []
        latest_comment = latest_comments[-1]["comment"] if latest_comments else ""
        submission_comment_form = f"""
        <div style="margin-top:16px;">
          <form method="post" action="/lms/course/{escape(course['course_code'])}/{escape(section['slug'])}/{escape(item['slug'])}/comment">
            <label for="submissionComment" class="m-answer-feedback-title" style="font-size:20px; margin:18px 0 10px;">Submission comments</label>
            <textarea id="submissionComment" name="submission_comment" rows="3" style="width:100%; border:1px solid #d0d7e2; border-radius:8px; padding:12px;" placeholder="Add an optional comment for faculty">{escape(latest_comment)}</textarea>
            <div style="margin-top:10px;">
              <button type="submit" class="btn btn-primary">Save comment</button>
            </div>
          </form>
        </div>
        """
    body = f"""
    <div class="m-shell m-wide-shell">
      <div class="m-panel">
        <div class="m-heading">{escape(course['course_code'])}-{escape(course['course_name'])}</div>
        <div class="m-breadcrumbs"><a href="/lms/site-home">Dashboard</a> / <a href="/lms/my/courses.php">My courses</a> / <a href="/lms/course/{course["course_code"]}">{escape(course["course_code"])}</a> / {escape(section["title"])} / {escape(item["label"])}</div>
      </div>
      <div class="m-panel m-answer-panel">
        <div class="m-answer-title">{escape(item["label"])}</div>
        <div class="m-answer-section">Submission status</div>
        <table class="m-status-table m-answer-table">
          <tr><td>Submission<br>status</td><td class="{status_class}">{status_text}</td></tr>
          <tr><td>Grading status</td><td class="{grading_class}">{grading_text}</td></tr>
          <tr><td>Last modified</td><td>{escape(latest['created_at'].replace('T',' ')[:19]) if submitted else '-'}</td></tr>
          <tr><td>File submissions</td><td>{file_row}</td></tr>
          <tr><td>Submission<br>comments</td><td><a href="#">Comments ({latest.get('submission_comments',0) if submitted else 0})</a></td></tr>
        </table>
        {submission_comment_form}
        {feedback_html}
      </div>
    </div>
    """
    return _layout(item["label"], body, user=user, footer=True)


def _faculty_submission_card(course: dict, section: dict, item: dict, sub: dict) -> str:
    graded = sub.get("grading_status") == "graded"
    status_class = "done" if graded else "pending"
    status_text = "Graded" if graded else "Pending"
    grade_value = sub.get("grade")
    grade_display = f"{float(grade_value):.2f}" if grade_value is not None else "Not graded"
    student = mock_lms_service.get_user_by_username(sub["student_username"]) or {}
    student_name = student.get("fullname") or sub["student_username"]
    view_url = f"/lms/faculty/submission/{escape(str(sub['submission_id']))}/view"
    action_label = "Re-access" if graded else "Grade"
    preview_html = f"""
    <object data="{view_url}" type="application/pdf">
      <iframe src="{view_url}"></iframe>
    </object>
    """
    latest_student_comment = ""
    comment_items = sub.get("submission_comment_items") or []
    if comment_items:
        latest_student_comment = comment_items[-1].get("comment") or ""
    student_comment_html = (
        f'<div><strong>Student comment:</strong> {escape(latest_student_comment)}</div>'
        if latest_student_comment else
        f'<div><strong>Student comments:</strong> {int(sub.get("submission_comments", 0) or 0)}</div>'
    )
    return f"""
    <article class="m-grade-card">
      <div class="m-grade-preview">{preview_html}</div>
      <div class="m-grade-body">
        <div class="m-grade-top">
          <div>
            <div class="m-grade-title">{escape(student_name)}</div>
            <div class="m-grade-name">{escape(sub['student_username'])} · {escape(sub['register_number'])}</div>
          </div>
        </div>
        <div class="m-grade-meta">
          <div><strong>{escape(course['course_code'])}</strong> · {escape(section['title'])}</div>
          <div>{escape(item['label'])}</div>
          <div><strong>File:</strong> {escape(sub['filename'])}</div>
          <div><strong>Submitted:</strong> {escape(sub['created_at'].replace('T', ' ')[:19])}</div>
          <div><strong>Grade:</strong> {grade_display} / {float(sub.get('grade_max', 100)):.2f}</div>
          {student_comment_html}
        </div>
        <div class="m-grade-actions">
          <a class="m-btn ghost" href="{view_url}" target="_blank">View</a>
          <button
            class="m-btn"
            type="button"
            data-submission-id="{escape(str(sub['submission_id']))}"
            data-student-name="{escape(student_name)}"
            data-student-username="{escape(sub['student_username'])}"
            data-register-number="{escape(sub['register_number'])}"
            data-grade="{escape(str(sub.get('grade') if sub.get('grade') is not None else ''))}"
            data-grade-max="{escape(str(sub.get('grade_max',100)))}"
            data-feedback-pdf="{escape(sub.get('feedback_pdf') or f'feedback_{sub["filename"]}')}"
            data-feedback-comment="{escape(sub.get('feedback_comment') or '')}"
            data-action-label="{action_label}"
            onclick="openGradeModal(this)"
          >{action_label}</button>
        </div>
      </div>
    </article>
    """


def _faculty_submission_page(user: dict, course: dict, section: dict, item: dict) -> HTMLResponse:
    exam_session = _label_for_section(section["slug"])
    submissions = mock_lms_service.get_submissions_for_course(course["course_code"], exam_session=exam_session)
    cards = [_faculty_submission_card(course, section, item, sub) for sub in submissions]
    card_html = (
        f'<div class="m-grade-grid">{"".join(cards)}</div>'
        if cards
        else '<div class="m-empty-panel">No student submissions yet for this CIA page.</div>'
    )
    modal_html = f"""
    <div class="m-grade-modal-backdrop" id="gradeModal">
      <div class="m-grade-modal">
        <div class="m-grade-modal-head">
          <div>
            <h2 class="m-grade-modal-title" id="gradeModalTitle">Grade submission</h2>
            <div class="m-grade-modal-sub" id="gradeModalMeta"></div>
          </div>
          <button type="button" class="m-grade-modal-close" onclick="closeGradeModal()">&times;</button>
        </div>
        <div class="m-grade-modal-body">
          <form class="m-grade-form" method="post" action="/lms/faculty/course/{escape(course['course_code'])}/{escape(section['slug'])}/{escape(item['slug'])}/grade">
            <input type="hidden" name="submission_id" id="gradeSubmissionId">
            <input type="hidden" name="action_type" id="gradeActionType" value="save">
            <div class="m-grade-row">
              <input name="grade" id="gradeInput" placeholder="Grade" min="0" step="0.01" required>
              <input name="grade_max" id="gradeMaxInput" placeholder="Max grade" min="0" step="0.01" required>
            </div>
            <input name="feedback_pdf" id="feedbackPdfInput" placeholder="Feedback PDF name">
            <textarea name="feedback_comment" id="feedbackCommentInput" rows="3" placeholder="Optional feedback comment for the student"></textarea>
            <div class="m-grade-modal-actions" id="gradeModalActions">
              <button class="m-btn m-remove" type="submit" id="gradeRemoveBtn" onclick="setGradeAction('remove')">Remove grade</button>
              <button class="m-btn" type="submit" id="gradeSaveBtn" onclick="setGradeAction('save')">Save</button>
            </div>
          </form>
        </div>
      </div>
    </div>
    <script>
      let gradeModalOriginal = null;
      function setGradeAction(actionType) {{
        document.getElementById('gradeActionType').value = actionType || 'save';
      }}
      function updateGradeModalButtons() {{
        const gradeValue = document.getElementById('gradeInput').value;
        const gradeMaxValue = document.getElementById('gradeMaxInput').value;
        const feedbackValue = document.getElementById('feedbackPdfInput').value;
        const feedbackCommentValue = document.getElementById('feedbackCommentInput').value;
        const saveBtn = document.getElementById('gradeSaveBtn');
        const removeBtn = document.getElementById('gradeRemoveBtn');
        const actions = document.getElementById('gradeModalActions');
        const isReaccess = gradeModalOriginal && gradeModalOriginal.mode === 'reaccess';
        const hasChanges = !gradeModalOriginal || gradeValue !== gradeModalOriginal.grade || gradeMaxValue !== gradeModalOriginal.gradeMax || feedbackValue !== gradeModalOriginal.feedbackPdf || feedbackCommentValue !== gradeModalOriginal.feedbackComment;
        const gradeNum = gradeValue === '' ? null : Number(gradeValue);
        const gradeMaxNum = gradeMaxValue === '' ? null : Number(gradeMaxValue);
        const invalidPair = gradeNum !== null && gradeMaxNum !== null && !Number.isNaN(gradeNum) && !Number.isNaN(gradeMaxNum) && gradeNum > gradeMaxNum;

        actions.classList.toggle('reaccess', !!isReaccess);
        document.getElementById('gradeInput').setCustomValidity(invalidPair ? 'Grade must be less than or equal to max grade' : '');
        document.getElementById('gradeMaxInput').setCustomValidity(invalidPair ? 'Max grade must be greater than or equal to grade' : '');

        if (isReaccess) {{
          removeBtn.style.display = 'block';
          saveBtn.textContent = 'Save changes';
          saveBtn.disabled = !hasChanges || invalidPair;
          removeBtn.disabled = false;
          saveBtn.classList.toggle('is-idle', !hasChanges || invalidPair);
          removeBtn.classList.remove('is-idle');
        }} else {{
          removeBtn.style.display = 'none';
          saveBtn.textContent = 'Save';
          saveBtn.disabled = !hasChanges || invalidPair;
          saveBtn.classList.toggle('is-idle', !hasChanges || invalidPair);
          removeBtn.disabled = true;
          removeBtn.classList.add('is-idle');
        }}
      }}
      function openGradeModal(button) {{
        document.getElementById('gradeSubmissionId').value = button.dataset.submissionId || '';
        document.getElementById('gradeInput').value = button.dataset.grade || '';
        document.getElementById('gradeMaxInput').value = button.dataset.gradeMax || '100';
        document.getElementById('feedbackPdfInput').value = button.dataset.feedbackPdf || '';
        document.getElementById('feedbackCommentInput').value = button.dataset.feedbackComment || '';
        document.getElementById('gradeActionType').value = 'save';
        document.getElementById('gradeModalTitle').textContent = (button.dataset.actionLabel || 'Grade') + ' submission';
        document.getElementById('gradeModalMeta').textContent = (button.dataset.studentName || '') + ' (' + (button.dataset.studentUsername || '') + ' / ' + (button.dataset.registerNumber || '') + ')';
        gradeModalOriginal = {{
          mode: button.dataset.actionLabel === 'Re-access' ? 'reaccess' : 'grade',
          grade: button.dataset.grade || '',
          gradeMax: button.dataset.gradeMax || '100',
          feedbackPdf: button.dataset.feedbackPdf || '',
          feedbackComment: button.dataset.feedbackComment || ''
        }};
        updateGradeModalButtons();
        document.getElementById('gradeModal').classList.add('open');
      }}
      function closeGradeModal() {{
        document.getElementById('gradeModal').classList.remove('open');
      }}
      document.addEventListener('DOMContentLoaded', function() {{
        ['gradeInput', 'gradeMaxInput', 'feedbackPdfInput', 'feedbackCommentInput'].forEach(function(id) {{
          const el = document.getElementById(id);
          if (el) {{
            el.addEventListener('input', updateGradeModalButtons);
          }}
        }});
      }});
      window.addEventListener('click', function(event) {{
        const modal = document.getElementById('gradeModal');
        if (event.target === modal) {{
          closeGradeModal();
        }}
      }});
      window.addEventListener('keydown', function(event) {{
        if (event.key === 'Escape') {{
          closeGradeModal();
        }}
      }});
    </script>
    """
    body = f"""
    <div class="m-shell m-focus-shell m-wide-shell">
      <div class="m-panel">
        <div class="m-heading">{escape(course['course_code'])}-{escape(course['course_name'])}</div>
        <div class="m-breadcrumbs"><a href="/lms/site-home">Dashboard</a> / <a href="/lms/faculty/courses">Faculty courses</a> / <a href="/lms/faculty/course/{course["course_code"]}">{escape(course["course_code"])}</a> / {escape(section["title"])} / {escape(item["label"])}</div>
      </div>
      <div class="m-panel m-answer-panel">
        <div class="m-summary-title">Faculty grading panel</div>
        {card_html}
      </div>
      {modal_html}
    </div>
    """
    return _layout(f"Faculty {item['label']}", body, user=user, footer=True)


@router.get("/", response_class=HTMLResponse)
@router.get("/site-home", response_class=HTMLResponse)
async def lms_home(request: Request):
    user = _get_logged_in_user(request)
    if user:
        return RedirectResponse(url="/lms/faculty/courses" if _is_faculty(user) else "/lms/my/courses.php", status_code=302)
    return _guest_home()


@router.get("/login/index.php", response_class=HTMLResponse)
async def lms_login_page(request: Request):
    user = _get_logged_in_user(request)
    if user:
        return RedirectResponse(url="/lms/faculty/courses" if _is_faculty(user) else "/lms/my/courses.php", status_code=302)
    return _login_page(error=request.query_params.get("error") == "1")


@router.post("/login")
async def lms_login(username: str = Form(...), password: str = Form(...)):
    user = mock_lms_service.authenticate(username.strip(), password.strip())
    if not user:
        return RedirectResponse(url="/lms/login/index.php?error=1", status_code=302)
    response = RedirectResponse(url="/lms/faculty/courses" if _is_faculty(user) else "/lms/my/courses.php", status_code=302)
    response.set_cookie("mock_lms_session", mock_lms_service.build_token(user), httponly=False)
    return response


@router.get("/logout")
async def lms_logout():
    response = RedirectResponse(url="/lms/site-home", status_code=302)
    response.delete_cookie("mock_lms_session")
    return response


@router.get("/my/courses.php", response_class=HTMLResponse)
async def lms_student_courses(request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if _is_faculty(user):
        return RedirectResponse(url="/lms/faculty/courses", status_code=302)
    return _courses_page(user)


@router.get("/faculty/courses", response_class=HTMLResponse)
async def lms_faculty_courses(request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if not _is_faculty(user):
        return RedirectResponse(url="/lms/my/courses.php", status_code=302)
    return _courses_page(user)


@router.get("/course/{course_code}", response_class=HTMLResponse)
async def lms_course_page(course_code: str, request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if _is_faculty(user):
        return RedirectResponse(url=f"/lms/faculty/course/{course_code}", status_code=302)
    course = mock_lms_service.get_course(course_code)
    return _course_topics_page(user, course, faculty=False) if course else _layout("Course not found", '<div class="m-shell"><div class="m-panel">Course not found</div></div>', user=user)


@router.get("/faculty/course/{course_code}", response_class=HTMLResponse)
async def lms_faculty_course_page(course_code: str, request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if not _is_faculty(user):
        return RedirectResponse(url=f"/lms/course/{course_code}", status_code=302)
    course = mock_lms_service.get_course(course_code)
    return _course_topics_page(user, course, faculty=True) if course else _layout("Course not found", '<div class="m-shell"><div class="m-panel">Course not found</div></div>', user=user)


@router.get("/course/{course_code}/{section_slug}/{item_slug}", response_class=HTMLResponse)
async def lms_student_item_page(course_code: str, section_slug: str, item_slug: str, request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if _is_faculty(user):
        return RedirectResponse(url=f"/lms/faculty/course/{course_code}/{section_slug}/{item_slug}", status_code=302)
    course = mock_lms_service.get_course(course_code)
    section, item = _find_item(section_slug, item_slug)
    if not course or not item:
        return _layout("Item not found", '<div class="m-shell"><div class="m-panel">Item not found</div></div>', user=user)
    if item["type"] == "quiz":
        return _quiz_page(user, course, section, item, faculty=False)
    return _student_submission_page(user, course, section, item)


@router.get("/faculty/course/{course_code}/{section_slug}/{item_slug}", response_class=HTMLResponse)
async def lms_faculty_item_page(course_code: str, section_slug: str, item_slug: str, request: Request):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if not _is_faculty(user):
        return RedirectResponse(url=f"/lms/course/{course_code}/{section_slug}/{item_slug}", status_code=302)
    course = mock_lms_service.get_course(course_code)
    section, item = _find_item(section_slug, item_slug)
    if not course or not item:
        return _layout("Item not found", '<div class="m-shell"><div class="m-panel">Item not found</div></div>', user=user)
    if item["type"] == "quiz":
        return _quiz_page(user, course, section, item, faculty=True)
    return _faculty_submission_page(user, course, section, item)


@router.get("/faculty/submission/{submission_id}/view")
async def lms_faculty_view_submission(
    submission_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if not _is_faculty(user):
        raise HTTPException(status_code=403, detail="Faculty access required")

    submission = mock_lms_service.get_submission(submission_id)
    if not submission or not submission.get("artifact_uuid"):
        raise HTTPException(status_code=404, detail="Submission not found")

    artifact_service = ArtifactService(db)
    artifact = await artifact_service.get_by_uuid(submission["artifact_uuid"])
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    resolved_path = _resolve_artifact_file_path(
        artifact.file_blob_path,
        artifact.original_filename,
        parsed_reg_no=artifact.parsed_reg_no,
        parsed_subject_code=submission.get("subject_code"),
    )
    if not resolved_path:
        raise HTTPException(status_code=404, detail="File not found on server")

    safe_name = (artifact.original_filename or submission.get("filename") or "paper").replace('"', "")
    return FileResponse(
        path=resolved_path,
        media_type=artifact.mime_type or "application/pdf",
        filename=safe_name,
        headers={"Content-Disposition": f'inline; filename="{safe_name}"'},
    )


@router.post("/faculty/course/{course_code}/{section_slug}/{item_slug}/grade")
async def lms_faculty_grade_submission(
    course_code: str,
    section_slug: str,
    item_slug: str,
    request: Request,
    submission_id: str = Form(...),
    action_type: str = Form("save"),
    grade: float = Form(0),
    grade_max: float = Form(100),
    feedback_pdf: str = Form(""),
    feedback_comment: str = Form(""),
):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if not _is_faculty(user):
        return RedirectResponse(url=f"/lms/course/{course_code}/{section_slug}/{item_slug}", status_code=302)
    if action_type == "remove":
        mock_lms_service.remove_grade(submission_id=submission_id)
    else:
        if grade < 0 or grade_max < 0 or grade > grade_max:
            raise HTTPException(status_code=400, detail="Grade must be between 0 and the max grade")
        mock_lms_service.grade_submission(
            submission_id=submission_id,
            grade=grade,
            grade_max=grade_max,
            graded_by=user.get("fullname", user["username"]),
            feedback_pdf=feedback_pdf or None,
            feedback_comment=feedback_comment or None,
        )
    return RedirectResponse(url=f"/lms/faculty/course/{course_code}/{section_slug}/{item_slug}", status_code=302)


@router.post("/course/{course_code}/{section_slug}/{item_slug}/comment")
async def lms_student_save_submission_comment(
    course_code: str,
    section_slug: str,
    item_slug: str,
    request: Request,
    submission_comment: str = Form(""),
):
    user, redirect = _require_user(request)
    if redirect:
        return redirect
    if _is_faculty(user):
        return RedirectResponse(url=f"/lms/faculty/course/{course_code}/{section_slug}/{item_slug}", status_code=302)
    course = mock_lms_service.get_course(course_code)
    section, _item = _find_item(section_slug, item_slug)
    if not course or not section:
        raise HTTPException(status_code=404, detail="Item not found")
    exam_session = _label_for_section(section["slug"])
    submissions = mock_lms_service.get_submissions_for_course(course["course_code"], exam_session=exam_session)
    latest = next(
        (
            s for s in reversed(submissions)
            if s.get("student_username") == user["username"]
            and s.get("register_number") == user.get("register_number")
        ),
        None,
    )
    if latest and (submission_comment or "").strip():
        mock_lms_service.add_submission_comment(
            submission_id=str(latest["submission_id"]),
            author_username=user["username"],
            comment=submission_comment,
        )
    return RedirectResponse(url=f"/lms/course/{course_code}/{section_slug}/{item_slug}", status_code=302)


@router.get("/dashboard")
async def lms_dashboard_redirect():
    return RedirectResponse(url="/lms/my/courses.php", status_code=302)
