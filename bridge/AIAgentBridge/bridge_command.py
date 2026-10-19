# -*- coding: utf-8 -*-
"""
ИИ-мост R-Pro — серверная часть, живущая внутри R-Pro.

Поднимает локальный HTTP-сервер (по умолчанию 127.0.0.1:8765), который
принимает JSON-команды от внешнего ИИ-агента и отдаёт ему состояние сцены,
сообщения, снимки 3D-вида и результаты выполнения кода.

Почему сервер устроен именно так
--------------------------------
Конструкция выстрадана двумя отказами на живой программе.

1. Фоновый поток с обычным HTTP-сервером не работает: встроенный интерпретатор
   удерживает GIL, пока не выполняет свой код, и поток Python не получает
   управления. Симптом обманчивый — соединение устанавливается (его принимает
   ядро ОС), но ответа нет.
2. Таймер Windows (SetTimer с обратным вызовом через ctypes) подвесил программу
   насмерть: вход в Python из сырого системного колбэка конфликтует с тем, как
   хост управляет состоянием потоков интерпретатора.

3. Событие OnIdle, на которое была ставка после первых двух отказов, в этой
   версии R-Pro не срабатывает вообще ни разу. В справке оно и помечено
   устаревшим — теперь понятно, насколько буквально.

4. Событие OnRender работает, но R-Pro рисует только по необходимости: стоит
   пользователю убрать руки — кадры прекращаются, и мост немеет. Разбудить
   отрисовку снаружи не вышло ничем: ни перерисовкой окна, ни виртуальной
   мышью, ни PrintWindow — 3D-вид рисуется средствами WPF внутри единственного
   окна приложения.

5. Заставить R-Pro рисовать изнутри Python не вышло: цепочка «кадр просит
   следующий» живёт ровно один шаг, а замеры, которые сначала выглядели
   удачными, оказались загрязнены движениями мыши.

Отсюда нынешняя схема: никаких своих потоков и никаких системных колбэков.
Сокет опрашивается из события OnRender, то есть управление приходит к нам
законным путём и в главном потоке. А кадры обеспечивает крошечный плагин на
C# (папка addon): у платформы .NET есть штатная служба отрисовки
IRenderService, и плагин по таймеру WPF просит у неё кадр десять раз в секунду.
Из Python эта служба недоступна — потому полтора дня и не получалось.

Поэтому keep_rendering по умолчанию выключен: мосту больше незачем трогать
сцену или камеру ради кадров. Способы вызова кадра оставлены в коде на случай,
если плагин не установлен: тогда мост будет отвечать, пока пользователь
работает в программе.

Плата за решение: R-Pro постоянно отрисовывает вид, даже когда никто не
работает. Отключается файлом ticker.disabled, см. addon/build.ps1. А тяжёлый
запрос (выполнение кода) на время работы придерживает интерфейс.

Python внутри R-Pro — 2.7, синтаксис строго py2.
"""

from vcCommand import *

import base64
import json
import os
import select
import socket
import sys
import time
import traceback

from StringIO import StringIO

BRIDGE_VERSION = '0.10.0'
DEFAULT_PORT = 8765
DEFAULT_HOST = '127.0.0.1'

# Сколько держим недочитанное соединение, прежде чем выбросить его, секунды.
CONNECTION_TTL = 15.0

# Ограничение на время отправки ответа, секунды.
SEND_TIMEOUT = 5.0

cmd = getCommand()
app = cmd.Application

# Пространство имён команды: отсюда берём константы VC_* и функции вроде
# loadLayout, которые появляются из "from vcCommand import *".
ENV = globals()

_listener = None
_clients = []            # недочитанные соединения: [socket, буфер, время появления]
_in_pump = False         # защита от повторного входа

_stats = {
    'started_at': time.time(),
    'requests': 0,
    'errors': 0,
    'pumps': 0,
    'last_pump_at': 0.0,
    # Считаем каждое событие отдельно: так сразу видно, какое из них живое.
    'idle_events': 0,
    'render_events': 0,
    'last_render_request': 0.0,
}

HANDLERS = {}


def handler(name):
    def wrap(fn):
        HANDLERS[name] = fn
        return fn
    return wrap


def log(text):
    print('[ИИ-мост] ' + text)


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

def _script_dir():
    path = ''
    try:
        path = cmd.getCommandPath()
    except Exception:
        pass
    if path.startswith('file:///'):
        path = path[8:]
    path = path.replace('/', os.sep)
    if path:
        return os.path.dirname(path)
    return os.path.dirname(os.path.abspath(__file__))


