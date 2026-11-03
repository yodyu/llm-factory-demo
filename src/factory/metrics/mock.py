"""Explicit controlled model responses, derived from labelled human examples.

Never selected after API failure. No response is evidence of real model ability.
"""

import json

from contracts.metrics import CandidatePlan
from factory.metrics.capability_registry import registry, configuration, default_methods


class MockTransport:
    mode = "mock"

    async def chat(self, *, messages, model, timeout):
        request = json.loads(messages[1]["content"])
        stage, data = request["stage"], request["input"]
        if stage.startswith("understand-"):
            from factory.metrics.requirements import controlled_extract
            result = controlled_extract(data["requirement"]).model_dump(mode="json")
        elif stage.startswith("extract-"):
            source, chunk = data["source"], data["chunks"][0]
            path = source["payload"]["path"]
            matches = [card for card in registry().cards.values()
                       if any(alias.lower().replace('_', '-') in path.lower().replace('_', '-')
                              for alias in [card.method_id, *card.aliases])]
            card = matches[0] if matches else None
            result = {"capabilities": [{"local_id": "controlled", "name": path,
                       "method_id": card.method_id if card else None,
                       "summary": "受控抽取示例：" + path, "metric_kinds": card.metric_kinds if card else ["gauge", "rate"],
                       "single_host": True, "min_history": card.min_history if card else 0,
                       "dependency_profile": "metrics-py312-stdlib/1", "conditions_status": "evidenced",
                       "constraints": ["单主机单指标"], "limitations": ["mock extraction"],
                       "citations": [{"chunk_id": chunk["id"], "quote": chunk["payload"]["text"].splitlines()[0], "symbol": None}]}]}

        elif stage.startswith("plan"):
            explicit = data["explicit_constraints"]
            direction = explicit.get("direction", data["anomaly_target"])
            candidates = []
            for method in data.get("allowed_methods", default_methods()):
                card = registry().get(method)
                available = [c for c in data['knowledge'].get('capabilities', []) if c['method_id'] == method]
                if data.get('knowledge_schema') == 'metrics-knowledge/2' and not data.get('knowledge_off') and not available:
                    continue
                if len(candidates) >= data.get('candidate_budget', 16):
                    break
                capability = available[0] if available else None
                candidates.append(CandidatePlan(candidate_id=card.candidate_name or method,
                    config=configuration(method, {**explicit, "direction": direction}),
                    persistence_points=int(explicit.get("persistence_points", 2)),
                    parameter_sources={key: "user_explicit" if key in explicit else
                        "candidate_assumption" if key == "threshold" else "protocol_default"
                        for key in card.config_schema["properties"]},
                    knowledge_ids=[capability['id']] if capability else data["knowledge"]["knowledge_ids"][:1],
                    capability_id=capability['id'] if capability else None,
                    selection_reason=card.display_name + '：' + '；'.join(card.assumptions),
                    limitations=["controlled example", *card.assumptions]))
            result = {"supported": True, "understanding": "受控单指标示例", "anomaly_target": direction,
                      "limitations": ["mock"], "candidates": [c.model_dump(mode="json") for c in candidates]}
        elif stage.startswith("code-"):
            method = data["frozen_plan"]["config"]["method_id"]
            source = (registry().directories[method] / "reference.py").read_text()
            result = {"source": source, "knowledge_ids": [data["frozen_plan"]["capability_id"]] if data["frozen_plan"].get("capability_id") else data["task"]["knowledge"]["knowledge_ids"][:1],
                      "explanation": "Explicit mock response copies the constructed human reference."}
        else:
            raise ValueError("unknown controlled stage")
        return {"model": "controlled", "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    async def aclose(self):
        pass
