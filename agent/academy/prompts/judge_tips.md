# Judge 1: curated life-hacks for R-Pro from lesson tips

Context. R-Pro («Рациональное производство») is a Russian-localized fork of
Visual Components 4.x (3D factory / robot simulation). Its scripting is the
embedded **Python 2.7** API. Russian-speaking engineers will use a local AI
assistant that gets short lessons built from Visual Components Academy videos.
The lessons were made by a small model (Haiku) from video transcripts, so some
tips are generic, obvious, duplicated, or subtly wrong.

Your input: one file of tips (`work/judge/tips_partN.md`). Each block is one
lesson: `### <title> | <slug> | версия <VC version> | применимость: ok|check`,
followed by lines starting with «- Совет:» / «- Ловушка:». Applicability `check`
means the lesson shows a feature that may not exist in R-Pro (Visual Components
5.x, Python 3 API, cloud). The version number is the Visual Components version
the video was recorded in (R-Pro is 4.x).

Your task: write a curated Russian life-hacks document.

1. Keep only tips that are **non-obvious and actionable** — shortcuts, hidden
   behaviours, "this silently fails if…", ordering requirements, performance
   advice, common mistakes. Drop generic advice ("save your work", "check the
   result"), pure UI description, and anything that only restates a step.
2. **Merge duplicates** across lessons into one item and list all source slugs.
3. Group by theme with `##` headings, for example: Интерфейс и навигация;
   Моделирование компонентов; Свойства и скрипты (Python); Process Modeling:
   потоки, ресурсы, операторы; Роботы и программирование (OLP); Подключения
   (ПЛК, роботы, OPC UA); Физика; Импорт CAD и экспорт; Визуализация и запись.
   Add or rename themes if the content needs it.
4. Each item: one or two sentences, imperative or declarative, in natural
   technical Russian, followed by the sources in square brackets, e.g.
   `[collision-geometry, spot-weld-programming]`. Mark items from `check`
   lessons with ⚠ and say in a few words why they may not hold in R-Pro.
5. Be honest about doubt: if a tip looks wrong, self-contradictory or
   suspiciously specific (a number or name that seems invented), put it in a
   final section `## Сомнительное` with a one-line reason instead of the main list.
6. Rank within each theme: most valuable first. Aim for the best ~150-250 items
   in total from your part, not all of them.

Never invent tips that are not in the input. Do not add knowledge of your own.

Write the result to `work/judge/lifehacks_partN.md` (N as in your input file),
starting with a line `# Лайфхаки R-Pro — часть N`. Then reply with only:
`kept <n> of <m> tips, doubtful <k>`.
