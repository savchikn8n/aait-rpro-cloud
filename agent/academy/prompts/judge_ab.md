# Judge 3: does adding the Academy lessons help the assistant's search?

Context. A small local AI assistant for R-Pro (a Russian-localized fork of
Visual Components 4.x) answers newcomers' how-to questions. Before answering it
is automatically given the top-2 text fragments found by keyword search. Until
now the search covered only R-Pro's own Russian help. We added short Russian
lessons built from Visual Components Academy videos (source `academy`).

`work/judge/ab_questions.md` lists 25 typical newcomer questions. For each, OFF =
the top-2 fragments from the help only; ON = the top-2 when the lessons are also
searched. Fragment text is cut to 700 characters.

For EACH question decide, as a domain expert who knows Visual Components:
- **Relevance** of OFF and ON to the question, each 0-3 (0 = unrelated, 3 = directly
  answers it). A fragment that is plausible-sounding but about a different task
  counts 0 or 1 — a wrong fragment is worse than no fragment.
- **Winner**: ON-better / OFF-better / same.
- A short reason; mention concrete misfires (a lesson ranked high that is about
  something else, or a help page that was wrongly displaced).

Then give an overall judgement:
1. Average relevance OFF vs ON and the win/loss counts.
2. Should lessons be searched by default? Choose one and justify with the data:
   (a) yes, on by default; (b) only through the explicit tool source, not in the
   automatic top-2; (c) automatic top-2 allows at most one lesson fragment next to
   one help fragment; (d) no.
3. Concrete ranking or content fixes you would make (for example: lesson
   fragments should only be used for tips; require a minimum score margin;
   drop the keywords line; boost help over lessons by a factor).

Write the full per-question table and judgement to `work/judge/ab_verdict.md`.
Reply with only the overall judgement (item 1-3, max 12 lines).
