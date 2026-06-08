import { Bot, Folder, Menu, Moon, ShieldCheck, Sun, Terminal } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface ThreadHeaderProps {
  title: string;
  onToggleSidebar: () => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  hideThemeButton?: boolean;
  minimal?: boolean;
  workspaceLabel?: string | null;
  modelLabel?: string | null;
  permissionLabel?: string | null;
  sessionIdLabel?: string | null;
  promptNavigatorAction?: ReactNode;
  sessionInfoAction?: ReactNode;
}

export function ThreadHeader({
  title,
  onToggleSidebar,
  theme,
  onToggleTheme,
  hideThemeButton = false,
  minimal = false,
  workspaceLabel = null,
  modelLabel = null,
  permissionLabel = null,
  sessionIdLabel = null,
  promptNavigatorAction,
  sessionInfoAction,
}: ThreadHeaderProps) {
  const { t } = useTranslation();

  return (
    <div
      className={cn(
        "relative z-10 flex items-center justify-between gap-3 px-3 py-2",
        minimal && "h-11",
      )}
    >
      <div className="relative flex min-w-0 items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          aria-label={t("thread.header.toggleSidebar")}
          onClick={onToggleSidebar}
          className="h-7 w-7 rounded-md text-muted-foreground hover:bg-accent/35 hover:text-foreground"
        >
          <Menu className="h-3.5 w-3.5" />
        </Button>
        {!minimal ? (
          <div className="flex min-w-0 items-center gap-2">
            <div className="flex min-w-0 items-center rounded-md px-1.5 py-1 text-[12px] font-medium text-muted-foreground">
              <span className="max-w-[min(30vw,22rem)] truncate">{title}</span>
            </div>
            <div className="hidden min-w-0 items-center gap-1.5 md:flex">
              {workspaceLabel ? (
                <HeaderBadge icon={Folder} label={workspaceLabel} />
              ) : null}
              {modelLabel ? (
                <HeaderBadge icon={Bot} label={modelLabel} />
              ) : null}
              {permissionLabel ? (
                <HeaderBadge icon={ShieldCheck} label={permissionLabel} />
              ) : null}
              {sessionIdLabel ? (
                <HeaderBadge icon={Terminal} label={sessionIdLabel} />
              ) : null}
            </div>
          </div>
        ) : null}
      </div>

      <div className="ml-auto flex shrink-0 items-center gap-1">
        {sessionInfoAction}
        {promptNavigatorAction}
        {!hideThemeButton ? (
          <ThemeButton
            theme={theme}
            onToggleTheme={onToggleTheme}
            label={t("thread.header.toggleTheme")}
          />
        ) : null}
      </div>

      {!minimal ? (
        <div aria-hidden className="pointer-events-none absolute inset-x-0 top-full h-4" />
      ) : null}
    </div>
  );
}

function HeaderBadge({
  icon: Icon,
  label,
}: {
  icon: typeof Bot;
  label: string;
}) {
  return (
    <span className="inline-flex max-w-[11rem] items-center gap-1 rounded-full border border-border/45 bg-background/65 px-2 py-1 text-[11px] font-medium text-muted-foreground">
      <Icon className="h-3 w-3 shrink-0" aria-hidden />
      <span className="truncate">{label}</span>
    </span>
  );
}

function ThemeButton({
  theme,
  onToggleTheme,
  label,
  className,
}: {
  theme: "light" | "dark";
  onToggleTheme: () => void;
  label: string;
  className?: string;
}) {
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={label}
      onClick={onToggleTheme}
      className={cn(
        "h-8 w-8 rounded-full text-muted-foreground/85 hover:bg-accent/40 hover:text-foreground",
        className,
      )}
    >
      {theme === "dark" ? (
        <Sun className="h-4 w-4" />
      ) : (
        <Moon className="h-4 w-4" />
      )}
    </Button>
  );
}
