"""
Regression tests for Board.wait_for_trigger_button_down()/_up()'s
clear()-then-wait() race.

trig_cb() (a GPIO interrupt callback, its own thread/context) can fire an
edge - setting the Event and updating Board.trigger_button - at any time,
including in the narrow window between a caller's previous wait_for_*()
returning and its *next* wait_for_*() call starting (e.g. while
board.audio.start() is still opening the recording device in
NomadRightApplication.run()). The old clear()-then-wait() implementation
silently discarded any edge that fired during that window: clear() wipes
an already-set Event with no way to tell it apart from one that simply
hasn't fired yet, so wait() then blocks for a *new* edge that may never
come. On real hardware this reproduced as a worker's brief press-release
leaving the app stuck showing "[LISTENING]" and recording for many extra
seconds, until a second press-release finally supplied a "fresh" edge.

These tests exercise Board.wait_for_trigger_button_down()/_up() directly
via a minimal stand-in object (not a real Board instance - Board.__init__
enumerates real ALSA devices, which these tests have no need for and no
hardware to satisfy).
"""
import threading
import time
import unittest

from pocketinfer.boards.base import Board


class _FakeButtonBoard:
    """Just enough state for Board.wait_for_trigger_button_down/up to operate
    on - mirrors what Board.__init__ sets up and what trig_cb() maintains."""

    def __init__(self):
        self.trigger_button = False
        self.trigger_button_down = threading.Event()
        self.trigger_button_up = threading.Event()

    def press(self):
        self.trigger_button = True
        self.trigger_button_down.set()

    def release(self):
        self.trigger_button = False
        self.trigger_button_up.set()


# Bind the real (unbound) implementations onto the lightweight stand-in so
# these tests exercise the actual production code, not a re-implementation
# of it.
_FakeButtonBoard.wait_for_trigger_button_down = Board.wait_for_trigger_button_down
_FakeButtonBoard.wait_for_trigger_button_up = Board.wait_for_trigger_button_up


class TestTriggerButtonRace(unittest.TestCase):
    def test_down_edge_that_fired_before_the_wait_call_is_not_lost(self):
        b = _FakeButtonBoard()
        b.press()  # edge fires before anyone is waiting on it
        start = time.monotonic()
        b.wait_for_trigger_button_down(timeout=3.0)
        self.assertLess(
            time.monotonic() - start, 0.5,
            "a down-edge that fired before wait_for_trigger_button_down() was "
            "called must be observed immediately via self.trigger_button, not "
            "lost by clear()",
        )

    def test_up_edge_that_fired_before_the_wait_call_is_not_lost(self):
        """Reproduces the real on-device symptom: the release happened
        before the app got around to calling wait_for_trigger_button_up()
        (e.g. audio.start() was still opening the mic)."""
        b = _FakeButtonBoard()
        b.press()
        b.wait_for_trigger_button_down()
        b.release()  # release races ahead of the app calling wait_for_up()

        result = {}

        def waiter():
            t0 = time.monotonic()
            b.wait_for_trigger_button_up(timeout=3.0)
            result["elapsed"] = time.monotonic() - t0

        th = threading.Thread(target=waiter)
        th.start()
        th.join(timeout=3.5)
        self.assertIn("elapsed", result, "wait_for_trigger_button_up() never returned")
        self.assertLess(
            result["elapsed"], 0.5,
            "a release that happened before wait_for_trigger_button_up() was "
            "called must be observed immediately, not block for a new edge "
            "that will never come (the 'stuck in Listening' bug)",
        )

    def test_down_then_up_normal_sequence_still_works(self):
        """Sanity check that the fix didn't break the ordinary case where
        the caller is already waiting when the edge fires."""
        b = _FakeButtonBoard()

        def presser():
            time.sleep(0.05)
            b.press()

        threading.Thread(target=presser, daemon=True).start()
        start = time.monotonic()
        b.wait_for_trigger_button_down(timeout=3.0)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertTrue(b.trigger_button)

        def releaser():
            time.sleep(0.05)
            b.release()

        threading.Thread(target=releaser, daemon=True).start()
        start = time.monotonic()
        b.wait_for_trigger_button_up(timeout=3.0)
        self.assertLess(time.monotonic() - start, 1.0)
        self.assertFalse(b.trigger_button)

    def test_repeated_press_release_cycles_never_stick(self):
        """The interaction must survive many consecutive turns without
        drifting into a stuck state - see requirement that the UI must not
        become stuck in Listening after repeated use."""
        b = _FakeButtonBoard()
        for _ in range(25):
            b.press()
            b.wait_for_trigger_button_down(timeout=1.0)
            b.release()
            start = time.monotonic()
            b.wait_for_trigger_button_up(timeout=1.0)
            self.assertLess(time.monotonic() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
