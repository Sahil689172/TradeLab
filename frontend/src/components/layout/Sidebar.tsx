interface SidebarProps {
  active: string;
}

const NAV_ITEMS = [
  { id: 'dashboard', label: 'Dashboard', icon: '▦' },
  { id: 'portfolio', label: 'Portfolio', icon: '◫', disabled: true },
  { id: 'orders', label: 'Orders', icon: '⇄', disabled: true },
  { id: 'strategies', label: 'Strategies', icon: '◈', disabled: true },
  { id: 'settings', label: 'Settings', icon: '⚙', disabled: true },
];

export function Sidebar({ active }: SidebarProps) {
  return (
    <aside className="flex w-14 flex-shrink-0 flex-col border-r border-terminal-border bg-terminal-panel md:w-52">
      <div className="flex h-12 items-center border-b border-terminal-border px-3 md:px-4">
        <span className="text-lg font-bold text-terminal-accent">TL</span>
        <span className="ml-2 hidden text-sm font-semibold tracking-wide md:inline">
          TradeLab
        </span>
      </div>
      <nav className="flex-1 space-y-1 p-2">
        {NAV_ITEMS.map((item) => {
          const isActive = item.id === active;
          return (
            <button
              key={item.id}
              type="button"
              disabled={item.disabled}
              className={`flex w-full items-center gap-3 rounded px-3 py-2 text-sm transition ${
                isActive
                  ? 'bg-terminal-accent/20 text-terminal-accent'
                  : item.disabled
                    ? 'cursor-not-allowed text-slate-600'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              <span className="font-mono text-base">{item.icon}</span>
              <span className="hidden md:inline">{item.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="border-t border-terminal-border p-3">
        <p className="hidden text-[10px] uppercase tracking-wider text-slate-600 md:block">
          Paper Trading
        </p>
      </div>
    </aside>
  );
}
