
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import base64
import urllib.request
import urllib.error
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path
from typing import Any


# ============================================================
# CONFIGURATION
# ============================================================

APP_DIR = Path(__file__).resolve().parent
OLLAMA_BASE_URL = "http://localhost:11434"
MANAGER_MODEL = "qwen3.5-9b-8kPM"
CODER_MODEL = "qwen2.5-coder-8k"
MAX_CYCLES = 5
RUNTIME_TIMEOUT_SECONDS = 15
PROJECTS_DIR = APP_DIR / "projects"

SUPERVISOR_FILES = {
    "supervisor.py",
    "supervisor_simple.py",
    "supervisor_simple_v2.py",
    "supervisor_review.py",
    "supervisor_review_v2.py",
    "supervisor_review_v3.py",
    "supervisor_final.py",
}


# ============================================================
# LOCAL OLLAMA MODEL CLIENT
# ============================================================

def ollama_chat(model: str, messages: list[dict[str, Any]]) -> str:
    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": False,
        # Qwen 3.5 may spend the whole generation budget in its hidden
        # reasoning channel and return an empty visible `content` field.
        # The Supervisor needs the actual response text, not the reasoning
        # trace, so disable thinking for the agent protocol.
        "think": False,
    }).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_BASE_URL + "/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Ollama connection failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ollama returned invalid JSON.") from exc
    message = data.get("message", {})
    content = message.get("content", "")

    # Some Ollama/Qwen combinations can still return an empty visible
    # response even when a thinking field is present. Never feed the
    # internal reasoning trace back into the pipeline as if it were the
    # Manager's answer. Fail with a useful diagnostic instead.
    if not isinstance(content, str) or not content.strip():
        thinking = message.get("thinking", "")
        if thinking:
            raise RuntimeError(
                "Ollama returned only thinking/reasoning and no visible "
                "message content. Thinking has been disabled for the "
                "Supervisor request; check that the running Ollama model "
                "supports the 'think' option or update Ollama."
            )
        raise RuntimeError(f"Ollama returned no message content: {data}")

    return content.strip()


def build_manager_prompt() -> str:
    return """You are the PROJECT MANAGER, SOFTWARE ARCHITECT, and FINAL REVIEWER.
You control feature-level planning, configuration, scope, interfaces, runtime expectations, and verification.
Understand the whole project before proposing changes. References are read-only knowledge, never target files.
Do not invent requirements. Preserve existing functionality and interfaces unless the approved feature explicitly changes them.

For planning, propose one bounded feature/sprint and use these headings:
FEATURE_ID:
GOAL:
SCOPE:
DEPENDENCIES:
FILES_TO_CREATE:
FILES_TO_MODIFY:
FILES_TO_PRESERVE:
CONFIGURATION:
INTERFACES:
BEHAVIOR:
REGRESSION_REQUIREMENTS:
ACCEPTANCE:
VERIFICATION:
RUNTIME:

CRITICAL OFFLINE RULE:
If the user requests offline operation, no internet, no API, local-only, a single local file, or similar constraints, treat those as hard requirements. Do not introduce Flask, FastAPI, Uvicorn, Requests, Alembic, databases, CDNs, external URLs, external APIs, npm packages, pip packages, remote assets, telemetry, or other network/external dependencies unless the user explicitly asks for them. A localhost Ollama call made by the Supervisor itself is not a project dependency and must never be proposed as part of the generated application.

FILES_TO_CREATE and FILES_TO_MODIFY must contain only bare relative file paths, one per line. Put explanations on separate lines or after the complete plan, never on the same path line.

RUNTIME may be YES or NO and must explain what should be executed when YES.
The user may ask questions or request changes. Revise the same plan; do not start coding until explicit approval.

For final review, return exactly:
VERDICT: VERIFIED
REASON: short factual explanation
or
VERDICT: REJECTED
REASON: specific problem that must be fixed"""


def build_coder_prompt() -> str:
    return """You are the CODER in a local autonomous development system.
Implement only the approved sprint specification. Work inside the supplied project workspace.
References are read-only and must never be modified. Preserve unrelated existing functionality.
Return ONLY complete file blocks using exactly:
===FILE: relative/path.ext===
file contents
===END_FILE===
Never use absolute paths, never escape the workspace, and never include Markdown fences around file contents.
ONLY write files explicitly listed under FILES_TO_CREATE or FILES_TO_MODIFY in the approved specification. Do not recreate architecture, config, feature metadata, references, or unrelated existing files unless they are explicitly approved targets.
Do not create tests unless the approved specification requires them."""


