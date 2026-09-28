import io
import uuid

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from graph_stock.app import create_app
from graph_stock.filings import Download, FilingError, FilingService, REPORTS, parse_directory, validate_pdf, validate_url
from graph_stock.store import Store

DIRECTORY = b'SYMBOL,NAME OF COMPANY, ISIN NUMBER\nBEL,Bharat Electronics Limited,INE263A01024\nHAL,Hindustan Aeronautics Limited,INE066F01020\n'


def pdf(marker=None):
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if marker:
        writer.add_metadata({'/Subject': marker})
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


class Provider:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail
        self.document = pdf()

    def __call__(self, url):
        self.calls.append(url)
        if self.fail:
            raise FilingError('unavailable', 'offline')
        return Download(DIRECTORY if url.endswith('.csv') else self.document, url, '2026-09-06T00:00:00+00:00')


def service(tmp_path, provider=None):
    return FilingService(Store(tmp_path / 'state.sqlite3'), tmp_path / 'vault', provider or Provider())


def test_acquisition_provenance_deduplication_and_restart(tmp_path):
    svc = service(tmp_path)
    key = str(uuid.uuid4())
    run_id, _ = svc.submit('BEL', key)
    assert svc.submit('BEL', key) == (run_id, False)
    svc.execute(run_id)
    run = svc.get(run_id)
    assert run['status'] == 'success'
    meta = run['source']
    assert meta['security']['isin'] == 'INE263A01024'
    assert meta['public_available_at'] == REPORTS['BEL']['nse_public_available_at']
    assert meta['availability_basis'] == 'timestamp encoded in the NSE archive path'
    assert meta['historical_feature_eligible'] is False
    assert (svc.vault.root / meta['pdf_path']).read_bytes() == svc.source(meta['id'])[1]
    assert meta['sha256'] in svc.vault.read(meta['note_path'])
    second, _ = svc.submit('BEL', str(uuid.uuid4()))
    svc.execute(second)
    assert svc.get(second)['status'] == 'unchanged'
    assert svc.get(second)['source'] == meta
    assert service(tmp_path).get(run_id) == run
    with svc.store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM filing_sources').fetchone()[0] == 1
    with pytest.raises(FilingError, match='different inputs'):
        svc.submit('HAL', key)


def test_fallback_invalid_provider_and_manual_same_pipeline(tmp_path):
    provider = Provider()
    def fetch(url):
        if url == REPORTS['BEL']['urls'][0]:
            raise FilingError('throttled', 'try fallback')
        return provider(url)
    svc = service(tmp_path, fetch)
    run_id, _ = svc.submit('BEL', str(uuid.uuid4()))
    svc.execute(run_id)
    run = svc.get(run_id)
    assert run['status'] == 'success'
    assert run['result']['attempts'][0]['status'] == 'throttled'
    manual, _ = svc.submit('BEL', str(uuid.uuid4()), content=provider.document, filename='report.pdf')
    svc.execute(manual)
    assert svc.get(manual)['status'] == 'unchanged'
    assert svc.get(manual)['result']['acquisition']['origin'] == 'manual:report.pdf'
    assert svc.get(manual)['source']['id'] == run['source']['id']

    dated, _ = svc.submit(
        'BEL', str(uuid.uuid4()), content=pdf('dated'), filename='dated.pdf',
        available_date='2025-08-05',
    )
    svc.execute(dated)
    assert svc.get(dated)['source']['public_available_at'] == '2025-08-05'
    assert svc.get(dated)['source']['availability_basis'] == 'user-supplied date, unverified'


