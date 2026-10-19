// Внешний вид окна чата.
//
// Разметка лежит строкой и разбирается во время выполнения. Так сделано не от
// хорошей жизни: сборка идёт компилятором из состава .NET Framework, без
// Visual Studio и MSBuild, а тот не умеет компилировать XAML. Зато шаблон
// остаётся нормальной разметкой, а не ручной сборкой дерева элементов.
//
// Caliburn.Micro находит этот класс по имени: ChatPanelViewModel → ChatPanelView.

using System;
using System.Collections.Specialized;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Input;
using System.Windows.Markup;

namespace RProAiBridge
{
    public class ChatPanelView : UserControl
    {
        // Ничего лишнего сверху: заголовок панели и так виден в её шапке.
        // Пока агент думает, внизу переписки мигают три точки — этого
        // достаточно, чтобы понять, что запрос в работе.
        // Разметка на сетке, а не на DockPanel. Разница принципиальная: хозяин
        // панели может отдать содержимому «бесконечную» высоту, и тогда
        // прижатое к низу поле ввода уезжает за нижний край видимой области —
        // ровно это и случилось, когда панели задали высоту с запасом.
        // У сетки строки заданы явно, поэтому поле всегда под перепиской.
        private const string Markup = @"
<UserControl xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation'
             xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml'>
  <UserControl.Resources>
    <BooleanToVisibilityConverter x:Key='ВидимостьПоФлагу'/>
  </UserControl.Resources>

  <Grid Margin='6'>
    <Grid.RowDefinitions>
      <RowDefinition Height='Auto'/>
      <RowDefinition Height='*' MinHeight='60'/>
      <RowDefinition Height='Auto'/>
      <RowDefinition Height='Auto'/>
    </Grid.RowDefinitions>

    <!-- Плашка «вышла новая версия». Видна, только когда есть что предложить. -->
    <Border Grid.Row='0' Margin='0,0,0,6' Padding='8,6' CornerRadius='3' Background='#33D97757'
            Visibility='{Binding IsUpdateVisible, Converter={StaticResource ВидимостьПоФлагу}}'>
      <Grid>
        <Grid.ColumnDefinitions>
          <ColumnDefinition Width='*'/>
          <ColumnDefinition Width='Auto'/>
        </Grid.ColumnDefinitions>
        <TextBlock Text='{Binding UpdateText}' TextWrapping='Wrap' VerticalAlignment='Center'/>
        <Button x:Name='UpdateButton' Grid.Column='1' Margin='8,0,0,0' Padding='10,2'
                VerticalAlignment='Center'
                Content='{Binding UpdateButtonText}' IsEnabled='{Binding CanUpdate}'
                Visibility='{Binding IsUpdateButtonVisible, Converter={StaticResource ВидимостьПоФлагу}}'/>
      </Grid>
    </Border>

    <TextBox x:Name='InputBox' Grid.Row='2' MinHeight='56' MaxHeight='140'
             Margin='0,6,0,0' Padding='4,3'
             Text='{Binding Input, UpdateSourceTrigger=PropertyChanged}'
             AcceptsReturn='True' TextWrapping='Wrap'
             VerticalScrollBarVisibility='Auto'/>

    <ScrollViewer x:Name='Scroller' Grid.Row='1' VerticalScrollBarVisibility='Auto'>
      <ItemsControl ItemsSource='{Binding Messages}'>
        <ItemsControl.ItemTemplate>
          <DataTemplate>
            <Border Margin='0,0,0,8' Padding='8,6' CornerRadius='3'>
              <Border.Style>
                <Style TargetType='Border'>
                  <Setter Property='Background' Value='#14808080'/>
                  <Style.Triggers>
                    <!-- вопросы человека — лёгким голубым, ответы агента — серым -->
                    <DataTrigger Binding='{Binding IsAgent}' Value='False'>
                      <Setter Property='Background' Value='#163B82F6'/>
                    </DataTrigger>
                    <DataTrigger Binding='{Binding IsService}' Value='True'>
                      <Setter Property='Background' Value='#14D97757'/>
                    </DataTrigger>
                  </Style.Triggers>
                </Style>
              </Border.Style>
              <StackPanel>
                <TextBlock Text='{Binding Author}' FontWeight='Bold'
                           Opacity='0.7' FontSize='11' Margin='0,0,0,3'/>

