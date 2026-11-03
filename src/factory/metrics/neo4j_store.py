"""Parameterized, namespace-isolated Neo4j knowledge repository (5.26+)."""
import json
import os
import re
from pathlib import Path

from factory.metrics.knowledge import KINDS, RELATIONS, canonical, identity, retrieve, verify_snapshot, snapshot_schema, RELATION_PAIRS, latest_versions
from factory.runtime.artifacts import digest
from factory.runtime.security import SecretGuard


class KnowledgeUnavailable(RuntimeError):
    pass


def snapshot_value(nodes, relations):
    value = {'schema_version': snapshot_schema(nodes), 'nodes': sorted(nodes, key=lambda n: n['id']),
             'relations': sorted(relations, key=lambda r: (r['source'], r['relation'], r['target']))}
    return {**value, 'snapshot_id': digest(canonical(value).encode())}


def validate_records(nodes, relations):
    seen = {}
    for node in nodes:
        if node['kind'] not in KINDS or not isinstance(node['id'], str) or not isinstance(node['payload'], dict):
            raise ValueError('invalid knowledge node')
        SecretGuard().require_public(node)
        raw = canonical(node)
        if node['id'] in seen and seen[node['id']] != raw:
            raise ValueError('immutable knowledge node conflict')
        seen[node['id']] = raw
        p = node['payload']
        identity_kind = {'ValidationRun':'validation'}.get(node['kind'], node['kind'].lower())
        identity_payload = {key:p[key] for key in ('path','sha256','extraction_protocol') if key in p} if node['kind']=='Source' else p
        if identity(identity_kind, identity_payload) != node['id']:
            raise ValueError('immutable knowledge identity/content conflict')
        if node['kind'] == 'Source' and not re.fullmatch(r'sha256:[a-f0-9]{64}', p['sha256']):
            raise ValueError('invalid source digest')
        if node['kind'] == 'Capability':
            from contracts.metrics_knowledge import ExtractedCapability
            ExtractedCapability.model_validate({k:p[k] for k in ExtractedCapability.model_fields if k in p})
        if node['kind'] in {'DataContract', 'Metric', 'Environment'}:
            from contracts.metrics_knowledge import DataContract, Metric, Environment
            {'DataContract': DataContract, 'Metric': Metric, 'Environment': Environment}[node['kind']].model_validate(p)
        if node['kind'] == 'Chunk' and digest(p['text'].encode()) != p['sha256']:
            raise ValueError('chunk digest mismatch')
    edges = {}
    for r in relations:
        if not isinstance(r['provenance'], dict):
            raise ValueError('relationship provenance object required')
        if r['relation'] not in RELATIONS:
            raise ValueError('unknown relation')
        SecretGuard().require_public(r)
        key = (r['source'], r['relation'], r['target'])
        raw = canonical(r['provenance'])
        if key in edges and edges[key] != raw:
            raise ValueError('immutable relationship conflict')
        edges[key] = raw


def properties(node):
    p = node['payload']
    result = {k: p[k] for k in ('method_id', 'metric_kind', 'metric_kinds', 'single_host', 'min_history', 'origin',
              'source_status', 'dependency_profile', 'required_imports', 'conditions_status', 'knowledge_status', 'implementation_verified', 'reusable_implementation',
              'effect_status', 'acceptance_status', 'task_id', 'source_id', 'implementation_id', 'validation_id',
              'source_sha256', 'sha256', 'path', 'version', 'method_validation_protocol') if p.get(k) is not None}
    if node['kind'] == 'Implementation':
        result['method_id'] = p.get('config', {}).get('method_id')
    if node['kind'] == 'ValidationRun':
        result['verification_status'] = ('PASSED' if (p.get('method_checks') or {}).get('passed') else 'FAILED')
        result['effect_status'] = (p.get('final') or {}).get('effect_status', 'NOT_MEASURED')
    else:
        result['verification_status'] = (p.get('knowledge_status') or
            ('PASSED' if p.get('implementation_verified') else 'UNVERIFIED'))
    return {k: v for k, v in result.items() if v is not None}


