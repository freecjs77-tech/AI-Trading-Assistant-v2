"""
generate_site.py -- GitHub Pages 배포 디렉토리 생성
최신 리포트를 index.html로 복사하고, 아카이브 페이지와 히스토리를 deploy/에 구성한다.
"""

import os
import shutil
import glob
from datetime import datetime

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEPLOY_DIR = os.path.join(PROJECT_DIR, "deploy")
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
HISTORY_DIR = os.path.join(PROJECT_DIR, "history")


def prepare_deploy():
    # 기존 deploy 디렉토리 정리
    if os.path.exists(DEPLOY_DIR):
        shutil.rmtree(DEPLOY_DIR)
    os.makedirs(DEPLOY_DIR)

    # .nojekyll (Jekyll 비활성화)
    with open(os.path.join(DEPLOY_DIR, ".nojekyll"), "w") as f:
        pass

    # reports/ 복사
    report_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "report_*.html")))
    if not report_files:
        print("WARNING: No report files found in reports/")
        return

    deploy_reports = os.path.join(DEPLOY_DIR, "reports")
    os.makedirs(deploy_reports)
    for f in report_files:
        shutil.copy2(f, deploy_reports)

    # 최신 리포트 -> index.html
    latest = report_files[-1]
    shutil.copy2(latest, os.path.join(DEPLOY_DIR, "index.html"))
    print(f"index.html <- {os.path.basename(latest)}")

    # 스캐너 페이지 복사 (deploy 루트에 배치)
    scanner_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "scanner_*.html")))
    for f in scanner_files:
        shutil.copy2(f, DEPLOY_DIR)
    if scanner_files:
        print(f"scanner pages copied ({len(scanner_files)} files)")

    # 백테스트 페이지 복사
    backtest_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "backtest_*.html")))
    for f in backtest_files:
        shutil.copy2(f, DEPLOY_DIR)
    if backtest_files:
        print(f"backtest pages copied ({len(backtest_files)} files)")

    # 트렌드 페이지 복사
    trend_files = sorted(glob.glob(os.path.join(REPORTS_DIR, "trend_*.html")))
    for f in trend_files:
        shutil.copy2(f, DEPLOY_DIR)
    if trend_files:
        print(f"trend pages copied ({len(trend_files)} files)")

    # details/ 복사 (종목 상세 페이지)
    details_src = os.path.join(REPORTS_DIR, "details")
    if os.path.exists(details_src):
        deploy_details = os.path.join(DEPLOY_DIR, "details")
        shutil.copytree(details_src, deploy_details)
        n_details = len(os.listdir(deploy_details))
        print(f"details/ copied ({n_details} pages)")

    # history/ 복사 (다음 실행에서 복원용)
    if os.path.exists(HISTORY_DIR):
        deploy_history = os.path.join(DEPLOY_DIR, "history")
        shutil.copytree(HISTORY_DIR, deploy_history)
        print(f"history/ copied ({len(os.listdir(deploy_history))} files)")

    # archive.html 생성
    _generate_archive(report_files)

    print(f"Deploy directory ready: {len(report_files)} reports")


