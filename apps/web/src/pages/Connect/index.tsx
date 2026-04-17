import { Connect as ConnectContent } from "@/components/Connect";
import { Footer } from "@/components/Footer";
import { LogoText } from "@/components/Logo/LogoText";
import { Navbar } from "@/components/Navbar";
import { Link } from "react-router-dom";

export function Connect() {
  return (
    <div className="flex flex-col flex-1 items-center justify-center min-h-0">
      <Navbar
        center={
          <Link to="/">
            <LogoText />
          </Link>
        }
      />
      <ConnectContent />
      <Footer />
    </div>
  );
}
