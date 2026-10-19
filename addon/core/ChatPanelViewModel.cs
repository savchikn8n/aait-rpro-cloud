// Окно чата с ИИ-агентом внутри R-Pro.
//
// Панель намеренно тонкая: она рисует переписку и отправляет вопросы агенту,
// который живёт отдельным процессом на Python (agent/serve.py). Там же
// остаётся работа с моделью, инструментами и историей разговора. Причина
// та же, что и у моста: внутри R-Pro живёт Python 2.7, современные
// библиотеки туда не поставить, а падение внешнего процесса не должно
// мешать инженеру работать.
//
// Устройство панели повторяет штатные панели R-Pro: наследник DockableScreen
// с экспортом IDockableScreen — ровно так сделаны каталог и редактор
// компонентов.

using System;
using System.Collections.ObjectModel;
using System.Diagnostics;
using System.IO;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;

using Newtonsoft.Json.Linq;

using RProSoftDigital1.UX.Shared;

namespace RProAiBridge
{
    /// <summary>Одна реплика в переписке.</summary>
    public class ChatMessage : System.ComponentModel.INotifyPropertyChanged
    {
        public event System.ComponentModel.PropertyChangedEventHandler PropertyChanged;

        private string _status = string.Empty;

        /// <summary>
        /// Что агент делает прямо сейчас («смотрю список компонентов…») — строка
        /// под точками в пузыре ожидания. Временная, как размышление: приходит
        /// ответ — пузырь вместе с ней уходит, в переписке остаётся только ответ.
        /// </summary>
        public string Status
        {
            get { return _status; }
            set
            {
                if (_status == value) return;
                _status = value ?? string.Empty;
                System.ComponentModel.PropertyChangedEventHandler handler = PropertyChanged;
                if (handler != null)
                {
                    handler(this, new System.ComponentModel.PropertyChangedEventArgs("Status"));
                }
            }
        }

        public string Author { get; set; }
        public string Text { get; set; }
        public bool IsAgent { get; set; }
        public bool IsService { get; set; }

        /// <summary>
        /// Ответ ещё готовится. В таком бабле вместо текста мигают три точки —
        /// как в мессенджерах, сразу под вопросом.
        /// </summary>
        public bool IsPending { get; set; }

        /// <summary>
        /// Оформленный текст реплики (MarkdownLite). Каждый раз новый элемент:
        /// один элемент WPF не может стоять в двух местах дерева, а шаблон
        /// списка вправе создать контейнер заново.
        /// </summary>
        public object Body
        {
            get { return MarkdownLite.Build(Text, IsAgent || IsService); }
        }
    }

    // Экспорт делает загрузчик (addon/loader/PluginLoader.cs), см. тикер.
    public class ChatPanelViewModel : DockableScreen
    {
        private static readonly HttpClient Http = new HttpClient
        {
            // Обычный ответ укладывается в десятки секунд. Запас нужен на
            // редкие тяжёлые случаи: разбор снимка окна моделью зрения или
            // несколько подряд обращений к R-Pro за фактами.
            Timeout = TimeSpan.FromMinutes(5)
        };

        private string _input = string.Empty;
        private bool _isBusy;

        public ChatPanelViewModel()
        {
            DisplayName = "ИИ-агент";
            PanelId = "AiAgentChatPanel";
            PaneLocation = DesiredPaneLocation.DockedRight;
            PaneOrientation = Orientation.Vertical;
            Width = 400;
            // Высота в разумных пределах. Ставить сюда «с запасом» нельзя:
            // при огромном значении хозяин панели отдаёт содержимому высоту
            // больше экрана, и низ разметки — поле ввода — уезжает за край.
            Height = 900;
            IsVisible = true;
            IsPinned = true;

            Messages = new ObservableCollection<ChatMessage>();

            // Сервер агента запускается вместе с R-Pro и ещё грузит модель в
            // память. Пока он не готов, на месте приветствия мигают точки:
            // здороваться раньше — значит обещать ответ, который придёт через
            // минуту.
            _greeting = new ChatMessage
            {
                Author = "ИИ-агент",
                Text = string.Empty,
                IsAgent = true,
                IsPending = true
            };
            Messages.Add(_greeting);
            Task.Run(() => WaitForAgentAsync());
            Task.Run(() => CheckForUpdateAsync());
        }

