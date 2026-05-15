import * as vscode from "vscode";
import * as http from "http";
import * as https from "https";
import { URL } from "url";

/**
 * EarCoach — VS Code extension
 *
 * Watches the active editor for two "stuck" signals:
 *   1. Long typing pause (default: 90s) while diagnostics are present
 *   2. Backspace churn — many deletions in a short window on the same line
 *
 * When a stuck signal fires, it grabs the current code, the line the cursor is on,
 * and any errors flagged by VS Code's Diagnostics API, then POSTs all of it to the
 * EarCoach backend, which generates a Socratic audio hint.
 */

let lastEditTime = Date.now();
let backspaceTimestamps: number[] = [];
let lastHintTime = 0;
let isEnabled = true;
let statusBar: vscode.StatusBarItem;
let idleTimer: NodeJS.Timeout | undefined;
let lastHintText = "";
let hintActive = false;

export function activate(context: vscode.ExtensionContext) {
  console.log("[EarCoach] activated");

  statusBar = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBar.command = "earcoach.toggle";
  updateStatusBar();
  statusBar.show();
  context.subscriptions.push(statusBar);

  // Track every text edit so we can detect pauses + backspace churn.
  const SUPPORTED_LANGUAGES = ["python", "javascript", "typescript", "java", "cpp", "c"];

  const onChange = vscode.workspace.onDidChangeTextDocument((e) => {
    if (!isEnabled) return;
    if (e.document !== vscode.window.activeTextEditor?.document) return;
    if (!SUPPORTED_LANGUAGES.includes(e.document.languageId)) return;

    lastEditTime = Date.now();

    // Did this change include a deletion?
    for (const change of e.contentChanges) {
      if (change.text.length === 0 && change.rangeLength > 0) {
        backspaceTimestamps.push(Date.now());
      }
    }
    pruneBackspaceWindow();
    maybeFireBackspaceChurn();

    // Reschedule the idle check.
    scheduleIdleCheck();
  });
  context.subscriptions.push(onChange);

  // Manual trigger.
  context.subscriptions.push(
    vscode.commands.registerCommand("earcoach.askForHint", () => {
      void requestHint("manual");
    })
  );

  // Toggle command.
  context.subscriptions.push(
    vscode.commands.registerCommand("earcoach.toggle", () => {
      isEnabled = !isEnabled;
      updateStatusBar();
      vscode.window.showInformationMessage(
        `EarCoach is now ${isEnabled ? "ON" : "OFF"}.`
      );
    })
  );

  // Dismiss current hint (Escape / AirPods tap proxy).
  context.subscriptions.push(
    vscode.commands.registerCommand("earcoach.dismiss", () => {
      hintActive = false;
      vscode.commands.executeCommand("setContext", "earcoachHintActive", false);
      vscode.window.setStatusBarMessage("$(headphones) EarCoach: hint dismissed", 2000);
      lastHintText = "";
    })
  );

  // Follow-up: ask the LLM to elaborate on the last hint.
  context.subscriptions.push(
    vscode.commands.registerCommand("earcoach.followUp", () => {
      void requestHint("follow_up");
    })
  );

  // Also fire idle check when switching to a different file.
  const onEditorChange = vscode.window.onDidChangeActiveTextEditor(() => {
    lastEditTime = Date.now();
    scheduleIdleCheck();
  });
  context.subscriptions.push(onEditorChange);

  scheduleIdleCheck();
}

export function deactivate() {
  if (idleTimer) clearTimeout(idleTimer);
}

function updateStatusBar() {
  statusBar.text = isEnabled ? "$(headphones) EarCoach" : "$(circle-slash) EarCoach";
  statusBar.tooltip = isEnabled
    ? "EarCoach is listening. Click to disable."
    : "EarCoach is paused. Click to enable.";
}

function getConfig() {
  return vscode.workspace.getConfiguration("earcoach");
}

function pruneBackspaceWindow() {
  const windowMs = getConfig().get<number>("backspaceWindowMs", 30000);
  const cutoff = Date.now() - windowMs;
  backspaceTimestamps = backspaceTimestamps.filter((t) => t >= cutoff);
}

function maybeFireBackspaceChurn() {
  const threshold = getConfig().get<number>("backspaceThreshold", 8);
  if (backspaceTimestamps.length >= threshold) {
    backspaceTimestamps = []; // reset so we don't fire repeatedly
    void requestHint("backspace_churn");
  }
}

