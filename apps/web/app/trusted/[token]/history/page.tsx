"use client";

import { useParams } from "next/navigation";
import { HistoryView } from "@/components/HistoryView";
import { Device } from "@/components/Device";

export default function HistoryPage() {
  const params = useParams<{ token: string }>();
  return (
    <Device>
      <HistoryView token={params.token} />
    </Device>
  );
}
