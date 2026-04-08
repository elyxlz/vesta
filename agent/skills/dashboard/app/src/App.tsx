// To add widgets and other shadcn or custom components: import them above, then include them inside the div below.
// Example:
// import { Tabs, TabsList, TabsTrigger, TabsContent } from "./components/ui/tabs";
// import MyWidget from "./widgets/MyWidget";
// ...
// <Tabs defaultValue="social" className="w-[400px]">
// <TabsList>
//  <TabsTrigger value="social">social</TabsTrigger>
//  <TabsTrigger value="work">Work</TabsTrigger>
// </TabsList>
// <TabsContent value="social">
//  <MyWidget />
// </TabsContent>
// </Tabs>

import { LayoutDashboard } from "lucide-react";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "./components/ui/empty";
import { FadeScroll } from "./components/FadeScroll";

// --- Empty state toggle ---
// Set to false once custom code & widgets are added.
const SHOW_EMPTY_STATE = true;

const isFullscreen = new URLSearchParams(window.location.search).get("fullscreen") === "true";

export default function App() {
  if (SHOW_EMPTY_STATE) {
    return (
      <Empty className="flex-1 h-full w-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <LayoutDashboard />
          </EmptyMedia>
          <EmptyTitle>your dashboard</EmptyTitle>
          <EmptyDescription>
            ask your agent to set up the dashboard and add some widgets
          </EmptyDescription>
        </EmptyHeader>
      </Empty>
    );
  }

  return (
    <FadeScroll className="w-full h-full overflow-y-auto">
      <div className={`flex flex-col gap-4 pb-page ${isFullscreen ? "px-page" : "pr-4"}`}>
        {/* your custom code and widgets and other components goes here */}
      </div>
    </FadeScroll>
  );
}
