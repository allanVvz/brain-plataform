import { redirect } from "next/navigation";

export default function LegacyAssetsRedirect() {
  redirect("/marketing/assets");
}
