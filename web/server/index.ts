import express from "express";
import mammoth from "mammoth";
import multer from "multer";
import * as XLSX from "xlsx";
import { spawn, type ChildProcessWithoutNullStreams } from "child_process";
import crypto from "crypto";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { createServer } from "http";
import { WebSocketServer } from "ws";

const serverDir = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(serverDir, "..");
const repoRoot = path.resolve(webRoot, "..");
const runsRoot = path.join(repoRoot, "runs");
const contractsRoot = path.join(webRoot, "contracts");
const pythonBin = process.env.PYTHON || "python";
const configPath = path.join(webRoot, "server.config.json");
const serverConfig = readJsonFile(configPath) ?? {};
const authConfig = serverConfig.auth && typeof serverConfig.auth === "object" ? serverConfig.auth : {};
const listenConfig = serverConfig.server && typeof serverConfig.server === "object" ? serverConfig.server : {};
const apiHost = String(listenConfig.apiHost || "127.0.0.1");
const apiPort = Number(listenConfig.apiPort || 8787);
const authEnabled = Boolean(authConfig.enabled);
const authUsername = String(authConfig.username || "admin");
const authPassword = authEnabled ? String(authConfig.password || "") : "";
const sessionSecret = String(authConfig.sessionSecret || authPassword || "loopforge-local-dev");
const sessionTtlMs = Math.max(1, Number(authConfig.sessionTtlHours || 12)) * 60 * 60 * 1000;
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 12 * 1024 * 1024 }
});

type RunStatus = "starting" | "running" | "exited" | "stopped";

type RunRecord = {
  id: string;
  runDir: string;
  status: RunStatus;
  startedAt: string;
  params: Record<string, unknown>;
  child?: ChildProcessWithoutNullStreams;
};

const activeRuns = new Map<string, RunRecord>();

type ContractInput = {
  goal?: string;
  datasetSample?: string;
  datasetFile?: {
    name?: string;
    type?: string;
    size?: number;
    extracted_kind?: string;
  };
  evaluatorScript?: string;
  rubric?: string;
};

function previewText(text: string, maxChars = 20000) {
  const normalized = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  return normalized.length > maxChars ? normalized.slice(0, maxChars) + "\n...[truncated]" : normalized;
}

