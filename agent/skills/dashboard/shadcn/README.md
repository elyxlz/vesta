# shadcn/ui component guide

The dashboard ships with shadcn/ui components. **Read this before building widgets.**

All components are already installed in `~/vesta/skills/dashboard/app/src/components/ui/`. Do NOT run the shadcn CLI — just import and use them.

## Principles

1. **Use existing components first.** Check `src/components/ui/` before writing custom markup.
2. **Compose, don't reinvent.** A stat card = Card + Badge. A settings widget = Tabs + form controls.
3. **Use built-in variants before custom styles.** `variant="outline"`, `size="sm"`, etc.
4. **Use semantic colors.** `bg-primary`, `text-muted-foreground` — never raw values like `bg-blue-500`.

## Critical Rules

### Styling & Tailwind → [rules/styling.md](./rules/styling.md)

- **`className` for layout, not styling.** Never override component colors or typography.
- **No `space-x-*` or `space-y-*`.** Use `flex` with `gap-*`. For vertical stacks, `flex flex-col gap-*`.
- **Use `size-*` when width and height are equal.** `size-10` not `w-10 h-10`.
- **Use `truncate` shorthand.** Not `overflow-hidden text-ellipsis whitespace-nowrap`.
- **No manual `dark:` color overrides.** Use semantic tokens (`bg-background`, `text-muted-foreground`).
- **Use `cn()` for conditional classes.** Import from `@/lib/utils`.
- **No manual `z-index` on overlay components.** Dialog, Sheet, Popover, etc. handle their own stacking.

### Forms & Inputs → [rules/forms.md](./rules/forms.md)

- **Forms use `FieldGroup` + `Field`.** Never use raw `div` with `space-y-*` for form layout.
- **`InputGroup` uses `InputGroupInput`/`InputGroupTextarea`.** Never raw `Input`/`Textarea` inside `InputGroup`.
- **Buttons inside inputs use `InputGroup` + `InputGroupAddon`.**
- **Option sets (2–7 choices) use `ToggleGroup`.** Don't loop `Button` with manual active state.
- **Field validation uses `data-invalid` + `aria-invalid`.**

### Component Structure → [rules/composition.md](./rules/composition.md)

- **Items always inside their Group.** `SelectItem` → `SelectGroup`. `DropdownMenuItem` → `DropdownMenuGroup`.
- **Dialog, Sheet, and Drawer always need a Title.** Use `className="sr-only"` if visually hidden.
- **Use full Card composition.** `CardHeader`/`CardTitle`/`CardDescription`/`CardContent`/`CardFooter`.
- **`Avatar` always needs `AvatarFallback`.** For when the image fails to load.

### Use Components, Not Custom Markup → [rules/composition.md](./rules/composition.md)

- **Callouts use `Alert`.** Don't build custom styled divs.
- **Empty states use `Empty`.** Don't build custom empty state markup.
- **Use `Separator`** instead of `<hr>` or `<div className="border-t">`.
- **Use `Skeleton`** for loading placeholders. No custom `animate-pulse` divs.
- **Use `Badge`** instead of custom styled spans.

### Icons → [rules/icons.md](./rules/icons.md)

- **Icons in `Button` use `data-icon`.** `data-icon="inline-start"` or `data-icon="inline-end"`.
- **No sizing classes on icons inside components.** Components handle icon sizing via CSS.

## Key Patterns

```tsx
// Form layout: FieldGroup + Field
<FieldGroup>
  <Field>
    <FieldLabel htmlFor="email">Email</FieldLabel>
    <Input id="email" />
  </Field>
</FieldGroup>

// Icons in buttons: data-icon, no sizing classes
<Button>
  <SearchIcon data-icon="inline-start" />
  Search
</Button>

// Spacing: gap-*, not space-y-*
<div className="flex flex-col gap-4">  // correct
<div className="space-y-4">           // wrong

// Equal dimensions: size-*, not w-* h-*
<Avatar className="size-10">   // correct
<Avatar className="w-10 h-10"> // wrong

// Status colors: Badge variants, not raw colors
<Badge variant="secondary">+20.1%</Badge>    // correct
<span className="text-emerald-600">+20.1%</span> // wrong
```

## Component Selection

| Need               | Use                                                            |
|--------------------|----------------------------------------------------------------|
| Button/action      | `Button` with appropriate variant                              |
| Form inputs        | `Input`, `Select`, `Combobox`, `Switch`, `Checkbox`, `Slider`  |
| Toggle options     | `ToggleGroup` + `ToggleGroupItem`                              |
| Data display       | `Table`, `Card`, `Badge`, `Avatar`                             |
| Overlays           | `Dialog`, `Sheet`, `Drawer`, `AlertDialog`                     |
| Feedback           | `Alert`, `Progress`, `Skeleton`, `Spinner`                     |
| Charts             | `Chart` (wraps Recharts)                                       |
| Layout             | `Card`, `Separator`, `ScrollArea`, `Accordion`, `Collapsible`  |
| Empty states       | `Empty`                                                        |
| Tooltips/info      | `Tooltip`, `HoverCard`, `Popover`                              |
| Tabs               | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`               |

## Detailed References

- [rules/forms.md](./rules/forms.md)
- [rules/composition.md](./rules/composition.md)
- [rules/icons.md](./rules/icons.md)
- [rules/styling.md](./rules/styling.md)
- [rules/base-vs-radix.md](./rules/base-vs-radix.md)
