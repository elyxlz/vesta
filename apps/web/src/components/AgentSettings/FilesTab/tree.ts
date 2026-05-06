import type { FileTreeEntry } from "@/api/files";

export interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  children: TreeNode[];
}

export function buildTree(entries: FileTreeEntry[]): TreeNode {
  const root: TreeNode = {
    name: "/",
    path: "/",
    isDir: true,
    children: [],
  };
  const dirs = new Map<string, TreeNode>();
  dirs.set("/", root);

  const sorted = [...entries].sort((a, b) => a.path.localeCompare(b.path));

  for (const entry of sorted) {
    const segments = entry.path.split("/").filter(Boolean);
    if (segments.length === 0) continue;

    let parent = root;
    let currentPath = "";
    for (let i = 0; i < segments.length; i++) {
      const segment = segments[i];
      currentPath += `/${segment}`;
      const isLeaf = i === segments.length - 1;
      const isDir = isLeaf ? entry.is_dir : true;

      let node = dirs.get(currentPath);
      if (!node) {
        node = { name: segment, path: currentPath, isDir, children: [] };
        parent.children.push(node);
        if (isDir) dirs.set(currentPath, node);
      } else if (isLeaf && !entry.is_dir) {
        node.isDir = false;
      }
      parent = node;
    }
  }

  sortNode(root);
  return root;
}

function sortNode(node: TreeNode) {
  node.children.sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
    return a.name.localeCompare(b.name);
  });
  for (const child of node.children) {
    if (child.isDir) sortNode(child);
  }
}
