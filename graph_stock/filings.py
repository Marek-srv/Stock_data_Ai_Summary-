"""Bounded public filing acquisition. No reasoning/model calls in this module."""
import csv
import hashlib
import io
import json
import re
import ssl
import certifi
import uuid
from dataclasses import dataclass
from datetime import date
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler
from urllib.parse import urlparse

from pypdf import PdfReader
from .store import now
from .vault import NoteConflict, Vault

MAX_BYTES = 25_000_000
DIRECTORIES = (
    'https://archives.nseindia.com/content/equities/EQUITY_L.csv',
    'https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv',
)
# A measured, historical coverage sample, deliberately not a latest-report claim.
REPORTS = {'BEL': {
    'title': 'BEL Integrated Annual Report 2024–25',
    'document_date': '2025-08-05',
    'nse_public_available_at': '2025-08-05T20:38:33+05:30',
    'urls': (
        'https://archives.nseindia.com/corporate/BEL_05082025203833_Letter_Signed_IAR_Notice.pdf',
        'https://bel-india.in/wp-content/uploads/2025/08/Integrated-Annual-Report-2024-25.pdf',
    ),
}}
ALLOWED_HOSTS = {'archives.nseindia.com', 'nsearchives.nseindia.com', 'bel-india.in'}


class FilingError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.port not in (None, 443):
        raise FilingError('invalid', 'Provider returned an unsupported location.')


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


@dataclass
class Download:
    content: bytes
    url: str
    retrieved_at: str


def download(url):
    validate_url(url)
    try:
        request = Request(url, headers={'User-Agent': 'graph_stock/0.3 public-research', 'Accept-Encoding': 'identity'})
        with build_opener(SafeRedirect(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where()))).open(request, timeout=12) as response:
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise FilingError('invalid', 'Source exceeds the 25 MB limit.')
            return Download(data, response.url, now())
    except HTTPError as error:
        raise FilingError('throttled' if error.code == 429 else 'unavailable',
                          'Provider throttled the request.' if error.code == 429 else 'Provider did not supply the source.') from None
    except (URLError, TimeoutError, OSError):
        raise FilingError('unavailable', 'Provider unavailable; retry or import a PDF.') from None


def parse_directory(data):
    try:
        rows = csv.DictReader(io.StringIO(data.decode('utf-8-sig')))
        if not rows.fieldnames or not {'SYMBOL', 'NAME OF COMPANY', 'ISIN NUMBER'} <= {k.strip() for k in rows.fieldnames}:
            raise ValueError()
        result = {}
        for raw in rows:
            row = {k.strip(): (v or '').strip() for k, v in raw.items() if k}
            symbol, isin = row['SYMBOL'], row['ISIN NUMBER']
            if not re.fullmatch(r'[A-Z0-9&_-]{1,30}', symbol) or not re.fullmatch(r'IN[A-Z0-9]{10}', isin) or not row['NAME OF COMPANY']:
                raise ValueError()
            result[symbol] = {'symbol': symbol, 'name': row['NAME OF COMPANY'], 'isin': isin, 'exchange': 'NSE'}
        if not result:
            raise ValueError()
        return result
    except (ValueError, KeyError, UnicodeError, csv.Error):
        raise FilingError('invalid', 'Security directory failed validation.') from None


def validate_pdf(data):
    if not data or len(data) > MAX_BYTES or not data.startswith(b'%PDF-'):
        raise FilingError('invalid', 'Import a valid PDF no larger than 25 MB.')
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 2000:
            raise ValueError()
        return len(reader.pages)
    except Exception:
        raise FilingError('invalid', 'PDF is malformed, encrypted or exceeds 2,000 pages.') from None


