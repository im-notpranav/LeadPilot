import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { LiveProvider } from "./lib/live";
import { AuthProvider } from "./lib/auth";
import { ThemeProvider } from "./lib/theme";
import { AuthGate } from "./pages/Login";
import Splash from "./components/Splash";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 2000, refetchOnWindowFocus: false, retry: 1 } },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <Splash />
          <AuthProvider>
            <AuthGate>
              <LiveProvider>
                <App />
              </LiveProvider>
            </AuthGate>
          </AuthProvider>
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
