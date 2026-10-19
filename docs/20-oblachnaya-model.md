# Облачная модель: NVIDIA Nemotron через OpenRouter

Реализует п. 2 плана `19-plan-fleshka-i-oblako.md`. Работает без флешки и без скачивания моделей:
облачная модель + локальная база знаний (Visual Components/R-Pro, Academy, ИИТБ — `agent/kb`).

## Включение

1. Ключ: openrouter.ai/keys. В аккаунте OpenRouter (Settings → Privacy) разрешить бесплатные
   endpoint'ы, иначе бесплатные модели вернут 404 «no endpoints».
2. `%LOCALAPPDATA%\R-Pro\AIAgentBridge\settings.json`:

```json
{ "RPRO_LLM": "openrouter", "OPENROUTER_API_KEY": "sk-or-..." }
```

`RPRO_LLM`: `ollama` (по умолчанию, как раньше) · `openrouter` · `auto` (облако, при сбое — Ollama).
Ключ в репозиторий и в `defaults.json` установщика не класть.

## Модели (проверено по каталогу OpenRouter на 19.10.2026)

| Роль | Переменная | По умолчанию |
|---|---|---|
| Основная (tools) | `OPENROUTER_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b:free` |
| Запасные при 429/5xx | `OPENROUTER_FALLBACK_MODELS` | `nvidia/nemotron-3-super-120b-a12b:free`, `nvidia/nemotron-3.5-lightning:free` |
| Зрение (снимки окна) | `OPENROUTER_VISION_MODEL` | `nvidia/nemotron-3.5-super-vl:free` |

## Устройство

`agent/llm.py` — единая точка (chat, look, warm_up, list_models, describe); `llm_ollama.py` без
изменений; `llm_openrouter.py` переводит сообщения Ollama ⇄ OpenAI (id вызовов, аргументы JSON).
Остальной код (`chat.py`, `serve.py`, `tools.py`, `answer.py`, `selfcheck.py`) ходит через `llm`.
Офлайн-тест на заглушке: `python tests/test_llm_openrouter.py`.

## Не сделано / риски

- **Не проверено на живом OpenRouter** (ключа не было): формат запросов проверен только заглушкой.
  Первым делом — `python agent/selfcheck.py`, затем `eval_routes.py` и фразы TechSkills.
- Системная подсказка и фильтр инструментов написаны под 8B (`chat._loop`); для крупной модели их,
  возможно, стоит ослабить — решать по прогонам.
- **Данные уходят за периметр** (противоречит `02-arhitektura.md`): нужно решение СБ. Бесплатные
  модели OpenRouter могут логироваться провайдером. Нет: фильтра путей/имён, журнала отправленного,
  переключателя в панели.
- Лимиты бесплатного уровня (запросов в минуту/сутки) — для ходов с инструментами возможна
  задержка; повтор и запасные модели смягчают, но не снимают.
- `NUM_CTX` (8192) относится только к Ollama; бюджет истории в `chat._compact` не пересматривался.
