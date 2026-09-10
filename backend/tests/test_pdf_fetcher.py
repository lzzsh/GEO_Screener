import hashlib

import httpx
import pytest

from backend.worker.pdf_fetcher import PMC_CLOUD, _fetch_pmc_cloud_pdf


@pytest.mark.asyncio
@pytest.mark.parametrize('boolean_flags', [False, True])
@pytest.mark.parametrize('case', ['published', 'wrong_pmid', 'wrong_host', 'bad_checksum', 'html'])
async def test_pmc_cloud_pdf_identity_and_integrity(tmp_path, case, boolean_flags):
    """Use the linked published article; never accept another PMID or an HTML challenge."""
    pdf = b'%PDF-1.7\nverified-test-content'
    checksum = hashlib.md5(pdf).hexdigest()
    requests = []

    def handle(request):
        requests.append(str(request.url))
        if request.url.path == '/':
            assert request.url.params['prefix'] == 'metadata/PMC123.'
            return httpx.Response(200, text='''<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
                <Contents><Key>metadata/PMC123.1.json</Key></Contents>
                <Contents><Key>metadata/PMC123.2.json</Key></Contents>
                <Contents><Key>metadata/PMC1234.1.json</Key></Contents>
            </ListBucketResult>''')
        if request.url.path.endswith('.json'):
            manuscript = request.url.path.endswith('.1.json')
            digest = '0' * 32 if case == 'bad_checksum' else checksum
            host = 'https://unrelated.example' if case == 'wrong_host' else PMC_CLOUD
            return httpx.Response(200, json={
                'pmid': '999' if case == 'wrong_pmid' else '456',
                'is_manuscript': manuscript if boolean_flags else ('yes' if manuscript else 'no'),
                'pdf_url': f'{host}/{"manuscript" if manuscript else "published"}.pdf?md5={digest}',
            })
        return httpx.Response(200, content=b'<html>verification required</html>' if case == 'html' else pdf)

    destination = tmp_path / 'article.pdf'
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await _fetch_pmc_cloud_pdf(client, 'PMC123', '456', destination)
    assert result is (case == 'published')
    assert not any('PMC1234' in url for url in requests)
    assert not any('unrelated.example' in url for url in requests)
    if result:
        assert destination.read_bytes() == pdf
        assert '/published.pdf?' in requests[-1]
        assert not any('/manuscript.pdf?' in url for url in requests)
    else:
        assert not destination.exists()
