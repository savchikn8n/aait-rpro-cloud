// Снимает транскрипты роликов YouTube и отправляет их приёмнику (receiver.py).
//
// Как пользоваться: вставить этот файл целиком в javascript_tool на открытой
// вкладке youtube.com (eval с Trusted Types запрещён, подключить по сети нельзя),
// затем запустить обход без ожидания, чтобы вызов не упёрся в таймаут:
//   window.__done = []; grabAll(['id1','id2',...]);  // не await
// и по желанию спрашивать прогресс: window.__done.length, window.__finished
//
// Между роликами переходим событием роутера YouTube (SPA): клик по ссылке
// вызывает полную перезагрузку и гибель скрипта. После перехода URL меняется
// РАНЬШЕ, чем плеер и панель транскрипта, — поэтому ждём, пока плеер сам
// назовёт нужный video_id, и принимаем запись, только если длительность
// плеера совпала с последней меткой времени транскрипта. Чужой текст в базе
// знаний хуже пустого места, поэтому при любом сомнении пишем ошибку.
async function grabAll(ids) {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const post = o => fetch('http://127.0.0.1:8799/', { method: 'POST', body: JSON.stringify(o) });
  const player = () => document.querySelector('#movie_player');
  const playing = () => player()?.getVideoData?.().video_id;
  // YouTube раздаёт две вёрстки панели транскрипта (старая ytd-transcript-segment-renderer и
  // новая transcript-segment-view-model); какая достанется ролику — заранее не известно.
  // Со старым селектором новая вёрстка давала «пустой транскрипт».
  const segs = () => [...document.querySelectorAll('ytd-transcript-segment-renderer, transcript-segment-view-model')];
  const segTime = s => (s.querySelector('.segment-timestamp, .ytwTranscriptSegmentViewModelTimestamp'))?.innerText.trim();
  const segText = s => (s.querySelector('.segment-text, .ytAttributedStringHost'))?.innerText.trim();
  const findBtn = () => [...document.querySelectorAll('button')].find(b =>
    /transcript|текст видео/i.test(b.getAttribute('aria-label') || b.textContent || ''));
  const secs = t => (t || '').split(':').reverse().reduce((a, v, i) => a + (+v || 0) * 60 ** i, 0);
  const until = async (cond, ms) => { for (let i = 0; i < ms / 250 && !cond(); i++) await sleep(250); return cond(); };
  let prevFirst = null;

  for (const id of ids) {
    const rec = { id, segments: [] };
    try {
      if (playing() !== id) {
        document.querySelector('ytd-app').dispatchEvent(new CustomEvent('yt-navigate', {
          bubbles: true, composed: true,
          detail: { endpoint: {
            commandMetadata: { webCommandMetadata: { url: '/watch?v=' + id, webPageType: 'WEB_PAGE_TYPE_WATCH', rootVe: 3832 } },
            watchEndpoint: { videoId: id } } },
        }));
      }
      if (!await until(() => playing() === id, 15000)) throw new Error('плеер не перешёл на ролик');
      player().pauseVideo?.();
      await until(() => player().getDuration() > 0, 5000);
      rec.seconds = Math.round(player().getDuration());
      rec.title = player().getVideoData().title;

      // страница после перехода ещё перерисовывается: клик по кнопке раньше
      // времени уходит в старый элемент и панель остаётся пустой
      await sleep(3000);
      let btn = null;
      for (let i = 0; i < 40 && !btn; i++) {
        btn = findBtn();
        if (!btn) await sleep(500);
      }
      if (!btn) throw new Error('нет кнопки транскрипта');
      let prev = -1, n = 0;
      for (let attempt = 0; attempt < 3 && n === 0; attempt++) {
        if (segs().length === 0) (findBtn() || btn).click();
        for (let i = 0; i < 16; i++) {
          await sleep(500);
          n = segs().length;
          if (n > 0 && n === prev) break;
          prev = n;
        }
      }
      rec.segments = segs().map(s => [
        segTime(s),
        segText(s),
      ]);
      // у серии роликов общая вступительная фраза, поэтому одной первой строки
      // мало: сравниваем число строк и три первые фразы
      if (!rec.segments[0]?.[1]) throw new Error('пустой транскрипт');
      const first = rec.segments.length + '|' + rec.segments.slice(0, 3).map(s => s[1]).join(' ');
      if (first === prevFirst) throw new Error('панель не обновилась (дубль предыдущего)');
      const last = secs(rec.segments[rec.segments.length - 1][0]);
      if (last > rec.seconds + 5 || last < rec.seconds * 0.7) throw new Error('длительность не сходится: ' + last + ' из ' + rec.seconds);
      prevFirst = first;
    } catch (e) {
      rec.err = String(e.message || e);
      rec.segments = [];
    }
    await post(rec);
    (window.__done = window.__done || []).push(id + (rec.err ? ' ERR ' + rec.err : ' ' + rec.segments.length));
  }
  window.__finished = true;
}
