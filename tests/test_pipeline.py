import json
from pathlib import Path

import pandas as pd
import pytest

from studio.core import COLUMNS, Client, Generator, ProviderError, company_folder, load_clients, run_batch


def table(path, rows):
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, sep=';', encoding='utf-8-sig')
    return path


@pytest.mark.parametrize('budget', ['NaN', 'inf', '-1', '0', 'abc', '1000000001'])
def test_invalid_budget_is_rejected(tmp_path, budget):
    good, errors = load_clients(table(tmp_path / 'input.csv', [['Тест', 'Имя', 'Задача', budget]]))
    assert not good
    assert errors[0]['row'] == 2


def test_excel_and_csv_read_equally(tmp_path):
    source = table(tmp_path / 'input.csv', [['Тест', 'Имя', 'Задача', '45 000,50']])
    pd.read_csv(source, sep=';').to_excel(tmp_path / 'input.xlsx', index=False)
    assert load_clients(source) == load_clients(tmp_path / 'input.xlsx')


@pytest.mark.parametrize('name', ['../../evil', 'CON', 'NUL.txt', 'a/b', 'a\\b', '...'])
def test_folder_stays_inside_output(name):
    folder = company_folder(name)
    assert '/' not in folder and '\\' not in folder
    assert folder.split('.')[0].upper() not in {'CON', 'NUL'}
    assert folder not in {'.', '..'}
    assert company_folder('a/b') != company_folder('a\\b')


def test_failure_does_not_stop_other_clients_and_log_appends(tmp_path):
    class FakeAPI:
        def generate(self, client):
            if client.company == 'Сбой':
                raise RuntimeError('API вернул HTTP 429.')
            return 'Решение для ' + client.company
    source = table(tmp_path / 'input.csv', [['Сбой', 'Имя', 'Задача', '10'], ['Успех', 'Имя', 'Задача < & >', '20'], ['Пусто', '', 'Задача', '30']])
    out = tmp_path / 'output'
    first = run_batch(source, out, generator=FakeAPI())
    assert first['success'] == 1 and first['failed'] == 2
    pdf = next(out.rglob('*.pdf'))
    assert pdf.read_bytes().startswith(b'%PDF-')
    second = run_batch(source, out, generator=FakeAPI())
    assert second['batch_id'] != first['batch_id']
    assert len(list(out.rglob('*.pdf'))) == 2
    entries = [json.loads(line) for line in (out / 'journal.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(entries) == 6


def test_missing_columns_fails_before_api(tmp_path):
    source = tmp_path / 'input.csv'
    source.write_text('foo,bar\n1,2', encoding='utf-8')
    with pytest.raises(ValueError, match='колонки'):
        run_batch(source, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('content,reason', [('', 'stop'), ('Оборванный текст', 'length')])
def test_incomplete_ai_answer_is_not_accepted(content, reason):
    from types import SimpleNamespace
    engine = Generator.__new__(Generator)
    engine.model = 'test'
    class Completions:
        def create(self, **kwargs):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason=reason, message=SimpleNamespace(content=content))])
    engine.api = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    with pytest.raises(RuntimeError):
        engine.generate(Client('Тест', 'Имя', 'Задача', 10))


def test_text_is_saved_when_pdf_fails(tmp_path, monkeypatch):
    source = table(tmp_path / 'input.csv', [['Тест', 'Имя', 'Задача', '10']])
    def broken_pdf(*args, **kwargs):
        raise OSError('disk unavailable')
    monkeypatch.setattr('studio.core.render_pdf', broken_pdf)
    result = run_batch(source, tmp_path / 'output', demo=True)
    assert result['failed'] == 1
    assert len(list((tmp_path / 'output').rglob('*.txt'))) == 1
    assert not list((tmp_path / 'output').rglob('*.pdf'))


