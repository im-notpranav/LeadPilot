import { Navigate, Route, Routes } from "react-router-dom";
import { LiveProvider } from "./lib/live";
import { RequireAuth } from "./lib/auth";
import Shell from "./components/Shell";
import Splash from "./components/Splash";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Queue from "./pages/Queue";
import Leads from "./pages/Leads";
import LeadDetail from "./pages/LeadDetail";
import Pipeline from "./pages/Pipeline";
import LiveFeed from "./pages/LiveFeed";
import Analytics from "./pages/Analytics";
import Quality from "./pages/Quality";
import Simulator from "./pages/Simulator";

export default function App() {
  return (
    <>
      <Splash />
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Login />} />
        <Route path="/" element={<RequireAuth><LiveProvider><Shell /></LiveProvider></RequireAuth>}>
          <Route index element={<Navigate to="/queue" replace />} />
          <Route path="queue" element={<Queue />} />
          <Route path="leads" element={<Leads />} />
          <Route path="leads/:id" element={<LeadDetail />} />
          <Route path="pipeline" element={<Pipeline />} />
          <Route path="feed" element={<LiveFeed />} />
          <Route path="analytics" element={<Analytics />} />
          <Route path="quality" element={<Quality />} />
          <Route path="simulator" element={<Simulator />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
