"""Российские провайдеры: только мок-HTTP (httpx.MockTransport), без сети."""
import json

import httpx
import pytest

from studio import core
from studio.core import Client, Generator, ProviderError, make_generator
from studio.providers import GigaChatGenerator, YandexGPTGenerator

CLIENT = Client('ООО Тест', 'Иван', 'Автоматизировать заявки', 50000)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setattr(core, 'load_dotenv', lambda *a, **k: None)
    for name in ['LLM_PROVIDER', 'OPENAI_API_KEY', 'GIGACHAT_CREDENTIALS', 'GIGACHAT_SCOPE', 'GIGACHAT_MODEL', 'YANDEX_API_KEY', 'YANDEX_FOLDER_ID', 'YANDEX_MODEL']:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr('studio.providers.time.sleep', lambda s: sleeps.append(s))
    sleeps.clear()


sleeps = []


def mock(handler):
    calls = []
    def wrapped(request):
        calls.append(request)
        return handler(request, len(calls))
    return httpx.Client(transport=httpx.MockTransport(wrapped)), calls


def giga_chat_ok(text='Готовый текст'):
    return httpx.Response(200, json={'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': text}}]})


def oauth_ok(token='tok1', expires_at=None):
    return httpx.Response(200, json={'access_token': token, 'expires_at': expires_at or 4_000_000_000_000})


@pytest.fixture
def giga(monkeypatch):
    monkeypatch.setenv('GIGACHAT_CREDENTIALS', 'c2VjcmV0')
    monkeypatch.setenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS')


# --- выбор провайдера ---

def test_default_provider_is_proxyapi(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'sk-test')
    assert isinstance(make_generator(), Generator)


def test_select_gigachat(monkeypatch, giga):
    monkeypatch.setenv('LLM_PROVIDER', 'GigaChat')
    assert isinstance(make_generator(), GigaChatGenerator)


def test_select_yandex(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'yandexgpt')
    monkeypatch.setenv('YANDEX_API_KEY', 'k')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'b1gfolder')
    engine = make_generator()
    assert isinstance(engine, YandexGPTGenerator)
    assert engine.model_uri == 'gpt://b1gfolder/yandexgpt/latest'


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'mistral')
    with pytest.raises(ValueError, match='LLM_PROVIDER'):
        make_generator()


def test_missing_keys_are_reported(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'gigachat')
    with pytest.raises(ValueError, match='GIGACHAT_CREDENTIALS'):
        make_generator()
    monkeypatch.setenv('LLM_PROVIDER', 'yandexgpt')
    monkeypatch.setenv('YANDEX_API_KEY', 'k')
    with pytest.raises(ValueError, match='YANDEX_FOLDER_ID'):
        make_generator()


def test_bad_scope(monkeypatch, giga):
    monkeypatch.setenv('GIGACHAT_SCOPE', 'WRONG')
    with pytest.raises(ValueError, match='GIGACHAT_SCOPE'):
        GigaChatGenerator()


def test_run_batch_aborts_cleanly_without_keys(monkeypatch, tmp_path):
    monkeypatch.setenv('LLM_PROVIDER', 'gigachat')
    source = tmp_path / 'c.csv'
    source.write_text('Название компании,Контактное лицо,Потребности клиента,Бюджет\nА,Б,В,100\n', encoding='utf-8')
    result = core.run_batch(source, tmp_path / 'out')
    assert result['failed'] == 1 and 'GIGACHAT_CREDENTIALS' in result['results'][0]['error']


# --- GigaChat ---

def test_gigachat_auth_and_request(giga):
    def handler(request, n):
        if 'oauth' in str(request.url):
            return oauth_ok()
        return giga_chat_ok()
    http, calls = mock(handler)
    engine = GigaChatGenerator(http=http)
    assert engine.generate(CLIENT) == 'Готовый текст'
    oauth, chat = calls
    assert str(oauth.url) == GigaChatGenerator.oauth_url
    assert oauth.headers['Authorization'] == 'Basic c2VjcmV0'
    assert len(oauth.headers['RqUID']) == 36
    assert oauth.content == b'scope=GIGACHAT_API_PERS'
    assert str(chat.url) == GigaChatGenerator.chat_url
    assert chat.headers['Authorization'] == 'Bearer tok1'
    body = json.loads(chat.content)
    assert body['messages'][0] == {'role': 'system', 'content': core.SYSTEM_PROMPT}
    assert json.loads(body['messages'][1]['content'])['company'] == 'ООО Тест'


def test_gigachat_token_cached_and_refreshed_on_expiry(giga):
    now = [1000.0]
    tokens = iter(['tok1', 'tok2'])
    def handler(request, n):
        if 'oauth' in str(request.url):
            return oauth_ok(next(tokens), expires_at=int((now[0] + 1800) * 1000))
        return giga_chat_ok()
    http, calls = mock(handler)
    engine = GigaChatGenerator(http=http, clock=lambda: now[0])
    engine.generate(CLIENT)
    engine.generate(CLIENT)
    assert sum('oauth' in str(c.url) for c in calls) == 1
    now[0] += 1800 - 30  # внутри запаса до истечения
    engine.generate(CLIENT)
    assert sum('oauth' in str(c.url) for c in calls) == 2
    assert calls[-1].headers['Authorization'] == 'Bearer tok2'


