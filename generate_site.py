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
  <title>Report Archive</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           max-width: 600px; margin: 40px auto; padding: 0 20px; background: #1a1a2e; color: #e0e0e0; }}
    h1 {{ color: #3498db; }}
    a {{ color: #3498db; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    td {{ padding: 10px 12px; border-bottom: 1px solid #333; }}
    .back {{ margin-bottom: 20px; display: inline-block; }}
  </style>
</head>
<body>
  <a href="index.html" class="back">&larr; Latest Report</a>
  <h1>Report Archive</h1>
  <table>
{chr(10).join(rows)}
  </table>
</body>
</html>"""

    with open(os.path.join(DEPLOY_DIR, "archive.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"archive.html generated ({len(rows)} entries)")


if __name__ == "__main__":
    prepare_deploy()
