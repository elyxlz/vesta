import { Outlet } from "react-router-dom";
import { HomeNavbar } from "@/components/Navbar/HomeNavbar";
import { Footer } from "@/components/Footer";

export function HomeLayout() {
  return (
    <>
      <HomeNavbar />
      <Outlet />
      <Footer />
    </>
  );
}
