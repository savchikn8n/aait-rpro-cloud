// Оформление ответов агента: простая разметка → документ WPF.
//
// Агент пишет ответы в небольшом подмножестве Markdown, чтобы их было
// удобно читать и в терминале, и здесь:
//
//   **Заголовок**            строка целиком жирная — заголовок ответа
//   1. шаг                   нумерованный шаг (номер берётся из текста)
//   • пункт  /  - пункт      пункт списка; с отступом — подпункт шага
//   > совет                  совет на цветной плашке
//   _источник_               строка целиком курсивом — мелкая приглушённая подпись
//   ```код```                блок кода моноширинным шрифтом
//   **жирный**, `код`        внутри строки
//   /справка Раздел          команда агента — ссылка, щелчок отправляет её
//
// Раньше ответ показывался одним TextBlock: шаги, советы и источник
// сливались в стену текста.

using System;
using System.Collections.Generic;
using System.Text.RegularExpressions;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Media;

namespace RProAiBridge
{
    public static class MarkdownLite
    {
        /// <summary>Щелчок по команде в ответе («/справка Сохранение планировки»).</summary>
        public static event Action<string> CommandClicked;

        private static readonly Brush TipBackground = Frozen(Color.FromArgb(0x22, 0x3B, 0x82, 0xF6));
        private static readonly Brush TipBorder = Frozen(Color.FromArgb(0xAA, 0x3B, 0x82, 0xF6));
        private static readonly Brush CodeBackground = Frozen(Color.FromArgb(0x1F, 0x80, 0x80, 0x80));
        private static readonly Brush LinkBrush = Frozen(Color.FromRgb(0x1E, 0x6F, 0xD9));
        private static readonly Brush MutedBrush = Frozen(Color.FromRgb(0x80, 0x80, 0x80));
        private static readonly FontFamily Mono = new FontFamily("Consolas, Courier New");

        private static Brush Frozen(Color c)
        {
            SolidColorBrush b = new SolidColorBrush(c);
            b.Freeze();
            return b;
        }

        private static readonly Regex Numbered = new Regex(@"^\s*(\d+)[.)]\s+(.*)$");
        private static readonly Regex Bullet = new Regex(@"^(\s*)[•\-\*·]\s+(.*)$");
        private static readonly Regex WholeBold = new Regex(@"^\*\*(.+)\*\*:?$");
        private static readonly Regex WholeItalic = new Regex(@"^_(.+)_$");

        // **жирный** | `код` | /команда с аргументами до ; ) или конца фразы
        private static readonly Regex Inline = new Regex(
            @"\*\*(?<b>.+?)\*\*|`(?<c>[^`]+)`|(?<cmd>(?<![\w/])/(справка|проблема|термин|api|совет|состояние|сцена|ошибки|каталог|снимок|габариты|где|симуляция|отчёт|отчет|оптимизация|домой|сброс|помощь)(?:\s+[^;\)\n«»—,:]*?)?)(?=\s*[;\)\n«»—,:]|\.\s|\.$|$)",
            RegexOptions.Compiled);