        private static readonly string GreetingText =
            "Здравствуйте. Спросите меня о сцене, компонентах или симуляции." +
            Environment.NewLine +
            "Наберите «/» — появится список команд; например, /справка как собрать конвейерную линию." +
            Environment.NewLine +
            "Отзыв о моей работе можно оставить по ссылке внизу панели.";

        private ChatMessage _greeting;

        /// <summary>
        /// Ждёт, пока сервер агента поднимется и загрузит модель, и тогда
        /// здоровается. Если агент долго не отвечает — объясняет, что делать,
        /// но ждать не перестаёт: его могут запустить и руками.
        /// </summary>
        private async Task WaitForAgentAsync()
        {
            DateTime started = DateTime.UtcNow;
            bool complained = false;

            while (DateTime.UtcNow - started < TimeSpan.FromMinutes(10))
            {
                JObject health = await TryHealthAsync().ConfigureAwait(false);
                string state = health != null ? (string)health["model_state"] : null;

                if (health != null)
                {
                    // Сервер жив — берём у него список команд для подсказки «/».
                    Task.Run(() => LoadCommandsAsync());
                }

                // Старый сервер не сообщает о модели — считаем, что готов.
                if (health != null && (state == null || state == "готова"))
                {
                    OnUi(() => Greet(GreetingText, null));
                    return;
                }
                if (state != null && state.StartsWith("ошибка"))
                {
                    // Сервер сам повторяет загрузку модели, поэтому панель не
                    // сдаётся: предупреждает один раз и ждёт, пока модель
                    // поднимется, чтобы сказать об этом.
                    string reason = state.Substring("ошибка".Length).TrimStart(':', ' ');
                    OnUi(() => Greet(GreetingText,
                        "Модель пока не загрузилась: " + reason));
                    await WaitForModelRecoveryAsync().ConfigureAwait(false);
                    return;
                }

                if (health == null && !complained &&
                    DateTime.UtcNow - started > TimeSpan.FromSeconds(30))
                {
                    complained = true;
                    OnUi(() => Notice(NotRunningHint()));
                }

                await Task.Delay(1000).ConfigureAwait(false);
            }

            OnUi(() => Greet(GreetingText, null));
        }

        /// <summary>
        /// После неудачного прогрева ждёт, пока сервер всё-таки поднимет
        /// модель (он повторяет сам), и сообщает, что можно спрашивать.
        /// </summary>
        private async Task WaitForModelRecoveryAsync()
        {
            DateTime started = DateTime.UtcNow;
            while (DateTime.UtcNow - started < TimeSpan.FromMinutes(30))
            {
                await Task.Delay(5000).ConfigureAwait(false);
                JObject health = await TryHealthAsync().ConfigureAwait(false);
                string state = health != null ? (string)health["model_state"] : null;
                if (state == "готова")
                {
                    OnUi(() => Notice("Модель загрузилась — можно спрашивать."));
                    // Сообщение о готовности временное: через несколько
                    // секунд уходит, в переписке не остаётся ни одного из двух.
                    await Task.Delay(TimeSpan.FromSeconds(8)).ConfigureAwait(false);
                    OnUi(() => ClearNotice());
                    return;
                }
            }
        }

        private bool _commandsLoaded;

