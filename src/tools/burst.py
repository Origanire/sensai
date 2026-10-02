## @file burst.py
# @brief Detection of chat activity bursts, used as automatic highlights.
#
# The anonymous chat connection gives no access to the real viewer count,
# so the audience is estimated from the number of distinct chatters over
# the last few minutes. The burst threshold scales with that audience:
# 15 messages in 10 seconds is a lot for 5 chatters, nothing for 300.

import math
from collections import deque


## @brief Sliding-window detector of message bursts.
class BurstDetector:
    ## @brief Build the detector.
    #
    # @param window Size of the burst window, in seconds.
    # @param audience_window Window used to count active chatters, in seconds.
    # @param ratio Messages required in the burst window per active chatter.
    # @param min_messages Threshold floor, so a near-empty chat never bursts.
    # @param cooldown Time after a burst during which no new one is reported,
    #        in seconds, so a single burst is not logged several times.
    def __init__(self, window, audience_window, ratio, min_messages, cooldown):
        ## @brief Size of the burst window, in seconds.
        self.window = window
        ## @brief Window used to count active chatters, in seconds.
        self.audience_window = audience_window
        ## @brief Messages required per active chatter.
        self.ratio = ratio
        ## @brief Threshold floor.
        self.min_messages = min_messages
        ## @brief Silence after a burst, in seconds.
        self.cooldown = cooldown
        ## @brief Timestamps of the messages inside the burst window.
        self.recent = deque()
        ## @brief Last message timestamp of each chatter.
        self.last_seen = {}
        ## @brief Timestamp of the last reported burst, or None.
        self.last_burst = None
        ## @brief Timestamp of the first message seen, or None.
        self.started = None

    ## @brief Number of distinct chatters active over the audience window.
    #
    # Forgets the chatters who left the window, so the dictionary does not
    # grow for the whole stream.
    #
    # @param now Current timestamp, in seconds.
    # @return Number of active chatters.
    def audience(self, now):
        limit = now - self.audience_window
        for viewer_id in [v for v, seen in self.last_seen.items() if seen < limit]:
            del self.last_seen[viewer_id]
        return len(self.last_seen)

    ## @brief Messages needed in the burst window for the current audience.
    #
    # @param now Current timestamp, in seconds.
    # @return Threshold, in messages.
    def threshold(self, now):
        return max(self.min_messages, math.ceil(self.audience(now) * self.ratio))

    ## @brief Record a message and tell whether it completes a burst.
    #
    # Nothing is reported until a full audience window has been observed:
    # right after launch the audience is underestimated, and the regular
    # chat flow would pass for a burst.
    #
    # @param viewer_id Twitch identifier of the author.
    # @param sent_at Timestamp of the message, in seconds.
    # @return A (messages, threshold, audience) tuple when a burst is
    #         detected, None otherwise.
    def add(self, viewer_id, sent_at):
        if self.started is None:
            self.started = sent_at
        self.last_seen[viewer_id] = sent_at
        self.recent.append(sent_at)
        while self.recent and self.recent[0] <= sent_at - self.window:
            self.recent.popleft()

        if sent_at - self.started < self.audience_window:
            return None
        if self.last_burst is not None and sent_at - self.last_burst < self.cooldown:
            return None

        threshold = self.threshold(sent_at)
        if len(self.recent) < threshold:
            return None

        self.last_burst = sent_at
        return len(self.recent), threshold, len(self.last_seen)
