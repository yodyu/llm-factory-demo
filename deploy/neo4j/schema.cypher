// Run explicitly in the authorized target database, then initialize the configured namespace.
CREATE CONSTRAINT metricsknowledge_identity IF NOT EXISTS
FOR (n:MetricsKnowledge) REQUIRE (n.namespace,n.id) IS UNIQUE;
CREATE CONSTRAINT metricsnamespace_identity IF NOT EXISTS
FOR (n:MetricsNamespace) REQUIRE (n.namespace,n.id) IS UNIQUE;
CREATE CONSTRAINT metricspublication_identity IF NOT EXISTS
FOR (n:MetricsPublication) REQUIRE (n.namespace,n.id) IS UNIQUE;
CREATE INDEX metrics_kind IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.kind);
CREATE INDEX metrics_method_id IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.method_id);
CREATE INDEX metrics_origin IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.origin);
CREATE INDEX metrics_task_id IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.task_id);
CREATE INDEX metrics_verification_status IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.verification_status);

// metrics-knowledge/2: DataContract, Metric, Environment; CONSUMES, PRODUCES,
// EVALUATED_WITH, DEPENDS_ON and SUPERSEDES are validated by both repositories.
CREATE INDEX metrics_capability_version IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.version);
