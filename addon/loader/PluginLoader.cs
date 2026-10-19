// Загрузчик ИИ-агента для R-Pro.
//
// Зачем он нужен
// --------------
// R-Pro подхватывает плагины только из своей папки в Program Files, а писать
// туда можно лишь с правами администратора. Файл к тому же занят, пока
// программа открыта. Если класть туда весь плагин, каждое обновление
// превращается в «закройте R-Pro и позовите администратора».
//
// Поэтому в папке программы лежит только этот загрузчик. Он почти никогда не
// меняется. Настоящий плагин — ядро (AiBridge.Core.dll) — живёт в профиле
// пользователя, в папке своей версии. Путь к нему установщик записывает в
// реестр: HKCU\Software\AAIT\RProAgent, значение CorePath. Новая версия
// ставится в соседнюю папку, пока R-Pro открыта, и подхватывается при
// следующем запуске — без прав администратора и без занятых файлов.
//
// Как отдаём ядро в R-Pro
// -----------------------
// R-Pro собирает плагины через MEF: ищет экспорты IPlugin и IDockableScreen
// в сборках из своей папки. Ядро в эту папку не попадает, поэтому загрузчик
// экспортирует не классы, а свойства: MEF спрашивает у него IPlugin и панель,
// а он создаёт их из ядра. Сами классы ядра об этом не знают и устроены так
// же, как когда жили в папке программы.
//
// Ядро не найдено или не загрузилось — R-Pro всё равно должна запуститься.
// Тогда вместо тикера работает заглушка, которая пишет причину в панель
// вывода, а вместо чата — панель с той же причиной.

using System;
using System.ComponentModel.Composition;
using System.IO;
using System.Reflection;
using System.Windows;
using System.Windows.Controls;

using Microsoft.Win32;

using RProSoftDigital1.Create3D;
using RProSoftDigital1.UX.Shared;

namespace RProAiBridge.Loader
{
    [PartCreationPolicy(CreationPolicy.Shared)]
    public class PluginLoader
    {
        private const string RegistryKey = @"Software\AAIT\RProAgent";

        private readonly IMessageService _messageService;
        private readonly IRenderService _renderService;

        private Assembly _core;
        private string _problem;
        private bool _loaded;

        private IPlugin _plugin;
        private IDockableScreen _panel;

        [ImportingConstructor]
        public PluginLoader(IMessageService messageService, IRenderService renderService)
        {
            _messageService = messageService;
            _renderService = renderService;
        }

        [Export(typeof(IPlugin))]
        public IPlugin Plugin
        {
            get
            {
                if (_plugin == null)
                {
                    _plugin = Create<IPlugin>("RProAiBridge.AiBridgeTicker",
                        _messageService, _renderService)
                        ?? new MissingCorePlugin(_messageService, _problem);
                }
                return _plugin;
            }
        }

        [Export(typeof(IDockableScreen))]
        public IDockableScreen Panel
        {
            get
            {
                if (_panel == null)
                {
                    _panel = Create<IDockableScreen>("RProAiBridge.ChatPanelViewModel")
                        ?? new MissingCorePanelViewModel(_problem);
                }
                return _panel;
            }
        }

        private T Create<T>(string typeName, params object[] arguments) where T : class
        {
            try
            {
                Assembly core = LoadCore();
                if (core == null)
                {
                    return null;
                }
                Type type = core.GetType(typeName, true);
                return (T)Activator.CreateInstance(type, arguments);
            }
            catch (Exception error)
            {
                TargetInvocationException wrapped = error as TargetInvocationException;
                Exception cause = wrapped != null && wrapped.InnerException != null
                    ? wrapped.InnerException
                    : error;
                _problem = "не удалось создать " + typeName + ": " + cause.Message;
                return null;
            }
        }

        private Assembly LoadCore()
        {
            if (_loaded)
            {
                return _core;
            }
            _loaded = true;

            string path = ReadCorePath();
            if (string.IsNullOrWhiteSpace(path))
            {
                _problem = "ИИ-агент не установлен: в реестре нет пути к ядру. " +
                           "Запустите установщик ИИ-агента ещё раз.";
                return null;
            }
            if (!File.Exists(path))
            {
                _problem = "ИИ-агент повреждён: не найдено ядро " + path +
                           ". Запустите установщик ИИ-агента ещё раз.";
                return null;
            }

            try
            {
                _core = Assembly.LoadFrom(path);
            }
            catch (Exception error)
            {
                _problem = "не удалось загрузить ядро " + path + ": " + error.Message;
                return null;
            }

            try
            {
                // Caliburn.Micro ищет разметку панели по имени только в
                // известных ему сборках. Добавить ядро нужно до того, как
                // R-Pro покажет панель, а это может случиться раньше, чем
                // плагину скажут Initialize.
                Caliburn.Micro.AssemblySource.Instance.Add(_core);
            }
            catch
            {
                // Ядро само повторит это в Initialize и скажет, если не выйдет.
            }
            return _core;
        }

        private static string ReadCorePath()
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegistryKey))
                {
                    return key == null ? null : key.GetValue("CorePath") as string;
                }
            }
            catch
            {
                return null;
            }
        }
    }

    /// <summary>Заменяет тикер, если ядро не загрузилось: объясняет почему.</summary>
    internal class MissingCorePlugin : IPlugin
    {
        private readonly IMessageService _messageService;
        private readonly string _problem;

        public MissingCorePlugin(IMessageService messageService, string problem)
        {
            _messageService = messageService;
            _problem = problem ?? "ядро ИИ-агента не загрузилось";
        }

        public void Initialize()
        {
            try
            {
                if (_messageService != null)
                {
                    _messageService.AppendMessage("[ИИ-мост] " + _problem, MessageLevel.Warning);
                }
            }
            catch
            {
                // Панель вывода может быть не готова. Это не повод мешать запуску.
            }
        }

        public void Exit()
        {
        }
    }

    /// <summary>Панель на месте чата, если ядро не загрузилось.</summary>
    public class MissingCorePanelViewModel : DockableScreen
    {
        public MissingCorePanelViewModel(string problem)
        {
            DisplayName = "ИИ-агент";
            PanelId = "AiAgentChatPanel";
            PaneLocation = DesiredPaneLocation.DockedRight;
            PaneOrientation = Orientation.Vertical;
            Width = 400;
            Height = 900;
            IsVisible = true;
            IsPinned = true;
            Problem = problem ?? "ядро ИИ-агента не загрузилось";

            try
            {
                Caliburn.Micro.AssemblySource.Instance.Add(typeof(MissingCorePanelViewModel).Assembly);
            }
            catch
            {
            }
        }

        public string Problem { get; private set; }
    }

    /// <summary>Разметка заглушки. Caliburn.Micro находит её по имени.</summary>
    public class MissingCorePanelView : UserControl
    {
        public MissingCorePanelView()
        {
            TextBlock text = new TextBlock
            {
                Margin = new Thickness(12),
                TextWrapping = TextWrapping.Wrap
            };
            text.SetBinding(TextBlock.TextProperty, "Problem");
            Content = text;
        }
    }
}
