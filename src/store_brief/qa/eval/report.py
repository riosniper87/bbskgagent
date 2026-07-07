"""Write eval reports and aggregate summaries."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from store_brief.qa.eval.schema import EvalResult, EvalRunSummary


def _mermaid_flow(summary: EvalRunSummary) -> str:
  """Build mermaid flowchart for latest run pipeline status."""
  n = summary.n_cases or 1
  ret_ok = int(summary.retrieval_hit_at_1_rate * n)
  att_ok = int(summary.attachment_match_rate * n)
  ans_ok = int(summary.answer_adequacy_rate * n)
  passed = summary.n_passed
  return f"""flowchart LR
  Suggest["Suggest {n}"] --> Ask["Ask {n}"]
  Ask --> Ret["Retrieval@1 {ret_ok}/{n}"]
  Ret --> Att["Attachment {att_ok}/{n}"]
  Att --> Judge["Answer {ans_ok}/{n}"]
  Judge --> Pass["Pass {passed}/{n}"]
  Pass -->|"< {summary.threshold:.0%}"| Fail["Troubleshoot"]
  Pass -->|">= {summary.threshold:.0%}"| Done["Done"]"""


def write_run_report(summary: EvalRunSummary, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    summary.mermaid_flow = _mermaid_flow(summary)
    report_path = out_dir / "report.json"
    report_path.write_text(
        summary.model_dump_json(indent=2),
        encoding="utf-8",
    )

    failures = [r for r in summary.results if not r.passed]
    failures_path = out_dir / "failures.jsonl"
    with failures_path.open("w", encoding="utf-8") as f:
        for r in failures:
            f.write(r.model_dump_json() + "\n")

    return report_path


def update_global_summary(
    data_dir: Path,
    summary: EvalRunSummary,
    *,
    max_runs: int = 30,
) -> Path:
    """Append run to data/eval/summary.json for canvas dashboard."""
    eval_root = data_dir / "eval"
    eval_root.mkdir(parents=True, exist_ok=True)
    summary_path = eval_root / "summary.json"

    existing: dict = {"runs": []}
    if summary_path.is_file():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {"runs": []}

    run_entry = {
        "run_id": summary.run_id,
        "as_of": summary.as_of,
        "started_at": summary.started_at,
        "n_cases": summary.n_cases,
        "n_passed": summary.n_passed,
        "overall_pass_rate": summary.overall_pass_rate,
        "retrieval_hit_at_1_rate": summary.retrieval_hit_at_1_rate,
        "retrieval_hit_at_3_rate": summary.retrieval_hit_at_3_rate,
        "attachment_match_rate": summary.attachment_match_rate,
        "damdang_match_rate": summary.damdang_match_rate,
        "answer_adequacy_rate": summary.answer_adequacy_rate,
        "threshold": summary.threshold,
        "failure_counts": summary.failure_counts,
        "mermaid_flow": summary.mermaid_flow,
        "failures": [
            {
                "question": r.case.question[:80],
                "failure_type": r.failure_type,
                "post_id": r.case.post_id,
                "source_label": r.case.source_label,
                "top_hit_attachment": r.top_hit_attachment,
                "judge_verdict": r.layers.judge_verdict,
                "suggested_prompt": r.suggested_prompt[:500],
            }
            for r in summary.results
            if not r.passed
        ][:10],
    }

    runs: list = existing.get("runs", [])
    runs = [r for r in runs if r.get("run_id") != summary.run_id]
    runs.append(run_entry)
    runs = sorted(runs, key=lambda x: x.get("started_at", ""), reverse=True)[:max_runs]

    existing["runs"] = runs
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    summary_path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    sync_canvas_dashboard(data_dir, existing)
    return summary_path


def sync_canvas_dashboard(data_dir: Path, summary_data: dict | None = None) -> Path | None:
    """Regenerate canvas with embedded eval summary data."""
    if summary_data is None:
        summary_path = data_dir / "eval" / "summary.json"
        if not summary_path.is_file():
            return None
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))

    runs = summary_data.get("runs", [])
    if not runs:
        return None

    canvas_dir = Path.home() / ".cursor" / "projects" / "c-Users-4250090-Documents-anaylsis" / "canvases"
    canvas_path = canvas_dir / "qa-eval-dashboard.canvas.tsx"
    if not canvas_dir.parent.exists():
        return None

    data_json = json.dumps(summary_data, ensure_ascii=False, indent=2)
    content = _CANVAS_TEMPLATE.replace("__EVAL_DATA__", data_json)
    canvas_dir.mkdir(parents=True, exist_ok=True)
    canvas_path.write_text(content, encoding="utf-8")
    return canvas_path


_CANVAS_TEMPLATE = r'''import {
  BarChart, Card, CardBody, CardHeader, Grid, H1, H2, Row, Stack, Stat, Table, Text, useHostTheme,
} from "cursor/canvas";

const EVAL_DATA = __EVAL_DATA__ as {
  runs: Array<{
    run_id: string;
    started_at: string;
    n_cases: number;
    n_passed: number;
    overall_pass_rate: number;
    retrieval_hit_at_1_rate: number;
    attachment_match_rate: number;
    answer_adequacy_rate: number;
    threshold: number;
    failure_counts: Record<string, number>;
    failures: Array<{
      question: string;
      failure_type: string | null;
      post_id: string;
      source_label: string;
      top_hit_attachment: string | null;
      judge_verdict: string;
    }>;
  }>;
  updated_at?: string;
};

export default function QaEvalDashboard() {
  const theme = useHostTheme();
  const runs = [...(EVAL_DATA.runs || [])].sort(
    (a, b) => a.started_at.localeCompare(b.started_at),
  );
  const latest = runs[runs.length - 1];
  const history = runs.slice(-14);

  const failureTypes = latest
    ? Object.entries(latest.failure_counts || {}).map(([k, v]) => ({ label: k, value: v }))
    : [];

  const historyPoints = history.map((r) => ({
    label: r.started_at.slice(5, 16).replace("T", " "),
    pass: Math.round(r.overall_pass_rate * 100),
    hit1: Math.round(r.retrieval_hit_at_1_rate * 100),
    attach: Math.round(r.attachment_match_rate * 100),
  }));

  const failRows = (latest?.failures || []).map((f, i) => ({
    id: String(i),
    question: f.question,
    type: f.failure_type || "—",
    source: f.source_label,
    topHit: f.top_hit_attachment || "—",
    verdict: f.judge_verdict,
  }));

  return (
    <Stack gap={theme.spacing.lg} style={{ padding: theme.spacing.lg }}>
      <Stack gap={theme.spacing.xs}>
        <H1>QA Eval Dashboard</H1>
        <Text tone="secondary">
          Source: data/eval/summary.json · updated {EVAL_DATA.updated_at?.slice(0, 19) || "—"}
        </Text>
      </Stack>

      {latest && (
        <Grid columns={4} gap={theme.spacing.md}>
          <Stat label="Pass rate" value={`${Math.round(latest.overall_pass_rate * 100)}%`} />
          <Stat label="Retrieval@1" value={`${Math.round(latest.retrieval_hit_at_1_rate * 100)}%`} />
          <Stat label="Attachment" value={`${Math.round(latest.attachment_match_rate * 100)}%`} />
          <Stat label="Answer" value={`${Math.round(latest.answer_adequacy_rate * 100)}%`} />
        </Grid>
      )}

      {historyPoints.length > 1 && (
        <Card>
          <CardHeader title="Run history (%)" />
          <CardBody>
            <BarChart
              data={historyPoints}
              xKey="label"
              series={[
                { key: "pass", label: "Pass rate" },
                { key: "hit1", label: "Retrieval@1" },
                { key: "attach", label: "Attachment" },
              ]}
              height={220}
            />
            <Text tone="secondary" size="sm">Last {historyPoints.length} runs · y-axis: percent</Text>
          </CardBody>
        </Card>
      )}

      {failureTypes.length > 0 && (
        <Card>
          <CardHeader title={`Failure breakdown — ${latest?.run_id || ""}`} />
          <CardBody>
            <Row gap={theme.spacing.md} wrap>
              {failureTypes.map((ft) => (
                <Stat key={ft.label} label={ft.label} value={String(ft.value)} />
              ))}
            </Row>
          </CardBody>
        </Card>
      )}

      {latest && (
        <Card>
          <CardHeader title="Pipeline (latest run)" />
          <CardBody>
            <Text>
              Suggest({latest.n_cases}) → Ask → Retrieval@1({Math.round(latest.retrieval_hit_at_1_rate * latest.n_cases)}/{latest.n_cases})
              → Attachment({Math.round(latest.attachment_match_rate * latest.n_cases)}/{latest.n_cases})
              → Answer({Math.round(latest.answer_adequacy_rate * latest.n_cases)}/{latest.n_cases})
              → Pass({latest.n_passed}/{latest.n_cases})
            </Text>
            <Text tone="secondary" size="sm">
              Threshold: {Math.round((latest.threshold || 0.85) * 100)}%
            </Text>
          </CardBody>
        </Card>
      )}

      {failRows.length > 0 && (
        <Card>
          <CardHeader title="Recent failures" />
          <CardBody>
            <Table
              columns={[
                { key: "question", header: "Question" },
                { key: "type", header: "Type" },
                { key: "source", header: "Expected source" },
                { key: "topHit", header: "Top hit" },
                { key: "verdict", header: "Judge" },
              ]}
              rows={failRows}
            />
          </CardBody>
        </Card>
      )}
    </Stack>
  );
}
'''


def load_failure_history(data_dir: Path) -> list[dict]:
    """Load all failures from recent runs for regression promotion."""
    summary_path = data_dir / "eval" / "summary.json"
    if not summary_path.is_file():
        return []
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    out: list[dict] = []
    for run in data.get("runs", []):
        for f in run.get("failures", []):
            out.append({**f, "run_id": run.get("run_id")})
    return out
