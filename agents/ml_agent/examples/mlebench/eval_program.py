# -*- coding: utf-8 -*-
"""
This file define
"""
import os
import json
from pathlib import Path
from typing import Any

import pandas as pd
from mlebench.data import get_leaderboard, is_dataset_prepared
from mlebench.registry import registry
from mlebench.utils import (
    load_answers,
    read_csv,
)


def _is_truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _load_competition(data_dir: Path, competition_id: str):
    new_registry = registry.set_data_dir(data_dir)
    competition = new_registry.get_competition(competition_id)

    if not is_dataset_prepared(competition, grading_only=True):
        raise ValueError(
            f"Dataset for competition `{competition.id}` is not prepared! "
        )

    return competition


def _score_with_grader(competition, submission_df: pd.DataFrame, answers: Any) -> float:
    score = competition.grader(submission_df, answers)
    if score is None:
        raise ValueError(f"Score for competition `{competition.id}` was not found.")
    return float(score)


def _infer_is_lower_better(competition) -> bool:
    """
    Infer score direction using the mle-bench grader.

    V1 intentionally keeps this inference source, but removes leaderboard-based
    normalization from the returned LoongFlow score.
    """
    competition_leaderboard = get_leaderboard(competition)
    return bool(competition.grader.is_lower_better(competition_leaderboard))


def _score_oof_submission(
    competition, oof_submission_df: pd.DataFrame, oof_answer_df: pd.DataFrame
) -> float:
    errors = []
    candidate_answers = [("full_oof_answer", oof_answer_df)]

    submission_cols = list(oof_submission_df.columns)
    if submission_cols and set(submission_cols).issubset(set(oof_answer_df.columns)):
        subset_df = oof_answer_df[submission_cols]
        if list(subset_df.columns) == submission_cols:
            candidate_answers.append(("submission_columns_subset", subset_df))

    seen = set()
    for name, answers in candidate_answers:
        key = (name, tuple(answers.columns), len(answers))
        if key in seen:
            continue
        seen.add(key)
        try:
            return _score_with_grader(competition, oof_submission_df, answers)
        except Exception as e:
            errors.append(f"{name}: {e}")

    raise ValueError(
        "OOF grading failed. Tried multiple answer formats. "
        + "; ".join(errors)
    )


def _write_test_debug_result(output_file: Path, payload: dict[str, Any]) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def evaluate(task_data_path, best_code_path, artifacts):
    """
    common evaluate function
    """
    _ = best_code_path  # not used by this evaluator
    artifacts = artifacts or {}

    required_keys = [
        "submission_file_path",
        "oof_submission_file_path",
        "oof_answer_file_path",
        "oof_coverage",
    ]
    missing = [k for k in required_keys if k not in artifacts]
    if missing:
        return {
            "status": "validation_failed",
            "summary": f"Missing required workflow artifacts: {missing}",
            "score": 0.0,
            "metrics": {},
            "artifacts": {
                "stderr": "Evaluation failed completely",
                "workflow_result": artifacts,
            },
        }

    submission_file_path = Path(artifacts["submission_file_path"])
    oof_submission_file_path = Path(artifacts["oof_submission_file_path"])
    oof_answer_file_path = Path(artifacts["oof_answer_file_path"])

    for key, path in [
        ("submission_file_path", submission_file_path),
        ("oof_submission_file_path", oof_submission_file_path),
        ("oof_answer_file_path", oof_answer_file_path),
    ]:
        if not path.is_file() or path.suffix.lower() != ".csv":
            return {
                "status": "validation_failed",
                "summary": f"Invalid csv path for {key}: {path}",
                "score": 0.0,
                "metrics": {},
                "artifacts": {
                    "workflow_result": artifacts,
                },
            }

    try:
        oof_coverage = float(artifacts.get("oof_coverage"))
    except Exception:
        return {
            "status": "validation_failed",
            "summary": f"Invalid oof_coverage: {artifacts.get('oof_coverage')}",
            "score": 0.0,
            "metrics": {},
            "artifacts": {
                "workflow_result": artifacts,
            },
        }

    if oof_coverage < 0.0 or oof_coverage > 1.0:
        return {
            "status": "validation_failed",
            "summary": f"oof_coverage must be in [0,1], got {oof_coverage}",
            "score": 0.0,
            "metrics": {},
            "artifacts": {
                "workflow_result": artifacts,
            },
        }

    data_dir = Path(task_data_path).parent.parent.parent
    competition_id = Path(task_data_path).parent.parent.name

    try:
        competition = _load_competition(data_dir, competition_id)
        oof_submission_df = read_csv(oof_submission_file_path)
        oof_answer_df = read_csv(oof_answer_file_path)

        oof_raw_score = _score_oof_submission(
            competition=competition,
            oof_submission_df=oof_submission_df,
            oof_answer_df=oof_answer_df,
        )
        is_lower_better = _infer_is_lower_better(competition)
        final_score = -oof_raw_score if is_lower_better else oof_raw_score

    except Exception as e:
        return {
            "status": "execution_failed",
            "summary": f"Program execution failed: {str(e)}",
            "score": 0.0,
            "metrics": {},
            "artifacts": {
                "stderr": f"OOF evaluation failed completely: {str(e)}",
                "oof_submission_file_path": str(oof_submission_file_path),
                "oof_answer_file_path": str(oof_answer_file_path),
                "submission_file_path": str(submission_file_path),
            },
        }

    if _is_truthy_env("MLEBENCH_COMPUTE_TEST_SCORE", default=False):
        test_result_path = submission_file_path.parent / "submission_test_result.json"
        try:
            test_submission_df = read_csv(submission_file_path)
            test_answers = load_answers(competition.answers)
            test_raw_score = _score_with_grader(
                competition=competition,
                submission_df=test_submission_df,
                answers=test_answers,
            )
            _write_test_debug_result(test_result_path, {
                "raw_score": test_raw_score,
                "is_lower_better": is_lower_better,
                "score_mode": "raw_metric_sign_adjusted",
            })
        except Exception as e:
            _write_test_debug_result(test_result_path, {
                "error": str(e),
            })

    return {
        "status": "success",
        "summary": "OOF evaluation successful",
        "score": final_score,
        "metrics": {
            "oof_raw_score": oof_raw_score,
            "oof_coverage": oof_coverage,
            "is_lower_better": is_lower_better,
            "score_mode": "raw_metric_sign_adjusted",
        },
        "artifacts": {
            "oof_submission_file_path": str(oof_submission_file_path),
            "oof_answer_file_path": str(oof_answer_file_path),
            "submission_file_path": str(submission_file_path),
        },
    }
