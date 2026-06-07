import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DiffEditor } from "@monaco-editor/react";
import ReactFlow, { Background, Controls, MarkerType, type Edge, type Node } from "reactflow";
import { AnimatePresence, motion } from "framer-motion";
import {
  Activity,
  Beaker,
  Brain,
  CheckCircle2,
  ClipboardCheck,
  Code2,
  FileText,
  FileUp,
  FlaskConical,
  GitBranch,
  ListTree,
  PauseCircle,
  Play,
  RefreshCcw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  Wrench,
  XCircle
} from "lucide-react";
import type { AgentEvent, EvaluationContract, RunSummary, SkillItem, ToolItem } from "./types";

type DecisionStep = {
  id: string;
  kind: "context" | "decision" | "tool" | "skill" | "code" | "check" | "eval" | "reflection";
  title: string;
  subtitle: string;
  reason?: string;
  purpose?: string;
  params?: Record<string, string | number | boolean | null | undefined>;
  result?: string;
  detail?: string;
  artifact?: string;
  status?: "pending" | "ok" | "bad" | "neutral";
};

type RoundView = {
  round: number;
  title: string;
  accepted?: boolean;
  verdict: string;
  codePath?: string;
  steps: DecisionStep[];
};

const eventTitles: Record<string, string> = {
  run_start: "任务启动",
  round_start: "回合展开",
  research_decision: "选择调研",
  tool_call: "工具返回",
  skill_selection: "加载 Skill",
  generation: "生成求解器",
  validation: "静态验证",
  evaluation: "本地评测",
  llm_judge: "LLM Judge",
  accepted: "采纳策略",
  skill_write: "扩展 Skill",
  round_summary: "本轮总结",
  project_tool_decision: "项目工具决策",
  termination: "触发终止",
  run_end: "任务结束",
  web_process: "进程状态"
};

const kindLabel: Record<DecisionStep["kind"], string> = {
  context: "上下文",
  decision: "决策",
  tool: "工具",
  skill: "Skill",
  code: "改代码",
  check: "验证",
  eval: "评测",
  reflection: "反思"
};

function metricLine(metrics: any) {
  if (!metrics?.ok) return metrics?.error ? `失败：${metrics.error}` : "等待评估";
  const score = Number(metrics.avg_det_score).toFixed(2);
  const cov = Number(metrics.min_det_cov).toFixed(3);
  const time = Number(metrics.avg_time_ms).toFixed(1);
  return `DetScore ${score} / 覆盖 ${cov} / ${time}ms`;
}

function compactRows(metrics: any) {
  const rows = Array.isArray(metrics?.rows) ? metrics.rows : [];
  return rows.slice(0, 7).map((row: any) => {
    const cov = Number(row.det_cov).toFixed(3);
    const score = Number(row.det_score).toFixed(1);
    return `${row.preset}: cov ${cov}, score ${score}`;
  }).join("\n");
}

function stringifyParams(params?: DecisionStep["params"]) {
  if (!params) return [];
  return Object.entries(params)
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `${key}: ${String(value)}`);
}

function stepIcon(kind: DecisionStep["kind"], status?: DecisionStep["status"]) {
  if (status === "ok") return <CheckCircle2 size={16} />;
  if (status === "bad") return <XCircle size={16} />;
  if (kind === "tool") return <Search size={16} />;
  if (kind === "skill") return <Sparkles size={16} />;
  if (kind === "code") return <Code2 size={16} />;
  if (kind === "check") return <ShieldCheck size={16} />;
  if (kind === "eval") return <FlaskConical size={16} />;
  if (kind === "reflection") return <FileText size={16} />;
  return <Brain size={16} />;
}

