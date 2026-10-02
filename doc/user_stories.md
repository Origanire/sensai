# User stories

## Internet agent — rapports automatiques (#41)

**As a streamer, I want the assistant to automatically research my stream
topics on a schedule, so that I have fresh talking points without manually
searching.**

Acceptance criteria:
- With `interval_minutes: 2` and two topics in `config.yaml`, one
  `report_<topic>_<YYYY-MM-DD>_<HHhMM>.md` file per topic appears in
  `reports/` within 2 minutes of `/reports start`, then a new one per topic
  every 2 minutes, with no further action.
- Every report contains a title, its generation date and time, 3 to 5 key
  points, and a "Sources" section listing the URLs actually returned by the
  web search.
- Every key point ends with the number of the source it comes from (e.g.
  `[2]`), and that number exists in the "Sources" section.
- If the network or Ollama is unavailable during a cycle, no report is written
  for the affected topic, the error is printed and shown by `/reports status`,
  and a report is produced again at the next cycle once the service is back.

**As a user, I want to start/stop the scheduled reports from the CLI, so that
I control when background network activity happens.**

Acceptance criteria:
- No web request is made for reports until `/reports start` is typed.
- `/reports start` gives the prompt back immediately; while a report is being
  generated, a regular chat message still gets its answer.
- `/reports status` says whether the reports are active and shows the topic
  being processed, or the time of the next cycle when idle.
- After `/reports stop` (or `exit`), at most the report already being written
  is finished, and no new file appears in `reports/` afterwards.
- A second `/reports start` while the loop is running is refused instead of
  launching a second loop.

**As a streamer, I want to choose my research topics and their frequency in
a configuration file, so that the watch follows my next streams without
touching the code.**

Acceptance criteria:
- Editing `scheduled_reports.topics` or `interval_minutes` in `config.yaml`
  then typing `/reports stop` and `/reports start` applies the new values,
  as shown by `/reports status`.
- A `config.yaml` without a `scheduled_reports` section still starts the CLI
  normally; `/reports start` then explains that no topic is configured.