def _load_config():
    cfg = {
        'host': DEFAULT_HOST,
        'port': DEFAULT_PORT,
        'token': '',
        'allow_exec': True,
        'screenshot_dir': '',
        'pump_on_idle': True,
        'pump_on_render': True,
        'keep_rendering': False,
        'render_fps': 0,
        'render_strategies': ['ao_contrast', 'camera', 'world_update'],
        'trace_frames': 0,
    }
    cfg_path = os.path.join(_script_dir(), 'bridge.json')
    if os.path.isfile(cfg_path):
        try:
            f = open(cfg_path, 'rb')
            try:
                # utf-8-sig: PowerShell 5.1 пишет файлы с BOM, и json.loads
                # на нём падает — так мост молча работал на умолчаниях.
                cfg.update(json.loads(f.read().decode('utf-8-sig')))
            finally:
                f.close()
        except Exception:
            log(u'не удалось прочитать bridge.json, беру значения по умолчанию')

    cfg['port'] = int(os.environ.get('RPRO_BRIDGE_PORT', cfg['port']))
    cfg['token'] = os.environ.get('RPRO_BRIDGE_TOKEN', cfg['token'])
    if not cfg['screenshot_dir']:
        cfg['screenshot_dir'] = os.path.join(
            os.environ.get('LOCALAPPDATA', os.environ.get('TEMP', '.')),
            'R-Pro', 'AIAgentBridge', 'screenshots')
    return cfg


CONFIG = _load_config()


# ---------------------------------------------------------------------------
# Вспомогательные преобразования объектов R-Pro в JSON
# ---------------------------------------------------------------------------

def _vec(v):
    try:
        return [round(float(v.X), 3), round(float(v.Y), 3), round(float(v.Z), 3)]
    except Exception:
        return None


def _matrix_info(m):
    out = {}
    try:
        out['position'] = _vec(m.P)
    except Exception:
        pass
    try:
        out['rotation_wpr'] = _vec(m.WPR)
    except Exception:
        pass
    return out


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, long, float)):
        return value
    if isinstance(value, bytes):
        # Разбор с перебором кодировок: сообщения R-Pro бывают и в cp1251.
        return _sanitize(value)
    if isinstance(value, unicode):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(x) for x in value]
    if isinstance(value, dict):
        # Без этой ветки словарь, возвращённый из exec, приезжал к клиенту
        # строкой с его текстовым представлением.
        return dict((_jsonable(k), _jsonable(v)) for k, v in value.items())
    vec = _vec(value)
    if vec is not None:
        return vec
    try:
        return unicode(value)
    except Exception:
        return repr(value)


def _component_brief(comp, with_position=True):
    info = {'name': _jsonable(comp.Name)}
    try:
        info['uri'] = _jsonable(comp.Uri)
    except Exception:
        pass
    try:
        info['visible'] = bool(comp.Visible)
    except Exception:
        pass
    if with_position:
        try:
            info.update(_matrix_info(comp.WorldPositionMatrix))
        except Exception:
            pass
    return info


def _selection_components():
    const = ENV.get('VC_SELECTION_COMPONENT')
    try:
        return list(app.SelectionManager.getSelection(const))
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Обработчики команд
# ---------------------------------------------------------------------------

@handler('ping')
def h_ping(p):
    return {
        'bridge_version': BRIDGE_VERSION,
        'product': _jsonable(getattr(app, 'ProductName', '')),
        'product_version': _jsonable(getattr(app, 'ProductVersion', '')),
        'python': sys.version.split()[0],
        'uptime_sec': round(time.time() - _stats['started_at'], 1),
        'stats': dict(_stats),
    }


@handler('status')
def h_status(p):
    sim = app.Simulation
    return {
        'layout_uri': _jsonable(getattr(app, 'LayoutUri', '')),
        'layout_modified': bool(getattr(app, 'LayoutModified', False)),
        'context': _jsonable(getattr(app, 'CurrentContext', '')),
        'component_count': len(app.Components),
        'simulation': {
            'running': bool(sim.IsRunning),
            'time_sec': round(float(sim.SimTime), 3),
            'speed': round(float(sim.SimSpeed), 3),
        },
        'selection': [_jsonable(c.Name) for c in _selection_components()],
    }


@handler('scene')
def h_scene(p):
    limit = int(p.get('limit', 200))
    with_position = bool(p.get('with_position', True))
    comps = list(app.Components)
    items = [_component_brief(c, with_position) for c in comps[:limit]]
    return {'total': len(comps), 'returned': len(items), 'components': items}


@handler('find')
def h_find(p):
    query = (p.get('query') or u'').lower()
    limit = int(p.get('limit', 50))
    out = []
    for c in app.Components:
        name = _jsonable(c.Name) or u''
        if query in name.lower():
            out.append(_component_brief(c))
            if len(out) >= limit:
                break
    return {'query': query, 'found': len(out), 'components': out}


