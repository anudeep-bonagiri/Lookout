"use client";

import { useParams } from "next/navigation";
import { CrewView } from "@/components/CrewView";
import { Device } from "@/components/Device";

export default function CrewPage() {
  const params = useParams<{ token: string }>();
  return (
    <Device>
      <CrewView token={params.token} />
    </Device>
  );
}
