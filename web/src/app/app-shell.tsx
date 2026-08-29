import Image from "next/image";
import Link from "next/link";

import { SHELL_ROUTES, getShellRoute, type ShellRouteHref } from "@/lib/shell-routes";

import { BridgeStatus } from "./bridge-status";
import { ShellIcon } from "./shell-icon";

type AppShellProps = Readonly<{
  children: React.ReactNode;
  homeConsole?: boolean;
  route: ShellRouteHref;
}>;

export function AppShell({ children, homeConsole = false, route: routeHref }: AppShellProps) {
  const route = getShellRoute(routeHref);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>

      <aside className="sidebar" id="primary-navigation" aria-label="Primary navigation">
        <div className="sidebar-heading">
          <Link aria-label="Mentat home" className="brand" data-nav-link href="/">
            <Image
              alt=""
              className="brand-mark"
              height={42}
              src="/mentat-mark-emerald.png"
              unoptimized
              width={42}
            />
            <span className="brand-copy">
              <strong>Mentat</strong>
              <span>Planning workspace</span>
            </span>
          </Link>
          <button
            aria-label="Close navigation"
            className="icon-button sidebar-close"
            data-nav-close
            type="button"
          >
            <ShellIcon name="close" />
          </button>
        </div>

        <nav className="primary-nav">
          {SHELL_ROUTES.map((item) => (
            <Link
              aria-label={item.label}
              aria-current={item.href === routeHref ? "page" : undefined}
              className="nav-link"
              data-nav-link
              data-tooltip={item.label}
              href={item.href}
              key={item.href}
            >
              <ShellIcon name={item.icon} />
              <span className="nav-copy">
                <strong>{item.label}</strong>
                <span>{item.description}</span>
              </span>
            </Link>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="sidebar-footer-dot" aria-hidden="true" />
          <span className="sidebar-footer-copy">
            <strong>Local preview</strong>
            <span>Python keeps authority</span>
          </span>
        </div>
      </aside>

      <button
        aria-controls="primary-navigation"
        aria-expanded="true"
        aria-label="Collapse workspace navigation"
        className="rail-toggle sidebar-toggle"
        data-sidebar-toggle
        type="button"
      >
        <span aria-hidden="true" data-sidebar-toggle-icon>‹</span>
      </button>

      <div aria-hidden="true" className="nav-tooltip" data-nav-tooltip hidden />

      <button aria-label="Close navigation" className="nav-backdrop" data-nav-backdrop hidden type="button" />

      <div className="workspace" data-workspace>
        <header className="utility-bar">
          <div className="utility-context">
            <button
              aria-controls="primary-navigation"
              aria-expanded="false"
              aria-label="Open navigation"
              className="icon-button nav-open"
              data-nav-open
              type="button"
            >
              <ShellIcon name="menu" />
            </button>
            <span className="utility-route">{route.label}</span>
          </div>

          <div className="utility-actions">
            <BridgeStatus />
            <label className="contrast-control">
              <ShellIcon name="contrast" size={18} />
              <span>Contrast</span>
              <select aria-label="Contrast" defaultValue="system" data-contrast-select>
                <option value="system">System</option>
                <option value="standard">Standard</option>
                <option value="high">High</option>
              </select>
            </label>
          </div>
        </header>

        <main className={`main-content${homeConsole ? " main-content-console" : ""}`} id="main-content" tabIndex={-1}>
          {!homeConsole ? (
            <header className="route-heading">
              <p className="route-eyebrow">Mentat workspace</p>
              <h1>{route.label}</h1>
              <p>{route.description}</p>
            </header>
          ) : null}
          {children}
        </main>
      </div>
    </div>
  );
}
