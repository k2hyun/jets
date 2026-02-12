# jvim 프로젝트 규칙

## 프로젝트 개요
Textual 기반 vim 스타일 JSON 편집기 (TUI). Python 3.10+.

## 코드 구조
- `src/jvim/widget.py` — 핵심 에디터 위젯 (`JsonEditor`). 모드 처리, 렌더링, 키 바인딩 모두 여기에 집중
- `src/jvim/editor.py` — 앱 레벨 (`JsonEditorApp`). 파일 I/O, EJ 패널 관리, JSONL 처리
- `src/jvim/differ.py` — diff 뷰어 (`jvimdiff`/`jvd`)
- `src/jvim/data/help.json` — 인라인 도움말 데이터 (`:help` 명령)
- `tests/test_editor.py` — 위젯 단위 테스트

## 버전 파일 위치
버전 변경 시 아래 두 파일을 반드시 동시에 업데이트:
- `pyproject.toml` (`version` 필드)
- `src/jvim/__init__.py` (`__version__`)

## 문서
기능 추가/변경 시 아래 모두 업데이트:
- `README.md` (영문)
- `README.kr.md` (한국어)
- `src/jvim/data/help.json` (인라인 도움말 — 기능에 키 바인딩이 있는 경우)

## 빌드 & 배포
```bash
python -m build              # 빌드
twine upload dist/*          # PyPI 업로드
gh release create v{버전}    # GitHub 릴리즈
```

## 테스트 & 린팅
```bash
pytest tests/ -v             # 테스트
ruff check src/ tests/       # 린트
ruff format src/ tests/      # 포맷
```

## 테스트 패턴
- `JsonEditor` 위젯을 직접 인스턴스화하여 테스트
- `_handle_normal(key)`, `_handle_insert(key)` 등 내부 메서드 직접 호출
- 테스트 클래스는 기능 단위로 그룹화 (예: `TestVisualMode`, `TestFolding`)

## 주의사항
- `widget.py`가 매우 크므로 코드 삽입/삭제 시 인접 분기 누락에 주의 (특히 elif 체인)