def manager_chat(task: str, project_context: str, conversation: list[dict[str, str]]) -> str:
    messages = [{"role": "system", "content": build_manager_prompt()}]
    messages.append({"role": "user", "content": f"PROJECT CONTEXT:\n{project_context}\n\nCURRENT USER TASK:\n{task}"})
    messages.extend(conversation)
    return ollama_chat(MANAGER_MODEL, messages)


def coder_chat(task: str, specification: str, project_context: str, review: str = "") -> str:
    prompt = f"""APPROVED SPRINT SPECIFICATION:\n{specification}\n\nORIGINAL TASK:\n{task}\n\nCURRENT PROJECT CONTEXT:\n{project_context}\n"""
    if review:
        prompt += f"\nLATEST REVIEW AND VERIFICATION EVIDENCE:\n{review}\n\nFix the implementation."
    return ollama_chat(CODER_MODEL, [
        {"role": "system", "content": build_coder_prompt()},
        {"role": "user", "content": prompt},
    ])


# ============================================================
# TASK / WORKSPACE
# ============================================================

# ============================================================

def make_task_id(task: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    slug = re.sub(
        r"[^a-zA-Z0-9]+",
        "-",
        task.lower(),
    ).strip("-")[:50]

    digest = hashlib.sha1(
        task.encode("utf-8")
    ).hexdigest()[:6]

    return f"{timestamp}-{slug or 'task'}-{digest}"


def safe_path(workspace: Path, relative_path: str) -> Path:
    relative = Path(relative_path)

    if relative.is_absolute():
        raise RuntimeError(
            f"Absolute paths are forbidden: {relative_path}"
        )

    candidate = (workspace / relative).resolve()

    try:
        candidate.relative_to(workspace.resolve())
    except ValueError as exc:
        raise RuntimeError(
            f"Path escapes workspace: {relative_path}"
        ) from exc

    if "references" in candidate.relative_to(workspace.resolve()).parts:
        raise RuntimeError(f"References are read-only: {relative_path}")

    if candidate.name in SUPERVISOR_FILES:
        raise RuntimeError(
            f"Protected supervisor file: {relative_path}"
        )

    return candidate


# ============================================================
# MODEL FILE PROTOCOL
# ============================================================

def normalize_model_source(content: str) -> str:
    """
    Remove accidental Markdown fences.

    Qwen is instructed not to emit them, but the supervisor must not trust
    formatting generated by an LLM.
    """
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    lines = content.split("\n")

    while lines and not lines[0].strip():
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    if lines and re.match(
        r"^\s*```(?:[A-Za-z0-9_+.-]+)?\s*$",
        lines[0],
    ):
        lines.pop(0)

    while lines and not lines[-1].strip():
        lines.pop()

    if lines and re.match(r"^\s*```\s*$", lines[-1]):
        lines.pop()

    return "\n".join(lines).rstrip() + "\n"


def parse_files(raw: str) -> dict[str, str]:
    pattern = re.compile(
        r"===FILE:\s*(.+?)===\s*\n(.*?)\n===END_FILE===",
        re.DOTALL,
    )

    matches = pattern.findall(raw)

    if not matches:
        raise RuntimeError(
            "Coder returned no parseable files. "
            "Expected ===FILE: path=== ... ===END_FILE===."
        )

    files: dict[str, str] = {}

    for relative_path, content in matches:
        relative_path = relative_path.strip()

        if not relative_path:
            raise RuntimeError("Coder returned an empty path.")

        files[relative_path] = normalize_model_source(content)

    return files


def write_files(
    workspace: Path,
    files: dict[str, str],
) -> list[str]:
    changed: list[str] = []

    for relative_path, content in files.items():
        target = safe_path(workspace, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.suffix.lower() in {".py", ".pyw"}:
            content = normalize_model_source(content)

        target.write_text(content, encoding="utf-8")
        changed.append(relative_path)

    return sorted(changed)


# ============================================================
# WORKSPACE CONTEXT
# ============================================================

def read_project_files(workspace: Path) -> dict[str, str]:
    result: dict[str, str] = {}

    for path in workspace.rglob("*"):
        if not path.is_file():
            continue

        if path.name in {
            "pipeline_state.json",
            "manager_spec.txt",
        }:
            continue

        if ".git" in path.parts:
            continue

        try:
            result[str(path.relative_to(workspace))] = (
                path.read_text(encoding="utf-8")
            )
        except UnicodeDecodeError:
            continue

    return result


def format_files(files: dict[str, str]) -> str:
    chunks = []

    for path, content in files.items():
        chunks.append(
            f"===FILE: {path}===\n"
            f"{content}\n"
            f"===END_FILE==="
        )

    return "\n\n".join(chunks)


# ============================================================
# MANAGER
# ============================================================

def manager_plan(task: str, workspace: Path, conversation: list[dict[str, str]] | None = None) -> str:
    conversation = conversation or []
    context = format_files(read_project_files(workspace))
    return manager_chat(task, context, conversation)


def manager_review(task: str, specification: str, workspace: Path, verification: dict[str, Any]) -> str:
    files = format_files(read_project_files(workspace))
    prompt = f"""FINAL REVIEW MODE
ORIGINAL USER TASK:
{task}

APPROVED SPRINT SPECIFICATION:
{specification}

DETERMINISTIC VERIFICATION:
{json.dumps(verification, indent=2, ensure_ascii=False)}

ACTUAL PROJECT FILES:
{files}

Review functional correctness, completeness, regression safety, and acceptance criteria. Return only the required VERDICT/REASON format."""
    return ollama_chat(MANAGER_MODEL, [{"role":"system","content":build_manager_prompt()},{"role":"user","content":prompt}])


def coder(task: str, specification: str, workspace: Path, review_feedback: str = "") -> dict[str, str]:
    files = format_files(read_project_files(workspace))
    return parse_files(coder_chat(task, specification, files, review_feedback))


# ============================================================
# DETERMINISTIC VERIFICATION
# ============================================================

def syntax_check(workspace: Path) -> dict[str, Any]:
    checked: list[str] = []
    errors: list[str] = []

    for path in workspace.rglob("*.py"):
        if ".git" in path.parts:
            continue

        checked.append(str(path.relative_to(workspace)))

        try:
            source = path.read_text(encoding="utf-8")

            if source.lstrip().startswith("```"):
                errors.append(
                    f"{path.name}: Markdown fence remained in source."
                )
                continue

            compile(
                source,
                str(path),
                "exec",
            )

        except SyntaxError as exc:
            errors.append(
                f"{path.name}: line {exc.lineno}: {exc.msg}"
            )
        except Exception as exc:
            errors.append(
                f"{path.name}: {type(exc).__name__}: {exc}"
            )

    return {
        "passed": not errors,
        "checked_files": checked,
        "errors": errors,
    }


def choose_entrypoint(
    workspace: Path,
) -> Path | None:
    candidates = []

    for path in workspace.glob("*.py"):
        if path.name.startswith("test_"):
            continue

        if path.name.endswith("_test.py"):
            continue

        candidates.append(path)

    preferred = [
        "main.py",
        "app.py",
        "run.py",
    ]

    for name in preferred:
        for path in candidates:
            if path.name == name:
                return path

    if len(candidates) == 1:
        return candidates[0]

    return None


def runtime_check(
    workspace: Path,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled:
        return {
            "attempted": False,
            "passed": True,
            "reason": "Manager specified RUNTIME: NO.",
        }

    entrypoint = choose_entrypoint(workspace)

    if entrypoint is None:
        return {
            "attempted": False,
            "passed": True,
            "reason": "No unambiguous Python entrypoint.",
        }

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(entrypoint),
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=RUNTIME_TIMEOUT_SECONDS,
            shell=False,
        )

        return {
            "attempted": True,
            "passed": result.returncode == 0,
            "entrypoint": str(entrypoint.relative_to(workspace)),
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:],
        }

    except subprocess.TimeoutExpired:
        return {
            "attempted": True,
            "passed": False,
            "entrypoint": str(entrypoint.relative_to(workspace)),
            "exit_code": 124,
            "stdout": "",
            "stderr": (
                f"Execution timed out after "
                f"{RUNTIME_TIMEOUT_SECONDS} seconds."
            ),
        }

    except Exception as exc:
        return {
            "attempted": True,
            "passed": False,
            "entrypoint": str(entrypoint.relative_to(workspace)),
            "exit_code": 1,
            "stdout": "",
            "stderr": (
                f"{type(exc).__name__}: {exc}"
            ),
        }


def verify(
    workspace: Path,
    runtime_enabled: bool,
) -> dict[str, Any]:
    syntax = syntax_check(workspace)

    if not syntax["passed"]:
        return {
            "passed": False,
            "syntax": syntax,
            "runtime": {
                "attempted": False,
                "passed": False,
                "reason": "Skipped because syntax failed.",
            },
        }

    runtime = runtime_check(
        workspace,
        runtime_enabled,
    )

    return {
        "passed": (
            syntax["passed"]
            and runtime["passed"]
        ),
        "syntax": syntax,
        "runtime": runtime,
    }


# ============================================================
# STATE / HISTORY
# ============================================================

def save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(
            data,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def save_state(
    workspace: Path,
    state: dict[str, Any],
) -> None:
    save_json(
        workspace / "pipeline_state.json",
        state,
    )


def save_history(
    workspace: Path,
    cycle: int,
    state: dict[str, Any],
) -> None:
    history = workspace / "history"
    history.mkdir(exist_ok=True)

    save_json(
        history / f"cycle_{cycle:03d}.json",
        state,
    )


# ============================================================
# GIT
# ============================================================

def git_checkpoint(
    workspace: Path,
    message: str,
) -> None:
    try:
        subprocess.run(
            ["git", "init"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["git", "add", "."],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

        subprocess.run(
            ["git", "commit", "-m", message],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        # Git is optional recovery/history. It never controls success.
        pass


# ============================================================
# MAIN
# ============================================================

def project_context(workspace: Path) -> str:
    files = read_project_files(workspace)
    return format_files(files) if files else "(empty project)"


def parse_runtime(specification: str) -> bool:
    return bool(re.search(r"(?im)^\s*RUNTIME:\s*YES\b", specification))


def approved_targets(specification: str) -> set[str]:
    """Extract only bare relative paths from the approved target sections.

    Manager plans often annotate a path with a description, e.g.
    `app.py` (main application). The old parser treated the whole line as
    the target, so a coder returning `app.py` was incorrectly rejected.
    """
    targets: set[str] = set()
    headings = ("FILES_TO_CREATE", "FILES_TO_MODIFY")
    for heading in headings:
        m = re.search(
            rf"(?ms)^\s*{heading}:\s*\n(.*?)(?=^\s*[A-Z][A-Z0-9_ ]+:|\Z)",
            specification,
        )
        if not m:
            continue
        for raw in m.group(1).splitlines():
            line = raw.strip().lstrip("-*• ").strip()
            line = re.sub(r"^\d+[.)]\s*", "", line)
            if not line or line.startswith("("):
                continue
            # Prefer an explicitly quoted/backticked path.
            quoted = re.match(r"^[`\"]([^`\"]+)[`\"]", line)
            if quoted:
                candidate = quoted.group(1).strip()
            else:
                # Otherwise take the first path-like token before a prose
                # description.
                candidate = re.split(r"\s+(?:[-–—:]|\(|\[)", line, maxsplit=1)[0].strip("`\"")
            candidate = candidate.replace("\\", "/").strip().strip("`")
            if candidate and not candidate.startswith("("):
                targets.add(candidate)
    return targets


class SupervisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Local LLM Supervisor")
        self.root.geometry("1250x820")
        self.root.minsize(1000, 680)
        self.project: Path | None = None
        self.references: list[Path] = []
        self.plan_conversation: list[dict[str, str]] = []
        self.specification = ""
        self.task = ""
        self.running = False
        self.cycle = 0
        self._build_ui()
        self.refresh_projects()

    def _build_ui(self):
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Project:").pack(side="left")
        self.project_var = tk.StringVar()
        self.project_combo = ttk.Combobox(top, textvariable=self.project_var, width=32, state="readonly")
        self.project_combo.pack(side="left", padx=6)
        ttk.Button(top, text="New Project", command=self.new_project).pack(side="left", padx=4)
        ttk.Button(top, text="Open", command=self.open_project).pack(side="left", padx=4)
        self.status_var = tk.StringVar(value="IDLE")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        main = ttk.PanedWindow(self.root, orient="horizontal")
        main.pack(fill="both", expand=True, padx=8, pady=4)
        left = ttk.Frame(main, padding=4)
        right = ttk.Frame(main, padding=4)
        main.add(left, weight=3)
        main.add(right, weight=2)

        ttk.Label(left, text="Request / Planning Dialogue").pack(anchor="w")
        self.task_text = tk.Text(left, height=8, wrap="word")
        self.task_text.pack(fill="x", pady=4)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x")
        self.plan_btn = ttk.Button(buttons, text="Plan / Revise", command=self.start_plan)
        self.plan_btn.pack(side="left")
        ttk.Button(buttons, text="Add Files", command=self.add_files).pack(side="left", padx=4)
        ttk.Button(buttons, text="Add Images", command=self.add_images).pack(side="left", padx=4)
        ttk.Button(buttons, text="Clear References", command=self.clear_references).pack(side="left", padx=4)
        self.approve_btn = ttk.Button(buttons, text="Approve Plan", command=self.approve_plan, state="disabled")
        self.approve_btn.pack(side="right")
        self.stop_btn = ttk.Button(buttons, text="Stop", command=self.stop_pipeline, state="disabled")
        self.stop_btn.pack(side="right", padx=4)

        self.references_label = ttk.Label(left, text="References: none")
        self.references_label.pack(anchor="w", pady=4)
        ttk.Label(left, text="Manager Plan / Response").pack(anchor="w")
        self.plan_text = tk.Text(left, wrap="word")
        self.plan_text.pack(fill="both", expand=True, pady=4)

        ttk.Label(right, text="Activity Log").pack(anchor="w")
        self.log_text = tk.Text(right, wrap="word", state="disabled")
        self.log_text.pack(fill="both", expand=True)
        ttk.Label(right, text="Project Files").pack(anchor="w", pady=(8, 2))
        self.files_list = tk.Listbox(right, height=10)
        self.files_list.pack(fill="x")
        ttk.Label(right, text="Verification / Review").pack(anchor="w", pady=(8, 2))
        self.verify_text = tk.Text(right, height=12, wrap="word")
        self.verify_text.pack(fill="both", expand=True)

        bottom = ttk.Frame(self.root, padding=8)
        bottom.pack(fill="x")
        self.stage_var = tk.StringVar(value="PLAN")
        ttk.Label(bottom, text="Stage:").pack(side="left")
        ttk.Label(bottom, textvariable=self.stage_var).pack(side="left", padx=4)
        ttk.Button(bottom, text="Inspect Project", command=self.inspect_project).pack(side="right")
        ttk.Button(bottom, text="System Status", command=self.system_status).pack(side="right", padx=4)

    def log(self, message: str):
        def add():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, add)

    def set_status(self, status: str, stage: str | None = None):
        self.root.after(0, lambda: self.status_var.set(status))
        if stage:
            self.root.after(0, lambda: self.stage_var.set(stage))

    def refresh_projects(self):
        PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
        names = sorted(p.name for p in PROJECTS_DIR.iterdir() if p.is_dir())
        self.project_combo["values"] = names
        if names and not self.project_var.get():
            self.project_var.set(names[0])
            self.open_project()

    def new_project(self):
        from tkinter.simpledialog import askstring
        name = askstring("New Project", "Project name:")
        if not name:
            return
        name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
        if not name:
            messagebox.showerror("Project", "Invalid project name.")
            return
        path = (PROJECTS_DIR / name).resolve()
        try:
            path.relative_to(PROJECTS_DIR.resolve())
        except ValueError:
            messagebox.showerror("Project", "Invalid project path.")
            return
        path.mkdir(parents=True, exist_ok=True)
        (path / "references").mkdir(exist_ok=True)
        (path / "features").mkdir(exist_ok=True)
        (path / "sprints").mkdir(exist_ok=True)
        (path / "state").mkdir(exist_ok=True)
        (path / "logs").mkdir(exist_ok=True)
        self.project_var.set(name)
        self.refresh_projects()
        self.project_var.set(name)
        self.open_project()

    def open_project(self):
        name = self.project_var.get().strip()
        if not name:
            return
        self.project = (PROJECTS_DIR / name).resolve()
        self.project.mkdir(parents=True, exist_ok=True)
        for d in ("references", "features", "sprints", "state", "logs"):
            (self.project / d).mkdir(exist_ok=True)
        self.references = []
        self.plan_conversation = []
        self.specification = ""
        self.load_project_files()
        self.log(f"[PROJECT] Opened {name}")

    def load_project_files(self):
        self.files_list.delete(0, "end")
        if not self.project:
            return
        for path in sorted(read_project_files(self.project)):
            self.files_list.insert("end", path)

    def add_files(self):
        if not self.project:
            messagebox.showinfo("Project", "Open a project first.")
            return
        paths = filedialog.askopenfilenames(title="Add reference files")
        self.copy_references(paths)

    def add_images(self):
        if not self.project:
            messagebox.showinfo("Project", "Open a project first.")
            return
        paths = filedialog.askopenfilenames(title="Add reference images", filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("All files", "*.*")])
        self.copy_references(paths)

    def copy_references(self, paths):
        if not self.project:
            return
        refdir = self.project / "references"
        refdir.mkdir(exist_ok=True)
        for src_name in paths:
            src = Path(src_name)
            target = refdir / src.name
            if target.exists():
                target = refdir / f"{src.stem}_{datetime.now().strftime('%H%M%S%f')}{src.suffix}"
            target.write_bytes(src.read_bytes())
            self.references.append(target)
        self.references_label.configure(text=f"References: {len(self.references)}")
        self.log(f"[REFERENCES] Added {len(paths)} file(s); references are read-only")

    def clear_references(self):
        self.references.clear()
        self.references_label.configure(text="References: none")

    def start_plan(self):
        if self.running:
            return
        if not self.project:
            messagebox.showinfo("Project", "Open or create a project first.")
            return
        task = self.task_text.get("1.0", "end").strip()
        if not task:
            messagebox.showinfo("Request", "Enter a programming request first.")
            return
        self.task = task
        user_msg = {"role": "user", "content": task}
        self.plan_conversation.append(user_msg)
        self.running = True
        self.plan_btn.configure(state="disabled")
        self.approve_btn.configure(state="disabled")
        self.set_status("MANAGER", "PLAN")
        self.log("[MANAGER] Planning / revising...")
        threading.Thread(target=self._plan_worker, daemon=True).start()

    def _plan_worker(self):
        try:
            response = manager_plan(self.task, self.project, self.plan_conversation)
            self.plan_conversation.append({"role": "assistant", "content": response})
            self.root.after(0, lambda: self._show_plan(response))
        except Exception as exc:
            self.log(f"[ERROR] Manager: {type(exc).__name__}: {exc}")
        finally:
            self.root.after(0, lambda: self._plan_finished())

    def _show_plan(self, response):
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("1.0", response)
        self.log("[MANAGER] Plan updated. Ask questions or request changes, then approve explicitly.")

    def _plan_finished(self):
        self.running = False
        self.plan_btn.configure(state="normal")
        self.approve_btn.configure(state="normal")
        self.set_status("WAITING FOR USER", "PLAN")

    def approve_plan(self):
        if self.running or not self.project:
            return
        specification = self.plan_text.get("1.0", "end").strip()
        if not specification:
            return
        self.specification = specification
        feature_id = re.search(r"(?im)^\s*FEATURE_ID:\s*(\S+)", specification)
        fid = feature_id.group(1) if feature_id else f"F{datetime.now().strftime('%Y%m%d%H%M%S')}"
        sprint = self.project / "sprints" / fid
        sprint.mkdir(parents=True, exist_ok=True)
        (sprint / "specification.md").write_text(specification, encoding="utf-8")
        state = {"status":"approved", "feature_id":fid, "task":self.task, "cycle":0, "max_cycles":MAX_CYCLES, "manager_model":MANAGER_MODEL, "coder_model":CODER_MODEL}
        save_state(self.project, state)
        self.approve_btn.configure(state="disabled")
        self.plan_btn.configure(state="disabled")
        self.running = True
        self.set_status("CODER", "CODE")
        self.log("[APPROVAL] Plan frozen. Starting implementation.")
        threading.Thread(target=self._pipeline_worker, daemon=True).start()

    def stop_pipeline(self):
        self.log("[STOP] Stop requested. Current model call cannot be force-killed safely; pipeline will stop before the next cycle.")
        self.running = False
        self.stop_btn.configure(state="disabled")

    def _pipeline_worker(self):
        review_feedback = ""
        try:
            targets = approved_targets(self.specification)
            runtime_enabled = parse_runtime(self.specification)
            for cycle in range(1, MAX_CYCLES + 1):
                if not self.running:
                    break
                self.cycle = cycle
                self.set_status(f"CODER CYCLE {cycle}/{MAX_CYCLES}", "CODE")
                self.log(f"[CODER] Cycle {cycle}/{MAX_CYCLES}")
                generated = coder(self.task, self.specification, self.project, review_feedback)
                if targets:
                    unexpected = sorted(set(generated) - targets)
                    if unexpected:
                        msg = (
                            "Coder attempted unapproved target(s): "
                            + ", ".join(unexpected)
                            + "\nAPPROVED TARGETS:\n- "
                            + "\n- ".join(sorted(targets))
                            + "\nGenerate files only for the approved targets."
                        )
                        self.log("[CODER] Rejected output: " + ", ".join(unexpected))
                        review_feedback = msg
                        state = {
                            "status": "rejected",
                            "task": self.task,
                            "feature_id": re.search(r"(?im)^\s*FEATURE_ID:\s*(\S+)", self.specification).group(1) if re.search(r"(?im)^\s*FEATURE_ID:\s*(\S+)", self.specification) else "feature",
                            "cycle": cycle,
                            "max_cycles": MAX_CYCLES,
                            "error": msg,
                        }
                        save_state(self.project, state)
                        save_history(self.project, cycle, state)
                        continue
                changed = write_files(self.project, generated)
                self.log("[CODER] Wrote: " + ", ".join(changed))
                self.set_status("VERIFY", "VERIFY")
                verification = verify(self.project, runtime_enabled)
                self.root.after(0, lambda v=verification: self._show_verification(v))
                self.set_status("MANAGER REVIEW", "REVIEW")
                review = manager_review(self.task, self.specification, self.project, verification)
                verified = "VERDICT: VERIFIED" in review and verification["passed"]
                state = {"status":"verified" if verified else "rejected", "task":self.task, "feature_id":re.search(r"(?im)^\s*FEATURE_ID:\s*(\S+)", self.specification).group(1) if re.search(r"(?im)^\s*FEATURE_ID:\s*(\S+)", self.specification) else "feature", "cycle":cycle, "max_cycles":MAX_CYCLES, "verification":verification, "review":review}
                save_state(self.project, state)
                save_history(self.project, cycle, state)
                self.root.after(0, lambda r=review: self._show_review(r))
                self.log("[REVIEW] " + ("VERIFIED" if verified else "REJECTED"))
                if verified:
                    git_checkpoint(self.project, f"verified feature - cycle {cycle}")
                    self.root.after(0, lambda: self._pipeline_done(True))
                    return
                review_feedback = review + "\n\nVERIFICATION EVIDENCE:\n" + json.dumps(verification, indent=2, ensure_ascii=False)
            if self.running and self.cycle >= MAX_CYCLES:
                state = {"status":"blocked", "task":self.task, "cycle":MAX_CYCLES, "max_cycles":MAX_CYCLES, "reason":"Maximum fix cycles reached. User decision required."}
                save_state(self.project, state)
                self.root.after(0, lambda: self._pipeline_done(False, blocked=True))
        except Exception as exc:
            self.log(f"[ERROR] Pipeline: {type(exc).__name__}: {exc}")
            if self.project:
                save_state(self.project, {"status":"error", "cycle":self.cycle, "error":f"{type(exc).__name__}: {exc}"})
            self.root.after(0, lambda: self._pipeline_done(False))

    def _show_verification(self, verification):
        self.verify_text.delete("1.0", "end")
        self.verify_text.insert("1.0", json.dumps(verification, indent=2, ensure_ascii=False))

    def _show_review(self, review):
        self.verify_text.insert("end", "\n\n=== MANAGER REVIEW ===\n" + review)

    def _pipeline_done(self, success: bool, blocked: bool = False):
        self.running = False
        self.stop_btn.configure(state="disabled")
        self.plan_btn.configure(state="normal")
        self.approve_btn.configure(state="disabled")
        self.load_project_files()
        if success:
            self.set_status("COMPLETE", "COMPLETE")
            self.log("[COMPLETE] Feature verified and checkpointed.")
        elif blocked:
            self.set_status("BLOCKED", "COMPLETE")
            self.log("[BLOCKED] Maximum 5 cycles reached. User decision required.")
        else:
            self.set_status("ERROR", "COMPLETE")

    def inspect_project(self):
        if not self.project:
            return
        files = read_project_files(self.project)
        self.plan_text.delete("1.0", "end")
        self.plan_text.insert("1.0", format_files(files))

    def system_status(self):
        messagebox.showinfo("System Status", f"Supervisor: {APP_DIR}\nManager: {MANAGER_MODEL}\nCoder: {CODER_MODEL}\nOllama: {OLLAMA_BASE_URL}\nMax cycles: {MAX_CYCLES}")


def main() -> int:
    root = tk.Tk()
    SupervisorApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
