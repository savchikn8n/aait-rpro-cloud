# -*- coding: utf-8 -*-
"""
Регистрация ИИ-моста в R-Pro.

Файл выполняется самой R-Pro при запуске приложения (механизм Python Add-on).
Задачи:
  1. зарегистрировать команду "aiAgentBridge" из файла bridge_command.py;
  2. положить кнопку запуска на ленту (вкладка "Главная", группа инструментов);
  3. при AUTOSTART = True сразу выполнить команду, чтобы мост поднялся
     без участия пользователя.

Python внутри R-Pro — версия 2.7, поэтому синтаксис здесь строго py2.
"""

from vcApplication import *

CMD_NAME = 'aiAgentBridge'
CMD_TITLE = 'ИИ-мост'
MENU_PATH = 'VcTabHome/VcRibbonTools'

# Поднимать мост автоматически при старте R-Pro.
# Если поставить False, мост будет запускаться только кнопкой на ленте.
AUTOSTART = True


def OnAppInitialized():
    cmd = findCommand(CMD_NAME)
    if cmd is None:
        cmd = loadCommand(CMD_NAME, getApplicationPath() + 'bridge_command.py')

    if cmd is None:
        print('[ИИ-мост] не удалось загрузить bridge_command.py')
        return

    addMenuItem(MENU_PATH, CMD_TITLE, -1, CMD_NAME)

    if AUTOSTART:
        try:
            cmd.execute()
        except Exception:
            import traceback
            print('[ИИ-мост] автозапуск не удался:\n' + traceback.format_exc())
