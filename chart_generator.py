"""
chart_generator.py -- mplfinance 기반 기술 차트 생성
AI Trading Assistant v3.0

각 종목별 캔들차트 + MA + BB + Volume + RSI + MACD 서브플롯을 PNG로 생성.
"""

import os
import sys

import numpy as np
import pandas as pd
import yfinance as yf
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def _calc_macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def generate_chart(symbol: str, output_path: str, days: int = 120, theme: str = "dark") -> bool:
    """
    종목 차트를 PNG로 생성.
    theme: "dark" 또는 "light"
    반환: 성공 여부
    """
    try:
        # KOSPI 종목(숫자 ticker) → .KS 접미사 추가 (yfinance 호환)
        yf_symbol = f"{symbol}.KS" if symbol.isdigit() else symbol.replace("_KS", ".KS")
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period="1y", interval="1d", auto_adjust=True)

        if df is None or df.empty or len(df) < 50:
            return False

        # 최근 N일만 사용
        df = df.tail(days).copy()

        # 이동평균
        ma20 = df["Close"].rolling(20).mean()
        ma50 = df["Close"].rolling(50).mean()

        # 볼린저 밴드
        bb_mid = df["Close"].rolling(20).mean()
        bb_std = df["Close"].rolling(20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        # RSI
        rsi = _calc_rsi(df["Close"])

        # MACD
        macd_line, signal_line, macd_hist = _calc_macd(df["Close"])

        # 테마별 스타일
        if theme == "light":
            # MACD 히스토그램 색상 (라이트: 블루/레드)
            macd_colors = ["#2563EB" if v >= 0 else "#E11D48" for v in macd_hist.fillna(0)]
            chart_style = mpf.make_mpf_style(
                base_mpf_style="charles",
                marketcolors=mpf.make_marketcolors(
                    up="#2563EB", down="#E11D48",
                    edge={"up": "#2563EB", "down": "#E11D48"},
                    wick={"up": "#2563EB", "down": "#E11D48"},
                    volume={"up": "#2563EB80", "down": "#E11D4880"},
                ),
                facecolor="#FFFFFF",
                edgecolor="#E2E8F0",
                figcolor="#F8FAFC",
                gridcolor="#E2E8F0",
                gridstyle="--",
                gridaxis="both",
                y_on_right=True,
                rc={
                    "axes.labelcolor": "#334155",
                    "xtick.color": "#64748B",
                    "ytick.color": "#64748B",
                    "font.size": 9,
                },
            )
            legend_face = "#FFFFFF"
            legend_edge = "#E2E8F0"
            legend_label = "#334155"
            fig_save_color = "#F8FAFC"
        else:
            chart_style = mpf.make_mpf_style(
                base_mpf_style="nightclouds",
                marketcolors=mpf.make_marketcolors(
                    up="#10B981", down="#EF4444",
                    edge={"up": "#10B981", "down": "#EF4444"},
                    wick={"up": "#10B981", "down": "#EF4444"},
                    volume={"up": "#10B98180", "down": "#EF444480"},
                ),
                facecolor="#0A1525",
                edgecolor="#1A3050",
                figcolor="#060D18",
                gridcolor="#1A3050",
                gridstyle="--",
                gridaxis="both",
                y_on_right=True,
                rc={
                    "axes.labelcolor": "#94A3B8",
                    "xtick.color": "#64748B",
                    "ytick.color": "#64748B",
                    "font.size": 9,
                },
            )
            # MACD 히스토그램 색상 (다크: 그린/레드)
            macd_colors = ["#10B981" if v >= 0 else "#EF4444" for v in macd_hist.fillna(0)]
            legend_face = "#0A1525"
            legend_edge = "#1A3050"
            legend_label = "#94A3B8"
            fig_save_color = "#060D18"

        # 추가 플롯 구성
        add_plots = [
            # MA 오버레이
            mpf.make_addplot(ma20, color="#06B6D4", width=1.0, linestyle="-"),     # cyan
            mpf.make_addplot(ma50, color="#F59E0B", width=1.0, linestyle="-"),     # orange
            # 볼린저 밴드
            mpf.make_addplot(bb_upper, color="#8B5CF6", width=0.7, linestyle="--"),  # purple 점선
            mpf.make_addplot(bb_lower, color="#8B5CF6", width=0.7, linestyle="--"),  # purple 점선
            # RSI 서브플롯
            mpf.make_addplot(rsi, panel=2, color="#06B6D4", width=1.0, ylabel="RSI"),
            # MACD 서브플롯
            mpf.make_addplot(macd_line, panel=3, color="#2563EB", width=1.0, ylabel="MACD"),
            mpf.make_addplot(signal_line, panel=3, color="#F59E0B", width=1.0),
            mpf.make_addplot(macd_hist, panel=3, type="bar", color=macd_colors, width=0.7),
        ]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        fig, axes = mpf.plot(
            df,
            type="candle",
            style=chart_style,
            addplot=add_plots,
            volume=True,
            volume_panel=1,
            panel_ratios=(4, 1, 1.2, 1.2),
            figsize=(10, 7),
            tight_layout=True,
            returnfig=True,
            xrotation=0,
            datetime_format="%m/%d",
        )

        # RSI 기준선 (30, 70)
        rsi_ax = axes[4]  # panel 2 = axes[4] (main=0, vol=2, rsi=4, macd=6)
        rsi_ax.axhline(y=70, color="#EF4444", linewidth=0.6, linestyle="--", alpha=0.6)
        rsi_ax.axhline(y=30, color="#10B981", linewidth=0.6, linestyle="--", alpha=0.6)
        rsi_ax.set_ylim(10, 90)

        # MACD 0선
        macd_ax = axes[6]  # panel 3
        macd_ax.axhline(y=0, color="#64748B", linewidth=0.5, linestyle="-", alpha=0.5)

        # 범례 (메인 차트) — Line2D 프록시로 색상 정확 매칭
        from matplotlib.lines import Line2D
        legend_items = [
            Line2D([0], [0], color="#06B6D4", linewidth=1.5, label="MA20"),
            Line2D([0], [0], color="#F59E0B", linewidth=1.5, label="MA50"),
            Line2D([0], [0], color="#8B5CF6", linewidth=1.0, linestyle="--", label="BB Upper"),
            Line2D([0], [0], color="#8B5CF6", linewidth=1.0, linestyle="--", label="BB Lower"),
        ]
        main_ax = axes[0]
        main_ax.legend(
            handles=legend_items,
            loc="upper left",
            fontsize=8,
            framealpha=0.5,
            facecolor=legend_face,
            edgecolor=legend_edge,
            labelcolor=legend_label,
        )

        fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig_save_color)
        matplotlib.pyplot.close(fig)
        return True

    except Exception as e:
        print(f"  WARN chart failed for {symbol}: {e}", file=sys.stderr)
        return False


def generate_all_charts(tickers: list[str], output_dir: str) -> dict:
    """
    전체 종목 차트 배치 생성 (dark + light 2벌).
    반환: {ticker: output_path} (dark 기준, 성공한 것만)
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}
    for ticker in tickers:
        out_dark = os.path.join(output_dir, f"{ticker}.png")
        out_light = os.path.join(output_dir, f"{ticker}_light.png")
        ok = generate_chart(ticker, out_dark, theme="dark")
        if ok:
            results[ticker] = out_dark
            generate_chart(ticker, out_light, theme="light")
    return results


if __name__ == "__main__":
    # 테스트: 단일 종목 (dark + light)
    symbol = sys.argv[1] if len(sys.argv) > 1 else "NVDA"
    out_dark = f"reports/details/charts/{symbol}.png"
    out_light = f"reports/details/charts/{symbol}_light.png"
    ok1 = generate_chart(symbol, out_dark, theme="dark")
    ok2 = generate_chart(symbol, out_light, theme="light")
    print(f"dark: {'OK' if ok1 else 'FAIL'} | light: {'OK' if ok2 else 'FAIL'}")
