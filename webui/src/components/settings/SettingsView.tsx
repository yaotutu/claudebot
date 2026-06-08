import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";
import {
  Activity,
  Bot,
  Check,
  ChevronDown,
  ChevronLeft,
  Loader2,
  LogOut,
  Palette,
  RotateCcw,
  Search,
  Server,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { SkillsCatalogSettings } from "@/components/settings/SkillsCatalogSettings";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import {
  fetchClaudeCodeHealth,
  fetchClaudeCodeSettings,
  fetchSettings,
  updateClaudeCodeSettings,
  updateNetworkSafetySettings,
  updateSettings,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useClient } from "@/providers/ClientProvider";
import type {
  ClaudeCodePermissionMode,
  ClaudeCodeSettingsPayload,
  ClaudeCodeSettingsUpdate,
  NetworkSafetySettingsUpdate,
  SettingsPayload,
  SkillSummary,
  WebuiDefaultAccessMode,
} from "@/lib/types";

export type SettingsSectionKey =
  | "overview"
  | "appearance"
  | "skills"
  | "runtime"
  | "advanced";

type LocalDensity = "comfortable" | "compact";
type LocalActivityMode = "auto" | "expanded";

interface LocalPreferences {
  density: LocalDensity;
  activityMode: LocalActivityMode;
  codeWrap: boolean;
  brandLogos: boolean;
}

interface AgentSettingsDraft {
  timezone: string;
  botName: string;
  botIcon: string;
  toolHintMaxLength: number;
}

interface ClaudeCodeSettingsDraft {
  baseUrl: string;
  apiKey: string;
  model: string;
  permissionMode: ClaudeCodePermissionMode;
  enableGatewayModelDiscovery: boolean;
  maxTurns: number;
}

type PendingRestartSection = "runtime";
type PendingRestartSections = Record<PendingRestartSection, boolean>;
const FALLBACK_TIMEZONES = [
  "UTC",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Tokyo",
  "Asia/Seoul",
  "Asia/Singapore",
  "Asia/Taipei",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Amsterdam",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/Toronto",
  "America/Sao_Paulo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

const LOCAL_PREFS_STORAGE_KEY = "claudebot-webui.settings-preferences";

const DEFAULT_LOCAL_PREFS: LocalPreferences = {
  density: "comfortable",
  activityMode: "auto",
  codeWrap: true,
  brandLogos: true,
};
const EMPTY_PENDING_RESTART_SECTIONS: PendingRestartSections = {
  runtime: false,
};

interface SettingsViewProps {
  theme: "light" | "dark";
  initialSection?: SettingsSectionKey;
  initialSettings?: SettingsPayload | null;
  showSidebar?: boolean;
  onToggleTheme: () => void;
  onBackToChat: () => void;
  onModelNameChange: (modelName: string | null) => void;
  onSettingsChange?: (payload: SettingsPayload) => void;
  skills?: SkillSummary[];
  onWorkspaceSettingsChange?: () => void | Promise<void>;
  onSectionChange?: (section: SettingsSectionKey) => void;
  onLogout?: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}

function readLocalPreferences(): LocalPreferences {
  try {
    const raw = window.localStorage.getItem(LOCAL_PREFS_STORAGE_KEY);
    if (!raw) return DEFAULT_LOCAL_PREFS;
    const parsed = JSON.parse(raw) as Partial<LocalPreferences>;
    return {
      density: parsed.density === "compact" ? "compact" : "comfortable",
      activityMode: parsed.activityMode === "expanded" ? "expanded" : "auto",
      codeWrap: parsed.codeWrap !== false,
      brandLogos: parsed.brandLogos !== false,
    };
  } catch {
    return DEFAULT_LOCAL_PREFS;
  }
}

const DEFAULT_AGENT_SETTINGS_DRAFT: AgentSettingsDraft = {
  timezone: "UTC",
  botName: "claudebot",
  botIcon: "",
  toolHintMaxLength: 40,
};

const DEFAULT_CLAUDE_CODE_DRAFT: ClaudeCodeSettingsDraft = {
  baseUrl: "",
  apiKey: "",
  model: "glm-cn/glm-5.1",
  permissionMode: "bypassPermissions",
  enableGatewayModelDiscovery: true,
  maxTurns: 200,
};

const DEFAULT_CLAUDE_CODE_SETTINGS: ClaudeCodeSettingsPayload["claudeCode"] = {
  baseUrl: "",
  authMode: "official_or_external",
  apiKey: "",
  model: "glm-cn/glm-5.1",
  permissionMode: "bypassPermissions",
  enableGatewayModelDiscovery: true,
  maxTurns: 200,
};

const DEFAULT_CLAUDE_CODE_HEALTH: ClaudeCodeSettingsPayload["health"] = {
  sdkRuntime: true,
  modelsEndpointReachable: false,
  lastError: "",
};

const DEFAULT_NETWORK_SAFETY_FORM: NetworkSafetySettingsUpdate = {
  webuiAllowLocalServiceAccess: true,
  webuiDefaultAccessMode: "default",
};

function agentDraftFromPayload(payload: SettingsPayload): AgentSettingsDraft {
  return {
    timezone: payload.agent.timezone,
    botName: payload.agent.bot_name,
    botIcon: payload.agent.bot_icon,
    toolHintMaxLength: payload.agent.tool_hint_max_length,
  };
}

function claudeCodeDraftFromPayload(
  payload: ClaudeCodeSettingsPayload,
  previous?: ClaudeCodeSettingsDraft,
): ClaudeCodeSettingsDraft {
  const current = payload.claudeCode ?? DEFAULT_CLAUDE_CODE_SETTINGS;
  return {
    baseUrl: current.baseUrl,
    apiKey: previous?.apiKey ?? "",
    model: current.model,
    permissionMode: current.permissionMode,
    enableGatewayModelDiscovery: current.enableGatewayModelDiscovery,
    maxTurns: current.maxTurns,
  };
}

function networkSafetyFormFromPayload(payload: SettingsPayload): NetworkSafetySettingsUpdate {
  return {
    webuiAllowLocalServiceAccess:
      payload.advanced.webui_allow_local_service_access ??
      payload.advanced.allow_local_preview_access ??
      true,
    webuiDefaultAccessMode: visibleWebuiDefaultAccessMode(
      payload.advanced.webui_default_access_mode,
    ),
  };
}

function pendingRestartSectionsFromPayload(payload: SettingsPayload): PendingRestartSections {
  const sections = payload.restart_required_sections ?? [];
  return {
    runtime: sections.includes("runtime"),
  };
}

export function SettingsView({
  theme,
  initialSection = "overview",
  initialSettings = null,
  showSidebar = true,
  onToggleTheme,
  onBackToChat,
  onSettingsChange,
  skills = [],
  onWorkspaceSettingsChange,
  onSectionChange,
  onLogout,
  onRestart,
  isRestarting = false,
}: SettingsViewProps) {
  const { t } = useTranslation();
  const { token } = useClient();
  const [settings, setSettings] = useState<SettingsPayload | null>(() => initialSettings);
  const [claudeCodeSettings, setClaudeCodeSettings] = useState<ClaudeCodeSettingsPayload | null>(null);
  const [loading, setLoading] = useState(() => initialSettings === null);
  const [claudeCodeLoading, setClaudeCodeLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [claudeCodeSaving, setClaudeCodeSaving] = useState(false);
  const [claudeCodeHealthLoading, setClaudeCodeHealthLoading] = useState(false);
  const [networkSafetySaving, setNetworkSafetySaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SettingsSectionKey>(initialSection);
  const [pendingRestartSections, setPendingRestartSections] = useState<PendingRestartSections>(
    EMPTY_PENDING_RESTART_SECTIONS,
  );
  const [localPrefs, setLocalPrefs] = useState<LocalPreferences>(() => readLocalPreferences());
  const [networkSafetyForm, setNetworkSafetyForm] = useState<NetworkSafetySettingsUpdate>(() =>
    initialSettings ? networkSafetyFormFromPayload(initialSettings) : DEFAULT_NETWORK_SAFETY_FORM,
  );

  useEffect(() => {
    setActiveSection(initialSection);
  }, [initialSection]);

  const selectSection = useCallback(
    (section: SettingsSectionKey) => {
      setActiveSection(section);
      onSectionChange?.(section);
    },
    [onSectionChange],
  );
  const [form, setForm] = useState<AgentSettingsDraft>(() =>
    initialSettings ? agentDraftFromPayload(initialSettings) : DEFAULT_AGENT_SETTINGS_DRAFT,
  );
  const [claudeCodeForm, setClaudeCodeForm] = useState<ClaudeCodeSettingsDraft>(
    DEFAULT_CLAUDE_CODE_DRAFT,
  );

  const text = useCallback(
    (key: string, fallback: string, options?: Record<string, unknown>) =>
      t(key, { defaultValue: fallback, ...(options ?? {}) }),
    [t],
  );

  const applyPayload = useCallback((payload: SettingsPayload) => {
    setSettings(payload);
    setForm(agentDraftFromPayload(payload));
    setNetworkSafetyForm(networkSafetyFormFromPayload(payload));
    if (payload.restart_required_sections) {
      setPendingRestartSections(pendingRestartSectionsFromPayload(payload));
    }
    onSettingsChange?.(payload);
  }, [onSettingsChange]);

  const applyClaudeCodePayload = useCallback((payload: ClaudeCodeSettingsPayload) => {
    const normalized = {
      ...payload,
      claudeCode: payload.claudeCode ?? DEFAULT_CLAUDE_CODE_SETTINGS,
      health: payload.health ?? DEFAULT_CLAUDE_CODE_HEALTH,
    };
    setClaudeCodeSettings(normalized);
    setClaudeCodeForm((prev) => claudeCodeDraftFromPayload(normalized, prev));
  }, []);

  useEffect(() => {
    if (!initialSettings || settings !== null) return;
    applyPayload(initialSettings);
    setLoading(false);
  }, [applyPayload, initialSettings, settings]);

  useEffect(() => {
    let cancelled = false;
    const showLoading = settings === null;
    if (showLoading) setLoading(true);
    fetchSettings(token)
      .then((payload) => {
        if (!cancelled) {
          applyPayload(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled && showLoading) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyPayload, token]);

  useEffect(() => {
    let cancelled = false;
    setClaudeCodeLoading(true);
    fetchClaudeCodeSettings(token)
      .then((payload) => {
        if (!cancelled) {
          applyClaudeCodePayload(payload);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError((err as Error).message);
      })
      .finally(() => {
        if (!cancelled) setClaudeCodeLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applyClaudeCodePayload, token]);

  useEffect(() => {
    try {
      window.localStorage.setItem(LOCAL_PREFS_STORAGE_KEY, JSON.stringify(localPrefs));
    } catch {
      // Browser-only preferences should never block settings.
    }
  }, [localPrefs]);

  const runtimeDirty = useMemo(() => {
    if (!settings) return false;
    return (
      form.timezone !== settings.agent.timezone ||
      form.botName !== settings.agent.bot_name ||
      form.botIcon !== settings.agent.bot_icon
    );
  }, [form, settings]);

  const networkSafetyDirty = useMemo(() => {
    if (!settings) return false;
    const currentLocalServiceAccess =
      settings.advanced.webui_allow_local_service_access ?? settings.advanced.allow_local_preview_access ?? true;
    const currentDefaultAccess = visibleWebuiDefaultAccessMode(settings.advanced.webui_default_access_mode);
    return (
      networkSafetyForm.webuiAllowLocalServiceAccess !== currentLocalServiceAccess ||
      networkSafetyForm.webuiDefaultAccessMode !== currentDefaultAccess
    );
  }, [networkSafetyForm, settings]);

  const claudeCodeDirty = useMemo(() => {
    const current = claudeCodeSettings?.claudeCode;
    if (!current) return false;
    return (
      claudeCodeForm.baseUrl !== current.baseUrl ||
      !!claudeCodeForm.apiKey.trim() ||
      claudeCodeForm.model !== current.model ||
      claudeCodeForm.permissionMode !== current.permissionMode ||
      claudeCodeForm.enableGatewayModelDiscovery !== current.enableGatewayModelDiscovery ||
      claudeCodeForm.maxTurns !== current.maxTurns
    );
  }, [claudeCodeForm, claudeCodeSettings]);

  const restartViaSettingsSurface = useCallback(() => {
    onRestart?.();
  }, [onRestart]);

  const saveClaudeCodeSettings = async () => {
    if (!claudeCodeSettings || !claudeCodeDirty || claudeCodeSaving) return;
    const update: ClaudeCodeSettingsUpdate = {
      baseUrl: claudeCodeForm.baseUrl,
      model: claudeCodeForm.model,
      permissionMode: claudeCodeForm.permissionMode,
      enableGatewayModelDiscovery: claudeCodeForm.enableGatewayModelDiscovery,
      maxTurns: claudeCodeForm.maxTurns,
    };
    const apiKey = claudeCodeForm.apiKey.trim();
    if (apiKey) update.apiKey = apiKey;

    setClaudeCodeSaving(true);
    try {
      const payload = await updateClaudeCodeSettings(token, update);
      applyClaudeCodePayload(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setClaudeCodeSaving(false);
    }
  };

  const refreshClaudeCodeHealth = async () => {
    if (!claudeCodeSettings || claudeCodeHealthLoading) return;
    setClaudeCodeHealthLoading(true);
    try {
      const payload = await fetchClaudeCodeHealth(token);
      setClaudeCodeSettings((current) =>
        current ? { ...current, health: payload.health } : current,
      );
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setClaudeCodeHealthLoading(false);
    }
  };

  const saveRuntimeSettings = async () => {
    if (!settings || !runtimeDirty || saving) return;
    setSaving(true);
    try {
      const payload = await updateSettings(token, {
        timezone: form.timezone,
        botName: form.botName,
        botIcon: form.botIcon,
      });
      applyPayload(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      await onWorkspaceSettingsChange?.();
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const saveNetworkSafetySettings = async () => {
    if (!settings || !networkSafetyDirty || networkSafetySaving) return;
    setNetworkSafetySaving(true);
    try {
      const payload = await updateNetworkSafetySettings(token, networkSafetyForm);
      applyPayload(payload);
      if (payload.requires_restart) {
        setPendingRestartSections((prev) => ({ ...prev, runtime: true }));
      }
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setNetworkSafetySaving(false);
    }
  };

  const renderSection = () => {
    if (!settings) return null;
    switch (activeSection) {
      case "overview":
        return claudeCodeSettings ? (
          <ClaudeCodeSettingsPanel
            settings={claudeCodeSettings}
            draft={claudeCodeForm}
            dirty={claudeCodeDirty}
            saving={claudeCodeSaving}
            healthLoading={claudeCodeHealthLoading}
            requiresRestartPending={pendingRestartSections.runtime}
            onChangeDraft={setClaudeCodeForm}
            onSave={saveClaudeCodeSettings}
            onRefreshHealth={refreshClaudeCodeHealth}
            onRestart={restartViaSettingsSurface}
            isRestarting={isRestarting}
          />
        ) : null;
      case "runtime":
        return (
          <RuntimeSettings
            form={form}
            setForm={setForm}
            settings={settings}
            dirty={runtimeDirty}
            saving={saving}
            onSave={saveRuntimeSettings}
            onRestart={restartViaSettingsSurface}
            isRestarting={isRestarting}
            requiresRestartPending={pendingRestartSections.runtime}
          />
        );
      case "appearance":
        return (
          <AppearanceSettings
            theme={theme}
            onToggleTheme={onToggleTheme}
            localPrefs={localPrefs}
            onChangeLocalPrefs={setLocalPrefs}
          />
        );
      case "skills":
        return <SkillsCatalogSettings skills={skills} />;
      case "advanced":
        return (
          <AdvancedSettings
            form={networkSafetyForm}
            dirty={networkSafetyDirty}
            saving={networkSafetySaving}
            onChangeForm={setNetworkSafetyForm}
            onSave={saveNetworkSafetySettings}
            onRestart={restartViaSettingsSurface}
            isRestarting={isRestarting}
            requiresRestartPending={pendingRestartSections.runtime}
          />
        );
      default:
        return null;
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-[radial-gradient(circle_at_50%_0%,hsl(var(--muted))_0%,hsl(var(--background))_42%)] md:flex-row">
      {showSidebar ? (
        <SettingsSidebar
          activeSection={activeSection}
          onSelectSection={selectSection}
          onBackToChat={onBackToChat}
          onLogout={onLogout}
        />
      ) : null}

      <main className="min-w-0 flex-1 overflow-y-auto [scrollbar-gutter:stable]">
        <div className="mx-auto w-full max-w-[920px] px-5 py-8 sm:px-8 lg:py-12">
          <div className="mb-7">
            {!showSidebar ? (
              <button
                type="button"
                onClick={onBackToChat}
                className="mb-4 inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground lg:hidden"
              >
                <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
                {t("settings.backToChat")}
              </button>
            ) : null}
            <p className="mb-2 text-[12px] font-normal text-muted-foreground">
              {t("settings.sidebar.title")}
            </p>
            <h1 className="text-[24px] font-normal leading-tight tracking-normal text-foreground sm:text-[28px]">
              {text(`settings.nav.${activeSection}`, titleForSection(activeSection))}
            </h1>
          </div>

          {loading || claudeCodeLoading ? (
            <div className="flex h-48 items-center justify-center rounded-[24px] border border-border/50 bg-card/75 text-sm text-muted-foreground shadow-[0_20px_70px_rgba(15,23,42,0.07)]">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              {t("settings.status.loading")}
            </div>
          ) : error && !settings ? (
            <SettingsGroup>
              <SettingsRow title={t("settings.status.loadError")}>
                <span className="max-w-[520px] text-sm text-muted-foreground">{error}</span>
              </SettingsRow>
            </SettingsGroup>
          ) : settings ? (
            <div className="space-y-5">
              {error ? (
                <div className="rounded-[18px] border border-destructive/20 bg-destructive/5 px-4 py-3 text-[13px] text-destructive">
                  {error}
                </div>
              ) : null}
              {renderSection()}
            </div>
          ) : null}
        </div>
      </main>
    </div>
  );
}

const SETTINGS_NAV_ITEMS: Array<{ key: SettingsSectionKey; icon: LucideIcon; fallback: string }> = [
  { key: "overview", icon: Bot, fallback: "Claude Code" },
  { key: "appearance", icon: Palette, fallback: "Appearance" },
  { key: "skills", icon: Sparkles, fallback: "Skills" },
  { key: "runtime", icon: Server, fallback: "System" },
  { key: "advanced", icon: ShieldCheck, fallback: "Security" },
];

function visibleWebuiDefaultAccessMode(mode: string | null | undefined): WebuiDefaultAccessMode {
  return mode === "full" ? "full" : "default";
}

function titleForSection(section: SettingsSectionKey): string {
  return SETTINGS_NAV_ITEMS.find((item) => item.key === section)?.fallback ?? "Settings";
}

function SettingsSidebar({
  activeSection,
  onSelectSection,
  onBackToChat,
  onLogout,
}: {
  activeSection: SettingsSectionKey;
  onSelectSection: (section: SettingsSectionKey) => void;
  onBackToChat: () => void;
  onLogout?: () => void;
}) {
  const { t } = useTranslation();
  return (
    <aside
      className="flex w-full shrink-0 flex-col border-b border-border/55 bg-card/62 px-4 pb-3 pt-4 shadow-[inset_0_-1px_0_rgba(255,255,255,0.55)] backdrop-blur-xl dark:bg-card/45 dark:shadow-none md:w-[17rem] md:border-b-0 md:border-r md:px-3 md:pb-4 md:pt-4 md:shadow-[inset_-1px_0_0_rgba(255,255,255,0.55)]"
    >
      <button
        type="button"
        onClick={onBackToChat}
        className="mb-2 inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] font-medium text-muted-foreground transition-colors hover:bg-muted/70 hover:text-foreground md:mb-3"
      >
        <ChevronLeft className="h-3.5 w-3.5" aria-hidden />
        {t("settings.backToChat")}
      </button>
      <div className="mb-3 px-1 md:mb-4 md:px-2">
        <h2 className="text-[18px] font-normal tracking-normal text-foreground">
          {t("settings.sidebar.title")}
        </h2>
      </div>

      <nav
        aria-label={t("settings.sidebar.ariaLabel")}
        className="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden md:mx-0 md:block md:space-y-1 md:overflow-visible md:px-0 md:pb-0"
      >
        {SETTINGS_NAV_ITEMS.map(({ key, icon: Icon, fallback }) => {
          const active = key === activeSection;
          return (
            <button
              key={key}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onSelectSection(key)}
              className={cn(
                "flex h-9 w-auto shrink-0 items-center gap-2 rounded-full px-3 text-left text-[13px] font-medium transition-colors md:w-full md:rounded-[10px] md:px-2.5",
                active
                  ? "bg-muted/90 text-foreground shadow-[inset_0_0_0_1px_rgba(0,0,0,0.025)]"
                  : "text-muted-foreground/78 hover:bg-muted/45 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4 shrink-0" strokeWidth={2} aria-hidden />
              <span className="truncate">{t(`settings.nav.${key}`, { defaultValue: fallback })}</span>
            </button>
          );
        })}
      </nav>

      <div className="hidden md:mt-auto md:block md:pt-4">
        {onLogout ? (
          <Button
            type="button"
            variant="ghost"
            onClick={onLogout}
            className="h-9 w-full justify-start gap-2 rounded-[10px] px-2.5 text-[13px] font-medium text-muted-foreground hover:bg-destructive/8 hover:text-destructive"
          >
            <LogOut className="h-4 w-4" aria-hidden />
            {t("app.account.logout")}
          </Button>
        ) : null}
      </div>
    </aside>
  );
}

function ClaudeCodeSettingsPanel({
  settings,
  draft,
  dirty,
  saving,
  healthLoading,
  requiresRestartPending,
  onChangeDraft,
  onSave,
  onRefreshHealth,
  onRestart,
  isRestarting,
}: {
  settings: ClaudeCodeSettingsPayload;
  draft: ClaudeCodeSettingsDraft;
  dirty: boolean;
  saving: boolean;
  healthLoading: boolean;
  requiresRestartPending: boolean;
  onChangeDraft: Dispatch<SetStateAction<ClaudeCodeSettingsDraft>>;
  onSave: () => void;
  onRefreshHealth: () => void;
  onRestart?: () => void;
  isRestarting: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const current = settings.claudeCode;
  const health = settings.health;
  const permissionOptions = [
    { value: "default", label: tx("settings.claude.permissions.readOnly", "Read only") },
    { value: "acceptEdits", label: tx("settings.claude.permissions.edit", "Edit") },
    { value: "bypassPermissions", label: tx("settings.claude.permissions.full", "Full") },
  ];
  const authStatus =
    current.authMode === "api_key"
      ? tx("settings.claude.apiKeyConfigured", "API key configured")
      : tx("settings.claude.officialAuth", "Official Claude auth or external provider");

  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{tx("settings.claude.title", "Claude Code")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.claude.baseUrl", "Compatible API base URL")}
            description={tx("settings.claude.baseUrlHelp", "Anthropic-compatible endpoint used by Claude Code.")}
          >
            <Input
              value={draft.baseUrl}
              placeholder="http://127.0.0.1:20128/v1"
              onChange={(event) =>
                onChangeDraft((prev) => ({ ...prev, baseUrl: event.target.value }))
              }
              className="h-9 w-[min(420px,70vw)] rounded-full px-4 text-[13px]"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.claude.apiKey", "ANTHROPIC_API_KEY")}
            description={`${authStatus}${current.apiKey ? ` · ${current.apiKey}` : ""}`}
          >
            <Input
              type="password"
              value={draft.apiKey}
              placeholder={current.apiKey || tx("settings.claude.secretPlaceholder", "Leave blank to keep current")}
              onChange={(event) =>
                onChangeDraft((prev) => ({ ...prev, apiKey: event.target.value }))
              }
              className="h-9 w-[min(360px,70vw)] rounded-full px-4 text-[13px]"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.model", "Model")}
            description={tx("settings.claude.modelHelp", "Model name passed through to Claude Code.")}
          >
            <Input
              value={draft.model}
              placeholder="glm-cn/glm-5.1"
              onChange={(event) =>
                onChangeDraft((prev) => ({ ...prev, model: event.target.value }))
              }
              className="h-9 w-[min(360px,70vw)] rounded-full px-4 text-[13px]"
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.claude.permissionMode", "Permission mode")}
            description={tx("settings.claude.permissionModeHelp", "Default Claude Code workspace permission.")}
          >
            <SegmentedControl
              value={draft.permissionMode}
              options={permissionOptions}
              onChange={(permissionMode) =>
                onChangeDraft((prev) => ({
                  ...prev,
                  permissionMode: permissionMode as ClaudeCodePermissionMode,
                }))
              }
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.claude.modelDiscovery", "Gateway model discovery")}
            description={tx("settings.claude.modelDiscoveryHelp", "Expose compatible gateway models to Claude Code.")}
          >
            <ToggleButton
              checked={draft.enableGatewayModelDiscovery}
              onChange={(enableGatewayModelDiscovery) =>
                onChangeDraft((prev) => ({ ...prev, enableGatewayModelDiscovery }))
              }
              ariaLabel={tx("settings.claude.modelDiscovery", "Gateway model discovery")}
              label={
                draft.enableGatewayModelDiscovery
                  ? tx("settings.values.on", "On")
                  : tx("settings.values.off", "Off")
              }
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.claude.maxTurns", "Max turns")}
            description={tx("settings.claude.maxTurnsHelp", "Upper bound for one Claude Code run.")}
          >
            <Input
              type="number"
              min={1}
              value={draft.maxTurns}
              onChange={(event) =>
                onChangeDraft((prev) => ({
                  ...prev,
                  maxTurns: Math.max(1, Number(event.target.value || 1)),
                }))
              }
              className="h-9 w-28 rounded-full px-4 text-[13px]"
            />
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.status", "Status")}</SettingsSectionTitle>
        <div className="grid gap-3 sm:grid-cols-3">
          <StatusCard
            title={tx("settings.claude.sdkRuntime", "Claude SDK")}
            value={
              health.sdkRuntime
                ? tx("settings.values.ready", "Ready")
                : tx("settings.values.notConfigured", "Not configured")
            }
            caption={tx("settings.claude.sdkRuntimeHelp", "Agent SDK runtime")}
          />
          <StatusCard
            title={tx("settings.claude.modelsEndpoint", "Models endpoint")}
            value={
              health.modelsEndpointReachable
                ? tx("settings.values.ready", "Ready")
                : tx("settings.values.unavailable", "Unavailable")
            }
            caption={current.baseUrl || tx("settings.claude.noBaseUrl", "No base URL configured")}
          />
          <StatusCard
            title={tx("settings.claude.activePermission", "Permission")}
            value={
              permissionOptions.find((option) => option.value === current.permissionMode)?.label ??
              current.permissionMode
            }
            caption={current.model}
          />
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-end gap-2">
        {requiresRestartPending ? (
          <Button
            type="button"
            variant="outline"
            className="rounded-full"
            onClick={onRestart}
            disabled={isRestarting}
          >
            {isRestarting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {isRestarting
              ? tx("app.system.restartingEngine", "Restarting engine...")
              : tx("app.system.restartEngine", "Restart engine")}
          </Button>
        ) : null}
        <Button
          type="button"
          variant="outline"
          className="rounded-full"
          onClick={onRefreshHealth}
          disabled={healthLoading}
        >
          {healthLoading ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Activity className="mr-1.5 h-3.5 w-3.5" aria-hidden />
          )}
          {tx("settings.actions.refresh", "Refresh")}
        </Button>
        <Button
          type="button"
          variant="default"
          className="rounded-full"
          onClick={onSave}
          disabled={!dirty || saving}
        >
          {saving ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          {saving ? tx("settings.actions.saving", "Saving...") : tx("settings.actions.save", "Save")}
        </Button>
      </div>
    </div>
  );
}

function StatusCard({
  title,
  value,
  caption,
}: {
  title: string;
  value: string;
  caption: string;
}) {
  return (
    <div className="min-w-0 rounded-[14px] border border-border/45 bg-card/78 px-4 py-3 shadow-[0_10px_30px_rgba(15,23,42,0.045)]">
      <div className="text-[11.5px] font-medium text-muted-foreground">{title}</div>
      <div className="mt-1 truncate text-[14px] font-semibold text-foreground">{value}</div>
      <div className="mt-1 truncate text-[11.5px] text-muted-foreground">{caption}</div>
    </div>
  );
}

function AppearanceSettings({
  theme,
  onToggleTheme,
  localPrefs,
  onChangeLocalPrefs,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  localPrefs: LocalPreferences;
  onChangeLocalPrefs: Dispatch<SetStateAction<LocalPreferences>>;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{t("settings.sections.interface")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={t("settings.rows.theme")}
            description={t("settings.help.theme")}
          >
            <button
              type="button"
              onClick={onToggleTheme}
              className="inline-flex h-8 items-center rounded-full bg-muted p-0.5 text-[12px] font-medium text-muted-foreground"
            >
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "light" && "bg-background text-foreground shadow-sm",
                )}
              >
                {t("settings.values.light")}
              </span>
              <span
                className={cn(
                  "rounded-full px-3 py-1 transition-colors",
                  theme === "dark" && "bg-background text-foreground shadow-sm",
                )}
              >
                {t("settings.values.dark")}
              </span>
            </button>
          </SettingsRow>

          <SettingsRow
            title={t("settings.rows.language")}
            description={t("settings.help.language")}
          >
            <LanguageSwitcher />
          </SettingsRow>
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{tx("settings.sections.localPreferences", "Local preferences")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.rows.density", "Density")}
            description={tx("settings.help.density", "Stored only in this browser.")}
          >
            <SegmentedControl
              value={localPrefs.density}
              options={[
                { value: "comfortable", label: tx("settings.values.comfortable", "Comfortable") },
                { value: "compact", label: tx("settings.values.compact", "Compact") },
              ]}
              onChange={(density) =>
                onChangeLocalPrefs((prev) => ({ ...prev, density: density as LocalDensity }))
              }
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.activityMode", "Activity detail")}
            description={tx("settings.help.activityMode", "Choose how much agent activity chrome to show by default.")}
          >
            <SegmentedControl
              value={localPrefs.activityMode}
              options={[
                { value: "auto", label: tx("settings.values.auto", "Auto") },
                { value: "expanded", label: tx("settings.values.expanded", "Expanded") },
              ]}
              onChange={(activityMode) =>
                onChangeLocalPrefs((prev) => ({ ...prev, activityMode: activityMode as LocalActivityMode }))
              }
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.codeWrap", "Code wrapping")}
            description={tx("settings.help.codeWrap", "Keep long code lines readable on smaller screens.")}
          >
            <ToggleButton
              checked={localPrefs.codeWrap}
              onChange={(codeWrap) => onChangeLocalPrefs((prev) => ({ ...prev, codeWrap }))}
              ariaLabel={tx("settings.rows.codeWrap", "Code wrapping")}
              label={localPrefs.codeWrap ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.brandLogos", "Brand logos")}
            description={tx("settings.help.brandLogos", "Show third-party provider and CLI logos in Settings.")}
          >
            <ToggleButton
              checked={localPrefs.brandLogos}
              onChange={(brandLogos) => onChangeLocalPrefs((prev) => ({ ...prev, brandLogos }))}
              ariaLabel={tx("settings.rows.brandLogos", "Brand logos")}
              label={localPrefs.brandLogos ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
        </SettingsGroup>
      </section>
    </div>
  );
}

function RuntimeSettings({
  form,
  setForm,
  settings,
  dirty,
  saving,
  onSave,
  onRestart,
  isRestarting,
  requiresRestartPending,
}: {
  form: AgentSettingsDraft;
  setForm: Dispatch<SetStateAction<AgentSettingsDraft>>;
  settings: SettingsPayload;
  dirty: boolean;
  saving: boolean;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
  requiresRestartPending: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>{tx("settings.sections.identity", "Identity")}</SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow title={tx("settings.rows.botName", "Bot name")} description={tx("settings.help.botName", "Shown wherever claudebot uses a display name.")}>
            <Input
              value={form.botName}
              onChange={(event) => setForm((prev) => ({ ...prev, botName: event.target.value }))}
              className="h-8 w-[220px] rounded-full text-[13px]"
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.botIcon", "Bot icon")} description={tx("settings.help.botIcon", "Short emoji or text shown with the bot name.")}>
            <Input
              value={form.botIcon}
              onChange={(event) => setForm((prev) => ({ ...prev, botIcon: event.target.value }))}
              className="h-8 w-[120px] rounded-full text-center text-[13px]"
            />
          </SettingsRow>
          <SettingsRow title={tx("settings.rows.timezone", "Timezone")} description={tx("settings.help.timezone", "Used for schedules and time-aware replies.")}>
            <TimezonePicker
              value={form.timezone}
              onChange={(timezone) => setForm((prev) => ({ ...prev, timezone }))}
            />
          </SettingsRow>
          <RestartSettingsFooter
            dirty={dirty}
            saving={saving}
            pendingRestart={requiresRestartPending}
            dirtyMessage={tx("settings.status.restartAfterSaving", "Save changes, then restart when ready.")}
            pendingMessage={tx("settings.status.savedRestartApply", "Saved. Restart when ready.")}
            onSave={onSave}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>

      <section>
        <SettingsSectionTitle>{t("settings.sections.system")}</SettingsSectionTitle>
        <SettingsGroup>
          <ReadOnlyRow
            title={tx("settings.rows.gateway", "Gateway")}
            value={`${settings.runtime.gateway_host}:${settings.runtime.gateway_port}`}
          />
          <ReadOnlyRow title={t("settings.rows.configPath")} value={settings.runtime.config_path} />
          <ReadOnlyRow title={tx("settings.rows.workspacePath", "Default workspace")} value={settings.runtime.workspace_path} />
          {onRestart && !requiresRestartPending ? (
            <SettingsRow
              title={t("settings.rows.restart")}
              description={t("app.system.restartHint")}
            >
              <Button
                size="sm"
                variant="outline"
                onClick={onRestart}
                disabled={isRestarting}
                className="rounded-full"
              >
                {isRestarting ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
                )}
                {isRestarting ? t("app.system.restarting") : t("app.system.restart")}
              </Button>
            </SettingsRow>
          ) : null}
        </SettingsGroup>
      </section>
    </div>
  );
}

function AdvancedSettings({
  form,
  dirty,
  saving,
  requiresRestartPending,
  onChangeForm,
  onSave,
  onRestart,
  isRestarting,
}: {
  form: NetworkSafetySettingsUpdate;
  dirty: boolean;
  saving: boolean;
  requiresRestartPending: boolean;
  onChangeForm: Dispatch<SetStateAction<NetworkSafetySettingsUpdate>>;
  onSave: () => void;
  onRestart?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  return (
    <div className="space-y-7">
      <section>
        <SettingsSectionTitle>
          {tx("settings.sections.webuiSafety", "Web safety")}
        </SettingsSectionTitle>
        <SettingsGroup>
          <SettingsRow
            title={tx("settings.rows.localServiceAccess", "Local Service Access")}
            description={tx(
              "settings.help.localServiceAccess",
              "Allow Full Access shell commands to reach localhost services.",
            )}
          >
            <ToggleButton
              checked={form.webuiAllowLocalServiceAccess}
              onChange={(webuiAllowLocalServiceAccess) =>
                onChangeForm((prev) => ({ ...prev, webuiAllowLocalServiceAccess }))
              }
              ariaLabel={tx("settings.rows.localServiceAccess", "Local Service Access")}
              label={form.webuiAllowLocalServiceAccess ? tx("settings.values.on", "On") : tx("settings.values.off", "Off")}
            />
          </SettingsRow>
          <SettingsRow
            title={tx("settings.rows.webuiDefaultAccess", "Default access")}
            description={tx(
              "settings.help.webuiDefaultAccess",
              "Used by web chats without a project-specific permission.",
            )}
          >
            <SegmentedControl
              value={form.webuiDefaultAccessMode}
              options={[
                { value: "default", label: tx("settings.values.defaultPermission", "Default Permission") },
                { value: "full", label: tx("settings.values.fullAccess", "Full Access") },
              ]}
              onChange={(webuiDefaultAccessMode) =>
                onChangeForm((prev) => ({
                  ...prev,
                  webuiDefaultAccessMode: webuiDefaultAccessMode as WebuiDefaultAccessMode,
                }))
              }
            />
          </SettingsRow>
          <RestartSettingsFooter
            dirty={dirty}
            saving={saving}
            pendingRestart={requiresRestartPending}
            onSave={onSave}
            onRestart={onRestart}
            isRestarting={isRestarting}
          />
        </SettingsGroup>
      </section>

      <p className="max-w-3xl px-1 text-sm leading-6 text-muted-foreground">
        {tx(
          "settings.help.securityManagedControls",
          "Web fetches always protect local, private, and metadata services. Core channel safety stays in config.json.",
        )}
      </p>
    </div>
  );
}

interface TimezoneOption {
  name: string;
  offset: string;
  searchText: string;
}

function timezoneOptions(current: string): TimezoneOption[] {
  return timezonesWithCurrent(current).map((name) => {
    const offset = timezoneOffset(name);
    return {
      name,
      offset,
      searchText: `${name} ${name.replace(/_/g, " ")} ${offset}`.toLowerCase(),
    };
  });
}

function timezonesWithCurrent(current: string): string[] {
  const intl = Intl as typeof Intl & {
    supportedValuesOf?: (key: "timeZone") => string[];
  };
  let values: string[];
  try {
    values = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    values = [];
  }
  const deduped = new Set([...FALLBACK_TIMEZONES, ...values, current].filter(Boolean));
  return Array.from(deduped).sort((left, right) => {
    if (left === "UTC") return -1;
    if (right === "UTC") return 1;
    return left.localeCompare(right);
  });
}

function filterTimezoneOptions(options: TimezoneOption[], query: string): TimezoneOption[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return options;
  return options.filter((option) => option.searchText.includes(normalized));
}

function timezoneOffset(timezone: string): string {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      timeZoneName: "shortOffset",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(new Date());
    const value = parts.find((part) => part.type === "timeZoneName")?.value;
    return value ? value.replace(/^GMT$/, "UTC").replace(/^GMT/, "UTC") : "UTC";
  } catch {
    return "Custom timezone";
  }
}

function TimezonePicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (timezone: string) => void;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const [query, setQuery] = useState("");
  const options = useMemo(() => timezoneOptions(value), [value]);
  const filteredOptions = useMemo(() => filterTimezoneOptions(options, query), [options, query]);

  return (
    <DropdownMenu onOpenChange={(open) => !open && setQuery("")}>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          className={cn(
            "h-8 w-[220px] justify-between rounded-full border-input bg-background px-3 text-[13px] font-normal shadow-none",
            "hover:bg-accent/55 focus-visible:ring-2 focus-visible:ring-ring",
          )}
        >
          <span className="truncate">{value || tx("settings.timezone.select", "Select timezone")}</span>
          <ChevronDown className="ml-2 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        className="w-[340px] max-w-[calc(100vw-2rem)]"
      >
        <div className="sticky top-0 z-10 bg-popover px-1 pb-1">
          <div className="flex h-9 items-center gap-2 rounded-full border border-input bg-background px-3">
            <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
            <Input
              autoFocus
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => event.stopPropagation()}
              placeholder={tx("settings.timezone.search", "Search timezone")}
              className="h-7 border-0 bg-transparent px-0 text-[13px] shadow-none focus-visible:ring-0"
            />
          </div>
        </div>
        <div
          className="mt-1 max-h-[18rem] overflow-y-auto pr-0.5 scrollbar-thin scrollbar-track-transparent"
          data-testid="timezone-picker-list"
        >
          {filteredOptions.length ? (
            filteredOptions.map((option) => {
              const selected = option.name === value;
              return (
                <DropdownMenuItem
                  key={option.name}
                  onSelect={() => onChange(option.name)}
                  className={cn(
                    "flex h-9 cursor-default items-center justify-between gap-3 rounded-[12px] px-2.5 text-[13px]",
                    "focus:bg-muted/85 focus:text-foreground",
                    selected && "bg-muted/80 text-foreground focus:bg-muted",
                  )}
                >
                  <span className="min-w-0 truncate font-medium text-foreground">{option.name}</span>
                  <span className="ml-auto flex shrink-0 items-center gap-2">
                    <span className="text-[11.5px] font-medium text-muted-foreground/80">
                      {option.offset}
                    </span>
                    {selected ? <Check className="h-3.5 w-3.5 shrink-0" aria-hidden /> : null}
                  </span>
                </DropdownMenuItem>
              );
            })
          ) : (
            <div className="px-3 py-5 text-center text-[12px] text-muted-foreground">
              {tx("settings.timezone.empty", "No matching timezones.")}
            </div>
          )}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function SettingsSectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-2 px-1 text-[13px] font-semibold tracking-[-0.01em] text-foreground/85">
      {children}
    </h2>
  );
}

function SettingsGroup({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[22px] border border-border/45 bg-card/86 shadow-[0_18px_65px_rgba(15,23,42,0.075)] backdrop-blur-xl dark:border-white/10 dark:shadow-[0_18px_65px_rgba(0,0,0,0.24)]">
      <div className="divide-y divide-border/45">{children}</div>
    </div>
  );
}

function SettingsRow({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex min-h-[62px] flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <div className="text-[14px] font-medium leading-5 text-foreground">{title}</div>
        {description ? (
          <div className="mt-0.5 max-w-[28rem] text-[12px] leading-5 text-muted-foreground">
            {description}
          </div>
        ) : null}
      </div>
      {children ? <div className="shrink-0 sm:ml-6">{children}</div> : null}
    </div>
  );
}

function ReadOnlyRow({
  title,
  value,
  description,
}: {
  title: string;
  value: string;
  description?: string;
}) {
  return (
    <SettingsRow title={title} description={description}>
      <span className="block max-w-[320px] truncate text-right text-[13px] text-muted-foreground">
        {value}
      </span>
    </SettingsRow>
  );
}

function RestartSettingsFooter({
  dirty,
  saving,
  pendingRestart,
  disabled = false,
  message,
  dirtyMessage,
  pendingMessage,
  onSave,
  onRestart,
  onReset,
  isRestarting,
}: {
  dirty: boolean;
  saving: boolean;
  pendingRestart: boolean;
  disabled?: boolean;
  message?: string;
  dirtyMessage?: string;
  pendingMessage?: string;
  onSave: () => void;
  onRestart?: () => void;
  onReset?: () => void;
  isRestarting?: boolean;
}) {
  const { t } = useTranslation();
  const tx = (key: string, fallback: string) => t(key, { defaultValue: fallback });
  const statusMessage =
    message ??
    (pendingRestart && !dirty
      ? pendingMessage ?? tx("settings.status.savedRestartApply", "Saved. Restart when ready.")
      : dirty
        ? dirtyMessage ?? t("settings.status.unsaved")
        : undefined);
  const statusTone = disabled ? "danger" : dirty || pendingRestart ? "accent" : undefined;

  return (
    <div className="flex min-h-[58px] flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0 text-[13px] leading-5 text-muted-foreground">
        <SettingsStatusMessage tone={statusTone}>{statusMessage}</SettingsStatusMessage>
      </div>
      <div className="flex w-full shrink-0 flex-wrap justify-end gap-2 sm:w-auto">
        {pendingRestart && !dirty && onRestart ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onRestart}
            disabled={isRestarting}
            className="rounded-full"
          >
            {isRestarting ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <RotateCcw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
            )}
            {isRestarting ? t("app.system.restarting") : t("app.system.restart")}
          </Button>
        ) : null}
        {onReset ? (
          <Button
            size="sm"
            variant="ghost"
            onClick={onReset}
            disabled={!dirty || saving}
            className="rounded-full"
          >
            {t("settings.actions.cancel")}
          </Button>
        ) : null}
        <Button
          size="sm"
          variant="outline"
          onClick={onSave}
          disabled={!dirty || disabled || saving}
          className="rounded-full"
        >
          {saving ? t("settings.actions.saving") : t("settings.actions.save")}
        </Button>
      </div>
    </div>
  );
}

function SettingsStatusMessage({
  children,
  tone,
}: {
  children?: ReactNode;
  tone?: "accent" | "danger";
}) {
  if (!children) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2",
        tone === "accent" && "font-medium text-blue-600 dark:text-blue-300",
        tone === "danger" && "font-medium text-destructive",
      )}
    >
      {tone ? (
        <span
          className={cn(
            "h-1.5 w-1.5 shrink-0 rounded-full",
            tone === "accent" &&
              "bg-blue-500 shadow-[0_0_0_3px_rgba(59,130,246,0.14)] dark:bg-blue-400 dark:shadow-[0_0_0_3px_rgba(96,165,250,0.18)]",
            tone === "danger" && "bg-destructive/70",
          )}
          aria-hidden
        />
      ) : null}
      <span>{children}</span>
    </span>
  );
}

function SegmentedControl({
  value,
  options,
  onChange,
}: {
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="inline-flex h-8 items-center rounded-full bg-muted p-0.5 text-[12px] font-medium text-muted-foreground">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          onClick={() => onChange(option.value)}
          className={cn(
            "rounded-full px-3 py-1 transition-colors",
            value === option.value && "bg-background text-foreground shadow-sm",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

function ToggleButton({
  checked,
  onChange,
  ariaLabel,
  label,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  ariaLabel?: string;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel ?? label}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative inline-flex h-[22px] w-[38px] shrink-0 items-center rounded-full p-[2px]",
        "transition-colors duration-200 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        checked
          ? "bg-[#2997FF] shadow-[inset_0_0_0_1px_rgba(0,0,0,0.035)]"
          : "bg-muted shadow-[inset_0_0_0_1px_rgba(0,0,0,0.035)] hover:bg-muted/80",
      )}
    >
      <span
        aria-hidden
        className={cn(
          "h-[18px] w-[18px] rounded-full bg-background shadow-[0_1px_2px_rgba(0,0,0,0.18),0_2px_7px_rgba(0,0,0,0.11)]",
          "transition-transform duration-200 ease-out",
          checked ? "translate-x-[16px]" : "translate-x-0",
        )}
      />
      <span className="sr-only">{label}</span>
    </button>
  );
}