function scheduleIdleCheck() {
  if (idleTimer) clearTimeout(idleTimer);
  const pauseMs = getConfig().get<number>("pauseThresholdMs", 10000);
  idleTimer = setTimeout(() => {
    console.log("[EarCoach] idle timer fired, isEnabled=" + isEnabled);
    if (!isEnabled) return;
    const idleFor = Date.now() - lastEditTime;
    console.log("[EarCoach] idleFor=" + idleFor + " pauseMs=" + pauseMs);
    if (idleFor >= pauseMs) {
      console.log("[EarCoach] firing requestHint");
      void requestHint("long_pause");
    } else {
      scheduleIdleCheck();
    }
  }, pauseMs);
}

function hasActiveDiagnostics(): boolean {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return false;
  const diags = vscode.languages.getDiagnostics(editor.document.uri);
  return diags.some(
    (d) =>
      d.severity === vscode.DiagnosticSeverity.Error ||
      d.severity === vscode.DiagnosticSeverity.Warning
  );
}

function snapshotContext(trigger: string) {
  const editor = vscode.window.activeTextEditor;
  if (!editor) return null;

  const doc = editor.document;
  const cursorLine = editor.selection.active.line + 1; // 1-indexed for the LLM
  const code = doc.getText();
  const language = doc.languageId;

  const diags = vscode.languages
    .getDiagnostics(doc.uri)
    .filter(
      (d) =>
        d.severity === vscode.DiagnosticSeverity.Error ||
        d.severity === vscode.DiagnosticSeverity.Warning
    )
    .map((d) => ({
      message: d.message,
      line: d.range.start.line + 1,
      severity:
        d.severity === vscode.DiagnosticSeverity.Error ? "error" : "warning",
      source: d.source ?? null,
    }));

  return {
    trigger,
    language,
    cursor_line: cursorLine,
    code,
    diagnostics: diags,
    file_name: doc.fileName.split(/[\\/]/).pop() ?? "untitled",
    previous_hint: trigger === "follow_up" ? lastHintText : "",
  };
}

async function requestHint(trigger: string) {
  const cooldown = getConfig().get<number>("cooldownMs", 15000);
  const timeSinceLast = Date.now() - lastHintTime;
  console.log("[EarCoach] requestHint trigger=" + trigger + " cooldown=" + cooldown + " timeSinceLast=" + timeSinceLast);
  if (trigger !== "manual" && timeSinceLast < cooldown) {
    console.log("[EarCoach] blocked by cooldown");
    return;
  }

  const ctx = snapshotContext(trigger);
  if (!ctx) return;

  // For automatic triggers, only fire if there's code in the file.
  if (trigger !== "manual" && ctx.code.trim().length === 0) {
    scheduleIdleCheck();
    return;
  }

  lastHintTime = Date.now();
  const url = getConfig().get<string>("backendUrl", "http://localhost:8000/hint");

  try {
    const response = await postJson(url, ctx);
    if (response.hint) {
      lastHintText = response.hint;
      hintActive = true;
      vscode.commands.executeCommand("setContext", "earcoachHintActive", true);
      vscode.window.setStatusBarMessage(`$(headphones) ${response.hint}`, 15000);
    }
  } catch (err) {
    console.error("[EarCoach] backend call failed:", err);
    vscode.window.setStatusBarMessage(
      "$(warning) EarCoach: backend not reachable",
      5000
    );
  } finally {
    scheduleIdleCheck();
  }
}

function postJson(urlStr: string, body: unknown): Promise<any> {
  return new Promise((resolve, reject) => {
    const url = new URL(urlStr);
    const lib = url.protocol === "https:" ? https : http;
    const data = Buffer.from(JSON.stringify(body), "utf-8");
    const req = lib.request(
      {
        hostname: url.hostname,
        port: url.port || (url.protocol === "https:" ? 443 : 80),
        path: url.pathname + url.search,
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Content-Length": data.length,
        },
      },
      (res) => {
        const chunks: Buffer[] = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const text = Buffer.concat(chunks).toString("utf-8");
          try {
            resolve(text ? JSON.parse(text) : {});
          } catch {
            resolve({ raw: text });
          }
        });
      }
    );
    req.on("error", reject);
    req.write(data);
    req.end();
  });
}
