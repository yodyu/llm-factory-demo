# 数值监控验证报告
任务：ewma-three-candidates；流程：COMPLETED
工程通过、效果测量、业务达标分别记录；业务门槛以冻结需求和验收结果为准。

## A. 工程质量

```json
{
  "model_origin": "mock",
  "dependency_profile": "metrics-py312-stdlib/1",
  "image": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
  "prompt_version": "metrics-prompts/5",
  "candidates": [
    {
      "business_acceptance": {
        "checks": [],
        "status": "NOT_DEFINED"
      },
      "calibration": {
        "binding": {
          "config": {
            "alpha": 0.3,
            "direction": "upper",
            "method_id": "ewma",
            "min_history": 3,
            "quantile": 0.99
          },
          "dataset": {
            "image_id": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
            "knowledge_snapshot": "sha256:ca4dc787dfb4ddb2ca0d384de36d6e6ee0b6659171df9950d1fc19fac404078e",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285"
          },
          "source": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333"
        },
        "labels_used": false,
        "quantile": 0.99,
        "rule": "nearest-rank",
        "score_count": 240,
        "threshold": 0.8980130927676739
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "ewma",
      "plan": {
        "candidate_id": "ewma",
        "capability_id": "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666",
        "config": {
          "alpha": 0.3,
          "direction": "upper",
          "method_id": "ewma",
          "min_history": 3,
          "quantile": 0.99
        },
        "knowledge_ids": [
          "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666"
        ],
        "limitations": [
          "controlled example",
          "适于持续变化；固定训练基线保留长期偏移，较小alpha会降低响应速度。"
        ],
        "parameter_sources": {
          "alpha": "protocol_default",
          "direction": "user_explicit",
          "min_history": "protocol_default",
          "quantile": "protocol_default"
        },
        "persistence_points": 2,
        "selection_reason": "EWMA：适于持续变化；固定训练基线保留长期偏移，较小alpha会降低响应速度。"
      },
      "report": {
        "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
        "coverage": {
          "denominator": 240,
          "null_reason": null,
          "numerator": 240,
          "value": 1.0
        },
        "effect_status": "MEASURED",
        "engineering_status": "PASSED",
        "event": {
          "f1": {
            "denominator": 2,
            "null_reason": null,
            "numerator": 2,
            "value": 1.0
          },
          "fn": 0,
          "fp": 0,
          "pairs": [
            {
              "delay_seconds": 60.0,
              "prediction_id": "pred-0000",
              "truth_id": "truth-0000"
            }
          ],
          "precision": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "recall": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "tp": 1,
          "unmatched_prediction_ids": [],
          "unmatched_truth_ids": []
        },
        "execution_status": "SUCCEEDED",
        "matched_delay_seconds": {
          "maximum": 60.0,
          "median": 60.0,
          "missed_events": 0,
          "null_reason": null
        },
        "normal_false_alarms_per_host_hour": {
          "denominator": 10800,
          "null_reason": null,
          "numerator": 0,
          "value": 0.0
        },
        "peak_memory_bytes": null,
        "peak_memory_null_reason": "not_measured",
        "point": {
          "abstained_normal": 0,
          "f1": {
            "denominator": 129,
            "null_reason": null,
            "numerator": 118,
            "value": 0.9147286821705426
          },
          "fn": 1,
          "fp": 10,
          "precision": {
            "denominator": 69,
            "null_reason": null,
            "numerator": 59,
            "value": 0.855072463768116
          },
          "recall": {
            "denominator": 60,
            "null_reason": null,
            "numerator": 59,
            "value": 0.9833333333333333
          },
          "tn": 170,
          "total": 240,
          "tp": 59
        },
        "predicted_events": [
          {
            "end_at": "2026-01-03T03:50:00Z",
            "event_id": "pred-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:41:00Z",
            "trigger_at": "2026-01-03T02:41:00Z"
          }
        ],
        "protocol": "metrics-evaluation/1",
        "runtime_seconds": 0.11995832249522209,
        "truth_events": [
          {
            "end_at": "2026-01-03T03:40:00Z",
            "event_id": "truth-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:40:00Z",
            "trigger_at": "2026-01-03T02:40:00Z"
          }
        ]
      },
      "role": "development",
      "versions": [
        {
          "capability_id": "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666",
          "capability_version": "1.0.0",
          "explanation": "Explicit mock response copies the constructed human reference.",
          "knowledge_ids": [
            "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666"
          ],
          "origin": "mock",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:34742af2d68e6df5600ee2547d4b0556cb1dff020e7c0fc895587dc4d8a12617",
            "checks.py": "sha256:025c96a17a67127db78722b0cfefe382b79c1c22eb88f6cea06c3f6c429c58fd",
            "reference.py": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333"
          },
          "source_path": "candidate-efb3912a92d56be58be551ee0b4717ae7250bd96e87d5df6c3c819b4767cfa15/v0.py",
          "source_ref": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333",
          "source_sha256": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333",
          "specification_sha256": "sha256:53abdca0789200f3681895fdd88b049227e8b5e9587a9cc82d7f1d1bcc70bda2",
          "validation": {
            "candidate_id": "ewma",
            "capability_version": "1.0.0",
            "checks": [
              {
                "check": "static_profile",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "missing_input_contract",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "state_reload",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "reset_repeat_future_invariance",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "ewma_cold_start",
                "layer": "property",
                "passed": true,
                "points": 3
              },
              {
                "check": "ewma_monotonic_step",
                "layer": "property",
                "passed": true,
                "points": 13
              },
              {
                "check": "ewma_missing",
                "layer": "property",
                "passed": true,
                "points": 8
              },
              {
                "check": "ewma_cold_start",
                "layer": "reference",
                "passed": true,
                "points": 3
              },
              {
                "check": "ewma_monotonic_step",
                "layer": "reference",
                "passed": true,
                "points": 13
              },
              {
                "check": "ewma_missing",
                "layer": "reference",
                "passed": true,
                "points": 8
              }
            ],
            "config": {
              "alpha": 0.3,
              "direction": "upper",
              "method_id": "ewma",
              "min_history": 3,
              "quantile": 0.99
            },
            "dependency_profile": "metrics-py312-stdlib/1",
            "origin": "mock",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:34742af2d68e6df5600ee2547d4b0556cb1dff020e7c0fc895587dc4d8a12617",
              "checks.py": "sha256:025c96a17a67127db78722b0cfefe382b79c1c22eb88f6cea06c3f6c429c58fd",
              "reference.py": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333",
            "verification_level": "reference_verified",
            "version": 0
          },
          "version": 0
        }
      ]
    },
    {
      "business_acceptance": {
        "checks": [],
        "status": "NOT_DEFINED"
      },
      "calibration": {
        "binding": {
          "config": {
            "direction": "upper",
            "method_id": "fixed_threshold",
            "threshold": 85.0
          },
          "dataset": {
            "image_id": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
            "knowledge_snapshot": "sha256:ca4dc787dfb4ddb2ca0d384de36d6e6ee0b6659171df9950d1fc19fac404078e",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285"
          },
          "source": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
        },
        "labels_used": false,
        "rule": "fixed_parameter_unchanged",
        "threshold": 0.0
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "fixed",
      "plan": {
        "candidate_id": "fixed",
        "capability_id": "capability-bfc8deb63f893fd0e82050292732064ce2f81f841ca02f55fa25dcb6ea8fff95",
        "config": {
          "direction": "upper",
          "method_id": "fixed_threshold",
          "threshold": 85.0
        },
        "knowledge_ids": [
          "capability-bfc8deb63f893fd0e82050292732064ce2f81f841ca02f55fa25dcb6ea8fff95"
        ],
        "limitations": [
          "controlled example",
          "业务阈值须由用户确认；未指定值只是候选假设。"
        ],
        "parameter_sources": {
          "direction": "user_explicit",
          "threshold": "user_explicit"
        },
        "persistence_points": 2,
        "selection_reason": "固定阈值：业务阈值须由用户确认；未指定值只是候选假设。"
      },
      "report": {
        "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
        "coverage": {
          "denominator": 240,
          "null_reason": null,
          "numerator": 240,
          "value": 1.0
        },
        "effect_status": "MEASURED",
        "engineering_status": "PASSED",
        "event": {
          "f1": {
            "denominator": 2,
            "null_reason": null,
            "numerator": 2,
            "value": 1.0
          },
          "fn": 0,
          "fp": 0,
          "pairs": [
            {
              "delay_seconds": 60.0,
              "prediction_id": "pred-0000",
              "truth_id": "truth-0000"
            }
          ],
          "precision": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "recall": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "tp": 1,
          "unmatched_prediction_ids": [],
          "unmatched_truth_ids": []
        },
        "execution_status": "SUCCEEDED",
        "matched_delay_seconds": {
          "maximum": 60.0,
          "median": 60.0,
          "missed_events": 0,
          "null_reason": null
        },
        "normal_false_alarms_per_host_hour": {
          "denominator": 10800,
          "null_reason": null,
          "numerator": 0,
          "value": 0.0
        },
        "peak_memory_bytes": null,
        "peak_memory_null_reason": "not_measured",
        "point": {
          "abstained_normal": 0,
          "f1": {
            "denominator": 119,
            "null_reason": null,
            "numerator": 118,
            "value": 0.9915966386554622
          },
          "fn": 1,
          "fp": 0,
          "precision": {
            "denominator": 59,
            "null_reason": null,
            "numerator": 59,
            "value": 1.0
          },
          "recall": {
            "denominator": 60,
            "null_reason": null,
            "numerator": 59,
            "value": 0.9833333333333333
          },
          "tn": 180,
          "total": 240,
          "tp": 59
        },
        "predicted_events": [
          {
            "end_at": "2026-01-03T03:40:00Z",
            "event_id": "pred-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:41:00Z",
            "trigger_at": "2026-01-03T02:41:00Z"
          }
        ],
        "protocol": "metrics-evaluation/1",
        "runtime_seconds": 0.09791019186377525,
        "truth_events": [
          {
            "end_at": "2026-01-03T03:40:00Z",
            "event_id": "truth-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:40:00Z",
            "trigger_at": "2026-01-03T02:40:00Z"
          }
        ]
      },
      "role": "development",
      "versions": [
        {
          "capability_id": "capability-bfc8deb63f893fd0e82050292732064ce2f81f841ca02f55fa25dcb6ea8fff95",
          "capability_version": "1.0.0",
          "explanation": "Explicit mock response copies the constructed human reference.",
          "knowledge_ids": [
            "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666"
          ],
          "origin": "mock",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:7af436aaf7e4a265e7d7e6792a4ac1d6311c8f98453904a136b8692209170bde",
            "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
            "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
          },
          "source_path": "candidate-12aff05139e917c8d6fe0daaa3e2191c2ee3434e51a6a5b5f67e001847ebd5aa/v0.py",
          "source_ref": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
          "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
          "specification_sha256": "sha256:d78418b686499b015abb691e10e65fad63592d12ad25bcab36e2ced5af7a2060",
          "validation": {
            "candidate_id": "fixed",
            "capability_version": "1.0.0",
            "checks": [
              {
                "check": "static_profile",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "missing_input_contract",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "state_reload",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "reset_repeat_future_invariance",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "fixed_strict_boundary",
                "layer": "property",
                "passed": true,
                "points": 3
              },
              {
                "check": "fixed_missing",
                "layer": "property",
                "passed": true,
                "points": 6
              },
              {
                "check": "fixed_strict_boundary",
                "layer": "reference",
                "passed": true,
                "points": 3
              },
              {
                "check": "fixed_missing",
                "layer": "reference",
                "passed": true,
                "points": 6
              }
            ],
            "config": {
              "direction": "upper",
              "method_id": "fixed_threshold",
              "threshold": 85.0
            },
            "dependency_profile": "metrics-py312-stdlib/1",
            "origin": "mock",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:7af436aaf7e4a265e7d7e6792a4ac1d6311c8f98453904a136b8692209170bde",
              "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
              "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
            "verification_level": "reference_verified",
            "version": 0
          },
          "version": 0
        }
      ]
    },
    {
      "business_acceptance": {
        "checks": [],
        "status": "NOT_DEFINED"
      },
      "calibration": {
        "binding": {
          "config": {
            "direction": "upper",
            "method_id": "rolling_mad",
            "min_history": 15,
            "quantile": 0.99,
            "window": 30
          },
          "dataset": {
            "image_id": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
            "knowledge_snapshot": "sha256:ca4dc787dfb4ddb2ca0d384de36d6e6ee0b6659171df9950d1fc19fac404078e",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285"
          },
          "source": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7"
        },
        "labels_used": false,
        "quantile": 0.99,
        "rule": "nearest-rank",
        "score_count": 240,
        "threshold": 2.370236853992631
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "mad",
      "plan": {
        "candidate_id": "mad",
        "capability_id": "capability-b4fb70d5b0d9351ba494f89462d2befb09fc808853abd75784daaf3c85ef8a3d",
        "config": {
          "direction": "upper",
          "method_id": "rolling_mad",
          "min_history": 15,
          "quantile": 0.99,
          "window": 30
        },
        "knowledge_ids": [
          "capability-b4fb70d5b0d9351ba494f89462d2befb09fc808853abd75784daaf3c85ef8a3d"
        ],
        "limitations": [
          "controlled example",
          "自适应历史窗口可能把持续变化吸收为新基线。"
        ],
        "parameter_sources": {
          "direction": "user_explicit",
          "min_history": "protocol_default",
          "quantile": "protocol_default",
          "window": "protocol_default"
        },
        "persistence_points": 2,
        "selection_reason": "滚动 MAD：自适应历史窗口可能把持续变化吸收为新基线。"
      },
      "report": {
        "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
        "coverage": {
          "denominator": 240,
          "null_reason": null,
          "numerator": 240,
          "value": 1.0
        },
        "effect_status": "MEASURED",
        "engineering_status": "PASSED",
        "event": {
          "f1": {
            "denominator": 2,
            "null_reason": null,
            "numerator": 2,
            "value": 1.0
          },
          "fn": 0,
          "fp": 0,
          "pairs": [
            {
              "delay_seconds": 60.0,
              "prediction_id": "pred-0000",
              "truth_id": "truth-0000"
            }
          ],
          "precision": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "recall": {
            "denominator": 1,
            "null_reason": null,
            "numerator": 1,
            "value": 1.0
          },
          "tp": 1,
          "unmatched_prediction_ids": [],
          "unmatched_truth_ids": []
        },
        "execution_status": "SUCCEEDED",
        "matched_delay_seconds": {
          "maximum": 60.0,
          "median": 60.0,
          "missed_events": 0,
          "null_reason": null
        },
        "normal_false_alarms_per_host_hour": {
          "denominator": 10800,
          "null_reason": null,
          "numerator": 0,
          "value": 0.0
        },
        "peak_memory_bytes": null,
        "peak_memory_null_reason": "not_measured",
        "point": {
          "abstained_normal": 0,
          "f1": {
            "denominator": 74,
            "null_reason": null,
            "numerator": 28,
            "value": 0.3783783783783784
          },
          "fn": 46,
          "fp": 0,
          "precision": {
            "denominator": 14,
            "null_reason": null,
            "numerator": 14,
            "value": 1.0
          },
          "recall": {
            "denominator": 60,
            "null_reason": null,
            "numerator": 14,
            "value": 0.23333333333333334
          },
          "tn": 180,
          "total": 240,
          "tp": 14
        },
        "predicted_events": [
          {
            "end_at": "2026-01-03T02:55:00Z",
            "event_id": "pred-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:41:00Z",
            "trigger_at": "2026-01-03T02:41:00Z"
          }
        ],
        "protocol": "metrics-evaluation/1",
        "runtime_seconds": 0.12452151253819466,
        "truth_events": [
          {
            "end_at": "2026-01-03T03:40:00Z",
            "event_id": "truth-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:40:00Z",
            "trigger_at": "2026-01-03T02:40:00Z"
          }
        ]
      },
      "role": "development",
      "versions": [
        {
          "capability_id": "capability-b4fb70d5b0d9351ba494f89462d2befb09fc808853abd75784daaf3c85ef8a3d",
          "capability_version": "1.0.0",
          "explanation": "Explicit mock response copies the constructed human reference.",
          "knowledge_ids": [
            "capability-6c5773d4f7d2ac25dd1eea67e3d1472c25adb240b3d7151b3a43569c851ba666"
          ],
          "origin": "mock",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:39d8d9a00953b367af3f105a356912956a920f26dcc44796dec0346b3b88fb66",
            "checks.py": "sha256:2ae8cf000dda9f9f86e3c19c993b76d14af181fba24d81d2a020643fdd9e613c",
            "reference.py": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7"
          },
          "source_path": "candidate-a7627b363c8b9db655145f8280b45089de3ec4b089747c5d875ca3b39528e2c3/v0.py",
          "source_ref": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7",
          "source_sha256": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7",
          "specification_sha256": "sha256:1341c8dba78c069e25220a8afe6f80caaf9150384348d3c7f47c3c4e1dce8309",
          "validation": {
            "candidate_id": "mad",
            "capability_version": "1.0.0",
            "checks": [
              {
                "check": "static_profile",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "missing_input_contract",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "state_reload",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "reset_repeat_future_invariance",
                "layer": "contract",
                "passed": true
              },
              {
                "check": "mad_past_only",
                "layer": "property",
                "passed": true,
                "points": 17
              },
              {
                "check": "mad_zero_scale",
                "layer": "property",
                "passed": true,
                "points": 33
              },
              {
                "check": "mad_missing_slots",
                "layer": "property",
                "passed": true,
                "points": 50
              },
              {
                "check": "mad_imputed_not_original",
                "layer": "property",
                "passed": true,
                "points": 19
              },
              {
                "check": "mad_past_only",
                "layer": "reference",
                "passed": true,
                "points": 17
              },
              {
                "check": "mad_zero_scale",
                "layer": "reference",
                "passed": true,
                "points": 33
              },
              {
                "check": "mad_missing_slots",
                "layer": "reference",
                "passed": true,
                "points": 50
              },
              {
                "check": "mad_imputed_not_original",
                "layer": "reference",
                "passed": true,
                "points": 19
              }
            ],
            "config": {
              "direction": "upper",
              "method_id": "rolling_mad",
              "min_history": 15,
              "quantile": 0.99,
              "window": 30
            },
            "dependency_profile": "metrics-py312-stdlib/1",
            "origin": "mock",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:39d8d9a00953b367af3f105a356912956a920f26dcc44796dec0346b3b88fb66",
              "checks.py": "sha256:2ae8cf000dda9f9f86e3c19c993b76d14af181fba24d81d2a020643fdd9e613c",
              "reference.py": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7",
            "verification_level": "reference_verified",
            "version": 0
          },
          "version": 0
        }
      ]
    }
  ],
  "stage_status": {
    "benchmark": "NOT_APPLICABLE",
    "detection": "SUCCEEDED",
    "engineering": "PASSED"
  },
  "model_usage": {
    "kind": "mock",
    "requests": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_tokens": 0,
    "missing_usage_requests": 0,
    "reservations": 0
  },
  "workflow_runtime_seconds": 25.678167823702097,
  "resources": {
    "peak_memory_bytes": null,
    "cpu_seconds": null,
    "reason": "not_measured; sandbox limits are not measurements"
  },
  "peak_memory": "NOT_MEASURED; container limits are not measurements",
  "failure": null
}
```

