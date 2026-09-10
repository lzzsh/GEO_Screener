"""Versioned perturbation-extractor contract and evidence validation."""
import csv
import io
import re
from decimal import Decimal, InvalidOperation

SCHEMA_VERSION = 'perturbation-extractor-v2.1'
COLUMNS = ['GSE_id', 'GSM_id', 'Article_title', 'Start_cell_type', 'Final_cell_type',
           'Stage_name', 'Stage_order', 'Pert_name', 'Addition_context', 'Pert_type',
           'pubchem_cid', 'chembl_id', 'dose_value', 'dose_unit', 'time_pert_start',
           'time_pert_end', 'duration_pert', 'time_unit', 'time_collection', 'Culture_medium',
           'Culture_system', 'Batch_id', 'Collection_methods', 'Reference']
STAGES = {'differentiation', 'reprogramming', 'sample culture', 'external treatment',
          'endpoint processing', 'other', 'NA'}
TYPES = {'small_molecule', 'protein', 'growth_factor', 'recombinant_protein', 'cytokine',
         'hormone', 'CRISPR', 'siRNA', 'shRNA', 'matrix', 'basal_medium_component',
         'supplement_component', 'antibiotic', 'serum_or_serum_replacement', 'vitamin',
         'amino_acid', 'metabolite', 'lipid', 'inorganic_salt', 'carbohydrate', 'enzyme',
         'dissociation_reagent', 'other', 'NA'}


def _text(value):
    if value is None or str(value).strip().lower() in {'', 'na', 'n/a', 'null', 'none'}:
        return 'NA'
    if isinstance(value, (list, dict)):
        raise ValueError('Protocol 字段必须为文本或数值')
    return str(value).strip()


def _number(value):
    if value == 'NA':
        return None
    try:
        result = Decimal(value)
        return result if result.is_finite() else None
    except InvalidOperation:
        return None


def _time(value, unit):
    value = value.strip()
    prefix = re.match(r'^(D|H)\s*', value, re.I)
    if prefix:
        if (prefix[1].upper() == 'D' and unit != 'days') or (prefix[1].upper() == 'H' and unit != 'hours'):
            return None
        value = value[prefix.end():]
    return _number(value)