                <!-- Ответ либо готов (оформленный, см. MarkdownLite), либо на
                     его месте мигают три точки. -->
                <ContentControl Content='{Binding Body}' Focusable='False' IsTabStop='False'>
                  <ContentControl.Style>
                    <Style TargetType='ContentControl'>
                      <Style.Triggers>
                        <DataTrigger Binding='{Binding IsPending}' Value='True'>
                          <Setter Property='Visibility' Value='Collapsed'/>
                        </DataTrigger>
                      </Style.Triggers>
                    </Style>
                  </ContentControl.Style>
                </ContentControl>

                <!-- Пока ждём ответа: точки и под ними — чем агент занят сейчас
                     («смотрю список компонентов…»). Уходит вместе с пузырём. -->
                <StackPanel Visibility='{Binding IsPending, Converter={StaticResource ВидимостьПоФлагу}}'>
                <StackPanel Orientation='Horizontal' Height='10' Margin='1,3,0,2'>
                  <Ellipse Width='6' Height='6' Margin='2,0' Fill='#9A9A9A'>
                    <Ellipse.Triggers>
                      <EventTrigger RoutedEvent='Loaded'>
                        <BeginStoryboard>
                          <Storyboard RepeatBehavior='Forever'>
                            <DoubleAnimation Storyboard.TargetProperty='Opacity'
                                             From='0.15' To='1' Duration='0:0:0.45'
                                             AutoReverse='True' BeginTime='0:0:0'/>
                          </Storyboard>
                        </BeginStoryboard>
                      </EventTrigger>
                    </Ellipse.Triggers>
                  </Ellipse>
                  <Ellipse Width='6' Height='6' Margin='2,0' Fill='#9A9A9A'>
                    <Ellipse.Triggers>
                      <EventTrigger RoutedEvent='Loaded'>
                        <BeginStoryboard>
                          <Storyboard RepeatBehavior='Forever'>
                            <DoubleAnimation Storyboard.TargetProperty='Opacity'
                                             From='0.15' To='1' Duration='0:0:0.45'
                                             AutoReverse='True' BeginTime='0:0:0.15'/>
                          </Storyboard>
                        </BeginStoryboard>
                      </EventTrigger>
                    </Ellipse.Triggers>
                  </Ellipse>
                  <Ellipse Width='6' Height='6' Margin='2,0' Fill='#9A9A9A'>
                    <Ellipse.Triggers>
                      <EventTrigger RoutedEvent='Loaded'>
                        <BeginStoryboard>
                          <Storyboard RepeatBehavior='Forever'>
                            <DoubleAnimation Storyboard.TargetProperty='Opacity'
                                             From='0.15' To='1' Duration='0:0:0.45'
                                             AutoReverse='True' BeginTime='0:0:0.3'/>
                          </Storyboard>
                        </BeginStoryboard>
                      </EventTrigger>
                    </Ellipse.Triggers>
                  </Ellipse>
                </StackPanel>
                <TextBlock Text='{Binding Status}' FontStyle='Italic' FontSize='11.5' Opacity='0.6'
                           TextWrapping='Wrap' Margin='1,2,0,0'/>
                </StackPanel>

              </StackPanel>
            </Border>
          </DataTemplate>
        </ItemsControl.ItemTemplate>
      </ItemsControl>
    </ScrollViewer>

    <!-- Подсказка команд: набрали «/» в поле ввода — список всплывает над
         полем, поверх переписки. Не Popup, а слой в той же сетке: отдельное
         окно Popup в стыкуемой панели R-Pro отстаёт при перетаскивании. -->
    <Border x:Name='CommandHints' Grid.Row='1' VerticalAlignment='Bottom' Margin='0,0,0,2'
            Visibility='Collapsed' Panel.ZIndex='10'
            Background='{DynamicResource {x:Static SystemColors.WindowBrushKey}}'
            BorderBrush='#55808080' BorderThickness='1' CornerRadius='4' Padding='0,4,0,4'>
      <Border.Effect>
        <DropShadowEffect BlurRadius='8' ShadowDepth='1' Opacity='0.25'/>
      </Border.Effect>
      <StackPanel>
        <TextBlock Text='Команды агента   ↑↓ выбрать · Tab/Enter подставить · Esc закрыть'
                   FontSize='10.5' Opacity='0.55' Margin='10,0,8,3'/>
        <ListBox x:Name='CommandList' BorderThickness='0' Background='Transparent'
                 MaxHeight='260' Focusable='False' Grid.IsSharedSizeScope='True'
                 ScrollViewer.HorizontalScrollBarVisibility='Disabled'>
          <ListBox.ItemContainerStyle>
            <Style TargetType='ListBoxItem'>
              <Setter Property='Focusable' Value='False'/>
              <Setter Property='Padding' Value='10,3,8,3'/>
              <Setter Property='HorizontalContentAlignment' Value='Stretch'/>
            </Style>
          </ListBox.ItemContainerStyle>
          <ListBox.ItemTemplate>
            <DataTemplate>
              <Grid ToolTip='{Binding Description}'>
                <Grid.ColumnDefinitions>
                  <ColumnDefinition Width='Auto' SharedSizeGroup='Команда'/>
                  <ColumnDefinition Width='*'/>
                </Grid.ColumnDefinitions>
                <TextBlock Grid.Column='0' Margin='0,0,10,0' FontWeight='SemiBold'
                           Text='{Binding Name}'/>
                <TextBlock Grid.Column='1' TextTrimming='CharacterEllipsis'>
                  <Run Text='{Binding Args, Mode=OneWay}' Foreground='#8A8A8A'/>
                  <Run Text='{Binding Description, Mode=OneWay}' Foreground='#555555'/>
                </TextBlock>
              </Grid>
            </DataTemplate>
          </ListBox.ItemTemplate>
        </ListBox>
      </StackPanel>
    </Border>