@handler('component')
def h_component(p):
    name = p.get('name')
    comp = app.findComponent(name)
    if comp is None:
        raise ValueError(u'компонент "%s" не найден' % name)

    info = _component_brief(comp)

    if p.get('with_properties', True):
        props = []
        for prop in comp.Properties:
            try:
                props.append({
                    'name': _jsonable(prop.Name),
                    'type': _jsonable(prop.Type),
                    'value': _jsonable(prop.Value),
                    'group': _jsonable(prop.Group),
                })
            except Exception:
                continue
        info['properties'] = props

    if p.get('with_behaviours', False):
        beh = []
        for b in comp.Behaviours:
            try:
                beh.append({'name': _jsonable(b.Name), 'type': _jsonable(b.Type)})
            except Exception:
                continue
        info['behaviours'] = beh

    if p.get('with_children', False):
        kids = []
        try:
            for n in comp.Children:
                kids.append(_jsonable(n.Name))
        except Exception:
            pass
        info['children'] = kids

    return info


def _commit_initial_state():
    """
    Запомнить текущую сцену как исходное состояние симуляции.

    Сброс (и наш, и кнопкой в интерфейсе) возвращает сцену к исходному
    состоянию. Правки через Python-API туда сами не попадают: шаблон,
    вставленный через app.load(), после сброса схлопывался — 32 из 34
    компонентов улетали в точку (0, 0, 0). Интерфейс фиксирует исходное
    состояние сам при каждой правке, мы делаем то же через setInitialState().

    Только когда симуляция стоит на нуле: иначе исходным стало бы
    промежуточное состояние прогона, и сброс перестал бы возвращать в начало.
    Возвращает True, если зафиксировали.
    """
    sim = app.Simulation
    if sim.IsRunning or _pending_reset['active'] or float(sim.SimTime) > 1e-6:
        return False
    sim.setInitialState()
    return True


@handler('set_property')
def h_set_property(p):
    _finish_pending_reset(force=True)
    comp = app.findComponent(p.get('component'))
    if comp is None:
        raise ValueError(u'компонент "%s" не найден' % p.get('component'))
    prop = comp.getProperty(p.get('property'))
    if prop is None:
        raise ValueError(u'свойство "%s" не найдено' % p.get('property'))
    prop.Value = p.get('value')
    _commit_initial_state()
    return {'component': _jsonable(comp.Name),
            'property': _jsonable(prop.Name),
            'value': _jsonable(prop.Value)}


@handler('select')
def h_select(p):
    names = p.get('names') or []
    sm = app.SelectionManager
    sm.clear()
    picked = []
    for name in names:
        c = app.findComponent(name)
        if c is not None:
            sm.setSelection(c, True)
            picked.append(_jsonable(c.Name))
    return {'selected': picked}


@handler('messages')
def h_messages(p):
    text = app.getMessages()
    if p.get('clear', False):
        app.clearMessages()
    tail = int(p.get('tail', 100))
    lines = (text or u'').splitlines()
    return {'lines': [_jsonable(x) for x in lines[-tail:]], 'total_lines': len(lines)}


def _clock(seconds):
    """Время симуляции так, как его показывает R-Pro: 0:01:35."""
    seconds = int(round(seconds))
    return u'%d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)


def _start_until(stop_at):
    """
    Запускает симуляцию как кнопкой «Пуск» с остановкой на отметке stop_at.

    Только app.startSimulation(stop_time). Проверено на живой программе:
    stop_time — абсолютная отметка на часах симуляции, а не длительность;
    симуляция идёт в реальном времени, видна пользователю и не держит главный
    поток; останавливается ровно на отметке.

    vcSimulation.run(t) для этого не годится, хотя справка обещает «прогон на
    заданное время». На деле он вслепую досчитывает до отметки t за доли
    секунды и всё это время держит программу: пользователь видит, что
    симуляцию «перемотало». А без аргумента — на десять суток, и программа
    замирает насовсем. Обе ловушки мы уже собрали.
    """
    app.startSimulation(float(stop_at))


# Сброс, который ещё не доделан: см. _reset_with_clock.
_pending_reset = {'active': False}


def _reset_with_clock():
    """
    Сброс так, чтобы часы на панели симуляции тоже показали 0:00:00.

    app.resetSimulation() сбрасывает модель, но часы в интерфейсе не трогает:
    после сброса с 0:00:31 модель на нуле, а на панели так и висит 0:00:31.
    sim.update() часы тоже не обновляет. Обновляет их только настоящий шаг
    симуляции, поэтому после сброса делаем прогон на одну миллисекунду —
    часы встают на 0:00:00. Но за эту миллисекунду источник успевает
    породить изделие, так что, когда прогон остановится, сбрасываем ещё раз
    (_finish_pending_reset из прокачки). Часы при этом остаются на нуле.
    """
    app.resetSimulation()
    app.startSimulation(0.001)
    _pending_reset['active'] = True
    _pending_reset['since'] = time.time()


