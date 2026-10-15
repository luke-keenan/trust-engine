from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Outcome(StrEnum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Rule:
    id: str
    sutra: str
    rule_name: str
    description: str
    severity: str
    nist_ref: str
    nist_characteristic: str


RULES = (
    Rule("S1", "Trust is the Foundation", "Data lineage", "Data lineage is documented.", "high", "GOVERN-1.2", "Accountable and transparent"),
    Rule("S2", "People First", "Human oversight", "Human oversight is present.", "critical", "GOVERN-2.1", "Human oversight"),
    Rule("S3", "Innovation over Restraint", "Model drift", "Model drift is within 0.5.", "high", "MEASURE-2.7", "Valid and reliable"),
    Rule("S4", "Fairness & Equity", "Bias audit", "Bias audit is complete and fairness is at least 0.7.", "high", "MEASURE-2.11", "Fair with harmful bias managed"),
    Rule("S5", "Accountability", "Access anomalies", "Access anomalies are at most two.", "high", "GOVERN-1.4", "Accountable and transparent"),
    Rule("S6", "Understandable by Design", "Explainability", "An explanation mechanism is available when reported.", "medium", "MEASURE-2.9", "Explainable and interpretable"),
    Rule("S7", "Safety, Resilience & Sustainability", "Operational safety", "Data quality is at least 0.6 and output variance at most 0.5.", "critical", "MANAGE-2.3", "Safe and resilient"),
)


def evaluate(signals: dict[str, Any]) -> list[dict[str, str]]:
    checks = (
        signals["data_lineage_documented"], signals["human_oversight"],
        signals["model_drift"] <= 0.5,
        signals["bias_audit_done"] and signals["fairness_metric"] >= 0.7,
        signals["access_anomaly_count"] <= 2, signals.get("explanation_available"),
        signals["data_quality"] >= 0.6 and signals["output_variance"] <= 0.5,
    )
    results = []
    for rule, passed in zip(RULES, checks):
        outcome = Outcome.WARN if passed is None else Outcome.PASS if passed else Outcome.FAIL
        results.append({
            "rule_id": rule.id, "sutra": rule.sutra, "rule_name": rule.rule_name,
            "result": outcome.value, "severity": rule.severity, "nist_ref": rule.nist_ref,
            "nist_characteristic": rule.nist_characteristic,
            "message": "Requirement satisfied" if outcome is Outcome.PASS else
            "Not reported; review required" if outcome is Outcome.WARN else rule.description,
        })
    return results


def pass_rate(results: list[dict[str, str]]) -> float:
    return sum({"pass": 1.0, "warn": 0.5, "fail": 0.0}[r["result"]] for r in results) / len(results)
