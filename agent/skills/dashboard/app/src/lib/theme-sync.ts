export function initThemeSync() {
  window.addEventListener("message", (event) => {
    if (event.data?.type === "vesta-theme") {
      document.documentElement.classList.toggle("dark", event.data.dark);
    }
  });

  // Request initial theme from parent
  window.parent.postMessage({ type: "vesta-theme-request" }, "*");
}
