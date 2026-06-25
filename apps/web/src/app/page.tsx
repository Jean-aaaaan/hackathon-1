import { redirect } from "next/navigation";

// Root redirects to inbox (protected — middleware handles auth check)
export default function Home() {
  redirect("/inbox");
}
