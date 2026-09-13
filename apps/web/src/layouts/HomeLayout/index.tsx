import { Outlet } from "react-router-dom";
import { HomeNavbar } from "@/components/Navbar/HomeNavbar";

export function HomeLayout() {
  return (
    <>
      <HomeNavbar />
      <Outlet />
    </>
  );
}
