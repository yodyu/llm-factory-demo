# 数值监控验证报告
任务：upload-labelled；流程：COMPLETED
工程通过、效果测量、业务达标分别记录；未定义业务门槛。

## A. 工程质量

```json
{
  "model_origin": "mock",
  "dependency_profile": "metrics-py312-stdlib/1",
  "image": "sha256:4ac57c88b37dae806e1542718e900f497dca56f3d8030bd4211d16193108162c",
  "prompt_version": "metrics-prompts/3",
  "candidates": [
    {
      "candidate_id": "fixed",
      "role": "preselected_upload",
      "plan": {
        "candidate_id": "fixed",
        "config": {
          "method_id": "fixed_threshold",
          "threshold": 85.0,
          "direction": "upper"
        },
        "persistence_points": 2,
        "parameter_sources": {
          "threshold": "user_explicit"
        },
        "knowledge_ids": [
          "capability-10ae25e3348a01de76dccd8b39b48b876303cddaa2f2780fd1d270e2dc03c9d1"
        ],
        "limitations": [
          "controlled example"
        ]
      },
      "versions": [
        {
          "version": 0,
          "origin": "mock",
          "source_path": "candidate-12aff05139e917c8d6fe0daaa3e2191c2ee3434e51a6a5b5f67e001847ebd5aa/v0.py",
          "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
          "source_ref": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
          "parent_source_sha256": null,
          "knowledge_ids": [
            "capability-10ae25e3348a01de76dccd8b39b48b876303cddaa2f2780fd1d270e2dc03c9d1"
          ],
          "explanation": "Explicit mock response copies the constructed human reference.",
          "validation": {
            "protocol": "metrics-method-check/2",
            "candidate_id": "fixed",
            "version": 0,
            "origin": "mock",
            "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
            "config": {
              "method_id": "fixed_threshold",
              "threshold": 85.0,
              "direction": "upper"
            },
            "dependency_profile": "metrics-py312-stdlib/1",
            "checks": [
              {
                "check": "static_profile",
                "passed": true
              },
              {
                "check": "fixed_strict_boundary",
                "passed": true,
                "points": 3
              },
              {
                "check": "fixed_missing",
                "passed": true,
                "points": 6
              },
              {
                "check": "state_reload",
                "passed": true
              },
              {
                "check": "reset_repeat_future_invariance",
                "passed": true
              }
            ],
            "passed": true,
            "repairable": true
          }
        }
      ],
      "calibration": {
        "threshold": 0.0,
        "rule": "fixed_parameter_unchanged",
        "labels_used": false,
        "binding": {
          "source": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
          "config": {
            "method_id": "fixed_threshold",
            "threshold": 85.0,
            "direction": "upper"
          },
          "dataset": {
            "manifest_sha256": "sha256:b1262a5c4c6b26139e6317176162ceb15d98e227dfcc841da1e6f0e540093a14",
            "knowledge_snapshot": "sha256:07d023872844c723de8c4a0f86c8828c11648b4300b67126118f775414cf44da",
            "image_id": "sha256:4ac57c88b37dae806e1542718e900f497dca56f3d8030bd4211d16193108162c",
            "upload_sha256": "sha256:c37eed2dd6d52a8a9b6a857e0db5ea0f727862ae5ebcd794d1427b7095b53eb1"
          }
        }
      },
      "calibration_status": "SUCCEEDED",
      "report": {
        "execution_status": "SUCCEEDED",
        "engineering_status": "PASSED",
        "effect_status": "NOT_EVALUATED"
      }
    }
  ],
  "stage_status": {
    "engineering": "PASSED",
    "detection": "SUCCEEDED",
    "benchmark": "SUCCEEDED"
  },
  "workflow_runtime_seconds": 7.7668976075947285,
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
    "benchmark": {
      "experiment_sha256": "sha256:baf682e0c88d592650313c347417361462a56bbd67e25a2cbcad0fd3758b4a75",
      "generator_version": "metrics-synthetic/1",
      "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285",
      "policy": "fixed before planning; independent refit/calibration; never selection or repair",
      "scenario": "memory_shift",
      "status": "READY"
    },
    "direction": "upper",
    "display_name": "upload-labelled.csv",
    "end_at_inclusive": "2026-08-01T05:59:00+00:00",
    "fit_points": 60,
    "history_points": 200,
    "host_id": "customer-host-7",
    "labels": {
      "coverage": 1.0,
      "points": 160,
      "sha256": "sha256:7df43942c5ea5793d2c1f0ef2d64fd7477f797586236e0a834cd4e1a6c48df75",
      "source": "用户提供标签；本案例为独立受控注入",
      "status": "用户提供标签"
    },
    "method": "fixed_threshold",
    "metric": "memory_utilization",
    "metric_kind": "gauge",
    "missing_points": 4,
    "normal_history_assumption": "用户假设历史参考适用且正常；系统未验证",
    "points": 360,
    "purpose": "all observations",
    "sampling_seconds": 60,
    "sha256": "sha256:f7b38e0aad75961da5046978d325d453bd3007338c916623518e18a77e7ab86d",
    "splits": [
      {
        "end_at_inclusive": "2026-08-01T00:59:00+00:00",
        "missing_points": 0,
        "points": 60,
        "purpose": "fit_history",
        "start_at": "2026-08-01T00:00:00+00:00"
      },
      {
        "end_at_inclusive": "2026-08-01T03:19:00+00:00",
        "missing_points": 0,
        "points": 140,
        "purpose": "calibration_history",
        "start_at": "2026-08-01T01:00:00+00:00"
      },
      {
        "end_at_inclusive": "2026-08-01T05:59:00+00:00",
        "missing_points": 4,
        "points": 160,
        "purpose": "detection_only",
        "start_at": "2026-08-01T03:20:00+00:00"
      }
    ],
    "start_at": "2026-08-01T00:00:00+00:00",
    "type": "uploaded_csv",
    "unit": "percent",
    "valid_range": [
      0,
      100
    ],
    "warmup_points": 60
  },
  "selection": {
    "status": "USER_PRESELECTED_METHOD",
    "selected": "fixed",
    "ranking": [],
    "reason": "method selected before execution; no upload or benchmark effect used; no optimality claim"
  },
  "result": {
    "protocol": "metrics-evaluation/1",
    "execution_status": "SUCCEEDED",
    "engineering_status": "PASSED",
    "effect_status": "MEASURED",
    "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
    "point": {
      "tp": 19,
      "fp": 0,
      "fn": 1,
      "tn": 139,
      "abstained_normal": 1,
      "total": 160,
      "precision": {
        "value": 1.0,
        "numerator": 19,
        "denominator": 19,
        "null_reason": null
      },
      "recall": {
        "value": 0.95,
        "numerator": 19,
        "denominator": 20,
        "null_reason": null
      },
      "f1": {
        "value": 0.9743589743589743,
        "numerator": 38,
        "denominator": 39,
        "null_reason": null
      }
    },
    "event": {
      "tp": 1,
      "fp": 0,
      "fn": 0,
      "pairs": [
        {
          "truth_id": "truth-0000",
          "prediction_id": "pred-0000",
          "delay_seconds": 60.0
        }
      ],
      "unmatched_truth_ids": [],
      "unmatched_prediction_ids": [],
      "precision": {
        "value": 1.0,
        "numerator": 1,
        "denominator": 1,
        "null_reason": null
      },
      "recall": {
        "value": 1.0,
        "numerator": 1,
        "denominator": 1,
        "null_reason": null
      },
      "f1": {
        "value": 1.0,
        "numerator": 2,
        "denominator": 2,
        "null_reason": null
      }
    },
    "coverage": {
      "value": 0.99375,
      "numerator": 159,
      "denominator": 160,
      "null_reason": null
    },
    "normal_false_alarms_per_host_hour": {
      "value": 0.0,
      "numerator": 0,
      "denominator": 8400,
      "null_reason": null
    },
    "matched_delay_seconds": {
      "median": 60.0,
      "maximum": 60.0,
      "null_reason": null,
      "missed_events": 0
    },
    "runtime_seconds": 0.05734289065003395,
    "peak_memory_bytes": null,
    "peak_memory_null_reason": "not_measured",
    "predicted_events": [
      {
        "event_id": "pred-0000",
        "host_id": "customer-host-7",
        "metric": "memory_utilization",
        "start_at": "2026-08-01T04:11:00Z",
        "end_at": "2026-08-01T04:30:00Z",
        "trigger_at": "2026-08-01T04:11:00Z"
      }
    ],
    "truth_events": [
      {
        "event_id": "truth-0000",
        "host_id": "customer-host-7",
        "metric": "memory_utilization",
        "start_at": "2026-08-01T04:10:00Z",
        "end_at": "2026-08-01T04:30:00Z",
        "trigger_at": "2026-08-01T04:10:00Z"
      }
    ],
    "threshold": 0.0,
    "config": {
      "method_id": "fixed_threshold",
      "threshold": 85.0,
      "direction": "upper"
    },
    "labels": {
      "coverage": 1.0,
      "points": 160,
      "sha256": "sha256:7df43942c5ea5793d2c1f0ef2d64fd7477f797586236e0a834cd4e1a6c48df75",
      "source": "用户提供标签；本案例为独立受控注入",
      "status": "用户提供标签"
    },
    "selection_sha256": "sha256:d41a15bd94a0b6cc2d2fdbd684ca38fdc25541fd066b094b24d4e78bc797eb5a",
    "selected": "fixed",
    "phase": "uploaded_detection",
    "test_execution_started": true
  },
  "notice": null
}
```