        /// <summary>Список команд агента для подсказки над полем ввода.</summary>
        private async Task LoadCommandsAsync()
        {
            if (_commandsLoaded)
            {
                return;
            }
            _commandsLoaded = true;
            try
            {
                using (CancellationTokenSource timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8)))
                {
                    HttpResponseMessage response = await Http
                        .GetAsync(AgentUrl + "/commands", timeout.Token).ConfigureAwait(false);
                    if (!response.IsSuccessStatusCode)
                    {
                        return;   // старый сервер — остаётся встроенный список
                    }
                    JObject body = JObject.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                    JArray commands = body["commands"] as JArray;
                    OnUi(() => CommandCatalog.Update(commands));
                }
            }
            catch
            {
                // Нет ответа — работаем со встроенным списком.
            }
        }

        private async Task<JObject> TryHealthAsync()
        {
            try
            {
                using (CancellationTokenSource timeout = new CancellationTokenSource(TimeSpan.FromSeconds(8)))
                {
                    HttpResponseMessage response = await Http
                        .GetAsync(AgentUrl + "/health", timeout.Token).ConfigureAwait(false);
                    string body = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
                    return JObject.Parse(body);
                }
            }
            catch
            {
                return null;
            }
        }

        /// <summary>Меняет точки на приветствие, не сдвигая порядок реплик.</summary>
        private void Greet(string text, string warning)
        {
            int index = Messages.IndexOf(_greeting);
            ChatMessage greeting = new ChatMessage { Author = "ИИ-агент", Text = text, IsAgent = true };
            if (index >= 0)
            {
                Messages[index] = greeting;
            }
            else
            {
                Messages.Add(greeting);
            }
            _greeting = null;

            if (warning != null)
            {
                Notice(warning);
            }
            else
            {
                // Модель готова — снять «агент не запущен», если оно висело.
                ClearNotice();
            }
        }

        private ChatMessage _notice;

        /// <summary>
        /// Одна служебная строка о состоянии агента и модели («не запущен»,
        /// «модель пока не загрузилась», «загрузилась»). Новое состояние
        /// заменяет прежнее на том же месте, а не добавляется ниже: иначе в
        /// переписке оставались взаимоисключающие сообщения.
        /// </summary>
        private void Notice(string text)
        {
            ChatMessage notice = new ChatMessage { Author = "система", Text = text, IsService = true };
            int index = _notice != null ? Messages.IndexOf(_notice) : -1;
            if (index >= 0)
            {
                Messages[index] = notice;
            }
            else
            {
                Messages.Add(notice);
            }
            _notice = notice;
        }

        private void ClearNotice()
        {
            if (_notice != null)
            {
                Messages.Remove(_notice);
                _notice = null;
            }
        }

        private string NotRunningHint()
        {
            return "Агент не отвечает по адресу " + AgentUrl + "." + Environment.NewLine +
                   "Перезапустите R-Pro. Не помогло — запустите установщик ИИ-агента ещё раз." +
                   Environment.NewLine + "Журнал агента: " + AgentLauncher.LogPath;
        }

        private static void OnUi(Action action)
        {
            Application application = Application.Current;
            if (application != null)
            {
                application.Dispatcher.BeginInvoke(action);
            }
        }

        // --- страница проекта: отзывы и обновления ---------------------------

        /// <summary>
        /// Страница проекта. Там форма отзыва и latest.json — сведения о
        /// последней версии. Для проверки можно подменить переменной окружения.
        /// </summary>
        private static string SiteUrl
        {
            get
            {
                string fromEnv = Environment.GetEnvironmentVariable("RPRO_SITE_URL");
                return string.IsNullOrWhiteSpace(fromEnv)
                    ? "https://rpro.itc.kl.avtotor.ru/"
                    : fromEnv.TrimEnd('/') + "/";
            }
        }

        /// <summary>Открывает форму отзыва в браузере, сразу с версией агента.</summary>
        public void OpenFeedback()
        {
            string url = SiteUrl + "?v=" + Uri.EscapeDataString(Installation.Version) + "#feedback";
            try
            {
                Process.Start(new ProcessStartInfo(url) { UseShellExecute = true });
            }
            catch (Exception error)
            {
                Say("система", "Не удалось открыть браузер (" + error.Message + "). Форма отзыва: " + url, false, true);
            }
        }

        /// <summary>Куда скачиваются установщики обновлений.</summary>
        private static string UpdatesFolder
        {
            get
            {
                return Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "R-Pro", "AIAgentBridge", "updates");
            }
        }

        private JObject _latest;
        private string _updateText = string.Empty;
        private string _updateButtonText = "Обновить";
        private bool _isUpdateVisible;
        private bool _isUpdateButtonVisible = true;
        private bool _canUpdate;

        public string UpdateText
        {
            get { return _updateText; }
            set { _updateText = value; NotifyOfPropertyChange(() => UpdateText); }
        }

        public string UpdateButtonText
        {
            get { return _updateButtonText; }
            set { _updateButtonText = value; NotifyOfPropertyChange(() => UpdateButtonText); }
        }

        public bool IsUpdateVisible
        {
            get { return _isUpdateVisible; }
            set { _isUpdateVisible = value; NotifyOfPropertyChange(() => IsUpdateVisible); }
        }

        public bool IsUpdateButtonVisible
        {
            get { return _isUpdateButtonVisible; }
            set { _isUpdateButtonVisible = value; NotifyOfPropertyChange(() => IsUpdateButtonVisible); }
        }

        public bool CanUpdate
        {
            get { return _canUpdate; }
            set { _canUpdate = value; NotifyOfPropertyChange(() => CanUpdate); }
        }

        /// <summary>
        /// Смотрит latest.json на странице проекта и, если там версия новее,
        /// показывает плашку с кнопкой «Обновить». Молча ничего не делает, если
        /// сайт недоступен: без обновления агент работает как работал.
        /// </summary>
        private async Task CheckForUpdateAsync()
        {
            // Запущено из репозитория, а не установщиком — обновляется через git.
            if (Installation.Directory == null)
            {
                return;
            }

            // Установщики прошлых обновлений уже отработали: R-Pro снова
            // запущена, а ставятся они только после её закрытия. Тот, что
            // ещё ждёт, занят и не удалится — так и надо.
            try
            {
                foreach (string old in System.IO.Directory.GetFiles(UpdatesFolder, "*.exe"))
                {
                    try { File.Delete(old); } catch { }
                }
            }
            catch
            {
                // Папки ещё нет — убирать нечего.
            }

            // Не мешаем запуску R-Pro и загрузке модели.
            await Task.Delay(TimeSpan.FromSeconds(10)).ConfigureAwait(false);

            try
            {
                JObject latest;
                using (CancellationTokenSource timeout = new CancellationTokenSource(TimeSpan.FromSeconds(20)))
                {
                    HttpResponseMessage response = await Http
                        .GetAsync(SiteUrl + "latest.json", timeout.Token).ConfigureAwait(false);
                    if (!response.IsSuccessStatusCode)
                    {
                        return;
                    }
                    latest = JObject.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                }

                Version current;
                Version offered;
                if (!Version.TryParse(Installation.Version, out current) ||
                    !Version.TryParse((string)latest["version"], out offered) ||
                    offered <= current)
                {
                    return;
                }

                // Качаем установщик только со своей страницы и только с
                // контрольной суммой: запускать мы его будем сами.
                string url = (string)latest["url"];
                if (string.IsNullOrEmpty(url) ||
                    !url.StartsWith(SiteUrl, StringComparison.OrdinalIgnoreCase) ||
                    string.IsNullOrEmpty((string)latest["sha256"]))
                {
                    return;
                }

                string notes = (string)latest["notes"];
                OnUi(() =>
                {
                    _latest = latest;
                    UpdateText = "Доступна версия " + offered +
                                 (string.IsNullOrWhiteSpace(notes) ? "." : ": " + notes);
                    CanUpdate = true;
                    IsUpdateVisible = true;
                });
            }
            catch
            {
                // Нет сети или сайт лежит — спросим в следующий запуск.
            }
        }

        /// <summary>
        /// Скачивает установщик новой версии, сверяет контрольную сумму и
        /// запускает его в тихом режиме. Сам установщик ждёт, пока R-Pro
        /// закроется (ключ /WAITFORRPRO), — открытая программа держит файлы.
        /// </summary>
        public async Task UpdateAsync()
        {
            JObject latest = _latest;
            if (latest == null || !CanUpdate)
            {
                return;
            }

            CanUpdate = false;
            UpdateButtonText = "Скачиваю…";

            try
            {
                string url = (string)latest["url"];
                string expected = ((string)latest["sha256"]).Trim().ToLowerInvariant();

                byte[] data = await Http.GetByteArrayAsync(url).ConfigureAwait(true);

                string actual;
                using (SHA256 sha = SHA256.Create())
                {
                    actual = BitConverter.ToString(sha.ComputeHash(data)).Replace("-", string.Empty).ToLowerInvariant();
                }
                if (actual != expected)
                {
                    UpdateText = "Скачанный установщик не совпал с опубликованным — возможно, файл оборвался. Попробуйте ещё раз.";
                    UpdateButtonText = "Повторить";
                    CanUpdate = true;
                    return;
                }

                string folder = UpdatesFolder;
                System.IO.Directory.CreateDirectory(folder);
                string setup = Path.Combine(folder, Path.GetFileName(new Uri(url).AbsolutePath));
                File.WriteAllBytes(setup, data);

                Process.Start(new ProcessStartInfo
                {
                    FileName = setup,
                    Arguments = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /WAITFORRPRO=1 " +
                                "/LOG=\"" + Path.Combine(folder, "update.log") + "\"",
                    UseShellExecute = true
                });

                UpdateText = "Версия " + (string)latest["version"] +
                             " скачана и установится сама, как только вы закроете R-Pro.";
                IsUpdateButtonVisible = false;
            }
            catch (Exception error)
            {
                UpdateText = "Не удалось скачать обновление: " + error.Message;
                UpdateButtonText = "Повторить";
                CanUpdate = true;
            }
        }

        public ObservableCollection<ChatMessage> Messages { get; private set; }

        public string AgentUrl
        {
            get
            {
                string fromEnv = Environment.GetEnvironmentVariable("RPRO_AGENT_URL");
                return string.IsNullOrWhiteSpace(fromEnv) ? "http://127.0.0.1:8766" : fromEnv;
            }
        }

        public string Input
        {
            get { return _input; }
            set { _input = value; NotifyOfPropertyChange(() => Input); }
        }

        public bool IsBusy
        {
            get { return _isBusy; }
            set
            {
                _isBusy = value;
                NotifyOfPropertyChange(() => IsBusy);
                NotifyOfPropertyChange(() => CanSend);
            }
        }

        public bool CanSend
        {
            get { return !_isBusy; }
        }

        private void Say(string author, string text, bool isAgent, bool isService = false)
        {
            Messages.Add(new ChatMessage
            {
                Author = author,
                Text = text,
                IsAgent = isAgent,
                IsService = isService
            });
        }

        /// <summary>Отправляет вопрос агенту и показывает ответ.</summary>
        public async Task SendAsync()
        {
            string question = (Input ?? string.Empty).Trim();
            if (question.Length == 0 || IsBusy)
            {
                return;
            }

            Input = string.Empty;
            Say("вы", question, false);
            IsBusy = true;

            // Заглушка с точками появляется сразу под вопросом и живёт, пока
            // агент думает. В конце она уступает место настоящему ответу.
            ChatMessage ожидание = new ChatMessage
            {
                Author = "ИИ-агент",
                Text = string.Empty,
                IsAgent = true,
                IsPending = true
            };
            Messages.Add(ожидание);

            CancellationTokenSource watching = new CancellationTokenSource();
            Task.Run(() => WatchProgressAsync(ожидание, watching.Token));

            try
            {
                JObject request = new JObject();
                request["message"] = question;

                StringContent content = new StringContent(
                    request.ToString(), Encoding.UTF8, "application/json");

                HttpResponseMessage response =
                    await Http.PostAsync(AgentUrl + "/ask", content).ConfigureAwait(true);
                string body = await response.Content.ReadAsStringAsync().ConfigureAwait(true);
                JObject answer = JObject.Parse(body);

                // Точки убираем здесь, а не в конце: иначе ответ и служебная
                // строка встанут выше заглушки, и порядок реплик поедет.
                Messages.Remove(ожидание);

                // Ход работы («посмотрел: rpro_scene…») в переписке не оставляем:
                // он был виден в пузыре ожидания, пока агент думал. Ошибка — тоже
                // ответ агента, а не отдельная реплика «системы» (требование 08.10).
                if (answer["ok"] != null && (bool)answer["ok"])
                {
                    Say("ИИ-агент", (string)answer["answer"], true);
                }
                else
                {
                    Say("ИИ-агент", "Не получилось: " + (string)answer["error"], true);
                }
            }
            catch (Exception error)
            {
                Say("система",
                    NotRunningHint() + Environment.NewLine + Environment.NewLine +
                    "Подробности: " + error.Message,
                    false, true);
            }
            finally
            {
                watching.Cancel();
                Messages.Remove(ожидание);
                IsBusy = false;
            }
        }

        /// <summary>
        /// Пока агент думает, спрашивает у него, чем он занят, и пишет это
        /// под точками. Старый сервер /progress не знает — тогда просто точки.
        /// </summary>
        private async Task WatchProgressAsync(ChatMessage pending, CancellationToken stop)
        {
            while (!stop.IsCancellationRequested)
            {
                try
                {
                    await Task.Delay(500, stop).ConfigureAwait(false);
                    using (CancellationTokenSource timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3)))
                    {
                        HttpResponseMessage response = await Http
                            .GetAsync(AgentUrl + "/progress", timeout.Token).ConfigureAwait(false);
                        if (!response.IsSuccessStatusCode)
                        {
                            return;
                        }
                        JObject body = JObject.Parse(await response.Content.ReadAsStringAsync().ConfigureAwait(false));
                        string text = (string)body["text"] ?? string.Empty;
                        if (!stop.IsCancellationRequested)
                        {
                            OnUi(() => pending.Status = text);
                        }
                    }
                }
                catch (OperationCanceledException)
                {
                    if (stop.IsCancellationRequested) return;
                }
                catch
                {
                    // сервер не ответил на опрос — попробуем через полсекунды
                }
            }
        }

    }
}
