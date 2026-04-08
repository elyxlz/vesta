import { NewAgent as NewAgentContent } from "@/components/NewAgent";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";
import { UpdateBar } from "@/components/UpdateBar";

export function NewAgent() {
  return (
    <div className="flex flex-col flex-1 min-h-0 gap-3 px-page">
      <div className="shrink-0">
        <Navbar />
        <UpdateBar />
      </div>
      <div className="flex-1 relative overflow-hidden min-h-0">
        <NewAgentContent />
      </div>
      <div className="shrink-0">
        <Footer />
      </div>
    </div>
  );
}
