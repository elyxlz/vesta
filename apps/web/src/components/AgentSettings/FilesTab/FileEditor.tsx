import { useEffect, useRef } from "react";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  highlightActiveLine,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  bracketMatching,
  defaultHighlightStyle,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import { javascript } from "@codemirror/lang-javascript";
import { python } from "@codemirror/lang-python";
import { markdown } from "@codemirror/lang-markdown";
import { json } from "@codemirror/lang-json";

interface FileEditorProps {
  path: string;
  initialContent: string;
  readonly: boolean;
  encoding: "utf-8" | "base64";
  onChange: (value: string) => void;
}

function langFor(path: string) {
  if (path.endsWith(".py")) return python();
  if (path.endsWith(".md")) return markdown();
  if (path.endsWith(".json")) return json();
  if (path.endsWith(".ts") || path.endsWith(".tsx")) {
    return javascript({ jsx: path.endsWith(".tsx"), typescript: true });
  }
  if (path.endsWith(".js") || path.endsWith(".jsx")) {
    return javascript({ jsx: path.endsWith(".jsx") });
  }
  return null;
}

export function FileEditor({
  path,
  initialContent,
  readonly,
  encoding,
  onChange,
}: FileEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const onChangeRef = useRef(onChange);

  useEffect(() => {
    onChangeRef.current = onChange;
  });

  useEffect(() => {
    if (encoding === "base64") return;
    const container = containerRef.current;
    if (!container) return;

    const extensions = [
      lineNumbers(),
      highlightActiveLine(),
      history(),
      bracketMatching(),
      indentOnInput(),
      syntaxHighlighting(defaultHighlightStyle),
      keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
      EditorState.readOnly.of(readonly),
      EditorView.editable.of(!readonly),
      EditorView.lineWrapping,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          onChangeRef.current(update.state.doc.toString());
        }
      }),
    ];
    const lang = langFor(path);
    if (lang) extensions.push(lang);

    const view = new EditorView({
      state: EditorState.create({ doc: initialContent, extensions }),
      parent: container,
    });

    return () => view.destroy();
  }, [path, initialContent, readonly, encoding]);

  if (encoding === "base64") {
    return (
      <div className="flex h-full items-center justify-center bg-muted/40 text-sm text-muted-foreground">
        binary file, not editable
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className="h-full min-h-0 overflow-auto bg-background font-mono text-xs"
    />
  );
}
