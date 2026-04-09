import { Outlet } from "react-router-dom";
import { Navbar } from "@/components/Navbar";
import { Footer } from "@/components/Footer";

export function HomeLayout() {
  return (
    <>
      <Navbar
        center={
          <span className="text-4xl font-serif font-medium tracking-tight">
            Vesta
          </span>
        }
      />
      <Outlet />
      <Footer />
    </>
  );
}
