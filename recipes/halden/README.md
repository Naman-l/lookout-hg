# Halden's import recipe (bootstrap)

The approved cleaning steps, one script per defect, replayed by `make build-data` with no model and no key.

This is the **bootstrap** recipe: written by hand in exactly the shape the Data steward produces
(`steps/NN_name.py`, each with a docstring that names the defect, the rule and the consequence), so the
database exists before the steward does. `answers.yaml` holds the decisions a person would otherwise be asked
for on a flashcard (which legacy ids are the same company, what a forecast name maps to), each with who answered
and why.

Each step is `run(ctx)`: it reads and writes tables on `ctx.t`, records every defect with `ctx.issue(...)` and
every dropped row with `ctx.drop(...)`. The raw tables (`raw_*`) are loaded once and never changed. After the
last step the load gate runs; a failed check writes no database.

## Extraction records (`extractions/`)

The supplier quotes (emails and their PDFs) are turned into offers by an extractor, and the extractor's work is a file: `extractions/<message id>.yaml`, one offer per entry, each citing the exact line of the document it was read from. **Model-assisted, cached as a replayable recipe, verified in code.**

- The build replays the files with no model and no key (step `22_extractions.py`).
- On every build, every price is checked in code: the cited line must be in the document, the raw price must be on it, and the offer's part (or the supplier's model number) must stand within 40 lines before it (or in the email's subject). A record that fails stops the build, naming the line.
- The files here are marked `by: transcribed`: typed once from the documents (by hand, in the first version of this step), then checked by the same rule as everything else.
- `python -m app.domain.imports.extract <message id>` asks a model to read one message into a new file. What it returns is checked the same way; entries that fail are listed under `rejected` with the reason. The file is written `by: model, reviewed: false` and is not loaded until a person has read it against the document and set `reviewed: true`.
