"""Compiled task graph; all business iteration is expressed by explicit edges."""

from langgraph.graph import END, START, StateGraph

from .candidate import build_candidate_graph
from .events import node
from .finalization import cleanup, export, publish, record_failure, write_report
from .nodes import task_actions
from .state import TaskInput, TaskOutput, TaskState


def build_task_graph(ctx):
    candidate = build_candidate_graph(ctx)
    actions = task_actions(ctx, candidate)
    actions.update(record_failure=lambda s: record_failure(ctx, s), cleanup=lambda s: cleanup(ctx, s),
                   write_report=lambda s: write_report(ctx, s), publish=lambda s: publish(ctx, s),
                   export=lambda s: export(ctx, s))
    graph = StateGraph(TaskState, input_schema=TaskInput, output_schema=TaskOutput)
    for name, action in actions.items():
        graph.add_node(name, node(ctx, name, action, propagate=name in {
            "record_failure", "cleanup", "write_report", "publish", "export"}))
    graph.add_edge(START, "preflight")
    for source, target in (("preflight", "freeze_knowledge"), ("freeze_knowledge", "initialize_task"),
            ("initialize_task", "bind_inputs"), ("bind_inputs", "retrieve_knowledge"),
            ("retrieve_knowledge", "plan_candidates"), ("plan_candidates", "next_candidate"),
            ("run_candidate", "record_candidate"), ("record_candidate", "next_candidate"),
            ("select_candidate", "freeze_selection"), ("freeze_selection", "final_evaluate"),
            ("final_evaluate", "resolve_outcome"), ("resolve_outcome", "cleanup")):
        graph.add_conditional_edges(source, lambda s: "failure" if s.get("error") else "next",
                                    {"failure": "record_failure", "next": target})
    graph.add_conditional_edges("next_candidate", lambda s: "failure" if s.get("error") else "candidate" if s.get("current_candidate_id") else "select",
        {"failure": "record_failure", "candidate": "run_candidate", "select": "select_candidate"})
    graph.add_edge("record_failure", "cleanup")
    graph.add_edge("cleanup", "write_report")
    graph.add_edge("write_report", "publish")
    graph.add_conditional_edges("publish", lambda s: "export" if ctx.export_delivery else "done", {"export": "export", "done": END})
    graph.add_edge("export", END)
    return graph.compile()
