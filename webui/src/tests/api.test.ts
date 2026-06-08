import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  deleteSession,
  fetchClaudeCodeHealth,
  fetchClaudeCodeSettings,
  fetchFilePreview,
  fetchSessionAutomations,
  fetchSettingsUsage,
  fetchSidebarState,
  fetchSkillDetail,
  fetchSkills,
  fetchWebuiThread,
  fetchWorkspaces,
  listSessions,
  listSlashCommands,
  updateClaudeCodeSettings,
  updateSidebarState,
  updateNetworkSafetySettings,
  updateSettings,
} from "@/lib/api";

describe("webui API helpers", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ deleted: true, key: "websocket:chat-1", messages: [] }),
      }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("percent-encodes websocket keys when fetching webui-thread snapshot", async () => {
    await fetchWebuiThread("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/webui-thread",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
        credentials: "same-origin",
      }),
    );
  });

  it("percent-encodes websocket keys and paths when fetching file previews", async () => {
    await fetchFilePreview("tok", "websocket:chat-1", "/tmp/project/hook.py:12");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/file-preview?path=%2Ftmp%2Fproject%2Fhook.py%3A12",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
        credentials: "same-origin",
      }),
    );
  });

  it("percent-encodes websocket keys when fetching session automations", async () => {
    await fetchSessionAutomations("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/automations",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("fetches the WebUI skill summary", async () => {
    await fetchSkills("tok");

    expect(fetch).toHaveBeenCalledWith(
      "/api/webui/skills",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("percent-encodes skill names when fetching skill details", async () => {
    await fetchSkillDetail("tok", "current web");

    expect(fetch).toHaveBeenCalledWith(
      "/api/webui/skills/current%20web",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("percent-encodes websocket keys when deleting a session", async () => {
    await deleteSession("tok", "websocket:chat-1");

    expect(fetch).toHaveBeenCalledWith(
      "/api/sessions/websocket%3Achat-1/delete",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes settings updates as a narrow query string", async () => {
    await updateSettings("tok", {
      timezone: "Asia/Shanghai",
      botName: "claudebot",
      botIcon: "nb",
      toolHintMaxLength: 120,
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/update?timezone=Asia%2FShanghai&bot_name=claudebot&bot_icon=nb&tool_hint_max_length=120",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("fetches token usage through the lightweight settings endpoint", async () => {
    await fetchSettingsUsage("tok");

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/usage",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("serializes claude code settings helpers", async () => {
    await fetchClaudeCodeSettings("tok");
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/settings/claude-code",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );

    await fetchClaudeCodeHealth("tok");
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/settings/claude-code/health",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );

    await updateClaudeCodeSettings("tok", {
      baseUrl: "http://127.0.0.1:20128/v1",
      apiKey: "token",
      model: "glm-cn/glm-5.1",
      permissionMode: "bypassPermissions",
      enableGatewayModelDiscovery: true,
    });

    expect(fetch).toHaveBeenLastCalledWith(
      "/api/settings/claude-code/update",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer tok",
          "Content-Type": "application/json",
        }),
        body: JSON.stringify({
          baseUrl: "http://127.0.0.1:20128/v1",
          apiKey: "token",
          model: "glm-cn/glm-5.1",
          permissionMode: "bypassPermissions",
          enableGatewayModelDiscovery: true,
        }),
      }),
    );
  });

  it("reports HTML API fallbacks as gateway mismatch errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        headers: new Headers({ "content-type": "text/html; charset=utf-8" }),
        text: async () => "<!doctype html><html></html>",
      }),
    );

    await expect(fetchClaudeCodeSettings("tok")).rejects.toMatchObject({
      status: 200,
      message: "Gateway returned WebUI HTML instead of JSON. Restart claudebot gateway and try again.",
    });
  });

  it("surfaces API error response bodies", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        text: async () => "npm error ENOTEMPTY",
      }),
    );

    await expect(
      updateNetworkSafetySettings("tok", {
        webuiAllowLocalServiceAccess: false,
        webuiDefaultAccessMode: "default",
      }),
    ).rejects.toMatchObject({
      status: 500,
      message: "npm error ENOTEMPTY",
    });
  });

  it("times out when an API request never responds", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => {})));

    const pending = expect(listSessions("tok")).rejects.toThrow(
      "Request timed out after 20000ms",
    );
    await vi.advanceTimersByTimeAsync(20_000);

    await pending;
  });

  it("serializes network safety settings updates", async () => {
    await updateNetworkSafetySettings("tok", {
      webuiAllowLocalServiceAccess: false,
      webuiDefaultAccessMode: "full",
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=full",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("reads and writes persisted sidebar state", async () => {
    const state = {
      schema_version: 1,
      pinned_keys: ["websocket:chat-1"],
      archived_keys: ["websocket:old"],
      title_overrides: { "websocket:chat-1": "Release" },
      project_name_overrides: { "/Users/me/claudebot": "Core" },
      tags_by_key: {},
      collapsed_groups: {},
      view: {
        density: "compact" as const,
        show_previews: false,
        show_timestamps: false,
        show_archived: true,
        sort: "updated_desc" as const,
      },
      updated_at: null,
    };
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => state,
    } as Response);

    await expect(fetchSidebarState("tok")).resolves.toEqual(state);
    expect(fetch).toHaveBeenCalledWith(
      "/api/webui/sidebar-state",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );

    await updateSidebarState("tok", state);
    const [url, init] = vi.mocked(fetch).mock.calls.at(-1)!;
    expect(String(url).startsWith("/api/webui/sidebar-state/update?")).toBe(true);
    expect(init).toEqual(expect.objectContaining({
      headers: { Authorization: "Bearer tok" },
    }));
    const encodedState = new URLSearchParams(String(url).split("?", 2)[1]).get("state");
    expect(encodedState).toBeTruthy();
    expect(JSON.parse(encodedState ?? "{}")).toMatchObject({
      pinned_keys: ["websocket:chat-1"],
      title_overrides: { "websocket:chat-1": "Release" },
      project_name_overrides: { "/Users/me/claudebot": "Core" },
    });
  });

  it("fetches workspace project state", async () => {
    const payload = {
      schema_version: 1,
      default_access_mode: "default" as const,
      default_scope: {
        project_path: "/tmp/workspace",
        project_name: "workspace",
        access_mode: "restricted" as const,
        restrict_to_workspace: true,
      },
      controls: {
        can_change_project: true,
        can_use_full_access: true,
      },
    };
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => payload,
    } as Response);

    await expect(fetchWorkspaces("tok")).resolves.toEqual(payload);
    expect(fetch).toHaveBeenCalledWith(
      "/api/workspaces",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });

  it("maps generated session titles from the sessions list", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        sessions: [
          {
            key: "websocket:chat-1",
            created_at: "2026-05-01T10:00:00",
            updated_at: "2026-05-01T10:01:00",
            title: "优化 WebUI 标题",
            run_started_at: 1_700_000_000,
          },
        ],
      }),
    } as Response);

    await expect(listSessions("tok")).resolves.toMatchObject([
      {
        key: "websocket:chat-1",
        title: "优化 WebUI 标题",
        preview: "",
        runStartedAt: 1_700_000_000,
      },
    ]);
  });

  it("maps slash command metadata from the commands endpoint", async () => {
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        commands: [
          {
            command: "/stop",
            title: "Stop current task",
            description: "Cancel the active task.",
            icon: "square",
          },
          {
            command: "/restart",
            title: "Restart claudebot",
            description: "Restart the bot process.",
            icon: "rotate-cw",
          },
          {
            command: "/help",
            title: "Show help",
            description: "List available slash commands.",
            icon: "circle-help",
          },
        ],
      }),
    } as Response);

    await expect(listSlashCommands("tok")).resolves.toEqual([
      {
        command: "/help",
        title: "Show help",
        description: "List available slash commands.",
        icon: "circle-help",
        argHint: "",
      },
    ]);
    expect(fetch).toHaveBeenCalledWith(
      "/api/commands",
      expect.objectContaining({
        headers: { Authorization: "Bearer tok" },
      }),
    );
  });
});
