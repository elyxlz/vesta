// Default coverage includes destinations and detailed interaction/error states.
// Explicit suite filters keep focused captures available without hiding coverage.
export function captureSelection(env = process.env) {
  const suite = env.VISUAL_SUITE || "all";
  if (!["pages", "states", "all"].includes(suite))
    throw new Error(`Unknown visual suite: ${suite}`);
  return { suite, page: env.VISUAL_PAGE || "" };
}

export function selectRegistry(registry, selection = captureSelection()) {
  const scenarios = registry.scenarios.filter((scenario) => {
    const isPage = typeof scenario.page === "string";
    return (
      (selection.suite === "all" ||
        (selection.suite === "pages" ? isPage : !isPage)) &&
      (!selection.page ||
        scenario.page === selection.page ||
        scenario.id === selection.page)
    );
  });
  if (selection.page && !scenarios.length)
    throw new Error(`No ${registry.family} page matches ${selection.page}`);
  return { ...registry, scenarios };
}
