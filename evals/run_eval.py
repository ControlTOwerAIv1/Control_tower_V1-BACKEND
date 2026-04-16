"""
Run QA evaluation against the live /api/chat endpoint.

Usage:
  python evals/run_eval.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List
from urllib import error, request

CITATION_PATTERN = re.compile(r"\[(S|D)\d+\]")


@dataclass
class EvalResult:
    id: int
    question: str
    status_code: int
    ok_http: bool
    has_answer: bool
    has_citation: bool
    from_cache: bool | None
    latency_ms: int
    error: str | None
    answer_preview: str


@dataclass
class EvalSummary:
    run_at: str
    base_url: str
    endpoint: str
    eval_file: str
    total: int
    http_success_count: int
    answer_success_count: int
    citation_count: int
    http_success_rate: float
    answer_success_rate: float
    citation_coverage_rate: float
    overall_pass: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run inventory QA eval set against chat API.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--endpoint", default="/api/chat", help="Chat endpoint path")
    parser.add_argument(
        "--eval-file",
        default="evals/inventory_qa_eval_set.json",
        help="Path to eval question set JSON",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional output report path. Defaults to evals/reports/eval_report_<timestamp>.json",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    parser.add_argument(
        "--min-answer-success-rate",
        type=float,
        default=0.95,
        help="Minimum answer success rate required for overall pass",
    )
    parser.add_argument(
        "--min-citation-coverage",
        type=float,
        default=0.70,
        help="Minimum citation coverage required for overall pass",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at first HTTP or parsing failure",
    )
    return parser.parse_args()


def load_eval_questions(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Eval file not found: {path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Eval file must be a JSON array of {id, question} objects")

    normalized: List[Dict[str, Any]] = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("Each eval row must be a JSON object")
        if "id" not in row or "question" not in row:
            raise ValueError("Each eval row must have 'id' and 'question'")
        normalized.append({"id": int(row["id"]), "question": str(row["question"])})

    return normalized


def build_url(base_url: str, endpoint: str) -> str:
    return base_url.rstrip("/") + "/" + endpoint.lstrip("/")


def detect_citation(answer: str) -> bool:
    if not answer:
        return False
    if "Sources:" in answer:
        return True
    return bool(CITATION_PATTERN.search(answer))


def post_chat_question(url: str, question: str, timeout: int) -> tuple[int, Dict[str, Any], int]:
    body = json.dumps({"question": question}).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            status = int(resp.status)
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="ignore") if exc.fp else ""
        status = int(exc.code)
        latency_ms = int((time.perf_counter() - t0) * 1000)
        try:
            payload = json.loads(raw) if raw else {}
        except Exception:
            payload = {"raw": raw}
        return status, payload, latency_ms

    latency_ms = int((time.perf_counter() - t0) * 1000)

    try:
        payload = json.loads(raw) if raw else {}
    except Exception as exc:
        raise RuntimeError(f"Invalid JSON response: {exc}") from exc

    return status, payload, latency_ms


def run_eval(args: argparse.Namespace) -> Dict[str, Any]:
    eval_path = Path(args.eval_file)
    questions = load_eval_questions(eval_path)
    url = build_url(args.base_url, args.endpoint)

    results: List[EvalResult] = []
    http_success_count = 0
    answer_success_count = 0
    citation_count = 0

    for row in questions:
        qid = row["id"]
        question = row["question"]

        status_code = 0
        payload: Dict[str, Any] = {}
        latency_ms = 0
        err_msg = None

        try:
            status_code, payload, latency_ms = post_chat_question(url, question, args.timeout)
            ok_http = status_code == 200
            answer = str(payload.get("answer", "")).strip()
            has_answer = bool(answer)
            has_citation = detect_citation(answer)
            from_cache = payload.get("from_cache")

            if ok_http:
                http_success_count += 1
            if ok_http and has_answer:
                answer_success_count += 1
            if ok_http and has_answer and has_citation:
                citation_count += 1

            result = EvalResult(
                id=qid,
                question=question,
                status_code=status_code,
                ok_http=ok_http,
                has_answer=has_answer,
                has_citation=has_citation,
                from_cache=from_cache if isinstance(from_cache, bool) else None,
                latency_ms=latency_ms,
                error=None,
                answer_preview=answer[:200],
            )
            results.append(result)

            if args.fail_fast and (not ok_http or not has_answer):
                break

        except Exception as exc:
            err_msg = str(exc)
            result = EvalResult(
                id=qid,
                question=question,
                status_code=status_code,
                ok_http=False,
                has_answer=False,
                has_citation=False,
                from_cache=None,
                latency_ms=latency_ms,
                error=err_msg,
                answer_preview="",
            )
            results.append(result)
            if args.fail_fast:
                break

    total = len(results)
    http_success_rate = round(http_success_count / total, 4) if total else 0.0
    answer_success_rate = round(answer_success_count / total, 4) if total else 0.0
    citation_coverage_rate = round(citation_count / total, 4) if total else 0.0

    overall_pass = (
        answer_success_rate >= float(args.min_answer_success_rate)
        and citation_coverage_rate >= float(args.min_citation_coverage)
    )

    summary = EvalSummary(
        run_at=datetime.now(timezone.utc).isoformat(),
        base_url=args.base_url,
        endpoint=args.endpoint,
        eval_file=str(eval_path),
        total=total,
        http_success_count=http_success_count,
        answer_success_count=answer_success_count,
        citation_count=citation_count,
        http_success_rate=http_success_rate,
        answer_success_rate=answer_success_rate,
        citation_coverage_rate=citation_coverage_rate,
        overall_pass=overall_pass,
    )

    return {
        "summary": asdict(summary),
        "results": [asdict(r) for r in results],
    }


def resolve_output_path(args: argparse.Namespace) -> Path:
    if args.output:
        return Path(args.output)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return Path("evals/reports") / f"eval_report_{stamp}.json"


def main() -> int:
    args = parse_args()

    try:
        report = run_eval(args)
    except Exception as exc:
        print(f"Eval run failed: {exc}", file=sys.stderr)
        return 2

    output_path = resolve_output_path(args)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = report["summary"]
    print("Eval completed")
    print(f"- Total: {summary['total']}")
    print(f"- HTTP success rate: {summary['http_success_rate']:.2%}")
    print(f"- Answer success rate: {summary['answer_success_rate']:.2%}")
    print(f"- Citation coverage: {summary['citation_coverage_rate']:.2%}")
    print(f"- Overall pass: {summary['overall_pass']}")
    print(f"- Report: {output_path}")

    return 0 if summary["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
