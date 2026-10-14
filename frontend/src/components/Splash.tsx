// Opening animation: the plane flies in along its contrail, the bars rise, the wordmark
// settles letter by letter, then the plane takes off and the app is revealed.
// Click or press any key to skip. Reduced-motion users get a short fade.
import { useEffect, useState } from "react";
import { LogoMark, Tagline, Wordmark } from "./Logo";

const HOLD_MS = 2100;
const LEAVE_MS = 520;

export default function Splash() {
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [phase, setPhase] = useState<"show" | "leave" | "gone">("show");

  useEffect(() => {
    if (phase === "show") {
      const t = window.setTimeout(() => setPhase("leave"), reduce ? 350 : HOLD_MS);
      const skip = () => setPhase("leave");
      window.addEventListener("keydown", skip, { once: true });
      return () => { clearTimeout(t); window.removeEventListener("keydown", skip); };
    }
    if (phase === "leave") {
      const t = window.setTimeout(() => setPhase("gone"), LEAVE_MS);
      return () => clearTimeout(t);
    }
  }, [phase, reduce]);

  if (phase === "gone") return null;
  return (
    <div className={`splash ${phase === "leave" ? "is-leaving" : ""}`} onClick={() => setPhase("leave")} role="status" aria-label="Loading LeadPilot">
      <div className="relative flex flex-col items-center">
        <div className="splash-plane-wrap relative h-28 w-28">
          {/* contrail drawn along the same curve the plane follows */}
          <svg className="pointer-events-none absolute left-1/2 top-1/2 overflow-visible" width="1" height="1" aria-hidden>
            <path className="splash-trail" d="M -260 190 C -150 150, -90 40, 0 0" fill="none" stroke="url(#trail)" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="2 8" />
            <defs><linearGradient id="trail" x1="-260" y1="190" x2="0" y2="0" gradientUnits="userSpaceOnUse"><stop stopColor="#60a5fa" stopOpacity="0" /><stop offset="1" stopColor="#3b82f6" /></linearGradient></defs>
          </svg>
          <div className="splash-plane absolute left-0 top-0">
            <LogoMark size={112} animateBars />
          </div>
        </div>
        <Wordmark animate className="mt-5 text-5xl sm:text-6xl" />
        <Tagline className="splash-tag mt-3 text-base font-medium sm:text-lg" />
        <div className="mt-8 h-1 w-40 overflow-hidden rounded-full bg-[var(--c-line)]">
          <div className="splash-progress h-full rounded-full bg-gradient-to-r from-[#60a5fa] to-[#2563eb]" />
        </div>
      </div>
    </div>
  );
}
