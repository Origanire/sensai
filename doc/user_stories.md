# User stories

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
