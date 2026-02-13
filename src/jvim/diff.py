"""JSON-aware diff computation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum, auto

_STR_TO_TAG = {
    "delete": "DELETE",
    "insert": "INSERT",
    "replace": "REPLACE",
}


class DiffTag(Enum):
    EQUAL = auto()
    INSERT = auto()  # 우측에만 존재
    DELETE = auto()  # 좌측에만 존재
    REPLACE = auto()  # 양쪽 다르게 존재


@dataclass
class DiffHunk:
    """연속된 변경 블록."""

    left_start: int  # 정렬된 라인 배열에서의 시작 (0-based)
    left_count: int
    right_start: int
    right_count: int
    tag: DiffTag


@dataclass
class DiffResult:
    """Diff 결과: 정렬된 라인 배열과 태그."""

    left_lines: list[str] = field(default_factory=list)
    right_lines: list[str] = field(default_factory=list)
    left_line_tags: list[DiffTag] = field(default_factory=list)
    right_line_tags: list[DiffTag] = field(default_factory=list)
    hunks: list[DiffHunk] = field(default_factory=list)

    def append_pair(self, left: str, right: str, tag: DiffTag) -> None:
        """좌우 1쌍 추가."""
        self.left_lines.append(left)
        self.right_lines.append(right)
        self.left_line_tags.append(tag)
        self.right_line_tags.append(tag)

    def append_equal(self, left_lines: list[str], right_lines: list[str]) -> None:
        """EQUAL 라인 일괄 추가."""
        for i in range(len(left_lines)):
            self.append_pair(left_lines[i], right_lines[i], DiffTag.EQUAL)

    def append_hunk(
        self, left_lines: list[str], right_lines: list[str], tag: DiffTag
    ) -> int:
        """라인 쌍 추가 + DiffHunk 기록. 짧은 쪽은 빈 문자열로 패딩. 추가된 줄 수 반환."""
        hunk_start = len(self.left_lines)
        count = max(len(left_lines), len(right_lines))
        lc, rc = len(left_lines), len(right_lines)
        for k in range(count):
            self.append_pair(
                left_lines[k] if k < lc else "", right_lines[k] if k < rc else "", tag
            )
        if count:
            self.hunks.append(DiffHunk(hunk_start, count, hunk_start, count, tag))
        return count


# -- 포맷팅 --


def _dumps(obj: object, sort_keys: bool = False) -> str:
    return json.dumps(obj, indent=4, ensure_ascii=False, sort_keys=sort_keys)


def _try_format(content: str, sort_keys: bool) -> str:
    """JSON을 indent=4로 포맷팅. sort_keys=True면 키 정렬. 파싱 실패 시 원본 반환."""
    try:
        return _dumps(json.loads(content), sort_keys=sort_keys)
    except (json.JSONDecodeError, ValueError):
        return content


def format_json(content: str) -> str:
    """JSON을 indent=4로 포맷팅. 파싱 실패 시 원본 반환."""
    return _try_format(content, sort_keys=False)


def normalize_json(content: str) -> str:
    """JSON을 indent=4 + sort_keys로 정규화. 파싱 실패 시 원본 반환."""
    return _try_format(content, sort_keys=True)


def _format_jsonl_records(content: str, sort_keys: bool) -> list[str]:
    """JSONL을 레코드별 포맷팅된 문자열 리스트로 변환."""
    records: list[str] = []
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(_dumps(json.loads(stripped), sort_keys=sort_keys))
        except json.JSONDecodeError:
            records.append(stripped)
    return records


def format_jsonl(content: str) -> str:
    """JSONL 레코드별 indent=4 포맷팅. 빈 줄로 구분."""
    return "\n\n".join(_format_jsonl_records(content, sort_keys=False))


def normalize_jsonl(content: str) -> str:
    """JSONL 레코드별 indent=4 + sort_keys 정규화. 빈 줄로 구분."""
    return "\n\n".join(_format_jsonl_records(content, sort_keys=True))


# -- Diff 계산 --


def _line_diff(
    result: DiffResult, left_lines: list[str], right_lines: list[str]
) -> None:
    """변경된 레코드 내부를 라인 단위 diff."""
    matcher = SequenceMatcher(None, left_lines, right_lines)
    hunk_start = len(result.left_lines)
    total = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.append_equal(left_lines[i1:i2], right_lines[j1:j2])
            total += i2 - i1
        else:
            dt = DiffTag[_STR_TO_TAG[tag]]
            mc = max(i2 - i1, j2 - j1)
            lc, rc = i2 - i1, j2 - j1
            for k in range(mc):
                result.append_pair(
                    left_lines[i1 + k] if k < lc else "",
                    right_lines[j1 + k] if k < rc else "",
                    dt,
                )
            total += mc
    if total:
        result.hunks.append(
            DiffHunk(hunk_start, total, hunk_start, total, DiffTag.REPLACE)
        )


def compute_json_diff(
    left: str, right: str, normalize: bool = True, jsonl: bool = False
) -> DiffResult:
    """두 JSON 문자열의 diff를 계산하여 정렬된 결과를 반환."""
    if jsonl:
        return _compute_jsonl_diff(left, right, normalize)
    fmt = normalize_json if normalize else format_json
    return _compute_line_diff(fmt(left).split("\n"), fmt(right).split("\n"))


_FULL_DIFF_LIMIT = 50_000


def _detect_blocks(lines: list[str]) -> tuple[int, int] | None:
    """indent별 {/[ 개수 집계, 최다 indent 반환. 최소 4블록이어야 유효."""
    indent_counts: dict[int, int] = {}
    for line in lines:
        stripped = line.lstrip()
        if stripped and stripped[0] in ("{", "["):
            indent = len(line) - len(stripped)
            indent_counts[indent] = indent_counts.get(indent, 0) + 1
    if not indent_counts:
        return None
    best_indent = max(indent_counts, key=indent_counts.get)
    count = indent_counts[best_indent]
    if count < 4:
        return None
    return (best_indent, count)


def _build_segments(lines: list[str], target_indent: int) -> list[tuple[int, int]]:
    """indent 기반 블록+gap 경계를 세그먼트 리스트로 분할."""
    segments: list[tuple[int, int]] = []
    block_start: int | None = None
    gap_start = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped:
            continue
        indent = len(line) - len(stripped)
        if indent != target_indent:
            continue
        ch = stripped[0]
        if ch in ("{", "[") and block_start is None:
            if gap_start < i:
                segments.append((gap_start, i))
            block_start = i
        elif ch in ("}", "]") and block_start is not None:
            segments.append((block_start, i + 1))
            gap_start = i + 1
            block_start = None
    # 미완료 블록 또는 후행 gap
    if block_start is not None:
        segments.append((block_start, len(lines)))
    elif gap_start < len(lines):
        segments.append((gap_start, len(lines)))
    return segments


def _handle_replace_segments(
    result: DiffResult,
    left_src: list[str],
    right_src: list[str],
    left_segs: list[tuple[int, int]],
    right_segs: list[tuple[int, int]],
) -> None:
    """replace 세그먼트 쌍의 라인 diff. 초과분은 DELETE/INSERT."""
    paired = min(len(left_segs), len(right_segs))
    for k in range(paired):
        ls, le = left_segs[k]
        rs, re = right_segs[k]
        l_lines = left_src[ls:le]
        r_lines = right_src[rs:re]
        if l_lines == r_lines:
            result.append_equal(l_lines, r_lines)
        else:
            _line_diff(result, l_lines, r_lines)
    for k in range(paired, len(left_segs)):
        ls, le = left_segs[k]
        result.append_hunk(left_src[ls:le], [], DiffTag.DELETE)
    for k in range(paired, len(right_segs)):
        rs, re = right_segs[k]
        result.append_hunk([], right_src[rs:re], DiffTag.INSERT)


def _compute_block_diff(
    left_src: list[str],
    right_src: list[str],
    left_segs: list[tuple[int, int]],
    right_segs: list[tuple[int, int]],
) -> DiffResult:
    """세그먼트 단위 SequenceMatcher로 diff 계산."""
    left_keys = ["\n".join(left_src[s:e]) for s, e in left_segs]
    right_keys = ["\n".join(right_src[s:e]) for s, e in right_segs]
    matcher = SequenceMatcher(None, left_keys, right_keys)
    result = DiffResult()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                ls, le = left_segs[i1 + k]
                rs, re = right_segs[j1 + k]
                result.append_equal(left_src[ls:le], right_src[rs:re])
        elif tag == "delete":
            for k in range(i2 - i1):
                ls, le = left_segs[i1 + k]
                result.append_hunk(left_src[ls:le], [], DiffTag.DELETE)
        elif tag == "insert":
            for k in range(j2 - j1):
                rs, re = right_segs[j1 + k]
                result.append_hunk([], right_src[rs:re], DiffTag.INSERT)
        elif tag == "replace":
            _handle_replace_segments(
                result, left_src, right_src, left_segs[i1:i2], right_segs[j1:j2]
            )

    return result


def _make_full_replace(left_src: list[str], right_src: list[str]) -> DiffResult:
    """대용량 폴백: 전체를 단일 REPLACE hunk로 처리."""
    result = DiffResult()
    result.append_hunk(left_src, right_src, DiffTag.REPLACE)
    return result


def _compute_line_diff_full(left_src: list[str], right_src: list[str]) -> DiffResult:
    """기존 라인 단위 SequenceMatcher diff. 대용량 시 전체 REPLACE 폴백."""
    if len(left_src) + len(right_src) > _FULL_DIFF_LIMIT:
        return _make_full_replace(left_src, right_src)

    matcher = SequenceMatcher(None, left_src, right_src)
    result = DiffResult()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            result.append_equal(left_src[i1:i2], right_src[j1:j2])
        elif tag == "delete":
            result.append_hunk(left_src[i1:i2], [], DiffTag.DELETE)
        elif tag == "insert":
            result.append_hunk([], right_src[j1:j2], DiffTag.INSERT)
        elif tag == "replace":
            result.append_hunk(left_src[i1:i2], right_src[j1:j2], DiffTag.REPLACE)

    return result


def _compute_line_diff(left_src: list[str], right_src: list[str]) -> DiffResult:
    """라인 배열의 diff를 계산. 블록 구조 감지 시 블록 단위 최적화 적용."""
    left_blocks = _detect_blocks(left_src)
    right_blocks = _detect_blocks(right_src)
    # 양쪽 블록 indent가 일치하면 블록 단위 diff
    if left_blocks and right_blocks and left_blocks[0] == right_blocks[0]:
        target_indent = left_blocks[0]
        left_segs = _build_segments(left_src, target_indent)
        right_segs = _build_segments(right_src, target_indent)
        return _compute_block_diff(left_src, right_src, left_segs, right_segs)
    return _compute_line_diff_full(left_src, right_src)


# -- JSONL diff --


def _jsonl_sep(result: DiffResult, tag: DiffTag, first: bool) -> bool:
    """JSONL 레코드 구분 빈 줄 삽입. first가 True면 스킵. 항상 False 반환."""
    if not first:
        result.append_pair("", "", tag)
    return False


def _compute_jsonl_diff(left: str, right: str, normalize: bool) -> DiffResult:
    """JSONL 레코드 단위 diff: 레코드 매칭 후 변경분만 라인 diff."""
    left_records = _format_jsonl_records(left, sort_keys=normalize)
    right_records = _format_jsonl_records(right, sort_keys=normalize)

    matcher = SequenceMatcher(None, left_records, right_records)
    result = DiffResult()
    first = True

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                first = _jsonl_sep(result, DiffTag.EQUAL, first)
                for line in left_records[i1 + k].split("\n"):
                    result.append_pair(line, line, DiffTag.EQUAL)

        elif tag == "delete":
            for k in range(i2 - i1):
                first = _jsonl_sep(result, DiffTag.DELETE, first)
                result.append_hunk(left_records[i1 + k].split("\n"), [], DiffTag.DELETE)

        elif tag == "insert":
            for k in range(j2 - j1):
                first = _jsonl_sep(result, DiffTag.INSERT, first)
                result.append_hunk(
                    [], right_records[j1 + k].split("\n"), DiffTag.INSERT
                )

        elif tag == "replace":
            l_count, r_count = i2 - i1, j2 - j1
            paired = min(l_count, r_count)
            for k in range(paired):
                first = _jsonl_sep(result, DiffTag.REPLACE, first)
                l_lines = left_records[i1 + k].split("\n")
                r_lines = right_records[j1 + k].split("\n")
                if left_records[i1 + k] == right_records[j1 + k]:
                    for line in l_lines:
                        result.append_pair(line, line, DiffTag.EQUAL)
                else:
                    _line_diff(result, l_lines, r_lines)
            for k in range(paired, l_count):
                first = _jsonl_sep(result, DiffTag.DELETE, first)
                result.append_hunk(left_records[i1 + k].split("\n"), [], DiffTag.DELETE)
            for k in range(paired, r_count):
                first = _jsonl_sep(result, DiffTag.INSERT, first)
                result.append_hunk(
                    [], right_records[j1 + k].split("\n"), DiffTag.INSERT
                )

    return result
