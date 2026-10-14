// Opening animation, about one second: the plane glides in on a short arc and settles over its bars,
// the name fades up, then the plane climbs out of frame as the app appears underneath.
// Only transforms and opacity are animated, so it stays smooth while the app mounts behind it.
// Click or press any key to skip. Reduced-motion users get a plain fade.
import { useEffect, useState } from "react";
import { LogoMark, Tagline, Wordmark } from "./Logo";

const HOLD_MS = 900;
const LEAVE_MS = 380;

export default function Splash() {
  const reduce = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const [phase, setPhase] = useState<"show" | "leave" | "gone">("show");

  useEffect(() => {
    if (phase === "show") {
      const t = window.setTimeout(() => setPhase("leave"), reduce ? 200 : HOLD_MS);
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
        <div className="relative h-28 w-28">
          {/* contrail behind the plane's approach; it flashes in and fades as the plane settles */}
          <svg className="splash-trail pointer-events-none absolute left-0 top-0 overflow-visible" width="1" height="1" aria-hidden>
            <defs><linearGradient id="splash-trail" x1="-170" y1="150" x2="18" y2="72" gradientUnits="userSpaceOnUse"><stop stopColor="#60a5fa" stopOpacity="0" /><stop offset="1" stopColor="#3b82f6" /></linearGradient></defs>
            <path d="M -170 150 C -110 136, -50 106, 18 72" fill="none" stroke="url(#splash-trail)" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="2 8" />
          </svg>
          <div className="splash-plane absolute inset-0">
            <LogoMark size={112} animateBars />
          </div>
        </div>
        <Wordmark animate className="mt-5 text-5xl sm:text-6xl" />
        <Tagline className="splash-tag mt-3 text-base font-medium sm:text-lg" />
      </div>
    </div>
  );
}
