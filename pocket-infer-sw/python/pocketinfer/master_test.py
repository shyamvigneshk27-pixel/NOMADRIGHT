"""
Regression tests for master.py's stop_conflicting_instances() self-stop bug.

pocketinfer.service's ExecStart is this very module (the unit runs
.../bin/pocketinfer-service, whose entry point is run_master), so the
"stop any background instance holding the hardware locks" step was issuing
`systemctl stop pocketinfer.service` against the process running it. Every
`systemctl start pocketinfer.service` therefore got SIGTERMed about two
seconds in, before service_main() was ever reached - the application never
launched from the service at all, only from a manual terminal run. Because a
clean SIGTERM stop isn't a failure, Restart=on-failure never fired and the
unit simply stayed dead.

That made the service a no-op that silently discarded every code change
shipped to it, which is why UI work kept "not showing up" on the LCD.
"""
import unittest
from unittest.mock import patch, mock_open

from pocketinfer import master


class TestServiceSelfDetection(unittest.TestCase):
    """_process_is_the_systemd_service() is what tells the two cases apart."""

    def test_detects_itself_via_cgroup_when_run_as_the_service(self):
        cgroup = "0::/system.slice/pocketinfer.service\n"
        with patch("builtins.open", mock_open(read_data=cgroup)):
            self.assertTrue(master._process_is_the_systemd_service())

    def test_interactive_terminal_run_is_not_the_service(self):
        cgroup = "0::/user.slice/user-1000.slice/session-17.scope\n"
        with patch("builtins.open", mock_open(read_data=cgroup)), \
             patch.dict("os.environ", {}, clear=True):
            self.assertFalse(master._process_is_the_systemd_service())

    def test_unrelated_unit_is_not_treated_as_this_service(self):
        """A different systemd unit that happens to run this code must still
        be allowed to stop a genuinely conflicting pocketinfer.service."""
        cgroup = "0::/system.slice/some-other.service\n"
        with patch("builtins.open", mock_open(read_data=cgroup)), \
             patch.dict("os.environ", {}, clear=True):
            self.assertFalse(master._process_is_the_systemd_service())

    def test_unreadable_cgroup_without_systemd_env_is_not_the_service(self):
        with patch("builtins.open", side_effect=OSError("no /proc")), \
             patch.dict("os.environ", {}, clear=True):
            self.assertFalse(master._process_is_the_systemd_service())


class TestStopConflictingInstances(unittest.TestCase):
    """The actual behavioural guarantee: the service must never stop itself,
    but an interactive run must still stop a real background instance."""

    def test_service_does_not_stop_itself(self):
        with patch.object(master, "_process_is_the_systemd_service", return_value=True), \
             patch("subprocess.run") as run:
            master.stop_conflicting_instances()
        self.assertEqual(
            run.call_count, 0,
            "running as pocketinfer.service must not shell out to systemctl at "
            "all - the stop it used to issue killed this very process before "
            "the application could start",
        )

    def test_interactive_run_still_stops_a_real_background_service(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            class Res:
                stdout = "active\n"
            return Res()

        with patch.object(master, "_process_is_the_systemd_service", return_value=False), \
             patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            master.stop_conflicting_instances()

        self.assertIn(
            ["systemctl", "stop", "pocketinfer.service"], calls,
            "an interactive run must still release the hardware locks held by "
            "a background instance - that is what this function is for",
        )

    def test_interactive_run_with_inactive_service_stops_nothing(self):
        def fake_run(cmd, **kwargs):
            class Res:
                stdout = "inactive\n"
            return Res()

        with patch.object(master, "_process_is_the_systemd_service", return_value=False), \
             patch("subprocess.run", side_effect=fake_run) as run:
            master.stop_conflicting_instances()

        for call in run.call_args_list:
            self.assertNotIn("stop", call.args[0])


class TestDefaultApplication(unittest.TestCase):
    def test_bare_service_launch_targets_nomadright(self):
        """pocketinfer.service's ExecStart passes no --app, so this default is
        what the device actually boots into. It used to be HearTheWorld, which
        meant that even with the self-stop bug fixed the service would have
        come up running the wrong application."""
        parser = None
        import argparse
        # Rebuild the same parser run_master() uses, without executing it.
        parser = argparse.ArgumentParser()
        parser.add_argument('--app', type=str, default="NomadRight")
        self.assertEqual(parser.parse_args([]).app, "NomadRight")

    def test_run_master_declares_nomadright_as_its_default(self):
        import inspect
        src = inspect.getsource(master.run_master)
        self.assertIn('default="NomadRight"', src)


if __name__ == "__main__":
    unittest.main()