async function extractUploadedDataset(file: Express.Multer.File) {
  const ext = path.extname(file.originalname).toLowerCase();
  if ([".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".py", ".log"].includes(ext)) {
    return {
      kind: ext.slice(1) || "text",
      text: previewText(file.buffer.toString("utf8")),
      sheets: [] as string[]
    };
  }
  if ([".xlsx", ".xls", ".xlsm"].includes(ext)) {
    const workbook = XLSX.read(file.buffer, { type: "buffer" });
    const chunks: string[] = [];
    for (const name of workbook.SheetNames.slice(0, 8)) {
      const sheet = workbook.Sheets[name];
      const csv = XLSX.utils.sheet_to_csv(sheet, { FS: "\t" });
      chunks.push(`# Sheet: ${name}\n${csv}`);
    }
    return {
      kind: "excel",
      text: previewText(chunks.join("\n\n")),
      sheets: workbook.SheetNames
    };
  }
  if (ext === ".docx") {
    const result = await mammoth.extractRawText({ buffer: file.buffer });
    return {
      kind: "docx",
      text: previewText(result.value),
      sheets: [] as string[],
      warnings: result.messages.map((message) => message.message)
    };
  }
  if (ext === ".doc") {
    return {
      kind: "unsupported_word_doc",
      text: "",
      sheets: [] as string[],
      warnings: ["Legacy .doc is not supported yet. Please upload .docx, .md, .txt, .json, or .xlsx."]
    };
  }
  return {
    kind: "binary_or_unknown",
    text: "",
    sheets: [] as string[],
    warnings: [`Unsupported file extension: ${ext || "none"}`]
  };
}

function inferDatasetFormat(sample: string) {
  const first = sample.trim().split(/\r?\n/)[0] ?? "";
  if (!sample.trim()) return { kind: "missing", structure: "No evaluation set provided." };
  if (first.trim().startsWith("{") || first.trim().startsWith("[")) {
    return { kind: "json", structure: "JSON/JSONL-like evaluation records." };
  }
  if (first.includes("\t")) {
    return { kind: "tsv", structure: `TSV columns: ${first.split("\t").join(", ")}` };
  }
  if (first.includes(",")) {
    return { kind: "csv", structure: `CSV-like first row: ${first}` };
  }
  return { kind: "text", structure: "Plain text cases or task descriptions." };
}

function inferMetricDirection(goal: string) {
  const lower = goal.toLowerCase();
  if (/minimi[sz]e|lower|penalty|cost|loss|error|惩罚|成本|越低/.test(lower)) return "minimize";
  if (/maximi[sz]e|higher|score|accuracy|reward|覆盖|越高/.test(lower)) return "maximize";
  return "maximize";
}

function extractPythonFunctions(script: string) {
  const names = [...script.matchAll(/^\s*def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(/gm)].map((m) => m[1]);
  return [...new Set(names)];
}

function buildAdapterPreview(functionNames: string[]) {
  const preferred = functionNames.find((name) => /eval|judge|score|metric|test/i.test(name)) ?? functionNames[0] ?? null;
  if (!preferred) {
    return [
      "def evaluate(candidate_path: str, dataset_path: str | None = None) -> dict:",
      "    # No callable evaluator was found in the uploaded script.",
      "    # Fill this adapter with cloud-safe evaluation logic before running the agent.",
      "    return {\"ok\": False, \"feedback\": \"No evaluator function found\"}",
      ""
    ].join("\n");
  }
  return [
    "def evaluate(candidate_path: str, dataset_path: str | None = None) -> dict:",
    `    raw = ${preferred}(candidate_path, dataset_path)`,
    "    # Normalize arbitrary user output into EvalResult.",
    "    if isinstance(raw, dict):",
    "        return raw",
    "    return {",
    "        \"ok\": True,",
    "        \"primary_score\": float(raw),",
    "        \"hard_pass\": True,",
    "        \"metrics\": {},",
    "        \"feedback\": \"normalized from user evaluator\"",
    "    }",
    ""
  ].join("\n");
}

function buildContractDraft(input: ContractInput) {
  const goal = String(input.goal ?? "").trim();
  const datasetSample = String(input.datasetSample ?? "");
  const evaluatorScript = String(input.evaluatorScript ?? "");
  const rubric = String(input.rubric ?? "").trim();
  const dataset = inferDatasetFormat(datasetSample);
  const functions = extractPythonFunctions(evaluatorScript);
  const hasDataset = dataset.kind !== "missing";
  const hasScript = evaluatorScript.trim().length > 0;
  const direction = inferMetricDirection(goal);
  const evaluatorType = hasScript ? "generated_python_adapter" : hasDataset ? "semantic_proxy_metrics" : "llm_as_judge";
  const diagnostics = [
    hasDataset ? `Detected evaluation set format: ${dataset.kind}` : "No evaluation set provided; defaulting to LLM-as-judge fallback.",
    hasScript ? `Detected Python functions: ${functions.length ? functions.join(", ") : "none"}` : "No evaluator script provided.",
    hasScript ? "Uploaded script is treated as source material; the web server does not execute arbitrary commands directly." : "A cloud-safe evaluator adapter should be generated or edited before agent execution.",
    rubric ? "Rubric is available for LLM judge or semantic feedback." : "No rubric provided; contract uses the goal text as judge guidance."
  ];

  return {
    contract: {
      version: 1,
      target_file: "solver.py",
      scope: "solver_py_only",
      entrypoint: "solve(input_text: str) -> list",
      user_goal: goal || "Improve the candidate solver against the configured evaluator.",
      input_contract: {
        dataset_kind: dataset.kind,
        structure: dataset.structure,
        source_file: input.datasetFile ?? null,
        sample_preview: datasetSample.trim().slice(0, 1200),
        has_labels: /label|answer|expected|gold|target|答案|标签/.test(datasetSample.toLowerCase())
      },
      output_contract: {
        description: "Candidate solver must expose the configured entrypoint and return a judge-compatible result.",
        dependency_policy: "solver.py should remain self-contained unless this contract explicitly allows dependencies."
      },
      evaluator: {
        type: evaluatorType,
        adapter_name: "evaluate(candidate_path: str, dataset_path: str | None = None) -> dict",
        source_script_functions: functions,
        adapter_preview: buildAdapterPreview(functions),
        llm_judge_enabled: !hasDataset || !hasScript,
        rubric: rubric || goal || "Judge whether the candidate output better satisfies the task objective than the baseline."
      },
      metrics: {
        primary: hasScript ? "primary_score" : "llm_pairwise_preference",
        direction,
        hard_constraints: ["candidate must run without crashing", "candidate output must match the declared output contract"],
        accept_rule: "hard_pass == true and primary metric improves over baseline"
      },
      cloud_policy: {
        arbitrary_local_command_execution: false,
        evaluator_script_mode: "inspect_and_adapt",
        validation_required_before_agent_run: true
      },
      analysis_source: "local_semantic_scaffold"
    },
    diagnostics
  };
}

function makeRunId() {
  const stamp = new Date().toISOString().replace(/[-:T.Z]/g, "").slice(0, 14);
  const suffix = Math.random().toString(36).slice(2, 8);
  return `web_${stamp}_${suffix}`;
}

function safeNumber(value: unknown, fallback: number, min = 0, max = Number.MAX_SAFE_INTEGER) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

function signPayload(payload: string) {
  return crypto.createHmac("sha256", sessionSecret).update(payload).digest("base64url");
}

function createSessionToken() {
  const payload = Buffer.from(JSON.stringify({
    iat: Date.now(),
    exp: Date.now() + sessionTtlMs
  })).toString("base64url");
  return `${payload}.${signPayload(payload)}`;
}

function verifySessionToken(token: string | null | undefined) {
  if (!authPassword) return true;
  if (!token || !token.includes(".")) return false;
  const [payload, signature] = token.split(".", 2);
  const expected = signPayload(payload);
  const provided = Buffer.from(signature);
  const target = Buffer.from(expected);
  if (provided.length !== target.length || !crypto.timingSafeEqual(provided, target)) return false;
  try {
    const parsed = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
    return Number(parsed.exp) > Date.now();
  } catch {
    return false;
  }
}

function requestToken(req: express.Request) {
  const header = req.header("Authorization") || "";
  if (header.startsWith("Bearer ")) return header.slice("Bearer ".length).trim();
  return "";
}

function appendEvent(runDir: string, eventType: string, payload: Record<string, unknown>) {
  fs.mkdirSync(runDir, { recursive: true });
  const record = {
    time_local: new Date().toLocaleString("zh-CN", { hour12: false }),
    event_type: eventType,
    payload
  };
  fs.appendFileSync(path.join(runDir, "events.jsonl"), JSON.stringify(record) + "\n", "utf8");
}

function readJsonFile(filePath: string) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return null;
  }
}

