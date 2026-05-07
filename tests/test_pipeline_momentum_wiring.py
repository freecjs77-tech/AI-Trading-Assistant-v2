"""pipeline.py wiring of momentum results into report + pages + charts + details."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _read_pipeline():
    return open(
        os.path.join(os.path.dirname(__file__), "..", "pipeline.py"),
        encoding="utf-8"
    ).read()


def test_generate_report_receives_momentum_args():
    src = _read_pipeline()
    # generate_report 호출에 momentum_us=..., momentum_kr=... 인자 추가
    assert "momentum_us=momentum_us_result" in src
    assert "momentum_kr=momentum_kr_result" in src


def test_pipeline_calls_generate_momentum_pages():
    src = _read_pipeline()
    assert "generate_momentum_pages" in src
    # 호출 시 두 결과 + output_dir 전달
    assert "momentum_us=momentum_us_result" in src
    assert "momentum_kr=momentum_kr_result" in src


def test_chart_extra_tickers_includes_momentum_signals():
    src = _read_pipeline()
    # 모멘텀 시그널 종목 → extra_tickers에 추가하는 흔적
    assert "MOMENTUM_3" in src or "momentum_signal_tickers" in src


def test_generate_detail_pages_receives_momentum_history():
    src = _read_pipeline()
    # generate_detail_pages 호출에 momentum_us_history / momentum_kr_history
    assert "momentum_us_history" in src
    assert "momentum_kr_history" in src
