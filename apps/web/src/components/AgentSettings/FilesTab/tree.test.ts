import { describe, it, expect } from "vitest";
import { buildTree } from "./tree";

describe("buildTree", () => {
  it("returns an empty root for no entries", () => {
    const root = buildTree([]);
    expect(root.children).toEqual([]);
  });

  it("creates a single file at root", () => {
    const root = buildTree([
      { path: "/root/foo.txt", is_dir: false, mode: 0o644 },
    ]);
    expect(root.children).toHaveLength(1);
    expect(root.children[0].name).toBe("root");
    expect(root.children[0].isDir).toBe(true);
    expect(root.children[0].children).toHaveLength(1);
    expect(root.children[0].children[0]).toMatchObject({
      name: "foo.txt",
      path: "/root/foo.txt",
      isDir: false,
    });
  });

  it("nests files inside multiple directory levels", () => {
    const root = buildTree([
      { path: "/root/agent", is_dir: true, mode: 0o755 },
      { path: "/root/agent/data", is_dir: true, mode: 0o755 },
      { path: "/root/agent/data/x.json", is_dir: false, mode: 0o644 },
    ]);
    const rootDir = root.children[0];
    expect(rootDir.name).toBe("root");
    const agent = rootDir.children[0];
    expect(agent.name).toBe("agent");
    expect(agent.isDir).toBe(true);
    const data = agent.children[0];
    expect(data.name).toBe("data");
    expect(data.children[0]).toMatchObject({
      name: "x.json",
      path: "/root/agent/data/x.json",
      isDir: false,
    });
  });

  it("sorts directories before files at each level", () => {
    const root = buildTree([
      { path: "/root/zfile.txt", is_dir: false, mode: 0o644 },
      { path: "/root/a-dir/inner.txt", is_dir: false, mode: 0o644 },
      { path: "/root/m-dir/inner.txt", is_dir: false, mode: 0o644 },
      { path: "/root/afile.txt", is_dir: false, mode: 0o644 },
    ]);
    const names = root.children[0].children.map((n) => n.name);
    expect(names).toEqual(["a-dir", "m-dir", "afile.txt", "zfile.txt"]);
  });

  it("treats explicitly-listed directories as directories", () => {
    const root = buildTree([
      { path: "/root/agent/empty-dir", is_dir: true, mode: 0o755 },
    ]);
    const agent = root.children[0].children[0];
    const empty = agent.children[0];
    expect(empty.isDir).toBe(true);
    expect(empty.name).toBe("empty-dir");
  });
});
