import { useRef, useState, type ChangeEvent } from "react";
import { Image, Paperclip, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/Popover";

// The composer's attach entry: the Plus opens a small popover whose two options click hidden file
// inputs (the renderer's picker works identically in the browser and Electron, so no native
// bridge is involved). Picking is allowed while disconnected: the upload engine parks the draft
// as "waiting" and resumes on its own.
export function AttachMenu({
  disabled,
  onFiles,
}: {
  disabled: boolean;
  onFiles: (files: File[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const mediaInputRef = useRef<HTMLInputElement>(null);
  const anyInputRef = useRef<HTMLInputElement>(null);

  const handlePicked = (event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    // Reset so picking the same file twice re-fires change.
    event.target.value = "";
    if (files.length > 0) onFiles(files);
  };

  const pick = (input: HTMLInputElement | null) => {
    setOpen(false);
    input?.click();
  };

  const itemClass =
    "flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-sm hover:bg-accent";

  return (
    <>
      <input
        ref={mediaInputRef}
        type="file"
        accept="image/*,video/*"
        multiple
        hidden
        onChange={handlePicked}
        aria-label="pick photos and videos"
      />
      <input
        ref={anyInputRef}
        type="file"
        multiple
        hidden
        onChange={handlePicked}
        aria-label="pick a file"
      />
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            aria-label="add attachment"
            disabled={disabled}
            className="size-9 rounded-full text-muted-foreground [&_svg]:size-5"
          >
            <Plus />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" sideOffset={8} className="w-52 p-1.5">
          <button
            type="button"
            className={itemClass}
            onClick={() => {
              pick(mediaInputRef.current);
            }}
          >
            <Image className="size-4 text-muted-foreground" />
            photos & videos
          </button>
          <button
            type="button"
            className={itemClass}
            onClick={() => {
              pick(anyInputRef.current);
            }}
          >
            <Paperclip className="size-4 text-muted-foreground" />
            file
          </button>
        </PopoverContent>
      </Popover>
    </>
  );
}
