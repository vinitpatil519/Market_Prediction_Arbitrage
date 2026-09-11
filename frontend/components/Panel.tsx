import type { ReactNode } from "react";

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
  bodyClassName = "",
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={`flex min-h-0 flex-col rounded border border-terminal-line bg-terminal-panel ${className}`}
    >
      <header className="flex shrink-0 items-baseline justify-between gap-3 border-b border-terminal-line px-3 py-2">
        <div className="flex items-baseline gap-2 truncate">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-terminal-text">
            {title}
          </h2>
          {subtitle && (
            <span className="truncate text-[10px] text-terminal-muted">{subtitle}</span>
          )}
        </div>
        {right}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}

export function Metric({
  label,
  value,
  hint,
  color,
}: {
  label: string;
  value: string;
  hint?: string;
  color?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-[0.12em] text-terminal-muted">
        {label}
      </span>
      <span className="num text-base leading-none" style={color ? { color } : undefined}>
        {value}
      </span>
      {hint && <span className="text-[10px] text-terminal-muted">{hint}</span>}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return (
    <div className="flex h-full items-center justify-center p-6 text-center text-[11px] text-terminal-muted">
      {message}
    </div>
  );
}
