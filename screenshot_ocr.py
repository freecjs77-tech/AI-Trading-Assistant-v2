"""
screenshot_ocr.py — 스크린샷 OCR (Claude API / Tesseract 이중 지원)
AI Trading Assistant v3.0

카카오톡 포트폴리오 스크린샷에서 종목 정보를 추출하여 portfolio.md를 갱신.
- ANTHROPIC_API_KEY 환경변수 설정 시 → Claude Vision API (정확도 높음)
- 미설정 시 → Tesseract OCR fallback (로컬, 무료)
"""

import os
import re
import json
import base64
import glob as glob_module
from portfolio_data import KR_TO_TICKER, TICKER_META, resolve_korean_name


def _find_latest_screenshots(screenshot_dir: str) -> list[str]:
    """최신 스크린샷 이미지 파일들을 찾기"""
    patterns = ["*.jpg", "*.jpeg", "*.png"]
    files = []
    for pat in patterns:
        files.extend(glob_module.glob(os.path.join(screenshot_dir, pat)))
    # KakaoTalk 스크린샷만 필터 (market_data JSON 제외)
    files = [f for f in files if not f.endswith(".json")]
    files.sort(key=os.path.getmtime, reverse=True)
    return files


def _parse_holdings_text(text: str) -> list[dict]:
    """OCR 텍스트에서 종목 정보 추출"""
    holdings = []
    lines = text.split("\n")

    # 패턴: 종목명 / 수량(주) / 금액($) / 수익금액 / 수익률
    # 카카오톡 스크린샷 형식:
    #   테슬라
    #   26.931576주
    #   $9,744.64
    #   -$759.24 (7.23%)
    current_name = None
    current_shares = None
    current_value = None
    current_pnl = None
    current_pnl_pct = None

    shares_pat = re.compile(r"([\d,]+\.?\d*)\s*주")
    value_pat = re.compile(r"\$?([\d,]+\.?\d+)")
    pnl_pat = re.compile(r"([+-]?\$?[\d,]+\.?\d+)\s*\(?([\d.]+)%?\)?")

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 주수 패턴
        sm = shares_pat.search(line)
        if sm and current_name:
            current_shares = float(sm.group(1).replace(",", ""))
            continue

        # 금액 패턴 ($ 포함)
        if "$" in line and current_shares:
            vm = value_pat.search(line)
            if vm:
                val = float(vm.group(1).replace(",", ""))
                if current_value is None:
                    current_value = val
                else:
                    # 두 번째 금액은 수익금액
                    pnl_str = line.strip()
                    pm = pnl_pat.search(pnl_str)
                    if pm:
                        pnl_val = float(pm.group(1).replace("$", "").replace(",", "").replace("+", ""))
                        if "-" in pnl_str:
                            pnl_val = -abs(pnl_val)
                        current_pnl = pnl_val
                        current_pnl_pct = float(pm.group(2))
                        if "-" in pnl_str:
                            current_pnl_pct = -current_pnl_pct

                    # 종목 완성
                    if current_name and current_shares and current_value:
                        ticker = resolve_korean_name(current_name)
                        if ticker:
                            holdings.append({
                                "ticker": ticker,
                                "shares": current_shares,
                                "value": current_value,
                                "pnl": current_pnl or 0,
                                "pnl_pct": current_pnl_pct or 0,
                            })
                    current_name = None
                    current_shares = None
                    current_value = None
                    current_pnl = None
                    current_pnl_pct = None
                continue

        # 종목명 (한글 또는 영문)
        if len(line) >= 2 and not line.startswith("$"):
            # 새 종목 시작 전 이전 종목 저장
            if current_name and current_shares and current_value:
                ticker = resolve_korean_name(current_name)
                if ticker:
                    holdings.append({
                        "ticker": ticker,
                        "shares": current_shares,
                        "value": current_value,
                        "pnl": current_pnl or 0,
                        "pnl_pct": current_pnl_pct or 0,
                    })
            current_name = line
            current_shares = None
            current_value = None
            current_pnl = None
            current_pnl_pct = None

    # 마지막 종목
    if current_name and current_shares and current_value:
        ticker = resolve_korean_name(current_name)
        if ticker:
            holdings.append({
                "ticker": ticker,
                "shares": current_shares,
                "value": current_value,
                "pnl": current_pnl or 0,
                "pnl_pct": current_pnl_pct or 0,
            })

    return holdings


def extract_with_claude(image_paths: list[str]) -> list[dict]:
    """Claude Vision API로 스크린샷에서 포트폴리오 추출"""
    try:
        import anthropic
    except ImportError:
        print("⚠️ anthropic 패키지가 설치되지 않았습니다. Tesseract로 fallback합니다.")
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    all_holdings = []

    for img_path in image_paths:
        with open(img_path, "rb") as f:
            img_data = base64.standard_b64encode(f.read()).decode("utf-8")

        ext = os.path.splitext(img_path)[1].lower()
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}},
                    {"type": "text", "text": """이 증권 앱 스크린샷에서 보유 종목 정보를 JSON 배열로 추출해주세요.
각 종목: {"name": "종목명(한국어/영문 그대로)", "shares": 보유주수, "value": 평가금액(달러), "pnl": 수익금액(달러), "pnl_pct": 수익률(%)}
JSON 배열만 출력하세요. 다른 텍스트는 제외."""}
                ],
            }],
        )

        text = response.content[0].text
        # JSON 추출
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            try:
                items = json.loads(json_match.group())
                for item in items:
                    ticker = resolve_korean_name(item.get("name", ""))
                    if ticker:
                        all_holdings.append({
                            "ticker": ticker,
                            "shares": float(item.get("shares", 0)),
                            "value": float(item.get("value", 0)),
                            "pnl": float(item.get("pnl", 0)),
                            "pnl_pct": float(item.get("pnl_pct", 0)),
                        })
            except json.JSONDecodeError:
                pass

    return all_holdings


