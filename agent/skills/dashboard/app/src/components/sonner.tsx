// Dashboard-local sonner Toaster. It lives outside components/ui/ because that
// directory is a strict mirror of the main app's shadcn registry (scripts/
// sync-dashboard.sh rsync --delete), which would remove any extra file.
import { useTheme } from "next-themes";
import { Toaster as Sonner, type ToasterProps } from "sonner";
import {
  CircleCheckIcon,
  InfoIcon,
  TriangleAlertIcon,
  OctagonXIcon,
  Loader2Icon,
} from "lucide-react";

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = "system" } = useTheme();

  return (
    <Sonner
      theme={theme as ToasterProps["theme"]}
      // At sonner's 600px mobile breakpoint the toaster is width:100% anchored
      // at the left offset, which runs off the right edge; width:auto makes its
      // box symmetric between the offsets so a w-fit toast can center in it.
      className="toaster group max-[600px]:![width:auto]"
      icons={{
        success: <CircleCheckIcon className="size-4" />,
        info: <InfoIcon className="size-4" />,
        warning: <TriangleAlertIcon className="size-4" />,
        error: <OctagonXIcon className="size-4" />,
        loading: <Loader2Icon className="size-4 animate-spin" />,
      }}
      style={
        {
          "--normal-bg": "var(--popover)",
          "--normal-text": "var(--popover-foreground)",
          "--normal-border": "var(--border)",
          "--border-radius": "calc(infinity * 1px)",
          "--width": "20rem",
        } as React.CSSProperties
      }
      toastOptions={{
        classNames: {
          toast:
            "cn-toast !w-fit !min-w-[14rem] !max-w-[min(20rem,calc(100vw-2rem))] !justify-center !gap-1 !px-3.5 !py-2.5 max-[600px]:mx-auto",
          title: "!text-[13px] !font-medium",
          description: "!text-xs",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