def _generate_archive(report_files):
    """날짜별 과거 리포트 목록 HTML 생성"""
    rows = []
    for f in reversed(report_files):
        name = os.path.basename(f)
        date_str = name.replace("report_", "").replace(".html", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display = dt.strftime("%Y년 %m월 %d일 (%a)")
        except ValueError:
            display = date_str
        rows.append(f'      <tr><td><a href="reports/{name}">{display}</a></td></tr>')

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Archive — Trading Assistant</title>
  <style>
    :root {{ --bg-body:#0a0e17; --bg-sidebar:#111827; --bg-card:#1a1f2e; --border:#1e2636; --text-primary:#e5e7eb; --text-secondary:#9ca3af; --text-muted:#6b7280; --accent-green:#10b981; --accent-blue:#3b82f6; --bg-hover:#1e293b; --sidebar-w:220px; }}
    * {{ box-sizing:border-box; margin:0; padding:0; }}
    body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Inter',sans-serif; background:var(--bg-body); color:var(--text-primary); font-size:14px; }}
    .sidebar {{ width:var(--sidebar-w); background:var(--bg-sidebar); border-right:1px solid var(--border); display:flex; flex-direction:column; position:fixed; top:0; left:0; bottom:0; z-index:100; }}
    .sidebar-brand {{ padding:24px 20px 20px; border-bottom:1px solid var(--border); }}
    .sidebar-brand h2 {{ font-size:16px; font-weight:800; color:#fff; letter-spacing:1px; }}
    .sidebar-brand .brand-sub {{ font-size:11px; color:var(--accent-green); font-weight:600; letter-spacing:0.5px; margin-top:2px; }}
    .sidebar-nav {{ flex:1; padding:16px 0; }}
    .sidebar-nav a {{ display:flex; align-items:center; gap:12px; padding:12px 20px; color:var(--text-secondary); text-decoration:none; font-size:14px; font-weight:500; transition:all 0.15s; }}
    .sidebar-nav a:hover {{ background:var(--bg-hover); color:var(--text-primary); }}
    .sidebar-nav a.active {{ background:rgba(16,185,129,0.1); color:var(--accent-green); border-left:3px solid var(--accent-green); }}
    .sidebar-nav .nav-icon {{ font-size:18px; width:24px; text-align:center; }}
    .sidebar-footer {{ padding:16px 20px; border-top:1px solid var(--border); font-size:11px; color:var(--text-muted); }}
    .main {{ margin-left:var(--sidebar-w); padding:24px 28px; max-width:800px; }}
    h1 {{ font-size:22px; font-weight:700; color:#fff; margin-bottom:20px; }}
    .archive-tbl {{ width:100%; border-collapse:collapse; background:var(--bg-card); border-radius:12px; overflow:hidden; border:1px solid var(--border); }}
    .archive-tbl td {{ padding:12px 16px; border-bottom:1px solid var(--border); }}
    .archive-tbl tr:last-child td {{ border-bottom:none; }}
    .archive-tbl tr:hover td {{ background:var(--bg-hover); }}
    .archive-tbl a {{ color:var(--accent-blue); text-decoration:none; font-weight:500; }}
    .archive-tbl a:hover {{ text-decoration:underline; }}
    .mobile-menu-btn {{ display:none; position:fixed; top:12px; left:12px; z-index:200; background:var(--bg-card); border:1px solid var(--border); border-radius:8px; padding:8px 12px; color:var(--text-primary); font-size:20px; cursor:pointer; }}
    .sidebar-overlay {{ display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); z-index:90; }}
    @media (max-width:768px) {{ .sidebar {{ transform:translateX(-100%); transition:transform 0.2s; }} .sidebar.open {{ transform:translateX(0); }} .sidebar-overlay.open {{ display:block; }} .mobile-menu-btn {{ display:block; }} .main {{ margin-left:0; padding:16px; padding-top:56px; }} }}
  </style>
</head>
<body>
  <button class="mobile-menu-btn" onclick="toggleSidebar()">&#9776;</button>
  <div class="sidebar-overlay" id="sidebarOverlay" onclick="toggleSidebar()"></div>
  <aside class="sidebar" id="sidebar">
    <div class="sidebar-brand"><h2>TRADING</h2><div class="brand-sub">COMMAND CENTER</div></div>
    <nav class="sidebar-nav">
      <a href="index.html"><span class="nav-icon">&#9638;</span> Dashboard</a>
      <a href="#"><span class="nav-icon">&#9678;</span> Scanner</a>
      <a href="#"><span class="nav-icon">&#8634;</span> Backtest</a>
      <a href="#"><span class="nav-icon">&#8599;</span> Trend</a>
      <a href="archive.html" class="active"><span class="nav-icon">&#9783;</span> Archive</a>
    </nav>
    <div class="sidebar-footer">{len(rows)} reports</div>
  </aside>
  <div class="main">
    <h1>Archive</h1>
    <table class="archive-tbl">
{chr(10).join(rows)}
    </table>
  </div>
  <script>function toggleSidebar(){{ document.getElementById('sidebar').classList.toggle('open'); document.getElementById('sidebarOverlay').classList.toggle('open'); }}</script>
</body>
</html>"""

    with open(os.path.join(DEPLOY_DIR, "archive.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"archive.html generated ({len(rows)} entries)")


if __name__ == "__main__":
    prepare_deploy()