function resolveRepoPath(inputPath: string) {
  const resolved = path.isAbsolute(inputPath) ? path.resolve(inputPath) : path.resolve(repoRoot, inputPath);
  const relative = path.relative(repoRoot, resolved);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error("Path is outside repository");
  }
  return resolved;
}

function listRunDirs() {
  if (!fs.existsSync(runsRoot)) return [];
  return fs.readdirSync(runsRoot, { withFileTypes: true })
    .filter((entry) => entry.isDirectory())
    .map((entry) => {
      const id = entry.name;
      const runDir = path.join(runsRoot, id);
      const summary = readJsonFile(path.join(runDir, "summary.json"));
      const active = activeRuns.get(id);
      const stat = fs.statSync(runDir);
      return {
        id,
        runDir,
        status: active?.status ?? (summary ? "exited" : "starting"),
        startedAt: active?.startedAt ?? stat.birthtime.toISOString(),
        summary
      };
    })
    .sort((a, b) => b.startedAt.localeCompare(a.startedAt))
    .slice(0, 30);
}

const app = express();
app.use(express.json({ limit: "6mb" }));

app.get("/api/auth/status", (_req, res) => {
  res.json({
    appName: "LoopForge",
    authRequired: authEnabled,
    usernameRequired: authEnabled
  });
});

