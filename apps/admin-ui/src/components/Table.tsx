import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

export function Table<T>({
  columns,
  rows,
  rowKey,
  empty = "(no rows)",
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
}) {
  if (rows.length === 0) {
    return (
      <div className="text-sm text-slate-500 italic px-4 py-8 text-center bg-white dark:bg-slate-900 rounded-md border border-slate-200 dark:border-slate-800">
        {empty}
      </div>
    );
  }
  return (
    <div className="overflow-x-auto bg-white dark:bg-slate-900 rounded-md border border-slate-200 dark:border-slate-800">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 dark:bg-slate-800/50 text-left">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-2 font-medium text-slate-600 dark:text-slate-400 ${
                  col.className ?? ""
                }`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
          {rows.map((row) => (
            <tr key={rowKey(row)} className="hover:bg-slate-50 dark:hover:bg-slate-800/50">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-4 py-2 align-top ${col.className ?? ""}`}
                >
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