def test_offline_manual_identity_and_unknown_ticker(tmp_path):
    svc = service(tmp_path, Provider(fail=True))
    run_id, _ = svc.submit('BEL', str(uuid.uuid4()), content=pdf(), filename='report.pdf', name='Bharat Electronics')
    svc.execute(run_id)
    run = svc.get(run_id)
    assert run['status'] == 'partial'
    assert run['source']['security']['isin'] is None
    assert 'unverified' in run['source']['security']['verification']
    svc.fetch = Provider()
    unknown, _ = svc.submit('UNKNOWN', str(uuid.uuid4()))
    svc.execute(unknown)
    assert svc.get(unknown)['status'] == 'invalid'
    unsupported, _ = svc.submit('HAL', str(uuid.uuid4()))
    svc.execute(unsupported)
    assert svc.get(unsupported)['status'] == 'partial'
    assert 'source' not in svc.get(unsupported)

    unavailable = service(tmp_path / 'offline-automatic', Provider(fail=True))
    failed, _ = unavailable.submit('BEL', str(uuid.uuid4()))
    unavailable.execute(failed)
    assert unavailable.get(failed)['status'] == 'unavailable'
    unavailable.fetch = Provider()
    assert unavailable.retry(failed)
    unavailable.execute(failed)
    recovered = unavailable.get(failed)
    assert recovered['status'] == 'success'
    assert [attempt['status'] for attempt in recovered['result']['attempts']] == [
        'unavailable', 'unavailable', 'success',
    ]


def test_pending_and_failed_publication_preserve_source(tmp_path, monkeypatch):
    svc = service(tmp_path)
    run_id, _ = svc.submit('BEL', str(uuid.uuid4()))
    def fail(*args):
        raise PermissionError('unwritable')
    monkeypatch.setattr(svc.vault, 'publish_bytes', fail)
    svc.execute(run_id)
    assert svc.get(run_id)['status'] == 'partial'
    source_id = svc.get(run_id)['source']['id']
    restarted = service(tmp_path)
    assert restarted.retry(run_id)
    restarted.execute(run_id)
    assert restarted.get(run_id)['status'] == 'unchanged'
    assert restarted.get(run_id)['source']['id'] == source_id
    queued, _ = restarted.submit('BEL', str(uuid.uuid4()))
    with restarted.store.connect() as db:
        db.execute("UPDATE filing_jobs SET status='running' WHERE id=?", (queued,))
    assert queued in service(tmp_path).pending()


@pytest.mark.parametrize('data', [b'<html>blocked</html>', b'%PDF-1.7\nbroken', b''])
def test_reject_malformed_documents(data):
    with pytest.raises(FilingError):
        validate_pdf(data)


def test_invalid_directory_and_unsafe_provider_locations():
    with pytest.raises(FilingError):
        parse_directory(b'<html>not CSV</html>')
    for url in ['http://archives.nseindia.com/x', 'https://127.0.0.1/x', 'https://bel-india.in.evil.test/x']:
        with pytest.raises(FilingError):
            validate_url(url)


def test_api_import_guard_and_persisted_retrieval(tmp_path):
    import time
    headers = {'X-Graph-Stock': 'local-research'}
    with TestClient(create_app(tmp_path, filing_fetch=Provider()), base_url='http://localhost') as client:
        automatic = client.post(
            '/api/v1/filings', headers=headers,
            json={'symbol': 'BEL', 'request_key': str(uuid.uuid4())},
        )
        assert automatic.status_code == 202
        automatic_id = automatic.json()['id']
        for _ in range(100):
            automatic_run = client.get('/api/v1/filings/' + automatic_id).json()
            if automatic_run['status'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert automatic_run['status'] == 'success'
        assert automatic_run['source']['security']['isin'] == 'INE263A01024'

        params = {'symbol': 'BEL', 'request_key': str(uuid.uuid4()), 'filename': 'report.pdf'}
        assert client.post('/api/v1/filings/import', params=params, content=pdf()).status_code == 403
        assert client.post('/api/v1/filings/import', params=params, content=b'bad', headers=headers).status_code == 422
        response = client.post('/api/v1/filings/import', params=params, content=pdf('manual-api'), headers=headers)
        assert response.status_code == 202
        run_id = response.json()['id']
        for _ in range(100):
            run = client.get('/api/v1/filings/' + run_id).json()
            if run['status'] not in ('queued', 'running'):
                break
            time.sleep(.01)
        assert run['status'] == 'success'
        source = run['source']['id']
        download = client.get('/api/v1/filings/sources/' + source + '/pdf')
        assert download.content.startswith(b'%PDF')
        assert 'attachment;' in download.headers['content-disposition']
        assert client.get('/api/v1/filings/sources/' + source + '/note').status_code == 200
        assert client.get('/api/v1/filings').json()[0]['id'] == run_id