def test_provider_outage_stops_requests_and_records_remaining_rows(tmp_path):
    class OfflineAPI:
        calls = 0
        def generate(self, client):
            self.calls += 1
            raise ProviderError('Нет ответа от API.', abort_batch=True)
    engine = OfflineAPI()
    source = table(tmp_path / 'input.csv', [['А', 'Имя', 'Бот', '100'], ['Б', 'Имя', 'Сайт', '200']])
    result = run_batch(source, tmp_path / 'output', generator=engine)
    assert engine.calls == 1
    assert result['success'] == 0 and result['failed'] == 2
    assert result['results'][1]['error'].startswith('Не отправлено:')
    assert len((tmp_path / 'output' / 'journal.jsonl').read_text(encoding='utf-8').splitlines()) == 2


@pytest.mark.parametrize('abort', [False, True])
def test_prior_success_survives_provider_failure(tmp_path, abort):
    class SometimesAPI:
        calls = []
        def generate(self, client):
            self.calls.append(client.company)
            if client.company == 'Б':
                raise ProviderError('API вернул ошибку.', abort_batch=abort)
            return 'Решение для ' + client.company
    engine = SometimesAPI()
    source = table(tmp_path / 'input.csv', [[name, 'Имя', 'Задача', '100'] for name in ['А', 'Б', 'В']])
    out = tmp_path / 'output'
    result = run_batch(source, out, generator=engine)
    assert engine.calls == (['А', 'Б'] if abort else ['А', 'Б', 'В'])
    assert result['success'] == (1 if abort else 2)
    assert len(result['results']) == 3
    assert not Path(result['results'][0]['pdf']).is_absolute()
    assert (out / result['results'][0]['pdf']).exists()
    assert len((out / 'journal.jsonl').read_text(encoding='utf-8').splitlines()) == 3


def _fake_engine(outcomes, monkeypatch):
    """Generator with a fake OpenAI client: each call pops the next outcome (exception or text)."""
    from types import SimpleNamespace
    sleeps = []
    monkeypatch.setattr('studio.core.time.sleep', sleeps.append)
    engine = Generator.__new__(Generator)
    engine.model = 'test'
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            outcome = outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=outcome))])
    engine.api = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    return engine, calls, sleeps


def _status_error(code):
    import httpx
    from openai import APIStatusError
    request = httpx.Request('POST', 'https://api.example.test/v1/chat/completions')
    return APIStatusError('error', response=httpx.Response(code, request=request), body=None)


def _timeout_error():
    import httpx
    from openai import APITimeoutError
    return APITimeoutError(request=httpx.Request('POST', 'https://api.example.test/v1/chat/completions'))


@pytest.mark.parametrize('make_error', [_timeout_error, lambda: _status_error(429), lambda: _status_error(502)])
def test_transient_error_is_retried_once(monkeypatch, make_error):
    engine, calls, sleeps = _fake_engine([make_error(), 'Готовый текст'], monkeypatch)
    assert engine.generate(Client('Тест', 'Имя', 'Задача', 10)) == 'Готовый текст'
    assert len(calls) == 2
    assert sleeps == [Generator.backoff]


def test_second_transient_error_stops_batch(monkeypatch):
    engine, calls, sleeps = _fake_engine([_timeout_error(), _timeout_error(), 'не дойдёт'], monkeypatch)
    with pytest.raises(ProviderError) as info:
        engine.generate(Client('Тест', 'Имя', 'Задача', 10))
    assert info.value.abort_batch
    assert len(calls) == 2 and len(sleeps) == 1


@pytest.mark.parametrize('code', [401, 402])
def test_auth_and_balance_errors_fail_fast(monkeypatch, code):
    engine, calls, sleeps = _fake_engine([_status_error(code), 'не дойдёт'], monkeypatch)
    with pytest.raises(ProviderError, match=f'HTTP {code}') as info:
        engine.generate(Client('Тест', 'Имя', 'Задача', 10))
    assert info.value.abort_batch
    assert len(calls) == 1 and not sleeps