    <!-- Отзыв о работе агента: форма на странице проекта. -->
    <TextBlock Grid.Row='3' Margin='2,5,0,0' FontSize='11' Opacity='0.8'>
      <Hyperlink x:Name='FeedbackLink'>Оставить отзыв о работе агента</Hyperlink>
    </TextBlock>

  </Grid>
</UserControl>";

        private ScrollViewer _scroller;
        private TextBox _input;
        private Border _hints;
        private ListBox _commandList;
        private ChatPanelViewModel _model;

        public ChatPanelView()
        {
            try
            {
                UserControl parsed = (UserControl)XamlReader.Parse(Markup);
                Content = parsed.Content;

                _scroller = parsed.FindName("Scroller") as ScrollViewer;

                _input = parsed.FindName("InputBox") as TextBox;
                _hints = parsed.FindName("CommandHints") as Border;
                _commandList = parsed.FindName("CommandList") as ListBox;
                if (_input != null)
                {
                    _input.PreviewKeyDown += OnInputKeyDown;
                    _input.TextChanged += delegate { UpdateHints(); };
                    _input.LostKeyboardFocus += delegate { HideHints(); };
                    Loaded += delegate { _input.Focus(); };
                }
                if (_commandList != null)
                {
                    _commandList.PreviewMouseLeftButtonUp += OnHintClicked;
                }

                // Команда в ответе агента («/справка Сохранение планировки») —
                // ссылка: щелчок отправляет её, как если бы её набрали.
                MarkdownLite.CommandClicked += OnCommandLinkClicked;
                Unloaded += delegate { MarkdownLite.CommandClicked -= OnCommandLinkClicked; };
                Loaded += delegate
                {
                    MarkdownLite.CommandClicked -= OnCommandLinkClicked;
                    MarkdownLite.CommandClicked += OnCommandLinkClicked;
                };

                // Кнопку и ссылку обрабатываем здесь, а не соглашениями
                // Caliburn.Micro: разметка разобрана из строки, и так надёжнее.
                Button update = parsed.FindName("UpdateButton") as Button;
                if (update != null)
                {
                    update.Click += async delegate
                    {
                        if (_model != null) { await _model.UpdateAsync(); }
                    };
                }

                Hyperlink feedback = parsed.FindName("FeedbackLink") as Hyperlink;
                if (feedback != null)
                {
                    feedback.Click += delegate
                    {
                        if (_model != null) { _model.OpenFeedback(); }
                    };
                }

                DataContextChanged += OnDataContextChanged;
            }
            catch (Exception error)
            {
                // Пустая панель без объяснений — худшее, что можно показать.
                Content = new TextBlock
                {
                    Text = "Не удалось построить панель: " + error.Message,
                    TextWrapping = TextWrapping.Wrap,
                    Margin = new Thickness(10)
                };
            }
        }

        private void OnDataContextChanged(object sender, DependencyPropertyChangedEventArgs e)
        {
            if (_model != null)
            {
                _model.Messages.CollectionChanged -= OnMessagesChanged;
            }

            _model = DataContext as ChatPanelViewModel;
            if (_model == null)
            {
                return;
            }

            _model.Messages.CollectionChanged += OnMessagesChanged;
        }

