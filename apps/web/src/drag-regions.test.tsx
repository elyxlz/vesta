import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";

// The desktop drag-region dismissal rule in index.css matches open overlays
// with `body > [data-state="open"]` and `body > [data-radix-popper-content-wrapper]`,
// relying on Radix portals rendering them as direct body children (their
// internal Portal uses asChild). Pin that DOM shape across Radix upgrades.
describe("portaled overlay DOM shape (index.css drag-region rule)", () => {
  it("open dialog puts data-state=open elements directly under body", () => {
    render(
      <Dialog open>
        <DialogContent>
          <DialogTitle>probe</DialogTitle>
        </DialogContent>
      </Dialog>,
    );
    expect(
      document.querySelectorAll('body > [data-state="open"]').length,
    ).toBeGreaterThan(0);
  });

  it("open dropdown puts the popper wrapper directly under body", () => {
    render(
      <DropdownMenu open>
        <DropdownMenuContent>
          <DropdownMenuItem>probe</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>,
    );
    expect(
      document.querySelectorAll("body > [data-radix-popper-content-wrapper]")
        .length,
    ).toBeGreaterThan(0);
  });
});