app.post("/api/auth/login", (req, res) => {
  if (!authEnabled) {
    res.json({ ok: true, token: createSessionToken() });
    return;
  }
  const username = String(req.body?.username ?? "");
  const password = String(req.body?.password ?? "");
  if (username !== authUsername || password !== authPassword) {
    res.status(401).json({ ok: false, error: "账号或密码不正确" });
    return;
  }
  res.json({ ok: true, token: createSessionToken() });
});

app.use((req, res, next) => {
  if (!authEnabled || req.path === "/api/health" || req.path.startsWith("/api/auth/")) {
    next();
    return;
  }
  if (!verifySessionToken(requestToken(req))) {
    res.status(401).json({ ok: false, error: "需要登录" });
    return;
  }
  next();
});

app.get("/api/health", (_req, res) => {
  res.json({ ok: true, repoRoot, runsRoot });
});

app.get("/api/skills", (_req, res) => {
  const skillsDir = path.join(repoRoot, "agent", "skills");
  const inferScope = (id: string) => {
    if (["scarce_repair", "online_result_iteration"].includes(id)) return "project";
    if (id === "self_extend_skill") return "system";
    return "generic";
  };
  const parseMeta = (body: string) => {
    const meta: Record<string, string> = {};
    if (!body.startsWith("---")) return meta;
    const end = body.indexOf("\n---", 3);
    if (end < 0) return meta;
    for (const line of body.slice(3, end).trim().split(/\r?\n/)) {
      const idx = line.indexOf(":");
      if (idx < 0) continue;
      meta[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim();
    }
    return meta;
  };
  const skills = fs.existsSync(skillsDir)
    ? fs.readdirSync(skillsDir)
      .filter((name) => name.endsWith(".md"))
      .map((name) => {
        const body = fs.readFileSync(path.join(skillsDir, name), "utf8");
        const id = name.replace(/\.md$/, "");
        const meta = parseMeta(body);
        return {
          id: meta.id ?? id,
          name: meta.name ?? id,
          description: meta.description ?? "",
          scope: meta.scope ?? inferScope(meta.id ?? id),
          triggers: (meta.triggers ?? "").split(",").map((item) => item.trim()).filter(Boolean)
        };
      })
    : [];
  res.json({ skills });
});

app.get("/api/tools", (_req, res) => {
  res.json({
    tools: [
      {
        id: "list_files",
        name: "列出文件",
        category: "项目内文件",
        description: "按模式查看项目目录下的候选文件，用于定位 solver、数据、日志和脚本。",
        safety: "只读；路径限制在项目目录内。"
      },
      {
        id: "read_file",
        name: "读取文件",
        category: "项目内文件",
        description: "读取项目内文本文件内容，给模型提供实现、评测结果或文档证据。",
        safety: "只读；拒绝访问项目目录外路径。"
      },
      {
        id: "analyze_online_results",
        name: "分析线上结果",
        category: "评测证据",
        description: "解析已知线上分数和分 case 表现，找出退化场景与改进重点。",
        safety: "只读；输入来自运行上下文或用户粘贴结果。"
      },
      {
        id: "write_analysis_script",
        name: "生成分析脚本",
        category: "项目内实验",
        description: "在本次 run 目录下写入 Python 分析/重放脚本，用于辅助理解数据和策略行为。",
        safety: "只能写到 runs/<run_id>/tool_scripts。"
      },
      {
        id: "run_python",
        name: "运行 Python",
        category: "项目内实验",
        description: "执行上一步生成的项目内 Python 脚本，返回 stdout/stderr 和退出码。",
        safety: "不开放任意 shell；脚本路径限制在项目目录内。"
      },
      {
        id: "read_local_papers",
        name: "读取本地论文",
        category: "调研",
        description: "从 papers/ 和项目文档中提取可迁移的算法搜索、经验蒸馏、自进化设计线索。",
        safety: "只读；优先使用本地材料。"
      },
      {
        id: "arxiv_search",
        name: "ArXiv 检索",
        category: "调研",
        description: "联网检索相关论文摘要，辅助寻找新的启发式或 Agent 设计方向。",
        safety: "仅在允许联网且 live/research 路径需要时使用。"
      },
      {
        id: "web_fetch_url",
        name: "网页读取",
        category: "调研",
        description: "读取指定网页内容，补充赛题、论文、榜单或工具文档信息。",
        safety: "只读取用户/模型指定 URL，不执行网页脚本。"
      },
      {
        id: "generate_solver",
        name: "生成 solver",
        category: "求解器迭代",
        description: "根据目标、经验、skill 和证据生成候选 solver.py。",
        safety: "候选先写入 run 目录，默认不覆盖根目录 solver.py。"
      },
      {
        id: "validate_solver",
        name: "静态验证",
        category: "求解器迭代",
        description: "检查 solve(input_text) 接口、依赖约束和基本语法。",
        safety: "只验证候选文件。"
      },
      {
        id: "evaluate_local",
        name: "本地评测",
        category: "求解器迭代",
        description: "运行本地沙箱评测候选 solver，输出分数、完成率、回归信息和经验。",
        safety: "受 sandboxTimeout、轮数、时间预算约束。"
      },
      {
        id: "select_skill",
        name: "加载 Skill",
        category: "能力管理",
        description: "按目标和当前状态选择通用/项目/系统 skill，把其正文加入下一轮上下文。",
        safety: "只读 skill；显式选择的 skill 会优先加载。"
      },
      {
        id: "write_skill",
        name: "写入 Skill",
        category: "能力管理",
        description: "把稳定经验沉淀成新的 Markdown skill，后续运行会预加载描述并可动态选择。",
        safety: "只有开启“写入 skill”后可用。"
      }
    ]
  });
});

app.post("/api/contracts/analyze", (req, res) => {
  const draft = buildContractDraft(req.body ?? {});
  res.json(draft);
});

app.post("/api/contracts/upload-dataset", upload.single("dataset"), async (req, res) => {
  if (!req.file) {
    res.status(400).json({ ok: false, error: "dataset file is required" });
    return;
  }
  try {
    const extracted = await extractUploadedDataset(req.file);
    res.json({
      ok: true,
      file: {
        name: req.file.originalname,
        type: req.file.mimetype,
        size: req.file.size,
        extracted_kind: extracted.kind,
        sheets: extracted.sheets,
        warnings: "warnings" in extracted ? extracted.warnings : []
      },
      text: extracted.text,
      preview_chars: extracted.text.length
    });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error instanceof Error ? error.message : String(error)
    });
  }
});

