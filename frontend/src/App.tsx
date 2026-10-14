import { Navigate, Route, Routes } from "react-router-dom";
import { useLive } from "./lib/live";
import { useAuth } from "./lib/auth";
import Shell, { visibleNav } from "./components/Shell";
import NotFound from "./pages/NotFound";
import Queue from "./pages/Queue";
import Leads from "./pages/Leads";
import Accounts from "./pages/Accounts";
import Account from "./pages/Account";
import Deal from "./pages/Deal";
import LeadDetail from "./pages/LeadDetail";
import Pipeline from "./pages/Pipeline";
import LiveFeed from "./pages/LiveFeed";
import Analytics from "./pages/Analytics";
import Quality from "./pages/Quality";
import Simulator from "./pages/Simulator";
import Access from "./pages/Access";
import Connectors from "./pages/Connectors";
import Import from "./pages/Import";

// Rendered only once AuthGate has a signed-in (or auth-off) user, so every route here is behind sign-in.
export default function App() {
  const { clock } = useLive();
  const { me } = useAuth();
  const nav = visibleNav(me, !!clock.live);
  const guard = (path: string, el: JSX.Element) => (nav.some((n) => n.to === path) ? el : <Navigate to="/queue" replace />);
  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/queue" replace />} />
      <Route path="/signup" element={<Navigate to="/queue" replace />} />
      <Route path="/" element={<Shell />}>
        <Route index element={<Navigate to="/queue" replace />} />
        <Route path="queue" element={<Queue />} />
        <Route path="leads" element={<Leads />} />
        <Route path="leads/:id" element={<LeadDetail />} />
        <Route path="pipeline" element={<Pipeline />} />
        <Route path="deals/:id" element={<Deal />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="accounts/:id" element={<Account />} />
        <Route path="feed" element={<LiveFeed />} />
        <Route path="analytics" element={guard("/analytics", <Analytics />)} />
        <Route path="quality" element={guard("/quality", <Quality />)} />
        <Route path="simulator" element={guard("/simulator", <Simulator />)} />
        <Route path="import" element={guard("/import", <Import />)} />
        <Route path="connectors" element={guard("/connectors", <Connectors />)} />
        <Route path="access" element={guard("/access", <Access />)} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}