def _finish_pending_reset(force=False):
    """Второй сброс после прогона на миллисекунду. force — не ждать остановки."""
    if not _pending_reset['active']:
        return
    sim = app.Simulation
    if sim.IsRunning:
        # Прогон на миллисекунду не должен длиться секундами; если длится —
        # это уже не наш прогон, и тормозить его нельзя.
        if not force and time.time() - _pending_reset['since'] < 5:
            return
        if force:
            app.stopSimulation()
    _pending_reset['active'] = False
    if not sim.IsRunning:
        app.resetSimulation()


@handler('simulation')
def h_simulation(p):
    """
    Управление симуляцией.

    run      — «Пуск» без остановки;
    run_for  — «Пуск» на seconds секунд от текущей отметки;
    run_until — «Пуск» до отметки until на часах симуляции; если часы уже
                дальше, сначала сброс, то есть это же и «перемотка назад»;
    halt, reset, status — как кнопки.
    """
    action = (p.get('action') or 'status').lower()
    sim = app.Simulation
    if action != 'status':
        # Недоделанный сброс не должен сработать поверх новой команды.
        _finish_pending_reset(force=True)
    now = float(sim.SimTime)
    note = None
    stop_at = None

    if action == 'run':
        app.startSimulation()
        note = u'симуляция запущена с отметки %s без остановки' % _clock(now)
    elif action == 'run_for':
        seconds = p.get('seconds')
        if seconds is None or float(seconds) <= 0:
            raise ValueError(u'для run_for нужно положительное seconds')
        stop_at = now + float(seconds)
        _start_until(stop_at)
        note = (u'симуляция идёт в реальном времени с %s, остановится сама на %s '
                u'(через %g с)' % (_clock(now), _clock(stop_at), float(seconds)))
    elif action == 'run_until':
        until = p.get('until')
        if until is None:
            raise ValueError(u'для run_until нужно until — отметка в секундах')
        stop_at = float(until)
        if stop_at < 0:
            raise ValueError(u'отметка не может быть отрицательной')
        if stop_at <= 0:
            stop_at = None
            _reset_with_clock()
            note = u'симуляция сброшена на 0:00:00, сцена вернулась в исходное состояние'
        else:
            prefix = u''
            if stop_at <= now:
                # Назад симуляция не ходит: сброс и прогон с нуля до отметки.
                # Часы при этом обновятся сами — прогон настоящий.
                if sim.IsRunning:
                    app.stopSimulation()
                app.resetSimulation()
                prefix = u'перемотка назад с %s: сброс на 0:00:00, ' % _clock(now)
                now = 0.0
            _start_until(stop_at)
            note = prefix + (u'симуляция идёт в реальном времени с %s, остановится '
                             u'сама на %s (через %g с)'
                             % (_clock(now), _clock(stop_at), stop_at - now))
    elif action in ('halt', 'stop'):
        app.stopSimulation()
        note = u'симуляция остановлена'
    elif action == 'reset':
        if sim.IsRunning:
            app.stopSimulation()
        _reset_with_clock()
        note = u'симуляция сброшена, сцена вернулась в исходное состояние'
    elif action == 'update':
        sim.update()
    elif action != 'status':
        raise ValueError(u'неизвестное действие: %s' % action)

    now = float(sim.SimTime)
    # Прогон на миллисекунду после сброса — служебный, для модели симуляция стоит.
    running = bool(sim.IsRunning) and not _pending_reset['active']
    out = {'running': running, 'time_sec': round(now, 3),
           'time': _clock(now), 'component_count': len(app.Components)}
    if stop_at is not None:
        out['stop_at_sec'] = round(stop_at, 3)
        out['stop_at'] = _clock(stop_at)
    if note:
        out['note'] = note
    return out


