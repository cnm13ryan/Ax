# Copyright (c) Meta Platforms, Inc. and affiliates.
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

import logging
from logging import Logger
from unittest.mock import patch

import pandas as pd
from ax.core.base_trial import TrialStatus
from ax.core.data import Data
from ax.modelbridge.generation_strategy import GenerationStep, GenerationStrategy
from ax.modelbridge.registry import Models
from ax.modelbridge.transition_criterion import (
    MaxTrials,
    MinimumPreferenceOccurances,
    MinimumTrialsInStatus,
    TransitionCriterion,
)
from ax.utils.common.logger import get_logger
from ax.utils.common.testutils import TestCase
from ax.utils.testing.core_stubs import get_branin_experiment, get_experiment

logger: Logger = get_logger(__name__)


class TestTransitionCriterion(TestCase):
    def test_minimum_preference_criterion(self) -> None:
        """Tests the minimum preference criterion subcalss of TransitionCriterion."""
        criterion = MinimumPreferenceOccurances(metric_name="m1", threshold=3)
        experiment = get_experiment()
        generation_strategy = GenerationStrategy(
            name="SOBOL::default",
            steps=[
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=-1,
                    completion_criteria=[criterion],
                ),
                GenerationStep(
                    model=Models.GPEI,
                    num_trials=-1,
                    max_parallelism=1,
                ),
            ],
        )
        generation_strategy.experiment = experiment

        # Has not seen enough of each preference
        self.assertFalse(
            generation_strategy._maybe_move_to_next_step(
                raise_data_required_error=False
            )
        )

        data = Data(
            df=pd.DataFrame(
                {
                    "trial_index": range(6),
                    "arm_name": [f"{i}_0" for i in range(6)],
                    "metric_name": ["m1" for _ in range(6)],
                    "mean": [0, 0, 0, 1, 1, 1],
                    "sem": [0 for _ in range(6)],
                }
            )
        )
        with patch.object(experiment, "fetch_data", return_value=data):
            # We have seen three "yes" and three "no"
            self.assertTrue(
                generation_strategy._maybe_move_to_next_step(
                    raise_data_required_error=False
                )
            )
            self.assertEqual(generation_strategy._curr.model, Models.GPEI)

    def test_default_step_criterion_setup(self) -> None:
        """This test ensures that the default completion criterion for GenerationSteps
        is set as expected.

        The default completion criterion is to create two TransitionCriterion, one
        of type `MaximumTrialsInStatus` and one of type `MinimumTrialsInStatus`.
        These are constructed via the inputs of `num_trials`, `enforce_num_trials`,
        and `minimum_trials_observed` on the GenerationStep.
        """
        experiment = get_experiment()
        gs = GenerationStrategy(
            name="SOBOL+GPEI::default",
            steps=[
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=3,
                ),
                GenerationStep(
                    model=Models.GPEI,
                    num_trials=4,
                    max_parallelism=1,
                    min_trials_observed=2,
                    enforce_num_trials=False,
                ),
                GenerationStep(
                    model=Models.GPEI,
                    num_trials=-1,
                    max_parallelism=1,
                ),
            ],
        )
        gs.experiment = experiment

        step_0_expected_transition_criteria = [
            MaxTrials(threshold=3, enforce=True, transition_to="GenerationStep_1"),
            MinimumTrialsInStatus(
                status=TrialStatus.COMPLETED,
                threshold=0,
                transition_to="GenerationStep_1",
            ),
        ]
        step_1_expected_transition_criteria = [
            MaxTrials(threshold=4, enforce=False, transition_to="GenerationStep_2"),
            MinimumTrialsInStatus(
                status=TrialStatus.COMPLETED,
                threshold=2,
                transition_to="GenerationStep_2",
            ),
        ]
        step_2_expected_transition_criteria = [
            MaxTrials(threshold=-1, enforce=True, transition_to="GenerationStep_3"),
            MinimumTrialsInStatus(
                status=TrialStatus.COMPLETED,
                threshold=0,
                transition_to="GenerationStep_3",
            ),
        ]
        self.assertEqual(
            gs._steps[0].transition_criteria, step_0_expected_transition_criteria
        )
        self.assertEqual(
            gs._steps[1].transition_criteria, step_1_expected_transition_criteria
        )
        self.assertEqual(
            gs._steps[2].transition_criteria, step_2_expected_transition_criteria
        )

    def test_minimum_trials_in_status_is_met(self) -> None:
        """Test that the is_met method in MinimumTrialsInStatus works"""
        experiment = get_branin_experiment()
        gs = GenerationStrategy(
            name="SOBOL::default",
            steps=[
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=4,
                    min_trials_observed=2,
                    enforce_num_trials=True,
                ),
                GenerationStep(
                    Models.SOBOL,
                    num_trials=-1,
                    max_parallelism=1,
                ),
            ],
        )
        gs.experiment = experiment

        # Need to add trials to test the transition criteria `is_met` method
        for _i in range(4):
            experiment.new_trial(gs.gen(experiment=experiment))

        # TODO: @mgarrard More comphrensive test of trials_from_node
        node_0_trials = gs._steps[0].trials_from_node
        node_1_trials = gs._steps[1].trials_from_node

        self.assertEqual(len(node_0_trials), 4)
        self.assertEqual(len(node_1_trials), 0)

        # MinimumTrialsInStatus is met should not pass yet, becasue no trials
        # are marked completed
        self.assertFalse(
            gs._steps[0]
            .transition_criteria[1]
            .is_met(experiment, gs._steps[0].trials_from_node)
        )

        # Should pass after two trials are marked completed
        for idx, trial in experiment.trials.items():
            trial.mark_running(no_runner_required=True).mark_completed()
            if idx == 1:
                break
        self.assertTrue(
            gs._steps[0]
            .transition_criteria[1]
            .is_met(experiment, gs._steps[0].trials_from_node)
        )

    def test_max_trials_is_met(self) -> None:
        """Test that the is_met method in MaxTrials works"""
        experiment = get_branin_experiment()
        gs = GenerationStrategy(
            name="SOBOL::default",
            steps=[
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=4,
                    min_trials_observed=0,
                    enforce_num_trials=True,
                ),
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=4,
                    min_trials_observed=0,
                    enforce_num_trials=False,
                ),
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=-1,
                    max_parallelism=1,
                ),
            ],
        )
        gs.experiment = experiment

        # If enforce_num_trials == False, should automatically pass
        self.assertTrue(
            gs._steps[1]
            .transition_criteria[0]
            .is_met(
                experiment=experiment, trials_from_node=gs._steps[1].trials_from_node
            )
        )

        # No trials yet, first step should fail
        self.assertFalse(
            gs._steps[0]
            .transition_criteria[0]
            .is_met(
                experiment=experiment,
                trials_from_node=gs._steps[0].trials_from_node,
            )
        )

        # After adding trials, should pass
        for _i in range(4):
            experiment.new_trial(gs.gen(experiment=experiment))
        self.assertTrue(
            gs._steps[0]
            .transition_criteria[0]
            .is_met(
                experiment=experiment,
                trials_from_node=gs._steps[0].trials_from_node,
            )
        )

        # if num_trials == -1, should always pass
        self.assertTrue(
            gs._steps[2]
            .transition_criteria[0]
            .is_met(
                experiment=experiment, trials_from_node=gs._steps[2].trials_from_node
            )
        )

    def test_max_trials_status_arg(self) -> None:
        """Tests the `only_in_status` argument checks the threshold based on the
        number of trials in specified status instead of all trials (which is the
        default behavior).
        """
        experiment = get_experiment()
        criterion = MaxTrials(
            threshold=5, only_in_status=TrialStatus.RUNNING, enforce=True
        )
        self.assertFalse(criterion.is_met(experiment, trials_from_node={2, 3}))

    def test_trials_from_node_none(self) -> None:
        """Tests MinimumTrialsInStatus and MaxTrials default to experiment
        level trials when trials_from_node is None.
        """
        # TODO: @mgarrard replace with assertion checks that `trials_from_node`
        # cannot be none
        experiment = get_experiment()
        gs = GenerationStrategy(
            name="SOBOL::default",
            steps=[
                GenerationStep(
                    model=Models.SOBOL,
                    num_trials=4,
                    min_trials_observed=2,
                    enforce_num_trials=True,
                ),
            ],
        )
        max_criterion_with_status = MaxTrials(
            threshold=2, enforce=True, only_in_status=TrialStatus.COMPLETED
        )
        max_criterion = MaxTrials(threshold=2, enforce=True)
        warning_msg = (
            "trials_from_node is None, will check threshold on experiment level"
        )

        # no trials so criterion should be false, then add trials to pass criterion
        with self.assertLogs(TransitionCriterion.__module__, logging.WARNING) as logger:
            self.assertFalse(max_criterion.is_met(experiment, trials_from_node=None))
            self.assertTrue(
                any(warning_msg in output for output in logger.output),
                logger.output,
            )
        for _i in range(3):
            experiment.new_trial(gs.gen(experiment=experiment))
        self.assertTrue(max_criterion.is_met(experiment, trials_from_node=None))

        # Before marking trial status it should be false, until trials are completed
        self.assertFalse(
            max_criterion_with_status.is_met(experiment, trials_from_node=None)
        )
        for idx, trial in experiment.trials.items():
            trial._status = TrialStatus.COMPLETED
            if idx == 1:
                break
        self.assertTrue(
            max_criterion_with_status.is_met(experiment, trials_from_node=None)
        )

        # Check MinimumTrialsInStatus
        min_criterion = MinimumTrialsInStatus(threshold=3, status=TrialStatus.COMPLETED)
        with self.assertLogs(TransitionCriterion.__module__, logging.WARNING) as logger:
            self.assertFalse(min_criterion.is_met(experiment, trials_from_node=None))
            self.assertTrue(
                any(warning_msg in output for output in logger.output),
                logger.output,
            )
        for _idx, trial in experiment.trials.items():
            trial._status = TrialStatus.COMPLETED
        self.assertTrue(min_criterion.is_met(experiment, trials_from_node=None))

    def test_repr(self) -> None:
        """Tests that the repr string is correctly formatted for all
        TransitionCriterion child classes.
        """
        max_trials_criterion = MaxTrials(
            threshold=5,
            enforce=True,
            transition_to="GenerationStep_1",
            only_in_status=TrialStatus.COMPLETED,
        )
        self.assertEqual(
            str(max_trials_criterion),
            "MaxTrials(threshold=5, enforce=True, only_in_status="
            + "TrialStatus.COMPLETED, transition_to='GenerationStep_1')",
        )

        minimum_trials_in_status_criterion = MinimumTrialsInStatus(
            status=TrialStatus.COMPLETED,
            threshold=0,
            transition_to="GenerationStep_2",
        )
        self.assertEqual(
            str(minimum_trials_in_status_criterion),
            "MinimumTrialsInStatus(status=TrialStatus.COMPLETED, threshold=0,"
            + " transition_to='GenerationStep_2')",
        )

        minimum_preference_occurances_criterion = MinimumPreferenceOccurances(
            metric_name="m1", threshold=3
        )
        self.assertEqual(
            str(minimum_preference_occurances_criterion),
            "MinimumPreferenceOccurances(metric_name='m1', threshold=3,"
            + " transition_to=None)",
        )