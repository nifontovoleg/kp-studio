import argparse
import sys
from pathlib import Path

from .core import ROOT, load_clients, run_batch


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='КП-студия — предложения из CSV и Excel')
    parser.add_argument('input', type=Path, help='Таблица клиентов .csv или .xlsx')
    parser.add_argument('--output', type=Path, default=ROOT / 'output')
    parser.add_argument('--demo', action='store_true', help='Локальный шаблон без обращения к AI')
    parser.add_argument('--check', action='store_true', help='Проверить таблицу без генерации')
    parser.add_argument('--limit', type=int, help='Обработать первые N корректных строк')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error('--limit должен быть положительным')
    try:
        if args.check:
            clients, errors = load_clients(args.input)
            print(f'Корректных строк: {len(clients)}. Ошибок: {len(errors)}.')
            for error in errors:
                print(f'Строка {error["row"]}: {error["error"]}')
            return 1 if errors else 0
        print('Режим: ' + ('демонстрация без AI' if args.demo else 'API — запросы расходуют баланс провайдера'), flush=True)
        result = run_batch(args.input, args.output, demo=args.demo, limit=args.limit)
        for entry in result['results']:
            print(f'Строка {entry["row"]}: ' + (str(args.output / entry['pdf']) if entry['status'] == 'ok' else entry['error']), flush=True)
        print(f'Готово: {result["success"]}; ошибок: {result["failed"]}. Журнал: {args.output / "journal.jsonl"}')
        return 1 if result['failed'] else 0
    except Exception as exc:
        print(str(exc) if isinstance(exc, (ValueError, RuntimeError, FileNotFoundError)) else f'Не удалось обработать таблицу ({type(exc).__name__}). Проверьте формат и доступ к файлу.')
        return 1
