# Independent interpretation cases

These small, hand-authored fixtures support development review of MLView's
interpretation guidance. They are independent of the held-out task set and are
not native-assistant outputs, scores, or human adjudication. Do not execute or
import them; inspect them as source.

[`expected-review.json`](expected-review.json) supplies questions and semantic
boundaries for a reviewer. It deliberately avoids prescribing artifact wording
or node layout. A useful forward test gives the skill and one case to a native
assistant, preserves the resulting artifact separately, and leaves every
answer pending human review.
