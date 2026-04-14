import { Connect as ConnectContent } from "@/components/Connect";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Link } from "react-router-dom";

export function Connect() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center min-h-0">
      <Link to="/" className="absolute top-3 left-1/2 -translate-x-1/2">
        <LogoText />
      </Link>
      <ConnectContent />
      <Footer />
    </div>
  );
}