# Same filter precedence as the frozen Python oracle. Null method means general material.
CAPABILITIES = '''MATCH (c:MetricsKnowledge {namespace:$ns,kind:'Capability'})
RETURN c.id AS id, CASE
WHEN coalesce(c.origin,'') <> $origin AND NOT (coalesce(c.origin,'')='reference' AND coalesce(c.source_status,'')='registered_card') THEN 'provenance_mode_mismatch'
WHEN c.method_id IS NOT NULL AND NOT c.method_id IN $methods THEN 'method_not_allowed'
WHEN c.source_status='registered_card' AND c.version <> $versions[c.method_id] THEN 'superseded_capability_version'
WHEN c.conditions_status = 'conflict' THEN 'conflicting_conditions'
WHEN c.conditions_status <> 'unknown' AND NOT $metric IN c.metric_kinds THEN 'metric_kind_not_supported'
WHEN c.conditions_status <> 'unknown' AND NOT c.single_host THEN 'not_single_host'
WHEN c.conditions_status <> 'unknown' AND c.min_history IS NOT NULL AND c.min_history > $history THEN 'insufficient_history'
WHEN c.dependency_profile <> $profile OR size(coalesce(c.required_imports,[])) > 0 THEN 'dependency_profile_incompatible'
ELSE null END AS reason'''