function summarizeEvents(events: AgentEvent[]): RoundView[] {
  const rounds = new Map<number, RoundView>();
  const ensure = (round: number) => {
    if (!rounds.has(round)) {
      rounds.set(round, {
        round,
        title: `第 ${round} 轮`,
        verdict: "等待闭环",
        steps: []
      });
    }
    return rounds.get(round)!;
  };
  const push = (round: number, step: Omit<DecisionStep, "id">) => {
    const view = ensure(round);
    view.steps.push({ ...step, id: `${round}-${view.steps.length + 1}-${step.kind}` });
  };

  for (const event of events) {
    const payload = event.payload ?? {};
    const round = Number(payload.round ?? 0);
    if (!round) continue;
    const view = ensure(round);

    if (event.event_type === "round_start") {
      push(round, {
        kind: "context",
        title: "读取上一轮状态",
        subtitle: `当前 best：${payload.best_name ?? "unknown"}`,
        reason: `连续未采纳轮数：${payload.stalled_rounds ?? 0}`,
        result: metricLine(payload.best_metrics),
        status: "neutral"
      });
    }

    if (event.event_type === "research_decision") {
      const call = payload.call ?? {};
      const skipped = call.tool === "generate_solver";
      push(round, {
        kind: "decision",
        title: skipped ? "决定跳过调研" : "决定调用调研工具",
        subtitle: skipped ? "直接进入 solver 生成" : `工具：${call.tool ?? "unknown"}`,
        reason: call.reason ?? payload.decision?.purpose,
        purpose: skipped ? "节省本轮搜索时间，直接利用已有经验" : "寻找可转化为纯 Python solver 的突破线索",
        params: { query: call.query, url: call.url },
        result: `累计 token：${payload.tokens_used ?? 0}`,
        status: "neutral"
      });
    }

    if (event.event_type === "project_tool_decision") {
      const call = payload.call ?? {};
      push(round, {
        kind: "decision",
        title: "决定调用项目工具",
        subtitle: `工具：${call.tool ?? "unknown"}`,
        reason: payload.reason ?? call.reason,
        purpose: payload.purpose ?? call.purpose,
        params: {
          step: payload.step,
          ...(call.params ?? {})
        },
        result: `本次工具决策 token：${payload.tokens_used_delta ?? 0}`,
        status: "neutral"
      });
    }

    if (event.event_type === "tool_call") {
      push(round, {
        kind: "tool",
        title: `${payload.tool ?? "tool"} 返回结果`,
        subtitle: payload.error ? "工具调用失败" : "工具调用完成",
        reason: payload.reason,
        purpose: payload.purpose,
        params: { query: payload.query, url: payload.url, ...(payload.params ?? {}) },
        result: payload.error ? String(payload.error) : String(payload.summary_preview ?? "无摘要"),
        detail: Array.isArray(payload.result_keys) ? `返回字段：${payload.result_keys.join(", ")}` : undefined,
        status: payload.error ? "bad" : "ok"
      });
    }

    if (event.event_type === "skill_selection") {
      const selected = Array.isArray(payload.selected_details) ? payload.selected_details : [];
      const selectedText = selected.length
        ? selected.map((skill: any) => `${skill.id}：${skill.description || skill.name}`).join("\n")
        : "未加载 skill";
      push(round, {
        kind: "skill",
        title: "选择并加载 Skill",
        subtitle: Array.isArray(payload.selected) && payload.selected.length ? payload.selected.join(", ") : "无",
        reason: payload.reason,
        purpose: payload.purpose,
        result: selectedText,
        status: selected.length ? "ok" : "neutral"
      });
    }

    if (event.event_type === "generation") {
      const summary = payload.code_summary ?? {};
      push(round, {
        kind: "code",
        title: "生成 solver 候选",
        subtitle: payload.name ?? summary.strategy ?? "candidate",
        reason: summary.rationale,
        purpose: payload.purpose,
        params: {
          direction: summary.direction,
          chars: payload.code_chars,
          tokens_delta: payload.tokens_delta
        },
        result: summary.strategy ? `策略：${summary.strategy}` : "已生成候选代码",
        status: "neutral"
      });
    }

    if (event.event_type === "validation") {
      view.codePath = payload.validated_path ?? payload.candidate_path ?? view.codePath;
      push(round, {
        kind: "check",
        title: "验证接口与语法",
        subtitle: payload.ok ? "solve 接口可执行" : "验证失败",
        result: payload.ok ? "语法、入口函数和返回格式通过第一层检查" : String(payload.error ?? "未知错误"),
        artifact: payload.validated_path ?? payload.candidate_path,
        status: payload.ok ? "ok" : "bad"
      });
    }

    if (event.event_type === "evaluation") {
      push(round, {
        kind: "eval",
        title: "运行本地校准评测",
        subtitle: payload.name ?? "candidate",
        result: payload.metrics_text ?? metricLine(payload.metrics),
        detail: compactRows(payload.metrics),
        status: payload.metrics?.all_full_cov ? "ok" : "bad"
      });
    }

    if (event.event_type === "llm_judge") {
      const judge = payload.judge ?? {};
      push(round, {
        kind: "eval",
        title: "LLM-as-judge 补充判断",
        subtitle: judge.preference ? `偏好：${judge.preference}` : "语义评估",
        reason: payload.purpose,
        params: {
          primary_score: judge.primary_score,
          hard_pass: judge.hard_pass,
          tokens_delta: payload.tokens_delta
        },
        result: judge.summary ?? judge.raw_preview ?? "已完成 LLM-as-judge 调用",
        detail: Array.isArray(judge.risks) ? `风险：${judge.risks.join("；")}` : undefined,
        status: judge.ok === false || judge.hard_pass === false ? "bad" : "ok"
      });
    }

    if (event.event_type === "accepted") {
      push(round, {
        kind: "reflection",
        title: "采纳为新 best",
        subtitle: payload.name ?? "accepted solver",
        result: payload.reason ?? "已进入策略库",
        artifact: payload.snapshot_py,
        status: "ok"
      });
    }

    if (event.event_type === "skill_write") {
      push(round, {
        kind: "skill",
        title: "写入新 Skill",
        subtitle: payload.ok ? String(payload.id ?? payload.name ?? "new skill") : "写入失败",
        result: payload.ok ? String(payload.description ?? payload.path ?? "") : String(payload.error ?? ""),
        artifact: payload.path,
        status: payload.ok ? "ok" : "bad"
      });
    }

    if (event.event_type === "round_summary") {
      push(round, {
        kind: "reflection",
        title: "本轮小总结",
        subtitle: payload.accepted ? "本轮被采纳" : "本轮未采纳",
        reason: payload.reason,
        result: payload.summary,
        status: payload.accepted ? "ok" : "neutral"
      });
    }

    if (event.event_type === "round_end") {
      view.accepted = Boolean(payload.accepted);
      view.verdict = payload.accepted ? `采纳：${payload.reason ?? ""}` : `未采纳：${payload.reason ?? ""}`;
      view.codePath = payload.validated_path ?? view.codePath;
      push(round, {
        kind: "reflection",
        title: "本轮反思与经验",
        subtitle: payload.accepted ? "成为下一轮基线" : "作为失败经验进入下一轮上下文",
        reason: payload.reason,
        result: payload.accepted
          ? "后续轮次会围绕新 best 继续小步搜索。"
          : "下一轮会把该失败原因、指标和候选名称写回 prompt，避免重复同类退化。",
        artifact: payload.validated_path,
        status: payload.accepted ? "ok" : "bad"
      });
    }
  }

  return [...rounds.values()].sort((a, b) => a.round - b.round);
}