def test_gigachat_refreshes_token_on_401(giga):
    tokens = iter(['old', 'new'])
    def handler(request, n):
        if 'oauth' in str(request.url):
            return oauth_ok(next(tokens))
        if request.headers['Authorization'] == 'Bearer old':
            return httpx.Response(401, json={'message': 'Token has expired'})
        return giga_chat_ok()
    http, calls = mock(handler)
    assert GigaChatGenerator(http=http).generate(CLIENT) == 'Готовый текст'
    assert len(calls) == 4


def test_gigachat_bad_credentials_abort(giga):
    http, calls = mock(lambda r, n: httpx.Response(401, json={'message': 'Authorization error'}))
    with pytest.raises(ProviderError, match='авторизация') as info:
        GigaChatGenerator(http=http).generate(CLIENT)
    assert info.value.abort_batch and len(calls) == 1 and not sleeps


@pytest.mark.parametrize('first', [httpx.Response(429), httpx.Response(503), 'timeout'])
def test_gigachat_transient_retried_once(giga, first):
    def handler(request, n):
        if 'oauth' in str(request.url):
            return oauth_ok()
        if n == 2:
            if first == 'timeout':
                raise httpx.ReadTimeout('slow', request=request)
            return first
        return giga_chat_ok()
    http, calls = mock(handler)
    assert GigaChatGenerator(http=http).generate(CLIENT) == 'Готовый текст'
    assert sleeps == [GigaChatGenerator.backoff]


def test_gigachat_persistent_5xx_aborts_batch(giga):
    def handler(request, n):
        return oauth_ok() if 'oauth' in str(request.url) else httpx.Response(502)
    http, calls = mock(handler)
    with pytest.raises(ProviderError, match='HTTP 502') as info:
        GigaChatGenerator(http=http).generate(CLIENT)
    assert info.value.abort_batch and len(calls) == 3


def test_gigachat_network_down(giga):
    def handler(request, n):
        raise httpx.ConnectError('refused', request=request)
    http, _ = mock(handler)
    with pytest.raises(ProviderError, match='Нет ответа от GigaChat') as info:
        GigaChatGenerator(http=http).generate(CLIENT)
    assert info.value.abort_batch


def test_gigachat_truncated_answer(giga):
    def handler(request, n):
        if 'oauth' in str(request.url):
            return oauth_ok()
        return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': 'обрыв'}}]})
    http, _ = mock(handler)
    with pytest.raises(RuntimeError, match='не завершил'):
        GigaChatGenerator(http=http).generate(CLIENT)


def test_gigachat_uses_russian_ca(giga):
    assert (core.ROOT / 'certs' / 'russian_trusted_root_ca.pem').exists()


# --- YandexGPT ---

@pytest.fixture
def yandex(monkeypatch):
    monkeypatch.setenv('YANDEX_API_KEY', 'AQVNsecret')
    monkeypatch.setenv('YANDEX_FOLDER_ID', 'b1gfolder')


def ya_ok(text='Текст Яндекса', status='ALTERNATIVE_STATUS_FINAL'):
    return httpx.Response(200, json={'result': {'alternatives': [{'message': {'role': 'assistant', 'text': text}, 'status': status}], 'usage': {}, 'modelVersion': 'x'}})


def test_yandex_request_format(yandex):
    http, calls = mock(lambda r, n: ya_ok())
    assert YandexGPTGenerator(http=http).generate(CLIENT) == 'Текст Яндекса'
    (request,) = calls
    assert str(request.url) == YandexGPTGenerator.url
    assert request.headers['Authorization'] == 'Api-Key AQVNsecret'
    assert request.headers['x-folder-id'] == 'b1gfolder'
    body = json.loads(request.content)
    assert body['modelUri'] == 'gpt://b1gfolder/yandexgpt/latest'
    assert body['completionOptions']['maxTokens'] == '3000'
    assert body['messages'][0] == {'role': 'system', 'text': core.SYSTEM_PROMPT}


def test_yandex_custom_model(monkeypatch, yandex):
    monkeypatch.setenv('YANDEX_MODEL', 'yandexgpt-lite/latest')
    assert YandexGPTGenerator(http=httpx.Client()).model_uri == 'gpt://b1gfolder/yandexgpt-lite/latest'


@pytest.mark.parametrize('code', [401, 403])
def test_yandex_auth_errors_fail_fast(yandex, code):
    http, calls = mock(lambda r, n: httpx.Response(code))
    with pytest.raises(ProviderError, match=f'HTTP {code}') as info:
        YandexGPTGenerator(http=http).generate(CLIENT)
    assert info.value.abort_batch and len(calls) == 1 and not sleeps


def test_yandex_429_retried_once(yandex):
    http, calls = mock(lambda r, n: httpx.Response(429) if n == 1 else ya_ok())
    assert YandexGPTGenerator(http=http).generate(CLIENT) == 'Текст Яндекса'
    assert len(calls) == 2 and sleeps == [YandexGPTGenerator.backoff]


def test_yandex_400_not_retried_and_not_abort(yandex):
    http, calls = mock(lambda r, n: httpx.Response(400))
    with pytest.raises(ProviderError) as info:
        YandexGPTGenerator(http=http).generate(CLIENT)
    assert not info.value.abort_batch and len(calls) == 1


def test_yandex_unfinished_answer(yandex):
    http, _ = mock(lambda r, n: ya_ok(status='ALTERNATIVE_STATUS_TRUNCATED_FINAL'))
    with pytest.raises(RuntimeError, match='не завершил'):
        YandexGPTGenerator(http=http).generate(CLIENT)
