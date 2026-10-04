"use client";

import { useParams } from "next/navigation";
import { CrewView } from "@/components/CrewView";

export default function CrewPage() {
  const params = useParams<{ token: string }>();
  return <CrewView token={params.token} />;
}
