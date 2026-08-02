import hashlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "codex-loop-prompt-architect" / "scripts" / "loopskill5"
LOADER = importlib.machinery.SourceFileLoader("loopskill5_phase2", str(ENTRY))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
loopskill5 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = loopskill5
LOADER.exec_module(loopskill5)


INITIAL_SERVER = '''
import http from "node:http";
import { fileURLToPath } from "node:url";
export function createServer() {
  return http.createServer((request, response) => {
    if (request.method === "GET") {
      response.writeHead(200, { "content-type": "text/html", "set-cookie": "nepha_session=before; Path=/" });
      return response.end('<body data-view="today"><meta name="csrf-token" content="before"></body>');
    }
    response.writeHead(501, { "content-type": "application/json" });
    response.end('{"error":"not_implemented"}');
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) createServer().listen(Number(process.env.PORT), "127.0.0.1");
'''.lstrip()


FIXED_SERVER = '''
import http from "node:http";
import { fileURLToPath } from "node:url";
const views = new Set(["/today", "/inbox", "/content", "/settings"]);
const sessions = new Map();
function send(response, status, body) {
  response.writeHead(status, { "content-type": "application/json", "cache-control": "no-store" });
  response.end(JSON.stringify(body));
}
export function createServer() {
  return http.createServer(async (request, response) => {
    const host = request.headers.host;
    if (!host?.startsWith("127.0.0.1:")) return send(response, 403, { error: "invalid_host" });
    const url = new URL(request.url, `http://${host}`);
    if (request.method === "GET" && views.has(url.pathname)) {
      const session = "session-fixed";
      const csrf = "csrf-fixed";
      sessions.set(session, csrf);
      response.writeHead(200, { "content-type": "text/html", "set-cookie": `nepha_session=${session}; Path=/` });
      return response.end(`<body data-view="${url.pathname.slice(1)}"><meta name="csrf-token" content="${csrf}"></body>`);
    }
    if (request.method === "POST" && url.pathname === "/api/intake") {
      if (request.headers.origin !== `http://${host}`) return send(response, 403, { error: "invalid_origin" });
      const session = (request.headers.cookie ?? "").match(/(?:^|; )nepha_session=([^;]+)/)?.[1];
      if (!session || sessions.get(session) !== request.headers["x-csrf-token"]) {
        return send(response, 403, { error: "invalid_session_or_csrf" });
      }
      let raw = "";
      for await (const chunk of request) raw += chunk;
      const input = JSON.parse(raw);
      if (typeof input.title !== "string" || typeof input.text !== "string") return send(response, 400, { error: "invalid_input" });
      return send(response, 201, { ok: true, titleLength: input.title.length, textLength: input.text.length });
    }
    return send(response, 404, { error: "not_found" });
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) createServer().listen(Number(process.env.PORT), "127.0.0.1");
'''.lstrip()


INITIAL_TEST = '''
import test from "node:test";
import assert from "node:assert/strict";
test("foundation", () => assert.equal(1, 1));
'''.lstrip()


FIXED_TEST = '''
import assert from "node:assert/strict";
import test from "node:test";
import { createServer } from "../src/server.js";
test("four pages remain available", async () => {
  const server = createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  for (const view of ["today", "inbox", "content", "settings"]) {
    const response = await fetch(`http://127.0.0.1:${port}/${view}`);
    assert.equal(response.status, 200);
    assert.match(await response.text(), new RegExp(`data-view="${view}"`));
  }
  await new Promise((resolve) => server.close(resolve));
});
'''.lstrip()


def run_git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    ).stdout.strip()


class WalkingSkeletonTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="loopskill5-test-")
        self.private_temporary = tempfile.TemporaryDirectory(prefix="loopskill5-private-test-")
        self.workspace = Path(self.temporary.name).resolve()
        self.private_root = Path(self.private_temporary.name).resolve() / "prepared"
        (self.workspace / "src").mkdir()
        (self.workspace / "test").mkdir()
        (self.workspace / "src/server.js").write_text(INITIAL_SERVER, encoding="utf-8")
        (self.workspace / "test/server.test.js").write_text(INITIAL_TEST, encoding="utf-8")
        (self.workspace / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
        run_git(self.workspace, "init", "--quiet")
        run_git(self.workspace, "config", "user.name", "LoopSkill Test")
        run_git(self.workspace, "config", "user.email", "loopskill-test.invalid")
        run_git(self.workspace, "add", ".")
        run_git(self.workspace, "commit", "--quiet", "-m", "fixture")
        self.head = run_git(self.workspace, "rev-parse", "HEAD")
        (self.workspace / loopskill5.OWNER_NOTE).write_bytes(loopskill5.OWNER_NOTE_BYTES)
        node = Path(shutil.which("node")).resolve()
        git = Path(shutil.which("git")).resolve()
        self.tools = {
            "codex": {"path": "/not-used/codex", "sha256": "c" * 64, "version": "codex-test"},
            "node": {
                "path": str(node),
                "sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
                "version": subprocess.run((str(node), "--version"), check=True, capture_output=True, text=True).stdout.strip(),
            },
            "git": {
                "path": str(git),
                "sha256": hashlib.sha256(git.read_bytes()).hexdigest(),
                "version": subprocess.run((str(git), "--version"), check=True, capture_output=True, text=True).stdout.strip(),
            },
            "path": os.pathsep.join((str(node.parent), str(git.parent), os.environ.get("PATH", ""))),
        }
        self.patches = (
            mock.patch.object(loopskill5, "EXPECTED_HEAD", self.head),
            mock.patch.object(loopskill5, "_tools", return_value=self.tools),
            mock.patch.object(loopskill5, "PRIVATE_PREPARE_ROOT", self.private_root),
        )
        for patcher in self.patches:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patches):
            patcher.stop()
        self.temporary.cleanup()
        self.private_temporary.cleanup()

    def test_prepare_is_human_readable_and_rejects_known_dirty_blocker(self):
        extra = self.workspace / "unapproved.txt"
        extra.write_text("blocked\n", encoding="utf-8")
        with self.assertRaisesRegex(loopskill5.LaunchError, "outside the fixed Owner note"):
            loopskill5.prepare(str(self.workspace), loopskill5.REQUEST)
        self.assertEqual(
            run_git(self.workspace, "status", "--porcelain=v1", "--untracked-files=all"),
            f"?? {loopskill5.OWNER_NOTE}\n?? unapproved.txt",
        )
        extra.unlink()

        status_before = run_git(self.workspace, "status", "--porcelain=v1", "--untracked-files=all")
        contract = loopskill5.prepare(str(self.workspace), loopskill5.REQUEST)
        self.assertTrue(contract.startswith("# LoopSkill 5.0 Launch Contract"))
        self.assertIn("合法 POST 非 501", contract)
        self.assertIn("端口竞态时换临时端口重建一次", contract)
        contract_path = loopskill5._preparation_path(self.workspace)
        self.assertEqual(contract_path.stat().st_mode & 0o777, 0o600)
        self.assertIn(loopskill5.FACTS_MARKER.strip(), contract_path.read_text(encoding="utf-8"))
        self.assertEqual(
            run_git(self.workspace, "status", "--porcelain=v1", "--untracked-files=all"),
            status_before,
        )
        self.assertFalse((self.workspace / contract_path.name).exists())

    def test_start_rejects_executable_drift_before_worker_or_workspace_effect(self):
        loopskill5.prepare(str(self.workspace), loopskill5.REQUEST)
        drifted = json_copy(self.tools)
        drifted["codex"]["sha256"] = "d" * 64
        worker_calls = 0

        def worker(_workspace, _tools):
            nonlocal worker_calls
            worker_calls += 1

        with mock.patch.object(loopskill5, "_tools", return_value=drifted):
            with self.assertRaisesRegex(loopskill5.LaunchError, "drifted before START"):
                loopskill5.start(str(self.workspace), worker=worker)
        self.assertEqual(worker_calls, 0)
        self.assertTrue(loopskill5._preparation_path(self.workspace).exists())
        self.assertEqual(
            run_git(self.workspace, "status", "--porcelain=v1", "--untracked-files=all").splitlines(),
            [f"?? {loopskill5.OWNER_NOTE}"],
        )

    def test_empty_optional_environment_keeps_the_prepared_safe_path(self):
        with tempfile.TemporaryDirectory(prefix="loopskill5-worker-env-") as scratch:
            with mock.patch.dict(os.environ, {}, clear=True):
                environment = loopskill5._worker_environment(self.tools, scratch)
            self.assertEqual(environment, {"PATH": self.tools["path"], "TMPDIR": scratch})
            self.assertEqual(
                subprocess.run(
                    (self.tools["node"]["path"], "--version"),
                    env=environment,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip(),
                self.tools["node"]["version"],
            )

    def test_gj1_real_loopback_recovers_one_verifier_crash_without_rerunning_worker(self):
        loopskill5.prepare(str(self.workspace), loopskill5.REQUEST)
        worker_calls = 0

        def worker(workspace, _tools):
            nonlocal worker_calls
            worker_calls += 1
            (workspace / "src/server.js").write_text(FIXED_SERVER, encoding="utf-8")
            (workspace / "test/server.test.js").write_text(FIXED_TEST, encoding="utf-8")

        with mock.patch.dict(os.environ, {loopskill5.INJECT_VERIFIER_EXIT: "1"}):
            report = loopskill5.start(str(self.workspace), worker=worker)
        self.assertEqual(worker_calls, 1)
        self.assertIn("真实 loopback POST 返回 HTTP 201", report)
        self.assertIn("/today、/inbox、/content、/settings 真实 loopback GET 均为 200", report)
        self.assertIn("verifier 首次 crash 后重建 1 次", report)
        self.assertFalse(loopskill5._preparation_path(self.workspace).exists())
        self.assertEqual((self.workspace / loopskill5.OWNER_NOTE).read_bytes(), loopskill5.OWNER_NOTE_BYTES)

    def test_gj1_rebuilds_verifier_once_after_a_real_port_collision(self):
        loopskill5.prepare(str(self.workspace), loopskill5.REQUEST)
        worker_calls = 0
        verifier_calls = 0
        real_popen = subprocess.Popen

        def worker(workspace, _tools):
            nonlocal worker_calls
            worker_calls += 1
            (workspace / "src/server.js").write_text(FIXED_SERVER, encoding="utf-8")
            (workspace / "test/server.test.js").write_text(FIXED_TEST, encoding="utf-8")

        def verifier(workspace, tools, *, injected_exit):
            nonlocal verifier_calls
            verifier_calls += 1
            self.assertFalse(injected_exit)
            if verifier_calls > 1:
                return loopskill5._launch_verifier(workspace, tools, injected_exit=False)

            blocker = None

            def collide_on_server_start(argv, **kwargs):
                nonlocal blocker
                if tuple(argv)[-1] == "src/server.js":
                    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    blocker.bind(("127.0.0.1", int(kwargs["env"]["PORT"])))
                return real_popen(argv, **kwargs)

            try:
                with mock.patch.object(loopskill5.subprocess, "Popen", side_effect=collide_on_server_start):
                    loopskill5._verify_gj1(workspace, tools)
            except loopskill5.LaunchError as exc:
                return 1, {"ok": False, "error": str(exc)}
            finally:
                if blocker is not None:
                    blocker.close()
            self.fail("the real port collision did not fail the first verifier")

        report = loopskill5.start(str(self.workspace), worker=worker, verifier=verifier)
        self.assertEqual(worker_calls, 1)
        self.assertEqual(verifier_calls, 2)
        self.assertIn("verifier 端口竞态后换临时端口重建 1 次", report)


def json_copy(value):
    import json

    return json.loads(json.dumps(value))


if __name__ == "__main__":
    unittest.main()