        /// <summary>
        /// Элемент для реплики: документ только для чтения, текст можно выделить
        /// и скопировать. markdown=false — текст как есть (вопросы человека).
        /// </summary>
        public static FrameworkElement Build(string text, bool markdown)
        {
            FlowDocument doc = markdown ? Parse(text ?? string.Empty) : Plain(text ?? string.Empty);
            doc.PagePadding = new Thickness(0);
            doc.TextAlignment = TextAlignment.Left;

            RichTextBox box = new RichTextBox
            {
                Document = doc,
                IsReadOnly = true,
                IsDocumentEnabled = true,           // ссылки кликаются
                BorderThickness = new Thickness(0),
                Background = Brushes.Transparent,
                Padding = new Thickness(0),
                Margin = new Thickness(-2, 0, 0, 0), // у RichTextBox свой отступ каретки
                Focusable = true,
                IsTabStop = false,
                VerticalScrollBarVisibility = ScrollBarVisibility.Disabled,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                FocusVisualStyle = null,
                Cursor = Cursors.Arrow
            };

            // Шрифт и цвет — как у панели (тема R-Pro), а не по умолчанию у документа.
            box.Loaded += delegate
            {
                doc.FontFamily = box.FontFamily;
                doc.FontSize = box.FontSize;
                object fg = box.Parent is FrameworkElement
                    ? ((FrameworkElement)box.Parent).GetValue(TextElement.ForegroundProperty)
                    : null;
                if (fg is Brush) { doc.Foreground = (Brush)fg; }
            };

            // RichTextBox забирает колесо мыши себе, даже когда прокручивать
            // нечего, — и переписка переставала листаться над ответом.
            box.PreviewMouseWheel += (sender, e) =>
            {
                e.Handled = true;
                UIElement parent = VisualTreeHelper.GetParent(box) as UIElement;
                if (parent != null)
                {
                    parent.RaiseEvent(new MouseWheelEventArgs(e.MouseDevice, e.Timestamp, e.Delta)
                    {
                        RoutedEvent = UIElement.MouseWheelEvent,
                        Source = box
                    });
                }
            };
            return box;
        }

        private static FlowDocument Plain(string text)
        {
            FlowDocument doc = new FlowDocument();
            doc.Blocks.Add(new Paragraph(new Run(text)) { Margin = new Thickness(0) });
            return doc;
        }

        public static FlowDocument Parse(string text)
        {
            FlowDocument doc = new FlowDocument();
            string[] lines = text.Replace("\r\n", "\n").Split('\n');

            List numbered = null;   // текущий нумерованный список
            List bullets = null;    // текущий список пунктов
            ListItem lastStep = null;

            for (int i = 0; i < lines.Length; i++)
            {
                string raw = lines[i];
                string line = raw.Trim();

                if (line.StartsWith("```"))
                {
                    // блок кода — до закрывающих ```
                    List<string> code = new List<string>();
                    for (i = i + 1; i < lines.Length && !lines[i].Trim().StartsWith("```"); i++)
                    {
                        code.Add(lines[i]);
                    }
                    doc.Blocks.Add(CodeBlock(string.Join("\n", code)));
                    numbered = null; bullets = null; lastStep = null;
                    continue;
                }

                if (line.Length == 0)
                {
                    numbered = null; bullets = null; lastStep = null;
                    continue;
                }

                Match m = Numbered.Match(raw);
                if (m.Success)
                {
                    if (numbered == null)
                    {
                        numbered = new List
                        {
                            MarkerStyle = TextMarkerStyle.Decimal,
                            StartIndex = int.Parse(m.Groups[1].Value),
                            Margin = new Thickness(0, 2, 0, 2),
                            Padding = new Thickness(20, 0, 0, 0)
                        };
                        doc.Blocks.Add(numbered);
                    }
                    lastStep = new ListItem(Para(m.Groups[2].Value, new Thickness(0, 1, 0, 1)));
                    numbered.ListItems.Add(lastStep);
                    bullets = null;
                    continue;
                }

                m = Bullet.Match(raw);
                if (m.Success)
                {
                    bool nested = m.Groups[1].Value.Length >= 2 && lastStep != null;
                    if (nested)
                    {
                        // подпункт шага — внутри его пункта
                        List sub = lastStep.Blocks.LastBlock as List;
                        if (sub == null)
                        {
                            sub = new List
                            {
                                MarkerStyle = TextMarkerStyle.Disc,
                                Margin = new Thickness(0, 0, 0, 2),
                                Padding = new Thickness(16, 0, 0, 0)
                            };
                            lastStep.Blocks.Add(sub);
                        }
                        sub.ListItems.Add(new ListItem(Para(m.Groups[2].Value, new Thickness(0))));
                        continue;
                    }
                    if (bullets == null)
                    {
                        bullets = new List
                        {
                            MarkerStyle = TextMarkerStyle.Disc,
                            Margin = new Thickness(0, 2, 0, 2),
                            Padding = new Thickness(18, 0, 0, 0)
                        };
                        doc.Blocks.Add(bullets);
                    }
                    bullets.ListItems.Add(new ListItem(Para(m.Groups[2].Value, new Thickness(0, 1, 0, 1))));
                    numbered = null; lastStep = null;
                    continue;
                }

                numbered = null; bullets = null; lastStep = null;

                if (line.StartsWith(">"))
                {
                    doc.Blocks.Add(Tip(line.TrimStart('>', ' ')));
                    continue;
                }

                m = WholeBold.Match(line);
                if (m.Success && !m.Groups[1].Value.Contains("**"))
                {
                    Paragraph head = new Paragraph { Margin = new Thickness(0, doc.Blocks.Count == 0 ? 0 : 8, 0, 3) };
                    head.Inlines.Add(new Bold(new Run(m.Groups[1].Value)));
                    head.FontSize = SystemFonts.MessageFontSize + 1.5;
                    doc.Blocks.Add(head);
                    continue;
                }

                m = WholeItalic.Match(line);
                if (m.Success)
                {
                    Paragraph note = Para(m.Groups[1].Value, new Thickness(0, 6, 0, 0));
                    note.FontStyle = FontStyles.Italic;
                    note.FontSize = Math.Max(10, SystemFonts.MessageFontSize - 1);
                    note.Foreground = MutedBrush;
                    doc.Blocks.Add(note);
                    continue;
                }

                doc.Blocks.Add(Para(line, new Thickness(0, 2, 0, 2)));
            }

            if (doc.Blocks.Count == 0)
            {
                doc.Blocks.Add(new Paragraph());
            }
            return doc;
        }

