"""Commit 068: real export -> frozen review -> plan -> transactional Apply."""
from __future__ import annotations

from dataclasses import replace
import ast
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from collection_ingestion import IngestionSource
from collection_ingestion_review_model import CollectionIngestionReviewModel
from collection_ingestion_session import build_collection_ingestion_session, finalize_ingestion_session_plan
from collection_plan_apply import apply_collection_change_plan, CollectionPlanStaleStateError
from collection_reconciliation import (
    FirstClearDecision, ReviewAction, ReviewDecision, ReviewState,
    UserFieldResolution, validate_review_decision,
)
from giganticbucket_ingestion import parse_giganticbucket_export
from test_collection_ingestion_session import _Fixture, _entry, _index, _detail
from test_giganticbucket_ingestion import _export, _record, _playthrough


class GiganticBucketProgressTest(unittest.TestCase):
    def session(self, runs=None, records=None):
        record = _record(1, "Quickie World 2", 19279, "SMWCHack")
        record["playthroughs"] = runs if runs is not None else [_playthrough("2:00:00", "May 1, 2026")]
        fixture = _Fixture(records if records is not None else {"19279": {"title": "Quickie World 2"}})
        self.addCleanup(fixture.close)
        before = fixture.processed.read_bytes()
        session = build_collection_ingestion_session(
            fixture.manager, fixture.hints_store,
            _index(_entry(19279, "Quickie World 2"), _entry(100, "Other Hack")),
            giganticbucket=parse_giganticbucket_export(_export(record)),
        )
        self.assertEqual(before, fixture.processed.read_bytes())
        return fixture, session

    def finalize(self, session, decision=None):
        return finalize_ingestion_session_plan(
            session, {decision.group_id: decision} if decision else {},
            catalogue_details=(_detail(19279, "Quickie World 2"), _detail(100, "Other Hack")),
        )

    def apply(self, fixture, plan):
        with patch("kaizoff_provider.KaizOffCatalogueProvider.get_hack", side_effect=AssertionError("Apply called provider")), patch("socket.socket.connect", side_effect=AssertionError("Apply called network")):
            apply_collection_change_plan(plan, fixture.manager, fixture.hints_store)
        return json.loads(fixture.processed.read_text(encoding="utf-8"))

    def decision(self, session, run=None, choices=(), action=ReviewAction.ACCEPT, target=""):
        group = session.groups[0]
        first = None if run is None else FirstClearDecision(
            True, IngestionSource.GIGANTIC_BUCKET if run != "none" else None,
            f"1:{run}" if run != "none" else None,
        )
        return ReviewDecision(group.group_id, action, target_key=target, first_clear=first,
                              user_field_resolutions=tuple(UserFieldResolution(*item) for item in choices))

    def test_single_first_clear_fills_dashboard_time_and_keeps_unknown_state(self):
        fixture, session = self.session(records={"19279": {
            "title": "Quickie World 2", "notes": "My note", "personal_rating": 5,
            "future_local": {"keep": [1]}, "playthroughs": [{"source": "manual", "source_record_id": "old"}],
        }})
        result = self.apply(fixture, self.finalize(session))["19279"]
        self.assertEqual(7200, result["time_to_beat"])
        spec = importlib.util.spec_from_file_location("commit068_dashboard_analytics", Path(__file__).parent / "ui" / "dashboard" / "analytics.py")
        analytics_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(analytics_module)
        analytics = analytics_module.DashboardAnalytics(fixture.manager)
        self.assertEqual(2.0, analytics.load_analytics_data()["avg_time_per_hack"])
        self.assertTrue(result["completed"])
        self.assertEqual("2026-05-01", result["completed_date"])
        self.assertEqual({"keep": [1]}, result["future_local"])
        self.assertEqual("My note", result["notes"])
        self.assertEqual(5, result["personal_rating"])
        self.assertEqual(2, len(result["playthroughs"]))
        self.assertEqual("1:0", result["first_clear_playthrough"]["source_record_id"])

    def test_conflicts_require_explicit_review_and_keep_overrides_survive_apply(self):
        initial = {"19279": {"title": "Quickie World 2", "completed": True,
                              "completed_date": "2026-05-08", "time_to_beat": 3000}}
        for use in (False, True):
            with self.subTest(use=use):
                fixture, session = self.session(records=initial)
                self.assertIn(ReviewState.USER_DATA_CONFLICT, session.groups[0].review_states)
                with self.assertRaises(ValueError):
                    self.finalize(session)
                choice = self.decision(session, choices=(("completed_date", use), ("time_to_beat", use)))
                result = self.apply(fixture, self.finalize(session, choice))["19279"]
                self.assertEqual("2026-05-01" if use else "2026-05-08", result["completed_date"])
                self.assertEqual(7200 if use else 3000, result["time_to_beat"])

    def test_unknown_date_can_complete_without_replacing_existing_date(self):
        fixture, session = self.session([_playthrough("2:00:00", "1/5/2026")],
            {"19279": {"title": "Quickie World 2", "completed_date": "2024-06-01"}})
        result = self.apply(fixture, self.finalize(session))["19279"]
        self.assertTrue(result["completed"])
        self.assertEqual("2024-06-01", result["completed_date"])
        self.assertEqual("", result["playthroughs"][0]["completed_date_iso"])
        self.assertEqual("1/5/2026", result["playthroughs"][0]["completed_date"])
        self.assertEqual(7200, result["time_to_beat"])

    def test_multiple_runs_project_only_selected_first_clear_or_none(self):
        first = _playthrough("4:00:00", "May 1, 2026")
        pb = dict(_playthrough("0:20:00", "May 3, 2026"), playKind="Speedrun PB", notes="keep PB")
        for run, duration, date in (("0", 14400, "2026-05-01"), ("1", 1200, "2026-05-03"), ("none", 0, "")):
            with self.subTest(run=run):
                fixture, session = self.session([pb, first])
                # Selection is source-record based, not chronological or speed based.
                selected = "1" if run == "0" else "0" if run == "1" else run
                with self.assertRaises(ValueError):
                    self.finalize(session)
                result = self.apply(fixture, self.finalize(session, self.decision(session, selected)))["19279"]
                self.assertEqual(2, len(result["playthroughs"]))
                self.assertEqual("keep PB", result["playthroughs"][0]["notes"])
                self.assertTrue(result["completed"])
                self.assertEqual(duration, result.get("time_to_beat"))
                self.assertEqual(date, result.get("completed_date"))

    def test_selected_run_introduces_conflict_that_must_be_reviewed(self):
        _, session = self.session([_playthrough("4:00:00", "May 1, 2026"), _playthrough("1:00:00", "May 3, 2026")],
            {"19279": {"title": "Quickie World 2", "completed": True, "time_to_beat": 3600}})
        self.finalize(session, self.decision(session, "1"))
        with self.assertRaisesRegex(ValueError, "Every conflicting"):
            self.finalize(session, self.decision(session, "0"))
        plan = self.finalize(session, self.decision(session, "0", (("time_to_beat", True),)))
        self.assertEqual(14400, next(item.value for item in plan.user_state_updates if item.field == "time_to_beat"))

    def test_retargeting_rechecks_frozen_values_and_does_not_use_original_target_conflicts(self):
        _, session = self.session(records={
            "19279": {"title": "Quickie World 2"},
            "100": {"title": "Other Hack", "completed_date": "2025-01-01", "time_to_beat": 100},
        })
        choice = self.decision(session, action=ReviewAction.USE_TARGET, target="100")
        with self.assertRaisesRegex(ValueError, "Every conflicting"):
            self.finalize(session, choice)
        model = CollectionIngestionReviewModel(session)
        proposals = model.user_field_proposals(session.groups[0].group_id, choice)
        self.assertEqual(100, next(p.current_value for p in proposals if p.field == "time_to_beat"))
        choice = replace(choice, user_field_resolutions=(UserFieldResolution("completed_date", False), UserFieldResolution("time_to_beat", False)))
        plan = self.finalize(session, choice)
        self.assertNotIn("time_to_beat", {p.field for p in plan.user_state_updates})
        self.assertEqual("100", plan.record_intents[0].target_key)

    def test_new_local_choice_does_not_inherit_old_numeric_conflicts(self):
        _, session = self.session(records={"19279": {"title": "Quickie World 2", "time_to_beat": 100}})
        choice = self.decision(session, action=ReviewAction.IMPORT_LOCAL)
        proposals = CollectionIngestionReviewModel(session).user_field_proposals(session.groups[0].group_id, choice)
        self.assertFalse(any(p.conflict for p in proposals))
        validate_review_decision(session.groups[0], choice)

    def test_pb_replay_race_and_practice_never_automatically_project_duration(self):
        for kind in ("PB", "Speedrun", "Replay", "Re-play", "Race", "Practice", "RTA"):
            with self.subTest(kind=kind):
                _, session = self.session([dict(_playthrough(), playKind=kind)])
                with self.assertRaises(ValueError):
                    self.finalize(session)
                plan = self.finalize(session, self.decision(session, "none"))
                self.assertNotIn("time_to_beat", {p.field for p in plan.user_state_updates})

    def test_duration_milliseconds_can_supply_selected_run_when_time_is_absent(self):
        fixture, session = self.session([dict(_playthrough("", "May 1, 2026"), durationMilliseconds=1234500)])
        result = self.apply(fixture, self.finalize(session))["19279"]
        self.assertEqual(1234.5, result["time_to_beat"])
        self.assertEqual(1234500, result["playthroughs"][0]["duration_milliseconds"])

    def test_bad_or_zero_duration_does_not_erase_collection_time(self):
        for value in ("", "garbage", "0:00:00", "1:99:00"):
            with self.subTest(value=value):
                _, session = self.session([_playthrough(value, "May 1, 2026")],
                    {"19279": {"title": "Quickie World 2", "time_to_beat": 100}})
                self.assertNotIn("time_to_beat", {p.field for p in self.finalize(session).user_state_updates})

    def test_model_reports_existing_and_new_targets_from_frozen_collection(self):
        _, session = self.session()
        model = CollectionIngestionReviewModel(session)
        self.assertEqual("Already in Collection", model.rows()[0].collection_status)
        self.assertEqual("New", model.collection_status("100"))
        self.assertEqual("Matched existing Collection entry", model.target_description("19279"))
        self.assertEqual("Proposed new Collection entry", model.target_description("100"))
        choice = self.decision(session, action=ReviewAction.USE_TARGET, target="100")
        model.set_decision(session.groups[0].group_id, choice)
        self.assertEqual("New", model.rows()[0].collection_status)

    def test_stale_state_is_rejected_by_apply(self):
        fixture, session = self.session()
        plan = self.finalize(session)
        fixture.processed.write_text('{"100":{"title":"Changed"}}', encoding="utf-8")
        with self.assertRaises(CollectionPlanStaleStateError):
            self.apply(fixture, plan)
        self.assertEqual({"100": {"title": "Changed"}}, json.loads(fixture.processed.read_text(encoding="utf-8")))

    def test_raw_time_proposal_cannot_bypass_verified_first_clear_duration(self):
        from collection_change_plan import finalize_collection_change_plan
        from collection_reconciliation import UserFieldProposal
        _, session = self.session()
        group = session.groups[0]
        bad = UserFieldProposal("time_to_beat", 0, 1, IngestionSource.GIGANTIC_BUCKET, "Wrong run duration")
        member = replace(group.members[0], user_field_proposals=(bad,))
        raw = replace(group, members=(member,), giganticbucket_user_state=None)
        with self.assertRaisesRegex(ValueError, "must match the selected first-clear duration"):
            finalize_collection_change_plan((raw,), existing_collection_keys=("19279",))