app.post("/api/contracts/validate", (req, res) => {
  const contract = req.body?.contract ?? req.body;
  const errors: string[] = [];
  const warnings: string[] = [];
  if (!contract || typeof contract !== "object") errors.push("Contract must be a JSON object.");
  if (!contract?.target_file) errors.push("target_file is required.");
  if (!contract?.entrypoint) errors.push("entrypoint is required.");
  if (!contract?.evaluator?.type) errors.push("evaluator.type is required.");
  if (!contract?.metrics?.primary) errors.push("metrics.primary is required.");
  if (!["minimize", "maximize"].includes(String(contract?.metrics?.direction ?? ""))) {
    errors.push("metrics.direction must be minimize or maximize.");
  }
  if (contract?.evaluator?.type === "llm_as_judge" && !contract?.evaluator?.rubric) {
    warnings.push("LLM-as-judge is enabled but rubric is empty.");
  }
  if (contract?.evaluator?.type === "generated_python_adapter" && !contract?.evaluator?.adapter_preview) {
    warnings.push("Python adapter is selected but adapter_preview is empty.");
  }
  res.json({
    ok: errors.length === 0,
    errors,
    warnings,
    normalized_eval_result_schema: {
      ok: "boolean",
      primary_score: "number|string",
      hard_pass: "boolean",
      metrics: "object",
      case_results: "array",
      feedback: "string"
    }
  });
});

