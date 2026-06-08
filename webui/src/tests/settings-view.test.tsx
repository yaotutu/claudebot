import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SettingsView } from "@/components/settings/SettingsView";
import { ClientProvider } from "@/providers/ClientProvider";
import type { SettingsPayload } from "@/lib/types";

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function settingsPayload(): SettingsPayload {
  return {
    agent: {
      model: "glm-cn/glm-5.1",
      has_api_key: true,
      max_tokens: 8192,
      context_window_tokens: 65536,
      temperature: 0.1,
      reasoning_effort: null,
      timezone: "UTC",
      bot_name: "claudebot",
      bot_icon: "nb",
      tool_hint_max_length: 40,
    },
    runtime: {
      config_path: "/tmp/config.json",
      workspace_path: "/tmp/workspace",
      gateway_host: "127.0.0.1",
      gateway_port: 18790,
      heartbeat: {
        enabled: true,
        interval_s: 1800,
        keep_recent_messages: 8,
      },
      dream: {
        schedule: "every 2h",
      },
      unified_session: false,
    },
    advanced: {
      restrict_to_workspace: false,
      webui_allow_local_service_access: true,
      webui_default_access_mode: "default",
      private_service_protection_enabled: true,
      ssrf_whitelist_count: 0,
      mcp_server_count: 0,
      exec_enabled: true,
      exec_sandbox: null,
      exec_path_append_set: false,
    },
    requires_restart: false,
  };
}

function claudeCodeSettingsPayload() {
  return {
    claudeCode: {
      baseUrl: "http://127.0.0.1:20128/v1",
      authMode: "api_key",
      apiKey: "sk-***",
      model: "glm-cn/glm-5.1",
      permissionMode: "bypassPermissions",
      enableGatewayModelDiscovery: true,
      maxTurns: 200,
    },
    health: {
      sdkRuntime: true,
      modelsEndpointReachable: true,
      lastError: "",
    },
  };
}

function renderSettingsView(
  options: {
    initialSection?: "overview" | "advanced";
    onSettingsChange?: (payload: SettingsPayload) => void;
  } = {},
) {
  render(
    <ClientProvider client={{} as never} token="tok">
      <SettingsView
        theme="light"
        initialSection={options.initialSection ?? "overview"}
        onToggleTheme={() => {}}
        onBackToChat={() => {}}
        onModelNameChange={() => {}}
        onSettingsChange={options.onSettingsChange}
      />
    </ClientProvider>,
  );
}

describe("SettingsView", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("publishes the latest settings payload to the shell", async () => {
    const payload = settingsPayload();
    const onSettingsChange = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(payload);
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ onSettingsChange });

    await waitFor(() => expect(onSettingsChange).toHaveBeenCalledWith(payload));
  });

  it("shows Claude Code gateway settings on the overview", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/api/settings") return jsonResponse(settingsPayload());
        if (url === "/api/settings/claude-code") return jsonResponse(claudeCodeSettingsPayload());
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }),
    );

    renderSettingsView({ initialSection: "overview" });

    expect(await screen.findByRole("heading", { name: "Claude Code" })).toBeInTheDocument();
    expect(await screen.findByDisplayValue("glm-cn/glm-5.1")).toBeInTheDocument();
    expect(screen.getByText(/API key configured/)).toBeInTheDocument();
    expect(screen.getByText(/sk-/)).toBeInTheDocument();
    expect(screen.getAllByText("Full").length).toBeGreaterThan(0);
  });

  it("saves network safety without exposing technical SSRF copy", async () => {
    const payload = settingsPayload();
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/api/settings") return jsonResponse(payload);
      if (url === "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=default") {
        return jsonResponse({
          ...payload,
          advanced: { ...payload.advanced, webui_allow_local_service_access: false },
          requires_restart: true,
          restart_required_sections: ["runtime"],
        });
      }
      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);

    renderSettingsView({ initialSection: "advanced" });

    expect(await screen.findByText("Web safety")).toBeInTheDocument();
    expect(screen.queryByText(/SSRF/i)).not.toBeInTheDocument();
    expect(screen.queryByText("Private Service Protection")).not.toBeInTheDocument();
    expect(screen.getByText("Default access")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restricted" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Default Permission" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Full Access" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Local services" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/settings/network-safety/update?webui_allow_local_service_access=false&webui_default_access_mode=default",
        expect.objectContaining({
          headers: { Authorization: "Bearer tok" },
        }),
      ),
    );
  });

});
