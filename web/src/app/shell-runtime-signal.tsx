"use client";

import { useEffect } from "react";

const HYDRATED_EVENT = "mentat:shell-hydrated";

export function ShellRuntimeSignal() {
  useEffect(() => {
    document.documentElement.dataset.shellHydrated = "true";
    window.dispatchEvent(new Event(HYDRATED_EVENT));
  }, []);

  return null;
}
