// Автозапуск сервера агента вместе с R-Pro.
//
// Окну чата нужен сервер agent/serve.py. Раньше его поднимали руками в
// терминале, и инженер, запустив R-Pro, первым делом натыкался на «агент не
// отвечает». Теперь плагин сам запускает сервер скрытым процессом при старте
// программы и гасит при выходе.
//
// Где лежит агент, плагин узнаёт из реестра: установщик пишет папку установки
// в HKCU\Software\AAIT\RProAgent (InstallDir), а там лежат свой Python и
// agent\serve.py. Для разработки это можно перебить файлом agent.json рядом с
// остальными настройками тикера (его пишет agent/install-autostart.ps1) —
// тогда агент запускается из репозитория.
//
// Порт сервер проверяет сам: если агент уже запущен (например, руками для
// отладки), второй экземпляр тихо завершится, а панель поговорит с первым.
// Поэтому здесь нет ни опроса порта, ни ожидания — только запуск процесса,
// который не задерживает старт R-Pro.

using System;
using System.Diagnostics;
using System.IO;

using Newtonsoft.Json.Linq;

namespace RProAiBridge
{
    internal static class AgentLauncher
    {
        private static Process _process;

        private static string SettingsFolder
        {
            get
            {
                string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                return Path.Combine(local, "R-Pro", "AIAgentBridge");
            }
        }

        private static string ConfigPath
        {
            get { return Path.Combine(SettingsFolder, "agent.json"); }
        }

        private static string DisableFlagPath
        {
            get { return Path.Combine(SettingsFolder, "agent.disabled"); }
        }

        public static string LogPath
        {
            get { return Path.Combine(SettingsFolder, "agent.log"); }
        }

        /// <summary>
        /// Запускает сервер агента. Возвращает строку для панели вывода или
        /// null, если сказать нечего (автозапуск не настроен).
        /// </summary>
        public static string Start()
        {
            if (File.Exists(DisableFlagPath))
            {
                return "автозапуск агента выключен файлом agent.disabled";
            }
            string python;
            string script;
            string fix;

            if (File.Exists(ConfigPath))
            {
                JObject config = JObject.Parse(File.ReadAllText(ConfigPath));
                python = (string)config["python"];
                script = (string)config["script"];
                fix = ". Повторите agent\\install-autostart.ps1";
            }
            else
            {
                string installDir = Installation.Directory;
                if (installDir == null)
                {
                    return null;
                }
                python = Path.Combine(installDir, "python", "python.exe");
                script = Path.Combine(installDir, "agent", "serve.py");
                fix = ". Запустите установщик ИИ-агента ещё раз";
            }

            if (string.IsNullOrWhiteSpace(python) || !File.Exists(python))
            {
                return "агент не запущен: не найден Python " + python + fix;
            }
            if (string.IsNullOrWhiteSpace(script) || !File.Exists(script))
            {
                return "агент не запущен: не найден " + script + fix;
            }

            // Начинаем лог заново при каждом запуске: иначе он растёт без
            // конца, а нужен почти всегда только последний сеанс.
            try { File.WriteAllText(LogPath, string.Empty); } catch { }

            int parentId = Process.GetCurrentProcess().Id;

            ProcessStartInfo info = new ProcessStartInfo
            {
                FileName = python,
                Arguments = Quote(script) +
                            " --log " + Quote(LogPath) +
                            " --parent-pid " + parentId,
                WorkingDirectory = Path.GetDirectoryName(script),
                UseShellExecute = false,
                CreateNoWindow = true
            };
            // Вывод Python идёт в файл, а не в трубу: трубу пришлось бы
            // вычитывать, иначе при заполнении буфера сервер встанет.
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";

            _process = Process.Start(info);
            return "агент запущен, журнал: " + LogPath;
        }

        /// <summary>Гасит сервер, если его запускали мы.</summary>
        public static void Stop()
        {
            // Сервер и сам следит за процессом R-Pro и завершится вслед за
            // ним. Здесь — чтобы не ждать и не оставлять его, если слежение
            // по какой-то причине не сработало.
            Process process = _process;
            _process = null;
            if (process == null)
            {
                return;
            }
            try
            {
                if (!process.HasExited)
                {
                    process.Kill();
                }
            }
            catch
            {
                // Уже завершился сам — ровно то, чего мы хотели.
            }
            finally
            {
                process.Dispose();
            }
        }

        private static string Quote(string value)
        {
            return "\"" + value + "\"";
        }
    }
}
