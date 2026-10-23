"""Российские LLM-провайдеры: GigaChat (Сбер) и YandexGPT (Yandex AI Studio).

Тот же промпт, тот же разбор ответа и та же политика повторов, что у ProxyAPI:
один повтор через backoff при таймауте, сетевом сбое, HTTP 429 и 5xx.
"""
from __future__ import annotations

import json
import os
import ssl
import threading
import time
import uuid
from dataclasses import asdict

import httpx

from .core import ROOT, SYSTEM_PROMPT, Client, ProviderError, status_error

MAX_TOKENS = 3000


class _HTTPGenerator:
    retries = 1
    backoff = 3.0
    name = 'API'

    def __init__(self, http: httpx.Client | None = None, verify=True):
        self.http = http or httpx.Client(timeout=90, verify=verify)

    def _post(self, url, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            try:
                response = self.http.post(url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError('transient', request=response.request, response=response)
                return response
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if attempt >= self.retries:
                    if isinstance(exc, httpx.HTTPStatusError):
                        return exc.response
                    raise ProviderError(f'Нет ответа от {self.name}. Проверьте соединение и доступность сервиса.', abort_batch=True) from None
                attempt += 1
                time.sleep(self.backoff * attempt)

    @staticmethod
    def _messages(client: Client, text_key: str):
        return [{'role': 'system', text_key: SYSTEM_PROMPT},
                {'role': 'user', text_key: json.dumps(asdict(client), ensure_ascii=False)}]

    @staticmethod
    def _check_text(content: str | None) -> str:
        content = (content or '').strip()
        if not content or len(content) > 18000:
            raise RuntimeError('API вернул пустой или слишком длинный текст.')
        return content


class GigaChatGenerator(_HTTPGenerator):
    name = 'GigaChat'
    oauth_url = 'https://ngw.devices.sberbank.ru:9443/api/v2/oauth'
    chat_url = 'https://gigachat.devices.sberbank.ru/api/v1/chat/completions'
    token_margin = 60  # секунд: обновляем токен заранее (живёт ~30 минут)

    def __init__(self, http: httpx.Client | None = None, clock=time.time):
        self.credentials = os.getenv('GIGACHAT_CREDENTIALS', '').strip()
        if not self.credentials:
            raise ValueError('Не задан GIGACHAT_CREDENTIALS (ключ авторизации) в .env.')
        self.scope = os.getenv('GIGACHAT_SCOPE', '').strip() or 'GIGACHAT_API_PERS'
        if self.scope not in {'GIGACHAT_API_PERS', 'GIGACHAT_API_B2B', 'GIGACHAT_API_CORP'}:
            raise ValueError('GIGACHAT_SCOPE: GIGACHAT_API_PERS, GIGACHAT_API_B2B или GIGACHAT_API_CORP.')
        self.model = os.getenv('GIGACHAT_MODEL', '').strip() or 'GigaChat'
        ca = os.getenv('GIGACHAT_CA_BUNDLE', '').strip() or str(ROOT / 'certs' / 'russian_trusted_root_ca.pem')
        # Системные корни + корневой сертификат Минцифры (им подписан сертификат GigaChat).
        verify = ssl.create_default_context()
        if os.path.exists(ca):
            verify.load_verify_locations(cafile=ca)
        super().__init__(http, verify=verify)
        self.clock = clock
        self._token, self._expires = None, 0.0
        self._lock = threading.Lock()

    def _get_token(self, force=False) -> str:
        with self._lock:
            if not force and self._token and self.clock() < self._expires - self.token_margin:
                return self._token
            response = self._post(self.oauth_url, data={'scope': self.scope}, headers={
                'Authorization': f'Basic {self.credentials}', 'RqUID': str(uuid.uuid4()),
                'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json'})
            if response.status_code != 200:
                raise ProviderError(f'GigaChat: авторизация не прошла (HTTP {response.status_code}). Проверьте GIGACHAT_CREDENTIALS и GIGACHAT_SCOPE.', abort_batch=True)
            data = response.json()
            self._token = data['access_token']
            expires = data.get('expires_at')  # миллисекунды Unix
            self._expires = expires / 1000 if expires else self.clock() + 30 * 60
            return self._token

    def generate(self, client: Client) -> str:
        body = {'model': self.model, 'messages': self._messages(client, 'content'), 'max_tokens': MAX_TOKENS}
        response = None
        for force in (False, True):
            response = self._post(self.chat_url, json=body, headers={'Authorization': f'Bearer {self._get_token(force)}', 'Accept': 'application/json'})
            if response.status_code != 401:
                break  # 401 с кэшированным токеном: один раз обновляем токен
        if response.status_code != 200:
            raise status_error(response.status_code)
        choices = response.json().get('choices') or []
        if not choices or choices[0].get('finish_reason') != 'stop':
            raise RuntimeError('API не завершил текст. PDF не создан; повторите запрос после проверки лимита ответа.')
        return self._check_text(choices[0].get('message', {}).get('content'))


class YandexGPTGenerator(_HTTPGenerator):
    name = 'YandexGPT'
    url = 'https://llm.api.cloud.yandex.net/foundationModels/v1/completion'

    def __init__(self, http: httpx.Client | None = None):
        self.api_key = os.getenv('YANDEX_API_KEY', '').strip()
        self.folder = os.getenv('YANDEX_FOLDER_ID', '').strip()
        if not self.api_key or not self.folder:
            raise ValueError('Для YandexGPT нужны YANDEX_API_KEY и YANDEX_FOLDER_ID в .env.')
        model = os.getenv('YANDEX_MODEL', '').strip() or 'yandexgpt/latest'
        self.model_uri = model if model.startswith('gpt://') else f'gpt://{self.folder}/{model}'
        super().__init__(http)

    def generate(self, client: Client) -> str:
        body = {'modelUri': self.model_uri, 'completionOptions': {'stream': False, 'temperature': 0.3, 'maxTokens': str(MAX_TOKENS)},
                'messages': self._messages(client, 'text')}
        response = self._post(self.url, json=body, headers={'Authorization': f'Api-Key {self.api_key}', 'x-folder-id': self.folder})
        if response.status_code != 200:
            raise status_error(response.status_code)
        alternatives = (response.json().get('result') or {}).get('alternatives') or []
        if not alternatives or alternatives[0].get('status') != 'ALTERNATIVE_STATUS_FINAL':
            raise RuntimeError('API не завершил текст. PDF не создан; повторите запрос после проверки лимита ответа.')
        return self._check_text(alternatives[0].get('message', {}).get('text'))
