import sys
sys.path.insert(0, ".")
import unittest, os, subprocess, tempfile
from pathlib import Path
from unittest.mock import patch
from app import cli

class ControllerManagementChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.original = cli.ROOT
        cli.ROOT = self.root
        (self.root / 'specs').mkdir()
        (self.root / 'runs').mkdir()
        cli.write(self.root / 'specs/sobel_fast.json', {'design_id': 'sobel_fast', 'top_module': 'tt_um_cf_sobel_fast'})
        cli.write(self.root / 'verification.freeze.json', {'specs/sobel_fast.json': cli.digest(self.root / 'specs/sobel_fast.json')})
        self.run = cli.new_run({'design_id': 'sobel_fast'})['run_id']

    def tearDown(self):
        cli.ROOT = self.original
        self.temp.cleanup()

    def candidate(self):
        return cli.submit_rtl({'run_id': self.run, 'source': 'module tt_um_cf_sobel_fast; endmodule'})

    def test_cancel_job_without_physical_global_lock_block(self):
        c = self.candidate()
        cand_p = cli.candidate_path(self.run, c['candidate_id'])
        job_p = cand_p / "physical/job.json"
        cli.write(job_p, {"job_id": "p-1234", "state": "RUNNING", "worker_pid": os.getpid()})

        # Simulate physical-global lock being held by a mock worker
        with cli.lock("physical-global"):
            with patch("app.cli.subprocess.run") as mock_run, patch("os.kill") as mock_kill:
                res = cli.cancel_job({"run_id": self.run, "candidate_id": c['candidate_id']})
                self.assertEqual(res["state"], "FLOW_CANCELLED")
                mock_run.assert_called_with(["docker", "stop", "--time", "5", "chipforge-p-1234"], capture_output=True)

    def test_recover_dead_worker_job(self):
        c = self.candidate()
        cand_p = cli.candidate_path(self.run, c['candidate_id'])
        job_p = cand_p / "physical/job.json"
        cli.write(job_p, {"job_id": "p-5678", "state": "RUNNING", "worker_pid": 99999999})

        with patch("app.cli.subprocess.run") as mock_run:
            res = cli.recover_job({"run_id": self.run, "candidate_id": c['candidate_id']})
            self.assertEqual(res["state"], "FLOW_FAILED_RECOVERED")
            mock_run.assert_called_with(["docker", "stop", "--time", "5", "chipforge-p-5678"], capture_output=True)

    def test_signed_off_state_transition_validation(self):
        c = self.candidate()
        # Attempt to sign off when RTL has not passed -> Must raise ValueError
        with self.assertRaisesRegex(ValueError, "has not passed RTL verification"):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

        cand_p = cli.candidate_path(self.run, c['candidate_id'])
        cli.write(cand_p / "verification/result.json", {"status": "RTL_PASS"})

        # Physical job not completed -> Must raise ValueError
        with self.assertRaisesRegex(ValueError, "physical job is not completed"):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

        # Physical completed, but gate-level verification missing -> Must raise ValueError
        cli.write(cand_p / "physical/job.json", {"state": "FLOW_COMPLETED"})
        with self.assertRaisesRegex(ValueError, "lacks gate-level verification"):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

        # Gate verification present, but final acceptance signoff report missing -> Must raise ValueError
        cli.write(cand_p / "verification_gate/protocol_metrics.json", {"kind": "gate_level_simulation"})
        with self.assertRaisesRegex(ValueError, "final_acceptance_signoff.json does not exist"):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

        # Final acceptance signoff present but candidate is NOT PASS -> Must raise ValueError
        signoff_f = self.root / "reports/final_acceptance_signoff.json"
        cli.write(signoff_f, {
            "designs": {
                "sobel_fast": {
                    "candidate_id": c['candidate_id'],
                    "overall_status": "FAIL"
                }
            }
        })
        with self.assertRaisesRegex(ValueError, "is not PASS in formal acceptance signoff"):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

        # A handwritten PASS without current XML, identity or evidence cannot sign off.
        cli.write(signoff_f, {
            "designs": {
                "sobel_fast": {
                    "candidate_id": c['candidate_id'],
                    "overall_status": "PASS"
                }
            }
        })
        with self.assertRaises(ValueError):
            cli.update_run_state({"run_id": self.run, "state": "SIGNED_OFF", "winning_candidate_id": c['candidate_id']})

if __name__ == "__main__":
    unittest.main()