        private static Paragraph Para(string text, Thickness margin)
        {
            Paragraph p = new Paragraph { Margin = margin };
            AddInlines(p.Inlines, text);
            return p;
        }

        private static Block Tip(string text)
        {
            Paragraph p = Para(text, new Thickness(0));
            Section s = new Section(p)
            {
                Background = TipBackground,
                BorderBrush = TipBorder,
                BorderThickness = new Thickness(3, 0, 0, 0),
                Padding = new Thickness(8, 4, 6, 4),
                Margin = new Thickness(0, 5, 0, 3)
            };
            return s;
        }

        private static Block CodeBlock(string code)
        {
            Paragraph p = new Paragraph(new Run(code))
            {
                FontFamily = Mono,
                Background = CodeBackground,
                Padding = new Thickness(6, 4, 6, 4),
                Margin = new Thickness(0, 4, 0, 4)
            };
            return p;
        }

        private static void AddInlines(InlineCollection inlines, string text)
        {
            int pos = 0;
            foreach (Match m in Inline.Matches(text))
            {
                if (m.Index > pos)
                {
                    inlines.Add(new Run(text.Substring(pos, m.Index - pos)));
                }
                if (m.Groups["b"].Success)
                {
                    inlines.Add(new Bold(new Run(m.Groups["b"].Value)));
                }
                else if (m.Groups["c"].Success)
                {
                    inlines.Add(new Run(" " + m.Groups["c"].Value + " ")
                    {
                        FontFamily = Mono,
                        Background = CodeBackground
                    });
                }
                else if (m.Groups["cmd"].Success)
                {
                    string command = m.Groups["cmd"].Value.Trim();
                    Hyperlink link = new Hyperlink(new Run(command))
                    {
                        Foreground = LinkBrush,
                        Cursor = Cursors.Hand,
                        ToolTip = "Отправить агенту"
                    };
                    link.Click += delegate
                    {
                        Action<string> handler = CommandClicked;
                        if (handler != null) { handler(command); }
                    };
                    inlines.Add(link);
                }
                pos = m.Index + m.Length;
            }
            if (pos < text.Length)
            {
                inlines.Add(new Run(text.Substring(pos)));
            }
        }
    }
}
