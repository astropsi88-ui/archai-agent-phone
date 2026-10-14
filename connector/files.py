"""Optional bounded attachment transport to the SAME existing runtime.

The edge never stores originals or parses documents. Runtime ownership, storage,
parsing, retention and canonical message/file linkage must be implemented upstream.
"""
import base64
import hashlib
import re
import uuid
from contract import Fault

CHUNK = 1024 * 1024
LIMITS = {'text': 5*1024*1024, 'document': 25*1024*1024, 'media': 100*1024*1024}
FORMATS = {
    'txt': ('text/plain', 'text'), 'md': ('text/markdown', 'text'),
    'csv': ('text/csv', 'text'), 'json': ('application/json', 'text'),
    'pdf': ('application/pdf', 'document'),
    'docx': ('application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'document'),
    'png': ('image/png', 'media'), 'jpg': ('image/jpeg', 'media'),
    'jpeg': ('image/jpeg', 'media'), 'webp': ('image/webp', 'media'),
    'mp4': ('video/mp4', 'media'), 'mov': ('video/quicktime', 'media'),
    'webm': ('video/webm', 'media'),
}

def file_id(value):
    try:
        if str(uuid.UUID(value)) != value: raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise Fault(400, 'invalid_file_id') from None

def file_ids(values):
    if not isinstance(values, list) or len(values) > 3 or len(set(map(str, values))) != len(values):
        raise Fault(400, 'invalid_file_ids')
    return [file_id(v) for v in values]

def metadata(body):
    if set(body) != {'uploadId', 'name', 'type', 'bytes'}: raise Fault(400, 'invalid_file_metadata')
    file_id(body['uploadId'])
    name = body['name']
    if not isinstance(name, str) or not re.fullmatch(r'[\w ().-]{1,100}\.[a-zA-Z0-9]{1,5}', name):
        raise Fault(400, 'invalid_file_name')
    fmt = FORMATS.get(name.rsplit('.', 1)[1].lower())
    if not fmt or body['type'] != fmt[0]: raise Fault(415, 'unsupported_file_type')
    if type(body['bytes']) is not int or not 0 < body['bytes'] <= LIMITS[fmt[1]]:
        raise Fault(413, 'file_size')
    return dict(body)

def chunk(body):
    if set(body) != {'uploadId', 'offset', 'base64', 'sha256'}: raise Fault(400, 'invalid_chunk')
    file_id(body['uploadId'])
    if type(body['offset']) is not int or not 0 <= body['offset'] < LIMITS['media']:
        raise Fault(400, 'invalid_chunk_offset')
    encoded = body['base64']
    if not isinstance(encoded, str) or not 0 < len(encoded) <= ((CHUNK+2)//3)*4:
        raise Fault(413, 'chunk_size')
    try: raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError): raise Fault(400, 'invalid_chunk_encoding') from None
    if not 0 < len(raw) <= CHUNK or base64.b64encode(raw).decode() != encoded:
        raise Fault(400, 'invalid_chunk_encoding')
    if hashlib.sha256(raw).hexdigest() != body['sha256']: raise Fault(400, 'chunk_hash')
    return dict(body)

class Files:
    def __init__(self, adapter): self.adapter = adapter

    def supported(self): return self.adapter.describe().get('attachments') is True

    def call(self, operation, body):
        if not self.supported(): raise Fault(503, 'existing_runtime_attachments_not_configured')
        if operation == 'begin': payload = metadata(body)
        elif operation == 'chunk': payload = chunk(body)
        else:
            if set(body) != {'uploadId'}: raise Fault(400, 'invalid_file_request')
            payload = {'uploadId': file_id(body['uploadId'])}
        result = self.adapter.call('file_'+operation, self.adapter.payload(**payload))
        self.adapter.validate(result)
        if result.get('uploadId') != body['uploadId'] or result.get('status') not in ('uploading','ready'):
            raise Fault(502, 'invalid_runtime_file_receipt')
        if type(result.get('offset')) is not int or not 0 <= result['offset'] <= LIMITS['media']:
            raise Fault(502, 'invalid_runtime_file_receipt')
        public = {k: result[k] for k in ('uploadId','status','offset')}
        if result['status'] == 'ready':
            if result.get('fileId') != body['uploadId'] or not re.fullmatch('[0-9a-f]{64}', result.get('sha256','')):
                raise Fault(502, 'invalid_runtime_file_receipt')
            public.update(fileId=result['fileId'], sha256=result['sha256'])
        return public

    def validate_ready(self, ids):
        for value in file_ids(ids):
            if self.call('status', {'uploadId':value})['status'] != 'ready':
                raise Fault(409, 'file_not_ready')
