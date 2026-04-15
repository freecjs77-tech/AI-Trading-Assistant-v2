"""포트폴리오 파일 경로 해결 헬퍼.

설계 문서 1단계: portfolio.md → portfolios/me.md 이동 이후 하드코딩 경로를
한 곳에서 관리하기 위한 모듈. 레거시 portfolio.md 폴백을 유지해 회귀를 방지한다.
"""

from __future__ import annotations

import glob
import os
from typing import List, Tuple

PORTFOLIOS_DIRNAME = "portfolios"
LEGACY_FILENAME = "portfolio.md"
PRIMARY_OWNER = "me"
ARCHIVE_SUFFIX = "_archive.md"


def portfolios_dir(project_dir: str) -> str:
    return os.path.join(project_dir, PORTFOLIOS_DIRNAME)


def primary_portfolio_path(project_dir: str) -> str:
    """보유종목 기본 파일(me) 경로를 반환.

    우선순위:
      1) portfolios/me.md (신규 표준)
      2) portfolio.md (레거시 폴백)

    두 파일 모두 없는 경우에도 신규 경로를 반환하여 이후 로직이
    기존처럼 "파일 없음" 경고를 출력할 수 있도록 한다.
    """
    new_path = os.path.join(portfolios_dir(project_dir), f"{PRIMARY_OWNER}.md")
    if os.path.exists(new_path):
        return new_path
    legacy = os.path.join(project_dir, LEGACY_FILENAME)
    if os.path.exists(legacy):
        return legacy
    return new_path


def discover_portfolios(project_dir: str) -> List[Tuple[str, str]]:
    """portfolios/*.md 글로브로 (owner, path) 리스트 반환. archive는 제외."""
    pdir = portfolios_dir(project_dir)
    results: List[Tuple[str, str]] = []
    if os.path.isdir(pdir):
        for path in sorted(glob.glob(os.path.join(pdir, "*.md"))):
            name = os.path.basename(path)
            if name.endswith(ARCHIVE_SUFFIX):
                continue
            owner = name[:-3]  # strip .md
            results.append((owner, path))
    # 레거시 폴백: portfolios/ 디렉토리에 me.md 가 없으면 portfolio.md 를 me로 매핑
    if not any(o == PRIMARY_OWNER for o, _ in results):
        legacy = os.path.join(project_dir, LEGACY_FILENAME)
        if os.path.exists(legacy):
            results.insert(0, (PRIMARY_OWNER, legacy))
    return results
