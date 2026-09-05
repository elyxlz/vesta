import { Outlet } from "react-router-dom";
import { HomeNavbar } from "@/components/Navbar/HomeNavbar";
import { NewRoomDialog } from "@/components/NewRoomDialog";

export function HomeLayout() {
  return (
    <>
      <HomeNavbar />
      <Outlet />
      <NewRoomDialog />
    </>
  );
}
