"""Small deterministic retrieval safeguards; no registry, service, or file access."""

import re


MONITOR_TERMS = (
    "cpu", "memory", "内存", "disk", "磁盘", "network", "网络", "latency", "延迟",
    "流量", "时序", "time series", "gauge", "单指标",
    "服务器", "主机", "server", "host", "负载", "load", "qps", "rps", "tps",
    "吞吐", "throughput", "响应时间", "响应耗时", "请求量", "请求数", "错误率",
    "error rate", "连接数", "connection count", "iops", "带宽", "bandwidth",
)


def mentions(query, term):
    term = term.casefold()
    if not term:
        return False
    if term.isascii():
        return re.search(r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])", query) is not None
    return term in query


def relevance_score(requirement, capabilities, *, metric_name=None):
    """One explicit monitoring-domain or eligible capability-name signal is required.

    This is a lexical scope gate, not semantic ranking or an evaluated retriever.
    Generic actions (monitor/anomaly/告警/突增) alone do not identify the domain.
    A bound dataset metric counts only when the requirement actually names it.
    Identity terms come only from the frozen eligible capabilities and dataset.
    """
    query = requirement.casefold()
    terms = set(MONITOR_TERMS)
    if metric_name:
        terms.add(metric_name)
    for node in capabilities:
        cap = node["payload"]
        terms.update(t for t in (cap.get("method_id"), cap.get("name")) if t)
    return sum(mentions(query, term) for term in terms)
