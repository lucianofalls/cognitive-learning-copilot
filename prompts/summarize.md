Merge the new transcript text into the existing meeting summary.

If the new text contains ANY substantive statement (a plan, a claim, an
opinion, a proposal, a question, a risk, a decision), it MUST be added to
exactly one list below. An empty summary is only correct when the new
text truly has no substantive content (e.g. only greetings or filler).
Do not leave a clearly substantive sentence unclassified just because
you are unsure which category fits best — pick the closest one:

- facts: statements presented as already true.
- proposals: suggestions or plans not yet agreed on.
- assumptions: things taken for granted but not confirmed.
- confirmed_decisions: something the group explicitly agreed on.
- risks: concerns, problems, or things that could go wrong.
- open_questions: unresolved questions needing an answer.
- action_items: concrete next steps assigned or implied.

Keep existing items unless the new text explicitly contradicts or
resolves them (e.g., an open_question that gets answered should move to
facts or confirmed_decisions, not stay duplicated).

Always set the topic field to a short phrase describing what is
currently being discussed, updating it if the topic shifted.

Do not invent information that is not present in the transcript. Do not
expose hidden reasoning. Output only the updated summary.
