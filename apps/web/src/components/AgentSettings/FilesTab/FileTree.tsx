import { useState } from "react";
import { ChevronDown, ChevronRight, File, Folder } from "lucide-react";
import { cn } from "@/lib/utils";
import type { TreeNode } from "./tree";

interface FileTreeProps {
  root: TreeNode;
  selected: string | null;
  onSelect: (path: string) => void;
}

export function FileTree({ root, selected, onSelect }: FileTreeProps) {
  return (
    <ul className="font-mono text-xs">
      {root.children.map((child) => (
        <TreeItem
          key={child.path}
          node={child}
          selected={selected}
          onSelect={onSelect}
          depth={0}
          defaultOpen={shouldDefaultOpen(child)}
        />
      ))}
    </ul>
  );
}

const ALWAYS_OPEN_PATHS = new Set([
  "/root",
  "/root/agent",
  "/root/agent/skills",
]);

function shouldDefaultOpen(node: TreeNode): boolean {
  return ALWAYS_OPEN_PATHS.has(node.path);
}

interface TreeItemProps {
  node: TreeNode;
  selected: string | null;
  onSelect: (path: string) => void;
  depth: number;
  defaultOpen: boolean;
}

function TreeItem({
  node,
  selected,
  onSelect,
  depth,
  defaultOpen,
}: TreeItemProps) {
  const [open, setOpen] = useState(defaultOpen);
  const isSelected = selected === node.path;
  const indent = { paddingLeft: `${depth * 12 + 4}px` };

  if (node.isDir) {
    return (
      <li>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "flex w-full items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-muted",
          )}
          style={indent}
        >
          {open ? (
            <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
          )}
          <Folder className="size-3 shrink-0 text-muted-foreground" />
          <span className="truncate">{node.name}</span>
        </button>
        {open && (
          <ul>
            {node.children.map((child) => (
              <TreeItem
                key={child.path}
                node={child}
                selected={selected}
                onSelect={onSelect}
                depth={depth + 1}
                defaultOpen={shouldDefaultOpen(child)}
              />
            ))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(node.path)}
        className={cn(
          "flex w-full items-center gap-1 rounded px-1 py-0.5 text-left hover:bg-muted",
          isSelected && "bg-muted text-foreground",
        )}
        style={indent}
      >
        <span className="size-3 shrink-0" />
        <File className="size-3 shrink-0 text-muted-foreground" />
        <span className="truncate">{node.name}</span>
      </button>
    </li>
  );
}
