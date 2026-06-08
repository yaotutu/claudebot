import type { ToolProgressEvent } from "@/lib/types";

/** Drop duplicate tool_call objects (same id or identical formatted trace). */
export function dedupeToolCallsForUi(calls: unknown): unknown[] {
  if (!Array.isArray(calls) || calls.length === 0) return [];
  const seen = new Set<string>();
  const out: unknown[] = [];
  for (const c of calls) {
    let key: string | null = null;
    if (c && typeof c === "object" && "id" in c) {
      const id = (c as { id?: unknown }).id;
      if (typeof id === "string" && id.length > 0) key = `id:${id}`;
    }
    if (key == null) {
      key = formatToolCallTrace(c) ?? "";
    }
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(c);
  }
  return out;
}

export function formatToolCallTrace(call: unknown): string | null {
  if (!call || typeof call !== "object") return null;
  const claudeTrace = formatClaudeCodeToolTrace(call);
  if (claudeTrace) return claudeTrace;
  const item = call as {
    name?: unknown;
    arguments?: unknown;
    function?: { name?: unknown; arguments?: unknown };
  };
  const name =
    typeof item.function?.name === "string"
      ? item.function.name
      : typeof item.name === "string"
        ? item.name
        : "";
  if (!name) return null;
  const args = item.function?.arguments ?? item.arguments;
  if (typeof args === "string" && args.trim()) return `${name}(${args})`;
  if (args && typeof args === "object") return `${name}(${JSON.stringify(args)})`;
  return `${name}()`;
}

function formatClaudeCodeToolTrace(call: object): string | null {
  const item = call as {
    activity?: unknown;
    name?: unknown;
    arguments?: unknown;
    result?: unknown;
    content?: unknown;
    function?: { name?: unknown; arguments?: unknown };
  };
  const rawName =
    typeof item.function?.name === "string"
      ? item.function.name
      : typeof item.name === "string"
        ? item.name
        : "";
  const args = parseMaybeJson(item.function?.arguments ?? item.arguments);
  const activity = activityRecord(item.activity) ?? activityRecord(args);
  const activityKind = typeof activity?.kind === "string" ? activity.kind : "";
  if (rawName === "claude_tool_start" || activityKind === "claude_tool_start") {
    const toolName = stringValue(activity?.toolName)
      || stringValue(activity?.tool_name)
      || stringValue((args as Record<string, unknown> | null)?.toolName)
      || "ClaudeTool";
    const input = activity?.input ?? activity?.toolInput ?? activity?.tool_input ?? {};
    return `${toolName}(${JSON.stringify(input && typeof input === "object" ? input : {})})`;
  }
  if (
    rawName === "claude_tool_result"
    || rawName === ""
    || activityKind === "claude_tool_result"
  ) {
    const result = item.result ?? item.content ?? activity?.content;
    if (result === undefined || result === null) return null;
    const content = resultContentPreview(result);
    return content ? `ClaudeResult(${JSON.stringify({ content })})` : "ClaudeResult()";
  }
  return null;
}

function activityRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  if (record.activity && typeof record.activity === "object" && !Array.isArray(record.activity)) {
    return record.activity as Record<string, unknown>;
  }
  return record;
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function parseMaybeJson(value: unknown): unknown {
  if (typeof value !== "string") return value;
  if (!value.trim()) return value;
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function resultContentPreview(value: unknown): string {
  const raw = typeof value === "string"
    ? value
    : value && typeof value === "object" && !Array.isArray(value)
      ? stringValue((value as Record<string, unknown>).content)
      : "";
  return raw.replace(/\s+/g, " ").trim().slice(0, 160);
}

const VALID_PHASES = new Set(["start", "end", "finish", "error"]);
const PHASE_RANK: Record<string, number> = { start: 1, end: 2, finish: 2, error: 3 };

export function normalizeToolProgressEvents(events: unknown): ToolProgressEvent[] {
  if (!Array.isArray(events)) return [];
  const out: ToolProgressEvent[] = [];
  for (const event of events) {
    if (!event || typeof event !== "object") continue;
    const record = event as ToolProgressEvent;
    const phase = record.phase;
    if (!(phase && typeof phase === "string" && VALID_PHASES.has(phase))) continue;
    const normalizedRecord = phase === "finish"
      ? { ...record, phase: "end" }
      : record;
    const name = typeof record.name === "string" ? record.name : "";
    const functionName =
      typeof (record as { function?: { name?: unknown } }).function?.name === "string"
        ? String((record as { function?: { name?: unknown } }).function?.name)
        : "";
    if (!name && !functionName && !formatToolCallTrace(record)) continue;
    out.push(normalizedRecord);
  }
  return out;
}

function toolEventKey(event: ToolProgressEvent): string {
  if (event.call_id) return `call:${event.call_id}`;
  return formatToolCallTrace(event) ?? JSON.stringify(event);
}

export function mergeToolProgressEvents(
  previous: ToolProgressEvent[] | undefined,
  incoming: ToolProgressEvent[],
): ToolProgressEvent[] {
  if (!previous?.length) return incoming;
  if (!incoming.length) return previous;
  const next = [...previous];
  const indexByKey = new Map(next.map((event, index) => [toolEventKey(event), index]));
  for (const event of incoming) {
    const key = toolEventKey(event);
    const existingIndex = indexByKey.get(key);
    if (existingIndex === undefined) {
      indexByKey.set(key, next.length);
      next.push(event);
      continue;
    }
    const existing = next[existingIndex];
    const incomingRank = PHASE_RANK[String(event.phase)] ?? 0;
    const existingRank = PHASE_RANK[String(existing.phase)] ?? 0;
    next[existingIndex] = incomingRank >= existingRank ? { ...existing, ...event } : existing;
  }
  return next;
}

export function toolTraceLinesFromEvents(events: unknown): string[] {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const event of normalizeToolProgressEvents(events)) {
    const callId = (event as { call_id?: unknown }).call_id;
    if (callId && typeof callId === "string") {
      if (seen.has(callId)) continue;
      seen.add(callId);
    }
    const line = formatToolCallTrace(event);
    if (!line) continue;
    lines.push(line);
  }
  return lines;
}

export function mergeUniqueToolTraceLines(
  previousTraces: string[],
  lines: string[],
): { traces: string[]; added: boolean } {
  const seen = new Set(previousTraces);
  const traces = [...previousTraces];
  let added = false;
  for (const line of lines) {
    if (seen.has(line)) continue;
    seen.add(line);
    traces.push(line);
    added = true;
  }
  return { traces, added };
}
