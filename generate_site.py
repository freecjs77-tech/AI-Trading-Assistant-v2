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
        rows.append(f'            <tr class="hover:bg-surface-container-high/50 transition-colors"><td class="px-6 py-4"><a href="reports/{name}" class="text-primary hover:underline font-medium">{display}</a></td></tr>')

    html = f"""<!DOCTYPE html>
<html class="dark" lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Archive — Trading Assistant</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Manrope:wght@300;400;500;600;700;800&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:wght,FILL@100..700,0..1&display=swap" rel="stylesheet">
  <script>tailwind.config={{darkMode:"class",theme:{{extend:{{colors:{{"surface-container":"#0f1930","surface-container-high":"#141f38","surface-container-low":"#091328","surface":"#060e20","surface-bright":"#1f2b49","background":"#060e20","primary":"#6dddff","primary-container":"#00d2fd","on-primary-container":"#004352","secondary":"#2ff801","tertiary":"#ff7166","on-surface":"#dee5ff","on-surface-variant":"#a3aac4","outline":"#6d758c","outline-variant":"#40485d"}},fontFamily:{{headline:["Space Grotesk"],body:["Manrope"],label:["Inter"]}}}}}}}}</script>
</head>
<body class="bg-surface text-on-surface font-body">
  <nav class="fixed left-0 top-0 h-full flex flex-col p-6 z-50 bg-surface-container-low font-body font-medium w-64 md:flex hidden" id="sidebar">
    <div class="flex items-center gap-3 mb-10">
      <div class="w-10 h-10 bg-primary-container rounded flex items-center justify-center"><span class="material-symbols-outlined text-on-primary-container" style="font-variation-settings:'FILL' 1;">dashboard_customize</span></div>
      <div><h2 class="text-lg font-black text-primary leading-none">Signal Report</h2><p class="text-[10px] uppercase tracking-widest text-on-surface/40 mt-1">Precision Curator</p></div>
    </div>
    <div class="space-y-2 flex-grow">
      <a class="flex items-center gap-3 px-4 py-3 text-on-surface/40 hover:bg-surface-container hover:text-on-surface transition-all" href="index.html"><span class="material-symbols-outlined">dashboard</span><span>Dashboard</span></a>
      <a class="flex items-center gap-3 px-4 py-3 text-on-surface/40 hover:bg-surface-container hover:text-on-surface transition-all" href="#"><span class="material-symbols-outlined">analytics</span><span>Scanner</span></a>
      <a class="flex items-center gap-3 px-4 py-3 text-on-surface/40 hover:bg-surface-container hover:text-on-surface transition-all" href="#"><span class="material-symbols-outlined">history</span><span>Backtest</span></a>
      <a class="flex items-center gap-3 px-4 py-3 text-on-surface/40 hover:bg-surface-container hover:text-on-surface transition-all" href="#"><span class="material-symbols-outlined">trending_up</span><span>Trend</span></a>
      <a class="flex items-center gap-3 px-4 py-3 text-primary bg-surface-container-high rounded-md shadow-[0_0_15px_rgba(109,221,255,0.1)]" href="archive.html"><span class="material-symbols-outlined">inventory_2</span><span>Archive</span></a>
    </div>
    <div class="pt-6 mt-6 border-t border-outline-variant/20 px-4 text-[10px] text-outline leading-relaxed">{len(rows)} reports</div>
  </nav>
  <div class="fixed inset-0 bg-black/50 z-40 hidden" id="sidebarOverlay" onclick="toggleSidebar()"></div>
  <main class="md:ml-64 min-h-screen">
    <header class="flex justify-between items-center w-full px-8 py-4 bg-surface/60 backdrop-blur-xl z-40 shadow-[0_40px_40px_0_rgba(222,229,255,0.08)] sticky top-0">
      <div class="flex items-center gap-4">
        <button class="md:hidden text-on-surface" onclick="toggleSidebar()"><span class="material-symbols-outlined">menu</span></button>
        <span class="text-xl font-bold text-on-surface uppercase font-headline tracking-tight">Archive</span>
      </div>
    </header>
    <div class="p-8 max-w-3xl">
      <div class="overflow-x-auto rounded-xl border border-outline-variant/10 bg-surface-container-low">
        <table class="w-full text-left border-collapse">
          <tbody class="divide-y divide-outline-variant/10 font-label text-sm">
{chr(10).join(rows)}
          </tbody>
        </table>
      </div>
    </div>
  </main>
  <script>function toggleSidebar(){{const s=document.getElementById('sidebar'),o=document.getElementById('sidebarOverlay');s.classList.toggle('hidden');s.classList.toggle('flex');o.classList.toggle('hidden');}}</script>
</body>
</html>"""

    with open(os.path.join(DEPLOY_DIR, "archive.html"), "w", encoding="utf-8") as f:
        f.write(html)
    print(f"archive.html generated ({len(rows)} entries)")


if __name__ == "__main__":
    prepare_deploy()