@handler('screenshot')
def h_screenshot(p):
    width = int(p.get('width', 1280))
    height = int(p.get('height', 720))
    path = p.get('path')
    if not path:
        folder = CONFIG['screenshot_dir']
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, 'view_%d.png' % int(time.time() * 1000))

    # На этой сборке кадр-граббер не работает: вызовы проходят без ошибок, а
    # файла не появляется ни при каком написании пути. Снимок окна делает
    # внешний агент средствами Windows (agent/screen.py). Здесь оставлена
    # попытка через API — вдруг в другой версии программы она оживёт.
    last_error = None
    for fmt in ('rpng', 'png', 'rjpegstd', 'rbmp'):
        try:
            app.beginFrameGrab(fmt, width, height)
            try:
                app.executeFrameGrab('file:///' + path.replace('\\', '/'))
            finally:
                app.endFrameGrab()
            if os.path.isfile(path):
                break
        except Exception:
            last_error = traceback.format_exc()
    if not os.path.isfile(path):
        raise RuntimeError(u'не удалось сохранить снимок вида.\n%s' % (last_error or u''))

    out = {'path': path, 'width': width, 'height': height}
    if p.get('as_base64', True):
        f = open(path, 'rb')
        try:
            out['base64'] = base64.b64encode(f.read())
        finally:
            f.close()
    return out


@handler('exec')
def h_exec(p):
    if not CONFIG.get('allow_exec', True):
        raise RuntimeError(u'выполнение кода отключено в bridge.json')

    code = p.get('code') or ''
    # Отложенный второй сброс, сработав после правки, откатил бы её.
    _finish_pending_reset(force=True)
    scope = dict(ENV)
    scope['app'] = app
    scope['cmd'] = cmd
    scope['result'] = None

    old_stdout, old_stderr = sys.stdout, sys.stderr
    buf_out, buf_err = StringIO(), StringIO()
    sys.stdout, sys.stderr = buf_out, buf_err
    try:
        exec(code, scope)
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr

    # Код мог поменять сцену (так агент и вставляет модели из каталога).
    # Сама фиксация дешёвая и на нуле безвредна.
    _commit_initial_state()

    return {
        'stdout': buf_out.getvalue().decode('utf-8', 'replace'),
        'stderr': buf_err.getvalue().decode('utf-8', 'replace'),
        'result': _jsonable(scope.get('result')),
    }


@handler('layout')
def h_layout(p):
    action = (p.get('action') or '').lower()
    uri = p.get('uri') or ''
    if action == 'open':
        ENV['loadLayout'](uri)
    elif action == 'save':
        app.save(uri)
    elif action == 'clear':
        app.clearWorld()
    elif action == 'load_component':
        _finish_pending_reset(force=True)
        comp = app.load(uri)
        if comp is None:
            raise ValueError(u'не удалось загрузить компонент: %s' % uri)
        _commit_initial_state()
        return _component_brief(comp)
    else:
        raise ValueError(u'неизвестное действие: %s' % action)
    return {'ok': True, 'layout_uri': _jsonable(getattr(app, 'LayoutUri', ''))}


@handler('help')
def h_help(p):
    return {'methods': sorted(HANDLERS.keys()), 'bridge_version': BRIDGE_VERSION}


# ---------------------------------------------------------------------------
# Однопоточный HTTP поверх сокета
# ---------------------------------------------------------------------------

