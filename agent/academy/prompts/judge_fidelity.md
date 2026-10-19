# Judge 2: fidelity and usefulness audit of lessons

Context. R-Pro is a Russian-localized fork of Visual Components 4.x (Python 2.7
scripting). A small local AI assistant will read short Russian lessons built from
Visual Components Academy videos: video transcript → English digest (Haiku) →
Russian lesson (Haiku, UI names taken from the program's resource files). Your
job is to audit that pipeline on a sample, using the transcript as the only truth.

Each sample file `work/judge/sample/<slug>.md` contains three parts: 1) the
transcript, 2) the English digest, 3) the Russian lesson the assistant will receive.

For EACH lesson you are given, check part 3 against part 1 (use part 2 only to
locate where an error entered) and report:

- **Unsupported**: statements in the Russian lesson that the transcript does not
  support (invented steps, values, names, API calls). Quote the Russian line and
  say what the transcript actually says (short quote).
- **Wrong**: facts that contradict the transcript (numbers, order of steps,
  which button/property).
- **Missed**: important tips, warnings or steps present in the transcript but
  absent from the lesson (max 3, only the valuable ones).
- **Terminology**: Russian UI names that look wrong or untranslated; code or API
  identifiers that are clearly mangled. Remember the transcript is speech-to-text,
  so identifiers may have been reconstructed — flag identifiers that look guessed.
- **Danger for the assistant**: advice that would make a novice or the assistant
  do something harmful or silly in R-Pro (for example Python 3 syntax in code for
  a Python 2.7 environment, or features that do not exist in version 4.x).
- Scores 1-5: **fidelity** (5 = every claim traceable to the transcript) and
  **usefulness** for an R-Pro novice asking a how-to question (5 = a clear,
  non-obvious, correct procedure or trick; 1 = filler or irrelevant to R-Pro).
- **Verdict**: keep / fix (name the exact fixes) / drop.

Be specific and brief; evidence beats adjectives. If something is fine, say "ok".

Write one file `work/judge/fidelity_<K>.md` (K is given in your task) with a
`##` section per lesson in this exact shape, and at the end a markdown table
`| slug | fidelity | usefulness | verdict |`. Then reply with only the table.