function latestCodePath(events: AgentEvent[]) {
  for (const event of [...events].reverse()) {
    const payload = event.payload ?? {};
    if (payload.validated_path) return String(payload.validated_path);
    if (payload.candidate_path) return String(payload.candidate_path);
  }
  return "solver.py";
}

export default function App() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [skills, setSkills] = useState<SkillItem[]>([]);
  const [tools, setTools] = useState<ToolItem[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [activeRun, setActiveRun] = useState<string>("");
  const [authReady, setAuthReady] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authToken, setAuthToken] = useState(() => localStorage.getItem("loopforge_auth_token") ?? "");
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("");
  const [authError, setAuthError] = useState("");
  const [baselineCode, setBaselineCode] = useState("");
  const [currentCode, setCurrentCode] = useState("");
  const [selectedSkills, setSelectedSkills] = useState<string[]>([
    "project_evidence_loop",
    "safe_project_tools",
    "evaluator_contract_adapter"
  ]);
  const [form, setForm] = useState({
    goal: "保持线上 10/10 完成率，优先寻找不会退化成 cost_first 的小幅改进。",
    maxRounds: 3,
    maxSeconds: 900,
    maxTokens: 12000,
    evalSeeds: 1,
    sandboxTimeout: 5,
    researchOnStall: 0,
    researchEvery: 0,
    maxSkills: 4,
    skillWriteOnStall: 3,
    live: false,
    initialResearch: true,
    allowSkillWrite: false,
    exportBest: false,
    projectTools: true,
    projectToolSteps: 6
  });
  const [contractInput, setContractInput] = useState({
    datasetSample: "",
    datasetFile: null as null | Record<string, any>,
    evaluatorScript: "",
    rubric: ""
  });
  const [contractDraft, setContractDraft] = useState<EvaluationContract | null>(null);
  const [contractJson, setContractJson] = useState("");
  const [contractDiagnostics, setContractDiagnostics] = useState<string[]>([]);
  const [contractValidation, setContractValidation] = useState<{ ok?: boolean; errors?: string[]; warnings?: string[] } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const rounds = useMemo(() => summarizeEvents(events), [events]);
  const lastEvent = events[events.length - 1];
  const runStatus = runs.find((run) => run.id === activeRun)?.status ?? (activeRun ? "running" : "idle");
  const runStart = events.find((event) => event.event_type === "run_start");
  const runEnd = [...events].reverse().find((event) => event.event_type === "run_end");
  const bestMetrics = runEnd?.payload?.best_metrics ?? runStart?.payload?.best_metrics;
  const unlocked = !authRequired || Boolean(authToken);

  const clearAuth = useCallback(() => {
    localStorage.removeItem("loopforge_auth_token");
    setAuthToken("");
  }, []);

  const authedFetch = useCallback(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const headers = new Headers(init.headers);
    if (authToken) headers.set("Authorization", `Bearer ${authToken}`);
    const res = await fetch(input, { ...init, headers });
    if (res.status === 401) {
      clearAuth();
      throw new Error("需要登录");
    }
    return res;
  }, [authToken, clearAuth]);

  const flowNodes: Node[] = useMemo(() => {
    const nodes: Node[] = [{
      id: "start",
      position: { x: 30, y: 40 },
      data: { label: "Goal" },
      type: "input",
      className: "flow-node start"
    }];
    rounds.forEach((round, index) => {
      nodes.push({
        id: `round-${round.round}`,
        position: { x: 250 + index * 230, y: 40 + (index % 2) * 90 },
        data: { label: `R${round.round} ${round.steps.length} steps` },
        className: `flow-node ${round.accepted ? "accepted" : "tested"}`
      });
    });
    nodes.push({
      id: "best",
      position: { x: 250 + Math.max(rounds.length, 1) * 230, y: 40 },
      data: { label: bestMetrics ? metricLine(bestMetrics) : "Best solver" },
      type: "output",
      className: "flow-node best"
    });
    return nodes;
  }, [rounds, bestMetrics]);

  const flowEdges: Edge[] = useMemo(() => {
    const ids = ["start", ...rounds.map((round) => `round-${round.round}`), "best"];
    return ids.slice(0, -1).map((id, index) => ({
      id: `${id}-${ids[index + 1]}`,
      source: id,
      target: ids[index + 1],
      markerEnd: { type: MarkerType.ArrowClosed },
      animated: index >= ids.length - 3
    }));
  }, [rounds]);

  const refreshRuns = useCallback(async () => {
    if (!unlocked) return;
    const res = await authedFetch("/api/runs");
    const data = await res.json();
    setRuns(data.runs ?? []);
  }, [authedFetch, unlocked]);

  const loadFile = useCallback(async (path: string, setter: (content: string) => void) => {
    if (!unlocked) return;
    const res = await authedFetch(`/api/file?path=${encodeURIComponent(path)}`);
    const data = await res.json();
    setter(data.content ?? "");
  }, [authedFetch, unlocked]);

  useEffect(() => {
    fetch("/api/auth/status")
      .then((res) => res.json())
      .then((data) => {
        setAuthRequired(Boolean(data.authRequired));
        setAuthReady(true);
      })
      .catch(() => {
        setAuthRequired(true);
        setAuthReady(true);
      });
  }, []);

  useEffect(() => {
    if (!authReady || !unlocked) return;
    refreshRuns();
    authedFetch("/api/skills").then((res) => res.json()).then((data) => setSkills(data.skills ?? []));
    authedFetch("/api/tools").then((res) => res.json()).then((data) => setTools(data.tools ?? []));
    loadFile("solver.py", setBaselineCode);
  }, [authReady, authedFetch, loadFile, refreshRuns, unlocked]);

  useEffect(() => {
    if (!activeRun) return;
    wsRef.current?.close();
    setEvents([]);
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const qs = authToken ? `?token=${encodeURIComponent(authToken)}` : "";
    const ws = new WebSocket(`${protocol}://${location.host}/api/runs/${activeRun}/events${qs}`);
    wsRef.current = ws;
    ws.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        setEvents((prev) => [...prev, event]);
      } catch {
        // WebSocket only transports JSONL event objects.
      }
    };
    return () => ws.close();
  }, [activeRun, authToken]);

  useEffect(() => {
    loadFile(latestCodePath(events), setCurrentCode);
  }, [events, loadFile]);

  const startRun = async () => {
    const activeContract = parseContractJson() ?? contractDraft;
    const res = await authedFetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...form, skills: selectedSkills, contract: activeContract })
    });
    const data = await res.json();
    setActiveRun(data.id);
    await refreshRuns();
  };

  const stopRun = async () => {
    if (!activeRun) return;
    await authedFetch(`/api/runs/${activeRun}/stop`, { method: "POST" });
    await refreshRuns();
  };

  const updateForm = (key: keyof typeof form, value: string | number | boolean) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const updateContractInput = (key: "datasetSample" | "evaluatorScript" | "rubric", value: string) => {
    setContractInput((prev) => ({ ...prev, [key]: value }));
  };

  const uploadDataset = async (file: File | null) => {
    if (!file) return;
    const data = new FormData();
    data.append("dataset", file);
    const res = await authedFetch("/api/contracts/upload-dataset", {
      method: "POST",
      body: data
    });
    const payload = await res.json();
    if (!payload.ok) {
      setContractDiagnostics([payload.error ?? "评估集上传失败"]);
      return;
    }
    setContractInput((prev) => ({
      ...prev,
      datasetSample: payload.text ?? "",
      datasetFile: payload.file ?? null
    }));
    const warnings = Array.isArray(payload.file?.warnings) ? payload.file.warnings : [];
    setContractDiagnostics([
      `已上传 ${payload.file?.name}，解析类型：${payload.file?.extracted_kind}，预览字符：${payload.preview_chars}`,
      ...warnings
    ]);
    setContractValidation(null);
  };

  const parseContractJson = () => {
    if (!contractJson.trim()) return null;
    try {
      return JSON.parse(contractJson) as EvaluationContract;
    } catch {
      return null;
    }
  };

  const analyzeContract = async () => {
    const res = await authedFetch("/api/contracts/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        goal: form.goal,
        datasetSample: contractInput.datasetSample,
        datasetFile: contractInput.datasetFile,
        evaluatorScript: contractInput.evaluatorScript,
        rubric: contractInput.rubric
      })
    });
    const data = await res.json();
    setContractDraft(data.contract);
    setContractJson(JSON.stringify(data.contract, null, 2));
    setContractDiagnostics(data.diagnostics ?? []);
    setContractValidation(null);
  };

  const validateContract = async () => {
    const parsed = parseContractJson();
    if (!parsed) {
      setContractValidation({ ok: false, errors: ["Contract JSON 无法解析"], warnings: [] });
      return;
    }
    const res = await authedFetch("/api/contracts/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ contract: parsed })
    });
    const data = await res.json();
    setContractValidation(data);
    if (data.ok) {
      setContractDraft(parsed);
      await authedFetch("/api/contracts/save", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contract: parsed })
      });
    }
  };

  const login = async () => {
    setAuthError("");
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });
    const data = await res.json();
    if (!res.ok || !data.token) {
      setAuthError(data.error ?? "登录失败");
      return;
    }
    localStorage.setItem("loopforge_auth_token", data.token);
    setAuthToken(data.token);
    setPassword("");
  };

  const toggleSkill = (id: string) => {
    setSelectedSkills((prev) => prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]);
  };

  const skillGroups = useMemo(() => {
    const labels: Record<string, string> = {
      generic: "通用 Skill",
      project: "项目专用",
      system: "自扩展"
    };
    const grouped = new Map<string, SkillItem[]>();
    for (const skill of skills) {
      const scope = skill.scope || "generic";
      grouped.set(scope, [...(grouped.get(scope) ?? []), skill]);
    }
    return [...grouped.entries()].sort(([a], [b]) => {
      const order: Record<string, number> = { generic: 0, project: 1, system: 2 };
      return (order[a] ?? 9) - (order[b] ?? 9);
    }).map(([scope, items]) => ({ scope, label: labels[scope] ?? scope, items }));
  }, [skills]);

  const toolGroups = useMemo(() => {
    const grouped = new Map<string, ToolItem[]>();
    for (const tool of tools) {
      grouped.set(tool.category, [...(grouped.get(tool.category) ?? []), tool]);
    }
    return [...grouped.entries()].map(([category, items]) => ({ category, items }));
  }, [tools]);

  return (
    <div className="shell">
      {authReady && !unlocked && (
        <div className="auth-screen">
          <div className="auth-card">
            <img src="/loopforge-logo.svg" alt="LoopForge" />
            <div>
              <span className="eyebrow">LoopForge Access</span>
              <h1>进入自迭代驾驶舱</h1>
              <p>公网模式已启用账号密码。登录后才能读取项目文件、启动 agent、订阅运行事件。</p>
            </div>
            <div className="auth-hints">
              {/*<p><strong>账号来源</strong>：在服务器的 <code>web/server.config.json</code> 中配置 <code>auth.username</code> 和 <code>auth.password</code>。</p>*/}
              {/*<p><strong>部署检查</strong>：公网只开放 <code>5173</code>，后端 API <code>8787</code> 默认保持本机访问。</p>*/}
              <p><strong>登录说明</strong>：登录后可以启动 Agent Loop、读取项目文件和查看运行事件。默认admin账户，密码admin</p>
            </div>
            <label className="field">
              <span>账号</span>
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
              />
            </label>
            <label className="field">
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void login();
                }}
                autoFocus
              />
            </label>
            {authError && <p className="auth-error">{authError}</p>}
            <button className="primary" onClick={login}><ShieldCheck size={18} /> 登录</button>
          </div>
        </div>
      )}
      <header className="topbar">
        <div>
          <div className="brand-line">
            <img src="/loopforge-logo.svg" alt="LoopForge" />
            <div>
              <div className="eyebrow"><Activity size={16} /> AutoResearch Mission Control</div>
              <h1>LoopForge</h1>
            </div>
          </div>
        </div>
        <div className="status-strip">
          <span>{runStatus}</span>
          <strong>{activeRun || "no active run"}</strong>
          <button className="icon-btn" onClick={refreshRuns} title="刷新运行列表"><RefreshCcw size={18} /></button>
          {authRequired && <button className="icon-btn" onClick={clearAuth} title="退出登录"><ShieldCheck size={18} /></button>}
        </div>
      </header>

      <main className="workspace">
        <aside className="launch-panel">
          <div className="guide">
            <Target size={20} />
            <p>设定目标和边界后启动。每一轮会展开成决策链：读状态、选工具、看返回、加载 skill、改 solver、评测、反思。</p>
          </div>

          <label className="field">
            <span>Goal</span>
            <textarea value={form.goal} onChange={(e) => updateForm("goal", e.target.value)} />
          </label>

          <section className="contract-panel">
            <div className="contract-head">
              <div>
                <span className="eyebrow"><SlidersHorizontal size={15} /> Evaluation Contract</span>
                <h2>评测契约</h2>
              </div>
              <span className={contractValidation?.ok ? "contract-pill ok" : "contract-pill"}>
                {contractValidation?.ok ? "已验证" : "草案"}
              </span>
            </div>

            <div className="upload-zone">
              <label className="upload-button">
                <FileUp size={16} />
                <span>上传评估集</span>
                <input
                  type="file"
                  accept=".txt,.md,.json,.jsonl,.csv,.tsv,.xlsx,.xls,.xlsm,.docx,.doc"
                  onChange={(e) => uploadDataset(e.target.files?.[0] ?? null)}
                />
              </label>
              <div className="upload-meta">
                <strong>{contractInput.datasetFile?.name ?? "未上传文件"}</strong>
                <span>支持 txt / md / json / csv / tsv / Excel / docx；旧版 .doc 会提示转换。</span>
              </div>
            </div>

            <label className="field compact">
              <span>评估集文本预览</span>
              <textarea
                value={contractInput.datasetSample}
                onChange={(e) => updateContractInput("datasetSample", e.target.value)}
                placeholder="上传后这里会显示抽取出的文本。没有评估集可留空，系统会走 LLM-as-judge 草案。"
              />
            </label>
            <label className="field compact">
              <span>可选评测脚本</span>
              <textarea
                value={contractInput.evaluatorScript}
                onChange={(e) => updateContractInput("evaluatorScript", e.target.value)}
                placeholder="粘贴用户已有 judge/eval 脚本；不要求函数名符合规范，后台只做检查和适配草案。"
              />
            </label>
            <label className="field compact">
              <span>Rubric / 好坏倾向</span>
              <textarea
                value={contractInput.rubric}
                onChange={(e) => updateContractInput("rubric", e.target.value)}
                placeholder="描述什么是好结果、硬约束、是否越低越好；LLM judge 会优先使用它。"
              />
            </label>

            <div className="contract-actions">
              <button className="secondary" onClick={analyzeContract}><Brain size={16} /> 生成草案</button>
              <button className="secondary" onClick={validateContract}><ClipboardCheck size={16} /> 验证保存</button>
            </div>

            {contractDiagnostics.length > 0 && (
              <div className="contract-notes">
                {contractDiagnostics.map((item) => <p key={item}>{item}</p>)}
              </div>
            )}

            <label className="field compact">
              <span>可手改 JSON</span>
              <textarea
                className="contract-json"
                value={contractJson}
                onChange={(e) => setContractJson(e.target.value)}
                placeholder="点击生成草案后，这里会出现 evaluation_contract.json。"
              />
            </label>

            {contractValidation && (
              <div className={contractValidation.ok ? "contract-validation ok" : "contract-validation bad"}>
                {(contractValidation.errors ?? []).map((item) => <p key={item}>{item}</p>)}
                {(contractValidation.warnings ?? []).map((item) => <p key={item}>警告：{item}</p>)}
                {contractValidation.ok && <p>契约结构通过，启动 run 时会写入本次运行目录。</p>}
              </div>
            )}
          </section>

          <div className="grid-fields">
            <label className="field"><span>轮数</span><input type="number" value={form.maxRounds} onChange={(e) => updateForm("maxRounds", Number(e.target.value))} /></label>
            <label className="field"><span>秒</span><input type="number" value={form.maxSeconds} onChange={(e) => updateForm("maxSeconds", Number(e.target.value))} /></label>
            <label className="field"><span>Token</span><input type="number" value={form.maxTokens} onChange={(e) => updateForm("maxTokens", Number(e.target.value))} /></label>
            <label className="field"><span>Seeds</span><input type="number" value={form.evalSeeds} onChange={(e) => updateForm("evalSeeds", Number(e.target.value))} /></label>
          </div>

          <div className="grid-fields">
            <label className="field"><span>单次超时</span><input type="number" value={form.sandboxTimeout} onChange={(e) => updateForm("sandboxTimeout", Number(e.target.value))} /></label>
            <label className="field"><span>停滞后调研</span><input type="number" value={form.researchOnStall} onChange={(e) => updateForm("researchOnStall", Number(e.target.value))} /></label>
            <label className="field"><span>定期调研</span><input type="number" value={form.researchEvery} onChange={(e) => updateForm("researchEvery", Number(e.target.value))} /></label>
            <label className="field"><span>每轮工具动作</span><input type="number" value={form.projectToolSteps} onChange={(e) => updateForm("projectToolSteps", Number(e.target.value))} /></label>
          </div>

          <div className="control-notes">
            <p><strong>真实 LLM</strong> 开启后会调用配置的模型；关闭时走 dry-run/模板链路。</p>
            <p><strong>每轮工具动作</strong> 是单轮最多执行几次项目工具，不是工具数量；<strong>停滞后调研</strong> 和 <strong>定期调研</strong> 填 0 即关闭触发。</p>
          </div>

          <div className="switches">
            <label><input type="checkbox" checked={form.live} onChange={(e) => updateForm("live", e.target.checked)} /> 真实 LLM</label>
            <label><input type="checkbox" checked={form.initialResearch} onChange={(e) => updateForm("initialResearch", e.target.checked)} /> 首轮调研</label>
            <label><input type="checkbox" checked={form.projectTools} onChange={(e) => updateForm("projectTools", e.target.checked)} /> 项目工具</label>
            <label><input type="checkbox" checked={form.allowSkillWrite} onChange={(e) => updateForm("allowSkillWrite", e.target.checked)} /> 写入 skill</label>
            <label className="danger"><input type="checkbox" checked={form.exportBest} onChange={(e) => updateForm("exportBest", e.target.checked)} /> 覆盖 solver.py</label>
          </div>

          <section className="tool-catalog">
            <div className="tool-catalog-head">
              <span>当前可用工具</span>
              <small>{tools.length}</small>
            </div>
            {toolGroups.map((group) => (
              <div className="tool-group" key={group.category}>
                <div className="tool-group-title">{group.category}</div>
                <div className="tool-list">
                  {group.items.map((tool) => (
                    <div className="tool-item" key={tool.id} title={`${tool.description}\n${tool.safety ?? ""}`}>
                      <Wrench size={13} />
                      <div>
                        <strong>{tool.name}</strong>
                        <span>{tool.id}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </section>

          <div className="skill-groups">
            {skillGroups.map((group) => (
              <section className="skill-group" key={group.scope}>
                <div className="skill-group-head">
                  <span>{group.label}</span>
                  <small>{group.items.length}</small>
                </div>
                <div className="skill-row">
                  {group.items.map((skill) => (
                    <button
                      key={skill.id}
                      className={selectedSkills.includes(skill.id) ? `skill active ${skill.scope ?? "generic"}` : `skill ${skill.scope ?? "generic"}`}
                      onClick={() => toggleSkill(skill.id)}
                      title={`${skill.name ?? skill.id}\n${skill.description}`}
                    >
                      <Sparkles size={14} />
                      <span>{skill.name ?? skill.id}</span>
                      <small>{skill.id}</small>
                    </button>
                  ))}
                </div>
              </section>
            ))}
          </div>

          <div className="actions">
            <button className="primary" onClick={startRun}><Play size={18} /> 启动</button>
            <button className="secondary" onClick={stopRun} disabled={!activeRun}><PauseCircle size={18} /> 停止</button>
          </div>

          <div className="run-list">
            {runs.slice(0, 6).map((run) => (
              <button key={run.id} className={run.id === activeRun ? "run active" : "run"} onClick={() => setActiveRun(run.id)}>
                <span>{run.id}</span>
                <small>{run.status}</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="mission">
          <div className="metric-band">
            <div><Beaker size={18} /><span>Best</span><strong>{bestMetrics ? metricLine(bestMetrics) : "等待基线"}</strong></div>
            <div><GitBranch size={18} /><span>Rounds</span><strong>{rounds.length}</strong></div>
            <div><Brain size={18} /><span>Last</span><strong>{lastEvent ? eventTitles[lastEvent.event_type] ?? lastEvent.event_type : "idle"}</strong></div>
          </div>

          <div className="flow-wrap">
            <ReactFlow nodes={flowNodes} edges={flowEdges} fitView minZoom={0.35}>
              <Background gap={18} size={1} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </div>

          <div className="round-stream">
            <AnimatePresence>
              {rounds.map((round) => (
                <motion.article
                  key={round.round}
                  className={`round-card ${round.accepted ? "accepted" : ""}`}
                  initial={{ opacity: 0, y: 18 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  <div className="round-head">
                    <div>
                      <span>{round.title}</span>
                      <small>{round.verdict}</small>
                    </div>
                    <strong>{round.steps.length} 个动作</strong>
                  </div>

                  <div className="decision-chain">
                    {round.steps.map((step, index) => (
                      <section key={step.id} className={`decision-step ${step.status ?? "neutral"}`}>
                        <div className="step-rail">
                          <span>{index + 1}</span>
                          {stepIcon(step.kind, step.status)}
                        </div>
                        <div className="step-body">
                          <div className="step-title">
                            <span>{kindLabel[step.kind]}</span>
                            <h3>{step.title}</h3>
                          </div>
                          <p className="step-subtitle">{step.subtitle}</p>
                          {(step.reason || step.purpose) && (
                            <div className="step-explain">
                              {step.reason && <p><b>理由</b>{step.reason}</p>}
                              {step.purpose && <p><b>目的</b>{step.purpose}</p>}
                            </div>
                          )}
                          {stringifyParams(step.params).length > 0 && (
                            <div className="param-row">
                              {stringifyParams(step.params).map((item) => <span key={item}>{item}</span>)}
                            </div>
                          )}
                          {step.result && <pre className="step-result">{step.result}</pre>}
                          {step.detail && <pre className="step-detail">{step.detail}</pre>}
                          {step.artifact && <div className="artifact"><ListTree size={14} /> {step.artifact}</div>}
                        </div>
                      </section>
                    ))}
                  </div>
                </motion.article>
              ))}
            </AnimatePresence>
          </div>
        </section>

        <section className="code-studio">
          <div className="studio-head">
            <div>
              <span className="eyebrow"><Code2 size={16} /> Solver Diff</span>
              <h2>solver.py 演化</h2>
            </div>
            <span className="path-label">{latestCodePath(events)}</span>
          </div>
          <DiffEditor
            height="calc(100vh - 178px)"
            language="python"
            original={baselineCode}
            modified={currentCode || baselineCode}
            theme="vs-dark"
            options={{
              readOnly: true,
              renderSideBySide: true,
              minimap: { enabled: false },
              fontSize: 13,
              wordWrap: "on",
              scrollBeyondLastLine: false
            }}
          />
        </section>
      </main>
    </div>
  );
}
