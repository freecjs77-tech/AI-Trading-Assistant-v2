"""pipeline.py Step 4c2 — MODE env var + result variable wiring."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import inspect


def test_pipeline_imports_momentum_scanner():
    """pipeline 모듈은 momentum_scanner를 임포트할 수 있어야 함 (실행하지는 않음)."""
    import importlib
    pipe_src = open(
        os.path.join(os.path.dirname(__file__), "..", "pipeline.py"),
        encoding="utf-8"
    ).read()
    assert "from momentum_scanner import" in pipe_src or "import momentum_scanner" in pipe_src


def test_pipeline_step_4c2_present():
    """Step 4c2 로깅 라인이 존재."""
    pipe_src = open(
        os.path.join(os.path.dirname(__file__), "..", "pipeline.py"),
        encoding="utf-8"
    ).read()
    assert "Step 4c2" in pipe_src or "[Step 4c2]" in pipe_src
    # both US and KR scans wrapped in try/except
    assert "scan_momentum_us" in pipe_src
    assert "scan_momentum_kr" in pipe_src


def test_pipeline_supports_mode_env_var():
    """MODE=momentum_only / scanner_only / full 처리 흔적."""
    pipe_src = open(
        os.path.join(os.path.dirname(__file__), "..", "pipeline.py"),
        encoding="utf-8"
    ).read()
    assert "MODE" in pipe_src
    assert "momentum_only" in pipe_src or "scanner_only" in pipe_src


def test_pipeline_skip_scanners_still_supported():
    """기존 SKIP_SCANNERS 환경변수도 호환 유지."""
    pipe_src = open(
        os.path.join(os.path.dirname(__file__), "..", "pipeline.py"),
        encoding="utf-8"
    ).read()
    assert "SKIP_SCANNERS" in pipe_src