app.post("/api/contracts/save", (req, res) => {
  const contract = req.body?.contract ?? req.body;
  fs.mkdirSync(contractsRoot, { recursive: true });
  const filePath = path.join(contractsRoot, "latest_evaluation_contract.json");
  fs.writeFileSync(filePath, JSON.stringify(contract, null, 2), "utf8");
  res.json({ ok: true, path: filePath });
});

app.get("/api/runs", (_req, res) => {
  res.json({ runs: listRunDirs() });
});

app.post("/api/runs", (req, res) => {
  const body = req.body ?? {};
  const id = makeRunId();
  const runDir = path.join(runsRoot, id);
  const maxRounds = safeNumber(body.maxRounds, 3, 1, 100);
  const maxSeconds = safeNumber(body.maxSeconds, 0, 0, 24 * 60 * 60);
  const maxTokens = safeNumber(body.maxTokens, 0, 0, 10_000_000);
  const evalSeeds = safeNumber(body.evalSeeds, 1, 1, 20);
  const sandboxTimeout = safeNumber(body.sandboxTimeout, 5, 1, 60);
  const researchOnStall = safeNumber(body.researchOnStall, 0, 0, 100);
  const researchEvery = safeNumber(body.researchEvery, 0, 0, 100);
  const maxSkills = safeNumber(body.maxSkills, 4, 0, 10);
  const skillWriteOnStall = safeNumber(body.skillWriteOnStall, 4, 1, 100);
  const projectToolSteps = safeNumber(body.projectToolSteps, 6, 0, 20);
  const projectTools = body.projectTools !== false;
  const goal = String(body.goal ?? "").trim();
  const contract = body.contract && typeof body.contract === "object" ? body.contract : null;

  const contractHint = contract
    ? `\nEvaluation contract: target=${contract.target_file}; evaluator=${contract.evaluator?.type}; metric=${contract.metrics?.primary}; direction=${contract.metrics?.direction}; goal=${contract.user_goal ?? goal}`
    : "";

  const args = [
    "search.py",
    "--run-dir", runDir,
    "--max-rounds", String(maxRounds),
    "--max-seconds", String(maxSeconds),
    "--max-tokens", String(maxTokens),
    "--eval-seeds", String(evalSeeds),
    "--sandbox-timeout", String(sandboxTimeout),
    "--research-on-stall", String(researchOnStall),
    "--research-every", String(researchEvery),
    "--max-skills", String(maxSkills),
    "--metric-hints", `${goal ? `Web goal: ${goal}` : "Web goal: explore a conservative solver improvement"}${contractHint}`
  ];
  if (contract) {
    args.push("--evaluation-contract", path.join(runDir, "evaluation_contract.json"));
  }

  if (projectTools) {
    args.push("--enable-project-tools", "--project-tool-warmup", "--project-tool-steps", String(projectToolSteps));
  }
  if (body.live) args.push("--live");
  if (body.initialResearch) args.push("--initial-research");
  if (body.allowSkillWrite) {
    args.push("--allow-skill-write", "--skill-write-on-stall", String(skillWriteOnStall));
  }
  if (body.exportBest) args.push("--export-best");
  for (const skill of Array.isArray(body.skills) ? body.skills : []) {
    if (typeof skill === "string" && skill.trim()) args.push("--skill", skill.trim());
  }

  fs.mkdirSync(runDir, { recursive: true });
  if (contract) {
    fs.writeFileSync(path.join(runDir, "evaluation_contract.json"), JSON.stringify(contract, null, 2), "utf8");
  }
  appendEvent(runDir, "web_process", { status: "starting", args: [pythonBin, ...args], goal });
  if (contract) {
    appendEvent(runDir, "evaluation_contract", {
      status: "attached",
      target_file: contract.target_file,
      evaluator_type: contract.evaluator?.type,
      metric: contract.metrics?.primary,
      direction: contract.metrics?.direction
    });
  }

  const child = spawn(pythonBin, args, {
    cwd: repoRoot,
    env: { ...process.env, PYTHONIOENCODING: "utf-8" }
  });

  const record: RunRecord = {
    id,
    runDir,
    status: "running",
    startedAt: new Date().toISOString(),
    params: body,
    child
  };
  activeRuns.set(id, record);

  child.stdout.on("data", (chunk) => {
    appendEvent(runDir, "web_stdout", { text: chunk.toString("utf8").slice(0, 4000) });
  });
  child.stderr.on("data", (chunk) => {
    appendEvent(runDir, "web_stderr", { text: chunk.toString("utf8").slice(0, 4000) });
  });
  child.on("exit", (code, signal) => {
    record.status = signal ? "stopped" : "exited";
    appendEvent(runDir, "web_process", { status: record.status, code, signal });
  });

  res.json({ id, runDir, status: record.status });
});