        private void OnMessagesChanged(object sender, NotifyCollectionChangedEventArgs e)
        {
            if (_scroller != null)
            {
                Dispatcher.BeginInvoke(new Action(() => _scroller.ScrollToEnd()));
            }
        }

        private async void OnInputKeyDown(object sender, KeyEventArgs e)
        {
            // Открыта подсказка команд — стрелки, Tab, Enter и Esc работают в ней.
            if (HintsVisible)
            {
                int count = _commandList.Items.Count;
                switch (e.Key)
                {
                    case Key.Down:
                        _commandList.SelectedIndex = (_commandList.SelectedIndex + 1) % count;
                        _commandList.ScrollIntoView(_commandList.SelectedItem);
                        e.Handled = true;
                        return;
                    case Key.Up:
                        _commandList.SelectedIndex = (_commandList.SelectedIndex - 1 + count) % count;
                        _commandList.ScrollIntoView(_commandList.SelectedItem);
                        e.Handled = true;
                        return;
                    case Key.Escape:
                        HideHints();
                        e.Handled = true;
                        return;
                    case Key.Tab:
                    case Key.Enter:   // Key.Return — то же значение
                        CommandInfo chosen = _commandList.SelectedItem as CommandInfo;
                        if (chosen != null)
                        {
                            e.Handled = true;
                            // Enter на команде без обязательных аргументов сразу
                            // отправляет её; Tab только подставляет.
                            bool sendNow = e.Key != Key.Tab && !chosen.RequiresArgs;
                            Complete(chosen, !sendNow && chosen.HasArgs);
                            if (sendNow) { await SendAsync(); }
                            return;
                        }
                        break;
                }
            }

            // Enter отправляет, Shift+Enter переносит строку — как принято в чатах.
            // Перехватываем именно PreviewKeyDown: иначе TextBox успевает вставить
            // перевод строки раньше нас.
            if (e.Key != Key.Enter && e.Key != Key.Return)
            {
                return;
            }

            bool shift = (Keyboard.Modifiers & ModifierKeys.Shift) == ModifierKeys.Shift;
            if (shift)
            {
                return;
            }

            e.Handled = true;
            await SendAsync();
        }

        private async System.Threading.Tasks.Task SendAsync()
        {
            HideHints();
            if (_model != null)
            {
                await _model.SendAsync();
                if (_input != null) { _input.Focus(); }
            }
        }

        // --- подсказка команд ---------------------------------------------------

        private bool HintsVisible
        {
            get { return _hints != null && _hints.Visibility == Visibility.Visible && _commandList.Items.Count > 0; }
        }

        /// <summary>
        /// Показывает команды, пока набирается само имя команды: «/», «/сп».
        /// Как только после имени пошёл пробел (аргументы) — прячет.
        /// </summary>
        private void UpdateHints()
        {
            if (_hints == null || _commandList == null || _input == null)
            {
                return;
            }
            string text = _input.Text ?? string.Empty;
            if (!text.StartsWith("/") || text.IndexOfAny(new[] { ' ', '\n', '\r', '\t' }) >= 0)
            {
                HideHints();
                return;
            }
            System.Collections.Generic.List<CommandInfo> found = CommandCatalog.Filter(text);
            if (found.Count == 0)
            {
                HideHints();
                return;
            }
            _commandList.ItemsSource = found;
            _commandList.SelectedIndex = 0;
            _hints.Visibility = Visibility.Visible;
        }

        private void HideHints()
        {
            if (_hints != null)
            {
                _hints.Visibility = Visibility.Collapsed;
            }
        }

        private void Complete(CommandInfo command, bool space)
        {
            if (_input == null)
            {
                return;
            }
            _input.Text = command.Name + (space ? " " : string.Empty);
            _input.CaretIndex = _input.Text.Length;
            HideHints();
            _input.Focus();
        }

        private async void OnHintClicked(object sender, MouseButtonEventArgs e)
        {
            DependencyObject source = e.OriginalSource as DependencyObject;
            ListBoxItem item = source == null ? null
                : ItemsControl.ContainerFromElement(_commandList, source) as ListBoxItem;
            CommandInfo command = item == null ? null : item.Content as CommandInfo;
            if (command == null)
            {
                return;
            }
            e.Handled = true;
            Complete(command, command.RequiresArgs);
            if (!command.RequiresArgs) { await SendAsync(); }
        }

        private async void OnCommandLinkClicked(string command)
        {
            if (_model == null || _input == null || !_model.CanSend)
            {
                return;
            }
            _input.Text = command;
            await SendAsync();
        }
    }
}
