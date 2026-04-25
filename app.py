"""
app.py — Flask 웹서버
AI Trading Assistant v3.0

리포트 서빙 + 업데이트 버튼 API
"""

import os
import sys
import glob

# Windows cp949 stdout encoding fix
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from flask import Flask, send_file, jsonify, send_from_directory, render_template, request
from jinja2 import Environment, FileSystemLoader

from pipeline import run_pipeline
from market_scanner import scan_sp100, scan_etf, scan_kospi, scan_watchlist
from watchlist_store import load_watchlist, add_ticker as wl_add, remove_ticker as wl_remove

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")
TEMPLATES_DIR = os.path.join(PROJECT_DIR, "templates")

app = Flask(__name__, template_folder=TEMPLATES_DIR)

# Jinja2 커스텀 필터 등록 (scanner 페이지용)
app.jinja_env.filters["f1"] = lambda x: f"{x:.1f}" if isinstance(x, (int, float)) else str(x)
app.jinja_env.filters["f2"] = lambda x: f"{x:.2f}" if isinstance(x, (int, float)) else str(x)
def _mcap_fmt(v):
    if not v: return ""
    v = float(v)
    if v >= 1e12: return f"${v/1e12:.1f}T"
    if v >= 1e9: return f"${v/1e9:.0f}B"
    if v >= 1e6: return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"
app.jinja_env.filters["mcap"] = _mcap_fmt


def _latest_report() -> str | None:
    """가장 최신 리포트 파일 경로 반환"""
    files = glob.glob(os.path.join(REPORTS_DIR, "report_*.html"))
    if not files:
        return None
    files.sort(reverse=True)
    return files[0]


@app.route("/")
def index():
    """최신 리포트 서빙"""
    report = _latest_report()
    if report:
        return send_file(report)
    return "<h1>리포트가 없습니다</h1><p>🔄 업데이트 버튼을 눌러 첫 리포트를 생성하세요.</p>", 404


@app.route("/api/run-pipeline", methods=["POST"])
def api_run_pipeline():
    """파이프라인 실행 API"""
    try:
        result = run_pipeline(PROJECT_DIR, skip_ocr=True, skip_fetch=False)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/scanner")
def scanner():
    """Market Scanner — 파이프라인이 생성한 최신 unified 스캐너 리포트로 리다이렉트.
    GitHub Pages 배포본과 동일한 페이지를 로컬에서도 보이도록 한다."""
    files = sorted(glob.glob(os.path.join(REPORTS_DIR, "scanner_*.html")), reverse=True)
    files = [f for f in files if "scanner_sp100_" not in os.path.basename(f)
             and "scanner_etf_" not in os.path.basename(f)
             and "scanner_kospi_" not in os.path.basename(f)]
    if not files:
        return "<h1>스캐너 리포트가 없습니다</h1><p>🔄 메인 페이지에서 업데이트를 실행하세요.</p>", 404
    return send_file(files[0])


@app.route("/api/scan-sp100", methods=["POST"])
def api_scan():
    """S&P 100 스캔 API"""
    try:
        result = scan_sp100(PROJECT_DIR)
        if result.get("status") == "ok":
            # 결과를 파일로 캐시 (scanner 페이지 렌더링용)
            import json
            from datetime import date
            today = date.today().strftime("%Y-%m-%d")
            result_path = os.path.join(PROJECT_DIR, "screenshots", f"scanner_result_{today}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/scanner-etf")
def scanner_etf():
    """ETF Scanner 페이지"""
    import json
    from datetime import date as _date
    today = _date.today().strftime("%Y-%m-%d")
    result_path = os.path.join(PROJECT_DIR, "screenshots", f"scanner_etf_result_{today}.json")
    context = {"scan_date": None}
    if os.path.exists(result_path):
        with open(result_path, "r", encoding="utf-8") as f:
            context = json.load(f)
    return render_template("scanner_etf.html", **context)


@app.route("/api/scan-etf", methods=["POST"])
def api_scan_etf():
    """ETF 스캔 API"""
    try:
        result = scan_etf(PROJECT_DIR)
        if result.get("status") == "ok":
            import json
            from datetime import date as _date
            today = _date.today().strftime("%Y-%m-%d")
            result_path = os.path.join(PROJECT_DIR, "screenshots", f"scanner_etf_result_{today}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/scan-kospi", methods=["POST"])
def api_scan_kospi():
    """KOSPI 스캔 API"""
    try:
        result = scan_kospi(PROJECT_DIR)
        if result.get("status") == "ok":
            import json
            from datetime import date as _date
            today = _date.today().strftime("%Y-%m-%d")
            result_path = os.path.join(PROJECT_DIR, "screenshots", f"scanner_kospi_result_{today}.json")
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/reports/<path:filename>")
def serve_report(filename):
    """과거 리포트 조회"""
    return send_from_directory(REPORTS_DIR, filename)


# ── Watchlist API (관심종목 추가/삭제/조회) ──
@app.route("/api/watchlist", methods=["GET"])
def api_watchlist_list():
    """현재 watchlist.md 내용 반환"""
    entries = load_watchlist(PROJECT_DIR)
    return jsonify({"status": "ok", "entries": [
        {"ticker": t, "comment": c} for t, c in entries
    ]})


@app.route("/api/watchlist/add", methods=["POST"])
def api_watchlist_add():
    """관심종목 추가. body: {ticker, comment?}"""
    try:
        data = request.get_json(silent=True) or {}
        ticker = (data.get("ticker") or "").strip()
        comment = (data.get("comment") or "").strip()
        if not ticker:
            return jsonify({"status": "error", "error": "ticker required"}), 400
        ok, msg = wl_add(PROJECT_DIR, ticker, comment)
        return jsonify({"status": "ok" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/watchlist/remove", methods=["POST", "DELETE"])
def api_watchlist_remove():
    """관심종목 삭제. body: {ticker}"""
    try:
        data = request.get_json(silent=True) or {}
        ticker = (data.get("ticker") or "").strip()
        if not ticker:
            return jsonify({"status": "error", "error": "ticker required"}), 400
        ok, msg = wl_remove(PROJECT_DIR, ticker)
        return jsonify({"status": "ok" if ok else "error", "message": msg})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/scan-watchlist", methods=["POST"])
def api_scan_watchlist():
    """Watchlist 즉시 재스캔"""
    try:
        result = scan_watchlist(PROJECT_DIR)
        return jsonify(result)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


if __name__ == "__main__":
    import webbrowser, threading

    print(f"\n{'=' * 50}")
    print(f"  AI Trading Assistant v3.0")
    print(f"{'=' * 50}")

    # 서버 시작 전 파이프라인 자동 실행
    print(f"\n[Auto] Running pipeline...")
    result = run_pipeline(PROJECT_DIR, skip_ocr=True, skip_fetch=False)
    if result["status"] == "ok":
        print(f"[Auto] Report generated: {result['report_path']}")
    else:
        print(f"[Auto] Pipeline error: {result.get('error')}")

    print(f"\n  http://localhost:5000")
    print(f"{'=' * 50}\n")

    # 서버 시작 후 브라우저 자동 열기
    threading.Timer(1.5, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(host="0.0.0.0", port=5000, debug=False)