class Neo4jKnowledgeStore:
    def __init__(self, uri, auth, *, namespace, database='neo4j'):
        from neo4j import GraphDatabase
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,96}', namespace):
            raise ValueError('explicit bounded knowledge namespace required')
        self.namespace, self.database = namespace, database
        self.driver = GraphDatabase.driver(uri, auth=auth, connection_timeout=3,
            connection_acquisition_timeout=3, max_transaction_retry_time=3)

    @classmethod
    def from_config(cls, path=None):
        path = path or os.environ.get('FACTORY_METRICS_KNOWLEDGE')
        if not path:
            raise KnowledgeUnavailable('NEO4J_NOT_CONFIGURED: server-side knowledge config required')
        try:
            config = json.loads(Path(path).read_text())
            auth = Path(config['auth_file']).read_text().strip().split('/', 1)
            if len(auth) != 2:
                raise ValueError()
            return cls(config['uri'], tuple(auth), namespace=config['namespace'], database=config.get('database', 'neo4j'))
        except Exception:
            raise KnowledgeUnavailable('NEO4J_CONFIG_INVALID: use a server-side JSON config; legacy SQLite requires explicit migration') from None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self.driver.close()

    def _execute(self, callback, *, write=False):
        try:
            with self.driver.session(database=self.database) as session:
                return (session.execute_write if write else session.execute_read)(callback)
        except ValueError:
            raise
        except Exception:
            # Never propagate driver messages, addresses, auth or query parameters to UI/artifacts.
            raise KnowledgeUnavailable('NEO4J_UNAVAILABLE: check server connection; no empty fallback') from None

    def initialize(self):
        def schema(tx):
            for label in ('MetricsKnowledge', 'MetricsNamespace', 'MetricsPublication'):
                tx.run(f'CREATE CONSTRAINT {label.lower()}_identity IF NOT EXISTS FOR (n:{label}) REQUIRE (n.namespace,n.id) IS UNIQUE').consume()
            for field in ('kind', 'method_id', 'origin', 'task_id', 'verification_status'):
                tx.run(f'CREATE INDEX metrics_{field} IF NOT EXISTS FOR (n:MetricsKnowledge) ON (n.namespace,n.{field})').consume()
        self._execute(schema, write=True)
        self._execute(lambda tx: tx.run('MERGE (g:MetricsNamespace {namespace:$ns,id:$ns}) ON CREATE SET g.revision=0', ns=self.namespace).consume(), write=True)

    def _lock(self, tx):
        row = tx.run('MATCH (g:MetricsNamespace {namespace:$ns,id:$ns}) SET g.revision=g.revision+1 RETURN g.revision AS r', ns=self.namespace).single()
        if row is None:
            raise ValueError('knowledge namespace not initialized; run metrics-knowledge-init')

    def _insert(self, tx, nodes, relations):
        validate_records(nodes, relations)
        for node in nodes:
            raw = canonical(node['payload'])
            old = tx.run('MATCH (n:MetricsKnowledge {namespace:$ns,id:$id}) RETURN n.kind AS kind,n.payload AS payload', ns=self.namespace, id=node['id']).single()
            if old and (old['kind'] != node['kind'] or old['payload'] != raw):
                raise ValueError('immutable knowledge node conflict')
            # Labels/type are strictly from closed enums, never model-generated Cypher.
            tx.run(f'MERGE (n:MetricsKnowledge:{node["kind"]} {{namespace:$ns,id:$id}}) ON CREATE SET n.kind=$kind,n.payload=$payload,n += $props',
                   ns=self.namespace, id=node['id'], kind=node['kind'], payload=raw, props=properties(node)).consume()
        for r in relations:
            row = tx.run(f'''MATCH (a:MetricsKnowledge {{namespace:$ns,id:$source}}), (b:MetricsKnowledge {{namespace:$ns,id:$target}})
                MERGE (a)-[r:{r['relation']}]->(b) ON CREATE SET r.provenance=$provenance,r.id=$rid
                RETURN r.provenance AS provenance,a.kind AS source_kind,b.kind AS target_kind''', ns=self.namespace, source=r['source'], target=r['target'],
                provenance=canonical(r['provenance']), rid=identity('relation', {k:r[k] for k in ('source','relation','target')})).single()
            if not row:
                raise ValueError('invalid relationship endpoints')
            pairs = RELATION_PAIRS
            if (row['source_kind'],row['target_kind']) not in pairs[r['relation']]:
                raise ValueError('invalid relationship endpoint kinds')
            if row['provenance'] != canonical(r['provenance']):
                raise ValueError('immutable relationship conflict')
        self._validate_links(tx, nodes)

    def _validate_links(self, tx, nodes):
        for node in nodes:
            if node['kind'] != 'Capability':
                continue
            for cite in node['payload']['citations']:
                row = tx.run('''MATCH (c:MetricsKnowledge {namespace:$ns,id:$id})-[:DERIVED_FROM]->
                    (ch:Chunk {namespace:$ns,id:$chunk})-[:DERIVED_FROM]->(s:Source {namespace:$ns})
                    RETURN ch.payload AS chunk,s.payload AS source''', ns=self.namespace, id=node['id'], chunk=cite['chunk_id']).single()
                if not row or cite['quote'] not in json.loads(row['chunk'])['text']:
                    raise ValueError('capability citation or graph provenance invalid')
                source = json.loads(row['source'])
                symbols = {s[k] for s in source.get('symbols', []) for k in ('name','qualified_name') if k in s}
                if cite.get('symbol') is not None and cite['symbol'] not in symbols:
                    raise ValueError('unknown source AST symbol')

    def add(self, nodes, relations):
        def write(tx):
            self._lock(tx)
            self._insert(tx, nodes, relations)
        self._execute(write, write=True)

    def publish(self, nodes, relations, receipt):
        def write(tx):
            self._lock(tx)
            old = tx.run('MATCH (p:MetricsPublication {namespace:$ns,id:$id}) RETURN p.receipt AS receipt', ns=self.namespace, id=receipt['publication_id']).single()
            if old:
                if json.loads(old['receipt']) != receipt:
                    raise ValueError('immutable publication conflict')
                return json.loads(old['receipt'])
            self._insert(tx, nodes, relations)
            tx.run('CREATE (p:MetricsPublication {namespace:$ns,id:$id,receipt:$receipt})',ns=self.namespace,id=receipt['publication_id'],receipt=canonical(receipt)).consume()
            return receipt
        return self._execute(write, write=True)

    def _snapshot(self, tx):
        nodes = [{'id':r['id'],'kind':r['kind'],'payload':json.loads(r['payload'])} for r in tx.run(
            'MATCH (n:MetricsKnowledge {namespace:$ns}) RETURN n.id AS id,n.kind AS kind,n.payload AS payload ORDER BY id', ns=self.namespace)]
        relations = [dict(r) for r in tx.run('''MATCH (a:MetricsKnowledge {namespace:$ns})-[r]->(b:MetricsKnowledge {namespace:$ns})
            RETURN a.id AS source,type(r) AS relation,b.id AS target,r.provenance AS provenance ORDER BY source,relation,target''', ns=self.namespace)]
        for r in relations:
            r['provenance'] = json.loads(r['provenance'])
        validate_records(nodes, relations)
        return verify_snapshot(snapshot_value(nodes, relations))

    def _consistent(self, tx, conditions=None):
        def revision():
            row = tx.run('MATCH (g:MetricsNamespace {namespace:$ns,id:$ns}) RETURN g.revision AS r',ns=self.namespace).single()
            if row is None:
                raise ValueError('knowledge namespace not initialized')
            return row['r']
        before = revision()
        snapshot = self._snapshot(tx)
        result = None
        if conditions is not None:
            # Query actual edges as well as typed conditions; compare with the frozen oracle.
            rows = list(tx.run(CAPABILITIES, ns=self.namespace, origin=conditions.get('origin','llm_api'),
                methods=conditions['allowed_methods'], metric=conditions['metric_kind'], history=conditions['history_points'], profile=conditions.get('dependency_profile','metrics-py312-stdlib/1'), versions=latest_versions(snapshot)))
            eligible = {r['id'] for r in rows if r['reason'] is None}
            links = [dict(r) for r in tx.run('''MATCH (c:Capability {namespace:$ns})-[:DERIVED_FROM]->
                (ch:Chunk {namespace:$ns})-[:DERIVED_FROM]->(s:Source {namespace:$ns})
                WHERE c.id IN $ids RETURN DISTINCT c.id AS capability,ch.id AS chunk,s.id AS source''',ns=self.namespace,ids=sorted(eligible))]
            by_id = {n['id']:n for n in snapshot['nodes']}
            linked = {(r['capability'],r['chunk'],r['source']) for r in links}
            for cap_id in eligible:
                for cite in by_id[cap_id]['payload']['citations']:
                    chunk = by_id[cite['chunk_id']]
                    if (cap_id,chunk['id'],chunk['payload']['source_id']) not in linked:
                        raise ValueError('capability graph provenance missing')
            # Model candidates come from typed Neo4j selection and actual source edges.
            # The full immutable snapshot is retained separately for audit/replay.
            experience_ids = {r['id'] for r in tx.run('''MATCH (e:Experience {namespace:$ns})
                WHERE e.origin=$origin AND e.method_id IN $methods AND e.metric_kind=$metric
                RETURN e.id AS id''',ns=self.namespace,origin=conditions.get('origin','llm_api'),
                methods=conditions['allowed_methods'],metric=conditions['metric_kind'])}
            broken = list(tx.run("""MATCH (e:Experience {namespace:$ns})
                WHERE e.origin=$origin AND e.method_id IN $methods AND e.metric_kind=$metric AND e.reusable_implementation=true
                OPTIONAL MATCH (e)-[:LEARNED_FROM]->(v:ValidationRun {namespace:$ns})<-[:EVALUATED_BY]-(i:Implementation {namespace:$ns})
                WHERE v.id=e.validation_id AND i.id=e.implementation_id
                WITH e,count(v) AS links WHERE links=0 RETURN e.id AS id""",ns=self.namespace,
                origin=conditions.get('origin','llm_api'),methods=conditions['allowed_methods'],metric=conditions['metric_kind']))
            if broken:
                raise ValueError('successful experience graph evidence incomplete')
            oracle = retrieve(snapshot, **conditions)
            if conditions.get('enabled', True):
                selected_ids = eligible | experience_ids | {r[k] for r in links for k in ('chunk','source')}
                scoped = snapshot_value([n for n in snapshot['nodes'] if n['id'] in selected_ids],
                    [r for r in snapshot['relations'] if r['source'] in selected_ids and r['target'] in selected_ids])
                result = retrieve(scoped, **conditions)
                result['snapshot_id'] = snapshot['snapshot_id']
                result['schema_version'] = snapshot['schema_version']
                # Preserve all condition exclusions and the historical validator quarantine,
                # including quarantined experiences outside the permitted method subset.
                result['excluded'] = ([{'capability_id':r['id'],'reason':r['reason']} for r in sorted(rows,key=lambda r:r['id']) if r['reason']]
                    + [r for r in oracle['excluded'] if 'experience_id' in r])
                if result != oracle:
                    raise ValueError('graph-selected view differs from frozen retrieval')
            else:
                result = oracle
        if revision() != before:
            raise KnowledgeUnavailable('KNOWLEDGE_CHANGED_DURING_FREEZE: retry before starting task')
        return snapshot, result

    def snapshot(self):
        return self._execute(lambda tx: self._consistent(tx)[0])

    def freeze(self, **conditions):
        return self._execute(lambda tx: self._consistent(tx, conditions))

    def details(self, ids):
        if len(ids) > 128:
            raise ValueError('node detail limit exceeded')
        return self._execute(lambda tx: [{'id':r['id'],'kind':r['kind'],'payload':json.loads(r['payload'])} for r in tx.run(
            'MATCH (n:MetricsKnowledge {namespace:$ns}) WHERE n.id IN $ids RETURN n.id AS id,n.kind AS kind,n.payload AS payload ORDER BY id',ns=self.namespace,ids=ids)])

    def local_graph(self, *, search='', method='', origin='', status='', source='', limit=60):
        limit = max(1,min(int(limit),100))
        def read(tx):
            roots = [r['id'] for r in tx.run('''MATCH (n:MetricsKnowledge {namespace:$ns})
                WHERE ($search='' OR n.id CONTAINS $search OR n.task_id=$search OR n.path CONTAINS $search)
                AND ($method='' OR n.method_id=$method) AND ($origin='' OR n.origin=$origin)
                AND ($status='' OR n.verification_status=$status OR n.effect_status=$status)
                AND ($source='' OR n.source_id=$source OR n.id=$source OR n.path=$source)
                RETURN n.id AS id ORDER BY id LIMIT $limit''',ns=self.namespace,search=search,method=method,origin=origin,status=status,source=source,limit=min(limit,3 if not search and not method and not source else 10))]
            if not any((search, method, origin, status, source)):
                # Represent every entity kind in the bounded overview, rather
                # than seeding only alphabetically adjacent capabilities.
                roots = [r['id'] for r in tx.run('''MATCH (n:MetricsKnowledge {namespace:$ns})
                    WITH n ORDER BY n.id
                    WITH n.kind AS kind, collect(n.id)[0] AS id
                    RETURN id ORDER BY kind LIMIT 10''', ns=self.namespace)]
            ids = [r['id'] for r in tx.run('''MATCH (a:MetricsKnowledge {namespace:$ns}) WHERE a.id IN $roots
                MATCH p=(a)-[:DERIVED_FROM|REQUIRES|IMPLEMENTED_BY|EVALUATED_BY|LEARNED_FROM|CONSUMES|PRODUCES|EVALUATED_WITH|DEPENDS_ON|SUPERSEDES*0..3]-(b:MetricsKnowledge {namespace:$ns})
                WHERE all(n IN nodes(p) WHERE n.namespace=$ns)
                RETURN b.id AS id,min(length(p)) AS distance ORDER BY distance,id LIMIT $limit''',ns=self.namespace,roots=roots,limit=limit)]
            nodes = [{'id':r['id'],'kind':r['kind'],'payload':json.loads(r['payload'])} for r in tx.run(
                'MATCH (n:MetricsKnowledge {namespace:$ns}) WHERE n.id IN $ids RETURN n.id AS id,n.kind AS kind,n.payload AS payload ORDER BY id',ns=self.namespace,ids=ids)]
            edges = [dict(r) for r in tx.run('''MATCH (a:MetricsKnowledge {namespace:$ns})-[r]->(b:MetricsKnowledge {namespace:$ns})
                WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS source,type(r) AS relation,b.id AS target,r.provenance AS provenance,r.id AS id
                ORDER BY source,relation,target''',ns=self.namespace,ids=ids)]
            for edge in edges:
                edge['provenance']=json.loads(edge['provenance'])
            return {'nodes':nodes,'relations':edges,'roots':roots,'limit':limit,'scope':'live_local_graph'}
        return self._execute(read)