## B. 当前检测数据

```json
{
  "frozen_source": {
    "display_name": "sim-memory_shift-v1",
    "end_at_inclusive": "2026-01-04T04:59:00+00:00",
    "host_id": "sim-host-a",
    "metric": "memory_utilization",
    "missing_points": 1,
    "points": 300,
    "roles": {
      "calibration": {
        "path": "calibration.csv",
        "prefix_points": 60,
        "sha256": "sha256:ec215bc11f1129f7703cf641743c06b9df71b041c6d69b67762f66a888e05ce1"
      },
      "development": {
        "path": "development.csv",
        "prefix_points": 60,
        "sha256": "sha256:9a389eb7d0487c4bd127a4b354e144b83b1819f7b98dcfbd2da1ce548f2b6709"
      },
      "test": {
        "path": "test.csv",
        "prefix_points": 60,
        "sha256": "sha256:7b47fe2b64d82c86dfb2609cc930d4edf2deff11a2a2f80fd739934b2926e464"
      },
      "train": {
        "path": "train.csv",
        "prefix_points": 60,
        "sha256": "sha256:872961e0a74fc3f72e1100475738576597ffe9b2f900c79b4023060dedd26049"
      }
    },
    "sampling_seconds": 60,
    "start_at": "2026-01-04T00:00:00+00:00",
    "type": "builtin_simulation",
    "unit": "percent"
  },
  "selection": {
    "basis": "labelled_development",
    "beta": 1.0,
    "criteria": [
      "event_f1_desc",
      "point_f1_desc",
      "false_alarm_rate_asc",
      "matched_delay_asc",
      "coverage_desc",
      "candidate_id"
    ],
    "objective": "event_detection",
    "policy": "balanced",
    "protocol": "metrics-selection/2",
    "ranking": [
      "fixed",
      "ewma",
      "mad"
    ],
    "reason": "按开发集目标及次级 Fβ、正常误报频次、匹配延迟、覆盖率和候选ID排序；最终测试不参与选择。",
    "requested_policy": "balanced",
    "selected": "fixed",
    "status": "SELECTED",
    "tie_broken_by": "point_f1",
    "warnings": [
      "LOW_EVENT_COUNT: 真实事件少于5个，事件F1不足以支持统计结论。"
    ]
  },
  "result": {
    "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
    "coverage": {
      "denominator": 240,
      "null_reason": null,
      "numerator": 240,
      "value": 1.0
    },
    "effect_status": "MEASURED",
    "engineering_status": "PASSED",
    "event": {
      "f1": {
        "denominator": 2,
        "null_reason": null,
        "numerator": 2,
        "value": 1.0
      },
      "fn": 0,
      "fp": 0,
      "pairs": [
        {
          "delay_seconds": 60.0,
          "prediction_id": "pred-0000",
          "truth_id": "truth-0000"
        }
      ],
      "precision": {
        "denominator": 1,
        "null_reason": null,
        "numerator": 1,
        "value": 1.0
      },
      "recall": {
        "denominator": 1,
        "null_reason": null,
        "numerator": 1,
        "value": 1.0
      },
      "tp": 1,
      "unmatched_prediction_ids": [],
      "unmatched_truth_ids": []
    },
    "execution_status": "SUCCEEDED",
    "matched_delay_seconds": {
      "maximum": 60.0,
      "median": 60.0,
      "missed_events": 0,
      "null_reason": null
    },
    "normal_false_alarms_per_host_hour": {
      "denominator": 10800,
      "null_reason": null,
      "numerator": 0,
      "value": 0.0
    },
    "peak_memory_bytes": null,
    "peak_memory_null_reason": "not_measured",
    "phase": "test",
    "point": {
      "abstained_normal": 0,
      "f1": {
        "denominator": 119,
        "null_reason": null,
        "numerator": 118,
        "value": 0.9915966386554622
      },
      "fn": 1,
      "fp": 0,
      "precision": {
        "denominator": 59,
        "null_reason": null,
        "numerator": 59,
        "value": 1.0
      },
      "recall": {
        "denominator": 60,
        "null_reason": null,
        "numerator": 59,
        "value": 0.9833333333333333
      },
      "tn": 180,
      "total": 240,
      "tp": 59
    },
    "predicted_events": [
      {
        "end_at": "2026-01-04T03:40:00Z",
        "event_id": "pred-0000",
        "host_id": "sim-host-a",
        "metric": "memory_utilization",
        "start_at": "2026-01-04T02:41:00Z",
        "trigger_at": "2026-01-04T02:41:00Z"
      }
    ],
    "protocol": "metrics-evaluation/1",
    "runtime_seconds": 0.10904646292328835,
    "selected": "fixed",
    "selection_sha256": "sha256:fe30b7b043af4a06c0613ee98516cd0454cd434a04262c5b5f16cc4572a724b5",
    "test_execution_started": true,
    "truth_events": [
      {
        "end_at": "2026-01-04T03:40:00Z",
        "event_id": "truth-0000",
        "host_id": "sim-host-a",
        "metric": "memory_utilization",
        "start_at": "2026-01-04T02:40:00Z",
        "trigger_at": "2026-01-04T02:40:00Z"
      }
    ]
  },
  "notice": null
}
```

