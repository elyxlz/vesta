import { Connect as ConnectContent } from "@/components/Connect";
import { Footer } from "@/components/Footer";
import { Navbar } from "@/components/Navbar";

export function Connect() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center min-h-0">
      <Navbar />
      <ConnectContent />
      <Footer />
    </div>
  );
}
