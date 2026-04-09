import { Connect as ConnectContent } from "@/components/Connect";
import { Footer } from "@/components/Footer";
import { Link } from "react-router-dom";

export function Connect() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center min-h-0">
      <Link to="/" className="absolute top-3 left-1/2 -translate-x-1/2">
        <h1 className="text-4xl font-serif font-medium tracking-tight">Vesta</h1>
      </Link>
      <ConnectContent />
      <Footer />
    </div>
  );
}
