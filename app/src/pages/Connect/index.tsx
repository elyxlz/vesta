import { Connect as ConnectContent } from "@/components/Connect";
import { Footer } from "@/components/Footer";

export function Connect() {
  return (
    <div className="flex flex-col flex-1 min-h-0 px-3 sm:px-5">
      <div className="flex-1 relative overflow-hidden min-h-0">
        <ConnectContent />
      </div>
      <div className="shrink-0">
        <Footer />
      </div>
    </div>
  );
}