## C. 独立模拟基准效果

```json
{
  "notice": "这些指标属于独立模拟基准，不代表上传数据的准确率或生产效果。",
  "result": {
    "experiment_sha256": "sha256:baf682e0c88d592650313c347417361462a56bbd67e25a2cbcad0fd3758b4a75",
    "generator_version": "metrics-synthetic/1",
    "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285",
    "policy": "fixed before planning; independent refit/calibration; never selection or repair",
    "scenario": "memory_shift",
    "status": "READY",
    "notice": "这些指标属于独立模拟基准，不代表上传数据的准确率或生产效果。",
    "execution_status": "SUCCEEDED",
    "evaluation": {
      "protocol": "metrics-evaluation/1",
      "execution_status": "SUCCEEDED",
      "engineering_status": "PASSED",
      "effect_status": "MEASURED",
      "acceptance_status": "MEASURED_NO_ACCEPTANCE_THRESHOLD",
      "point": {
        "tp": 59,
        "fp": 0,
        "fn": 1,
        "tn": 180,
        "abstained_normal": 0,
        "total": 240,
        "precision": {
          "value": 1.0,
          "numerator": 59,
          "denominator": 59,
          "null_reason": null
        },
        "recall": {
          "value": 0.9833333333333333,
          "numerator": 59,
          "denominator": 60,
          "null_reason": null
        },
        "f1": {
          "value": 0.9915966386554622,
          "numerator": 118,
          "denominator": 119,
          "null_reason": null
        }
      },
      "event": {
        "tp": 1,
        "fp": 0,
        "fn": 0,
        "pairs": [
          {
            "truth_id": "truth-0000",
            "prediction_id": "pred-0000",
            "delay_seconds": 60.0
          }
        ],
        "unmatched_truth_ids": [],
        "unmatched_prediction_ids": [],
        "precision": {
          "value": 1.0,
          "numerator": 1,
          "denominator": 1,
          "null_reason": null
        },
        "recall": {
          "value": 1.0,
          "numerator": 1,
          "denominator": 1,
          "null_reason": null
        },
        "f1": {
          "value": 1.0,
          "numerator": 2,
          "denominator": 2,
          "null_reason": null
        }
      },
      "coverage": {
        "value": 1.0,
        "numerator": 240,
        "denominator": 240,
        "null_reason": null
      },
      "normal_false_alarms_per_host_hour": {
        "value": 0.0,
        "numerator": 0,
        "denominator": 10800,
        "null_reason": null
      },
      "matched_delay_seconds": {
        "median": 60.0,
        "maximum": 60.0,
        "null_reason": null,
        "missed_events": 0
      },
      "runtime_seconds": 0.07676508277654648,
      "peak_memory_bytes": null,
      "peak_memory_null_reason": "not_measured",
      "predicted_events": [
        {
          "event_id": "pred-0000",
          "host_id": "sim-host-a",
          "metric": "memory_utilization",
          "start_at": "2026-01-04T02:41:00Z",
          "end_at": "2026-01-04T03:40:00Z",
          "trigger_at": "2026-01-04T02:41:00Z"
        }
      ],
      "truth_events": [
        {
          "event_id": "truth-0000",
          "host_id": "sim-host-a",
          "metric": "memory_utilization",
          "start_at": "2026-01-04T02:40:00Z",
          "end_at": "2026-01-04T03:40:00Z",
          "trigger_at": "2026-01-04T02:40:00Z"
        }
      ]
    },
    "calibration": {
      "threshold": 0.0,
      "rule": "fixed_parameter_unchanged",
      "labels_used": false,
      "binding": {
        "selection_sha256": "sha256:d41a15bd94a0b6cc2d2fdbd684ca38fdc25541fd066b094b24d4e78bc797eb5a",
        "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285",
        "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
        "config": {
          "method_id": "fixed_threshold",
          "threshold": 85.0,
          "direction": "upper"
        },
        "roles": {
          "train": {
            "path": "train.csv",
            "sha256": "sha256:872961e0a74fc3f72e1100475738576597ffe9b2f900c79b4023060dedd26049",
            "prefix_points": 60
          },
          "calibration": {
            "path": "calibration.csv",
            "sha256": "sha256:ec215bc11f1129f7703cf641743c06b9df71b041c6d69b67762f66a888e05ce1",
            "prefix_points": 60
          },
          "development": {
            "path": "development.csv",
            "sha256": "sha256:9a389eb7d0487c4bd127a4b354e144b83b1819f7b98dcfbd2da1ce548f2b6709",
            "prefix_points": 60
          },
          "test": {
            "path": "test.csv",
            "sha256": "sha256:7b47fe2b64d82c86dfb2609cc930d4edf2deff11a2a2f80fd739934b2926e464",
            "prefix_points": 60
          }
        },
        "state_policy": "fresh independent detector for calibration and test; independent of upload fitted state"
      }
    },
    "threshold": 0.0,
    "config": {
      "method_id": "fixed_threshold",
      "threshold": 85.0,
      "direction": "upper"
    },
    "binding": {
      "selection_sha256": "sha256:d41a15bd94a0b6cc2d2fdbd684ca38fdc25541fd066b094b24d4e78bc797eb5a",
      "manifest_sha256": "sha256:fa1285126d0d20c64f69aacafd732f851b54b704de045560cea5cfc11374e285",
      "source_sha256": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70",
      "config": {
        "method_id": "fixed_threshold",
        "threshold": 85.0,
        "direction": "upper"
      },
      "roles": {
        "train": {
          "path": "train.csv",
          "sha256": "sha256:872961e0a74fc3f72e1100475738576597ffe9b2f900c79b4023060dedd26049",
          "prefix_points": 60
        },
        "calibration": {
          "path": "calibration.csv",
          "sha256": "sha256:ec215bc11f1129f7703cf641743c06b9df71b041c6d69b67762f66a888e05ce1",
          "prefix_points": 60
        },
        "development": {
          "path": "development.csv",
          "sha256": "sha256:9a389eb7d0487c4bd127a4b354e144b83b1819f7b98dcfbd2da1ce548f2b6709",
          "prefix_points": 60
        },
        "test": {
          "path": "test.csv",
          "sha256": "sha256:7b47fe2b64d82c86dfb2609cc930d4edf2deff11a2a2f80fd739934b2926e464",
          "prefix_points": 60
        }
      },
      "state_policy": "fresh independent detector for calibration and test; independent of upload fitted state"
    }
  }
}
```
