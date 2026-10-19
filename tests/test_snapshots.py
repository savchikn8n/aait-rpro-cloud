# -*- coding: utf-8 -*-
"""Офлайн-проверка автосохранения, отката и «сначала осмотр» на заглушках (без R-Pro и модели).
Запуск: python tests/test_snapshots.py"""
import json, os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "agent"))
os.environ["RPRO_SNAPSHOT_DIR"] = tempfile.mkdtemp()
os.environ["RPRO_SNAPSHOT_KEEP"] = "3"

import snapshots, intents, chat, tools, llm


class Fake:
    """Мост-заглушка: «сцена» — число компонентов; save пишет файл, open читает его обратно."""
    def __init__(self): self.n, self.uri, self.calls, self.save_as = 5, "file:///C:/p/my.rpro", [], False
    def status(self): return {"component_count": self.n, "layout_uri": self.uri, "layout_modified": True}
    def layout(self, action, uri=""):
        self.calls.append((action, uri))
        path = uri.replace("file:///", "")
        if action == "save":
            open(path, "w").write(str(self.n))
            if self.save_as: self.uri = uri
        elif action == "open":
            self.n = int(open(path).read()); self.uri = uri
        return {"ok": True, "layout_uri": self.uri}


fake = Fake(); tools.client = fake

# --- автосохранение и откат ---
assert "нет" in snapshots.rollback_text(fake) or "не к чему" in snapshots.rollback_text(fake)
e1 = snapshots.take(fake, "перед правкой"); fake.n = 9                       # агент «испортил» сцену
assert "warning" not in e1
out = intents.handle("Откатись до последнего автосохранения")
assert "возвращена" in out and fake.n == 5, (out, fake.n)
assert [a for a, _ in fake.calls].count("open") == 1
out2 = intents.handle("откатись")                                            # откат откатывается обратно
assert fake.n == 9, fake.n
assert snapshots.ROLLBACK.match("верни как было") and snapshots.ROLLBACK.match("отмени последние изменения")
assert not snapshots.ROLLBACK.match("верни робота домой") and not snapshots.ROLLBACK.match("что в сцене")
assert "Автосохранения" in intents.handle("/автосохранение")
assert "сохранена" in intents.handle("/сохрани перед стрелкой")
for i in range(6): snapshots.take(fake, f"x{i}")
assert len(snapshots.entries()) == 3 and len(os.listdir(snapshots.folder())) == 4   # 3 копии + index.json
fake.save_as = True
assert "warning" in snapshots.take(fake, "save-as")                          # «Сохранить как» замечено

# --- цикл агента: осмотр → автосохранение → правка; запрет очистки ---
ran, script = [], []
def fake_run(name, args):
    ran.append((name, args))
    return json.dumps({"ok": True, "tool": name})
tools.run_tool = fake_run
def fake_chat(messages, tools=None, model=None, timeout=0):
    return script.pop(0)
llm.chat = fake_chat
def call(name, args): return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": args}}]}
fin = lambda t: {"role": "assistant", "content": t}

fake.save_as = False; before = len(snapshots.entries()); fake.calls.clear(); ran.clear()
script[:] = [call("rpro_set_property", {"component": "Конвейер 1", "prop": "ConveyorSpeed", "value": 300}),
             call("rpro_set_property", {"component": "Конвейер 1", "prop": "ConveyorSpeed", "value": 300}),
             fin("Скорость 300 поставил.")]
msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "поставь скорость конвейера 1 на 300"}]
answer = chat._loop(msgs)
names = [n for n, _ in ran]
assert names[:3] == ["rpro_status", "rpro_scene", "rpro_messages"], names          # сначала осмотр кодом
assert names.count("rpro_set_property") == 1 and names.index("rpro_set_property") > 2   # правка — после осмотра
assert [a for a, _ in fake.calls] == ["save"], fake.calls                              # одно автосохранение перед правкой
assert "откатись" in answer and "Скорость 300" in answer, answer

# если модель сама осмотрела сцену — отдельный осмотр кодом не нужен, автосохранение — всё равно
ran.clear(); fake.calls.clear()
script[:] = [call("rpro_scene", {}), call("rpro_set_property", {"component": "a", "prop": "b", "value": 1}), fin("ок")]
chat._loop([{"role": "system", "content": "s"}, {"role": "user", "content": "поставь свойство b у a в 1"}])
assert [n for n, _ in ran] == ["rpro_scene", "rpro_set_property"] and [a for a, _ in fake.calls] == ["save"]

# вопрос: ничего не меняется и копий нет
ran.clear(); fake.calls.clear()
script[:] = [call("rpro_scene", {}), fin("Там 5 компонентов.")]
chat._loop([{"role": "system", "content": "s"}, {"role": "user", "content": "что сейчас в сцене?"}])
assert not fake.calls

# rpro_exec с очисткой сцены — отказ, ничего не выполнено и копии нет
for bad in ("app.clearWorld()", "loadLayout('x.rpro')", "for c in app.Components:\n    c.delete()"):
    ran.clear(); fake.calls.clear()
    script[:] = [call("rpro_scene", {}), call("rpro_exec", {"code": bad}), fin("Не стал стирать сцену.")]
    chat._loop([{"role": "system", "content": "s"}, {"role": "user", "content": "пересобери сцену заново, сотри всё"}])
    assert "rpro_exec" not in [n for n, _ in ran], (bad, ran)
# точечное удаление названного компонента разрешено
ran.clear()
script[:] = [call("rpro_scene", {}), call("rpro_exec", {"code": "app.findComponent('Робот 2').delete()"}), fin("Удалил Робот 2.")]
chat._loop([{"role": "system", "content": "s"}, {"role": "user", "content": "удали Робот 2"}])
assert "rpro_exec" in [n for n, _ in ran]
print("OK: автосохранение, откат, осмотр перед правкой, запрет очистки сцены")
