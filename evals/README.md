# Evaluation Runner

This folder contains the QA evaluation set and a runner script for the live chat API.

## Files
- `inventory_qa_eval_set.json`: Question set (24 prompts)
- `run_eval.py`: Executes questions against `/api/chat` and writes a report

## Run
```powershell
python evals/run_eval.py --base-url http://localhost:8000
```

## Options
- `--endpoint /api/chat`
- `--eval-file evals/inventory_qa_eval_set.json`
- `--output evals/reports/custom_report.json`
- `--timeout 30`
- `--min-answer-success-rate 0.95`
- `--min-citation-coverage 0.70`
- `--fail-fast`

## Output
A JSON report is written to `evals/reports/` by default and includes:
- summary metrics (HTTP success, answer success, citation coverage, overall pass)
- per-question details (status, latency, answer preview, error)
