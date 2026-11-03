# 数值监控验证报告
任务：ui-176b9b949a214571；流程：COMPLETED
工程通过、效果测量、业务达标分别记录；业务门槛以冻结需求和验收结果为准。

## A. 工程质量

```json
{
  "model_origin": "llm_api",
  "dependency_profile": "metrics-py312-stdlib/1",
  "image": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
  "prompt_version": "metrics-prompts/6",
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
            "knowledge_snapshot": "sha256:8629bb2cc8fb47ca561445d92ebc70655622684d48b6e9b7d4ae2b5941ff8754",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:83a8d6be7a979e9049d679c822c43fb727ecaad5ff30aa62da142ead69245061"
          },
          "source": "sha256:d24379db52651e37bdf3910cf4ea3bd826342329407de12e1421fa45a273e438"
        },
        "labels_used": false,
        "quantile": 0.99,
        "rule": "nearest-rank",
        "score_count": 240,
        "threshold": 1.1672470868257325
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "ewma_alpha0p3_q99_p2",
      "plan": {
        "candidate_id": "ewma_alpha0p3_q99_p2",
        "capability_id": "capability-4221130af82542b1e0f26df0f7045cfbf27f62fcd00e47a1478672f2063ccd17",
        "config": {
          "alpha": 0.3,
          "direction": "upper",
          "method_id": "ewma",
          "min_history": 3,
          "quantile": 0.99
        },
        "knowledge_ids": [
          "capability-4221130af82542b1e0f26df0f7045cfbf27f62fcd00e47a1478672f2063ccd17",
          "chunk-11ca31cb82ace4c988fd45e3b108a0f0b6956534e4225a49d406aed476b7f8fd",
          "source-f5e5f8ac42e9fd7f7bb393e7cc89533f14187c96f6d02a17f9fd4374221933b2"
        ],
        "limitations": [
          "固定训练基线可能保留长期偏移；若训练后业务水位整体合理上升，可能增加误报。",
          "较小alpha会降低对突发尖峰的响应速度；本候选使用默认0.3，未根据模拟数据额外调参。"
        ],
        "parameter_sources": {
          "alpha": "protocol_default",
          "direction": "user_explicit",
          "min_history": "protocol_default",
          "persistence_points": "user_explicit",
          "quantile": "protocol_default"
        },
        "persistence_points": 2,
        "selection_reason": "EWMA适用于持续变化，并以训练期均值作为固定baseline，对内存利用率逐步升高形成的长期上移较敏感；其upper方向与可信目标完全一致。alpha=0.3、min_history=3和quantile=0.99均来自方法默认配置；连续2点告警来自用户明确约束。假设可信侧会按0.99分位数完成无标签校准，并且默认平滑速度适合本次60秒采样的模拟数据。"
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
            "denominator": 127,
            "null_reason": null,
            "numerator": 118,
            "value": 0.9291338582677166
          },
          "fn": 1,
          "fp": 8,
          "precision": {
            "denominator": 67,
            "null_reason": null,
            "numerator": 59,
            "value": 0.8805970149253731
          },
          "recall": {
            "denominator": 60,
            "null_reason": null,
            "numerator": 59,
            "value": 0.9833333333333333
          },
          "tn": 172,
          "total": 240,
          "tp": 59
        },
        "predicted_events": [
          {
            "end_at": "2026-01-03T03:48:00Z",
            "event_id": "pred-0000",
            "host_id": "sim-host-a",
            "metric": "memory_utilization",
            "start_at": "2026-01-03T02:41:00Z",
            "trigger_at": "2026-01-03T02:41:00Z"
          }
        ],
        "protocol": "metrics-evaluation/1",
        "runtime_seconds": 0.10088878870010376,
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
          "capability_id": "capability-4221130af82542b1e0f26df0f7045cfbf27f62fcd00e47a1478672f2063ccd17",
          "capability_version": "1.1.0",
          "explanation": "实现冻结候选 EWMA：训练期均值作为固定 baseline，总体标准差作为 scale；在线点先更新 EWMA，original_present=True 才计入真实历史，upper 方向输出 (ewma-baseline)/scale。缺失不更新状态，非有限数返回 invalid_input；状态序列化保留配置和全部统计量。",
          "knowledge_ids": [
            "capability-4221130af82542b1e0f26df0f7045cfbf27f62fcd00e47a1478672f2063ccd17",
            "chunk-11ca31cb82ace4c988fd45e3b108a0f0b6956534e4225a49d406aed476b7f8fd",
            "source-f5e5f8ac42e9fd7f7bb393e7cc89533f14187c96f6d02a17f9fd4374221933b2"
          ],
          "origin": "llm_api",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:99e8d1e67f8b4b1fd9df769136a4b0bb3778393bdb266ccb706b1c289755bded",
            "checks.py": "sha256:025c96a17a67127db78722b0cfefe382b79c1c22eb88f6cea06c3f6c429c58fd",
            "reference.py": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333"
          },
          "source_path": "candidate-60cfebeccce8f8f8e979b3274528c0b828f50b74b33f99708415c0c8b8a8dc8d/v0.py",
          "source_ref": "sha256:d24379db52651e37bdf3910cf4ea3bd826342329407de12e1421fa45a273e438",
          "source_sha256": "sha256:d24379db52651e37bdf3910cf4ea3bd826342329407de12e1421fa45a273e438",
          "specification_sha256": "sha256:53abdca0789200f3681895fdd88b049227e8b5e9587a9cc82d7f1d1bcc70bda2",
          "validation": {
            "candidate_id": "ewma_alpha0p3_q99_p2",
            "capability_version": "1.1.0",
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
            "origin": "llm_api",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:99e8d1e67f8b4b1fd9df769136a4b0bb3778393bdb266ccb706b1c289755bded",
              "checks.py": "sha256:025c96a17a67127db78722b0cfefe382b79c1c22eb88f6cea06c3f6c429c58fd",
              "reference.py": "sha256:44dd23aa0347c6a21a5bdd5ac6cc405385225bd8af67b44d9c95c93cd66a1333"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:d24379db52651e37bdf3910cf4ea3bd826342329407de12e1421fa45a273e438",
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
            "knowledge_snapshot": "sha256:8629bb2cc8fb47ca561445d92ebc70655622684d48b6e9b7d4ae2b5941ff8754",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:83a8d6be7a979e9049d679c822c43fb727ecaad5ff30aa62da142ead69245061"
          },
          "source": "sha256:06527fe8ef00a3f4fe7d054e2e85d1bd1ae19483dc890d31eca79ab89ba64f9d"
        },
        "labels_used": false,
        "rule": "fixed_parameter_unchanged",
        "threshold": 0.0
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "fixed_threshold_85_p2",
      "plan": {
        "candidate_id": "fixed_threshold_85_p2",
        "capability_id": "capability-980278873da6192086687b800c048bd4ab9a43d94e9f70b85bbac707a6b8e7c2",
        "config": {
          "direction": "upper",
          "method_id": "fixed_threshold",
          "threshold": 85.0
        },
        "knowledge_ids": [
          "capability-980278873da6192086687b800c048bd4ab9a43d94e9f70b85bbac707a6b8e7c2",
          "chunk-6e26ee889962cededda5b592fdb65c8638e92974b684d337218eebe3bd42d952"
        ],
        "limitations": [
          "只能识别超过85%的水平，不能发现低于85%但相对历史显著升高的趋势。",
          "等号不触发；值正好为85%时分数为0。",
          "演示纠正：已移除未提供的知识引用，相关参数不再标记为知识依据。"
        ],
        "parameter_sources": {
          "direction": "user_explicit",
          "persistence_points": "user_explicit",
          "threshold": "user_explicit"
        },
        "persistence_points": 2,
        "selection_reason": "固定阈值直接表达用户给定的内存利用率85%上侧业务阈值，upper分数为x-85，严格大于0才进入异常候选，再由连续2点规则抑制单点抖动。该方法不需要历史基线，适合与自适应方法进行基准对照。阈值和方向均由用户明确给出，不是候选假设。"
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
        "runtime_seconds": 0.1356843076646328,
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
          "capability_id": "capability-980278873da6192086687b800c048bd4ab9a43d94e9f70b85bbac707a6b8e7c2",
          "capability_version": "1.1.0",
          "explanation": "实现用户明确指定的固定上侧阈值：score=value-85，value为None时missing_input，非有限数值时invalid_input，evidence仅在ok时包含threshold；不实现连续两点告警，由可信侧处理。",
          "knowledge_ids": [
            "capability-980278873da6192086687b800c048bd4ab9a43d94e9f70b85bbac707a6b8e7c2",
            "chunk-6e26ee889962cededda5b592fdb65c8638e92974b684d337218eebe3bd42d952"
          ],
          "origin": "llm_api",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:a19217ef27bff5c0726e6be8d4dc123a509bfe2d34c6fe8b63b0f2cd6c5ef045",
            "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
            "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
          },
          "source_path": "candidate-9ffd513ec09cff74c2f5fc8a52a712b0fe49d3e72447c7752a6e36c0a9713c28/v0.py",
          "source_ref": "sha256:06527fe8ef00a3f4fe7d054e2e85d1bd1ae19483dc890d31eca79ab89ba64f9d",
          "source_sha256": "sha256:06527fe8ef00a3f4fe7d054e2e85d1bd1ae19483dc890d31eca79ab89ba64f9d",
          "specification_sha256": "sha256:d78418b686499b015abb691e10e65fad63592d12ad25bcab36e2ced5af7a2060",
          "validation": {
            "candidate_id": "fixed_threshold_85_p2",
            "capability_version": "1.1.0",
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
            "origin": "llm_api",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:a19217ef27bff5c0726e6be8d4dc123a509bfe2d34c6fe8b63b0f2cd6c5ef045",
              "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
              "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:06527fe8ef00a3f4fe7d054e2e85d1bd1ae19483dc890d31eca79ab89ba64f9d",
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
            "knowledge_snapshot": "sha256:8629bb2cc8fb47ca561445d92ebc70655622684d48b6e9b7d4ae2b5941ff8754",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:83a8d6be7a979e9049d679c822c43fb727ecaad5ff30aa62da142ead69245061"
          },
          "source": "sha256:9dc02e6ddeb151ff8ead98d7b2c44f163ff177c0e89dc73c4f97ab4d679aa9e8"
        },
        "labels_used": false,
        "quantile": 0.99,
        "rule": "nearest-rank",
        "score_count": 240,
        "threshold": 2.6414490111655153
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "rolling_mad_w30_q99_p2",
      "plan": {
        "candidate_id": "rolling_mad_w30_q99_p2",
        "capability_id": "capability-6747a218c8d93e1ea51119c340c872561250a5aff4c107065488b17e1c70419f",
        "config": {
          "direction": "upper",
          "method_id": "rolling_mad",
          "min_history": 15,
          "quantile": 0.99,
          "window": 30
        },
        "knowledge_ids": [
          "capability-6747a218c8d93e1ea51119c340c872561250a5aff4c107065488b17e1c70419f",
          "chunk-540d23ca3e0b80a2dad62cf1c6226169b3fb8c24be12c111857f374835b2e568",
          "chunk-7dac2ccb0ebc85c7009c621e5b2f788300c84ffc40fb8cac687c24d2a85a217a",
          "chunk-89dee4a6e8de7c81be4b201100029a46a872709076128ca67b394c6ecd2a4816",
          "source-b87632b829b20184b15b4a9610c028db947eb04a8672c227b3caa14ff39afcd3",
          "source-ba12995471501af4d22a092ff63e3420003103c0a364a4769ae2afa939fd5cab"
        ],
        "limitations": [
          "自适应历史窗口可能把持续上升吸收为新基线，因此对“持续升高”场景可能不如固定训练基线敏感。",
          "周期性模式若未在短窗口中充分表示，可能造成误报。",
          "至少15个真实观测后才能评分，冷启动阶段为insufficient_history。"
        ],
        "parameter_sources": {
          "direction": "user_explicit",
          "min_history": "protocol_default",
          "persistence_points": "user_explicit",
          "quantile": "protocol_default",
          "window": "protocol_default"
        },
        "persistence_points": 2,
        "selection_reason": "滚动MAD使用最近30个时间槽的中位数和MAD，检测当前内存利用率相对近期正常水平的上侧偏离；upper方向与任务目标一致。默认窗口和min_history适合60秒采样，并可处理缺失槽及短缺失插补。假设模拟数据中的异常是相对近期基线的显著突增，而不是长达数十分钟的缓慢爬升。"
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
        "runtime_seconds": 0.1439221315085888,
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
          "capability_id": "capability-6747a218c8d93e1ea51119c340c872561250a5aff4c107065488b17e1c70419f",
          "capability_version": "1.1.0",
          "explanation": "实现 rolling_mad：使用最近30个时间槽，真实原始观测满15个后评分；中位数和MAD基于评分前历史，插补值可参与统计但不计真实历史；训练有效原始值IQR的百万分之一与1e-9取最大值作为尺度下限；当前点先评分再入窗，缺失和不可用点也保留为时间槽。",
          "knowledge_ids": [
            "capability-6747a218c8d93e1ea51119c340c872561250a5aff4c107065488b17e1c70419f",
            "chunk-540d23ca3e0b80a2dad62cf1c6226169b3fb8c24be12c111857f374835b2e568",
            "chunk-7dac2ccb0ebc85c7009c621e5b2f788300c84ffc40fb8cac687c24d2a85a217a",
            "chunk-89dee4a6e8de7c81be4b201100029a46a872709076128ca67b394c6ecd2a4816",
            "source-b87632b829b20184b15b4a9610c028db947eb04a8672c227b3caa14ff39afcd3",
            "source-ba12995471501af4d22a092ff63e3420003103c0a364a4769ae2afa939fd5cab"
          ],
          "origin": "llm_api",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:8c0d97bc2c8d13616df091cf37dd91afb32c06abe43ac6449d9c512c083333bf",
            "checks.py": "sha256:2ae8cf000dda9f9f86e3c19c993b76d14af181fba24d81d2a020643fdd9e613c",
            "reference.py": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7"
          },
          "source_path": "candidate-d84ad70973e0d239b24eaa93550665370d24276a19fdaf5fd0acc152fc8c3ec4/v0.py",
          "source_ref": "sha256:9dc02e6ddeb151ff8ead98d7b2c44f163ff177c0e89dc73c4f97ab4d679aa9e8",
          "source_sha256": "sha256:9dc02e6ddeb151ff8ead98d7b2c44f163ff177c0e89dc73c4f97ab4d679aa9e8",
          "specification_sha256": "sha256:1341c8dba78c069e25220a8afe6f80caaf9150384348d3c7f47c3c4e1dce8309",
          "validation": {
            "candidate_id": "rolling_mad_w30_q99_p2",
            "capability_version": "1.1.0",
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
            "origin": "llm_api",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:8c0d97bc2c8d13616df091cf37dd91afb32c06abe43ac6449d9c512c083333bf",
              "checks.py": "sha256:2ae8cf000dda9f9f86e3c19c993b76d14af181fba24d81d2a020643fdd9e613c",
              "reference.py": "sha256:aa1246059df4e8f057f78f274db84d98a52391ad351bd192b654e5ee8cf6c7c7"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:9dc02e6ddeb151ff8ead98d7b2c44f163ff177c0e89dc73c4f97ab4d679aa9e8",
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
            "method_id": "threshold_probe",
            "threshold": 85.0
          },
          "dataset": {
            "image_id": "sha256:ec7e3f613d45080c580bed6c83b6404df77b17a7cb72be69bacc80cce954ed31",
            "knowledge_snapshot": "sha256:8629bb2cc8fb47ca561445d92ebc70655622684d48b6e9b7d4ae2b5941ff8754",
            "labels_sha256": "sha256:6a517b2eb58c8139863a5c9439b37bde43e1e4a4b0486a6d1ae94bc395e24be5",
            "manifest_sha256": "sha256:83a8d6be7a979e9049d679c822c43fb727ecaad5ff30aa62da142ead69245061"
          },
          "source": "sha256:5eb9f0789e436dd0c5e4609553cacf89b059125cfab3668b0238039ab6635ada"
        },
        "labels_used": false,
        "rule": "fixed_parameter_unchanged",
        "threshold": 0.0
      },
      "calibration_status": "SUCCEEDED",
      "candidate_id": "threshold_probe_85_p2",
      "plan": {
        "candidate_id": "threshold_probe_85_p2",
        "capability_id": "capability-83a3b18547ffce40c11ca2d018fbc959668cacb379f34c86bde5072744b03919",
        "config": {
          "direction": "upper",
          "method_id": "threshold_probe",
          "threshold": 85.0
        },
        "knowledge_ids": [
          "capability-83a3b18547ffce40c11ca2d018fbc959668cacb379f34c86bde5072744b03919",
          "chunk-6e26ee889962cededda5b592fdb65c8638e92974b684d337218eebe3bd42d952",
          "chunk-4cde96ee5d5f4c785edb11ca42de730e583dec8ac36327aa9388973ab7666a09",
          "source-c6d85ec31dbd8809fc844451579165bc762b556e94fd925222e0afb96d75a74c",
          "source-77c556c6553d4192078e1bfdf985a4cd89e45754f491b6ee917b9dcc07769438"
        ],
        "limitations": [
          "与fixed_threshold检测逻辑基本等价，方法层面的差异化信息有限。",
          "只能捕获超过85%的水平异常，不能单独识别未达85%的趋势性升高。"
        ],
        "parameter_sources": {
          "direction": "user_explicit",
          "persistence_points": "user_explicit",
          "threshold": "user_explicit"
        },
        "persistence_points": 2,
        "selection_reason": "阈值探针与固定阈值同样直接实现用户明确给定的85%上侧阈值，但其参数契约将threshold限制在0到100，和内存利用率百分比的valid_range完全匹配。该候选可作为同一固定阈值规则的契约化对照，并使用连续2点告警。"
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
        "runtime_seconds": 0.09661605581641197,
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
          "capability_id": "capability-83a3b18547ffce40c11ca2d018fbc959668cacb379f34c86bde5072744b03919",
          "capability_version": "1.0.0",
          "explanation": "实现用户明确指定的上侧阈值探针：threshold=85.0，分数为 value-85.0；等于阈值得0分，严格大于0才会由可信侧在连续两点后告警。缺失值返回missing_input，非有限数值返回invalid_input；fit只验证训练数据存在有效观测，reset不保留历史状态。",
          "knowledge_ids": [
            "capability-83a3b18547ffce40c11ca2d018fbc959668cacb379f34c86bde5072744b03919",
            "chunk-6e26ee889962cededda5b592fdb65c8638e92974b684d337218eebe3bd42d952",
            "chunk-4cde96ee5d5f4c785edb11ca42de730e583dec8ac36327aa9388973ab7666a09",
            "source-c6d85ec31dbd8809fc844451579165bc762b556e94fd925222e0afb96d75a74c",
            "source-77c556c6553d4192078e1bfdf985a4cd89e45754f491b6ee917b9dcc07769438"
          ],
          "origin": "llm_api",
          "parent_source_sha256": null,
          "plugin_hashes": {
            "capability.json": "sha256:be1f518eed062b83b27bd1790af70c7a38f576756cffe2f91e7eca4ba240160e",
            "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
            "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
          },
          "source_path": "candidate-2541b7702fe4e681ac87408c92510fcb36b6a3778114c59a8c25a7a9d954837b/v0.py",
          "source_ref": "sha256:5eb9f0789e436dd0c5e4609553cacf89b059125cfab3668b0238039ab6635ada",
          "source_sha256": "sha256:5eb9f0789e436dd0c5e4609553cacf89b059125cfab3668b0238039ab6635ada",
          "specification_sha256": "sha256:d78418b686499b015abb691e10e65fad63592d12ad25bcab36e2ced5af7a2060",
          "validation": {
            "candidate_id": "threshold_probe_85_p2",
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
              "method_id": "threshold_probe",
              "threshold": 85.0
            },
            "dependency_profile": "metrics-py312-stdlib/1",
            "origin": "llm_api",
            "passed": true,
            "plugin_hashes": {
              "capability.json": "sha256:be1f518eed062b83b27bd1790af70c7a38f576756cffe2f91e7eca4ba240160e",
              "checks.py": "sha256:009933701326684689fb100d585f4bb44d596016fa7d9278147f6999566e9427",
              "reference.py": "sha256:8905463c215a83c37c295d265a4c6ef0d1f457911f7cae9320777ddb76c3ce70"
            },
            "protocol": "metrics-method-check/3",
            "repairable": true,
            "source_sha256": "sha256:5eb9f0789e436dd0c5e4609553cacf89b059125cfab3668b0238039ab6635ada",
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
    "kind": "api",
    "requests": 5,
    "reservations": 5,
    "input_tokens": 212949,
    "output_tokens": 9094,
    "total_tokens": 222043,
    "missing_usage_requests": 0,
    "notice": "Counts include retries and repairs; tokens are provider-reported only; missing usage is not zero."
  },
  "workflow_runtime_seconds": 216.89810618385673,
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
        "sha256": "sha256:605b9bb673608aad066b4bd81c10678d15cd6126f3bb9801663b7e2fb86d3c3a"
      },
      "development": {
        "path": "development.csv",
        "prefix_points": 60,
        "sha256": "sha256:bab9614eaa452351b2a05d50d003c6a28be1c5cc389b5c54e749325af34a10d3"
      },
      "test": {
        "path": "test.csv",
        "prefix_points": 60,
        "sha256": "sha256:7b24563c551f4803d09372f44046f74e4172d7cc7b70390e58c76b245dc92003"
      },
      "train": {
        "path": "train.csv",
        "prefix_points": 60,
        "sha256": "sha256:ca450606ca4dd56cb12050fc87ab0d8fab85ca7d4d1447eb4477ca95ccb257c7"
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
      "point_f1_desc",
      "event_f1_desc",
      "false_alarm_rate_asc",
      "matched_delay_asc",
      "coverage_desc",
      "candidate_id"
    ],
    "objective": "sustained_coverage",
    "policy": "balanced",
    "protocol": "metrics-selection/2",
    "ranking": [
      "fixed_threshold_85_p2",
      "threshold_probe_85_p2",
      "ewma_alpha0p3_q99_p2",
      "rolling_mad_w30_q99_p2"
    ],
    "reason": "按开发集目标及次级 Fβ、正常误报频次、匹配延迟、覆盖率和候选ID排序；最终测试不参与选择。",
    "requested_policy": "balanced",
    "selected": "fixed_threshold_85_p2",
    "status": "SELECTED",
    "tie_broken_by": "candidate_id",
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
    "runtime_seconds": 0.08965741842985153,
    "selected": "fixed_threshold_85_p2",
    "selection_sha256": "sha256:68d00fb161fd7f43e31f251e4350fc63d1cd89feb40f7716a9808be17a826ae8",
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
      "rolling_mad",
      "threshold_probe"
    ],
    "anomaly_target": "upper",
    "budgets": {
      "candidates": 4,
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
    "knowledge_snapshot": "sha256:8629bb2cc8fb47ca561445d92ebc70655622684d48b6e9b7d4ae2b5941ff8754",
    "metric": "memory_utilization",
    "model_mode": "api",
    "model_profile_id": "metrics-c9a0036e73b91ba3",
    "ranking_preferences": [],
    "requirement": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
    "requirement_draft": {
      "binding": "sha256:8ac834b876fa44212cc42761057061fa9a85160858d8441e6955acabe8a17133",
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
          "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
          "turn": 1
        },
        "evaluation_objective": {
          "origin": "user_explicit",
          "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
          "turn": 1
        },
        "methods": {
          "origin": "user_explicit",
          "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
          "turn": 1
        },
        "persistence_points": {
          "origin": "user_explicit",
          "quote": "连续两点",
          "turn": 1
        },
        "scenario": {
          "origin": "user_explicit",
          "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
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
      "model_mode": "api",
      "model_usage": {
        "input_tokens": 970,
        "kind": "api",
        "missing_usage_requests": 0,
        "notice": "Counts include retries and repairs; tokens are provider-reported only; missing usage is not zero.",
        "output_tokens": 112,
        "requests": 1,
        "reservations": 1,
        "total_tokens": 1082
      },
      "parse_task_id": "understand-f08c36f47ec5497c",
      "revision": 2,
      "schema_version": "metrics-requirement-draft/1",
      "turns": [
        "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。"
      ],
      "values": {
        "data_source": "simulation",
        "direction": "upper",
        "evaluation_objective": "sustained_coverage",
        "methods": [
          "ewma",
          "fixed_threshold",
          "rolling_mad",
          "threshold_probe"
        ],
        "persistence_points": 2,
        "scenario": "memory_shift",
        "selection_policy": "balanced",
        "threshold": 85.0
      }
    },
    "schema_version": "metrics-task/1",
    "selection_policy": "balanced",
    "task_id": "ui-176b9b949a214571",
    "validation_protocol": "metrics-evaluation/1"
  },
  "selection_explanation": {
    "评价目标": "持续区间覆盖",
    "实际选优偏好": "综合选优",
    "比较依据": "有标签开发集",
    "排序顺序": "开发点级 F1 → 开发事件 F1 → 开发正常误报频次（升序） → 开发匹配延迟（升序） → 开发覆盖率（降序） → 候选标识（稳定决胜）",
    "实际决胜项": "候选标识（稳定决胜）"
  },
  "evaluation_policy": null,
  "requirement": {
    "binding": "sha256:8ac834b876fa44212cc42761057061fa9a85160858d8441e6955acabe8a17133",
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
        "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
        "turn": 1
      },
      "evaluation_objective": {
        "origin": "user_explicit",
        "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
        "turn": 1
      },
      "methods": {
        "origin": "user_explicit",
        "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
        "turn": 1
      },
      "persistence_points": {
        "origin": "user_explicit",
        "quote": "连续两点",
        "turn": 1
      },
      "scenario": {
        "origin": "user_explicit",
        "quote": "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。",
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
    "model_mode": "api",
    "model_usage": {
      "input_tokens": 970,
      "kind": "api",
      "missing_usage_requests": 0,
      "notice": "Counts include retries and repairs; tokens are provider-reported only; missing usage is not zero.",
      "output_tokens": 112,
      "requests": 1,
      "reservations": 1,
      "total_tokens": 1082
    },
    "parse_task_id": "understand-f08c36f47ec5497c",
    "revision": 2,
    "schema_version": "metrics-requirement-draft/1",
    "turns": [
      "用模拟数据检测单主机内存利用率持续升高，比较全部方法，阈值85%，连续两点告警，输出代码和验证报告。"
    ],
    "values": {
      "data_source": "simulation",
      "direction": "upper",
      "evaluation_objective": "sustained_coverage",
      "methods": [
        "ewma",
        "fixed_threshold",
        "rolling_mad",
        "threshold_probe"
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
