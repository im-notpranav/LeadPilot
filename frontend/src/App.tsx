import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { LiveProvider } from "./lib/live";
import { RequireAuth } from "./lib/auth";
import Shell from "./components/Shell";
import Splash from "./components/Splash";
import Login from "./pages/Login";
import NotFound from "./pages/NotFound";
import Queue from "./pages/Queue";
import Leads from "./pages/Leads";
import Pipeline from "./pages/Pipeline";
import LiveFeed from "./pages/LiveFeed";
import Simulator from "./pages/Simulator";
import { Loading } from "./components/ui";

// The chart library is only used on these pages. Splitting them out keeps the first load (and the splash) fast;
// they are fetched in the background once the browser is idle, so opening them later doesn't wait on the network.
const loadLeadDetail = () => import("./pages/LeadDetail");
const loadAnalytics = () => import("./pages/Analytics");
const loadQuality = () => import("./pages/Quality");
const LeadDetail = lazy(loadLeadDetail);
const Analytics = lazy(loadAnalytics);
const Quality = lazy(loadQuality);
const idle = window.requestIdleCallback ?? ((cb: () => void) => window.setTimeout(cb, 1500));
idle(() => { loadLeadDetail(); loadAnalytics(); loadQuality(); });
const Deferred = ({ children }: { children: ReactNode }) => <Suspense fallback={<Loading />}>{children}</Suspense>;

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
          <Route path="leads/:id" element={<Deferred><LeadDetail /></Deferred>} />
          <Route path="pipeline" element={<Pipeline />} />
          <Route path="feed" element={<LiveFeed />} />
          <Route path="analytics" element={<Deferred><Analytics /></Deferred>} />
          <Route path="quality" element={<Deferred><Quality /></Deferred>} />
          <Route path="simulator" element={<Simulator />} />
        </Route>
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  );
}
