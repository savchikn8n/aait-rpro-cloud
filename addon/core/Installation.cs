// Сведения об установке ИИ-агента.
//
// Установщик пишет их в HKCU\Software\AAIT\RProAgent: папку установки
// (InstallDir), версию (Version) и путь к этому ядру (CorePath, его читает
// загрузчик). При запуске из репозитория ключа может не быть — тогда
// Directory вернёт null, а версия возьмётся из самой сборки.

using System;
using System.Reflection;

using Microsoft.Win32;

namespace RProAiBridge
{
    internal static class Installation
    {
        public const string RegistryKey = @"Software\AAIT\RProAgent";

        /// <summary>Папка установки или null, если агент не ставился установщиком.</summary>
        public static string Directory
        {
            get
            {
                string value = Read("InstallDir");
                return string.IsNullOrWhiteSpace(value) ? null : value;
            }
        }

        /// <summary>Версия ядра, как её проставила сборка из файла VERSION.</summary>
        public static string Version
        {
            get
            {
                AssemblyInformationalVersionAttribute attribute =
                    (AssemblyInformationalVersionAttribute)Attribute.GetCustomAttribute(
                        typeof(Installation).Assembly,
                        typeof(AssemblyInformationalVersionAttribute));
                return attribute != null
                    ? attribute.InformationalVersion
                    : typeof(Installation).Assembly.GetName().Version.ToString();
            }
        }

        private static string Read(string name)
        {
            try
            {
                using (RegistryKey key = Registry.CurrentUser.OpenSubKey(RegistryKey))
                {
                    return key == null ? null : key.GetValue(name) as string;
                }
            }
            catch
            {
                return null;
            }
        }
    }
}
