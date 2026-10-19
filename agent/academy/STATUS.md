# Реестр знаний Academy: состояние

Файл строит `python academy_status.py` по фактам на диске. Машинный вариант — `status.json`.

| Состояние | Сколько | Что это |
|---|---|---|
| done | 272 | урок в реестре `registry/lessons.jsonl` (в базе агента: 269) |
| ready | 0 | вход подготовлен в `pending/lessons/`, ждёт запуска модели |
| need_pdf | 0 | документные уроки без видео: PDF не скачан |
| need_transcript | 0 | у ролика нет транскрипта |

Где что лежит: знания — `registry/lessons.jsonl` (русский урок, английский конспект, метаданные), исходные тексты — `registry/sources.jsonl.gz`, отчёты оценки — `registry/audit/`, поиск агента — `../kb/academy_chunks.jsonl`. Рабочие папки `pending/`, `digests_*`, `transcripts/`, `work/` существуют только во время обработки и убираются командой `academy_consolidate.py --apply --clean`.

В реестре, но не в базе агента: `allen-bradley-plc-connectivity-plugin` (не применимо к R-Pro); `python-3-overview` (Python 3 API (в R-Pro Python 2.7)); `mqtt-client-tutorial` (не применимо к R-Pro)
