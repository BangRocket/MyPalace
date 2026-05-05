import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { hasAdminKey } from "./auth/storage";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Tenants } from "./pages/Tenants";
import { Keys } from "./pages/Keys";
import { Stats } from "./pages/Stats";
import { Audit } from "./pages/Audit";
import { Health } from "./pages/Health";
import { Memories } from "./pages/Memories";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  if (!hasAdminKey()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<Health />} />
        <Route path="tenants" element={<Tenants />} />
        <Route path="keys" element={<Keys />} />
        <Route path="stats" element={<Stats />} />
        <Route path="audit" element={<Audit />} />
        <Route path="memories" element={<Memories />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
