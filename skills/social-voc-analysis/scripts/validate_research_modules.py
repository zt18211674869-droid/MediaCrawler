"""Check keyword-coding-v1 and journey-map-v1 against a frozen opinion snapshot.

Usage: python validate_research_modules.py RUN_DIR --modules all --output result.json
Only provenance, structure, exact text and counting invariants are checked. The
journey v1 observed_proxy contract is stage experience-source coverage; arbitrary
business metrics need a separately defined and validated schema.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class Validator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.errors, self.warnings = [], []
        self.opinions, self.evidence, self.sources = {}, {}, {}
        self.source_path = None
        self.summary = {}

    def error(self, code, path, message):
        self.errors.append({'code': code, 'path': path, 'message': message})

    def check(self, condition, code, path, message):
        if not condition:
            self.error(code, path, message)
        return bool(condition)

    def local_path(self, name, label):
        if not isinstance(name, str) or not name.strip():
            self.error('path_required', label, 'Expected a nonempty relative file path')
            return None
        target = (self.root / name).resolve()
        if not target.is_relative_to(self.root):
            self.error('path_outside_run', label, 'Source paths must stay inside run_dir')
            return None
        return target

    def read(self, path):
        try:
            data = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(data, dict):
                raise ValueError('Top-level JSON must be an object')
            return data
        except (OSError, ValueError) as exc:
            self.error('read_error', str(path), str(exc))
            return {}

    def digest(self, path, expected, label):
        if path is None:
            return
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            self.check(expected == actual, 'hash_mismatch', label,
                       'SHA256 missing or different from current source bytes')
        except OSError as exc:
            self.error('source_missing', label, str(exc))

    def index(self, rows, label, key='id'):
        result = {}
        if not self.check(isinstance(rows, list), 'array_required', label, 'Expected an array'):
            return result
        for n, row in enumerate(rows):
            p = f'{label}[{n}]'
            if not isinstance(row, dict):
                self.error('object_required', p, 'Expected an object')
                continue
            rid = row.get(key)
            if not self.check(isinstance(rid, str) and bool(rid.strip()), 'id_required', p, f'Missing {key}'):
                continue
            self.check(rid not in result, 'duplicate_id', p, rid)
            result[rid] = row
        return result

    def texts(self, row, fields, label):
        for field in fields:
            value = row.get(field)
            self.check(isinstance(value, str) and bool(value.strip()), 'text_required',
                       f'{label}.{field}', 'Expected nonempty text')

    def refs(self, row, field, pool, label):
        values = row.get(field)
        p = f'{label}.{field}'
        if not self.check(isinstance(values, list) and all(isinstance(x, str) for x in values),
                          'refs_required', p, 'Expected an array of string IDs'):
            return []
        self.check(len(values) == len(set(values)), 'duplicate_ref', p, 'Repeated reference')
        for value in values:
            self.check(value in pool, 'unknown_ref', p, value)
        return [v for v in values if v in pool]

    def same_fields(self, row, original, fields, label, required=True):
        for field in fields:
            if required or field in row:
                self.check(row.get(field) == original.get(field), 'join_mismatch',
                           f'{label}.{field}', 'Does not match frozen opinion')

    def evidence_records(self, rows, label, allowed):
        if not self.check(isinstance(rows, list), 'array_required', label, 'Expected an array'):
            return
        for n, row in enumerate(rows):
            p = f'{label}[{n}]'
            if not isinstance(row, dict):
                self.error('object_required', p, 'Expected a text-and-evidence object')
                continue
            self.texts(row, ['text'], p)
            ids = self.refs(row, 'evidence_opinion_ids', self.opinions, p)
            self.check(bool(ids), 'evidence_refs_empty', p, 'A claim needs at least one valid opinion reference')
            self.check(set(ids) <= allowed, 'stage_reference_mismatch', p,
                       'Referenced opinion is not assigned to this stage/branch')

    def original_text(self, row, field, label):
        source = self.sources.get(row.get('source_key'))
        self.check(source is not None, 'unknown_source', label, 'Unknown source_key')
        value = row.get(field)
        self.texts(row, [field], label)
        if source:
            self.check(source.get('text_kind') not in {'summary', 'rewritten', 'unknown'},
                       'nonverbatim_source', label, 'Source cannot support verbatim quotation')
            self.check(isinstance(value, str) and bool(value) and value in source.get('text', ''),
                       'not_continuous_original', f'{label}.{field}', 'Not a continuous original substring')
            if 'source_url' in row:
                self.check(row['source_url'] == source.get('url'), 'source_url_mismatch', label,
                           'URL differs from frozen source')

    def base(self):
        path = self.root / 'opinions.json'
        doc = self.read(path)
        meta = doc.get('meta', {})
        if not isinstance(meta, dict):
            self.error('object_required', 'opinions.meta', 'Expected an object')
            meta = {}
        self.source_path = self.local_path(meta.get('source_analysis'), 'opinions.meta.source_analysis')
        self.digest(self.source_path, meta.get('source_sha256'), 'opinions.meta.source_sha256')
        analysis = self.read(self.source_path) if self.source_path else {}
        self.evidence = self.index(analysis.get('evidence'), 'evidence')
        for eid, source in self.evidence.items():
            source_key = source.get('display_key') or eid
            if not self.check(isinstance(source_key, str) and bool(source_key.strip()),
                              'id_required', f'evidence.{eid}', 'Expected display_key or evidence.id'):
                continue
            self.check(source_key not in self.sources, 'duplicate_id', 'sources', source_key)
            self.sources[source_key] = source
        self.opinions = self.index(doc.get('opinions'), 'opinions')
        for oid, row in self.opinions.items():
            source = self.evidence.get(row.get('evidence_id'))
            self.check(source is not None, 'unknown_evidence', oid, 'Unknown evidence_id')
            if source:
                self.check(row.get('source_key') == (source.get('display_key') or source['id']),
                           'source_join_mismatch', oid, 'evidence_id/source_key disagree')
            self.texts(row, ['product'], oid)
            self.check(row.get('evidence_role') in {'experience', 'supply', 'context'},
                       'invalid_role', oid, 'Invalid evidence_role')
            self.check(row.get('polarity') in {'positive', 'negative', 'neutral', 'mixed'},
                       'invalid_polarity', oid, 'Invalid polarity')
            self.original_text(row, 'quote', oid)

    def keyword(self, doc):
        label = 'keywords'
        meta = doc.get('meta', {})
        self.check(meta.get('schema_version') == 'keyword-coding-v1', 'unsupported_schema', label, 'Expected keyword-coding-v1')
        for name, hash_field, target in [
            ('source_opinions', 'source_opinions_sha256', self.root / 'opinions.json'),
            ('source_evidence', 'source_evidence_sha256', self.source_path),
        ]:
            p = self.local_path(meta.get(name), f'{label}.meta.{name}')
            self.check(p == target, 'source_file_mismatch', f'{label}.meta.{name}', 'Source differs from opinion snapshot')
            self.digest(p, meta.get(hash_field), f'{label}.meta.{hash_field}')
        reviews = self.index(doc.get('opinion_reviews'), 'keywords.opinion_reviews', 'opinion_id')
        terms = self.index(doc.get('terms'), 'keywords.terms')
        mentions = self.index(doc.get('mentions'), 'keywords.mentions')
        self.check(set(reviews) == set(self.opinions), 'opinion_coverage', label, 'Reviews must cover every opinion exactly once')
        seen_pairs, by_opinion, used_terms = set(), {}, set()
        for mid, row in mentions.items():
            oid, tid = row.get('opinion_id'), row.get('term_id')
            opinion, term = self.opinions.get(oid), terms.get(tid)
            self.check(opinion is not None, 'unknown_opinion', mid, str(oid))
            self.check(term is not None, 'unknown_term', mid, str(tid))
            pair = (oid, tid)
            self.check(pair not in seen_pairs, 'duplicate_opinion_term', mid, str(pair))
            seen_pairs.add(pair)
            by_opinion.setdefault(oid, set()).add(tid)
            used_terms.add(tid)
            if opinion:
                self.same_fields(row, opinion, ['evidence_id', 'source_key', 'product', 'evidence_role'], mid)
                if row.get('polarity') != opinion.get('polarity'):
                    self.check(row.get('source_polarity') == opinion.get('polarity') and
                               row.get('polarity_basis') == 'explicit_phrase_subset' and
                               isinstance(row.get('polarity_reason'), str) and bool(row['polarity_reason'].strip()),
                               'unexplained_polarity_change', mid,
                               'Phrase polarity differs: require source_polarity, explicit_phrase_subset basis and polarity_reason')
                elif 'source_polarity' in row:
                    self.same_fields({'polarity': row['source_polarity']}, opinion, ['polarity'], mid + '.source_polarity')
            if term:
                self.check(row.get('polarity') == term.get('polarity'), 'term_polarity_mismatch', mid,
                           'Mention and term polarities differ')
            self.texts(row, ['reason'], mid)
            self.original_text(row, 'surface', mid)
            if 'quote' in row:
                self.original_text(row, 'quote', mid)
        for oid, review in reviews.items():
            ids = self.refs(review, 'term_ids', terms, oid)
            self.texts(review, ['reason'], oid)
            self.check(set(ids) == by_opinion.get(oid, set()), 'review_mention_mismatch', oid,
                       'Reviewed term IDs differ from actual mentions')
            if oid in self.opinions:
                self.same_fields(review, self.opinions[oid], ['source_key', 'product', 'evidence_role', 'polarity'], oid, required=False)
        for tid, term in terms.items():
            self.texts(term, ['label', 'definition'], tid)
            self.check(term.get('polarity') in {'positive', 'negative', 'neutral', 'mixed'}, 'invalid_polarity', tid, 'Invalid term polarity')
            self.check(tid in used_terms, 'unused_term', tid, 'No evidence-backed mention for term')
        counts = {'opinion_coverage': len(reviews), 'total_opinions': len(self.opinions),
                  'coded_opinions': len(by_opinion), 'abstained_opinions': len(reviews) - len(by_opinion),
                  'terms': len(terms), 'mentions': len(mentions)}
        for key, value in counts.items():
            if key in meta.get('validation', {}):
                self.check(type(meta['validation'][key]) is int and meta['validation'][key] == value,
                           'declared_count_mismatch', f'keywords.meta.validation.{key}', f'Expected {value}')
        self.summary['keywords'] = counts

    def journey(self, doc):
        meta = doc.get('meta', {})
        self.check(meta.get('schema_version') == 'journey-map-v1', 'unsupported_schema', 'journey', 'Expected journey-map-v1')
        files = self.index(meta.get('source_files'), 'journey.meta.source_files', 'path')
        paths = set()
        for name, record in files.items():
            p = self.local_path(name, 'journey.meta.source_files')
            paths.add(p)
            self.digest(p, record.get('sha256'), f'journey.meta.source_files.{name}')
        self.check({self.root / 'opinions.json', self.source_path} <= paths, 'required_hash_missing',
                   'journey.meta.source_files', 'Require hashes for opinions and source evidence')
        stages = self.index(doc.get('stages'), 'journey.stages')
        assignments = self.index(doc.get('stage_assignment'), 'journey.stage_assignment', 'opinion_id')
        self.check(set(assignments) == set(self.opinions), 'opinion_coverage', 'journey.stage_assignment',
                   'Assignments must cover every opinion exactly once')
        for oid, row in assignments.items():
            ids = self.refs(row, 'stage_ids', stages, oid)
            status = row.get('status')
            self.check(status in {'mapped', 'unknown'}, 'invalid_assignment_status', oid, 'Expected mapped or unknown')
            self.check((status == 'mapped' and bool(ids)) or (status == 'unknown' and not ids),
                       'assignment_status_mismatch', oid, 'Mapped needs stages; unknown must have none')
            self.texts(row, ['rationale'], oid)
            if oid in self.opinions:
                self.same_fields(row, self.opinions[oid], ['source_key', 'evidence_role'], oid)
                self.same_fields(row, self.opinions[oid], ['product', 'polarity'], oid, required=False)

        def nested(node, path, allowed):
            if isinstance(node, list):
                for i, child in enumerate(node):
                    nested(child, f'{path}[{i}]', allowed)
            elif isinstance(node, dict):
                if 'evidence_opinion_ids' in node:
                    ids = self.refs(node, 'evidence_opinion_ids', self.opinions, path)
                    self.check(set(ids) <= allowed, 'stage_reference_mismatch', path,
                               'Referenced opinion is not assigned to this stage/branch')
                    if 'quote' in node and node.get('source_key'):
                        self.check(any(self.opinions[i].get('source_key') == node['source_key'] for i in ids),
                                   'quote_opinion_mismatch', path, 'Quote source not supported by referenced opinions')
                if 'quote' in node:
                    self.original_text(node, 'quote', path)
                for key, child in node.items():
                    nested(child, f'{path}.{key}', allowed)

        coverage = {}
        for sid, stage in stages.items():
            ids = self.refs(stage, 'evidence_opinion_ids', self.opinions, sid)
            expected = {oid for oid, a in assignments.items() if sid in a.get('stage_ids', []) and oid in self.opinions}
            self.check(set(ids) == expected, 'stage_assignment_mismatch', sid, 'Stage references differ from assignments')
            self.texts(stage, ['title', 'goal', 'emotion_note'], sid)
            for field in ['actions', 'concerns', 'touchpoints', 'frictions', 'workarounds']:
                self.evidence_records(stage.get(field), f'{sid}.{field}', expected)
            representative = stage.get('representative_quote')
            if not isinstance(representative, dict):
                self.error('representative_quote_required', sid, 'Expected an original quote object')
            else:
                self.original_text(representative, 'quote', sid + '.representative_quote')
                stage_keys = {self.opinions[i].get('source_key') for i in expected}
                self.check(representative.get('source_key') in stage_keys, 'quote_stage_mismatch',
                           sid + '.representative_quote', 'Quote source is not represented by a stage opinion')
            nested(stage, sid, expected)
            by_role = stage.get('evidence_by_role', {})
            for role in ['experience', 'context', 'supply']:
                actual = self.refs(by_role, role, self.opinions, sid + '.evidence_by_role')
                role_ids = {i for i in expected if self.opinions[i].get('evidence_role') == role}
                self.check(set(actual) == role_ids, 'role_partition_mismatch', sid + '.' + role, 'Incorrect role partition')
            emotions = stage.get('emotions')
            if self.check(isinstance(emotions, list), 'array_required', sid + '.emotions', 'Expected an array'):
                for n, emotion in enumerate(emotions):
                    p = f'{sid}.emotions[{n}]'
                    if not isinstance(emotion, dict):
                        self.error('object_required', p, 'Expected an object')
                        continue
                    self.check(emotion.get('basis') == 'explicit', 'emotion_not_explicit', p, 'Emotion must be explicit')
                    self.texts(emotion, ['label'], p)
                    self.original_text(emotion, 'quote', p)
                    eids = self.refs(emotion, 'evidence_opinion_ids', self.opinions, p)
                    self.check(bool(eids), 'evidence_refs_empty', p, 'Emotion requires an opinion reference')
            expids = {i for i in expected if self.opinions[i].get('evidence_role') == 'experience'}
            keys = {self.opinions[i]['source_key'] for i in expids}
            source_rows = [self.sources[k] for k in keys if k in self.sources]
            units = {(e.get('platform'), e.get('note_id'), e.get('unit_id') or e['id'])
                     if e.get('note_id') else (e.get('platform'), None, e['id']) for e in source_rows}
            works = {(e.get('platform'), e['note_id']) for e in source_rows if e.get('note_id')}
            work_ids = {e['note_id'] for e in source_rows if e.get('note_id')}
            coverage[sid] = len(units)
            metrics = stage.get('measurement')
            if not self.check(isinstance(metrics, list), 'array_required', sid + '.measurement', 'Expected an array'):
                continue
            for n, metric in enumerate(metrics):
                p = f'{sid}.measurement[{n}]'
                if not isinstance(metric, dict):
                    self.error('object_required', p, 'Expected an object')
                    continue
                self.texts(metric, ['name', 'definition', 'unit', 'limitations'], p)
                kind = metric.get('type')
                if kind == 'proposed_test':
                    self.check('value' in metric and metric['value'] is None, 'proposed_value_not_null', p,
                               'Untested metric must explicitly have value=null')
                elif kind == 'observed_proxy':
                    mids = self.refs(metric, 'evidence_opinion_ids', self.opinions, p)
                    self.check(set(mids) == expids, 'proxy_population_mismatch', p, 'Coverage must include all stage experience opinions')
                    mkeys = self.refs(metric, 'source_keys', self.sources, p)
                    self.check(set(mkeys) == keys, 'proxy_sources_mismatch', p, 'Incorrect deduplicated source keys')
                    self.check(type(metric.get('value')) is int and metric['value'] == len(units), 'proxy_count_mismatch', p,
                               f'Expected {len(units)} experience source units after platform+note_id+unit_id deduplication')
                    self.check(metric.get('unit') == '来源单元', 'unsupported_proxy_unit', p, 'v1 coverage uses 来源单元')
                    if 'distinct_parent_works' in metric:
                        self.check(type(metric['distinct_parent_works']) is int and metric['distinct_parent_works'] == len(works),
                                   'proxy_work_count_mismatch', p, f'Expected {len(works)} parent works')
                    if 'parent_work_ids' in metric:
                        vals = metric['parent_work_ids']
                        self.check(isinstance(vals, list) and all(isinstance(x, str) for x in vals) and
                                   len(vals) == len(set(vals)) and set(vals) == work_ids,
                                   'proxy_work_ids_mismatch', p, 'Incorrect parent work IDs')
                else:
                    self.error('unsupported_metric_type', p, 'Expected observed_proxy or proposed_test')
        for n, branch in enumerate(doc.get('branches', [])):
            if not isinstance(branch, dict):
                self.error('object_required', f'branches[{n}]', 'Expected an object')
                continue
            ids = self.refs(branch, 'stages', stages, f'branches[{n}]')
            allowed = {oid for oid, row in assignments.items() if set(row.get('stage_ids', [])) & set(ids)}
            self.evidence_records(branch.get('cases'), f'branches[{n}].cases', allowed)
            nested(branch, f'branches[{n}]', allowed)
        counts = {'total_opinions': len(self.opinions),
                  'mapped_opinions': sum(a.get('status') == 'mapped' for a in assignments.values()),
                  'unknown_opinions': sum(a.get('status') == 'unknown' for a in assignments.values()),
                  'unreviewed_opinions': len(set(self.opinions) - set(assignments))}
        for key, value in counts.items():
            if key in doc.get('assignment_audit', {}):
                self.check(type(doc['assignment_audit'][key]) is int and doc['assignment_audit'][key] == value,
                           'declared_count_mismatch', f'journey.assignment_audit.{key}', f'Expected {value}')
        self.summary['journey'] = dict(counts, stages=len(stages), experience_source_coverage=coverage)


def validate(run_dir, modules='auto'):
    v = Validator(run_dir)
    try:
        v.base()
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        v.error('malformed_base', 'opinions/source evidence', f'{type(exc).__name__}: {exc}')
    statuses = {}
    for name, filename in [('keywords', 'keyword-coding.json'), ('journey', 'journey-map.json')]:
        selected = modules in {'auto', 'all', name}
        path = v.root / filename
        if not selected:
            statuses[name] = 'not_requested'
        elif not path.exists():
            statuses[name] = 'missing'
            if modules == 'auto':
                v.warnings.append({'code': 'module_skipped', 'path': filename, 'message': 'Module not present; not validated'})
            else:
                v.error('required_module_missing', filename, 'Requested module is absent')
        else:
            before = len(v.errors)
            doc = v.read(path)
            try:
                (v.keyword if name == 'keywords' else v.journey)(doc)
            except (KeyError, TypeError, AttributeError, ValueError) as exc:
                v.error('malformed_module', filename, f'{type(exc).__name__}: {exc}')
            statuses[name] = 'passed' if len(v.errors) == before else 'failed'
    if not any(x in {'passed', 'failed'} for x in statuses.values()):
        v.error('no_modules_validated', str(v.root), 'No requested module was available')
    return {'validator': 'research-modules-v1', 'checked_at': datetime.now(timezone.utc).isoformat(),
            'run_dir': str(v.root), 'valid': not v.errors, 'modules': statuses,
            'errors': v.errors, 'warnings': v.warnings, 'summary': v.summary,
            'limits': ['Does not establish semantic accuracy of labels, grouping, emotion interpretation or stage assignment.',
                       'Does not prove source authenticity, representative sampling, task performance or medical effectiveness.',
                       'Explicit phrase-polarity exceptions are checked for disclosure, not automatically judged correct.',
                       'Run validate_opinions.py and validate_analysis.py separately for full admission and opinion-layer checks.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--modules', choices=['auto', 'all', 'keywords', 'journey'], default='auto')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = validate(args.run_dir, args.modules)
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    raise SystemExit(0 if result['valid'] else 1)


if __name__ == '__main__':
    main()
