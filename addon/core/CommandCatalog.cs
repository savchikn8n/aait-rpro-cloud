// Команды агента для подсказки над полем ввода: набрали «/» — всплывает
// список, как в терминальных агентах.
//
// Список приходит с сервера агента (GET /commands, agent/intents.py COMMANDS),
// чтобы панель не отставала от агента. Пока сервер не ответил или он старый,
// работает встроенная копия.

using System;
using System.Collections.Generic;

using Newtonsoft.Json.Linq;

namespace RProAiBridge
{
    public class CommandInfo
    {
        public string Name { get; set; }
        public string Args { get; set; }
        public string Description { get; set; }
        public string Group { get; set; }

        /// <summary>Аргументы есть, хотя бы необязательные: «[минуты]».</summary>
        public bool HasArgs
        {
            get { return !string.IsNullOrEmpty(Args); }
        }

        /// <summary>Без аргумента команда не имеет смысла: «/справка &lt;вопрос&gt;».</summary>
        public bool RequiresArgs
        {
            get { return HasArgs && Args.StartsWith("<"); }
        }
    }

    public static class CommandCatalog
    {
        private static List<CommandInfo> _items = Defaults();

        public static IList<CommandInfo> Items
        {
            get { return _items; }
        }

        private static List<CommandInfo> Defaults()
        {
            return new List<CommandInfo>
            {
                C("/справка", "<вопрос>", "короткий ответ по шагам: как сделать, что такое", "Справка"),
                C("/проблема", "<что случилось>", "проверенные ответы на частые неполадки", "Справка"),
                C("/термин", "<слово>", "английское название ↔ русская кнопка R-Pro", "Справка"),
                C("/api", "<имя>", "класс или метод Python API R-Pro", "Справка"),
                C("/совет", "<тема>", "советы из уроков Academy", "Справка"),
                C("/состояние", "", "что открыто, сколько компонентов, симуляция, выделение", "Сцена"),
                C("/сцена", "", "состав сцены: компоненты или построенные линии", "Сцена"),
                C("/ошибки", "", "ошибки и предупреждения из панели вывода", "Сцена"),
                C("/каталог", "<что найти>", "поиск модели в каталоге R-Pro", "Сцена"),
                C("/снимок", "[вопрос]", "снимок окна и описание моделью зрения", "Сцена"),
                C("/габариты", "", "площадь под оборудованием (м²), этажи, высоты", "Сцена"),
                C("/где", "<что>", "найти пост, робота или лифт и показать камерой", "Сцена"),
                C("/симуляция", "<минуты>", "запустить симуляцию на N минут", "Сцена"),
                C("/отчёт", "[минуты]", "выпуск, брак, узкое место", "Сцена"),
                C("/оптимизация", "[проверка]", "убрать лишнее, сжать площадь: было → стало", "Сцена"),
                C("/домой", "", "роботы возвращаются «Домой» между заданиями", "Сцена"),
                C("/сброс", "", "начать разговор заново", "Разговор"),
                C("/помощь", "", "список команд", "Разговор")
            };
        }

        private static CommandInfo C(string name, string args, string description, string group)
        {
            return new CommandInfo { Name = name, Args = args, Description = description, Group = group };
        }

        /// <summary>Список с сервера агента. Пустой или кривой — остаётся прежний.</summary>
        public static void Update(JArray commands)
        {
            if (commands == null || commands.Count == 0)
            {
                return;
            }
            List<CommandInfo> fresh = new List<CommandInfo>();
            foreach (JToken c in commands)
            {
                string name = (string)c["name"];
                if (string.IsNullOrEmpty(name) || !name.StartsWith("/"))
                {
                    continue;
                }
                fresh.Add(C(name, (string)c["args"] ?? string.Empty,
                            (string)c["description"] ?? string.Empty, (string)c["group"] ?? string.Empty));
            }
            if (fresh.Count > 0)
            {
                _items = fresh;
            }
        }

        /// <summary>Команды, начинающиеся с набранного («/сп» → /справка). Ё и Е не различаем.</summary>
        public static List<CommandInfo> Filter(string typed)
        {
            string t = Normalize(typed);
            List<CommandInfo> found = new List<CommandInfo>();
            foreach (CommandInfo c in _items)
            {
                if (Normalize(c.Name).StartsWith(t, StringComparison.Ordinal))
                {
                    found.Add(c);
                }
            }
            return found;
        }

        private static string Normalize(string s)
        {
            return (s ?? string.Empty).Trim().ToLowerInvariant().Replace('ё', 'е');
        }
    }
}
