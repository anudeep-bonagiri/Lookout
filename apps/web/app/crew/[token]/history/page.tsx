"use client";

import { useParams } from "next/navigation";
import { HistoryView } from "@/components/HistoryView";

export default function HistoryPage() {
  const params = useParams<{ token: string }>();
  return <HistoryView token={params.token} />;
}