def extract_with_tesseract(image_paths: list[str]) -> list[dict]:
    """Tesseract OCR로 스크린샷에서 포트폴리오 추출"""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance
    except ImportError:
        print("⚠️ pytesseract/Pillow가 설치되지 않았습니다.")
        return []

    all_holdings = []
    for img_path in image_paths:
        img = Image.open(img_path)
        # 전처리: 그레이스케일 + 대비 강화
        img = img.convert("L")
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(2.0)

        text = pytesseract.image_to_string(img, lang="kor+eng")
        holdings = _parse_holdings_text(text)
        all_holdings.extend(holdings)

    return all_holdings


def extract_portfolio_from_screenshots(screenshot_dir: str) -> list[dict]:
    """
    스크린샷에서 포트폴리오 추출.
    Claude API > Tesseract 순으로 시도.
    반환: [{"ticker", "shares", "value", "pnl", "pnl_pct"}, ...]
    """
    image_paths = _find_latest_screenshots(screenshot_dir)
    if not image_paths:
        print("⚠️ 스크린샷 이미지가 없습니다.")
        return []

    print(f"  📸 스크린샷 {len(image_paths)}장 발견")

    # Claude API 시도
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("  🤖 Claude Vision API로 OCR 실행...")
        holdings = extract_with_claude(image_paths)
        if holdings:
            print(f"  ✅ Claude OCR: {len(holdings)}종목 추출")
            return _deduplicate(holdings)

    # Tesseract fallback
    print("  📝 Tesseract OCR로 fallback...")
    holdings = extract_with_tesseract(image_paths)
    if holdings:
        print(f"  ✅ Tesseract OCR: {len(holdings)}종목 추출")
        return _deduplicate(holdings)

    print("  ⚠️ OCR 추출 실패")
    return []


def _deduplicate(holdings: list[dict]) -> list[dict]:
    """중복 종목 제거 (같은 ticker가 여러 이미지에서 나온 경우)"""
    seen = {}
    for h in holdings:
        ticker = h["ticker"]
        if ticker not in seen:
            seen[ticker] = h
    return list(seen.values())


def update_portfolio_md(holdings: list[dict], output_path: str):
    """portfolio.md 파일 갱신"""
    from datetime import datetime

    lines = [
        "# Portfolio Holdings",
        f"> 최종 업데이트: {datetime.now().strftime('%Y-%m-%d')} (스크린샷 자동 추출)",
        "> ⚠️ 이 파일은 스크린샷에서 자동 갱신됩니다. 직접 편집하지 마세요.",
        "",
        "---",
        "",
    ]

    # 카테고리별 분류
    from portfolio_data import STRATEGY_GROUP
    categories = {
        "ETF (Core)": [h for h in holdings if h["ticker"] in STRATEGY_GROUP.get("etf", []) + STRATEGY_GROUP.get("cash", [])],
        "Growth": [h for h in holdings if h["ticker"] in STRATEGY_GROUP.get("growth", [])],
        "Value / Dividend": [h for h in holdings if h["ticker"] in STRATEGY_GROUP.get("value", [])],
        "Bond": [h for h in holdings if h["ticker"] in STRATEGY_GROUP.get("bond", [])],
        "Metal": [h for h in holdings if h["ticker"] in STRATEGY_GROUP.get("metal", [])],
    }

    for cat_name, cat_holdings in categories.items():
        if not cat_holdings:
            continue
        lines.append(f"## {cat_name}")
        lines.append("")
        lines.append("| Ticker | 종목명 | 보유수량 | 평가금액 | 수익금액 | 수익률 |")
        lines.append("|--------|--------|---------|---------|---------|--------|")
        for h in cat_holdings:
            name = TICKER_META.get(h["ticker"], {}).get("name", h["ticker"])
            pnl_sign = "+" if h["pnl"] >= 0 else ""
            lines.append(
                f"| {h['ticker']} | {name} | {h['shares']}주 | "
                f"${h['value']:,.2f} | {pnl_sign}${h['pnl']:,.2f} | "
                f"{pnl_sign}{h['pnl_pct']:.2f}% |"
            )
        lines.append("")

    # 합계
    total_value = sum(h["value"] for h in holdings)
    total_pnl = sum(h["pnl"] for h in holdings)
    total_pnl_pct = (total_pnl / (total_value - total_pnl) * 100) if (total_value - total_pnl) > 0 else 0

    lines.extend([
        "---",
        "",
        "## 합계",
        "",
        "| 항목 | 금액 |",
        "|------|------|",
        f"| 총 평가금액 | ${total_value:,.2f} |",
        f"| 총 수익금액 | {'+'if total_pnl>=0 else ''}${total_pnl:,.2f} |",
        f"| 총 수익률 | {'+'if total_pnl_pct>=0 else ''}{total_pnl_pct:.1f}% |",
        f"| 보유 종목 수 | {len(holdings)} |",
        "",
        "---",
        "",
        "## Ticker 목록 (fetch_market_data.py 용)",
        "```",
        " ".join(h["ticker"] for h in holdings),
        "```",
    ])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
