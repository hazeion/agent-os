import type { ShellIconName } from "@/lib/shell-routes";

type ShellIconProps = Readonly<{
  name: ShellIconName;
  size?: number;
}>;

export function ShellIcon({ name, size = 20 }: ShellIconProps) {
  const paths: Record<ShellIconName, React.ReactNode> = {
    home: (
      <>
        <path d="m3 11 9-8 9 8" />
        <path d="M5 10v10h14V10" />
        <path d="M9 20v-6h6v6" />
      </>
    ),
    agents: (
      <>
        <circle cx="12" cy="8" r="3.5" />
        <path d="M5.5 20a6.5 6.5 0 0 1 13 0" />
        <path d="M18.5 5.5 21 3M5.5 5.5 3 3" />
      </>
    ),
    tasks: (
      <>
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <path d="m8 9 1.5 1.5L12 8M14 9h3M8 15h9" />
      </>
    ),
    runs: (
      <>
        <path d="M8 5v14l11-7Z" />
        <path d="M4 4v16" />
      </>
    ),
    menu: (
      <>
        <path d="M4 7h16M4 12h16M4 17h16" />
      </>
    ),
    close: (
      <>
        <path d="m6 6 12 12M18 6 6 18" />
      </>
    ),
    contrast: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 3a9 9 0 0 1 0 18Z" />
      </>
    ),
  };

  return (
    <svg
      aria-hidden="true"
      className="shell-icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7">
        {paths[name]}
      </g>
    </svg>
  );
}
