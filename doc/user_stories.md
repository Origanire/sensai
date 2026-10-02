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

## Inter-agent communication: Chat <-> Internet (#43)

**As a viewer, I want to ask a question with `!search` in the Twitch chat, so
that I get an up-to-date answer from the web without leaving the stream.**

Acceptance criteria:
- Typing `!search <question>` in the chat makes Sensai reply in the chat,
  addressed to me (`@<viewer> ...`), with at least one source URL.
- The reply is never longer than 500 characters: a longer answer ends with
  `...` followed by its source URL instead of being rejected by Twitch.
- When the web search or the model is unavailable, Sensai replies
  "Recherche indisponible pour le moment." and keeps answering later messages.

**As a streamer, I want `!search` to be limited by a cooldown, so that viewers
cannot flood the chat or freeze my bot with searches.**

Acceptance criteria:
- With `internet_agent.cooldown_seconds: 30`, a second `!search` sent less than
  30 seconds after the previous one, by any viewer, gets no reply in the chat
  and is logged as ignored in the terminal.
- A `!search` sent after the cooldown is answered normally.
- `!search` without a question gets the usage message
  `usage : !search <question>` and starts no search.

## Inter-agent communication: OBS <-> Internet (#44)

**As a streamer, I want the answer to a viewer's `!search` to appear on my OBS
overlay, so that the whole audience sees it on screen, not only in the chat.**

Acceptance criteria:
- With OBS open, its WebSocket server enabled and a text source named
  `SensaiOverlay`, the text of that source changes after each successful
  `!search`.
- The overlay text is one or two sentences, at most 160 characters, with no
  URL and no list.
- When the search fails, the overlay keeps its previous text instead of
  showing an error.

**As a streamer, I want the bot to keep working when OBS is closed or
misconfigured, so that an overlay problem never takes down the chat bot
during a live stream.**

Acceptance criteria:
- With OBS closed, `!search` still gets its reply in the chat, and the
  terminal shows `[OBS] injoignable sur <host>:<port>, overlay non mis à jour.`
- With a wrong source name or WebSocket password, the terminal shows a
  message naming the problem (source not found, wrong password), with no
  traceback, and the agent keeps reading the chat.
- Changing `obs.host`, `obs.port` or `obs.source_name` in `config.yaml` (or
  setting `obs.enabled: false`) takes effect at the next start of the agent,
  without touching the code.
