import { Outlet } from "react-router-dom";
import { ConnectedNavbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";

export function HomeLayout() {
  return (
    <>
      <ConnectedNavbar
        center={
          <span className="text-3xl font-serif font-medium tracking-tight pointer-events-none">
            Vesta
          </span>
        }
      />
      <Outlet />
      <Footer />
    </>
  );
}
