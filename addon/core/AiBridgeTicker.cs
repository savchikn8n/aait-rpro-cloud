// Тикер для ИИ-моста R-Pro.
//
// Зачем он нужен
// --------------
// Python-мост получает управление только в момент отрисовки 3D-вида, а R-Pro
// рисует исключительно по действиям пользователя. Изнутри Python вызвать кадр
// не удалось ничем: у vcApplication нет доступа к службе отрисовки, а все
// косвенные приёмы (обновление мира, сдвиг камеры, перерисовка окна средствами
// Windows) кадра не порождают. Подробности — в docs/05-problema-tika.md.
//
// В .NET-части такая служба есть: IRenderService.RequestRender(). Этот плагин
// по таймеру WPF просит кадр, чем и оживляет мост. Конструкция не выдумана —
// ровно так устроен штатный плагин R-Pro AutosaveAgent: тот же интерфейс
// IPlugin, тот же ImportingConstructor со службой отрисовки, тот же
// DispatcherTimer.
//
// Плагин намеренно крошечный: никакой логики агента здесь нет и не будет, она
// живёт в Python-мосте и во внешнем процессе. Здесь только тик.

using System;
using System.Globalization;
using System.IO;
using System.Windows.Threading;

using RProSoftDigital1.Create3D;
using RProSoftDigital1.UX.Shared;

namespace RProAiBridge
{
    // Экспорта здесь нет: ядро лежит вне папки R-Pro, и в программу его
    // отдаёт загрузчик (addon/loader/PluginLoader.cs).
    public class AiBridgeTicker : IPlugin
    {
        private const int DefaultIntervalMs = 100;
        private const int MinIntervalMs = 20;
        private const int MaxIntervalMs = 5000;

        private readonly IMessageService _messageService;
        private readonly IRenderService _renderService;
        private DispatcherTimer _timer;

        public AiBridgeTicker(IMessageService messageService, IRenderService renderService)
        {
            _messageService = messageService;
            _renderService = renderService;
        }

        /// <summary>
        /// Папка настроек тикера. Лежит в профиле пользователя, а не в папке
        /// программы, чтобы отключать тикер можно было без прав администратора.
        /// </summary>
        private static string SettingsFolder
        {
            get
            {
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return Path.Combine(local, "R-Pro", "AIAgentBridge");
            }
        }

        private static string DisableFlagPath
        {
            get { return Path.Combine(SettingsFolder, "ticker.disabled"); }
        }

        private static string IntervalFilePath
        {
            get { return Path.Combine(SettingsFolder, "ticker.interval"); }
        }

        /// <summary>
        /// Интервал между кадрами в миллисекундах. Берётся из файла
        /// ticker.interval, если он есть; иначе сто миллисекунд.
        /// </summary>
        private static int ReadIntervalMs()
        {
            try
            {
                if (File.Exists(IntervalFilePath))
                {
                    string text = File.ReadAllText(IntervalFilePath).Trim();
                    int value;
                    if (int.TryParse(text, NumberStyles.Integer, CultureInfo.InvariantCulture, out value))
                    {
                        if (value < MinIntervalMs) return MinIntervalMs;
                        if (value > MaxIntervalMs) return MaxIntervalMs;
                        return value;
                    }
                }
            }
            catch
            {
                // Настройки — дело десятое: не читаются, работаем со значением по умолчанию.
            }
            return DefaultIntervalMs;
        }

        private void Say(string message)
        {
            try
            {
                if (_messageService != null)
                {
                    _messageService.AppendMessage("[ИИ-мост] " + message, MessageLevel.Info);
                }
            }
            catch
            {
                // Панель вывода может быть ещё не готова. Это не повод падать.
            }
        }

        public void Initialize()
        {
            // Любая ошибка здесь не должна мешать запуску R-Pro, поэтому весь
            // метод под защитой: в худшем случае тикера просто не будет.
            Say("ИИ-агент " + Installation.Version);

            try
            {
                // Без этой строки Caliburn.Micro не найдёт разметку панели чата:
                // он ищет вид по имени только в известных ему сборках, а наша
                // в этот список сама не попадает.
                // Загрузчик обычно успевает раньше, второй раз не добавляем.
                System.Reflection.Assembly core = typeof(AiBridgeTicker).Assembly;
                if (!Caliburn.Micro.AssemblySource.Instance.Contains(core))
                {
                    Caliburn.Micro.AssemblySource.Instance.Add(core);
                }
            }
            catch (Exception error)
            {
                Say("панель чата может не открыться: " + error.Message);
            }

            // Сервер агента поднимаем до тикера: тикер можно выключить, а
            // окну чата агент нужен всё равно.
            try
            {
                string started = AgentLauncher.Start();
                if (started != null)
                {
                    Say(started);
                }
            }
            catch (Exception error)
            {
                Say("агент не запустился: " + error.Message);
            }

            try
            {
                if (File.Exists(DisableFlagPath))
                {
                    Say("тикер выключен файлом ticker.disabled");
                    return;
                }

                if (_renderService == null)
                {
                    Say("тикер не запущен: служба отрисовки недоступна");
                    return;
                }

                int intervalMs = ReadIntervalMs();

                _timer = new DispatcherTimer(DispatcherPriority.Background);
                _timer.Interval = TimeSpan.FromMilliseconds(intervalMs);
                _timer.Tick += OnTick;
                _timer.Start();

                Say(string.Format(CultureInfo.InvariantCulture,
                    "тикер запущен: кадр каждые {0} мс", intervalMs));
            }
            catch (Exception error)
            {
                Say("тикер не запустился: " + error.Message);
            }
        }

        private void OnTick(object sender, EventArgs e)
        {
            try
            {
                _renderService.RequestRender();
            }
            catch
            {
                // Один неудачный кадр ничего не решает, следующий придёт через
                // интервал. Сыпать сообщениями в панель вывода незачем.
            }
        }

        public void Exit()
        {
            AgentLauncher.Stop();

            try
            {
                if (_timer != null)
                {
                    _timer.Stop();
                    _timer.Tick -= OnTick;
                    _timer = null;
                }
            }
            catch
            {
                // Программа и так закрывается.
            }
        }
    }
}
