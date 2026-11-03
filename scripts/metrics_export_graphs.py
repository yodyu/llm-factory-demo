"""Export Mermaid from actual compiled LangGraph definitions without running a task."""

import argparse
from pathlib import Path

from factory.metrics.orchestration.candidate import build_candidate_graph
from factory.metrics.orchestration.graph import build_task_graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    for name, builder in (("task", build_task_graph), ("candidate", build_candidate_graph)):
        diagram = builder(None).get_graph().draw_mermaid()
        (args.output / f"langgraph-{name}.mmd").write_text(diagram.rstrip() + "\n")


if __name__ == "__main__":
    main()
