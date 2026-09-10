"""Collect same-article Methods and declared supplementary materials from PMC."""
import asyncio
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from backend.worker.pdf_fetcher import pmc_article_versions, fetch_pmc_asset, pmc_asset_url

SUPPORTED_SUPPLEMENTS = {'.pdf', '.txt', '.md', '.docx', '.xlsx', '.csv', '.tsv', '.zip'}


def _text(node):
    return re.sub(r'\s+', ' ', ''.join(node.itertext())).strip() if node is not None else ''


def _section_text(node):
    blocks = []
    for child in node:
        if child.tag == 'title':
            blocks.append('## ' + _text(child))
        elif child.tag == 'table':
            for row in child.iter('tr'):
                blocks.append('\t'.join(_text(cell) for cell in row if cell.tag in {'td', 'th'}))
        elif child.tag in {'p', 'list-item', 'disp-formula'}:
            blocks.append(_text(child))
        else:
            blocks.append(_section_text(child))
    return '\n\n'.join(block for block in blocks if block)


def parse_article_xml(content):
    root = ET.fromstring(content)
    for node in root.iter():
        node.tag = node.tag.rsplit('}', 1)[-1]
    parents = {child: parent for parent in root.iter() for child in parent}
    chosen = []
    for section in root.iter('sec'):
        title = re.sub(r'[^a-z]', '', _text(section.find('title')).lower())
        kind = section.get('sec-type', '').lower()
        if 'method' not in kind and title not in {
            'methods', 'materialsandmethods', 'materialsandmethod', 'materialsampmethods',
            'experimentalprocedures', 'experimentalmethods', 'starmethods', 'onlinemethods',
            'methoddetails', 'materials',
            'protocol', 'experimentalprotocol', 'procedure', 'procedures',
        } and not re.fullmatch(r'(materials(and)?methods?|methods)', title):
            continue
        parent = parents.get(section)
        while parent is not None and parent not in chosen:
            parent = parents.get(parent)
        if parent is None:
            chosen.append(section)
    cited = {rid for section in chosen for ref in section.iter('xref')
             if ref.get('ref-type') == 'bibr' for rid in ref.get('rid', '').split()}
    references = []
    for ref in root.iter('ref'):
        if ref.get('id') not in cited:
            continue
        identifiers = {node.get('pub-id-type'): _text(node) for node in ref.iter('pub-id')}
        references.append({'id': ref.get('id'), 'label': _text(ref.find('label')),
                           'citation': _text(ref), 'doi': identifiers.get('doi'), 'pmid': identifiers.get('pmid')})
    supplements = []
    for node in root.iter('supplementary-material'):
        caption = _text(node)
        for element in node.iter():
            for key, href in element.attrib.items():
                if key.rsplit('}', 1)[-1] == 'href':
                    supplements.append({'href': href, 'caption': caption})
    return {'methods': '\n\n'.join(_section_text(section) for section in chosen),
            'method_titles': [_text(section.find('title')) for section in chosen],
            'references': references, 'supplements': supplements}


async def collect_article_sources(pmid):
    """Return original bytes plus an explicit inventory; never substitute another paper."""
    async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
        for attempt in range(4):
            response = await client.get('https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/',
                                        params={'ids': str(pmid), 'idtype': 'pmid', 'format': 'json', 'tool': 'GEO_Screener'})
            if response.status_code not in {429, 502, 503, 504} or attempt == 3:
                break
            await asyncio.sleep(2 ** (attempt + 1))
        response.raise_for_status()
        record = next((r for r in response.json().get('records', []) if str(r.get('pmid')) == str(pmid)), None)
        if not record or not record.get('pmcid'):
            raise ValueError(f'PMID {pmid} 没有可用的 PMC 全文关联')
        versions = await pmc_article_versions(client, record['pmcid'], str(pmid))
        if not versions:
            raise ValueError(f'{record["pmcid"]} 没有可读取的公开全文版本')
        metadata = versions[0]
        xml_url = pmc_asset_url(metadata['xml_url'])
        xml = await fetch_pmc_asset(client, xml_url)
        parsed = parse_article_xml(xml)
        documents, inventory = [], []
        if parsed['methods'].strip():
            text = f'# {metadata.get("title", "Article")} — Methods\n\n'
            text += f'PMID: {pmid}\nPMCID: {record["pmcid"]}\nDOI: {metadata.get("doi", "")}\n'
            text += f'Source: {xml_url}\nThis is ordered Methods text from the same article XML. Text-section numbers are not PDF page numbers.\n\n'
            text += parsed['methods']
            if parsed['references']:
                text += '\n\n# References cited in Methods\n\n' + '\n\n'.join(
                    f'[{ref["id"]}; reference {ref["label"]}] {ref["citation"]}' for ref in parsed['references'])
            name = f'{record["pmcid"]}-Methods.md'
            documents.append({'name': name, 'kind': 'methods', 'reference': xml_url, 'content': text.encode('utf-8')})
            inventory.append({'name': name, 'kind': 'methods', 'url': xml_url, 'status': 'downloaded'})
        else:
            inventory.append({'name': 'Methods', 'kind': 'methods', 'status': 'not_identified',
                              'reason': '未定位到独立 Methods 章节，将检查原始全文'})
        media = {Path(unquote(urlparse(url).path)).name: url for url in metadata.get('media_urls', [])}
        seen = set()
        for supplement in parsed['supplements']:
            name = Path(unquote(urlparse(supplement['href']).path)).name
            if name in seen:
                continue
            seen.add(name)
            entry = {'name': name, 'kind': 'supplement', 'caption': supplement['caption']}
            inventory.append(entry)
            url = media.get(name)
            if not url:
                entry.update(status='unavailable', reason='正文声明了补充文件，但公开数据中没有对应附件')
                continue
            entry['url'] = pmc_asset_url(url)
            if Path(name).suffix.lower() not in SUPPORTED_SUPPLEMENTS:
                entry.update(status='unsupported', reason='非可搜索文本附件，需人工检查原文件')
                continue
            if re.search(r'peer review|reporting summary|mdar checklist', supplement['caption'], re.I):
                entry.update(status='not_protocol', reason='期刊审稿或报告清单，已登记来源')
                continue
            try:
                content = await fetch_pmc_asset(client, url)
                documents.append({'name': name, 'kind': 'supplement',
                                  'reference': f'{entry["url"]}\n{supplement["caption"]}', 'content': content})
                entry['status'] = 'downloaded'
            except (httpx.HTTPError, ValueError) as exc:
                entry.update(status='unavailable', reason=f'补充附件获取失败（{type(exc).__name__}）')
        return {'pmid': str(pmid), 'pmcid': record['pmcid'], 'doi': metadata.get('doi'),
                'documents': documents, 'inventory': inventory, 'references': parsed['references'],
                'method_titles': parsed['method_titles']}