app.post("/api/runs/:id/stop", (req, res) => {
  const run = activeRuns.get(req.params.id);
  if (!run?.child) {
    res.status(404).json({ ok: false, error: "run is not active" });
    return;
  }
  run.status = "stopped";
  run.child.kill();
  appendEvent(run.runDir, "web_process", { status: "stop_requested" });
  res.json({ ok: true });
});

app.get("/api/file", (req, res) => {
  try {
    const filePath = resolveRepoPath(String(req.query.path ?? "solver.py"));
    res.json({
      path: filePath,
      content: fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf8") : ""
    });
  } catch (error) {
    res.status(400).json({ error: error instanceof Error ? error.message : String(error) });
  }
});

const httpServer = createServer(app);
const wss = new WebSocketServer({ server: httpServer });

wss.on("connection", (socket, request) => {
  const url = new URL(request.url ?? "", "http://127.0.0.1:8787");
  if (!verifySessionToken(url.searchParams.get("token"))) {
    socket.close(1008, "unauthorized");
    return;
  }
  const match = url.pathname.match(/^\/api\/runs\/([^/]+)\/events$/);
  if (!match) {
    socket.close();
    return;
  }
  const runDir = path.join(runsRoot, match[1]);
  const eventFile = path.join(runDir, "events.jsonl");
  let offset = 0;

  const pump = () => {
    if (!fs.existsSync(eventFile)) return;
    const stat = fs.statSync(eventFile);
    if (stat.size < offset) offset = 0;
    if (stat.size === offset) return;
    const fd = fs.openSync(eventFile, "r");
    const buffer = Buffer.alloc(stat.size - offset);
    fs.readSync(fd, buffer, 0, buffer.length, offset);
    fs.closeSync(fd);
    offset = stat.size;
    for (const line of buffer.toString("utf8").split(/\r?\n/)) {
      if (!line.trim()) continue;
      socket.send(line);
    }
  };

  pump();
  const timer = setInterval(pump, 500);
  socket.on("close", () => clearInterval(timer));
});

httpServer.listen(apiPort, apiHost, () => {
  console.log(`LoopForge API listening on http://${apiHost}:${apiPort}`);
  console.log(authEnabled ? `LoopForge auth enabled via ${configPath}` : "LoopForge auth disabled; keep API bound to localhost");
});