## C. 独立模拟基准效果

```json
{
  "notice": "这些指标属于独立模拟基准，不代表上传数据的准确率或生产效果。",
  "result": {
    "execution_status": "NOT_EVALUATED",
    "reason": "builtin simulation evaluated in B"
  }
}
```

## D. 需求理解与业务验收

```json
{
  "frozen_task": {
    "acceptance_criteria": {
      "max_false_alarms_per_hour": null,
      "min_event_f1": null,
      "min_event_recall": null
    },
    "allowed_methods": [
      "ewma",
      "fixed_threshold",
      "rolling_mad"
    ],
    "anomaly_target": "upper",
    "budgets": {
      "candidates": 3,
      "model_calls": 16,
      "repair_rounds": 2,
      "wall_seconds": 900
    },
    "dataset_id": "sim-memory_shift-v1",
    "evaluation_objective": "sustained_coverage",
    "explicit_constraints": {
      "direction": "upper",
      "persistence_points": 2.0,
      "threshold": 85.0
    },
    "knowledge_snapshot": "sha256:ca4dc787dfb4ddb2ca0d384de36d6e6ee0b6659171df9950d1fc19fac404078e",
    "metric": "memory_utilization",
    "model_mode": "mock",
    "model_profile_id": "metrics-mock-v1",
    "ranking_preferences": [],
    "requirement": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
    "requirement_draft": {
      "binding": "sha256:3bd90956899e2db4cbc0ee8339869d1ea58bc698351c65d2ef1993247f8fe0b6",
      "defaults": [
        "选优偏好：balanced",
        "模拟数据：每 60 秒一点，独立四段；允许最多前向填补 3 点。",
        "未明确变化形态：CPU默认突增、内存默认阶跃模拟场景；模拟结果不代表生产效果。"
      ],
      "evidence": {
        "data_source": {
          "origin": "user_explicit",
          "quote": "模拟",
          "turn": 1
        },
        "direction": {
          "origin": "user_explicit",
          "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
          "turn": 1
        },
        "evaluation_objective": {
          "origin": "user_explicit",
          "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
          "turn": 1
        },
        "methods": {
          "origin": "user_explicit",
          "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
          "turn": 1
        },
        "persistence_points": {
          "origin": "user_explicit",
          "quote": "连续两点",
          "turn": 1
        },
        "scenario": {
          "origin": "user_explicit",
          "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
          "turn": 1
        },
        "selection_policy": {
          "origin": "protocol_default",
          "quote": "协议默认值",
          "turn": 0
        },
        "threshold": {
          "origin": "user_explicit",
          "quote": "阈值85%",
          "turn": 1
        }
      },
      "issues": [],
      "model_mode": "mock",
      "model_usage": {},
      "parse_task_id": null,
      "revision": 1,
      "schema_version": "metrics-requirement-draft/1",
      "turns": [
        "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警"
      ],
      "values": {
        "data_source": "simulation",
        "direction": "upper",
        "evaluation_objective": "sustained_coverage",
        "methods": [
          "ewma",
          "fixed_threshold",
          "rolling_mad"
        ],
        "persistence_points": 2,
        "scenario": "memory_shift",
        "selection_policy": "balanced",
        "threshold": 85.0
      }
    },
    "schema_version": "metrics-task/1",
    "selection_policy": "balanced",
    "task_id": "ewma-three-candidates",
    "validation_protocol": "metrics-evaluation/1"
  },
  "evaluation_policy": null,
  "requirement": {
    "binding": "sha256:3bd90956899e2db4cbc0ee8339869d1ea58bc698351c65d2ef1993247f8fe0b6",
    "defaults": [
      "选优偏好：balanced",
      "模拟数据：每 60 秒一点，独立四段；允许最多前向填补 3 点。",
      "未明确变化形态：CPU默认突增、内存默认阶跃模拟场景；模拟结果不代表生产效果。"
    ],
    "evidence": {
      "data_source": {
        "origin": "user_explicit",
        "quote": "模拟",
        "turn": 1
      },
      "direction": {
        "origin": "user_explicit",
        "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
        "turn": 1
      },
      "evaluation_objective": {
        "origin": "user_explicit",
        "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
        "turn": 1
      },
      "methods": {
        "origin": "user_explicit",
        "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
        "turn": 1
      },
      "persistence_points": {
        "origin": "user_explicit",
        "quote": "连续两点",
        "turn": 1
      },
      "scenario": {
        "origin": "user_explicit",
        "quote": "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警",
        "turn": 1
      },
      "selection_policy": {
        "origin": "protocol_default",
        "quote": "协议默认值",
        "turn": 0
      },
      "threshold": {
        "origin": "user_explicit",
        "quote": "阈值85%",
        "turn": 1
      }
    },
    "issues": [],
    "model_mode": "mock",
    "model_usage": {},
    "parse_task_id": null,
    "revision": 1,
    "schema_version": "metrics-requirement-draft/1",
    "turns": [
      "比较固定阈值、滚动MAD和EWMA检测模拟内存持续升高，固定阈值85%，连续两点告警"
    ],
    "values": {
      "data_source": "simulation",
      "direction": "upper",
      "evaluation_objective": "sustained_coverage",
      "methods": [
        "ewma",
        "fixed_threshold",
        "rolling_mad"
      ],
      "persistence_points": 2,
      "scenario": "memory_shift",
      "selection_policy": "balanced",
      "threshold": 85.0
    }
  },
  "acceptance": {
    "checks": [],
    "status": "NOT_DEFINED"
  },
  "criteria": {
    "max_false_alarms_per_hour": null,
    "min_event_f1": null,
    "min_event_recall": null
  }
}
```