class GiganticBucketReviewUITest(unittest.TestCase):
    """Exercise the actual review methods with lightweight headless Tk widgets."""

    session = GiganticBucketProgressTest.session
    decision = GiganticBucketProgressTest.decision

    def dialog(self, session):
        source = (Path(__file__).parent / "ui" / "collection_ingestion_review_dialog.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CollectionIngestionReviewDialog")
        cls.body = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name in {
            "_user_state_draft", "_refresh_user_conflicts", "_render_user_conflicts"}]
        formatter = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_user_value_text")
        module = ast.Module(body=[formatter, cls], type_ignores=[])

        class Value:
            def __init__(self, value=""): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value

        class Widget:
            def __init__(self, parent=None, **kwargs):
                self.parent = parent
                self.children = []
                self.kwargs = kwargs
                if parent is not None: parent.children.append(self)
            def pack(self, **kwargs): pass
            def winfo_children(self): return tuple(self.children)
            def destroy(self): self.parent.children.remove(self)

        namespace = dict(ReviewAction=ReviewAction, ReviewDecision=ReviewDecision,
                         FirstClearDecision=FirstClearDecision, IngestionSource=IngestionSource,
                         tk=SimpleNamespace(StringVar=Value),
                         ttk=SimpleNamespace(Frame=Widget, LabelFrame=Widget, Label=Widget, Radiobutton=Widget))
        exec(compile(module, str(Path(__file__).parent / "ui" / "collection_ingestion_review_dialog.py"), "exec"), namespace)
        dialog = namespace["CollectionIngestionReviewDialog"]()
        dialog.model = CollectionIngestionReviewModel(session)
        dialog._action_var = Value("accept")
        dialog._first_clear_var = Value("")
        dialog._first_clear_values = {"none": (None, None), "run:0": (IngestionSource.GIGANTIC_BUCKET, "1:0"), "run:1": (IngestionSource.GIGANTIC_BUCKET, "1:1")}
        dialog._user_conflicts_area = Widget()
        dialog._displayed_user_proposals = None
        dialog._current_group_id = session.groups[0].group_id
        dialog._wrapped_label = lambda parent, text, **kwargs: Widget(parent, text=text, **kwargs)
        return dialog

    def test_giganticbucket_default_is_visible_and_saved_keep_choice_restores(self):
        _, session = self.session(records={"19279": {"title": "Quickie World 2", "completed_date": "2026-05-08", "time_to_beat": 100}})
        dialog = self.dialog(session)
        dialog._render_user_conflicts(session.groups[0], None)
        self.assertEqual({"completed_date": "imported", "time_to_beat": "imported"},
                         {k: v.get() for k, v in dialog._user_field_vars.items()})
        def texts(widget):
            return [widget.kwargs.get("text", "")] + [text for child in widget.children for text in texts(child)]
        copy = "\n".join(texts(dialog._user_conflicts_area))
        self.assertIn("Keep current Collection value: 2026-05-08", copy)
        self.assertIn("Use GiganticBucket first-clear value: 2026-05-01", copy)
        self.assertIn("Use GiganticBucket first-clear value: 2:00:00", copy)
        self.assertIn("original source may not be recorded", copy)
        dialog._user_field_vars["completed_date"].set("existing")
        dialog._refresh_user_conflicts()
        self.assertEqual("existing", dialog._user_field_vars["completed_date"].get())
        reopened = self.dialog(session)
        previous = self.decision(session, choices=(("completed_date", False), ("time_to_beat", True)))
        reopened._render_user_conflicts(session.groups[0], previous)
        self.assertEqual("existing", reopened._user_field_vars["completed_date"].get())

    def test_first_clear_change_refreshes_conflicts_and_none_removes_date_time_projection(self):
        _, session = self.session([_playthrough("4:00:00", "May 1, 2026"), _playthrough("1:00:00", "May 3, 2026")],
            {"19279": {"title": "Quickie World 2", "time_to_beat": 3600}})
        dialog = self.dialog(session)
        dialog._refresh_user_conflicts()
        self.assertEqual({}, dialog._user_field_vars)
        dialog._first_clear_var.set("run:0")
        dialog._refresh_user_conflicts()
        self.assertEqual("imported", dialog._user_field_vars["time_to_beat"].get())
        dialog._first_clear_var.set("run:1")
        dialog._refresh_user_conflicts()
        self.assertEqual({}, dialog._user_field_vars)
        dialog._first_clear_var.set("none")
        dialog._refresh_user_conflicts()
        self.assertEqual({"completed"}, {p.field for p in dialog._displayed_user_proposals})


if __name__ == "__main__":
    unittest.main(verbosity=2)
