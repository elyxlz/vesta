import { useState } from "react";
import { Textarea } from "@/components/ui/textarea";

interface FileEditorProps {
  initialContent: string;
  readonly: boolean;
  encoding: "utf-8" | "base64";
  onChange: (value: string) => void;
  placeholder?: string;
}

export function FileEditor({
  initialContent,
  readonly,
  encoding,
  onChange,
  placeholder,
}: FileEditorProps) {
  // Seed once from the loaded file; the parent remounts via key={path} per file,
  // and keeps the saved content in sync, so re-reading initialContent would only
  // fight the user's in-progress edits.
  const [value, setValue] = useState(initialContent);

  if (encoding === "base64") {
    return (
      <div className="flex h-full items-center justify-center bg-muted/40 text-sm text-muted-foreground">
        binary file, not editable
      </div>
    );
  }

  return (
    <Textarea
      value={value}
      readOnly={readonly}
      placeholder={placeholder}
      spellCheck={false}
      onChange={(e) => {
        setValue(e.target.value);
        onChange(e.target.value);
      }}
      className="field-sizing-fixed h-full resize-none rounded-none border-0 bg-transparent px-4 py-3 font-mono text-xs leading-relaxed shadow-none focus-visible:border-0 focus-visible:ring-0"
    />
  );
}
