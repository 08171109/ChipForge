import json
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch
from app import cli


class ExecutionChecks(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.original=cli.ROOT
        cli.ROOT=self.root
        (self.root/'specs').mkdir()
        (self.root/'runs').mkdir()
        cli.write(self.root/'specs/sobel_fast.json',{'design_id':'sobel_fast','top_module':'tt_um_cf_sobel_fast'})
        cli.write(self.root/'verification.freeze.json',{'specs/sobel_fast.json':cli.digest(self.root/'specs/sobel_fast.json')})
        self.run=cli.new_run({'design_id':'sobel_fast'})['run_id']

    def tearDown(self):
        cli.ROOT=self.original
        self.temp.cleanup()

    def candidate(self):
        return cli.submit_rtl({'run_id':self.run,'source':'module tt_um_cf_sobel_fast; endmodule'})

    def test_source_immutability_and_frozen_contract(self):
        c=self.candidate()
        path=cli.candidate_path(self.run,c['candidate_id'])
        (path/'rtl/project.v').write_text('changed')
        with self.assertRaisesRegex(ValueError,'source changed'):
            cli.candidate_path(self.run,c['candidate_id'])
        (self.root/'specs/sobel_fast.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Frozen'):
            self.candidate()

    def test_global_budget_does_not_reset_with_new_run(self):
        for _ in range(20): self.candidate()
        second=cli.new_run({'design_id':'sobel_fast'})['run_id']
        with self.assertRaisesRegex(ValueError,'budget exhausted'):
            cli.submit_rtl({'run_id':second,'source':'module x; endmodule'})

    def test_missing_test_results_cannot_pass(self):
        c=self.candidate()
        with patch('app.cli.subprocess.run') as invoke:
            invoke.return_value.returncode=0
            result=cli.validate({'run_id':self.run,'candidate_id':c['candidate_id']})
        self.assertEqual(result['status'],'RTL_FAIL')
        with self.assertRaisesRegex(ValueError,'verification required'):
            cli.harden({'run_id':self.run,'candidate_id':c['candidate_id']})

    def test_path_escape_rejected(self):
        for value in ['../outside','/tmp','a/b','',123]:
            with self.assertRaises(ValueError): cli.valid_id(value)

    def test_timeout_stops_only_owned_simulation_container(self):
        c=self.candidate()
        with patch('app.cli.subprocess.run') as invoke:
            invoke.side_effect=[subprocess.TimeoutExpired('docker',600), subprocess.CompletedProcess([],0)]
            result=cli.validate({'run_id':self.run,'candidate_id':c['candidate_id']})
        self.assertEqual(result['status'],'RTL_FAIL')
        self.assertEqual(result['exit_code'],124)
        launch=invoke.call_args_list[0].args[0]
        container=launch[launch.index('--name')+1]
        self.assertTrue(container.startswith('chipforge-sim-'))
        self.assertEqual(invoke.call_args_list[1].args[0],['docker','stop','--time','10',container])


if __name__=='__main__': unittest.main()
