(function preloadMentatPreferences() {
  "use strict";

  var root = document.documentElement;
  var storageKey = "mentat-contrast-v1";
  var preference = "system";

  try {
    var stored = window.localStorage.getItem(storageKey);
    if (stored === "standard" || stored === "high") {
      preference = stored;
    }
  } catch {
    preference = "system";
  }

  var systemWantsHigh = false;
  try {
    systemWantsHigh = window.matchMedia("(prefers-contrast: more)").matches;
  } catch {
    systemWantsHigh = false;
  }

  root.dataset.uiShell = "emerald";
  root.dataset.contrastPreference = preference;
  root.dataset.contrast = preference === "high" || (preference === "system" && systemWantsHigh)
    ? "high"
    : "standard";
})();
