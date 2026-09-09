import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import voice


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(voice.config, 'STT_URL', 'http://localhost:9000/v1/audio/transcriptions')
    monkeypatch.setattr(voice.config, 'STT_API_KEY', 'test-secret')
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app)


def upstream(monkeypatch, response=None, error=None):
    class Stub:
        def __init__(self, **kwargs):
            assert kwargs['follow_redirects'] is False
            assert kwargs['timeout'] == 60
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, **kwargs):
            assert kwargs['data']['language'] == 'ja'
            assert kwargs['headers']['Authorization'] == 'Bearer test-secret'
            assert kwargs['files']['file'][1] == b'audio'
            if error:
                raise error
            return response
    monkeypatch.setattr(voice.httpx, 'AsyncClient', Stub)


def test_status_hides_credentials_and_rejects_unsafe_config(client, monkeypatch):
    assert client.get('/api/stt/status').json()['configured'] is True
    assert 'test-secret' not in client.get('/api/stt/status').text
    for url in ['', 'http://remote.test/stt', 'https://user:secret@example.com/stt']:
        monkeypatch.setattr(voice.config, 'STT_URL', url)
        assert client.get('/api/stt/status').json()['configured'] is False
        assert client.post('/api/stt', content=b'audio').status_code == 503


@pytest.mark.parametrize('media', ['audio/mp4', 'audio/webm;codecs=opus', 'audio/ogg'])
def test_transcription(client, monkeypatch, media):
    upstream(monkeypatch, httpx.Response(200, json={'text': ' こんにちは '}))
    response = client.post('/api/stt', content=b'audio', headers={'Content-Type': media})
    assert response.json() == {'text': 'こんにちは'}
    assert response.headers['cache-control'] == 'no-store'


def test_input_limits(client, monkeypatch):
    assert client.post('/api/stt', content=b'audio', headers={'Content-Type': 'text/plain'}).status_code == 415
    assert client.post('/api/stt', headers={'Content-Type': 'audio/mp4'}).status_code == 400
    monkeypatch.setattr(voice, 'STT_MAX_BYTES', 4)
    assert client.post('/api/stt', content=b'audio', headers={'Content-Type': 'audio/mp4'}).status_code == 413


@pytest.mark.parametrize('response,expected', [
    (httpx.Response(401, text='secret upstream body'), 'stt_upstream_error'),
    (httpx.Response(307, headers={'Location': 'https://other.test'}), 'stt_upstream_error'),
    (httpx.Response(200, text='not json'), 'invalid_transcript'),
    (httpx.Response(200, json=[]), 'invalid_transcript'),
    (httpx.Response(200, json={'text': 3}), 'invalid_transcript'),
])
def test_invalid_upstream(client, monkeypatch, response, expected):
    upstream(monkeypatch, response)
    result = client.post('/api/stt', content=b'audio', headers={'Content-Type': 'audio/mp4'})
    assert result.json()['error_code'] == expected
    assert 'secret' not in result.text


@pytest.mark.parametrize('error,code', [(httpx.ConnectError('secret'), 'stt_unavailable'),
                                        (httpx.ReadTimeout('secret'), 'stt_timeout')])
def test_unavailable(client, monkeypatch, error, code):
    upstream(monkeypatch, error=error)
    result = client.post('/api/stt', content=b'audio', headers={'Content-Type': 'audio/mp4'})
    assert result.json()['error_code'] == code
    assert 'secret' not in result.text