def _sanitize(value):
    """
    Готовит данные к сборке JSON.

    Байтовые строки из R-Pro и из трассировок приходят кто в utf-8, кто в
    cp1251. Раньше такая строка роняла ответ целиком: json.dumps спотыкался о
    первый же русский байт, и клиент не получал вообще ничего.
    """
    # В Python 2 bytes — это и есть str. Проверка именно по bytes позволяет
    # гонять тот же код под Python 3 в офлайн-тесте на заглушке.
    if isinstance(value, bytes):
        for encoding in ('utf-8', 'cp1251', 'latin-1'):
            try:
                return value.decode(encoding)
            except Exception:
                continue
        return repr(value)
    if isinstance(value, dict):
        return dict((_sanitize(k), _sanitize(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    return value


def _http_response(code, reason, payload):
    try:
        body = json.dumps(_sanitize(payload), ensure_ascii=False).encode('utf-8')
    except Exception:
        # Последний рубеж: пусть ответ будет уродливым, но дойдёт.
        body = json.dumps({'ok': False,
                           'error': 'ответ не удалось собрать: ' + repr(payload)[:2000]},
                          ensure_ascii=True).encode('utf-8')
    head = (
        'HTTP/1.1 %d %s\r\n'
        'Content-Type: application/json; charset=utf-8\r\n'
        'Content-Length: %d\r\n'
        'Connection: close\r\n'
        '\r\n' % (code, reason, len(body))
    )
    return head.encode('ascii') + body


def _parse_request(data):
    """Разбирает накопленный буфер. Возвращает None, если запрос ещё не целиком."""
    if b'\r\n\r\n' not in data:
        return None

    head, _, rest = data.partition(b'\r\n\r\n')
    lines = head.decode('latin-1').split('\r\n')
    request_line = lines[0]
    headers = {}
    for line in lines[1:]:
        if ':' in line:
            key, _, value = line.partition(':')
            headers[key.strip().lower()] = value.strip()

    length = int(headers.get('content-length', 0) or 0)
    if len(rest) < length:
        return None

    return request_line, headers, rest[:length]


def _handle_request(conn, request_line, headers, body):
    try:
        # На отправку переходим в блокирующий режим с коротким сроком:
        # ответы уходят на localhost и укладываются в миллисекунды.
        conn.setblocking(1)
        conn.settimeout(SEND_TIMEOUT)

        parts = request_line.split()
        method = parts[0] if parts else ''
        path = parts[1] if len(parts) > 1 else '/'

        if method == 'GET':
            if path.startswith('/health'):
                conn.sendall(_http_response(200, 'OK', {
                    'ok': True,
                    'bridge_version': BRIDGE_VERSION,
                    'pumps': _stats['pumps'],
                    'idle_events': _stats['idle_events'],
                    'render_events': _stats['render_events'],
                    'requests': _stats['requests'],
                    'seconds_since_pump': round(time.time() - _stats['last_pump_at'], 2)
                    if _stats['last_pump_at'] else None,
                }))
            else:
                conn.sendall(_http_response(404, 'Not Found',
                                            {'ok': False, 'error': 'not found'}))
            return

        if method != 'POST':
            conn.sendall(_http_response(405, 'Method Not Allowed',
                                        {'ok': False, 'error': 'only GET and POST'}))
            return

        token = CONFIG.get('token') or ''
        if token and headers.get('x-bridge-token', '') != token:
            conn.sendall(_http_response(403, 'Forbidden',
                                        {'ok': False, 'error': u'неверный токен'}))
            return

        try:
            payload = json.loads(body.decode('utf-8') or '{}')
        except Exception:
            conn.sendall(_http_response(400, 'Bad Request',
                                        {'ok': False,
                                         'error': u'тело запроса не разобрано как JSON'}))
            return

        _stats['requests'] += 1
        name = payload.get('method')
        params = payload.get('params') or {}

        try:
            fn = HANDLERS.get(name)
            if fn is None:
                raise ValueError(u'неизвестный метод: %s' % name)
            result = fn(params)
            conn.sendall(_http_response(200, 'OK', {'ok': True, 'result': result}))
        except Exception:
            _stats['errors'] += 1
            conn.sendall(_http_response(200, 'OK',
                                        {'ok': False, 'error': traceback.format_exc()}))
    except socket.timeout:
        pass
    except Exception:
        try:
            log(u'сбой при обработке запроса:\n' + traceback.format_exc())
        except Exception:
            pass
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _accept_new():
    """Забирает все ожидающие соединения, ничего не блокируя."""
    while True:
        try:
            ready, _, _ = select.select([_listener], [], [], 0)
        except Exception:
            return
        if not ready:
            return
        try:
            conn, _addr = _listener.accept()
        except Exception:
            return
        conn.setblocking(0)
        _clients.append([conn, b'', time.time()])


def _service_clients():
    """Дочитывает запросы и отвечает на те, что пришли целиком."""
    now = time.time()

    for entry in list(_clients):
        conn, buf, born = entry
        closed = False

        try:
            ready, _, _ = select.select([conn], [], [], 0)
            if ready:
                chunk = conn.recv(65536)
                if chunk:
                    buf += chunk
                    entry[1] = buf
                else:
                    closed = True
        except socket.error:
            pass  # данных пока нет — вернёмся на следующей прокачке
        except Exception:
            closed = True

        if len(buf) > 8 * 1024 * 1024:
            closed = True

        parsed = None if closed else _parse_request(buf)

        if parsed is not None:
            _clients.remove(entry)
            request_line, headers, body = parsed
            _handle_request(conn, request_line, headers, body)
        elif closed or now - born > CONNECTION_TTL:
            _clients.remove(entry)
            try:
                conn.close()
            except Exception:
                pass


def _pump(*args):
    """
    Главный поток заглядывает в сокет.

    Вызывается только событием OnIdle самой R-Pro. Ничего не блокирует:
    если запрос пришёл не целиком, дочитаем его на следующей прокачке.
    """
    global _in_pump

    if _listener is None or _in_pump:
        return

    _in_pump = True
    try:
        _stats['pumps'] += 1
        _stats['last_pump_at'] = time.time()

        _finish_pending_reset()
        _accept_new()
        _service_clients()
    except Exception:
        try:
            log(u'сбой прокачки:\n' + traceback.format_exc())
        except Exception:
            pass
    finally:
        _in_pump = False


def _on_idle(*args):
    """Обработчик OnIdle. Считаем вызовы отдельно, чтобы знать, живо ли событие."""
    _stats['idle_events'] += 1
    if _stats['idle_events'] in (1, 50, 500):
        log(u'событие OnIdle сработало %d раз' % _stats['idle_events'])
    _pump()


def _on_render(*args):
    """Обработчик OnRender. Тоже со счётчиком."""
    _stats['render_events'] += 1
    if _stats['render_events'] in (1, 50, 500):
        log(u'событие OnRender сработало %d раз' % _stats['render_events'])
    _pump()
    _keep_render_alive()


def _keep_render_alive():
    """
    Поддерживает цепочку отрисовки: каждый кадр просит следующий.

    Зачем. OnRender — единственное живое событие, но R-Pro рисует только по
    необходимости: стоит пользователю убрать руки, кадры прекращаются, и мост
    перестаёт получать управление. Первый кадр программа рисует сама при
    запуске, дальше цепочку тянем мы.

    Ограничитель частоты здесь же страхует от рекурсии: если app.render()
    окажется синхронным, вложенный вызов упрётся в интервал и цепочка не уйдёт
    в глубину больше двух уровней.
    """
    if not CONFIG.get('keep_rendering', True):
        return

    # Пропускать кадры нельзя: следующий рождается только из запроса на
    # предыдущем. Стоит один раз промолчать — и цепочка обрывается насовсем.
    # Именно так её убивал прежний ограничитель: кадр приходит примерно через
    # 100 мс, а при 5 кадр/с интервал был 200 мс, и каждый кадр отбрасывался.
    #
    # Поэтому запрашиваем на каждом кадре, а частоту задаёт сама R-Pro
    # (около 10 кадр/с). Ограничитель остался лишь как аварийный тормоз и по
    # умолчанию выключен: осмысленные значения — только выше естественного
    # ритма программы, иначе цепочка снова оборвётся.
    interval = _render_interval()
    if interval > 0:
        now = time.time()
        if now - _stats['last_render_request'] < interval:
            return
        _stats['last_render_request'] = now
    else:
        _stats['last_render_request'] = time.time()

    _request_next_frame()


def _strategy_world_update():
    """
    Обновление 3D-мира — рабочий способ вызвать кадр.

    Найден перебором на живой программе (agent/tickhunt.py). Из пяти проверенных
    способов этот единственный подчиняется ограничителю частоты: при 10 кадр/с
    даёт ровно ~10 прокачек в секунду. Переключение вида и мигание видимостью
    тоже оживляют цепочку, но рисуют втрое-вчетверо чаще заданного и вдобавок
    трогают вид пользователя или его сцену.

    Внимание на разницу: работает обновление МИРА, а не симуляции.
    Simulation.update() кадра не порождает — на этом потерян день.
    """
    app.Simulation.World.update()


def _strategy_ao_contrast():
    """
    Подстройка контраста затенения на одну десятитысячную.

    Настройка отрисовки, а не данные сцены: ни компонентов, ни камеры не
    трогает и в планировку не сохраняется. Значение колеблется вокруг
    исходного, так что не уплывает. На проверке дало самый высокий темп.
    """
    step = 0.0001 if _stats['render_events'] % 2 else -0.0001
    app.AmbientOcclusionContrast = app.AmbientOcclusionContrast + step


def _strategy_render():
    """Прямая просьба отрисовать сцену. На живой R-Pro кадра не даёт."""
    app.render()


def _strategy_sim_update():
    """Обновление симуляции. На живой R-Pro кадра не даёт, оставлено для истории."""
    app.Simulation.update()


def _strategy_view():
    """Переключение на текущий вид. Кадры даёт, но мимо ограничителя частоты."""
    views = app.Views
    if views:
        app.useView(views[0])


def _strategy_camera():
    """
    Незаметное шевеление камеры.

    Присвоение того же самого значения программа вправе отбросить как
    бессмысленное, поэтому камера смещается на одну миллионную миллиметра
    и на следующем кадре возвращается обратно. Глазу это недоступно, а вид
    обязан считать себя устаревшим.
    """
    camera = app.findCamera()
    if camera is None:
        return
    delta = 1e-6 if _stats['render_events'] % 2 else -1e-6
    matrix = camera.Matrix
    matrix.translateRel(delta, 0.0, 0.0)
    camera.Matrix = matrix


# Набор проверен на живой R-Pro. По умолчанию включён только world_update;
# остальные оставлены, чтобы их можно было включить в bridge.json, если в
# другой версии программы поведение окажется иным.
RENDER_STRATEGIES = (
    ('ao_contrast', _strategy_ao_contrast),
    ('camera', _strategy_camera),
    ('world_update', _strategy_world_update),
    ('view', _strategy_view),
    ('render', _strategy_render),
    ('sim_update', _strategy_sim_update),
)


def _request_next_frame():
    """
    Просит следующий кадр, перебирая способы до первого удачного.

    Порядок важен и выстрадан журналом кадров на живой программе:

    * ao_contrast — самый безобидный, но при запуске приложения свойство ещё
      не готово и вызов падает;
    * camera — страхует этот промежуток: сдвиг на сотую миллиметра работает
      с первого кадра;
    * world_update — на запуске даёт ровно один кадр (миру больше нечего
      обновлять), поэтому в одиночку цепочку не держит и стоит последним.

    Перебор идёт до первого способа, отработавшего без ошибки: так в обычной
    работе камера остаётся нетронутой.
    """
    allowed = CONFIG.get('render_strategies') or [n for n, _ in RENDER_STRATEGIES]
    done = []
    for name, fn in RENDER_STRATEGIES:
        if name not in allowed:
            continue
        try:
            fn()
            done.append(name)
            break
        except Exception:
            _stats.setdefault('render_strategy_errors', {})[name] = \
                traceback.format_exc().splitlines()[-1]
            done.append(name + ': сбой')

    # Разбор запуска цепочки: первые кадры пишем в панель вывода со временем.
    # Видно, приходит ли следующий кадр после нашего запроса и с какой задержкой.
    if CONFIG.get('trace_frames') and _stats['render_events'] <= int(CONFIG['trace_frames']):
        previous = _stats.get('trace_last_at') or _stats['started_at']
        now = time.time()
        _stats['trace_last_at'] = now
        log(u'кадр %d, пауза %.3f c, запрошено: %s'
            % (_stats['render_events'], now - previous, u', '.join(done) or u'ничего'))


def _render_interval():
    """Интервал между запросами кадра. Ноль — не ограничивать (по умолчанию)."""
    try:
        fps = float(CONFIG.get('render_fps', 0))
    except Exception:
        fps = 0.0
    if fps <= 0:
        return 0.0
    return 1.0 / fps


# ---------------------------------------------------------------------------
# Запуск и остановка
# ---------------------------------------------------------------------------

def start_bridge():
    global _listener

    if _listener is not None:
        log(u'мост уже запущен на %s:%s' % (CONFIG['host'], CONFIG['port']))
        return

    # Аварийный выключатель: положите рядом файл bridge.disabled, и мост
    # не станет подниматься. Пригодится, если он начнёт мешать работе.
    if os.path.isfile(os.path.join(_script_dir(), 'bridge.disabled')):
        log(u'выключен файлом bridge.disabled')
        return

    try:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((CONFIG['host'], int(CONFIG['port'])))
        srv.listen(16)
        srv.setblocking(0)
    except socket.error:
        log(u'не удалось занять порт %s — вероятно, мост уже работает в другом окне R-Pro'
            % CONFIG['port'])
        return

    _listener = srv

    # Управление к нам приходит только через события самой R-Pro: в главном
    # потоке и законным путём. Ни своих потоков, ни системных таймеров.
    # Каждое событие включается отдельно, чтобы подозрительное можно было
    # выключить в bridge.json без правки кода.
    sources = []
    if CONFIG.get('pump_on_idle', True):
        app.OnIdle = _on_idle
        sources.append('OnIdle')
    if CONFIG.get('pump_on_render', True):
        app.OnRender = _on_render
        sources.append('OnRender')

    log(u'запущен на http://%s:%s (методов: %d, версия %s)'
        % (CONFIG['host'], CONFIG['port'], len(HANDLERS), BRIDGE_VERSION))
    log(u'источники тика: %s' % (', '.join(sources) if sources else u'нет ни одного!'))
    if CONFIG.get('keep_rendering', True):
        fps = float(CONFIG.get('render_fps', 0))
        log(u'цепочка отрисовки поддерживается, частота: %s'
            % (u'задаёт R-Pro' if fps <= 0 else u'не чаще %g кадр/с' % fps))
        # Просим первый кадр: дальше цепочка тянет сама себя.
        _request_next_frame()
        errors = _stats.get('render_strategy_errors') or {}
        for name in sorted(errors):
            log(u'способ %s дал сбой: %s' % (name, errors[name]))


def stop_bridge():
    global _listener

    for entry in list(_clients):
        try:
            entry[0].close()
        except Exception:
            pass
    del _clients[:]

    if _listener is not None:
        try:
            _listener.close()
        except Exception:
            pass
        _listener = None
        log(u'остановлен')


def OnStart():
    start_bridge()


def OnStop():
    # Команда может завершаться, а мост должен жить всё время работы R-Pro.
    pass


# Если файл выполнили повторно (например, кнопкой на ленте), просто поднимаем мост.
start_bridge()
