from __future__ import annotations

from state_runtime_support import *  # noqa: F403


class AdaptiveStateRuntimeEvidenceTests(AdaptiveStateRuntimeTestCase):  # noqa: F405
    def _prepare_worker_validation_projection(
        self,
        root: Path,
    ) -> tuple[
        Harness,
        dict[str, Any],
        str,
        str,
        dict[str, Any],
        str,
    ]:
        required_dimensions = tuple(
            dimension
            for dimension in (
                "functional",
                "regression",
                "static_quality",
                "compatibility",
                "security",
                "performance",
                "change_impact",
            )
        )
        definition = goal("g1", "m1")
        definition["validation_matrix"] = complete_validation_matrix(
            required_dimensions=required_dimensions
        )
        definition["payload_template_digest"] = goal_definition_digest(definition)
        harness = Harness(root)
        initialized, _ = harness.initialize(definitions={"g1": definition})
        self.assertTrue(initialized["ok"], initialized)
        harness.ensure_controller_goal()
        harness.register_control_result(
            "THREAD",
            "projection-worker-create",
            "controller-1",
            {"role_kind": "WORKER"},
            {
                "thread_id": "projection-worker",
                "role_kind": "WORKER",
                "worktree_path": ".",
            },
        )
        claim = harness.acquire()
        dispatch_id = "projection-dispatch"
        prepared, payload = harness.prepare_outbox(
            claim,
            "DISPATCH",
            dispatch_id,
            {
                "goal_id": "g1",
                "goal_definition_digest": definition["payload_template_digest"],
            },
            target_id="projection-worker",
        )
        self.assertTrue(prepared["ok"], prepared)
        sent = harness.mark_sent(
            claim,
            "DISPATCH",
            dispatch_id,
            payload,
            target_id="projection-worker",
        )
        self.assertTrue(sent["ok"], sent)
        artifact_digest = digest("projection-current-artifact")
        result = {"status": "PASS", "artifact_digest": artifact_digest}
        report_text = harness.formal_report_content(
            "DISPATCH", dispatch_id, result
        )
        return harness, claim, dispatch_id, payload, result, report_text

    def test_report_evidence_input_failures_are_zero_effect(self) -> None:
        def rewrite_report(request: dict[str, Any], mutate: Any) -> None:
            report = json.loads(request["report_text"])
            mutate(report)
            request["report_text"] = json.dumps(
                report,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        def non_list(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"] = None

        def invalid_report_artifact(request: dict[str, Any], _: Path) -> None:
            rewrite_report(request, lambda report: report.update(evidence_artifacts=[7]))

        def malformed_source(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"] = [{"path": "missing-keys"}]

        def duplicate_source(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"].append(
                copy.deepcopy(request["evidence_sources"][0])
            )

        def invalid_destination(request: dict[str, Any], _: Path) -> None:
            invalid_path = ".codex-loop/reports/nested/evidence.json"
            request["evidence_sources"][0]["path"] = invalid_path
            rewrite_report(
                request,
                lambda report: report["evidence_artifacts"][0].update(
                    path=invalid_path
                ),
            )

        def invalid_media(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"][0]["media_type"] = "application/octet-stream"

        def invalid_digest(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"][0]["digest"] = "not-a-digest"

        def digest_mismatch(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"][0]["digest"] = "sha256:" + "0" * 64

        def relative_source(request: dict[str, Any], _: Path) -> None:
            request["evidence_sources"][0]["source_path"] = "relative.json"

        def missing_source(request: dict[str, Any], root: Path) -> None:
            request["evidence_sources"][0]["source_path"] = str(root / "missing.json")

        def invalid_json(request: dict[str, Any], root: Path) -> None:
            content = "{not-json}"
            source = root / "invalid-evidence.json"
            source.write_text(content, encoding="utf-8")
            content_digest = digest(content)
            request["evidence_sources"][0].update(
                source_path=str(source), digest=content_digest
            )

        def nested_control_source(request: dict[str, Any], root: Path) -> None:
            source = root / ".CODEX-LOOP" / "reports" / "evidence.json"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text('{"status":"PASS"}', encoding="utf-8")
            source_digest = digest(source.read_text(encoding="utf-8"))
            request["evidence_sources"][0].update(
                source_path=str(source), digest=source_digest
            )

        def invalid_utf8(request: dict[str, Any], root: Path) -> None:
            payload = b"\xff\xfe"
            source = root / "invalid-utf8.json"
            source.write_bytes(payload)
            request["evidence_sources"][0].update(
                source_path=str(source),
                digest="sha256:" + hashlib.sha256(payload).hexdigest(),
            )

        def oversized_source(request: dict[str, Any], root: Path) -> None:
            source = root / "oversized.json"
            with source.open("wb") as stream:
                stream.truncate(state_runtime_module.MAX_ARTIFACT_CONTENT_SIZE + 1)
            request["evidence_sources"][0].update(
                source_path=str(source), digest="sha256:" + "0" * 64
            )

        def claim_mismatch(request: dict[str, Any], _: Path) -> None:
            rewrite_report(
                request,
                lambda report: report["evidence_artifacts"][0].update(
                    size_bytes=999999
                ),
            )

        def unarchived_report_evidence(request: dict[str, Any], _: Path) -> None:
            rewrite_report(
                request,
                lambda report: report["evidence_artifacts"].append(
                    ".codex-loop/reports/unarchived-validation.json"
                ),
            )
            rewrite_report(
                request,
                lambda report: report["evidence_artifacts"][0].update(
                    digest=content_digest
                ),
            )

        scenarios = (
            ("non-list", non_list, "FORMAL_REPORT_EVIDENCE_INPUT_INVALID"),
            (
                "invalid-report-artifact",
                invalid_report_artifact,
                "WORKER_REVIEW_HANDOFF_EVIDENCE_INVALID",
            ),
            ("malformed-source", malformed_source, "FORMAL_REPORT_EVIDENCE_INPUT_INVALID"),
            ("duplicate-source", duplicate_source, "FORMAL_REPORT_EVIDENCE_UNBOUND"),
            ("invalid-destination", invalid_destination, "FORMAL_REPORT_EVIDENCE_PATH_INVALID"),
            ("invalid-media", invalid_media, "FORMAL_REPORT_EVIDENCE_MEDIA_TYPE_INVALID"),
            ("invalid-digest", invalid_digest, "DIGEST_INVALID"),
            ("digest-mismatch", digest_mismatch, "FORMAL_REPORT_EVIDENCE_SOURCE_INVALID"),
            ("relative-source", relative_source, "FORMAL_REPORT_EVIDENCE_SOURCE_INVALID"),
            ("missing-source", missing_source, "FORMAL_REPORT_EVIDENCE_SOURCE_INVALID"),
            (
                "nested-control-source",
                nested_control_source,
                "FORMAL_REPORT_EVIDENCE_CONTROL_SOURCE_FORBIDDEN",
            ),
            ("invalid-utf8", invalid_utf8, "FORMAL_REPORT_EVIDENCE_UTF8_INVALID"),
            ("oversized-source", oversized_source, "FORMAL_REPORT_EVIDENCE_SOURCE_INVALID"),
            ("invalid-json", invalid_json, "FORMAL_REPORT_EVIDENCE_JSON_INVALID"),
            (
                "claim-mismatch",
                claim_mismatch,
                "WORKER_REVIEW_HANDOFF_EVIDENCE_CLAIM_MISMATCH",
            ),
            (
                "unarchived-report-evidence",
                unarchived_report_evidence,
                "WORKER_REVIEW_HANDOFF_EVIDENCE_UNARCHIVED",
            ),
        )
        for name, mutate, expected_code in scenarios:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                harness, _, dispatch_id, _, result, report_text = (
                    self._prepare_worker_validation_projection(root)
                )
                content = '{"status":"PASS","suite":"focused"}'
                source = root / "focused-validation.json"
                source.write_text(content, encoding="utf-8")
                content_digest = digest(content)
                evidence_path = (
                    f".codex-loop/reports/{dispatch_id}-focused-validation.json"
                )
                report = json.loads(report_text)
                report["evidence_artifacts"] = [
                    {
                        "path": evidence_path,
                        "digest": content_digest,
                        "media_type": "application/json",
                    }
                ]
                request = {
                    "outbox_id": dispatch_id,
                    "result": result,
                    "report_text": json.dumps(
                        report,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "evidence_sources": [
                        {
                            "path": evidence_path,
                            "source_path": str(source),
                            "digest": content_digest,
                            "media_type": "application/json",
                        }
                    ],
                }
                mutate(request, root)
                before = persisted_snapshot(root)
                state = harness.state()
                with self.assertRaises(
                    state_runtime_module.RuntimeRejection
                ) as direct_context:
                    harness.runtime._collect_report_evidence_locked(
                        state,
                        state["dispatch_outbox"][dispatch_id],
                        json.loads(request["report_text"]),
                        request["evidence_sources"],
                    )
                self.assertEqual(direct_context.exception.code, expected_code)
                with self.assertRaises(
                    state_runtime_module.RuntimeRejection
                ) as context:
                    harness.runtime.stage_formal_report(request)
                self.assertEqual(context.exception.code, expected_code)
                self.assertEqual(persisted_snapshot(root), before)
