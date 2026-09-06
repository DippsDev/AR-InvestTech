import type { Metadata } from "next";
import Purchase from "@/screens/Purchase";

export const metadata: Metadata = {
  title: "Purchase License · AR-InvestTech",
  description: "Request an ARI_Sniper_EA license key for the multi-symbol scalping system.",
};

export default function PurchasePage() {
  return <Purchase />;
}
