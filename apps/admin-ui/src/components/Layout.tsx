import { NavLink, Outlet } from "react-router-dom";
import { clearAdminKey } from "../auth/storage";

const NAV = [
  { to: "/", label: "Health", end: true },
  { to: "/tenants", label: "Tenants" },
  { to: "/keys", label: "API Keys" },
  { to: "/stats", label: "Stats" },
  { to: "/audit", label: "Audit" },
  { to: "/memories", label: "Memories" },
];

export function Layout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-slate-900 text-slate-100 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <h1 className="text-lg font-semibold">MyPalace Admin</h1>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block px-3 py-2 rounded-md text-sm transition-colors ${
                  isActive
                    ? "bg-slate-700 text-white"
                    : "text-slate-300 hover:bg-slate-800 hover:text-white"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-slate-800">
          <button
            type="button"
            onClick={() => {
              clearAdminKey();
              window.location.href = "/admin/";
            }}
            className="w-full text-left px-3 py-2 rounded-md text-sm text-slate-300 hover:bg-slate-800 hover:text-white"
          >
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 p-6 overflow-x-auto">
        <Outlet />
      </main>
    </div>
  );
}