def validate_extraction(payload, documents, gse_id, gsm_ids):
    if not isinstance(payload, dict) or payload.get('outcome') not in {'extracted', 'no_protocol', 'needs_sources'}:
        raise ValueError('模型必须返回 outcome: extracted/no_protocol/needs_sources')
    rows = payload.get('events')
    if not isinstance(rows, list) or len(rows) > 2000:
        raise ValueError('events 必须为列表且不超过 2000 行')
    if payload['outcome'] == 'extracted' and not rows:
        raise ValueError('extracted 结果不能没有事件')
    if payload['outcome'] == 'no_protocol' and rows:
        raise ValueError('no_protocol 结果不能包含事件')
    requests = payload.get('reference_requests', [])
    if not isinstance(requests, list) or any(not isinstance(r, str) for r in requests):
        raise ValueError('reference_requests 必须为文本列表')
    events, blockers, warnings = [], [], []
    if payload['outcome'] == 'needs_sources' or requests:
        blockers.append('引用配方或补充材料尚未补齐，请添加来源后重新提取')
    seen = set()
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get('values'), dict):
            raise ValueError(f'第 {index} 行缺少 values 对象')
        values = {key: _text(row['values'].get(key)) for key in COLUMNS}
        type_alias = values['Pert_type'].replace(' ', '_')
        if type_alias in TYPES:
            values['Pert_type'] = type_alias
        prefix = f'第 {index} 行：'
        if values['GSE_id'] not in {'NA', gse_id}:
            blockers.append(prefix + 'GSE 与来源不一致')
        values['GSE_id'] = gse_id
        if values['GSM_id'] != 'NA' and values['GSM_id'] not in gsm_ids:
            blockers.append(prefix + f"GSM {values['GSM_id']} 不属于所选来源")
        if values['GSM_id'] == 'NA':
            warnings.append(prefix + '尚未映射到 GSM；保留为文献级 protocol')
        for key, allowed in [('Stage_name', STAGES), ('Pert_type', TYPES),
                             ('Addition_context', {'perturbation', 'basal medium', 'NA'}),
                             ('time_unit', {'days', 'hours', 'NA'})]:
            if values[key] not in allowed:
                blockers.append(prefix + f'{key} 的取值不合法')
        if values['Addition_context'] == 'basal medium':
            if values['Pert_name'] != 'NA':
                blockers.append(prefix + '纯培养基行的 Pert_name 应为 NA')
        elif values['Pert_name'] == 'NA':
            warnings.append(prefix + '扰动名称缺失')
        if values['Stage_order'] != 'NA' and (not values['Stage_order'].isdigit() or int(values['Stage_order']) < 1):
            blockers.append(prefix + 'Stage_order 应为正整数或 NA')
        for field in ['dose_value', 'duration_pert']:
            number = _number(values[field])
            if values[field] != 'NA' and (number is None or number < 0):
                blockers.append(prefix + f'{field} 应为非负数或 NA')
        times = [_time(values[key], values['time_unit']) for key in ['time_pert_start', 'time_pert_end', 'time_collection']]
        for key, number in zip(['time_pert_start', 'time_pert_end', 'time_collection'], times):
            if values[key] != 'NA' and (number is None or number < 0):
                blockers.append(prefix + f'{key} 无法按 time_unit 解释，或位于 Day 0 之前')
        start, end, collection = times
        duration = _number(values['duration_pert'])
        if start is not None and end is not None:
            if end < start:
                blockers.append(prefix + '结束时间早于开始时间')
            if duration is not None and duration != end - start:
                blockers.append(prefix + '持续时间与开始/结束时间不一致')
        if collection is not None and end is not None and end > collection:
            blockers.append(prefix + '结束时间超过该 GSM 采样时间')
        for key in ['dose_value', 'dose_unit', 'time_pert_start', 'time_pert_end', 'Culture_medium']:
            if values[key] == 'NA':
                warnings.append(prefix + f'{key} 缺失')
        evidence = row.get('evidence', [])
        if not isinstance(evidence, list):
            raise ValueError(prefix + 'evidence 必须为列表')
        checked_evidence = []
        for ev in evidence:
            if not isinstance(ev, dict):
                raise ValueError(prefix + '证据格式不正确')
            doc_id, page = ev.get('document_id'), ev.get('page')
            doc = documents.get(doc_id)
            quote = str(ev.get('quote') or '').strip()
            page_text = next((p['text'] for p in doc['pages'] if p['page'] == page), '') if doc else ''
            compact = lambda s: re.sub(r'\s+', '', s)
            valid = bool(quote and len(compact(quote)) >= 8 and compact(quote) in compact(page_text))
            if not valid:
                blockers.append(prefix + '证据页码或原文片段无法核实')
            checked_evidence.append({'document_id': doc_id, 'page': page, 'quote': quote, 'verified': valid})
        if not evidence:
            blockers.append(prefix + '缺少原文证据')
        protocol_name = _text(row.get('protocol_name'))
        signature = (protocol_name, *(values[key] for key in COLUMNS))
        if signature in seen:
            blockers.append(prefix + '与前面的事件重复')
        seen.add(signature)
        events.append({'protocol_name': protocol_name, 'values': values, 'evidence': checked_evidence})
    return {'outcome': payload['outcome'], 'summary': str(payload.get('summary') or ''),
            'events': events, 'reference_requests': requests,
            'blockers': list(dict.fromkeys(blockers)), 'warnings': list(dict.fromkeys(warnings)),
            'schema_version': SCHEMA_VERSION}


def to_tsv(events):
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
    writer.writerow(COLUMNS)
    for event in events:
        writer.writerow([event['values'].get(key, 'NA') for key in COLUMNS])
    return stream.getvalue()