class FilingService:
    def __init__(self, store, vault_dir, fetch=download):
        self.store, self.vault, self.fetch = store, Vault(vault_dir), fetch
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS filing_jobs (
                    id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL,
                    fingerprint TEXT NOT NULL, request TEXT NOT NULL, payload BLOB,
                    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    result TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS filing_sources (
                    id TEXT PRIMARY KEY, symbol TEXT NOT NULL, hash TEXT NOT NULL,
                    metadata TEXT NOT NULL, content BLOB NOT NULL,
                    UNIQUE(symbol,hash)
                );
                CREATE TABLE IF NOT EXISTS filing_directory (
                    id INTEGER PRIMARY KEY CHECK(id=1), content BLOB NOT NULL,
                    url TEXT NOT NULL, retrieved_at TEXT NOT NULL
                );
            ''')
            db.execute("UPDATE filing_jobs SET status='queued' WHERE status='running'")

    def submit(self, symbol, key, *, content=None, filename=None, name=None, available_date=None):
        symbol = symbol.strip().upper()
        if not re.fullmatch(r'[A-Z0-9&_-]{1,30}', symbol):
            raise FilingError('invalid', 'Enter an exact NSE ticker.')
        if content is not None:
            validate_pdf(content)
            if not filename or not re.fullmatch(r'[^/\\\r\n]{1,120}\.pdf', filename, re.I):
                raise FilingError('invalid', 'Use a PDF filename without directory components.')
        if available_date:
            try:
                if date.fromisoformat(available_date) > date.today():
                    raise FilingError('invalid', 'Public availability cannot be in the future.')
            except ValueError:
                raise FilingError('invalid', 'Public availability must be a valid ISO date.') from None
        request = {'symbol': symbol, 'kind': 'manual' if content is not None else 'automatic',
                   'filename': filename, 'name': name, 'available_date': available_date,
                   'vault_root': str(self.vault.root)}
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode() + (content or b'')).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT id,fingerprint FROM filing_jobs WHERE request_key=?', (key,)).fetchone()
            if old:
                if old['fingerprint'] != fingerprint:
                    raise FilingError('conflict', 'This request key belongs to different inputs.')
                return old['id'], False
            if db.execute("SELECT COUNT(*) FROM filing_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 8:
                raise FilingError('queue-full', 'Filing queue is full. Try again shortly.')
            run_id, timestamp = str(uuid.uuid4()), now()
            db.execute('INSERT INTO filing_jobs VALUES (?,?,?,?,?,\'queued\',?,?,\'{}\')',
                       (run_id, key, fingerprint, json.dumps(request), content, timestamp, timestamp))
        return run_id, True

    def pending(self):
        with self.store.connect() as db:
            return [r[0] for r in db.execute("SELECT id FROM filing_jobs WHERE status='queued'")]

    def retry(self, run_id):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM filing_jobs WHERE id=?', (run_id,)).fetchone()
            if not row:
                raise KeyError(run_id)
            if row[0] in ('queued', 'running', 'success', 'unchanged'):
                return False
            if db.execute("SELECT COUNT(*) FROM filing_jobs WHERE status IN ('queued','running')").fetchone()[0] >= 8:
                raise FilingError('queue-full', 'Filing queue is full.')
            db.execute("UPDATE filing_jobs SET status='queued',updated_at=? WHERE id=?", (now(), run_id))
            return True

    def identity(self, symbol, attempts):
        # A current-day cache conserves provider requests. Never silently accept stale identity.
        with self.store.connect() as db:
            cached = db.execute('SELECT * FROM filing_directory WHERE id=1').fetchone()
        if cached and cached['retrieved_at'][:10] == now()[:10]:
            data, url, timestamp = cached['content'], cached['url'], cached['retrieved_at']
        else:
            for url in DIRECTORIES:
                try:
                    response = self.fetch(url)
                    parse_directory(response.content)
                    data, url, timestamp = response.content, response.url, response.retrieved_at
                    with self.store.connect() as db:
                        db.execute('INSERT OR REPLACE INTO filing_directory VALUES (1,?,?,?)', (data, url, timestamp))
                    break
                except FilingError as error:
                    attempts.append({'url': url, 'status': error.status})
            else:
                raise FilingError('unavailable', 'NSE identity lookup unavailable. Manual import may retain an explicitly unverified identity.')
        security = parse_directory(data).get(symbol)
        if not security:
            raise FilingError('invalid', 'Ticker is not in the retrieved NSE equity directory.')
        return {**security, 'verification': 'NSE directory', 'source_url': url,
                'retrieved_at': timestamp, 'directory_sha256': hashlib.sha256(data).hexdigest()}

    def execute(self, run_id):
        with self.store.connect() as db:
            changed = db.execute("UPDATE filing_jobs SET status='running',updated_at=? WHERE id=? AND status='queued'", (now(), run_id)).rowcount
            row = db.execute('SELECT * FROM filing_jobs WHERE id=?', (run_id,)).fetchone()
        if not changed:
            return
        request = json.loads(row['request'])
        result = json.loads(row['result'])
        attempts = list(result.get('attempts', [])) if result else []
        result = result or {'message': ''}
        result['attempts'] = attempts
        result['missing'] = []
        status = 'unavailable'
        try:
            if request['vault_root'] != str(self.vault.root):
                raise FilingError('partial', 'Restore the original vault configuration before retrying.')
            previous = json.loads(row['result'])
            if previous.get('source_id'):
                metadata, data = self.source(previous['source_id'])
                self.publish_source(metadata, data)
                recovered_status = 'partial' if metadata['security']['verification'].startswith('user assertion') else 'unchanged'
                previous['message'] = 'Saved source publication verified. Identity and extraction gaps remain as recorded.'
                with self.store.connect() as db:
                    db.execute('UPDATE filing_jobs SET status=?,updated_at=?,result=? WHERE id=?',
                               (recovered_status, now(), json.dumps(previous), run_id))
                return
            try:
                security = self.identity(request['symbol'], attempts)
            except FilingError as error:
                if request['kind'] != 'manual' or error.status == 'invalid':
                    raise
                security = {'symbol': request['symbol'], 'name': request['name'] or request['symbol'],
                            'exchange': 'NSE', 'isin': None, 'verification': 'user assertion; unverified'}
                result['missing'].append('Official identity verification unavailable')
            result['security'] = security
            if request['kind'] == 'manual':
                data, origin, retrieved = row['payload'], 'manual:' + request['filename'], row['created_at']
                title, document_date = request['filename'], None
                public_available_at = request['available_date']
                availability_basis = (
                    'user-supplied date, unverified'
                    if request['available_date']
                    else 'unknown; first observation only'
                )
                pages = validate_pdf(data)
            else:
                report = REPORTS.get(request['symbol'])
                if not report:
                    raise FilingError('partial', 'Identity resolved. Automatic coverage currently includes BEL FY2024–25 only; import this company’s filing.')
                for url in report['urls']:
                    try:
                        response = self.fetch(url)
                        pages = validate_pdf(response.content)
                        data, origin, retrieved = response.content, response.url, response.retrieved_at
                        attempts.append({'url': url, 'status': 'success'})
                        break
                    except FilingError as error:
                        attempts.append({'url': url, 'status': error.status})
                else:
                    raise FilingError(attempts[-1]['status'], 'Filing not acquired. Retry or import a public PDF.')
                title = report['title']
                document_date = report['document_date'] if origin == report['urls'][0] else None
                public_available_at = (
                    report['nse_public_available_at']
                    if origin == report['urls'][0]
                    else None
                )
                availability_basis = (
                    'timestamp encoded in the NSE archive path'
                    if public_available_at
                    else 'unknown; first observation only'
                )
            content_hash = hashlib.sha256(data).hexdigest()
            source_id = hashlib.sha256((request['symbol'] + ':' + content_hash).encode()).hexdigest()
            # Retrieval establishes first observation, not the original public release timestamp.
            metadata = {'id': source_id, 'symbol': request['symbol'], 'title': title, 'sha256': content_hash,
                        'origin': origin, 'retrieved_at': retrieved, 'document_date': document_date,
                        'public_available_at': public_available_at,
                        'availability_basis': availability_basis,
                        'historical_feature_eligible': False,
                        'parser_status': 'PDF validated; financial extraction is a separate versioned run',
                        'parser_version': 'pdf-validation/v1', 'pages': pages, 'security': security,
                        'pdf_path': f'Graph Stock/Sources/{request["symbol"]}/{source_id}.pdf',
                        'note_path': f'Graph Stock/Sources/{request["symbol"]}/{source_id}.md'}
            with self.store.connect() as db:
                created = db.execute('INSERT OR IGNORE INTO filing_sources VALUES (?,?,?,?,?)',
                                     (source_id, request['symbol'], content_hash, json.dumps(metadata), data)).rowcount
                saved = db.execute('SELECT metadata FROM filing_sources WHERE id=?', (source_id,)).fetchone()
            metadata = json.loads(saved[0])
            result.update(source_id=source_id, acquisition={'origin': origin, 'retrieved_at': retrieved},
                          message='Filing saved. Start a separate local financial extraction from this source.')
            result['missing'].append('Financial extraction is a separate explicit action')
            if availability_basis == 'timestamp encoded in the NSE archive path':
                result['missing'].append('Historical feature eligibility remains deferred until point-in-time features are built')
            else:
                result['missing'].append('Public availability not independently verified; excluded from historical features')
            self.publish_source(metadata, data)
            status = 'partial' if security['verification'].startswith('user assertion') else 'success' if created else 'unchanged'
        except FilingError as error:
            status, result['message'] = error.status, error.message
        except NoteConflict:
            status, result['message'] = 'partial', 'An existing source artifact differs and was preserved. Move it aside before retrying.'
        except (OSError, ValueError, UnicodeError):
            status, result['message'] = 'partial', 'Source publication incomplete. Check the vault and retry; existing files are preserved.'
        except Exception:
            status, result['message'] = 'unavailable', 'Acquisition interrupted by an unexpected provider or parser failure. Retry or import a PDF.'
        with self.store.connect() as db:
            db.execute('UPDATE filing_jobs SET status=?,updated_at=?,result=? WHERE id=?',
                       (status, now(), json.dumps(result), run_id))

    def publish_source(self, metadata, data):
        self.vault.publish_bytes(metadata['pdf_path'], data)
        note = '# ' + metadata['symbol'] + ' — source evidence\n\n'
        note += (
            'Source document only; not a financial assessment.\n\n```json\n'
            + json.dumps(metadata, indent=2)
            + '\n```\n\n'
        )
        note += (
            f'PDF attachment: [[{metadata["id"]}.pdf]]\n\n'
            'Missing: financial extraction, verified public availability.\n'
        )
        self.vault.publish(metadata['note_path'], note)

    def get(self, run_id):
        with self.store.connect() as db:
            row = db.execute('SELECT id,status,created_at,updated_at,request,result FROM filing_jobs WHERE id=?', (run_id,)).fetchone()
        if not row:
            raise KeyError(run_id)
        result = dict(row)
        result['request'] = json.loads(result['request'])
        result['request'].pop('vault_root')
        result['result'] = json.loads(result['result'])
        if result['result'].get('source_id'):
            result['source'] = self.source(result['result']['source_id'])[0]
        return result

    def recent(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute('SELECT id FROM filing_jobs ORDER BY created_at DESC LIMIT 30')]
        return [self.get(i) for i in ids]

    def source(self, source_id):
        with self.store.connect() as db:
            row = db.execute('SELECT metadata,content FROM filing_sources WHERE id=?', (source_id,)).fetchone()
        if not row:
            raise KeyError(source_id)
        return json.loads(row[0]), row[1]
